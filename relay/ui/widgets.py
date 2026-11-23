# -*- coding: utf-8 -*-
"""轻量控件层。

不做通用 GUI——只做这个游戏真正用得到的几样：
  Button / Toggle / Chip / Card / Divider / Toast
所有控件都是「立即模式」：每帧调用 draw() 并返回是否被点击。
"""

from __future__ import annotations

import math

import pygame

from . import theme as T


# ────────────────────────── 按钮 ──────────────────────────
class Button:
    def __init__(self, rect, label, kind="normal", size=15, enabled=True,
                 sublabel=None, icon=None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.kind = kind          # normal | primary | danger | ghost
        self.size = size
        self.enabled = enabled
        self.sublabel = sublabel
        self.icon = icon
        self.hover = False
        self._press_t = 0.0       # 按下动画计时

    def _colors(self):
        if not self.enabled:
            return (T.NIGHT_2, T.NIGHT_3, T.DIM)
        if self.kind == "primary":
            return ((44, 74, 62) if not self.hover else (54, 92, 76), T.LAMP, T.SNOW)
        if self.kind == "danger":
            return ((70, 34, 32) if not self.hover else (92, 42, 38), T.CINNABAR, T.SNOW)
        if self.kind == "ghost":
            return ((0, 0, 0), T.NIGHT_3 if not self.hover else T.SNOW_FAINT,
                    T.SNOW_DIM if not self.hover else T.SNOW)
        return ((T.NIGHT_3) if not self.hover else (40, 56, 72), T.NIGHT_3, T.SNOW)

    def handle(self, ev):
        if not self.enabled:
            return False
        if ev.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(ev.pos)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.rect.collidepoint(ev.pos):
                self._press_t = 0.08
                return True
        return False

    def draw(self, surface, dt=0.0):
        bg, border, fg = self._colors()
        r = self.rect.copy()
        if self._press_t > 0:
            self._press_t = max(0.0, self._press_t - dt)
            r = r.move(0, 1)
        if self.kind == "ghost":
            if self.hover:
                T.panel(surface, r, (255, 255, 255), border, radius=8, alpha=10)
            pygame.draw.rect(surface, border, r, width=1, border_radius=8)
        else:
            T.panel(surface, r, bg, border, radius=8)
        cy = r.centery if not self.sublabel else r.centery - 7
        T.text(surface, self.label, (r.centerx, cy - (0 if not self.sublabel else 0)),
               size=self.size, color=fg, anchor="center")
        if self.sublabel:
            T.text(surface, self.sublabel, (r.centerx, cy + 16),
                   size=11, color=T.DIM, anchor="center")


# ────────────────────────── 开关式选项（分段） ──────────────────────────
class Segmented:
    def __init__(self, rect, options, index=0, size=14):
        self.rect = pygame.Rect(rect)
        self.options = options      # [(key, label), ...]
        self.index = index
        self.size = size
        self.hover = -1

    def handle(self, ev):
        if ev.type == pygame.MOUSEMOTION:
            self.hover = self._hit(ev.pos)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            i = self._hit(ev.pos)
            if i >= 0:
                self.index = i
                return self.options[i][0]
        return None

    def _hit(self, pos):
        if not self.rect.collidepoint(pos):
            return -1
        n = len(self.options)
        if n == 0:
            return -1
        w = self.rect.width / n
        return min(n - 1, int((pos[0] - self.rect.left) / w))

    def draw(self, surface):
        T.panel(surface, self.rect, T.NIGHT_2, T.NIGHT_3, radius=7)
        n = len(self.options)
        w = self.rect.width / n
        for i, (k, lab) in enumerate(self.options):
            rr = pygame.Rect(int(self.rect.left + i * w), self.rect.top,
                             int(w), self.rect.height)
            if i == self.index:
                T.panel(surface, rr.inflate(-4, -6), T.NIGHT_3, T.LAMP, radius=5)
            col = T.SNOW if i == self.index else (T.SNOW_DIM if i == self.hover else T.DIM)
            T.text(surface, lab, rr.center, size=self.size, color=col, anchor="center")


# ────────────────────────── 小标签 ──────────────────────────
def chip(surface, pos, label, color=T.LAMP, bg=None, size=12, pad_x=7, pad_y=3,
         radius=5, anchor="topleft"):
    f = T.font(size)
    tw, th = f.size(label)
    w, h = tw + pad_x * 2, th + pad_y * 2
    r = pygame.Rect(0, 0, w, h)
    setattr(r, anchor, pos)
    if bg is None:
        bg = (color[0] // 4, color[1] // 4, color[2] // 4)
    pygame.draw.rect(surface, bg, r, border_radius=radius)
    pygame.draw.rect(surface, color, r, width=1, border_radius=radius)
    T.text(surface, label, r.center, size=size, color=color, anchor="center")
    return r


def chip_width(label, size=12, pad_x=7):
    return T.font(size).size(label)[0] + pad_x * 2


# ────────────────────────── 卡片底 ──────────────────────────
def card(surface, rect, hi=False, accent=None, alpha=255):
    bg = T.NIGHT_2 if not hi else (34, 48, 62)
    bd = accent if accent else (T.NIGHT_3 if not hi else T.LAMP_DIM)
    T.panel(surface, rect, bg, bd, radius=10, width=1, alpha=alpha)


# ────────────────────────── 分隔线 ──────────────────────────
def divider(surface, x1, x2, y, color=T.NIGHT_3):
    T.hline(surface, x1, x2, y, color, 1)


# ────────────────────────── 提示条 ──────────────────────────
class Toast:
    def __init__(self):
        self.msg = ""
        self.kind = "info"
        self.t = 0.0

    def show(self, msg, kind="info", duration=2.6):
        self.msg = msg
        self.kind = kind
        self.t = duration

    def update(self, dt):
        if self.t > 0:
            self.t = max(0.0, self.t - dt)

    def draw(self, surface, y=None):
        if self.t <= 0 or not self.msg:
            return
        color = {"info": T.INFO, "good": T.GOOD, "warn": T.WARN,
                 "bad": T.BAD}[self.kind]
        w = min(760, T.font(14).size(self.msg)[0] + 40)
        h = 34
        x = (surface.get_width() - w) // 2
        yy = y if y is not None else surface.get_height() - 78
        a = int(255 * min(1.0, self.t / 0.35))
        rect = pygame.Rect(x, yy, w, h)
        T.panel(surface, rect, T.NIGHT_2, color, radius=8, alpha=a)
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        T.text(surf, self.msg, (w // 2, h // 2), size=14, color=color, anchor="center")
        surf.set_alpha(a)
        surface.blit(surf, (x, yy))


# ────────────────────────── 进度环（用于「期限」） ──────────────────────────
def ring(surface, center, radius, frac, color=T.LAMP, bg=T.NIGHT_3, width=3):
    rect = pygame.Rect(0, 0, radius * 2, radius * 2)
    rect.center = center
    pygame.draw.circle(surface, bg, center, radius, width)
    if frac > 0:
        steps = max(3, int(36 * frac))
        pts = []
        for i in range(steps + 1):
            a = -math.pi / 2 + (2 * math.pi * frac) * (i / steps)
            pts.append((center[0] + math.cos(a) * radius,
                        center[1] + math.sin(a) * radius))
        if len(pts) >= 2:
            pygame.draw.lines(surface, color, False, pts, width)


# ────────────────────────── 闪光 / 高亮 ──────────────────────────
def glow(surface, center, radius, color=T.LAMP, alpha=40):
    s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    for i in range(6, 0, -1):
        r = int(radius * i / 6)
        a = int(alpha * (1 - i / 7))
        pygame.draw.circle(s, (*color, a), (radius, radius), r)
    surface.blit(s, (center[0] - radius, center[1] - radius),
                 special_flags=pygame.BLEND_RGBA_ADD)
