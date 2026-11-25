# -*- coding: utf-8 -*-
"""主界面上「点一下就会出事」的两处：存盘退出、修路文案。

这两个都不是核心规则 bug——纯逻辑测试跑一百遍也发现不了，因为它们只在
「玩家真的点了一下」的时候才出现（文档里 S-03「整备面板只能用 Esc 关闭」
就是同一类）。所以这里直接造 scene，喂一个真实的鼠标事件。

不需要窗口：SDL 用 dummy driver，只测事件分发和写盘，不测绘制。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame                       # noqa: E402

from relay.core import save as SV   # noqa: E402
from relay.core.sim import GameState  # noqa: E402
from relay.ui import app as APP     # noqa: E402
from relay.ui import scenes as S    # noqa: E402


def setUpModule():
    pygame.init()


def tearDownModule():
    pygame.quit()


class FakeApp:
    """只记「被叫了什么」，不建窗口、不加载素材。"""

    def __init__(self):
        self.saved = 0
        self.titled = 0

    def save_progress(self):
        self.saved += 1
        return True

    def goto_title(self):
        self.titled += 1


def click(scene, rect):
    scene.handle(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))


class TestStoreAndQuit(unittest.TestCase):
    """右上角那个按钮：v0.5.0 之前它叫「菜单」，点了直接回标题，
    不存档、不确认——一整局（25 分钟）就没了。"""

    def test_clicking_it_saves_before_leaving(self):
        app = FakeApp()
        scene = S.PlayScene(app, GameState(seed=7))
        click(scene, scene.btn_menu.rect)
        self.assertEqual(app.saved, 1, "回标题之前必须先存一次盘")
        self.assertEqual(app.titled, 1)

    def test_label_matches_what_it_does(self):
        scene = S.PlayScene(FakeApp(), GameState(seed=7))
        self.assertEqual(scene.btn_menu.label, "存盘退出")


class TestSaveProgress(unittest.TestCase):
    """App.save_progress()：关窗口和「存盘退出」共用的那一次写盘。"""

    def test_writes_a_save_that_can_be_loaded(self):
        gs = GameState(seed=11)
        gs.night = 5
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(SV, "saves_dir", lambda: Path(td)):
                ok = APP.App.save_progress(SimpleNamespace(gs=gs))
                self.assertTrue(ok)
                self.assertTrue(SV.exists("auto"))
                back = SV.load("auto")
            self.assertIsNotNone(back, "写进去的存档必须能读回来")
            self.assertEqual(back.night, 5)
            self.assertEqual(back.seed, 11)

    def test_over_game_is_not_saved(self):
        gs = GameState(seed=11)
        gs.over = True
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(SV, "saves_dir", lambda: Path(td)):
                self.assertFalse(APP.App.save_progress(SimpleNamespace(gs=gs)))
                self.assertFalse(SV.exists("auto"))


class TestRepairLabel(unittest.TestCase):
    """整备面板的修路按钮。

    v0.5.0 写的是「修 北口（3→2 夜）」——但 3 和 2 是**路程**，不是夜数。
    北口走几夜取决于天气和脚力（晴天快组合 1 夜，暴雪慢组合 3 夜），
    修完只是路程短一截。玩家照着「少一夜」去算余量会算错。
    """

    def test_label_says_distance_not_nights(self):
        label = S.repair_label("北口", 3)
        self.assertIn("路程", label)
        self.assertIn("3→2", label)
        self.assertNotIn("夜", label)

    def test_all_routes(self):
        from relay.core import balance as B
        for rk, rd in B.ROUTES.items():
            cur = rd["distance"] - 1
            label = S.repair_label(rd["name"], cur)
            self.assertIn("路程 %d→%d" % (cur, cur - 1), label, rk)


if __name__ == "__main__":
    unittest.main()
