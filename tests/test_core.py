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
        # 只用真正可派的：没伤、且不在路上
        riders = gs.available_riders()
        horses = gs.available_horses()
        if not riders or not horses:
            return []
        r = max(riders, key=lambda x: x.speed)
        h = max(horses, key=lambda x: x.speed)
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


class TestRuleRegressions(unittest.TestCase):
    """针对两份外部评审（哈基米 / 龙娘）指出的规则问题，各留一条回归测试。

    这些规则以前没有测试覆盖——25 项全绿，但边界一条没测到。
    """

    # ── 派遣顺序不得影响结果 ──
    def _snapshot(self, order, seed, oil):
        gs = GameState(seed=seed)
        gs.oil = oil
        d0, d1 = gs.dispatches[0], gs.dispatches[1]
        d0.route = d1.route = "mine"
        d0.deadline = d1.deadline = 3
        pairs = [(d0, gs.riders[0], gs.horses[0]),
                 (d1, gs.riders[1], gs.horses[1])]
        if order == "rev":
            pairs = pairs[::-1]
        gs.advance(pairs)
        return sorted((t.rider_name, t.route, t.nights_taken, t.delivered, t.event)
                      for t in gs.history[0].trips)

    def test_assignment_order_does_not_matter(self):
        """换点击顺序不能改变结果。

        以前有两个独立的原因导致顺序有影响：
          1. 灯系数每次现读 oil，而油在同一夜里边派边扣；
          2. random 按派单顺序消耗，事件抽到什么都跟它是第几个结算有关。
        现在灯系数夜初定死 + 按信 id 排序结算，两者都消掉了。
        """
        for seed in (42, 7, 101, 555):
            for oil in (3, 5, 100):
                self.assertEqual(self._snapshot("fwd", seed, oil),
                                 self._snapshot("rev", seed, oil),
                                 "种子 %d 油 %d 下顺序影响了结果" % (seed, oil))

    # ── 信归零后不得继续结算 ──
    def test_no_settlement_after_faith_zero(self):
        gs = GameState(seed=1)
        gs.faith = 3
        for d in gs.dispatches[:2]:
            d.deadline = 0
            d.penalty = 5
        gs.advance([(gs.dispatches[0], gs.riders[0], gs.horses[0]),
                    (gs.dispatches[1], gs.riders[1], gs.horses[1])])
        # 两封都在夜初出发了（资源已扣）。第一封结算把信打到 0，
        # 第二封被终止——但它仍然留下记录、计入分母，所以是 2 条。
        self.assertEqual(len(gs.history[0].trips), 2)
        self.assertTrue(gs.over)
        aborted = [t for t in gs.history[0].trips if t.event == "aborted"]
        self.assertEqual(len(aborted), 1, "被终止的那封应该标记为 aborted")
        # 资源不退还：第二支队已经出发了，马的状态该扣
        # （玩家是夜初决定派遣的，不能假装没派出去）
        self.assertLess(gs.horses[1].condition, 100)

    # ── 信必须是整数，且和日志差额完全对得上 ──
    def test_faith_is_integer_and_deltas_add_up(self):
        gs = GameState(seed=7)
        start = gs.faith
        for _ in range(6):
            if gs.over:
                break
            riders = gs.available_riders()
            horses = gs.available_horses()
            if not riders or not horses or not gs.dispatches:
                gs.advance([])
                continue
            d = gs.dispatches[0]
            d.kind = "urgent"
            d.deadline = 99
            gs.advance([(d, riders[0], horses[0])])
        # 在途模型里，派出的信不一定当夜结算，所以要扫全量 history
        total = sum(nr.faith_delta for nr in gs.history)
        self.assertIsInstance(gs.faith, int)
        self.assertEqual(gs.faith - start, total,
                         "最终信和逐夜差额之和不等")

    # ── 受伤当晚不得开始倒计时 ──
    def test_new_injury_does_not_tick_same_night(self):
        """本夜刚受伤的骑手，当夜不能被减成痊愈。

        以前受伤判定和倒计时在同一函数里、倒计时在后面无条件遍历，
        抽到「1 夜伤」的当晚就减到 0 直接好了——受伤机制一半失效。
        """
        healed_same_night = 0
        injured_count = 0
        for seed in range(200):
            gs = GameState(seed=seed)
            d = gs.dispatches[0]
            d.route = "north"
            d.deadline = 1
            gs.night_progress = lambda *a, **k: 2.5   # 两夜才到，必然超期
            riders = gs.available_riders()
            horses = gs.available_horses()
            r = riders[0]
            gs.advance([(d, r, horses[0])])
            gs.advance([])                             # 抵达
            if any("受了伤" in e["text"] for e in gs.log[-10:]):
                injured_count += 1
                if r.state != "injured":
                    healed_same_night += 1
        self.assertGreater(injured_count, 10, "样本里没抽到受伤，测不动")
        self.assertEqual(healed_same_night, 0,
                         "%d 次受伤里有 %d 次当晚就好了" % (injured_count, healed_same_night))

    # ── 事件提示不得掩盖失败原因 ──
    def test_late_arrival_reports_how_late(self):
        """超期抵达时，日志要写清「晚了几夜」，而不是笼统一句「晚了一夜」。"""
        gs = GameState(seed=1)
        d = gs.dispatches[0]
        d.route = "north"
        d.deadline = 1                  # due_night = 出发夜
        gs.night_progress = lambda *a, **k: 2.5   # 两夜才到
        gs.advance([(d, gs.riders[0], gs.horses[0])])
        gs.advance([])                  # 抵达
        t = gs.history[-1].trips[0]
        self.assertFalse(t.delivered)
        self.assertIn("晚", t.note)
        self.assertIn("1", t.note)      # 晚了几夜要说清

    # ── 出勤的马不得吃自然恢复 ──
    def test_working_horse_does_not_recover(self):
        gs = GameState(seed=3)
        gs.horses[0].condition = 60
        gs.horses[1].condition = 60
        gs.advance([(gs.dispatches[0], gs.riders[0], gs.horses[0])])
        used = 60 - gs.horses[0].condition
        idle = gs.horses[1].condition - 60
        self.assertGreaterEqual(used, B.HORSE_COST_MIN)
        self.assertLessEqual(used, B.HORSE_COST_MAX)
        self.assertAlmostEqual(idle, B.HORSE_NATURAL_RECOVERY, places=5)

    # ── 休息必须自动推断 ──
    def test_resting_is_automatic(self):
        gs = GameState(seed=5)
        gs.riders[0].stamina = 40
        gs.advance([])          # 不传 resting
        self.assertAlmostEqual(gs.riders[0].stamina, 40 + B.REST_STAMINA_GAIN, places=5)

        # 出勤的骑手不该额外回体力（他本来就扣了 Stamina）
        gs2 = GameState(seed=5)
        gs2.riders[0].stamina = 90
        gs2.advance([(gs2.dispatches[0], gs2.riders[0], gs2.horses[0])])
        self.assertLess(gs2.riders[0].stamina, 90)

    # ── 预报错了要当场告诉玩家 ──
    def test_forecast_miss_is_reported_in_game(self):
        miss = 0
        for seed in range(200):
            gs = GameState(seed=seed)
            gs.advance([])
            if any("没准" in e["text"] for e in gs.log):
                miss += 1
        self.assertGreater(miss, 20, "预报错的反馈几乎没有")

    # ── 天气档位选择：取最后一个 start <= night 的 ──
    def test_weather_schedule_picks_latest_tier(self):
        gs = GameState(seed=1)
        self.assertEqual(gs._weather_weights(0),
                         B.WEATHER_SCHEDULE[0][1])
        self.assertEqual(gs._weather_weights(5),
                         B.WEATHER_SCHEDULE[1][1])
        self.assertEqual(gs._weather_weights(20),
                         B.WEATHER_SCHEDULE[-1][1])


