# -*- coding: utf-8 -*-
"""特效：雪、余烬、屏幕震动。

全部是轻量粒子，上限写死，避免老旧显卡掉帧。
"""

from __future__ import annotations

import math
import random

import pygame

from . import theme as T


class Snow:
    """飘雪。三层视差：远层慢而小，近层快而大。"""

    def __init__(self, w, h, count=260, seed=7):
        self.w, self.h = w, h
        self.rng = random.Random(seed)
        self.count = min(count, 400)
        self.flakes = []
        for i in range(self.count):
            layer = i % 3
            self.flakes.append(self._spawn(layer, initial=True))

    def _spawn(self, layer, initial=False):
        r = self.rng
        speed = (0.35, 0.75, 1.35)[layer]
        size = (1, 2, 3)[layer]
        alpha = (70, 120, 175)[layer]
        return {
            "x": r.uniform(-20, self.w + 20),
            "y": r.uniform(-self.h, self.h) if initial else r.uniform(-30, -5),
            "spd": speed * r.uniform(0.8, 1.3),
            "drift": r.uniform(-0.35, 0.35),
            "size": size,
            "alpha": alpha,
            "phase": r.uniform(0, 6.28),
        }

    def resize(self, w, h):
        self.w, self.h = w, h

    def update(self, dt, wind=0.0):
        for f in self.flakes:
            f["phase"] += dt * 1.6
            f["y"] += f["spd"] * dt * 60
            f["x"] += (f["drift"] + wind + math.sin(f["phase"]) * 0.25) * dt * 60
            if f["y"] > self.h + 6:
                f2 = self._spawn(0)
                f.update(f2)
            if f["x"] < -25:
                f["x"] = self.w + 20
            elif f["x"] > self.w + 25:
                f["x"] = -20

    def draw(self, surface):
        for f in self.flakes:
            s = f["size"]
            if s <= 1:
                pygame.draw.circle(surface, (200, 214, 224),
                                   (int(f["x"]), int(f["y"])), 1)
            else:
                col = (215, 226, 236) if s == 2 else (230, 238, 244)
                pygame.draw.circle(surface, col, (int(f["x"]), int(f["y"])), s)


class Embers:
    """灯火余烬：从某点向上飘的小橙点。"""

    def __init__(self, count=26, seed=11):
        self.rng = random.Random(seed)
        self.parts = []
        self.count = count

    def emit(self, pos, n=1):
        for _ in range(n):
            if len(self.parts) >= self.count:
                self.parts.pop(0)
            self.parts.append({
                "x": pos[0] + self.rng.uniform(-4, 4),
                "y": pos[1] + self.rng.uniform(-2, 2),
                "vx": self.rng.uniform(-8, 8),
                "vy": self.rng.uniform(-26, -10),
                "life": self.rng.uniform(0.8, 2.0),
                "age": 0.0,
                "sz": self.rng.choice([1, 1, 2]),
            })

    def update(self, dt):
        alive = []
        for p in self.parts:
            p["age"] += dt
            if p["age"] >= p["life"]:
                continue
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vy"] += 6 * dt
            p["vx"] += self.rng.uniform(-6, 6) * dt
            alive.append(p)
        self.parts = alive

    def draw(self, surface):
        for p in self.parts:
            k = 1.0 - p["age"] / p["life"]
            a = int(200 * k)
            if a <= 0:
                continue
            s = pygame.Surface((p["sz"] * 2 + 2, p["sz"] * 2 + 2), pygame.SRCALPHA)
            pygame.draw.circle(s, (255, 196, 120, a),
                               (p["sz"] + 1, p["sz"] + 1), p["sz"])
            surface.blit(s, (int(p["x"]), int(p["y"])))


class Shake:
    """屏幕震动。"""

    def __init__(self):
        self.t = 0.0
        self.mag = 0.0

    def fire(self, mag=5.0, dur=0.28):
        self.mag = mag
        self.t = max(self.t, dur)
        self.dur = dur

    def update(self, dt):
        if self.t > 0:
            self.t = max(0.0, self.t - dt)

    def offset(self):
        if self.t <= 0:
            return (0, 0)
        k = self.t / max(0.001, self.dur)
        m = self.mag * k
        import random
        return (random.randint(-int(m), int(m)), random.randint(-int(m), int(m)))


class Fade:
    """入/出场淡入淡出。"""

    def __init__(self):
        self.alpha = 0.0
        self.target = 0.0
        self.speed = 3.0

    def to(self, target, speed=3.0):
        self.target = target
        self.speed = speed

    def update(self, dt):
        if abs(self.alpha - self.target) < 0.5:
            self.alpha = self.target
            return
        d = self.target - self.alpha
        self.alpha += d * min(1.0, self.speed * dt)

    def draw(self, surface, color=(0, 0, 0)):
        if self.alpha <= 1:
            return
        ov = pygame.Surface(surface.get_size())
        ov.fill(color)
        ov.set_alpha(int(self.alpha))
        surface.blit(ov, (0, 0))
