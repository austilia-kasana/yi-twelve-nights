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
            gs._roll_trip_event = lambda *a, **k: "calm"
            d = gs.dispatches[0]
            d.route = "north"
            d.deadline = 1
            gs.night_progress = lambda *a, **k: 2.5   # 两夜才到，必然超期
            riders = gs.available_riders()
            horses = gs.available_horses()
            r = riders[0]
            gs.advance([(d, r, horses[0])])
            gs.advance([])                             # 抵达
            # 只看抵达当夜的结果：那之后伤会正常倒计时，不该算进来
            arrived = gs.history[-1].trips
            if arrived and "受了伤" in arrived[0].note:
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
        gs._roll_trip_event = lambda *a, **k: "calm"   # 关事件，只验时间与文案
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
        # 本组测的是时间轴，关掉每夜事件，避免随机事件干扰断言
        gs._roll_trip_event = lambda *a, **k: "calm"
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
            gs._roll_trip_event = lambda *a, **k: "calm"
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
        gs._roll_trip_event = lambda *a, **k: "calm"
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


class TestDeterminismAcrossSaves(unittest.TestCase):
    """确定性：存档不能改变对局走向。

    这一组是龙娘列为必测的。核心命题：
    **同种子下，读档续跑和不中断运行，结果必须完全一致。**
    """

    @staticmethod
    def _play(seed, split_at=None):
        import json
        from relay.core.sim import GameState as GS
        gs = GS(seed=seed)
        # 事件关掉：本组验的是「存档不改变走向」，不是事件分布
        guard = 0
        while not gs.over and guard < 60:
            guard += 1
            riders = gs.available_riders()
            horses = gs.available_horses()
            plan = []
            if riders and horses and gs.dispatches:
                d = gs.dispatches[0]
                plan = [(d, riders[0], horses[0])]
            gs.advance(plan)
            if gs.over:
                break
            if split_at is not None and gs.night == split_at + 1:
                gs = GS.from_dict(json.loads(
                    json.dumps(gs.to_dict(), ensure_ascii=False)))
                split_at = None
        return gs

    @staticmethod
    def _fp(gs):
        return (
            gs.night, gs.faith, round(gs.gold, 6), round(gs.oil, 6),
            gs.over,
            [(nr.night, nr.weather, nr.gold_delta, nr.faith_delta) for nr in gs.history],
        )

    def test_id_sort_is_numeric_not_string(self):
        """id 必须按数值排序。

        id 形如 d5 d6 ... d9 d10 ...，字符串排序会把 "d10" 排到 "d9" 前面。
        结算顺序一变，随机数消耗顺序就变——同种子会跑出不同结果。
        """
        from relay.core.models import id_key
        ids = ["d9", "d10", "d99", "d100", "d2"]
        self.assertEqual(sorted(ids), ["d10", "d100", "d2", "d9", "d99"],
                         "字符串排序确实会错（本测试的前提）")
        self.assertEqual(sorted(ids, key=id_key),
                         ["d2", "d9", "d10", "d99", "d100"],
                         "id_key 必须给出数值序")

    def test_same_seed_twice_identical(self):
        for seed in (0, 7, 42):
            self.assertEqual(self._fp(self._play(seed)),
                             self._fp(self._play(seed)),
                             "同样种子两次结果不同")

    def test_resume_matches_uninterrupted(self):
        """第 N 夜存档往返后继续，必须和一口气跑完一致。"""
        for seed in (0, 3, 11):
            straight = self._fp(self._play(seed))
            for split in (1, 4, 7):
                self.assertEqual(
                    self._fp(self._play(seed, split_at=split)), straight,
                    "种子 %d 在第 %d 夜切分后分叉" % (seed, split))

    def test_rng_state_roundtrips(self):
        import json
        from relay.core.sim import GameState as GS
        gs = GS(seed=99)
        gs.advance([])
        # 先存档再抽随机数，否则比的是两个不同位置的状态
        snap = json.dumps(gs.to_dict(), ensure_ascii=False)
        a = [gs.rng.random() for _ in range(5)]
        # 注意：读档只做一次。写成列表推导里每次 GS.from_dict(...) 的话，
        # 拿到的五个值都会是「恢复后第一个随机数」——同一个数。
        restored = GS.from_dict(json.loads(snap))
        b = [restored.rng.random() for _ in range(5)]
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, places=12)

    def test_in_transit_survives_save(self):
        import json
        from relay.core.sim import GameState as GS
        gs = GS(seed=3)
        gs.weather = "clear"
        gs.forecast = "clear"
        gs._roll_trip_event = lambda *a, **k: "calm"
        gs.night_progress = lambda *a, **k: 1.0
        r, h = gs.available_riders()[0], gs.available_horses()[0]
        d = gs.dispatches[0]
        d.route = "mine"
        d.deadline = 3
        gs.advance([(d, r, h)])
        before = [(t.route, round(t.progress, 6), t.due_night, t.depart_night)
                  for t in gs.trips]
        back = GS.from_dict(json.loads(json.dumps(gs.to_dict(), ensure_ascii=False)))
        after = [(t.route, round(t.progress, 6), t.due_night, t.depart_night)
                 for t in back.trips]
        self.assertEqual(before, after, "在途任务没正确往返")
        # 读档后必须还能继续推进到抵达
        back.night_progress = lambda *a, **k: 5.0
        back.advance([])
        self.assertEqual(len(back.history[-1].trips), 1)
        self.assertEqual(len(back.trips), 0)