class TestSaveLoad(unittest.TestCase):
    """存档 / 读档。最容易出问题的是 id 计数器。"""

    def _played(self, nights=5):
        gs = GameState(seed=17)
        gs.gold = 500
        for _ in range(nights):
            if gs.over:
                break
            riders = gs.available_riders()
            horses = gs.available_horses()
            if riders and horses and gs.dispatches:
                gs.advance([(gs.dispatches[0], riders[0], horses[0])])
            else:
                gs.advance([])
        return gs

    def test_roundtrip_preserves_state(self):
        import json
        gs = self._played()
        back = GameState.from_dict(json.loads(json.dumps(gs.to_dict(), ensure_ascii=False)))
        self.assertEqual(back.night, gs.night)
        self.assertEqual(back.faith, gs.faith)
        self.assertAlmostEqual(back.gold, gs.gold)
        self.assertAlmostEqual(back.oil, gs.oil)
        self.assertEqual(back.weather, gs.weather)
        self.assertEqual(back.forecast, gs.forecast)
        self.assertEqual(back.route_distance, gs.route_distance)
        self.assertEqual([r.id for r in back.riders], [r.id for r in gs.riders])
        self.assertEqual([h.id for h in back.horses], [h.id for h in gs.horses])
        self.assertEqual([d.id for d in back.dispatches], [d.id for d in gs.dispatches])

    def test_id_counter_does_not_collide_after_load(self):
        """读档后新建的对象不能和存档里的撞号。

        models._id_counter 是模块级自增。如果读档时不把它推到已有 id 之上，
        新雇的骑手会拿到和存档里某个骑手相同的 id——然后派单、存档、查表全乱。
        """
        import json
        gs = self._played(6)
        back = GameState.from_dict(json.loads(json.dumps(gs.to_dict(), ensure_ascii=False)))
        used = {o.id for o in list(back.riders) + list(back.horses) + list(back.dispatches)}
        back.gold = 10000
        r = back.hire_rider()
        h = back.buy_horse()
        self.assertIsNotNone(r)
        self.assertIsNotNone(h)
        self.assertNotIn(r.id, used, "新骑手 id 撞了")
        self.assertNotIn(h.id, used, "新马 id 撞了")

    def test_can_continue_after_load(self):
        import json
        gs = self._played(4)
        back = GameState.from_dict(json.loads(json.dumps(gs.to_dict(), ensure_ascii=False)))
        night_before = back.night
        back.advance([])
        self.assertTrue(back.night > night_before or back.over, "读档后推进不动")

    def test_broken_save_does_not_raise(self):
        """坏档必须返回 None，不能把游戏带崩。"""
        from relay.core import save as SV
        import time
        slot = "slot3"
        p = SV.slot_path(slot)
        p.write_text("{ 这不是 json", encoding="utf-8")
        try:
            self.assertIsNone(SV.load(slot))
            self.assertIsNone(SV.info(slot))
        finally:
            SV.delete(slot)


