# -*- coding: utf-8 -*-
"""打包脚本：把游戏打成单个 exe。

用法：
    python build.py            # 打包
    python build.py --clean    # 先清掉旧的 build/dist

产物：dist/驿.exe
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "驿"
ENTRY = os.path.join(HERE, "main.py")
ICON = os.path.join(HERE, "relay", "assets", "icon.ico")


def make_icon():
    """从标题图裁一个 ico。没有 Pillow 就跳过。"""
    if os.path.exists(ICON):
        return True
    try:
        from PIL import Image
    except Exception:
        print("  [跳过] 没有 Pillow，不出图标")
        return False
    art_dir = os.path.join(HERE, "relay", "assets", "art")
    cands = [f for f in os.listdir(art_dir)
             if f.startswith("title_") and f.endswith(".png")] if os.path.isdir(art_dir) else []
    if not cands:
        print("  [跳过] 找不到标题图，不出图标")
        return False
    cands.sort()
    src = os.path.join(art_dir, cands[-1])
    try:
        im = Image.open(src).convert("RGB")
        w, h = im.size
        s = min(w, h)
        # 取偏中间偏上的方块（屋子和月亮都在那）
        left = (w - s) // 2
        top = max(0, (h - s) // 3)
        im = im.crop((left, top, left + s, top + s))
        sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
        im.save(ICON, format="ICO", sizes=sizes)
        print("  图标已生成: %s" % ICON)
        return True
    except Exception as e:
        print("  [跳过] 图标生成失败: %s" % e)
        return False


def clean():
    for d in ("build", "dist"):
        p = os.path.join(HERE, d)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
            print("  已删除 %s" % d)
    spec = os.path.join(HERE, NAME + ".spec")
    if os.path.exists(spec):
        os.remove(spec)
        print("  已删除 %s.spec" % NAME)


def build(onefile=True, windowed=True):
    assets = os.path.join(HERE, "relay", "assets")
    if not os.path.isdir(assets):
        print("❌ 找不到素材目录: %s" % assets)
        return 1

    art = os.path.join(assets, "art")
    n_art = len([f for f in os.listdir(art) if f.endswith(".png")]) if os.path.isdir(art) else 0
    sfx = os.path.join(assets, "sfx")
    n_sfx = len([f for f in os.listdir(sfx) if f.endswith(".wav")]) if os.path.isdir(sfx) else 0
    print("  素材: 美术 %d 张，音效 %d 个" % (n_art, n_sfx))
    if n_art < 20:
        print("  ⚠ 美术不全（%d/20），打包后缺的会用替身图" % n_art)

    need_icon = make_icon()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name", NAME,
        "--add-data", "%s%srelay/assets" % (assets, os.pathsep),
        "--hidden-import", "numpy",
        "--hidden-import", "relay.core.sim",
        "--hidden-import", "relay.ui.app",
        "--hidden-import", "relay.audio.player",
    ]
    if onefile:
        cmd.append("--onefile")
    if windowed:
        cmd.append("--windowed")
    if need_icon:
        cmd += ["--icon", ICON]
    cmd.append(ENTRY)

    print()
    print("执行: %s" % " ".join(cmd[:6] + ["..."]))
    print()
    r = subprocess.run(cmd, cwd=HERE)
    if r.returncode != 0:
        print("❌ 打包失败，返回码 %d" % r.returncode)
        return r.returncode

    out = os.path.join(HERE, "dist", NAME + ".exe")
    if os.path.exists(out):
        size = os.path.getsize(out) / 1024 / 1024
        print()
        print("=" * 56)
        print(" 打包完成")
        print(" 产物: %s" % out)
        print(" 体积: %.1f MB" % size)
        print("=" * 56)
        return 0
    print("❌ 没找到产物")
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--onedir", action="store_true", help="打成目录而不是单文件")
    ap.add_argument("--console", action="store_true", help="保留控制台窗口（调试用）")
    args = ap.parse_args()

    if args.clean:
        clean()
        if len(sys.argv) == 2:
            return 0

    return build(onefile=not args.onedir, windowed=not args.console)


if __name__ == "__main__":
    sys.exit(main())
