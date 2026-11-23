# -*- coding: utf-8 -*-
"""音效播放。

设计要点：
  · mixer 初始化失败时全部静音，游戏照常跑（不是所有机器都有声卡）
  · 环境音用单独 channel 循环，音量压低
  · 所有失败都吞掉，不给玩家报错——音效挂了不该影响游戏
"""

from __future__ import annotations

import os
import sys

import pygame

_SOUNDS: dict = {}
_AMBIENT: dict = {}
_enabled = True
_vol_master = 0.7
_vol_ambient = 0.35
_drone_ch = None
_wind_ch = None


def sfx_root() -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        for cand in (os.path.join(base, "relay", "assets", "sfx"),
                     os.path.join(base, "assets", "sfx")):
            if os.path.isdir(cand):
                return cand
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "assets", "sfx")


def init(enable=True):
    global _enabled, _SOUNDS, _AMBIENT
    _enabled = enable
    if not enable:
        return False
    try:
        if pygame.mixer.get_init() is None:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
    except Exception:
        _enabled = False
        return False

    root = sfx_root()
    if not os.path.isdir(root):
        return True      # 没音效也能玩

    for name in ("click", "chime", "fail", "bell", "horse"):
        p = os.path.join(root, name + ".wav")
        if os.path.isfile(p):
            try:
                s = pygame.mixer.Sound(p)
                s.set_volume(_vol_master)
                _SOUNDS[name] = s
            except Exception:
                pass

    for name, vol in (("wind", 0.22), ("drone", 0.18)):
        p = os.path.join(root, name + ".wav")
        if os.path.isfile(p):
            try:
                s = pygame.mixer.Sound(p)
                s.set_volume(vol)
                _AMBIENT[name] = s
            except Exception:
                pass
    return True


def play(name, volume=None):
    if not _enabled:
        return
    s = _SOUNDS.get(name)
    if not s:
        return
    try:
        if volume is not None:
            s.set_volume(max(0.0, min(1.0, volume)))
        s.play()
    except Exception:
        pass


def start_ambient():
    """循环播放风声 + 环境 drone。"""
    global _drone_ch, _wind_ch
    if not _enabled:
        return
    try:
        if _wind_ch is None and "wind" in _AMBIENT:
            _wind_ch = _AMBIENT["wind"].play(loops=-1)
        if _drone_ch is None and "drone" in _AMBIENT:
            _drone_ch = _AMBIENT["drone"].play(loops=-1)
    except Exception:
        pass


def stop_ambient():
    global _drone_ch, _wind_ch
    for ch in (_wind_ch, _drone_ch):
        try:
            if ch:
                ch.fadeout(600)
        except Exception:
            pass
    _wind_ch = None
    _drone_ch = None


def set_master(v: float):
    global _vol_master
    _vol_master = max(0.0, min(1.0, v))
    for s in _SOUNDS.values():
        try:
            s.set_volume(_vol_master)
        except Exception:
            pass


def available() -> dict:
    return {
        "enabled": _enabled,
        "sfx": sorted(_SOUNDS.keys()),
        "ambient": sorted(_AMBIENT.keys()),
        "mixer": bool(pygame.mixer.get_init()),
    }