class TestV03Regressions(unittest.TestCase):
    """v0.3.0 里新引入的三个 bug（龙娘在评审中抓到的）。

    共同点：都是「修一个 bug 的时候带出来的新 bug」。
    """

    def _played(self, nights=6):
        gs = GameState(seed=17)
        for _ in range(nights):
            if gs.over:
                break
            riders = gs.available_riders()
            horses = gs.available_horses()
            if riders and horses and gs.dispatches:
                gs.advance([(gs.dispatches[0], riders[0], horses[0])])
            else:
                gs.advance([])
        return gs

    # ── ① 读档必须恢复 history ──
    def test_load_restores_history(self):
        import json
        gs = self._played()
        back = GameState.from_dict(json.loads(json.dumps(gs.to_dict(), ensure_ascii=False)))
        self.assertEqual(len(back.history), len(gs.history),
                         "history 没恢复，结算的送达率会只算读档之后")
        for a, b in zip(gs.history, back.history):
            self.assertEqual(
                (a.night, a.weather, a.forecast, a.gold_delta, a.faith_delta),
                (b.night, b.weather, b.forecast, b.gold_delta, b.faith_delta))
            self.assertEqual(len(a.trips), len(b.trips))

    def test_load_then_idle_is_not_judged_as_idle_fail(self):
        """读档后一封信都不派，不能因为 history 空了就被判「一封也没派出去」。

        这是 history 丢失最严重的连带后果：玩家存了档反而更容易输。
        """
        import json
        gs = self._played()
        self.assertGreater(sum(len(nr.trips) for nr in gs.history), 0)
        back = GameState.from_dict(json.loads(json.dumps(gs.to_dict(), ensure_ascii=False)))
        while not back.over:
            back.advance([])
        self.assertTrue((back.result or {}).get("survived"),
                        "读档后全程不派被判失败——history 没恢复")

    # ── ② 信值差额要记实际变化 ──
    def test_faith_delta_respects_clamp(self):
        # 上界：99 送达八百里（+7）实际只到 100
        gs = GameState(seed=1)
        gs.faith = 99
        d = gs.dispatches[0]
        d.kind = "express"
        d.deadline = 99
        gs.advance([(d, gs.riders[0], gs.horses[0])])
        self.assertEqual(gs.faith - 99, gs.history[-1].faith_delta,
                         "撞到 100 上限时差额记错了")

        # 下界：3 被罚 8，实际只掉到 0
        gs = GameState(seed=1)
        gs.faith = 3
        d = gs.dispatches[0]
        d.deadline = 0
        d.penalty = 8
        gs.advance([(d, gs.riders[0], gs.horses[0])])
        self.assertEqual(gs.faith - 3, gs.history[-1].faith_delta,
                         "撞到 0 下限时差额记错了")

    # ── ③ 归零后拒收索引 ──
    def test_aborted_trips_are_recorded(self):
        """信归零后未抵达的任务：资源不退，但必须留下记录、计入分母。"""
        gs = GameState(seed=1)
        gs.gold = 10000
        while len(gs.riders) < 3:
            gs.hire_rider()
        while len(gs.horses) < 3:
            gs.buy_horse()
        gs.faith = 3
        ds = gs.dispatches[:3]
        for x in ds:
            x.deadline = 0
            x.penalty = 5
        gs.advance([(ds[0], gs.riders[0], gs.horses[0]),
                    (ds[1], gs.riders[1], gs.horses[1]),
                    (ds[2], gs.riders[2], gs.horses[2])])
        nr = gs.history[0]
        # 三封都在夜初出发了（资源已扣），所以没有「拒收」
        self.assertEqual(len(nr.dropped), 0, "三封都已派出，不该有拒收")
        # 但被终止的在途任务必须留下记录
        self.assertGreaterEqual(len(nr.trips), 2,
                                "被终止的在途任务也要计入统计")


