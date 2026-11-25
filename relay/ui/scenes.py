# -*- coding: utf-8 -*-
"""三个场景：标题、主界面（排班）、结算。

主界面交互设计（刻意做得「点两下就完成」，不折腾下拉框）：
  1. 点一封信 → 选中
  2. 点一个骑手 → 派给他；再点一次取消
  3. 点一匹马 → 换马
  4. 点「送出去」 → 推进一夜
"""

from __future__ import annotations

import math

import pygame

from ..core import balance as B
from ..core.sim import GameState
from ..audio import player as A
from . import art, fx, theme as T, widgets as W


# ────────────────────────── 通用小件 ──────────────────────────
def draw_header(surf, gs: GameState, title_right=None):
    """顶部状态条。"""
    h = 62
    bar = pygame.Surface((surf.get_width(), h), pygame.SRCALPHA)
    bar.fill((*T.INK, 215))
    surf.blit(bar, (0, 0))
    pygame.draw.line(surf, T.NIGHT_3, (0, h), (surf.get_width(), h), 1)

    T.text(surf, "驿", (24, h // 2), size=24, color=T.LAMP, anchor="midleft")
    T.text(surf, "十二夜", (54, h // 2 + 1), size=13, color=T.DIM, anchor="midleft")

    # 夜
    nx = 130
    T.text(surf, "第", (nx, h // 2), size=13, color=T.DIM, anchor="midleft")
    nw = T.font(20, True).size(str(gs.night))[0]
    T.text(surf, str(gs.night), (nx + 22, h // 2), size=20,
           color=T.SNOW, anchor="midleft", bold=True)
    T.text(surf, "/ %d 夜" % B.TOTAL_NIGHTS, (nx + 22 + nw + 4, h // 2),
           size=13, color=T.DIM, anchor="midleft")

    # 信
    fx0 = 280
    T.text(surf, "信", (fx0, h // 2 - 1), size=13, color=T.DIM, anchor="midleft")
    bar_rect = pygame.Rect(fx0 + 20, h // 2 - 5, 170, 10)
    frac = gs.faith / B.MAX_FAITH
    col = T.GOOD if frac > 0.6 else (T.WARN if frac > 0.35 else T.BAD)
    T.bar(surf, bar_rect, gs.faith, B.MAX_FAITH, color=col)

    # 三条刻度：60 守住 / 70 A / 80 S。
    # 玩家不该靠记忆知道 S 线在哪——早先我自己玩的时候一直在心里记着 80。
    for th, lab, tcol in ((B.SURVIVE_FAITH, "守", T.SNOW_FAINT),
                          (70, "A", T.SNOW_FAINT),
                          (80, "S", T.LAMP_DIM)):
        tx = bar_rect.x + int(bar_rect.width * th / B.MAX_FAITH)
        pygame.draw.line(surf, tcol, (tx, bar_rect.y - 4), (tx, bar_rect.bottom + 4), 1)
        T.text(surf, lab, (tx, bar_rect.y - 8), size=9, color=tcol, anchor="midbottom")

    T.text(surf, "%d" % int(gs.faith), (bar_rect.right + 8, h // 2),
           size=16, color=col, anchor="midleft", bold=True)

    # 金 / 油
    gx = 600
    T.text(surf, "金", (gx, h // 2), size=13, color=T.DIM, anchor="midleft")
    T.text(surf, "%d" % int(gs.gold), (gx + 20, h // 2), size=17,
           color=T.LAMP, anchor="midleft", bold=True)
    ox = gx + 110
    T.text(surf, "油", (ox, h // 2), size=13, color=T.DIM, anchor="midleft")
    ocol = T.SNOW if gs.oil >= 20 else T.BAD
    T.text(surf, "%d" % int(gs.oil), (ox + 20, h // 2), size=17,
           color=ocol, anchor="midleft", bold=True)
    if gs.oil < B.NO_LIGHT_OIL_THRESHOLD:
        T.text(surf, "没灯！", (ox + 60, h // 2), size=12, color=T.BAD, anchor="midleft")

    if title_right:
        T.text(surf, title_right, (surf.get_width() - 24, h // 2),
               size=13, color=T.DIM, anchor="midright")
    return h


# ────────────────────────── 标题场景 ──────────────────────────
class TitleScene:
    def __init__(self, app):
        self.app = app
        self.snow = fx.Snow(T.WIDTH, T.HEIGHT, 300, seed=3)
        self.t = 0.0
        self.bg = None
        self.btn_start = W.Button((T.WIDTH // 2 - 90, 470, 180, 48),
                                  "入夜", kind="primary", size=17)
        self.btn_help = W.Button((T.WIDTH // 2 - 90, 530, 180, 38),
                                 "怎么玩", kind="normal", size=14)
        self.show_help = False
        self.btn_back = W.Button((T.WIDTH // 2 - 60, T.HEIGHT - 90, 120, 38),
                                 "知道了", kind="normal", size=14)

        # 存档
        from ..core import save as SV
        self.save_info = SV.info("auto")
        self.btn_resume = None
        if self.save_info:
            # 有存档时把「入夜」上移，下面插一个「继续」
            self.btn_start.rect.y = 420
            self.btn_resume = W.Button((T.WIDTH // 2 - 90, 478, 180, 48),
                                       "继续", kind="normal", size=16)
            self.btn_help.rect.y = 536

    def _resume(self):
        from ..core import save as SV
        gs = SV.load("auto")
        if gs is None:
            # 存档坏了：删掉它，别让玩家反复点进一个坏档
            SV.delete("auto")
            self.save_info = None
            self.btn_resume = None
            self.app.gs = None
            self.app.scene = TitleScene(self.app)
            return
        self.app.gs = gs
        if gs.over:
            self.app.goto_result(gs)
        else:
            self.app.scene = PlayScene(self.app, gs)
            self.app.fade.alpha = 0.0

    def handle(self, ev):
        if self.show_help:
            if self.btn_back.handle(ev):
                self.show_help = False
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_RETURN):
                self.show_help = False
            return
        if self.btn_start.handle(ev):
            self.app.start_new_game()
        if self.btn_resume and self.btn_resume.handle(ev):
            self._resume()
        if self.btn_help.handle(ev):
            self.show_help = True

    def update(self, dt):
        self.t += dt
        self.snow.update(dt, wind=0.15)

    def draw(self, surf):
        if self.bg is None:
            self.bg = art.load_cover("title", (T.WIDTH, T.HEIGHT))
        surf.blit(self.bg, (0, 0))
        T.vignette(surf, 120)
        self.snow.draw(surf)

        # 标题
        cy = 250 + math.sin(self.t * 0.9) * 2
        T.text(surf, "驿", (T.WIDTH // 2, cy - 40), size=76, color=T.LAMP,
               anchor="center", shadow=True)
        T.text(surf, "十  二  夜", (T.WIDTH // 2, cy + 34), size=22,
               color=T.SNOW, anchor="center", shadow=True)
        T.text(surf, "你是山口驿站的驿丞。十二个夜晚，把北边的战报送过山。",
               (T.WIDTH // 2, cy + 78), size=14, color=T.SNOW_DIM,
               anchor="center", shadow=True)

        if not self.show_help:
            self.btn_start.draw(surf)
            if self.btn_resume:
                self.btn_resume.draw(surf)
            self.btn_help.draw(surf)
            if self.btn_resume and self.save_info:
                si = self.save_info
                box = pygame.Rect(0, 0, 360, 32)
                box.center = (T.WIDTH // 2, 606)
                # 底要够实：这块压在亮雪上，半透明会被吃掉
                ov = pygame.Surface((box.width, box.height), pygame.SRCALPHA)
                pygame.draw.rect(ov, (12, 18, 26, 235), ov.get_rect(), border_radius=8)
                pygame.draw.rect(ov, T.NIGHT_3, ov.get_rect(), 1, border_radius=8)
                surf.blit(ov, box.topleft)
                label = "上一局  第 %d 夜" % si["night"]
                T.text(surf, label, (box.centerx - 34, box.centery), size=12,
                       color=T.SNOW_DIM, anchor="midright")
                T.text(surf, "信 %d" % int(si["faith"]), (box.centerx - 22, box.centery),
                       size=12, color=T.LAMP, anchor="midleft")
            else:
                T.text(surf, "点「入夜」开始。十二个夜晚，把信送过山。",
                       (T.WIDTH // 2, T.HEIGHT - 46), size=11, color=T.SNOW_FAINT,
                       anchor="center")
        else:
            self._draw_help(surf)

    def _draw_help(self, surf):
        # 发布验收要求（GPT/Gemini 裁决）：
        #   玩家必须能从这里看懂 ①在途占用 ②抵达夜不可派遣
        #   ③每夜天气重算 ④事件效果
        # 所以面板做高一点，分成四小节。
        panel = pygame.Rect(0, 0, 840, 692)
        panel.center = (T.WIDTH // 2, T.HEIGHT // 2)
        ov = pygame.Surface((T.WIDTH, T.HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 170))
        surf.blit(ov, (0, 0))
        T.panel(surf, panel, T.NIGHT_2, T.NIGHT_3, radius=14)

        x = panel.left + 34
        y = panel.top + 18

        def head(s):
            nonlocal y
            T.text(surf, s, (x, y), size=17, color=T.LAMP)
            y += 24

        def line(s, c=T.SNOW, indent=0):
            nonlocal y
            if s:
                T.text(surf, s, (x + indent, y), size=13, color=c)
            y += 18

        head("怎么玩")
        line("每夜黄昏会收到三到五封信。每封有目的地、期限、赏钱、罚信。", T.SNOW)
        line("点一封信选中它，再点骑手派给他，再点一匹马换马。", T.SNOW, 12)
        line("十二夜后信到 60 以上才算守住；信归零，驿就被撤了。", T.SNOW_DIM, 12)
        y += 6

        head("① 在途占用")
        line("派出的人和马不是当夜就回来。路程几夜，他们就占用几夜。", T.SNOW)
        line("占用期间他们不在左边列表里，也不能派去别的信。", T.SNOW_DIM, 12)
        line("每张信上标着「在途 N%」，N 到 100% 就是到了。", T.SNOW_DIM, 12)
        y += 6

        head("② 抵达当夜不能再用")
        line("人马抵达的那一夜仍然算占用，要等到下一夜才能再派。", T.SNOW)
        line("所以算排班时要多留一夜——这也是为什么「余量」很重要。", T.SNOW_DIM, 12)
        y += 6

        head("③ 天气每夜重算")
        line("天气不是出发时锁死的，每一夜都会重新变。", T.SNOW)
        line("出发时晴天，不代表路上一直晴。预报只有七成准。", T.SNOW_DIM, 12)
        line("你的「预计 N 夜」是按预报算的，变天就会更久。", T.SNOW_DIM, 12)
        y += 6

        head("④ 路上会发生事")
        line("每在途一夜，都有一点点概率碰到事。碰到的事会写在日志里。", T.SNOW)
        line("顺风 → 这一夜走得更快；迷路 → 只走一半。", T.SNOW_DIM, 12)
        line("落石 → 这一夜原地不动（和迷路不同，是完全不前进）。", T.WARN, 12)
        line("遇劫 → 这封信直接丢了，还要扣罚信。骑手可能受伤。", T.WARN, 12)
        line("事件概率是固定的，不是随机惩罚——你能靠余量对冲。", T.SNOW_DIM, 12)
        y += 6

        # 外部评估指出：只讲机制、不讲「怎么想」，新手懂了机制也不会做决策。
        # 这一节补的是判断方法，不是规则。
        head("⑤ 那到底该怎么想")
        line("看「期限 - 预计夜数」这个差，就是你的余量。", T.LAMP)
        line("余量 2 以上：基本稳，可以放心接。", T.SNOW_DIM, 12)
        line("余量 1：要赌一次变天。大多数时候划算。", T.SNOW_DIM, 12)
        line("余量 0：这趟只有「一路顺风」才成。输了要赔罚信。", T.WARN, 12)
        line("真正的决策是「这一夜把人马用在哪封信上」——用一次少一次。", T.SNOW)
        line("前期不缺信时稳着来；后期信吃紧时，才值得赌。", T.SNOW_DIM)

        self.btn_back.rect.center = (panel.centerx, panel.bottom - 30)
        self.btn_back.draw(surf)


def repair_label(route_name: str, cur_distance: int) -> str:
    """整备面板里「修路」按钮的文案。

    早先写的是「修 北口（3→2 夜）」——但那两个数其实是**路程**
    （`gs.route_distance`），不是夜数。北口走 1 夜还是 2 夜要看天气和脚力，
    修完不保证少一夜。玩家照着「3→2 夜」去算余量，会算错。
    所以老老实实写「路程」。
    """
    return "修 %s（路程 %d→%d）" % (route_name, cur_distance, cur_distance - 1)


# ────────────────────────── 主界面 ──────────────────────────
class PlayScene:
    def __init__(self, app, gs: GameState):
        self.app = app
        self.gs = gs
        self.snow = fx.Snow(T.WIDTH, T.HEIGHT, 200, seed=17)
        self.embers = fx.Embers()
        self.toast = W.Toast()
        self.t = 0.0

        self.selected_dispatch = None    # dispatch id
        self.plan = {}                   # dispatch_id -> (rider_id, horse_id)

        self.btn_send = W.Button((T.WIDTH - 210, T.HEIGHT - 66, 186, 48),
                                 "送出今夜", kind="primary", size=17)
        self.btn_shop = W.Button((T.WIDTH - 210, T.HEIGHT - 112, 186, 34),
                                 "整备", kind="normal", size=13)
        self.btn_clear = W.Button((T.WIDTH - 210, T.HEIGHT - 156, 186, 30),
                                  "清空本夜", kind="ghost", size=12)
        # 早先这个按钮叫「菜单」，点一下直接回标题页：什么都不问，
        # 也不存档，一整局就这么丢了。既然它实际上就是「存盘退出」，
        # 就照实叫这个名字，并且真的存一次盘。
        self.btn_menu = W.Button((T.WIDTH - 104, 16, 84, 30), "存盘退出",
                                 kind="ghost", size=12)
        self.show_shop = False
        self.shop_rect = pygame.Rect(0, 0, 1, 1)
        self.btn_shop_close = W.Button((0, 0, 30, 30), "×", kind="ghost", size=19)
        self.shop_btns = []
        self._build_shop()

        self.card_rects = []             # [(rect, dispatch_id)]
        self.rider_rects = []
        self.horse_rects = []

        self.last_faith = gs.faith
        self.faith_flash = 0.0
        self.report = None               # 上一夜结算，用于显示

    # ---- 商店 ----
    def _build_shop(self):
        gs = self.gs
        x = T.WIDTH - 300
        y = 120
        self.shop_btns = [
            ("oil", W.Button((x, y, 250, 34),
                             "添油 +%d" % B.OIL_REFILL_AMOUNT,
                             sublabel="—", size=13), B.PRICES["oil"]),
            ("rider", W.Button((x, y + 52, 250, 34),
                               "雇一个骑手", size=13), B.PRICES["hire_rider"]),
            ("horse", W.Button((x, y + 104, 250, 34),
                               "买一匹马", size=13), B.PRICES["buy_horse"]),
        ]
        # 喂料按钮：每个马一个。在途的马不给喂——按钮直接不放出来。
        for i, h in enumerate(gs.horses[:4]):
            if gs.is_busy(horse_id=h.id):
                continue
            self.shop_btns.append(
                ("feed:" + h.id, W.Button((x, y + 170 + i * 40, 250, 32),
                                          "喂 %s" % h.name, size=12),
                 B.PRICES["feed"]))

        # 修路按钮。
        # 早先 repair_route() 只有实现、没有入口——是纯死代码：
        # 玩家永远触发不到，整个功能等于不存在。修一次路短一截，每条路只能修一次。
        for rk, rd in B.ROUTES.items():
            if rk in gs.route_repaired:
                continue
            cur = gs.route_distance[rk]
            if cur <= 1:
                continue
            self.shop_btns.append(
                ("repair:" + rk,
                 W.Button((x, y + 400, 250, 32),
                          repair_label(rd["name"], cur),
                          size=12),
                 rd["repair_cost"]))

    # ---- 事件 ----
    def handle(self, ev):
        if self.show_shop:
            for key, btn, cost in self.shop_btns:
                if btn.handle(ev):
                    self._do_shop(key)
                    return
            # 关闭途径：右上角 × 按钮，或者点面板外面
            # （早先只认 Esc，纯鼠标玩家会卡死在面板里）
            if self.btn_shop_close.handle(ev):
                self.show_shop = False
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if not self.shop_rect.collidepoint(ev.pos):
                    self.show_shop = False
                    return
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_SPACE):
                self.show_shop = False
            return

        if self.btn_send.handle(ev):
            A.play("bell")
            self._send()
            return
        if self.btn_shop.handle(ev):
            self.show_shop = True
            self._build_shop()
            return
        if self.btn_clear.handle(ev):
            n = len(self.plan)
            self.plan.clear()
            self.selected_dispatch = None
            if n:
                self.toast.show("清空了 %d 条指派。" % n, "info")
            return
        if self.btn_menu.handle(ev):
            # 先写自动存档，再回标题。写盘失败也照样回去（save_progress 返回 False），
            # 但至少不会像以前那样——玩家以为按了菜单，回来发现进度没了。
            self.app.save_progress()
            self.app.goto_title()
            return

        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            # 点信
            for rect, did in self.card_rects:
                if rect.collidepoint(ev.pos):
                    self.selected_dispatch = (None if self.selected_dispatch == did
                                              else did)
                    return
            # 点骑手
            for rect, rid in self.rider_rects:
                if rect.collidepoint(ev.pos):
                    self._assign(rid, "rider")
                    return
            # 点马
            for rect, hid in self.horse_rects:
                if rect.collidepoint(ev.pos):
                    self._assign(hid, "horse")
                    return

        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_SPACE or ev.key == pygame.K_RETURN:
                self._send()
            elif ev.key == pygame.K_ESCAPE:
                self.selected_dispatch = None

    def _assign(self, oid, what):
        did = self.selected_dispatch
        if not did:
            self.toast.show("先点一封信。", "warn")
            return
        # 在路上的人马不能派。核心层也会挡，这里先给个明白的提示。
        gs0 = self.gs
        if what == "rider" and gs0.is_busy(rider_id=oid):
            self.toast.show("这个人还在路上。", "warn")
            return
        if what == "horse" and gs0.is_busy(horse_id=oid):
            self.toast.show("这匹马还在路上。", "warn")
            return
        cur = self.plan.get(did, (None, None))
        r, h = cur
        if what == "rider":
            if r == oid:
                r = None
            else:
                # 这个骑手已经派给别人了
                for k, (rr, hh) in self.plan.items():
                    if k != did and rr == oid:
                        self.toast.show("他已经在送别处了。", "warn")
                        return
                r = oid
        else:
            if h == oid:
                h = None
            else:
                for k, (rr, hh) in self.plan.items():
                    if k != did and hh == oid:
                        self.toast.show("这匹马今夜已经用过了。", "warn")
                        return
                h = oid
        self.plan[did] = (r, h)
        A.play("click")

    def _do_shop(self, key):
        gs = self.gs
        if key == "oil":
            if gs.buy_oil():
                self.toast.show("油添好了。", "good")
            else:
                self.toast.show("钱不够。", "bad")
        elif key == "rider":
            r = gs.hire_rider()
            if r:
                self.toast.show("雇了 %s。" % r.name, "good")
            else:
                self.toast.show("钱不够。", "bad")
        elif key == "horse":
            h = gs.buy_horse()
            if h:
                self.toast.show("买了 %s。" % h.name, "good")
            else:
                self.toast.show("钱不够。", "bad")
        elif key.startswith("feed:"):
            hid = key.split(":", 1)[1]
            if gs.feed(hid):
                self.toast.show("喂过了。", "good")
            else:
                self.toast.show("钱不够，或马不在了。", "bad")
        elif key.startswith("repair:"):
            rk = key.split(":", 1)[1]
            if gs.repair_route(rk):
                self.toast.show("修好了，路短了一截。", "good")
            else:
                self.toast.show("修不了——钱不够，或者已经修过了。", "bad")
        self._build_shop()

    def _send(self):
        gs = self.gs
        assignments = []
        for did, (rid, hid) in self.plan.items():
            if not rid or not hid:
                continue
            d = gs.dispatch_by_id(did)
            r = gs.rider_by_id(rid)
            h = gs.horse_by_id(hid)
            if d and r and h and r.is_available():
                assignments.append((d, r, h))

        resting = {r.id for r in gs.riders
                   if r.state == "idle" and r.id not in {a[1].id for a in assignments}}

        try:
            res = gs.advance(assignments, resting)
        except Exception as e:
            self.toast.show("出错了：%s" % e, "bad")
            return

        self.report = res
        self.plan.clear()
        self.selected_dispatch = None
        self._build_shop()

        if gs.over:
            # 结束了就把自动存档清掉，免得标题页一直挂着「继续」
            try:
                from ..core import save as SV
                SV.delete("auto")
            except Exception:
                pass
            self.app.goto_result(gs)
            return

        # 每夜自动存一次。玩家中途关窗口也不会丢进度。
        try:
            from ..core import save as SV
            SV.save(gs, "auto")
        except Exception:
            pass

        if res.faith_delta < 0:
            A.play("fail")
            self.app.shake.fire(4.0)

        elif res.gold_delta > 0:
            A.play("chime")
        self.toast.show("第 %d 夜过去了。" % res.night, "info")

    # ---- 更新 ----
    def update(self, dt):
        self.t += dt
        self.snow.update(dt, wind=0.2)
        self.toast.update(dt)
        self.embers.update(dt)
        if self.t % 0.12 < dt:
            self.embers.emit((150, 660), 1)
        if self.faith_flash > 0:
            self.faith_flash = max(0.0, self.faith_flash - dt)

    # ---- 绘制 ----
    def draw(self, surf):
        bg = art.load_cover("main_bg", (T.WIDTH, T.HEIGHT))
        surf.blit(art.dim(bg, 150), (0, 0))
        self.snow.draw(surf)
        self.embers.draw(surf)

        h = draw_header(surf, self.gs)
        self.btn_menu.draw(surf, 0.016)

        self._draw_dispatches(surf, h)
        self._draw_roster(surf, h)
        self._draw_log(surf)

        self.btn_send.draw(surf, 0.016)
        self.btn_shop.draw(surf, 0.016)
        if self.plan:
            self.btn_clear.draw(surf, 0.016)
        self.toast.draw(surf, T.HEIGHT - 160)

        if self.show_shop:
            self._draw_shop(surf)

    # -- 最近发生了什么 --
    def _draw_log(self, surf):
        """底部流水。玩家靠它知道前几夜到底出了什么事。

        早先只显示 4 行，打到第 9 夜就完全不记得第 5 夜为什么失败了。
        现在显示 7 行，并且把「昨夜」改成「近况」。
        """
        rect = pygame.Rect(24, T.HEIGHT - 150, 760, 132)
        T.panel(surf, rect, T.NIGHT_2, T.NIGHT_3, radius=8, alpha=205)
        T.text(surf, "近况", (rect.x + 12, rect.y + 9), size=11, color=T.DIM)
        y = rect.y + 26
        lines = self.gs.log[-7:]
        for entry in lines:
            txt = entry["text"]
            col = T.SNOW_DIM
            if txt.startswith("[成]"):
                col = T.GOOD
            elif txt.startswith("[败]"):
                col = T.BAD
            elif entry.get("kind") == "end":
                col = T.LAMP
            T.text(surf, txt, (rect.x + 12, y), size=12, color=col)
            y += 15
        if not lines:
            T.text(surf, "还没有发生什么。", (rect.x + 12, y), size=12, color=T.SNOW_FAINT)

    # -- 信 --
    def _draw_dispatches(self, surf, top):
        gs = self.gs
        x = 24
        y = top + 16
        wtot = 760
        self.card_rects = []

        # 今夜天气
        wx = B.WEATHER[gs.forecast]
        T.text(surf, "今夜预报：%s" % wx["name"], (x, y), size=16,
               color=T.LAMP, bold=True)
        T.text(surf, wx["desc"], (x + 130, y + 2), size=12, color=T.SNOW_DIM)
        T.text(surf, "只有七成准。", (x + 130 + T.font(12).size(wx["desc"])[0] + 8, y + 2),
               size=12, color=T.WARN)
        y += 30

        ch = 82
        for d in gs.dispatches:
            rect = pygame.Rect(x, y, wtot, ch)
            self.card_rects.append((rect, d.id))
            sel = (self.selected_dispatch == d.id)
            W.card(surf, rect, hi=sel, accent=T.LAMP if sel else None)

            # 左：路线 + 种类
            rname = B.ROUTES[d.route]["name"]
            kind = B.DISPATCH_KINDS[d.kind]
            kcol = {"normal": T.SNOW_DIM, "urgent": T.WARN, "express": T.CINNABAR}[d.kind]
            T.text(surf, rname, (rect.x + 14, rect.y + 12), size=16,
                   color=T.SNOW, bold=True)
            W.chip(surf, (rect.x + 14, rect.y + 38), kind["name"], color=kcol, size=11)
            T.text(surf, "期限 %d 夜" % d.deadline, (rect.x + 74, rect.y + 40),
                   size=12, color=T.SNOW_DIM)

            # 中间：信原文
            T.text_wrapped(surf, "「%s」" % d.text,
                           pygame.Rect(rect.x + 150, rect.y + 10, 300, 40),
                           size=13, color=T.PAPER)

            # 赏罚
            T.text(surf, "+%d 金" % d.reward, (rect.x + 150, rect.y + 54),
                   size=13, color=T.LAMP)
            T.text(surf, "-%d 信" % d.penalty, (rect.x + 214, rect.y + 54),
                   size=13, color=T.BAD)

            # 右：当前指派
            rid, hid = self.plan.get(d.id, (None, None))
            r = gs.rider_by_id(rid) if rid else None
            hh = gs.horse_by_id(hid) if hid else None

            ax = rect.right - 250
            if r and hh:
                # 关键：用「预报」算，不是用实际天气。
                # 早先这里没传天气，travel_nights 就用了 self.weather（真实值），
                # 等于在派出去之前就告诉玩家能不能赶上——整个「赌预报」的设计就废了。
                nights_fc = gs.travel_nights(d, r, hh, gs.forecast)
                # 顺便把「天气若变坏会变成几夜」也提示出来，让风险可见但不直接给答案
                worst = max(gs.travel_nights(d, r, hh, w) for w in ("rain", "snow", "storm"))
                ok = nights_fc <= d.deadline
                W.chip(surf, (ax, rect.y + 26), "%s + %s" % (r.name, hh.name),
                       color=T.GOOD if ok else T.WARN, size=12)
                T.text(surf, "按预报 %d 夜" % nights_fc, (ax, rect.y + 54), size=12,
                       color=T.GOOD if ok else T.WARN)
                if not ok:
                    T.text(surf, "赶不上", (ax + 82, rect.y + 54), size=12, color=T.BAD)
                elif worst > d.deadline:
                    T.text(surf, "变天则误", (ax + 82, rect.y + 54), size=11, color=T.WARN)
            else:
                T.text(surf, "未指派", (ax, rect.y + 30), size=13, color=T.SNOW_FAINT)
                T.text(surf, "点这里，再点骑手", (ax, rect.y + 50), size=11,
                       color=T.SNOW_FAINT)

            y += ch + 8

    # -- 骑手 / 马 --
    def _portrait_for(self, rider, idx):
        """给骑手挑一张立绘。开局两位是固定的，雇来的按序号轮换。"""
        if rider.name == "老陈":
            return "rider_old"
        if rider.name == "小满":
            return "rider_young"
        return ["rider_woman", "rider_scar", "rider_young", "rider_woman"][idx % 4]

    def _horseportrait_for(self, horse, idx):
        return "horse_dark" if idx % 2 == 0 else "horse_grey"

    def _draw_roster(self, surf, top):
        gs = self.gs
        x = 800
        y = top + 16
        self.rider_rects = []
        self.horse_rects = []

        T.text(surf, "骑手", (x, y), size=13, color=T.DIM, bold=True)
        y += 22
        for i, r in enumerate(gs.riders):
            used = any(rr == r.id for rr, _ in self.plan.values())
            away = gs.is_busy(rider_id=r.id)
            rect = pygame.Rect(x, y, 220, 56)
            self.rider_rects.append((rect, r.id))
            prog = ""
            if away:
                t = gs.trip_of_rider(r.id)
                if t is not None:
                    prog = "在途 %d%%" % int(t.ratio * 100)
            self._draw_unit(surf, rect, r.name, r.speed, r.stamina,
                            r.state, used, "rider", self._portrait_for(r, i),
                            away=away, away_text=prog)
            y += 62

        y += 6
        T.text(surf, "马", (x, y), size=13, color=T.DIM, bold=True)
        y += 22
        for i, hh in enumerate(gs.horses):
            used = any(hid == hh.id for _, hid in self.plan.values())
            away = gs.is_busy(horse_id=hh.id)
            rect = pygame.Rect(x, y, 220, 56)
            self.horse_rects.append((rect, hh.id))
            prog = ""
            if away:
                t = gs.trip_of_horse(hh.id)
                if t is not None:
                    prog = "在途 %d%%" % int(t.ratio * 100)
            self._draw_unit(surf, rect, hh.name, hh.speed, hh.condition,
                            "idle", used, "horse", self._horseportrait_for(hh, i),
                            away=away, away_text=prog)
            y += 62

        # 休息提示。早先「什么都不派 = 休息」这件事只写在 GDD 里，
        # 新玩家不会知道。压在背景上太淡，先垫一层半透明底再写字。
        resting = [r for r in gs.riders
                   if r.state == "idle"
                   and not gs.is_busy(rider_id=r.id)
                   and r.id not in {rr for rr, _ in self.plan.values()}]
        hint_y = y + 4
        if hint_y < T.HEIGHT - 170:
            box = pygame.Rect(x - 6, hint_y - 4, 232, 36)
            T.panel(surf, box, T.INK, T.NIGHT_3, radius=6, alpha=170)
            if resting:
                T.text(surf, "歇着：%s（体力 +%d/夜）" % (
                    "、".join(r.name for r in resting),
                    int(B.REST_STAMINA_GAIN)),
                    (x, hint_y), size=11, color=T.SNOW_DIM)
            else:
                T.text(surf, "全员出动，没人歇着。",
                       (x, hint_y), size=11, color=T.WARN)
            T.text(surf, "马不跑也会自己回 +%d/夜" % int(B.HORSE_NATURAL_RECOVERY),
                   (x, hint_y + 16), size=11, color=T.SNOW_DIM)

    def _draw_unit(self, surf, rect, name, speed, meter, state, used, kind,
                   portrait_id=None, away=False, away_text=""):
        avail = (state == "idle") and not used and not away
        W.card(surf, rect, hi=avail and state == "idle",
               accent=T.LAMP_DIM if avail else None, alpha=225)

        # 头像
        px = rect.x + 8
        pw = 40
        if portrait_id:
            thumb = art.load_cover(portrait_id, (pw, rect.height - 12))
            # 圆角裁一圈
            mask = pygame.Surface(thumb.get_size(), pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(),
                             border_radius=6)
            thumb = thumb.copy()
            thumb.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            surf.blit(thumb, (px, rect.y + 6))
            if not avail or away:
                ov = pygame.Surface(thumb.get_size(), pygame.SRCALPHA)
                ov.fill((10, 16, 22, 150))
                ov.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                surf.blit(ov, (px, rect.y + 6))
        else:
            pw = 0

        tx = px + pw + 10
        col = T.SNOW if state == "idle" else T.SNOW_FAINT
        T.text(surf, name, (tx, rect.y + 7), size=14, color=col, bold=True)
        T.text(surf, "%.2f" % speed, (rect.right - 12, rect.y + 8), size=12,
               color=T.LAMP, anchor="topright")
        # 体力 / 状态条
        bcol = T.GOOD if meter > 60 else (T.WARN if meter > 30 else T.BAD)
        barw = rect.right - tx - 46
        T.bar(surf, (tx, rect.y + 32, barw, 6), meter, 100, color=bcol)
        T.text(surf, "%d" % int(meter), (rect.right - 12, rect.y + 28), size=11,
               color=T.SNOW_DIM, anchor="topright")
        if away:
            T.text(surf, away_text or "在途", (rect.right - 12, rect.y + 42),
                   size=11, color=T.LAMP, anchor="topright")
        elif state == "injured":
            T.text(surf, "伤", (rect.right - 12, rect.y + 42), size=11,
                   color=T.BAD, anchor="topright")
        elif used:
            T.text(surf, "已派", (rect.right - 12, rect.y + 42), size=11,
                   color=T.SNOW_FAINT, anchor="topright")

    # -- 商店 --
    def _draw_shop(self, surf):
        n_rows = len(self.shop_btns)
        panel_h = 120 + n_rows * 46 + 40
        panel = pygame.Rect(0, 0, 560, panel_h)
        panel.center = (T.WIDTH // 2, T.HEIGHT // 2)
        self.shop_rect = panel.copy()
        ov = pygame.Surface((T.WIDTH, T.HEIGHT), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        surf.blit(ov, (0, 0))
        T.panel(surf, panel, T.NIGHT_2, T.NIGHT_3, radius=14)

        T.text(surf, "整备", (panel.left + 30, panel.top + 22), size=20, color=T.LAMP)
        T.text(surf, "现在有 %d 金" % int(self.gs.gold),
               (panel.right - 70, panel.top + 28), size=13, color=T.SNOW_DIM,
               anchor="topright")

        # 右上角关闭按钮
        self.btn_shop_close.rect = pygame.Rect(panel.right - 42, panel.top + 14, 30, 30)
        self.btn_shop_close.enabled = True
        self.btn_shop_close.draw(surf, 0.016)

        y = panel.top + 62
        for key, btn, cost in self.shop_btns:
            r = pygame.Rect(panel.left + 30, y, panel.width - 60, 36)
            btn.rect = r
            btn.enabled = (self.gs.gold >= cost)
            bg, border, fg = btn._colors()
            T.panel(surf, r, bg, border, radius=8)
            # 左对齐名字，右对齐价格——不要两个都居中，会撞在一起
            T.text(surf, btn.label, (r.x + 14, r.centery), size=13,
                   color=fg, anchor="midleft")
            pcol = T.DIM if not btn.enabled else T.LAMP
            T.text(surf, "%d 金" % cost, (r.right - 14, r.centery),
                   size=12, color=pcol, anchor="midright")
            y += 46

        T.text(surf, "点右上角 × 或面板外面关闭（Esc 也行）",
               (panel.centerx, panel.bottom - 22), size=12,
               color=T.SNOW_FAINT, anchor="center")


# ────────────────────────── 结算场景 ──────────────────────────
class ResultScene:
    def __init__(self, app, gs: GameState):
        self.app = app
        self.gs = gs
        self.t = 0.0
        self.snow = fx.Snow(T.WIDTH, T.HEIGHT, 260, seed=23)
        r = gs.result or {}
        self.win = r.get("survived") and gs.faith >= B.SURVIVE_FAITH
        self.btn_again = W.Button((T.WIDTH // 2 - 170, T.HEIGHT - 96, 160, 46),
                                  "再来一局", kind="primary", size=15)
        self.btn_title = W.Button((T.WIDTH // 2 + 10, T.HEIGHT - 96, 160, 46),
                                  "回标题", kind="normal", size=15)

    def handle(self, ev):
        if self.btn_again.handle(ev):
            self.app.start_new_game()
        if self.btn_title.handle(ev):
            self.app.goto_title()

    def update(self, dt):
        self.t += dt
        self.snow.update(dt, wind=0.3)

    def draw(self, surf):
        key = "ending_good" if self.win else "ending_bad"
        surf.blit(art.load_cover(key, (T.WIDTH, T.HEIGHT)), (0, 0))
        T.vignette(surf, 140)
        self.snow.draw(surf)

        r = self.gs.result or {}
        cy = 210
        head = "守住了" if self.win else "没守住"
        hcol = T.LAMP if self.win else T.CINNABAR
        T.text(surf, head, (T.WIDTH // 2, cy), size=46, color=hcol,
               anchor="center", shadow=True)
        T.text(surf, r.get("why", ""), (T.WIDTH // 2, cy + 54), size=16,
               color=T.SNOW, anchor="center", shadow=True)

        # 数据
        box = pygame.Rect(0, 0, 560, 150)
        box.center = (T.WIDTH // 2, cy + 170)
        T.panel(surf, box, T.NIGHT_2, T.NIGHT_3, radius=12, alpha=225)

        items = [
            ("最终信", "%d / %d" % (int(self.gs.faith), B.MAX_FAITH)),
            ("送达率", ("%.0f%%" % (r.get("rate", 0) * 100)) if r.get("total") else "—"),
            ("送达 / 总", "%d / %d" % (r.get("delivered", 0), r.get("total", 0))),
            ("评价", r.get("rating", "—")),
        ]
        for i, (k, v) in enumerate(items):
            col = i % 4
            cx = box.left + 70 + col * 140
            # 标签用 SNOW_DIM 而不是 DIM：DIM 在深色面板上几乎看不见，
            # 玩家只能看到数值、不知道数值是什么意思。
            T.text(surf, k, (cx, box.top + 34), size=13, color=T.SNOW_DIM,
                   anchor="center")
            T.text(surf, v, (cx, box.top + 68), size=22,
                   color=T.LAMP if i == 3 else T.SNOW, anchor="center", bold=True)

        self.btn_again.draw(surf, 0.016)
        self.btn_title.draw(surf, 0.016)
