# -*- coding: utf-8 -*-
"""主循环与场景切换。

对外只有一个入口：App().run()
"""

from __future__ import annotations

import sys
import traceback

import pygame

from ..core import balance as B
from ..core.sim import GameState
from ..audio import player as A
from . import art, fx, theme as T
from . import scenes as S


class App:
    def __init__(self, seed=None, headless_frames: int = 0,
                 shot_path: str = None, shot_at: int = 40,
                 shot_scene: str = "title", autoplay: int = 0):
        self.seed = seed
        self.gs = None
        self.scene = None
        self.running = True
        self.shake = fx.Shake()
        self.fade = fx.Fade()
        self.clock = pygame.time.Clock()
        self.headless_frames = headless_frames
        self.shot_path = shot_path
        self.shot_at = shot_at
        self.autoplay = autoplay          # >0 时自动推进 N 夜（无头验证用）
        self._frame = 0
        self._shots_taken = 0

        pygame.init()
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
        except Exception:
            pass
        A.init(enable=True)
        A.start_ambient()

        flags = pygame.DOUBLEBUF
        self.screen = pygame.display.set_mode((T.WIDTH, T.HEIGHT), flags)
        pygame.display.set_caption(T.TITLE)
        self._set_icon()

        # 预加载全部素材，避免开局卡
        art.load_cover("title", (T.WIDTH, T.HEIGHT))
        art.load_cover("main_bg", (T.WIDTH, T.HEIGHT))

        if shot_scene == "play":
            self.start_new_game()
            if self.autoplay:
                self._autoplay(self.autoplay)
        elif shot_scene == "result":
            self.start_new_game()
            self._autoplay(self.autoplay or 12)
        elif shot_scene == "help":
            # 自测用：直接打开标题界面并展开帮助面板，方便截图核查
            self.goto_title()
            if hasattr(self.scene, "show_help"):
                self.scene.show_help = True
        else:
            self.goto_title()

    def _set_icon(self):
        try:
            icon = art.fit("title", (64, 64))
            pygame.display.set_icon(icon)
        except Exception:
            pass

    # ────────────────────── 场景切换 ──────────────────────
    def goto_title(self):
        self.gs = None
        self.scene = S.TitleScene(self)
        self.fade.alpha = 0.0

    def start_new_game(self):
        # 开新局前把上一局的自动存档清掉——否则标题页会挂着一个
        # 属于另一局的「继续」，点进去是别人的进度。
        try:
            from ..core import save as SV
            SV.delete("auto")
        except Exception:
            pass
        self.gs = GameState(seed=self.seed)
        self.scene = S.PlayScene(self, self.gs)
        self.fade.alpha = 0.0

    def goto_result(self, gs):
        # 一局结束就把完整对局写盘，方便玩家复盘
        try:
            from ..core import runlog
            paths = runlog.save(gs)
            if paths.get("text"):
                print("对局日志: %s" % paths["text"])
        except Exception as e:
            print("对局日志写入失败: %s" % e)
        self.scene = S.ResultScene(self, gs)

    # ────────────────────── 无头自动推进（仅自测） ──────────────────────
    def _autoplay(self, nights: int):
        """按一个简单策略自动玩 N 夜，用来在无头环境截主界面图。"""
        from ..core import balance as B
        guard = 0
        while (self.gs and not self.gs.over and self.gs.night <= nights
               and guard < 40):
            guard += 1
            gs = self.gs
            # 一律走可用性 API：在途的人马不能派，否则 advance() 会抛
            # ValueError("还在路上")，被下面的 except 吞掉，autoplay 会静默停住。
            riders = gs.available_riders()
            horses = gs.available_horses()
            plan = []
            used_r, used_h = set(), set()
            # 贪心：给每封信挑最快的可用组合
            scored = []
            for d in gs.dispatches:
                best = None
                for r in riders:
                    if r.id in used_r:
                        continue
                    for h in horses:
                        if h.id in used_h:
                            continue
                        n = gs.travel_nights(d, r, h)
                        ok = n <= d.deadline
                        ev = (d.reward if ok else -d.penalty * 3) - n * 2
                        if best is None or ev > best[0]:
                            best = (ev, r, h)
                if best and best[0] > 0:
                    scored.append((best[0], d, best[1], best[2]))
            scored.sort(key=lambda x: -x[0])
            for ev, d, r, h in scored:
                if r.id in used_r or h.id in used_h:
                    continue
                used_r.add(r.id)
                used_h.add(h.id)
                plan.append((d, r, h))
            resting = {r.id for r in gs.riders
                       if r.state == "idle"
                       and not gs.is_busy(rider_id=r.id)
                       and r.id not in used_r}
            try:
                gs.advance(plan, resting)
            except Exception:
                break
            if gs.over:
                self.goto_result(gs)
                break
            self.scene = S.PlayScene(self, gs)

    # ────────────────────── 主循环 ──────────────────────
    def run(self):
        while self.running:
            dt = self.clock.tick(T.FPS) / 1000.0
            dt = min(dt, 0.05)     # 防止切换窗口时巨大 dt
            self._frame += 1

            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self._save_on_exit()
                    self.running = False
                elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_F4 and \
                        (ev.mod & pygame.KMOD_ALT):
                    self._save_on_exit()
                    self.running = False
                else:
                    if self.scene:
                        try:
                            self.scene.handle(ev)
                        except Exception:
                            traceback.print_exc()

            if not self.running:
                break

            try:
                self.scene.update(dt)
                self.shake.update(dt)
                self.fade.update(dt)
                self._draw()
            except Exception:
                traceback.print_exc()
                self.running = False

            pygame.display.flip()

            # 无头截图
            if self.shot_path and self._frame == self.shot_at:
                try:
                    pygame.image.save(self.screen, self.shot_path)
                    self._shots_taken += 1
                    print("截图已保存: %s" % self.shot_path)
                except Exception as e:
                    print("截图失败: %s" % e)

            if self.headless_frames and self._frame >= self.headless_frames:
                self.running = False

        pygame.quit()

    def _save_on_exit(self):
        """关窗口时存一次。一局 25 分钟，不能让人因为切窗口丢掉进度。"""
        self.save_progress()

    def save_progress(self):
        """把当前进度写进自动存档。

        三个地方要用：关窗口（QUIT / Alt+F4）、主界面「存盘退出」、
        以及以后可能加的暂停菜单——所以抽出来，别再各写一份。
        成功返回 True；没有局在打、或者已经结算、或者写盘失败都返回 False。
        """
        if not self.gs or self.gs.over:
            return False
        try:
            from ..core import save as SV
            return SV.save(self.gs, "auto") is not None
        except Exception:
            return False

    def _draw(self):
        buf = pygame.Surface((T.WIDTH, T.HEIGHT))
        self.scene.draw(buf)
        self.fade.draw(buf)
        if self.shake.t > 0:
            ox, oy = self.shake.offset()
            self.screen.fill((0, 0, 0))
            self.screen.blit(buf, (ox, oy))
        else:
            self.screen.blit(buf, (0, 0))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=T.TITLE)
    ap.add_argument("--seed", type=int, default=None, help="固定随机种子（复盘用）")
    ap.add_argument("--assets-check", action="store_true", help="只检查素材完整性")
    ap.add_argument("--frames", type=int, default=0, help="跑 N 帧后退出（自测用）")
    ap.add_argument("--shot", default=None, help="在第 --shot-at 帧保存截图到此路径")
    ap.add_argument("--shot-at", type=int, default=40)
    ap.add_argument("--shot-scene", default="title",
                    choices=["title", "play", "result", "help"])
    ap.add_argument("--autoplay", type=int, default=0,
                    help="无头自动玩 N 夜（配合 --shot-scene play）")
    args = ap.parse_args(argv)

    if args.assets_check:
        pygame.init()
        pygame.display.set_mode((64, 64))
        r = art.report()
        print("素材目录: %s" % r["root"])
        print("存在: %s" % r["exists"])
        print("完整: %d / %d" % (r["ok"], r["total"]))
        if r["missing"]:
            print("缺失: %s" % ", ".join(r["missing"]))
        print("中文字体: %s" % ("有" if T.font_ok() else "缺（会退回默认字体）"))
        pygame.quit()
        return 0 if r["ok"] == r["total"] else 1

    try:
        app = App(seed=args.seed, headless_frames=args.frames,
                  shot_path=args.shot, shot_at=args.shot_at,
                  shot_scene=args.shot_scene, autoplay=args.autoplay)
        app.run()
    except Exception:
        traceback.print_exc()
        return 1
    return 0