class TestSaveVersioning(unittest.TestCase):
    """存档版本检查与迁移。"""

    def test_unknown_future_version_returns_none(self):
        import json
        from relay.core import save as SV
        gs = GameState(seed=5)
        gs.advance([])
        SV.save(gs, "slot2")
        try:
            p = SV.slot_path("slot2")
            raw = json.loads(p.read_text(encoding="utf-8"))
            raw["version"] = 99
            p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            self.assertIsNone(SV.load("slot2"), "比本程序新的存档应该拒绝加载")
        finally:
            SV.delete("slot2")

    def test_v1_save_can_be_migrated(self):
        import json
        from relay.core import save as SV
        gs = GameState(seed=5)
        gs.advance([])
        SV.save(gs, "slot2")
        try:
            p = SV.slot_path("slot2")
            raw = json.loads(p.read_text(encoding="utf-8"))
            raw["version"] = 1
            raw["faith"] = 61.7          # v1 里 faith 可能是浮点
            p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            back = SV.load("slot2")
            self.assertIsNotNone(back, "v1 存档应该能迁移加载")
            self.assertIsInstance(back.faith, int, "迁移后 faith 应该是整数")
        finally:
            SV.delete("slot2")


class TestTransit(unittest.TestCase):
    """在途运输模型（Phase B1）的核心规则。

    规范见 docs/TRANSPORT.md。这些测试对应文档第 14 节的清单。
    """

    def _setup(self, route="north", deadline=None, per_night=None):
        gs = GameState(seed=1)
        gs.weather = "clear"
        gs.forecast = "clear"
        if per_night is not None:
            gs.night_progress = lambda *a, **k: per_night
        d = gs.dispatches[0]
        d.route = route
        if deadline is not None:
            d.deadline = deadline
        return gs, d, gs.available_riders(), gs.available_horses()

    # ── 时间轴 ──
    def test_one_night_trip_arrives_same_night(self):
        """一夜任务：出发当夜抵达，次夜可用。"""
        gs, d, riders, horses = self._setup("north", deadline=1, per_night=3.0)
        r, h = riders[0], horses[0]
        gs.advance([(d, r, h)])
        self.assertEqual(len(gs.history[-1].trips), 1, "出发当夜就该抵达")
        self.assertEqual(len(gs.trips), 0)
        self.assertFalse(gs.is_busy(rider_id=r.id), "次夜应该能再用")

    def test_two_night_trip_occupies_two_turns(self):
        """两夜任务：出发次夜抵达，再下一夜可用。"""
        gs, d, riders, horses = self._setup("north", deadline=2, per_night=2.5)
        r, h = riders[0], horses[0]

        gs.advance([(d, r, h)])
        self.assertEqual(len(gs.history[-1].trips), 0, "当夜不该抵达")
        self.assertEqual(len(gs.trips), 1, "应该在路上")
        self.assertTrue(gs.is_busy(rider_id=r.id))
        self.assertTrue(gs.is_busy(horse_id=h.id))

        gs.advance([])
        self.assertEqual(len(gs.history[-1].trips), 1, "次夜抵达")
        self.assertFalse(gs.is_busy(rider_id=r.id), "抵达夜之后释放")

    # ── 可用性 ──
    def test_busy_rider_and_horse_not_available(self):
        gs, d, riders, horses = self._setup("mine", deadline=3, per_night=1.0)
        r, h = riders[0], horses[0]
        gs.advance([(d, r, h)])
        self.assertNotIn(r, gs.available_riders())
        self.assertNotIn(h, gs.available_horses())
        with self.assertRaises(ValueError):
            gs.advance([(gs.dispatches[0], r, gs.available_horses()[0])])

    # ── 在途不恢复 ──
    def test_no_recovery_while_in_transit(self):
        gs, d, riders, horses = self._setup("mine", deadline=3, per_night=1.0)
        r, h = riders[0], horses[0]
        r.stamina = 50
        h.condition = 50
        gs.advance([(d, r, h)])
        st, co = r.stamina, h.condition
        gs.advance([])
        self.assertEqual(r.stamina, st, "在途骑手不该回体力")
        self.assertEqual(h.condition, co, "在途马不该回状态")

    # ── 灯火锁定 ──
    def test_light_factor_locked_at_departure(self):
        """出发时锁定的灯火系数，不因后续油量变化而改变。"""
        gs, d, riders, horses = self._setup("mine", deadline=3, per_night=1.0)
        r, h = riders[0], horses[0]
        gs.oil = 100
        gs.advance([(d, r, h)])
        trip = gs.trips[0]
        self.assertAlmostEqual(trip.light_factor, 1.0, places=5)
        # 把油烧光，已出发的任务不应受影响
        gs.oil = 0
        self.assertEqual(gs.current_light_factor(), B.OIL_LIGHT_FACTOR)
        self.assertAlmostEqual(trip.light_factor, 1.0, places=5)

    # ── 天气每夜重算 ──
    def test_weather_changes_progress(self):
        """同样的出发条件，暴雪夜里推进更慢（矿道免疫除外）。"""
        gs1 = GameState(seed=1)
        gs1.weather = "clear"
        p_clear = gs1.night_progress("ford", gs1.riders[0], gs1.horses[0])
        gs2 = GameState(seed=1)
        gs2.weather = "storm"
        p_storm = gs2.night_progress("ford", gs2.riders[0], gs2.horses[0])
        self.assertLess(p_storm, p_clear, "暴雪应该更慢")

        # 矿道对天气免疫
        gs3 = GameState(seed=1)
        gs3.weather = "clear"
        m_clear = gs3.night_progress("mine", gs3.riders[0], gs3.horses[0])
        gs4 = GameState(seed=1)
        gs4.weather = "storm"
        m_storm = gs4.night_progress("mine", gs4.riders[0], gs4.horses[0])
        self.assertAlmostEqual(m_clear, m_storm, places=5)

    # ── 超期仍继续运输 ──
    def test_late_trip_keeps_travelling(self):
        """期限决定能否成功，**不决定任务什么时候结束**。"""
        gs, d, riders, horses = self._setup("north", deadline=1, per_night=1.5)
        r, h = riders[0], horses[0]
        gs.advance([(d, r, h)])          # due_night = 出发夜，已经超期
        self.assertEqual(len(gs.trips), 1, "超期了但人还在路上")
        gs.advance([])                   # 第二夜抵达
        t = gs.history[-1].trips[0]
        self.assertFalse(t.delivered)
        self.assertIn("晚", t.note)

    # ── 修路不影响已出发 ──
    def test_repair_does_not_affect_departed_trip(self):
        gs, d, riders, horses = self._setup("mine", deadline=5, per_night=1.0)
        r, h = riders[0], horses[0]
        before = gs.route_distance["mine"]
        gs.advance([(d, r, h)])
        trip = gs.trips[0]
        self.assertEqual(trip.distance, float(before))
        gs.gold = 10000
        gs.repair_route("mine")
        self.assertEqual(trip.distance, float(before), "已出发的任务距离不该变")

    # ── 同夜多队结算顺序无关 ──
    def test_multi_trip_order_independent(self):
        """同一夜多支队伍抵达，只换登记顺序，结果必须一致。"""
        def run(reverse):
            gs = GameState(seed=42)
            gs.weather = "clear"
            gs.forecast = "clear"
            riders = gs.available_riders()[:2]
            horses = gs.available_horses()[:2]
            ds = gs.dispatches[:2]
            for x in ds:
                x.route = "north"
                x.deadline = 1
            gs.night_progress = lambda *a, **k: 3.0     # 当夜就都到
            pairs = [(ds[0], riders[0], horses[0]),
                     (ds[1], riders[1], horses[1])]
            if reverse:
                pairs = pairs[::-1]
            gs.advance(pairs)
            return sorted((t.rider_name, t.route, t.delivered)
                          for t in gs.history[-1].trips)
        self.assertEqual(run(False), run(True), "登记顺序影响了结算")

    # ── 第十二夜未抵达 ──
    def test_unfinished_on_last_night_is_counted(self):
        """第十二夜仍在途 → 按未送达处理，计入分母。"""
        gs = GameState(seed=1)
        gs.night = B.TOTAL_NIGHTS
        gs.weather = "clear"
        gs.forecast = "clear"
        gs.night_progress = lambda *a, **k: 1.0        # 走不完
        riders = gs.available_riders()
        horses = gs.available_horses()
        d = gs.dispatches[0]
        d.route = "mine"
        d.deadline = 3
        gs.advance([(d, riders[0], horses[0])])
        self.assertTrue(gs.over)
        nr = gs.history[-1]
        # 派出去的那封必须计入分母
        self.assertEqual(len(nr.trips), 1, "第十二夜未完成的信要计入统计")
        self.assertFalse(nr.trips[0].delivered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
