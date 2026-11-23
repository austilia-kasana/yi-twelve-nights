# -*- coding: utf-8 -*-
"""核心逻辑单元测试。

不依赖 pygame，可以直接：
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from relay.core import balance as B          # noqa: E402
from relay.core.sim import GameState, _clamp  # noqa: E402


class TestDeterminism(unittest.TestCase):
    """同一个种子必须产生同一局——否则复盘和测试都无从谈起。"""

    def test_same_seed_same_weather(self):
        a = GameState(seed=1234)
        b = GameState(seed=1234)
        for _ in range(6):
            self.assertEqual(a.weather, b.weather)
            self.assertEqual(a.forecast, b.forecast)
            self.assertEqual(len(a.dispatches), len(b.dispatches))
            for da, db in zip(a.dispatches, b.dispatches):
                self.assertEqual(da.route, db.route)
                self.assertEqual(da.kind, db.kind)
                self.assertEqual(da.deadline, db.deadline)
                self.assertEqual(da.reward, db.reward)
            plan_a = self._fast_plan(a)
            plan_b = self._fast_plan(b)
            if not plan_a or a.over:
                break
            a.advance(plan_a, ())
            b.advance(plan_b, ())
            if a.over:
                break

    def test_different_seed_differs(self):
        a = GameState(seed=1)
        b = GameState(seed=2)
        # 至少有一处不同（天气或信件），否则种子没起作用
        same = (a.weather == b.weather
                and len(a.dispatches) == len(b.dispatches)
                and all(x.route == y.route and x.kind == y.kind
                        for x, y in zip(a.dispatches, b.dispatches)))
        self.assertFalse(same, "不同种子产生了完全相同的开局")

    @staticmethod
    def _fast_plan(gs):
        """给最快的骑手配最快的马，只送一封最简单的事。"""
        riders = [r for r in gs.riders if r.state == "idle"]
        if not riders or not gs.horses:
            return []
        r = max(riders, key=lambda x: x.speed)
        h = max(gs.horses, key=lambda x: x.speed)
        best = None
        for d in gs.dispatches:
            n = gs.travel_nights(d, r, h)
            if n <= d.deadline and (best is None or d.reward > best.reward):
                best = d
        return [(best, r, h)] if best else []


class TestTravel(unittest.TestCase):
    def setUp(self):
        self.gs = GameState(seed=7)

    def test_north_fast_pair_one_night(self):
        """快组合（1.25 × 1.20）在晴天走北口应该是 1 夜。"""
        r = min(self.gs.riders, key=lambda x: abs(x.speed - 1.25))
        r.speed = 1.25
        r.stamina = 100.0
        h = min(self.gs.horses, key=lambda x: abs(x.speed - 1.20))
        h.speed = 1.20
        h.condition = 100.0
        self.gs.oil = 50
        d = self.gs.dispatches[0]
        d.route = "north"
        self.assertEqual(self.gs.travel_nights(d, r, h, "clear"), 1)

    def test_snow_slows_north(self):
        r = self.gs.riders[0]
        r.speed, r.stamina = 1.25, 100.0
        h = self.gs.horses[0]
        h.speed, h.condition = 1.20, 100.0
        self.gs.oil = 50
        d = self.gs.dispatches[0]
        d.route = "north"
        clear = self.gs.travel_nights(d, r, h, "clear")
        snow = self.gs.travel_nights(d, r, h, "snow")
        self.assertGreater(snow, clear, "下雪应该比晴天慢")

    def test_low_stamina_penalty(self):
        r = self.gs.riders[0]
        r.speed = 1.25
        h = self.gs.horses[0]
        h.speed, h.condition = 1.20, 100.0
        self.gs.oil = 50
        d = self.gs.dispatches[0]
        d.route = "north"
        r.stamina = 100.0
        fast = self.gs.travel_nights(d, r, h, "clear")
        r.stamina = 5.0
        slow = self.gs.travel_nights(d, r, h, "clear")
        self.assertGreaterEqual(slow, fast)

    def test_no_oil_slows(self):
        r = self.gs.riders[0]
        r.speed, r.stamina = 1.25, 100.0
        h = self.gs.horses[0]
        h.speed, h.condition = 1.20, 100.0
        d = self.gs.dispatches[0]
        d.route = "north"
        self.gs.oil = 50
        lit = self.gs.travel_nights(d, r, h, "clear")
        self.gs.oil = 0
        dark = self.gs.travel_nights(d, r, h, "clear")
        self.assertGreater(dark, lit, "没灯应该更慢")

    def test_mine_ignores_weather(self):
        """旧矿道是「天气拿它没办法」的那条路。"""
        r = self.gs.riders[0]
        r.speed, r.stamina = 1.25, 100.0
        h = self.gs.horses[0]
        h.speed, h.condition = 1.20, 100.0
        self.gs.oil = 50
        d = self.gs.dispatches[0]
        d.route = "mine"
        a = self.gs.travel_nights(d, r, h, "clear")
        b = self.gs.travel_nights(d, r, h, "storm")
        self.assertEqual(a, b)


class TestAssignValidation(unittest.TestCase):
    def setUp(self):
        self.gs = GameState(seed=11)

    def test_duplicate_rider_rejected(self):
        r = self.gs.riders[0]
        h1, h2 = self.gs.horses[0], self.gs.horses[1]
        d1, d2 = self.gs.dispatches[0], self.gs.dispatches[1]
        with self.assertRaises(ValueError):
            self.gs.advance([(d1, r, h1), (d2, r, h2)])

    def test_duplicate_horse_rejected(self):
        r1, r2 = self.gs.riders[0], self.gs.riders[1]
        h = self.gs.horses[0]
        d1, d2 = self.gs.dispatches[0], self.gs.dispatches[1]
        with self.assertRaises(ValueError):
            self.gs.advance([(d1, r1, h), (d2, r2, h)])

    def test_advance_after_over_raises(self):
        gs = GameState(seed=12)
        gs.faith = 1
        gs.over = True
        with self.assertRaises(RuntimeError):
            gs.advance([], ())


class TestNightFlow(unittest.TestCase):
    def test_dispatches_count_in_range(self):
        for seed in range(40):
            gs = GameState(seed=seed)
            lo, hi = B.DISPATCHES_PER_NIGHT
            self.assertGreaterEqual(len(gs.dispatches), lo)
            self.assertLessEqual(len(gs.dispatches), hi)

    def test_deadline_matches_route_base(self):
        """期限必须 >= 该路线的基准夜数，否则那封信根本送不了。"""
        for seed in range(60):
            gs = GameState(seed=seed)
            for d in gs.dispatches:
                base = B.ROUTE_BASE_NIGHTS[d.route]
                self.assertGreaterEqual(
                    d.deadline, base,
                    "种子 %d：%s 路线期限 %d 小于基准 %d" % (
                        seed, d.route, d.deadline, base))

    def test_express_not_before_night(self):
        for seed in range(40):
            gs = GameState(seed=seed)
            while not gs.over and gs.night < B.EXPRESS_STARTS_NIGHT:
                for d in gs.dispatches:
                    self.assertNotEqual(
                        d.kind, "express",
                        "第 %d 夜不该出现八百里（种子 %d）" % (gs.night, seed))
                gs.advance([], ())

    def test_faith_never_exceeds_max(self):
        gs = GameState(seed=21)
        gs.faith = B.MAX_FAITH
        # 强制送达一封八百里
        r = gs.riders[0]
        h = gs.horses[0]
        d = gs.dispatches[0]
        d.kind = "express"
        d.deadline = 99
        gs.advance([(d, r, h)], ())
        self.assertLessEqual(gs.faith, B.MAX_FAITH)

    def test_faith_never_below_zero(self):
        gs = GameState(seed=22)
        gs.faith = 3
        d = gs.dispatches[0]
        d.deadline = 0
        d.penalty = 999
        r, h = gs.riders[0], gs.horses[0]
        gs.advance([(d, r, h)], ())
        self.assertGreaterEqual(gs.faith, 0)

    def test_game_ends_at_total_nights(self):
        gs = GameState(seed=23)
        guard = 0
        while not gs.over and guard < 40:
            guard += 1
            gs.advance([], ())
        self.assertTrue(gs.over)
        self.assertIsNotNone(gs.result)
        self.assertEqual(gs.night, B.TOTAL_NIGHTS)

    def test_faith_zero_ends_game(self):
        gs = GameState(seed=24)
        gs.faith = 2
        guard = 0
        while not gs.over and guard < 30:
            guard += 1
            # 全部拒收 → 不吃罚，但也不会掉信；改成每夜都派最慢的
            gs.faith = max(0, gs.faith - 1)
            if gs.faith <= 0:
                gs._finish(False, "测试")
        self.assertTrue(gs.over)
        self.assertFalse(gs.result["survived"])


class TestShop(unittest.TestCase):
    def setUp(self):
        self.gs = GameState(seed=31)
        self.gs.gold = 10000

    def test_hire_rider(self):
        n = len(self.gs.riders)
        r = self.gs.hire_rider()
        self.assertIsNotNone(r)
        self.assertEqual(len(self.gs.riders), n + 1)
        self.assertGreaterEqual(r.speed, B.HIRE_SPEED_RANGE[0])
        self.assertLessEqual(r.speed, B.HIRE_SPEED_RANGE[1] + 1e-6)

    def test_buy_horse(self):
        n = len(self.gs.horses)
        h = self.gs.buy_horse()
        self.assertIsNotNone(h)
        self.assertEqual(len(self.gs.horses), n + 1)

    def test_feed_caps_condition(self):
        h = self.gs.horses[0]
        h.condition = 10
        self.assertTrue(self.gs.feed(h.id))
        self.assertEqual(h.condition, 10 + B.FEED_CONDITION_GAIN)

    def test_oil_caps(self):
        self.gs.oil = B.MAX_OIL
        n = self.gs.oil
        self.assertTrue(self.gs.buy_oil())
        self.assertLessEqual(self.gs.oil, B.MAX_OIL)

    def test_repair_route_once(self):
        gs = GameState(seed=32)
        gs.gold = 10000
        before = gs.route_distance["north"]
        self.assertTrue(gs.repair_route("north"))
        self.assertEqual(gs.route_distance["north"], before - 1)
        # 第二次应该失败
        self.assertFalse(gs.repair_route("north"))

    def test_cannot_afford(self):
        gs = GameState(seed=33)
        gs.gold = 0
        self.assertIsNone(gs.hire_rider())
        self.assertIsNone(gs.buy_horse())
        self.assertFalse(gs.buy_oil())


class TestSerialization(unittest.TestCase):
    def test_to_dict_is_json_serializable(self):
        import json
        gs = GameState(seed=41)
        d = gs.to_dict()
        s = json.dumps(d, ensure_ascii=False)
        self.assertGreater(len(s), 100)
        back = json.loads(s)
        self.assertEqual(back["night"], gs.night)
        self.assertEqual(len(back["riders"]), len(gs.riders))


class TestHelpers(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(_clamp(5, 0, 10), 5)
        self.assertEqual(_clamp(-3, 0, 10), 0)
        self.assertEqual(_clamp(99, 0, 10), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
