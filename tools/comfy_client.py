# -*- coding: utf-8 -*-
"""ComfyUI 极简客户端 + 出图测试。

ComfyUI API 三步：
  1) POST /prompt  {prompt: <工作流图>, client_id}
  2) 轮询 GET /history/<prompt_id> 直到出现 outputs
  3) GET /view?filename=...&subfolder=...&type=output  下载 PNG

用法：
  python comfy_client.py --test          # 出 3 张测试图
  python comfy_client.py --prompt "..." --out x.png
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid

HOST = "http://127.0.0.1:8188"
CLIENT_ID = "relay-art-" + uuid.uuid4().hex[:8]


def _post(path, payload, timeout=30):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        HOST + path, data=data,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path, timeout=30):
    with urllib.request.urlopen(HOST + path, timeout=timeout) as r:
        return r.read()


def queue_prompt(workflow: dict) -> str:
    d = _post("/prompt", {"prompt": workflow, "client_id": CLIENT_ID})
    if "prompt_id" not in d:
        raise RuntimeError("排队失败: %s" % json.dumps(d, ensure_ascii=False)[:500])
    return d["prompt_id"]


def wait_history(prompt_id: str, timeout=600, poll=1.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        raw = _get("/history/" + prompt_id, timeout=20)
        if raw:
            d = json.loads(raw.decode("utf-8"))
            if prompt_id in d:
                return d[prompt_id]
        time.sleep(poll)
    raise TimeoutError("出图超时（%.0f 秒）" % timeout)


def download_images(hist: dict, out_dir: str, prefix: str = "img") -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for node_id, node_out in (hist.get("outputs") or {}).items():
        for img in node_out.get("images", []):
            q = urllib.parse.urlencode({
                "filename": img["filename"],
                "subfolder": img.get("subfolder", ""),
                "type": img.get("type", "output"),
            })
            raw = _get("/view?" + q, timeout=60)
            p = os.path.join(out_dir, "%s_%s" % (prefix, img["filename"]))
            with open(p, "wb") as f:
                f.write(raw)
            paths.append(p)
    return paths


# ────────────────────────── 工作流构造 ──────────────────────────
def sdxl_workflow(prompt: str, negative: str, width: int, height: int,
                  steps: int, cfg: float, seed: int,
                  ckpt: str = "RealVisXL_V4.0.safetensors",
                  sampler: str = "dpmpp_2m", scheduler: str = "karras") -> dict:
    """标准 SDXL txt2img 图。"""
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {
                  "seed": seed, "steps": steps, "cfg": cfg,
                  "sampler_name": sampler, "scheduler": scheduler,
                  "denoise": 1.0,
                  "model": ["1", 0], "positive": ["2", 0],
                  "negative": ["3", 0], "latent_image": ["4", 0],
              }},
        "6": {"class_type": "VAEDecode",
              "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"images": ["6", 0], "filename_prefix": "relay"}},
    }


NEG_DEFAULT = (
    "text, watermark, signature, logo, lowres, blurry, jpeg artifacts, "
    "deformed, bad anatomy, extra limbs, modern buildings, cars, "
    "electricity, wires, anime, cartoon, oversaturated, neon"
)


def gen(prompt: str, out_dir: str, name: str, negative: str = NEG_DEFAULT,
        width=1024, height=1024, steps=26, cfg=6.0, seed=12345,
        ckpt="RealVisXL_V4.0.safetensors", quiet=False) -> list[str]:
    wf = sdxl_workflow(prompt, negative, width, height, steps, cfg, seed, ckpt)
    t0 = time.time()
    pid = queue_prompt(wf)
    hist = wait_history(pid)
    paths = download_images(hist, out_dir, prefix=name)
    if not quiet:
        print("  %-28s %5.1fs  %s" % (name, time.time() - t0,
                                      os.path.basename(paths[0]) if paths else "无输出"))
    return paths


# ────────────────────────── 自测 ──────────────────────────
def selftest():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_test")
    print("=== ComfyUI 连通性 ===")
    try:
        raw = _get("/system_stats", timeout=10)
        d = json.loads(raw.decode("utf-8"))
        s = d.get("system", {})
        print("  OK  ComfyUI %s  RAM free %.1f GB" % (
            s.get("comfyui_version"), s.get("ram_free", 0) / 1024**3))
        for dv in d.get("devices", []):
            print("  GPU %s  VRAM free %.2f / %.2f GB" % (
                dv.get("name", "?"),
                dv.get("vram_free", 0) / 1024**3,
                dv.get("vram_total", 0) / 1024**3))
    except Exception as e:
        print("  连接失败: %s" % e)
        return 1

    print()
    print("=== 出图测试（3 张，看风格合不合适）===")
    tests = [
        ("landscape_pass",
         "Chinese ink wash painting blended with moody oil painting, "
         "a narrow mountain pass at night in winter, steep dark cliffs "
         "on both sides, heavy snow falling, a single tiny warm lantern "
         "glow far in the distance, deep indigo and charcoal palette, "
         "muted, atmospheric, painterly brushwork, cinematic wide shot, "
         "no people, 19th century Chinese northern frontier",
         1344, 768),
        ("station_house",
         "Traditional Chinese relay station house on a mountain ridge at dusk, "
         "dark timber and grey tile roof, one warm lit paper window, "
         "snow on the roof, bare pine trees, distant layered mountain silhouettes, "
         "ink wash and oil painting hybrid, muted indigo and amber, "
         "lonely, quiet, painterly, no people",
         1024, 1024),
        ("courier_portrait",
         "Portrait of a weathered Chinese courier in his thirties, "
         "wearing a thick dark cotton winter coat and a fur hat, "
         "snow on his shoulders, tired determined eyes, "
         "holding a sealed bamboo message tube, "
         "painterly oil and ink wash style, muted palette, "
         "dark background, soft rim light, three quarter view",
         832, 1024),
    ]
    for name, prompt, w, h in tests:
        try:
            gen(prompt, out, name, width=w, height=h)
        except Exception as e:
            print("  %-28s 失败: %s" % (name, e))
    print()
    print("输出目录: %s" % out)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--prompt")
    ap.add_argument("--out", default="out.png")
    ap.add_argument("--ckpt", default="RealVisXL_V4.0.safetensors")
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--steps", type=int, default=26)
    ap.add_argument("--cfg", type=float, default=6.0)
    args = ap.parse_args()

    if args.test:
        sys.exit(selftest())

    if args.prompt:
        d = os.path.dirname(os.path.abspath(args.out)) or "."
        base = os.path.splitext(os.path.basename(args.out))[0]
        paths = gen(args.prompt, d, base, width=args.width, height=args.height,
                    steps=args.steps, cfg=args.cfg, seed=args.seed, ckpt=args.ckpt)
        for p in paths:
            print(p)
        return

    ap.print_help()


if __name__ == "__main__":
    main()