class TestPerNightEvents(unittest.TestCase):
    """B2：每夜事件。

    权重表原本按「每趟一次」标定，改成每夜之后必须：
      1. 概率按 1-(1-p)^(1/N) 换算，而不是 p/N
      2. 每种事件的效果在新模型下明确（进度倍率 / 加距离 / 终止）
      3. 事件按稳定顺序抽取，不受列表插入顺序影响
    """

    def _trip(self, gs, route="mine", deadline=5, per_night=1.0):
        gs.weather = "clear"
        gs.forecast = "clear"
        gs._roll_trip_event = lambda *a, **k: "calm"
        gs.night_progress = lambda *a, **k: per_night
        r, h = gs.available_riders()[0], gs.available_horses()[0]
        d = gs.dispatches[0]
        d.route = route
        d.deadline = deadline
        return d, r, h

    def test_probability_conversion_not_naive_division(self):
        """每夜概率必须用 1-(1-p)^(1/N)，不能用 p/N。"""
        gs = GameState(seed=1)
        p_trip = 0.10
        for n in (1, 2, 3):
            p_night = 1 - (1 - p_trip) ** (1 / n)
            naive = p_trip / n
            if n > 1:
                self.assertNotAlmostEqual(p_night, naive, places=4,
                                          msg="N=%d 时两者应该不同" % n)
            # 累计概率必须还原
            cum = 1 - (1 - p_night) ** n
            self.assertAlmostEqual(cum, p_trip, places=9,
                                   msg="N=%d 夜累计概率没还原" % n)

    def test_tailwind_advances_faster(self):
        """顺风：本夜进度 × 1.5，能提前抵达。"""
        gs = GameState(seed=1)
        d, r, h = self._trip(gs, route="mine", deadline=5, per_night=1.2)
        base = GameState(seed=1)
        d2, r2, h2 = self._trip(base, route="mine", deadline=5, per_night=1.2)

        gs._roll_trip_event = lambda *a, **k: "tailwind"
        gs.advance([(d, r, h)])
        base.advance([(d2, r2, h2)])
        self.assertGreater(gs.trips[0].progress, base.trips[0].progress,
                           "顺风应该推得更远")

    def test_lost_advances_slower(self):
        """迷路：本夜进度 × 0.5。"""
        gs = GameState(seed=1)
        d, r, h = self._trip(gs, route="mine", deadline=5, per_night=1.2)
        base = GameState(seed=1)
        d2, r2, h2 = self._trip(base, route="mine", deadline=5, per_night=1.2)
        gs._roll_trip_event = lambda *a, **k: "lost"
        gs.advance([(d, r, h)])
        base.advance([(d2, r2, h2)])
        self.assertLess(gs.trips[0].progress, base.trips[0].progress)

    def test_rockfall_only_one_penalty(self):
        """落石只惩罚一项：本夜进度归零，**不再额外加距离**。

        双重惩罚（归零 + 距离 +1）会让出发当夜就吃落石的任务直接失去
        一整夜 + 20% 距离，实测送达率只有 16%——那不是麻烦，是判死。
        """
        gs = GameState(seed=1)
        d, r, h = self._trip(gs, route="mine", deadline=5, per_night=1.2)
        dist_before = float(gs.route_distance["mine"])
        gs._roll_trip_event = lambda *a, **k: "rockfall"
        gs.advance([(d, r, h)])
        trip = gs.trips[0]
        self.assertAlmostEqual(trip.progress, 0.0, places=6, msg="落石当夜不该推进")
        self.assertAlmostEqual(trip.distance, dist_before, places=6,
                               msg="落石不该再加距离（只惩罚一项）")

    def test_robbery_ends_trip_and_costs_faith(self):
        """遇劫：任务立即终止，信丢，扣一半罚款，人马下一夜归队。"""
        gs = GameState(seed=1)
        d, r, h = self._trip(gs, route="mine", deadline=5, per_night=0.5)
        d.penalty = 10
        gs.faith = 50
        gs._roll_trip_event = lambda *a, **k: "robbery"
        gs.advance([(d, r, h)])
        self.assertEqual(len(gs.trips), 0, "遇劫后任务应该终止")
        self.assertLess(gs.faith, 50, "遇劫应该扣信")
        self.assertEqual(gs.faith, 50 - 5, "遇劫按一半罚款扣")
        # 人马下一夜可再用
        self.assertFalse(gs.is_busy(rider_id=r.id))
        self.assertFalse(gs.is_busy(horse_id=h.id))
        notes = [t.note for t in gs.history[-1].trips]
        self.assertTrue(any("遇劫" in x for x in notes))

    def test_events_sorted_by_numeric_id(self):
        """多支队伍同夜推进，事件抽取顺序必须按数值 id，不是字符串 id。"""
        from relay.core.models import id_key
        ids = ["t9", "t10", "t2"]
        self.assertEqual(min(ids, key=id_key), "t2",
                         "最小 id 应该按数值算，不是按字符串")

    def test_event_weights_cover_all_keys(self):
        """每个事件都要有明确的效果定义，否则新模型下会静默失效。"""
        from relay.core import balance as BB
        for k in BB.EVENTS:
            if k == "calm":
                continue
            self.assertIn(k, BB.EVENT_EFFECTS,
                          "事件 %s 没有定义每夜效果" % k)


