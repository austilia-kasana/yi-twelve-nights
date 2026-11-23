# -*- coding: utf-8 -*-
"""视觉主题：颜色、字体、尺寸。

所有颜色都从「驿站」的调子里取：夜蓝、灯橙、雪白、旧木、朱砂。
"""

from __future__ import annotations

import math
import os

import pygame

# ────────────────────────── 画布 ──────────────────────────
WIDTH = 1280
HEIGHT = 720
FPS = 60
TITLE = "驿 · 十二夜"

# ────────────────────────── 颜色 ──────────────────────────
# 夜
NIGHT = (14, 22, 32)
NIGHT_2 = (20, 30, 42)
NIGHT_3 = (28, 40, 54)
INK = (10, 15, 22)

# 灯
LAMP = (232, 160, 76)
LAMP_DIM = (168, 112, 52)
LAMP_GLOW = (255, 206, 138)

# 雪
SNOW = (223, 232, 238)
SNOW_DIM = (170, 186, 198)
SNOW_FAINT = (120, 136, 150)

# 纸 / 木
PAPER = (226, 216, 198)
PAPER_DARK = (196, 184, 164)
WOOD = (58, 44, 34)
WOOD_LIGHT = (86, 66, 50)

# 语义
GOOD = (110, 190, 132)
WARN = (226, 176, 84)
BAD = (200, 86, 78)
CRIT = (228, 92, 84)
INFO = (140, 178, 200)
DIM = (128, 142, 156)

# 朱砂（印章色）
CINNABAR = (168, 54, 46)

# ────────────────────────── 字体 ──────────────────────────
_FONT_CACHE: dict = {}
_FONT_NAME: str | None = None
FONT_CANDIDATES = [
    "microsoftyahei",
    "microsoftyaheiui",
    "simhei",
    "nsimsun",
    "simsun",
    "dengxian",
    "fangsong",
]


def _resolve_font_name() -> str:
    global _FONT_NAME
    if _FONT_NAME is not None:
        return _FONT_NAME
    # pygame.font.match_font 能查系统字体
    for cand in FONT_CANDIDATES:
        p = pygame.font.match_font(cand)
        if p:
            _FONT_NAME = p
            return p
    # 退回到 pygame 自带字体（会缺中文）
    _FONT_NAME = ""
    return ""


def font(size: int, bold: bool = False) -> pygame.font.Font:
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    path = _resolve_font_name()
    try:
        if path:
            f = pygame.font.Font(path, size)
        else:
            f = pygame.font.Font(None, size)
        f.set_bold(bold)
    except Exception:
        f = pygame.font.Font(None, size)
    _FONT_CACHE[key] = f
    return f


def font_ok() -> bool:
    """系统里找不找得到中文字体。打包后自检用。"""
    return bool(_resolve_font_name())


# ────────────────────────── 排版助手 ──────────────────────────
def text(surface: pygame.Surface, s: str, pos, size=16, color=SNOW,
         bold=False, anchor="topleft", shadow=False):
    f = font(size, bold)
    img = f.render(s, True, color)
    r = img.get_rect(**{anchor: pos})
    if shadow:
        sh = f.render(s, True, (0, 0, 0))
        sh.set_alpha(140)
        surface.blit(sh, r.move(1, 2))
    surface.blit(img, r)
    return r


def text_wrapped(surface: pygame.Surface, s: str, rect: pygame.Rect,
                 size=15, color=SNOW, line_gap=4, bold=False):
    """按宽度自动折行。返回实际用掉的高度。"""
    f = font(size, bold)
    max_w = rect.width
    lines = []
    for para in s.split("\n"):
        if not para:
            lines.append("")
            continue
        cur = ""
        for ch in para:
            trial = cur + ch
            if f.size(trial)[0] <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
    y = rect.top
    lh = f.get_height() + line_gap
    for ln in lines:
        if y + lh > rect.bottom:
            break
        img = f.render(ln, True, color)
        surface.blit(img, (rect.left, y))
        y += lh
    return y - rect.top


def measure_wrapped(s: str, width: int, size=15, line_gap=4, bold=False) -> int:
    f = font(size, bold)
    lines = []
    for para in s.split("\n"):
        if not para:
            lines.append("")
            continue
        cur = ""
        for ch in para:
            trial = cur + ch
            if f.size(trial)[0] <= width:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
    return len(lines) * (f.get_height() + line_gap)


# ────────────────────────── 基础绘制 ──────────────────────────
def panel(surface: pygame.Surface, rect, color=NIGHT_2, border=NIGHT_3,
          radius=10, width=1, alpha=255):
    if alpha < 255:
        s = pygame.Surface(rect[2:], pygame.SRCALPHA)
        pygame.draw.rect(s, (*color, alpha), s.get_rect(), border_radius=radius)
        surface.blit(s, rect[:2])
    else:
        pygame.draw.rect(surface, color, rect, border_radius=radius)
    if width > 0:
        pygame.draw.rect(surface, border, rect, width=width, border_radius=radius)


def bar(surface: pygame.Surface, rect, value: float, max_value: float,
        color=LAMP, bg=NIGHT_3, radius=4):
    r = pygame.Rect(rect)
    pygame.draw.rect(surface, bg, r, border_radius=radius)
    if max_value <= 0:
        return
    frac = max(0.0, min(1.0, value / max_value))
    w = int(r.width * frac)
    if w > 0:
        pygame.draw.rect(surface, color, (r.x, r.y, w, r.height), border_radius=radius)


def hline(surface, x1, x2, y, color=NIGHT_3, w=1):
    pygame.draw.line(surface, color, (x1, y), (x2, y), w)


_VIGNETTE_CACHE: dict = {}


def vignette(surface: pygame.Surface, strength=90):
    """四周压暗，让画面聚焦。

    用一次性算好的径向遮罩（按分辨率缓存）。
    早先逐层矩形叠加的写法会在画面上留下可见的矩形色块。
    """
    w, h = surface.get_size()
    key = (w, h, strength)
    mask = _VIGNETTE_CACHE.get(key)
    if mask is None:
        # 低分辨率算再放大，既快又平滑
        lw, lh = max(2, w // 8), max(2, h // 8)
        small = pygame.Surface((lw, lh), pygame.SRCALPHA)
        cx, cy = lw / 2.0, lh / 2.0
        maxd = math.hypot(cx, cy)
        for y in range(lh):
            for x in range(lw):
                d = math.hypot(x - cx, y - cy) / maxd
                # 中心 0.55 以内不压暗，往外平滑增强
                t = max(0.0, (d - 0.55) / 0.45)
                a = int(strength * (t ** 1.6))
                if a > 0:
                    small.set_at((x, y), (0, 0, 0, min(255, a)))
        mask = pygame.transform.smoothscale(small, (w, h))
        _VIGNETTE_CACHE[key] = mask
    surface.blit(mask, (0, 0))
