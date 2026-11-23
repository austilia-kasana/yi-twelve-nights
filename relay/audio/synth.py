# -*- coding: utf-8 -*-
"""音效合成。

不下载任何音频素材，全部用 numpy 现算成 WAV。
这样 exe 里不带音频文件，体积小，也没有版权问题。

设计：
  · 所有音效都是「短、轻、不打扰」——这是款安静的游戏
  · 失败音不做成刺耳的，只是变沉
  · 环境音是一个可循环的低频 drone，压低音量当底噪
"""

from __future__ import annotations

import math
import os
import struct
import wave

import numpy as np

SR = 44100


# ────────────────────────── 基础工具 ──────────────────────────
def _env(n, attack=0.01, decay=0.2, curve=2.0):
    """简单包络：线性起音 + 幂次衰减。"""
    a = max(1, int(attack * SR))
    d = max(1, n - a)
    e = np.ones(n)
    e[:a] = np.linspace(0, 1, a)
    e[a:] = np.power(np.linspace(1, 0, d), curve)
    return e


def _noise(n, seed=0):
    rng = np.random.default_rng(seed)
    return rng.uniform(-1, 1, n)


def _lowpass(x, cutoff):
    """一阶 IIR 低通。够用就行。"""
    a = math.exp(-2.0 * math.pi * cutoff / SR)
    y = np.zeros_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a) * x[i] + a * acc
        y[i] = acc
    return y


def _highpass(x, cutoff):
    return x - _lowpass(x, cutoff)


def _to_int16(x):
    x = np.clip(x, -1.0, 1.0)
    return (x * 32767).astype(np.int16)


def _write_wav(path, samples, channels=2):
    """samples: float32 mono [-1,1]；写成 16-bit 立体声。"""
    data = _to_int16(samples)
    if channels == 2:
        inter = np.empty(data.size * 2, dtype=np.int16)
        inter[0::2] = data
        inter[1::2] = data
        data = inter
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


# ────────────────────────── 各种音 ──────────────────────────
def sfx_click():
    n = int(0.055 * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * 920 * t) * 0.35 + np.sin(2 * np.pi * 1840 * t) * 0.12
    x *= _env(n, 0.002, 0.08, 3.5)
    return x


def sfx_chime(root=523.25):
    """送达：三音上行（五声音阶）。"""
    freqs = [root, root * 9 / 8, root * 3 / 2]
    total = int(0.85 * SR)
    out = np.zeros(total)
    for i, f in enumerate(freqs):
        off = int(i * 0.085 * SR)
        n = total - off
        t = np.arange(n) / SR
        # 基频 + 两个泛音，让铃有金属感
        x = (np.sin(2 * np.pi * f * t) * 0.55
             + np.sin(2 * np.pi * f * 2.01 * t) * 0.18
             + np.sin(2 * np.pi * f * 3.02 * t) * 0.08)
        x *= _env(n, 0.004, 0.9, 2.2)
        out[off:off + n] += x * 0.5
    return out


def sfx_fail():
    """延误/失败：两音下行，低而闷。"""
    freqs = [196.0, 146.83]
    total = int(0.9 * SR)
    out = np.zeros(total)
    for i, f in enumerate(freqs):
        off = int(i * 0.14 * SR)
        n = total - off
        t = np.arange(n) / SR
        x = np.sin(2 * np.pi * f * t) * 0.5
        x += _lowpass(_noise(n, seed=7), 300) * 0.12
        x *= _env(n, 0.01, 1.0, 2.6)
        out[off:off + n] += x * 0.5
    return out


def sfx_bell_soft():
    """低音量提示（换夜）。"""
    n = int(1.2 * SR)
    t = np.arange(n) / SR
    f = 392.0
    x = (np.sin(2 * np.pi * f * t) * 0.4
         + np.sin(2 * np.pi * f * 2.76 * t) * 0.12
         + np.sin(2 * np.pi * f * 5.4 * t) * 0.05)
    x *= _env(n, 0.006, 1.3, 2.0)
    return x


def sfx_horse():
    """马蹄：短噪声脉冲 + 低频。"""
    n = int(0.16 * SR)
    t = np.arange(n) / SR
    body = np.sin(2 * np.pi * 92 * t) * 0.35
    nz = _lowpass(_noise(n, seed=3), 900) * 0.5
    x = body + nz
    x *= _env(n, 0.002, 0.18, 4.0)
    return x


def sfx_wind(seconds=8.0, seed=5):
    """风：低通白噪 + 缓慢起伏。可循环。"""
    n = int(seconds * SR)
    base = _lowpass(_noise(n, seed=seed), 420) * 0.5
    # 缓慢包络
    t = np.arange(n) / SR
    lfo = 0.55 + 0.45 * np.sin(2 * np.pi * t / seconds * 1.5 + 1.2)
    x = base * lfo
    # 首尾淡入淡出，便于循环
    fade = int(0.5 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    return x * 0.55


def sfx_drone(seconds=12.0):
    """环境底噪：两个相差五度的正弦 + 极缓 LFO。可循环。"""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    f1, f2 = 65.41, 98.0          # C2 + G2
    x = (np.sin(2 * np.pi * f1 * t) * 0.30
         + np.sin(2 * np.pi * f2 * t) * 0.18
         + np.sin(2 * np.pi * f1 * 2 * t) * 0.06)
    lfo = 0.7 + 0.3 * np.sin(2 * np.pi * t / seconds * 2.0)
    x *= lfo
    fade = int(1.2 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    return x * 0.4


# ────────────────────────── 生成全套 ──────────────────────────
SOUNDS = {
    "click": (sfx_click, 0.8),
    "chime": (sfx_chime, 0.7),
    "fail": (sfx_fail, 0.75),
    "bell": (sfx_bell_soft, 0.6),
    "horse": (sfx_horse, 0.7),
    "wind": (sfx_wind, 0.35),
    "drone": (sfx_drone, 0.3),
}


def generate_all(out_dir: str, verbose=True) -> dict:
    """生成全部 WAV，返回 {名字: 路径}。已存在则跳过。"""
    os.makedirs(out_dir, exist_ok=True)
    result = {}
    for name, (fn, vol) in SOUNDS.items():
        path = os.path.join(out_dir, name + ".wav")
        result[name] = path
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            if verbose:
                print("  %-8s 已存在，跳过" % name)
            continue
        x = fn() * vol
        _write_wav(path, x.astype(np.float32))
        if verbose:
            print("  %-8s %.2f 秒  %d KB" % (
                name, len(x) / SR, os.path.getsize(path) // 1024))
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets", "sfx"))
    args = ap.parse_args()
    print("生成音效到 %s" % args.out)
    generate_all(args.out)