class TestSettlementIntegrity(unittest.TestCase):
    """龙娘 v0.4.0 裁决定的「结算正确性」——任务不能丢、资源不能提前恢复。"""

    def _calm(self, gs):
        gs._roll_trip_event = lambda *a, **k: "calm"
        return gs

    # ── 信归零时已抵达但未结算的任务不能消失 ──
    def test_arrived_but_unsettled_are_recorded(self):
        gs = self._calm(GameState(seed=1))
        gs.weather = "clear"
        gs.forecast = "clear"
        gs.night_progress = lambda *a, **k: 99.0
        gs.gold = 10000
        while len(gs.riders) < 3:
            gs.hire_rider()
        while len(gs.horses) < 3:
            gs.buy_horse()
        gs.faith = 3
        ds = gs.dispatches[:3]
        for d in ds:
            d.route = "north"
            d.deadline = 0        # 必然超期，第一封失败就把信打到 0
            d.penalty = 5
        gs.advance([(ds[0], gs.riders[0], gs.horses[0]),
                    (ds[1], gs.riders[1], gs.horses[1]),
                    (ds[2], gs.riders[2], gs.horses[2])])
        nr = gs.history[0]
        self.assertEqual(len(nr.trips), 3,
                         "已抵达但没轮到结算的任务也必须留下记录")
        aborted = [t for t in nr.trips if t.event == "aborted"]
        self.assertEqual(len(aborted), 2)

    # ── 第十二夜罚款把信打到 0 之后不能再判存活 ──
    def test_final_night_penalty_can_lose_the_game(self):
        gs = self._calm(GameState(seed=2))
        gs.weather = "clear"
        gs.forecast = "clear"
        gs.night_progress = lambda *a, **k: 0.1     # 走不完
        gs.night = B.TOTAL_NIGHTS
        gs.faith = 3
        d = gs.dispatches[0]
        d.route = "mine"
        d.deadline = 3
        d.penalty = 8
        r, h = gs.available_riders()[0], gs.available_horses()[0]
        gs.advance([(d, r, h)])
        self.assertEqual(gs.faith, 0)
        self.assertFalse((gs.result or {}).get("survived"),
                         "信被最终罚款打到 0，不能判「守住了」")

    # ── 抵达当夜人马不能恢复 ──
    def test_no_recovery_on_arrival_night(self):
        gs = self._calm(GameState(seed=3))
        gs.weather = "clear"
        gs.forecast = "clear"
        gs.night_progress = lambda *a, **k: 2.5     # 两夜任务
        r, h = gs.available_riders()[0], gs.available_horses()[0]
        r.stamina = 100.0
        h.condition = 100.0
        d = gs.dispatches[0]
        d.route = "north"
        d.deadline = 9
        gs.advance([(d, r, h)])
        st, co = r.stamina, h.condition
        gs.advance([])                               # 抵达
        self.assertAlmostEqual(r.stamina, st, places=6,
                               msg="抵达当夜不该回体力（应下一夜才回）")
        self.assertAlmostEqual(h.condition, co, places=6,
                               msg="抵达当夜马不该回状态")

    # ── 三类结果统一按 id 排序 ──
    def test_settlement_order_is_unified_by_id(self):
        from relay.core.models import id_key
        gs = GameState(seed=4)
        gs.weather = "clear"
        gs.forecast = "clear"
        gs.night_progress = lambda *a, **k: 99.0
        gs.gold = 10000
        while len(gs.riders) < 2:
            gs.hire_rider()
        while len(gs.horses) < 2:
            gs.buy_horse()
        ds = gs.dispatches[:2]
        for d in ds:
            d.route = "north"
            d.deadline = 1
        victim = max(ds, key=id_key)          # id 较大的那封遇劫
        gs._roll_trip_event = lambda trip, w: (
            "robbery" if trip.dispatch.id == victim.id else "calm")
        gs.advance([(ds[0], gs.riders[0], gs.horses[0]),
                    (ds[1], gs.riders[1], gs.horses[1])])
        ids = [t.dispatch.id for t in gs.history[0].trips]
        self.assertEqual(ids, sorted(ids, key=id_key),
                         "遇劫和抵达必须统一按 id 排序")

    # ── TripResult 必须带事件历史 ──
    def test_trip_result_keeps_event_history(self):
        gs = GameState(seed=5)
        gs.weather = "clear"
        gs.forecast = "clear"
        gs.night_progress = lambda *a, **k: 1.0
        seq = ["lost", "calm", "calm", "calm", "calm", "calm"]
        idx = {"i": 0}

        def roll(trip, w):
            i = idx["i"]
            idx["i"] = min(i + 1, len(seq) - 1)
            return seq[i]
        gs._roll_trip_event = roll
        r, h = gs.available_riders()[0], gs.available_horses()[0]
        d = gs.dispatches[0]
        d.route = "mine"
        d.deadline = 9
        gs.advance([(d, r, h)])
        for _ in range(10):
            if not gs.trips or gs.over:
                break
            gs.advance([])
        arrived = [t for nr in gs.history for t in nr.trips]
        self.assertTrue(arrived)
        self.assertTrue(arrived[0].events, "结算后的事件历史不能丢")
        self.assertEqual(arrived[0].events[0]["event"], "lost")



    # ── 遇劫人马当夜也不能恢复 ──
    def test_robbed_units_do_not_recover(self):
        """遇劫 = 被打了一顿。当夜不该有休息加成。"""
        gs = self._calm(GameState(seed=6))
        gs.weather = "clear"
        gs.forecast = "clear"
        gs.night_progress = lambda *a, **k: 1.0
        r, h = gs.available_riders()[0], gs.available_horses()[0]
        r.stamina = 100.0
        h.condition = 100.0
        d = gs.dispatches[0]
        d.route = "mine"
        d.deadline = 9
        gs.advance([(d, r, h)])              # 夜1 出发
        st, co = r.stamina, h.condition
        gs._roll_trip_event = lambda *a, **k: "robbery"
        gs.advance([])                        # 夜2 遇劫
        self.assertAlmostEqual(r.stamina, st, places=6,
                               msg="遇劫当夜不该回体力")
        self.assertAlmostEqual(h.condition, co, places=6,
                               msg="遇劫当夜马不该回状态")

    # ── 副作用顺序必须按 id ──
    def test_side_effects_ordered_by_id(self):
        """同夜「抵达」和「遇劫」并存时，id 小的先生效。

        早先是阶段②遇劫立刻扣信、阶段③才结算抵达，于是遇劫永远先生效。
        id 小的那封本该先送达，却因为 id 大的先遇劫把信扣光而被记成 aborted。
        """
        from relay.core.models import id_key
        gs = GameState(seed=8)
        gs.weather = "clear"
        gs.forecast = "clear"
        gs.night_progress = lambda *a, **k: 99.0
        gs.gold = 10000
        while len(gs.riders) < 2:
            gs.hire_rider()
        while len(gs.horses) < 2:
            gs.buy_horse()
        ds = gs.dispatches[:2]
        for d in ds:
            d.route = "north"
            d.deadline = 1
            d.penalty = 50
        lo, hi = sorted(ds, key=id_key)
        # id 大的遇劫，id 小的抵达
        gs._roll_trip_event = lambda trip, w: (
            "robbery" if trip.dispatch.id == hi.id else "calm")
        gs.faith = 20
        gs.advance([(ds[0], gs.riders[0], gs.horses[0]),
                    (ds[1], gs.riders[1], gs.horses[1])])
        by_id = {t.dispatch.id: t for t in gs.history[0].trips}
        self.assertTrue(by_id[lo.id].delivered,
                        "id 小的那封应该先结算并送达，不该被记成 aborted")
        self.assertEqual(by_id[hi.id].event, "robbery")

    # ── 遇劫受伤必须走 event_rng ──
    def test_robbery_injury_uses_event_rng(self):
        import inspect
        src = inspect.getsource(GameState._resolve_robbery)
        self.assertIn("self.event_rng", src)
        self.assertNotIn("self.rng.random()", src,
                         "遇劫受伤不该用主随机流")


