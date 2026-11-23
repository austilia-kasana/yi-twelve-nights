# -*- coding: utf-8 -*-
"""在真实游戏窗口里，按种子 17 的最优序列打一局，目标 S。

坐标约定（从源码布局推导，已验证）：
  客户端 (cx, cy) → 屏幕 (cx + 640, cy + 360)

  信卡 i        (404, 149 + i*90)       → 屏幕 (1044, 509 + i*90)
  骑手 i        (910, 128 + i*62)       → 屏幕 (1550, 488 + i*62)
  马 i（n 骑手） (910, 156 + n*62 + i*62) → 屏幕 (1550, 516 + n*62 + i*62)
  送出今夜       (1163, 678)             → 屏幕 (1803, 1038)
  整备           (1163, 625)             → 屏幕 (1803, 985)
  商店第 i 行（n 行） x=1280, y = 720 - 23n + 46i
  关商店          点面板外（700, 400）

序列来自 tools/ai_optimal.py 的 Human 策略（只看预报）跑种子 17 的结果。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time

user32 = ctypes.windll.user32

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

# 屏幕偏移（客户端原点）
OX, OY = 640, 360


def click(sx, sy, delay=0.22):
    user32.SetCursorPos(int(sx), int(sy))
    time.sleep(0.055)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.04)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(delay)


def click_client(cx, cy, delay=0.22):
    click(cx + OX, cy + OY, delay)


def click_dispatch(i):
    click_client(404, 149 + i * 90)
    print("    信 #%d" % i)


def click_rider(i):
    click_client(910, 128 + i * 62)
    print("    骑手 #%d" % i)


def click_horse(i, n_riders):
    click_client(910, 156 + n_riders * 62 + i * 62)
    print("    马 #%d（%d 骑手）" % (i, n_riders))


def click_send():
    click_client(1163, 678, 0.55)
    print("    → 送出")


def click_shop():
    click_client(1163, 625, 0.55)
    print("    → 整备")


def click_shop_row(i, n_rows):
    y = 720 - 23 * n_rows + 46 * i
    click(1280, y, 0.4)
    print("    商店行 %d（共 %d 行, y=%d）" % (i, n_rows, y))


def close_shop():
    click(700, 400, 0.45)
    print("    → 关闭商店")


# ────────────────────────── 种子 17 的最优序列 ──────────────────────────
# 每夜: (n_riders, [(didx, ridx, hidx), ...], [shop_row, ...], n_horses)
# shop_row: 0=添油 1=雇 2=买马 3=喂马0 4=喂马1 5=喂马2
PLAN = [
    # 夜,  骑手数, 派单,                商店行,   马数
    (1,  2, [(2, 0, 0)],                [1],       2),   # 雇小六
    (2,  3, [(3, 0, 0)],                [3],       2),   # 喂乌蹄
    (3,  3, [(4, 1, 0)],                [],        2),
    (4,  3, [(1, 0, 0), (3, 1, 1)],     [1],       2),   # 雇阿桃
    (5,  4, [(2, 2, 1)],                [],        2),
    (6,  4, [(0, 0, 0), (2, 1, 1)],     [3],       2),   # 喂乌蹄
    (7,  4, [(2, 3, 1)],                [4],       2),   # 喂灰耳
    (8,  4, [(2, 1, 1), (3, 0, 0)],     [0, 4],    2),   # 添油+喂灰耳
    (9,  4, [(2, 0, 0)],                [3],       2),   # 喂乌蹄
    (10, 4, [(1, 1, 0)],                [3, 2],    2),   # 喂乌蹄+买踏雪
    (11, 4, [(0, 0, 0)],                [],        3),
    (12, 4, [(2, 1, 0)],                [],        3),
]


def main():
    print("=" * 60)
    print("按种子 17 最优序列打一局")
    print("=" * 60)

    p = subprocess.Popen(
        [sys.executable, "main.py", "--seed", "17"],
        cwd=r"C:\Users\19536\AI\games\relay")
    time.sleep(9)

    # 找窗口并置前
    hwnd = user32.FindWindowW(None, "驿 · 十二夜")
    if not hwnd:
        print("❌ 找不到窗口")
        return 1
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(1)
    print("窗口已就绪 hwnd=%s" % hwnd)

    # 入夜
    click_client(640, 494, 1.2)
    print("→ 入夜\n")

    for (night, n_r, dispatches, shop, n_h) in PLAN:
        print("第 %d 夜" % night)
        for (di, ri, hi) in dispatches:
            click_dispatch(di)
            click_rider(ri)
            click_horse(hi, n_r)
        click_send()
        if shop:
            n_rows = 3 + n_h
            click_shop()
            for row in shop:
                click_shop_row(row, n_rows)
            close_shop()
        print()

    print("=" * 60)
    print("12 夜打完，等结算")
    time.sleep(3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
