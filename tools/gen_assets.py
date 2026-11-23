# -*- coding: utf-8 -*-
"""《驿 · 十二夜》全套素材生成器。

美术方向（两族，各有稳定风格前缀）：
  A. 场景族 —— 水彩 + 水墨，冷靛蓝 + 暖琥珀，纸纹，留白多
  B. 人物族 —— 厚涂写实，暖褐灰，暗背景，边缘柔光

所有图统一：RealVisXL_V4.0，dpmpp_2m/karras，cfg 6.0，固定 seed 基址。
这样 20 多张出图能保持一个整体感。

用法：
  python gen_assets.py                 # 出全部（跳过已存在的）
  python gen_assets.py --only title    # 只出指定 id
  python gen_assets.py --force         # 重出已有
  python gen_assets.py --list          # 列出清单
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comfy_client import gen  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "relay", "assets", "art")

# ────────────────────────── 风格前缀 ──────────────────────────
SCENE = (
    "traditional Chinese watercolor and ink wash illustration, "
    "cold indigo and warm amber palette, soft handmade paper texture, "
    "delicate brush outlines, generous negative space, quiet melancholic atmosphere, "
    "limited muted color, hand painted, visible paper grain, "
    "no text, no lettering, no signature, no border, "
)

PORTR = (
    "painterly realistic portrait, thick brushwork, warm sepia and slate grey palette, "
    "dark vignetted background, soft rim light from one side, "
    "muted desaturated color, film grain, hand painted, "
    "no text, no lettering, no signature, no frame, "
)

NEG_SCENE = (
    "text, watermark, signature, letters, chinese characters, calligraphy, "
    "logo, frame, border, modern, photo, 3d render, cgi, anime, cartoon, "
    "oversaturated, neon, busy composition, people in foreground, "
    "lowres, blurry, jpeg artifacts, deformed"
)

NEG_PORTR = (
    "text, watermark, signature, letters, chinese characters, calligraphy, "
    "logo, frame, border, multiple people, extra limbs, extra fingers, "
    "deformed face, asymmetric eyes, anime, cartoon, 3d render, "
    "oversaturated, neon, lowres, blurry, jpeg artifacts"
)

# ────────────────────────── 素材清单 ──────────────────────────
# (id, prompt_body, width, height, seed, family)
ASSETS = [
    # ---- 大图 / 背景 ----
    ("title",
     "a lone relay station house on a snowy mountain pass at deep night, "
     "one small warm lit window, a vast dark sky with a thin crescent moon, "
     "snow falling softly, layered mountain silhouettes fading into mist, "
     "seen from a distance, the house very small against the mountains",
     1536, 864, 1101, "scene"),

    ("main_bg",
     "a snowy mountain valley at night seen from a relay station courtyard, "
     "dark cliffs on both sides framing a narrow pass, distant faint lantern light, "
     "bare pine trees, deep indigo sky with scattered stars, "
     "wide empty composition with space in the middle for interface",
     1536, 864, 1102, "scene"),

    ("ending_good",
     "dawn breaking over a snowy mountain pass, warm golden light spilling over "
     "the ridge, a small relay station with smoke from the chimney, "
     "the road clear and quiet, calm and hopeful",
     1536, 864, 1103, "scene"),

    ("ending_bad",
     "a relay station abandoned in heavy snow at night, windows dark, "
     "door ajar, snow drifting against the walls, no light anywhere, "
     "cold and desolate, mountains lost in the storm",
     1536, 864, 1104, "scene"),

    # ---- 三条路线 ----
    ("route_north",
     "a narrow steep mountain pass between two dark rock walls, "
     "snow and loose stones on the path, wind blowing snow across, "
     "a single thin trail winding upward, cold blue shadow",
     768, 1024, 1201, "scene"),

    ("route_ford",
     "a wide shallow river crossing at night, stepping stones half submerged, "
     "swollen dark water, reeds bent by wind, mist over the surface, "
     "the far bank barely visible",
     768, 1024, 1202, "scene"),

    ("route_mine",
     "an old abandoned mine tunnel entrance in a hillside, "
     "timber supports leaning, dark opening, a faint lantern glow inside, "
     "rubble and broken rails, still air, no weather",
     768, 1024, 1203, "scene"),

    # ---- 天气图标（小方块，正方形）----
    ("wx_clear",
     "small square vignette of a clear winter night sky, "
     "a thin crescent moon and a few bright stars, deep indigo, "
     "snow-covered ridge at the very bottom", 512, 512, 1301, "scene"),
    ("wx_cloud",
     "small square vignette of heavy low clouds over a snowy ridge, "
     "no moon visible, grey blue tones, still air", 512, 512, 1302, "scene"),
    ("wx_rain",
     "small square vignette of cold rain falling over a dark ridge, "
     "wet stone, thin diagonal rain streaks, slate grey", 512, 512, 1303, "scene"),
    ("wx_snow",
     "small square vignette of soft snow falling over a mountain ridge, "
     "large slow flakes, pale blue white, quiet", 512, 512, 1304, "scene"),
    ("wx_storm",
     "small square vignette of a violent blizzard, "
     "white out, wind-driven snow, barely visible ridge, "
     "harsh and cold", 512, 512, 1305, "scene"),

    # ---- 骑手立绘（四种气质）----
    ("rider_old",
     "portrait of an older Chinese courier in his fifties, weathered deeply lined face, "
     "grey stubble, calm steady eyes, thick dark padded winter coat with fur collar, "
     "snow melting on his shoulders, looking slightly off camera",
     768, 1024, 1401, "portrait"),
    ("rider_young",
     "portrait of a young Chinese courier around twenty, "
     "sharp alert eyes, wind-burnt cheeks, short black hair under a wool cap, "
     "dark blue cotton coat, scarf pulled up, eagerness and nerves",
     768, 1024, 1402, "portrait"),
    ("rider_woman",
     "portrait of a Chinese woman courier in her late twenties, "
     "hair tied back tightly, composed determined expression, "
     "dark quilted jacket, leather gloves, a folded message tucked at her collar, "
     "quiet confidence",
     768, 1024, 1403, "portrait"),
    ("rider_scar",
     "portrait of a Chinese courier with a long old scar across one cheek, "
     "gaunt face, hard flat stare, heavy sheepskin coat, "
     "a rope belt, snow in his hair, unsmiling",
     768, 1024, 1404, "portrait"),

    # ---- 马 ----
    ("horse_dark",
     "portrait of a dark bay Chinese frontier horse, thick winter coat, "
     "breath steaming in cold air, snow on its back, side view head and shoulders",
     896, 768, 1501, "portrait"),
    ("horse_grey",
     "portrait of a grey dappled Chinese frontier horse, shaggy winter coat, "
     "calm eye, frost on its muzzle, side view head and shoulders",
     896, 768, 1502, "portrait"),

    # ---- 纹理 ----
    ("paper",
     "seamless texture of aged handmade Chinese paper, "
     "warm off-white, subtle fibers and faint stains, no pattern, "
     "flat even lighting, full frame texture",
     1024, 1024, 1601, "scene"),
    ("lacquer",
     "seamless texture of old dark lacquered wood, "
     "near black with faint warm brown grain, worn edges, "
     "flat even lighting, full frame texture",
     1024, 1024, 1602, "scene"),
]

FAMILY = {
    "scene": (SCENE, NEG_SCENE),
    "portrait": (PORTR, NEG_PORTR),
}


def output_path(asset_id: str) -> str:
    return os.path.join(OUT, asset_id + ".png")


def run(only=None, force=False, seed_offset=0):
    os.makedirs(OUT, exist_ok=True)
    todo = []
    for a in ASSETS:
        aid, body, w, h, seed, fam = a
        if only and aid not in only:
            continue
        if not force and os.path.exists(output_path(aid)):
            continue
        todo.append(a)

    if not todo:
        print("没有需要生成的素材。")
        return 0

    total = len(todo)
    print("待生成 %d 张，输出到 %s" % (total, OUT))
    print()
    t_all = time.time()
    ok = 0
    for i, (aid, body, w, h, seed, fam) in enumerate(todo, 1):
        style, neg = FAMILY[fam]
        prompt = style + body
        t0 = time.time()
        try:
            paths = gen(prompt, OUT, aid, negative=neg,
                        width=w, height=h, steps=26, cfg=6.0,
                        seed=seed + seed_offset, quiet=True)
            if paths:
                ok += 1
                print("  [%2d/%2d] %-14s %5.1fs  %dx%d" % (
                    i, total, aid, time.time() - t0, w, h))
            else:
                print("  [%2d/%2d] %-14s 无输出" % (i, total, aid))
        except Exception as e:
            print("  [%2d/%2d] %-14s 失败: %s" % (i, total, aid, str(e)[:120]))

    print()
    print("完成 %d/%d，总计 %.1f 分钟" % (ok, total, (time.time() - t_all) / 60))
    return 0 if ok == total else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="只出这些 id")
    ap.add_argument("--force", action="store_true", help="重出已存在的")
    ap.add_argument("--list", action="store_true", help="列出清单")
    ap.add_argument("--seed-offset", type=int, default=0)
    args = ap.parse_args()

    if args.list:
        print("%-14s %-10s %6s  %s" % ("id", "family", "尺寸", "状态"))
        for aid, body, w, h, seed, fam in ASSETS:
            st = "已存在" if os.path.exists(output_path(aid)) else "待生成"
            print("%-14s %-10s %6s  %s" % (aid, fam, "%dx%d" % (w, h), st))
        print()
        print("共 %d 项" % len(ASSETS))
        return

    sys.exit(run(only=set(args.only) if args.only else None,
                 force=args.force, seed_offset=args.seed_offset))


if __name__ == "__main__":
    main()
