# -*- coding: utf-8 -*-
"""素材加载。

设计原则：
  · 素材缺失不能让游戏崩——生成一个替身图，游戏照常能玩
  · 所有图按需缩放并缓存，避免每帧转换
  · 素材目录可以是「开发目录」也可以是 PyInstaller 解包目录
"""

from __future__ import annotations

import os
import sys

import pygame

from . import theme as T

_CACHE: dict = {}
_MISSING: set = set()


def asset_root() -> str:
    """找到 assets/art 目录，兼容 PyInstaller 单文件模式。"""
    # PyInstaller 把数据解到 sys._MEIPASS
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = os.path.join(base, "relay", "assets", "art")
        if os.path.isdir(p):
            return p
        p = os.path.join(base, "assets", "art")
        if os.path.isdir(p):
            return p
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "assets", "art")


ROOT = asset_root()


def _find_file(asset_id: str) -> str | None:
    """支持 Relay 导出的 xxx_relay_00004_.png 这种带序号的文件名。"""
    if not os.path.isdir(ROOT):
        return None
    exact = os.path.join(ROOT, asset_id + ".png")
    if os.path.isfile(exact):
        return exact
    # 前缀匹配，取序号最大的（最新出的）
    cands = [f for f in os.listdir(ROOT)
             if f.startswith(asset_id + "_") and f.endswith(".png")]
    if not cands:
        return None
    cands.sort()
    return os.path.join(ROOT, cands[-1])


# ────────────────────────── 替身图 ──────────────────────────
def _placeholder(w: int, h: int, label: str = "") -> pygame.Surface:
    """素材缺失时的替身：一张带渐变和水印的暗色图。"""
    s = pygame.Surface((max(8, w), max(8, h))).convert()
    top = T.NIGHT_3
    bot = T.NIGHT
    for y in range(h):
        t = y / max(1, h - 1)
        c = (int(top[0] + (bot[0] - top[0]) * t),
             int(top[1] + (bot[1] - top[1]) * t),
             int(top[2] + (bot[2] - top[2]) * t))
        pygame.draw.line(s, c, (0, y), (w, y))
    if label and w >= 90 and h >= 40:
        T.text(s, label, (w // 2, h // 2), size=max(11, min(20, h // 8)),
               color=T.SNOW_FAINT, anchor="center")
    return s


# ────────────────────────── 对外接口 ──────────────────────────
def load(asset_id: str, size: tuple[int, int] | None = None,
         label: str = "") -> pygame.Surface:
    """按 id 载入素材，可指定缩放尺寸（会缓存）。"""
    key = (asset_id, size)
    if key in _CACHE:
        return _CACHE[key]

    path = _find_file(asset_id)
    surf = None
    if path:
        try:
            surf = pygame.image.load(path).convert()
        except Exception:
            surf = None

    if surf is None:
        if asset_id not in _MISSING:
            _MISSING.add(asset_id)
        if size:
            surf = _placeholder(size[0], size[1], label or asset_id)
        else:
            surf = _placeholder(640, 360, label or asset_id)
    elif size and surf.get_size() != size:
        surf = pygame.transform.smoothscale(surf, size)

    _CACHE[key] = surf
    return surf


def load_cover(asset_id: str, size: tuple[int, int], label: str = "") -> pygame.Surface:
    """按「填满并裁切」的方式缩放（保持比例）。"""
    key = ("cover", asset_id, size)
    if key in _CACHE:
        return _CACHE[key]

    path = _find_file(asset_id)
    if not path:
        surf = _placeholder(size[0], size[1], label or asset_id)
        _CACHE[key] = surf
        return surf
    try:
        src = pygame.image.load(path).convert()
    except Exception:
        surf = _placeholder(size[0], size[1], label or asset_id)
        _CACHE[key] = surf
        return surf

    sw, sh = src.get_size()
    dw, dh = size
    scale = max(dw / sw, dh / sh)
    nw, nh = int(sw * scale + 0.5), int(sh * scale + 0.5)
    scaled = pygame.transform.smoothscale(src, (nw, nh))
    x = (nw - dw) // 2
    y = (nh - dh) // 2
    out = pygame.Surface(size).convert()
    out.blit(scaled, (0, 0), pygame.Rect(x, y, dw, dh))
    _CACHE[key] = out
    return out


def fit(asset_id: str, max_size: tuple[int, int], label: str = "") -> pygame.Surface:
    """按「等比缩放放进框里」的方式加载。"""
    key = ("fit", asset_id, max_size)
    if key in _CACHE:
        return _CACHE[key]
    path = _find_file(asset_id)
    if not path:
        surf = _placeholder(max_size[0], max_size[1], label or asset_id)
        _CACHE[key] = surf
        return surf
    try:
        src = pygame.image.load(path).convert()
    except Exception:
        surf = _placeholder(max_size[0], max_size[1], label or asset_id)
        _CACHE[key] = surf
        return surf
    sw, sh = src.get_size()
    mw, mh = max_size
    scale = min(mw / sw, mh / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    surf = pygame.transform.smoothscale(src, (nw, nh))
    _CACHE[key] = surf
    return surf


def dim(surf: pygame.Surface, alpha: int) -> pygame.Surface:
    """返回压暗后的副本（带缓存）。"""
    key = ("dim", id(surf), alpha)
    if key in _CACHE:
        return _CACHE[key]
    s = surf.copy()
    ov = pygame.Surface(s.get_size(), pygame.SRCALPHA)
    ov.fill((0, 0, 0, alpha))
    s.blit(ov, (0, 0))
    _CACHE[key] = s
    return s


def tint(surf: pygame.Surface, color, alpha: int) -> pygame.Surface:
    key = ("tint", id(surf), color, alpha)
    if key in _CACHE:
        return _CACHE[key]
    s = surf.copy()
    ov = pygame.Surface(s.get_size(), pygame.SRCALPHA)
    ov.fill((*color[:3], alpha))
    s.blit(ov, (0, 0))
    _CACHE[key] = s
    return s


def report() -> dict:
    """素材自检：打包后用来确认资源都在。"""
    ids = [
        "title", "main_bg", "ending_good", "ending_bad",
        "route_north", "route_ford", "route_mine",
        "wx_clear", "wx_cloud", "wx_rain", "wx_snow", "wx_storm",
        "rider_old", "rider_young", "rider_woman", "rider_scar",
        "horse_dark", "horse_grey", "paper", "lacquer",
    ]
    found = {i: bool(_find_file(i)) for i in ids}
    return {
        "root": ROOT,
        "exists": os.path.isdir(ROOT),
        "found": found,
        "missing": [k for k, v in found.items() if not v],
        "total": len(ids),
        "ok": sum(1 for v in found.values() if v),
    }