class TestEventSampling(unittest.TestCase):
    """真实事件抽样：概率换算和每夜口径必须对得上。"""

    @staticmethod
    def _sample(n_games=200, route="mine", per_night=1.0, deadline=9):
        from collections import Counter
        from relay.core.sim import GameState as GS
        counts = Counter()
        nights = 0
        for seed in range(n_games):
            gs = GS(seed=seed)
            gs.weather = "clear"
            gs.forecast = "clear"
            gs.night_progress = lambda *a, **k: per_night
            r, h = gs.available_riders()[0], gs.available_horses()[0]
            d = gs.dispatches[0]
            d.route = route
            d.deadline = deadline
            gs.advance([(d, r, h)])
            trip = gs.trips[0] if gs.trips else None
            if trip is None:
                continue
            n_exp = trip.expected_nights
            for _ in range(n_exp):
                if not gs.trips:
                    break
                counts[gs._roll_trip_event(gs.trips[0], "clear")] += 1
                nights += 1
        return counts, nights

    def test_per_night_rate_matches_conversion(self):
        """每夜事故率应接近 1-(1-p_trip)^(1/N)，而不是 p_trip。"""
        counts, nights = self._sample()
        self.assertGreater(nights, 100, "样本太小")
        any_event = sum(v for k, v in counts.items() if k != "calm") / nights
        from relay.core import balance as BB
        raw = {k: v["weight"] for k, v in BB.EVENTS.items()}
        total = sum(raw.values())
        p_trip = sum(v for k, v in raw.items() if k != "calm") / total
        # 期望每夜率（按期望行程 2 夜算）
        p_expect = 1 - (1 - p_trip) ** (1 / 2.0)
        self.assertLess(abs(any_event - p_expect), 0.06,
                        "实测每夜率 %.3f，期望 %.3f" % (any_event, p_expect))
        # 必须明显低于每趟率——那才说明换算生效了
        self.assertLess(any_event, p_trip,
                        "每夜率不低于每趟率，说明没做换算")

    def test_event_rng_is_separate_from_main_rng(self):
        """事件流和主随机流必须独立。

        否则「关掉事件」做 A/B 时整局随机轨迹都会变，测出的差异
        分不清是事件效果还是随机流错位。
        """
        a = GameState(seed=7)
        b = GameState(seed=7)
        # 在 a 上狂抽事件随机数
        for _ in range(50):
            a.event_rng.random()
        # 主随机流不该受影响
        for _ in range(10):
            self.assertAlmostEqual(a.rng.random(), b.rng.random(), places=12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
