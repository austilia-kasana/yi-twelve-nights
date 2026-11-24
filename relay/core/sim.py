# -*- coding: utf-8 -*-
"""《驿 · 十二夜》核心模拟。

铁律：
  1. 本模块**不 import pygame**，可以无头运行、无头测试
  2. 所有随机都走 self.rng（带种子），保证可复现
  3. advance() 不修改全局，只推进 self 并返回报告

对外主要接口：
    gs = GameState(seed=1234)
    gs.begin_night()                     # 生成今夜的信 + 预报（构造时自动调一次）
    gs.travel_nights(dispatch, rider, horse)   # 预估 / 实际行程夜数
    res = gs.advance(assignments, resting)     # 推进一夜
    gs.hire_rider() / buy_horse() / feed(...) / buy_oil() / repair_route(...)
"""

from __future__ import annotations

import ast
import itertools
import math
import random
from typing import Iterable, Optional

from . import balance as B
from .models import (ActiveTrip, Dispatch, Horse, NightResult, Rider,
                     TripResult, id_key)


# ────────────────────────── 工具 ──────────────────────────
def _weighted_choice(rng: random.Random, weights: dict):
    """{'a': 3, 'b': 1} -> 'a' 概率 0.75"""
    total = sum(weights.values())
    if total <= 0:
        return next(iter(weights))
    r = rng.random() * total
    acc = 0.0
    for k, w in weights.items():
        acc += w
        if r <= acc:
            return k
    return list(weights)[-1]


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


class GameState:
    # ────────────────────── 构造 ──────────────────────
    def __init__(self, seed: Optional[int] = None):
        self.seed = seed
        # 主随机流：信件生成、天气、受伤、采购
        self.rng = random.Random(seed)
        # 独立的事件流。
        #
        # 为什么拆：事件的抽取次数随行程长度变化，如果和其他随机共用一条流，
        # 「关掉事件」做 A/B 对比时整局的随机轨迹都会变——测出来的差异
        # 就分不清是「事件的效果」还是「随机流错位」。
        # 拆开之后，关掉事件不影响其余任何判定。
        self.event_rng = random.Random(
            None if seed is None else seed ^ 0x5EED_E7E17)

        self.night = 1
        # 信用整数。早先是 float，和日志里的 int 差量对不上（见 advance 里的说明）。
        self.faith = int(B.START_FAITH)
        self.gold = float(B.START_GOLD)
        self.oil = float(B.START_OIL)

        self.riders: list[Rider] = [
            Rider(name=d["name"], speed=d["speed"], stamina=d["stamina"])
            for d in B.START_RIDERS
        ]
        self.horses: list[Horse] = [
            Horse(name=d["name"], speed=d["speed"], condition=d["condition"])
            for d in B.START_HORSES
        ]

        # 可修复的路线距离
        self.route_distance: dict[str, int] = {
            k: v["distance"] for k, v in B.ROUTES.items()
        }
        self.route_repaired: set[str] = set()

        self.weather: Optional[str] = None
        self.forecast: Optional[str] = None
        self.dispatches: list[Dispatch] = []

        # 在途任务。「谁在途」以它为准——骑手和马身上都不存这个状态。
        self.trips: list[ActiveTrip] = []

        self.over = False
        self.result: Optional[dict] = None

        self.log: list[dict] = []
        self.history: list[NightResult] = []

        self._name_pool = [
            "阿石", "老周", "七斤", "顺子", "哑叔", "小六", "阿桃",
            "铁头", "麻子", "栓柱", "阿绣", "黑娃",
        ]
        self._horse_pool = [
            "踏雪", "赤云", "墨点", "黄骠", "白尾", "青鬃", "驮山", "小月",
        ]
        self._used_names: set[str] = set(d["name"] for d in B.START_RIDERS)
        self._used_horse_names: set[str] = set(d["name"] for d in B.START_HORSES)

        self.begin_night()

    # ────────────────────── 日志 ──────────────────────
    def note(self, text: str, kind: str = "info"):
        self.log.append({"night": self.night, "text": text, "kind": kind})
        if len(self.log) > 300:
            self.log = self.log[-300:]

    # ────────────────────── 天气 ──────────────────────
    def _weather_weights(self, night: int) -> dict:
        table = B.WEATHER_SCHEDULE[0][1]
        for start, w in B.WEATHER_SCHEDULE:
            if night >= start:
                table = w
        return table

    def roll_weather(self, night: int) -> str:
        return _weighted_choice(self.rng, self._weather_weights(night))

    def roll_forecast(self, actual: str) -> str:
        """预报有 FORECAST_ACCURACY 的概率说对。

        说错时不会离得太离谱：只跳到相邻的天气档
        （晴↔阴↔雨↔雪↔暴雪），避免「预报晴、实际暴雪」这种致命欺骗。
        """
        if self.rng.random() < B.FORECAST_ACCURACY:
            return actual
        order = ["clear", "cloud", "rain", "snow", "storm"]
        i = order.index(actual)
        # 相邻偏移 ±1，边界只往内偏
        if i == 0:
            return order[1]
        if i == len(order) - 1:
            return order[-2]
        return order[i + self.rng.choice([-1, 1])]

    # ────────────────────── 信件生成 ──────────────────────
    def _pick_kind(self, night: int) -> str:
        kinds = dict()
        for k, d in B.DISPATCH_KINDS.items():
            if k == "express" and night < B.EXPRESS_STARTS_NIGHT:
                continue
            kinds[k] = d["weight"]
        return _weighted_choice(self.rng, kinds)

    def _pick_name(self, pool: list, used: set) -> str:
        free = [n for n in pool if n not in used]
        if not free:
            return "无名"
        n = self.rng.choice(free)
        used.add(n)
        return n

    def _make_dispatch(self, night: int) -> Dispatch:
        kind = self._pick_kind(night)
        kd = B.DISPATCH_KINDS[kind]
        route = self.rng.choice(list(B.ROUTES))

        # 期限 = 该路线的基准夜数 + 该种类的余量
        slack = kd["slack"]
        if "slack_mix" in kd:
            slack = self.rng.choice(kd["slack_mix"])
        deadline = B.ROUTE_BASE_NIGHTS[route] + slack

        r_lo, r_hi = kd["reward"]
        p_lo, p_hi = kd["penalty"]
        reward = self.rng.randint(r_lo, r_hi)
        penalty = self.rng.randint(p_lo, p_hi)

        return Dispatch(
            route=route, kind=kind, deadline=deadline,
            reward=reward, penalty=penalty,
            text=self._dispatch_text(kind),
        )

    def _dispatch_text(self, kind: str) -> str:
        lines = {
            "normal": [
                "家中一切安好，勿念。",
                "前线暂歇，请转告粮车缓行。",
                "问北边天气，回信。",
                "旧部三人调往西营，已核。",
                "冬衣三百件已发，收讫。",
            ],
            "urgent": [
                "敌骑已过河，速报总营。",
                "粮道被截，请就近调拨。",
                "北口守军请增五十人，急。",
                "伤兵已过百，医官不足。",
            ],
            "express": [
                "城破在即，援军三日不至则退守南岗。",
                "主帅中矢，诸将暂听副将节制。",
                "粮尽。此信若到，请勿再发援。",
            ],
        }
        return self.rng.choice(lines.get(kind, ["—"]))

    def begin_night(self):
        """进入黄昏：定天气、出预报、收信。"""
        self.weather = self.roll_weather(self.night)
        self.forecast = self.roll_forecast(self.weather)
        n = self.rng.randint(*B.DISPATCHES_PER_NIGHT)
        self.dispatches = [self._make_dispatch(self.night) for _ in range(n)]
        self.note("第 %d 夜。%s" % (self.night, B.WEATHER[self.forecast]["desc"]))

    # ────────────────────── 行进计算 ──────────────────────
    def current_light_factor(self) -> float:
        """油够就点灯，不够就摸黑。"""
        return 1.0 if self.oil >= B.NO_LIGHT_OIL_THRESHOLD else B.OIL_LIGHT_FACTOR

    def travel_nights(self, dispatch: Dispatch, rider: Rider, horse: Horse,
                      weather: Optional[str] = None,
                      light_factor: Optional[float] = None) -> int:
        """用某骑手+某马送这封信，按最乐观情况要跑几夜。

        **这是给 UI 做预估用的**，不是实际推进逻辑。
        在途任务的真实推进见 night_progress()。
        """
        dist = self.route_distance[dispatch.route]
        per = self.night_progress(dispatch.route, rider, horse,
                                  weather, light_factor)
        if per <= 0.01:
            return 99
        return max(1, int(math.ceil(dist / per)))

    def expected_nights(self, dispatch: Dispatch, rider: Rider,
                        horse: Horse, light_factor: Optional[float] = None) -> int:
        """按**典型天气**估算这趟要走几夜。用于事件概率换算的基数。

        和 travel_nights 的区别：travel_nights 用当晚实际/预报天气（最短路），
        这个用路线在全局天气分布下的平均系数（预期路）。
        """
        dist = self.route_distance[dispatch.route]
        wf = B.EXPECTED_ROUTE_FACTOR.get(dispatch.route, 1.0)
        light = self.current_light_factor() if light_factor is None else light_factor
        per = (rider.effective_speed() * horse.effective_speed()
               * wf * light * B.BASE_TRAVEL)
        if per <= 0.01:
            return 99
        return max(1, int(math.ceil(dist / per)))

    def night_progress(self, route: str, rider: Rider, horse: Horse,
                       weather: Optional[str] = None,
                       light_factor: Optional[float] = None) -> float:
        """一夜能推进多少等效距离。

        公式和原来的 travel_nights 是同一个，只是从「一次算总时间」
        改成「每夜加一格」。
        """
        w = weather or self.weather or "clear"
        wf = B.WEATHER[w]["route_factor"][route]
        light = self.current_light_factor() if light_factor is None else light_factor
        return (rider.effective_speed() * horse.effective_speed()
                * wf * light * B.BASE_TRAVEL)

    def _roll_trip_event(self, trip: ActiveTrip, weather: str) -> str:
        """一夜一个在途事件。

        权重表是按「每趟一次」标定的，这里换算成「每夜」：

            p_night = 1 - (1 - p_trip) ** (1 / planned_nights)

        不能直接用 p_trip / N —— 那只是小概率下的近似，
        长途会系统性偏低，短途会偏高。
        """
        raw = {k: v["weight"] for k, v in B.EVENTS.items()}
        total = sum(raw.values())
        if total <= 0:
            return "calm"

        # 天气/路线修正
        rc = B.ROCKFALL_CONDITION
        if trip.route == rc["route"] and weather == rc["weather"]:
            raw["rockfall"] *= rc["mult"]
        rb = B.ROBBERY_CONDITION
        if weather == rb["weather"]:
            raw["robbery"] *= rb["mult"]
        risk = B.WEATHER[weather]["risk"]
        raw["calm"] = max(20.0, raw["calm"] * (1.0 - risk))

        total = sum(raw.values())
        # 换算基数用**期望行程**，不是出发时的乐观估计。
        n = max(B.EVENT_NIGHTS_MIN, float(trip.expected_nights))

        # 逐项换算成每夜概率
        probs = {}
        for k, w in raw.items():
            if k == "calm":
                continue
            p_trip = w / total
            probs[k] = 1.0 - (1.0 - p_trip) ** (1.0 / n)

        p_any = sum(probs.values())
        if p_any <= 0:
            return "calm"
        if self.event_rng.random() >= p_any:
            return "calm"

        # 在「发生事件」的前提下按相对概率挑一个
        r = self.event_rng.random() * p_any
        acc = 0.0
        for k, p in probs.items():
            acc += p
            if r <= acc:
                return k
        return list(probs)[-1]

    # ────────────────────── 在途查询 ──────────────────────
    def is_busy(self, rider_id: Optional[str] = None,
                horse_id: Optional[str] = None) -> bool:
        """这个人/这匹马是不是正在路上。

        ActiveTrip 是唯一事实来源——不靠 Rider.state 或 Horse 上的标记。
        """
        for t in self.trips:
            if rider_id is not None and t.rider_id == rider_id:
                return True
            if horse_id is not None and t.horse_id == horse_id:
                return True
        return False

    def trip_of_rider(self, rider_id: str) -> Optional[ActiveTrip]:
        return next((t for t in self.trips if t.rider_id == rider_id), None)

    def trip_of_horse(self, horse_id: str) -> Optional[ActiveTrip]:
        return next((t for t in self.trips if t.horse_id == horse_id), None)

    # ────────────────────── 事件 ──────────────────────
    def _roll_event(self, dispatch: Dispatch, weather: str) -> str:
        weights = {k: v["weight"] for k, v in B.EVENTS.items()}
        # 雪天走北口，落石翻倍
        rc = B.ROCKFALL_CONDITION
        if dispatch.route == rc["route"] and weather == rc["weather"]:
            weights["rockfall"] *= rc["mult"]
        rb = B.ROBBERY_CONDITION
        if weather == rb["weather"]:
            weights["robbery"] *= rb["mult"]
        # 坏天气同时压低「无事」的权重，让坏事更容易发生
        risk = B.WEATHER[weather]["risk"]
        weights["calm"] = max(20, int(weights["calm"] * (1.0 - risk)))
        return _weighted_choice(self.rng, weights)

    # ────────────────────── 推进一夜 ──────────────────────
    def advance(self, assignments: Iterable[tuple],
                resting: Iterable[str] = ()) -> NightResult:
        """推进一夜。

        assignments: [(dispatch, rider, horse), ...]
        resting:     已废弃（自动推断），保留只为兼容旧调用。

        ## 阶段顺序（定案，见 docs/TRANSPORT.md 第 1 节）

            ① 校验并登记本夜新派单，扣除出发资源
            ② 推进所有在途任务，**包括刚刚出发的**
            ③ 统一结算抵达，释放人马

        为什么新任务当夜就要推进：玩家安排的是「当前夜的派遣」，
        当前夜的天气就应该参与推进。如果从次夜才开始动，整体会晚一夜。
        """
        if self.over:
            raise RuntimeError("本局已经结束")

        assignments = list(assignments)

        # 用到的骑手/马不能重复
        seen_r, seen_h = set(), set()
        for d, r, h in assignments:
            if r.id in seen_r:
                raise ValueError("同一个骑手被派了两次：%s" % r.name)
            if h.id in seen_h:
                raise ValueError("同一匹马被用了两次：%s" % h.name)
            if self.is_busy(rider_id=r.id):
                raise ValueError("%s 还在路上" % r.name)
            if self.is_busy(horse_id=h.id):
                raise ValueError("%s 还在路上" % h.name)
            if r.state != "idle":
                raise ValueError("%s 现在不能出发" % r.name)
            seen_r.add(r.id)
            seen_h.add(h.id)

        # 按信 id 排序后再登记。
        # random 是按顺序消耗的，排序保证「谁先抽到什么」和 UI 点击顺序无关。
        assignments.sort(key=lambda a: id_key(a[0]))

        weather = self.weather or "clear"
        result = NightResult(
            night=self.night,
            weather=weather,
            forecast=self.forecast or weather,
            forecast_was_right=(self.forecast == weather),
        )

        # 夜初统一算一次灯火快照。同一夜所有新派单共用这个值——
        # 这是 v0.3.0 修好的「派遣顺序不影响结果」，必须保留。
        light = self.current_light_factor()

        # ── ① 登记新派单 ──
        taken_ids = set()
        for d, r, h in assignments:
            taken_ids.add(d.id)
            # 消耗在出发时一次性扣掉（不是每夜扣）
            r.stamina = _clamp(
                r.stamina - self.rng.uniform(B.STAMINA_COST_MIN, B.STAMINA_COST_MAX),
                0, 100)
            h.condition = _clamp(
                h.condition - self.rng.uniform(B.HORSE_COST_MIN, B.HORSE_COST_MAX),
                0, 100)
            self.oil = max(0.0, self.oil - self.rng.uniform(4, 8))

            self.trips.append(ActiveTrip(
                dispatch=d,
                rider_id=r.id,
                horse_id=h.id,
                route=d.route,
                distance=float(self.route_distance[d.route]),
                progress=0.0,
                depart_night=self.night,
                elapsed_nights=0,
                due_night=self.night + d.deadline - 1,
                light_factor=light,
                # 出发时的行程估计（最优），只作参考
                planned_nights=self.travel_nights(d, r, h, weather, light),
                # 事件概率换算用的**期望**行程：按典型天气系数算，不是最短路
                expected_nights=self.expected_nights(d, r, h, light),
            ))

        # 拒收的信（本夜清单里没被派出去的那些）
        result.dropped = [d for d in self.dispatches if d.id not in taken_ids]

        # ── ② 推进所有在途（含刚出发的）──
        # 按任务 id 的**数值**排序推进：多个任务同夜推进时，
        # 谁先抽到事件不能由列表插入顺序或 id 的字符串形态决定。
        injured_tonight: set[str] = set()
        robbed: list[ActiveTrip] = []
        for trip in sorted(self.trips, key=id_key):
            rider = self.rider_by_id(trip.rider_id)
            horse = self.horse_by_id(trip.horse_id)
            if rider is None or horse is None:
                continue

            # 天气每夜重算，灯火用出发时锁定的快照
            per = self.night_progress(trip.route, rider, horse,
                                      weather, trip.light_factor)

            # 每夜一个事件
            event = self._roll_trip_event(trip, weather)
            if event != "calm":
                eff = B.EVENT_EFFECTS.get(event, {})
                per *= eff.get("progress_mult", 1.0)
                trip.distance += eff.get("distance_add", 0.0)
                trip.events.append({"night": self.night, "event": event})
                if event == "robbery":
                    robbed.append(trip)

            trip.progress += per
            trip.elapsed_nights += 1

        # 遇劫：任务立即终止，人马下一夜归队（信丢了）
        robbery_results = []
        for trip in robbed:
            if trip in self.trips:
                self.trips.remove(trip)
            rider = self.rider_by_id(trip.rider_id)
            horse = self.horse_by_id(trip.horse_id)
            old = self.faith
            rob_pen = max(1, trip.dispatch.penalty // 2)
            self.faith = _clamp(old - rob_pen, 0, B.MAX_FAITH)
            result.faith_delta += self.faith - old
            tr = TripResult(
                dispatch=trip.dispatch,
                rider_name=rider.name if rider else "?",
                horse_name=horse.name if horse else "?",
                route=trip.route,
                nights_taken=trip.elapsed_nights,
                delivered=False, lost=True, event="robbery",
                note="遇劫，信没了。",
                events=list(trip.events),
            )
            # 遇劫的人更容易受伤
            if rider is not None and rider.state == "idle":
                if self.rng.random() < B.ROBBERY_INJURY_CHANCE:
                    rider.state = "injured"
                    rider.injured_nights = self.rng.randint(1, 3)
                    injured_tonight.add(rider.id)
                    tr.note += " 骑手受了伤。"
            robbery_results.append(tr)

        # ── ③ 统一结算抵达 ──
        #
        # 遇劫的结果在阶段②就已经产生了，抵达的结果在这里产生。
        # 如果先后 append，同一夜的结果顺序就取决于「哪个阶段先跑」，
        # 而不是 id。所以这里把三类结果**先收集、再按 id 排序、最后统一写入**。
        pending = list(robbery_results)

        arrived = [t for t in self.trips if t.arrived()]
        arrived.sort(key=id_key)

        # 本夜归队的人马——他们**当夜不恢复**，下一夜才开始恢复和重新派遣
        returned_tonight: set = set()

        for trip in arrived:
            returned_tonight.add(trip.rider_id)
            returned_tonight.add(trip.horse_id)
            if self.faith <= 0:
                # 已经判定失败：这趟不能再结算，但**必须留下记录**，
                # 否则它会从 history 里凭空消失、送达率分母也少算。
                pending.append(self._aborted_result(
                    trip, "驿被撤了，这封信没能送到。"))
                continue
            pending.append(self._resolve_arrival(trip, result, injured_tonight))

        # 统一按 id 排序后写入。三类结果（遇劫 / 抵达 / 终止）不再分先后。
        pending.sort(key=lambda t: id_key(t.dispatch))
        result.trips.extend(pending)

        # 已抵达的都从在途列表移除
        arrived_ids = {t.id for t in arrived}
        self.trips = [t for t in self.trips if t.id not in arrived_ids]

        # 信归零：尚未抵达的任务一并终止。
        #
        # **资源不退还**——玩家是夜初决定派遣的，不能假装没派出去
        # （这是龙娘的裁决，哈基米原来的表述是「未派出」）。
        #
        # 但它们必须留下记录：派出去了、资源扣了，就该进送达率分母，
        # 否则终局统计会虚高。
        if self.faith <= 0:
            left = list(self.trips)
            self.trips.clear()
            for trip in sorted(left, key=id_key):
                result.trips.append(
                    self._aborted_result(trip, "驿被撤了，这封信没能送到。"))
            if left:
                self.note("信已见底，驿被撤了。还有 %d 支队伍在路上。" % len(left), "end")

        # 休息：本夜没被指派、没受伤、不在路上、**也不是今夜刚归队的**
        #
        # 「刚归队」这一条是关键：抵达当夜人马仍算占用，下一夜才恢复。
        # 早先只挡了「本夜被指派的人」（seen_r），跨夜抵达的人不在 seen_r 里，
        # 于是抵达当夜就白拿了一份休息加成——等于路上跑一趟还倒赚体力。
        for r in self.riders:
            if (r.state == "idle" and r.id not in seen_r
                    and r.id not in returned_tonight
                    and not self.is_busy(rider_id=r.id)):
                r.stamina = _clamp(r.stamina + B.REST_STAMINA_GAIN, 0, 100)

        # 伤兵恢复。本夜刚受伤的不参与倒计时（沿用 v0.3.0 的保护逻辑）。
        for r in self.riders:
            if r.state == "injured" and r.id not in injured_tonight:
                r.injured_nights -= 1
                if r.injured_nights <= 0:
                    r.state = "idle"
                    r.injured_nights = 0
                    self.note("%s 的伤好了。" % r.name)

        # 马每夜自然恢复——只给「今晚没出勤、不在路上、也不是今夜刚归队」的。
        for h in self.horses:
            if (h.id not in seen_h
                    and h.id not in returned_tonight
                    and not self.is_busy(horse_id=h.id)):
                if h.condition < 100:
                    h.condition = _clamp(h.condition + B.HORSE_NATURAL_RECOVERY, 0, 100)

        self.history.append(result)
        self.log_trips(result)

        # 预报准不准，当场告诉玩家
        if not result.forecast_was_right:
            self.note("昨夜预报 %s，实际 %s —— 没准。" % (
                B.WEATHER[result.forecast]["name"],
                B.WEATHER[result.weather]["name"]), "weather")

        # 结束判定
        if self.faith <= 0:
            self._finish(False, "驿被撤了。")
        elif self.night >= B.TOTAL_NIGHTS:
            # 第十二夜结束时还在路上的：按未送达处理。
            #
            # 定案（龙娘裁决 §8）：扣一次正常罚款、不获得奖励、
            # 计入总派遣数和送达率分母。
            #
            # 为什么不能「不扣罚」：那是个免费期权——最后一夜把所有人马
            # 撒出去，成功拿赏、失败不亏。
            self._settle_unfinished_on_final_night(result)
            # 最终罚款可能把信打到 0。那种情况是失败，不是「守住了」。
            if self.faith <= 0:
                self._finish(False, "驿被撤了。")
            else:
                self._finish(True, None)
        else:
            self.night += 1
            self.begin_night()

        return result

    def _aborted_result(self, trip: ActiveTrip, note: str) -> TripResult:
        """把这趟在途任务记成「没能送到」，用于归零/终局时补记录。"""
        rider = self.rider_by_id(trip.rider_id)
        horse = self.horse_by_id(trip.horse_id)
        return TripResult(
            dispatch=trip.dispatch,
            rider_name=rider.name if rider else "?",
            horse_name=horse.name if horse else "?",
            route=trip.route,
            nights_taken=trip.elapsed_nights,
            delivered=False, lost=False, event="aborted",
            note=note, events=list(trip.events),
        )

    def _settle_unfinished_on_final_night(self, result: NightResult):
        """十二夜结束仍未抵达的任务。

        这是「战役结束造成的最终超时」，不代表信件遗失——
        但对玩家来说结果一样：没送到。
        """
        if not self.trips:
            return
        left = list(self.trips)
        self.trips.clear()
        for trip in sorted(left, key=id_key):
            d = trip.dispatch
            rider = self.rider_by_id(trip.rider_id)
            horse = self.horse_by_id(trip.horse_id)

            old = self.faith
            self.faith = _clamp(old - d.penalty, 0, B.MAX_FAITH)
            result.faith_delta += self.faith - old

            result.trips.append(
                self._aborted_result(trip, "信还在路上，十二夜就结束了。"))
        self.note("十二夜到了，还有 %d 支队伍在路上。" % len(left), "end")

    # ────────────────────── 抵达结算 ──────────────────────
    def _resolve_arrival(self, trip: ActiveTrip, result: NightResult,
                         injured_tonight: set) -> TripResult:
        """一支队伍走到了。判定送达/超时，扣赏罚，可能受伤。

        期限规则（定案）：期限决定信件能否成功，**不决定任务什么时候结束**。
        即使已经超期，人马仍然保持在途，直到真正抵达——
        但这里的 trip 已经抵达了，所以照常结算。
        """
        d = trip.dispatch
        rider = self.rider_by_id(trip.rider_id)
        horse = self.horse_by_id(trip.horse_id)
        if rider is None or horse is None:
            return

        nights_taken = trip.elapsed_nights
        delivered = (self.night <= trip.due_night)

        event_note = ""
        outcome_note = ""

        if delivered:
            self.gold += d.reward
            old = self.faith
            gain = int(round(B.FAITH_PER_DELIVER
                             * B.FAITH_DELIVER_MULT[d.kind]))
            self.faith = _clamp(old + gain, 0, B.MAX_FAITH)
            result.gold_delta += d.reward
            result.faith_delta += self.faith - old
            outcome_note = "送到了。"
        else:
            old = self.faith
            self.faith = _clamp(old - d.penalty, 0, B.MAX_FAITH)
            result.faith_delta += self.faith - old
            outcome_note = "晚了 %d 夜。" % (self.night - trip.due_night)

        trip_result = TripResult(
            dispatch=d,
            rider_name=rider.name,
            horse_name=horse.name,
            route=trip.route,
            nights_taken=nights_taken,
            delivered=delivered,
            lost=False,
            event="calm",
            note=(event_note + " " + outcome_note).strip() if event_note else outcome_note,
            events=list(trip.events),
        )

        # 抵达时受伤：变 injured，当夜不减倒计时
        if not delivered and self.rng.random() < 0.15:
            rider.state = "injured"
            rider.injured_nights = self.rng.randint(1, 2)
            injured_tonight.add(rider.id)
            trip_result.note += " 骑手受了伤。"

        return trip_result

    def log_trips(self, result: NightResult):
        for t in result.trips:
            route = B.ROUTES[t.route]["name"]
            kind = B.DISPATCH_KINDS[t.dispatch.kind]["name"]
            # 用中文标记而不是 ✓/×：很多中文字体没有这两个字形，会显示成方块
            tag = "[成]" if t.delivered else "[败]"
            self.note("%s %s %s %s：%s" % (
                tag, t.rider_name, route, kind, t.note), "trip")

    def _finish(self, survived: bool, why: Optional[str]):
        self.over = True
        delivered = sum(1 for nr in self.history for t in nr.trips if t.delivered)
        total = sum(len(nr.trips) for nr in self.history)
        rate = (delivered / total) if total else 0.0

        # 躺平也不能过关：一封信都没派过，就算熬到第 12 夜也是失败。
        # 否则最优解就是「什么都不做」，整个游戏就没意义了。
        idle = (total == 0)
        if idle and survived:
            survived = False
            why = "十二夜过去了，你一封也没派出去。"

        rating = "C"
        for th, label in B.RATING_THRESHOLDS:
            if self.faith >= th:
                rating = label
                break

        if not survived:
            self.result = {
                "survived": False, "faith": self.faith, "gold": self.gold,
                "delivered": delivered, "total": total, "rate": rate,
                "rating": "—", "why": why or "失败了。", "idle": idle,
            }
        else:
            ok = self.faith >= B.SURVIVE_FAITH
            if ok:
                why_text = "守住了。"
            elif self.faith >= B.ENDING_OK:
                why_text = "撑过了十二夜，但信已经薄了。"
            else:
                # 信掉到这个程度，已经不只是「薄」了
                why_text = "十二夜过去了。没人再指望这条驿路。"
            self.result = {
                "survived": True, "faith": self.faith, "gold": self.gold,
                "delivered": delivered, "total": total, "rate": rate,
                "rating": rating,
                "why": why_text,
                "idle": False,
            }
        self.note(self.result["why"], "end")

    # ────────────────────── 商店 ──────────────────────
    def _spend(self, amount: int) -> bool:
        if self.gold < amount:
            return False
        self.gold -= amount
        return True

    def hire_rider(self) -> Optional[Rider]:
        cost = B.PRICES["hire_rider"]
        if self.gold < cost:
            return None
        self.gold -= cost
        lo, hi = B.HIRE_SPEED_RANGE
        name = self._pick_name(self._name_pool, self._used_names)
        r = Rider(name=name, speed=round(self.rng.uniform(lo, hi), 2), stamina=100.0)
        self.riders.append(r)
        self.note("雇了 %s，脚力 %.2f。" % (r.name, r.speed))
        return r

    def buy_horse(self) -> Optional[Horse]:
        cost = B.PRICES["buy_horse"]
        if self.gold < cost:
            return None
        self.gold -= cost
        lo, hi = B.BUY_HORSE_SPEED_RANGE
        name = self._pick_name(self._horse_pool, self._used_horse_names)
        h = Horse(name=name, speed=round(self.rng.uniform(lo, hi), 2), condition=100.0)
        self.horses.append(h)
        self.note("买了 %s，脚力 %.2f。" % (h.name, h.speed))
        return h

    def feed(self, horse_id: str) -> bool:
        cost = B.PRICES["feed"]
        h = self.horse_by_id(horse_id)
        if h is None or self.gold < cost:
            return False
        # 在路上喂不了。这条必须在核心层挡，不能只靠 UI。
        if self.is_busy(horse_id=horse_id):
            return False
        self.gold -= cost
        h.condition = _clamp(h.condition + B.FEED_CONDITION_GAIN, 0, 100)
        self.note("给 %s 喂了料。" % h.name)
        return True

    def buy_oil(self) -> bool:
        cost = B.PRICES["oil"]
        if self.gold < cost:
            return False
        self.gold -= cost
        self.oil = _clamp(self.oil + B.OIL_REFILL_AMOUNT, 0, B.MAX_OIL)
        self.note("添了油。")
        return True

    def repair_route(self, route_key: str) -> bool:
        if route_key not in B.ROUTES or route_key in self.route_repaired:
            return False
        cost = B.ROUTES[route_key]["repair_cost"]
        if self.gold < cost:
            return False
        self.gold -= cost
        self.route_distance[route_key] = max(1, self.route_distance[route_key] - 1)
        self.route_repaired.add(route_key)
        self.note("修了 %s，路短了一截。" % B.ROUTES[route_key]["name"])
        return True

    # ────────────────────── 查询 ──────────────────────
    def rider_by_id(self, rid: str) -> Optional[Rider]:
        return next((r for r in self.riders if r.id == rid), None)

    def horse_by_id(self, hid: str) -> Optional[Horse]:
        return next((h for h in self.horses if h.id == hid), None)

    def dispatch_by_id(self, did: str) -> Optional[Dispatch]:
        return next((d for d in self.dispatches if d.id == did), None)

    def available_riders(self) -> list[Rider]:
        """能派的骑手：没伤、也不在路上。"""
        return [r for r in self.riders
                if r.state == "idle" and not self.is_busy(rider_id=r.id)]

    def available_horses(self) -> list[Horse]:
        """能用的马：不在路上。

        马没有 state 字段——可用性完全由 ActiveTrip 决定。
        """
        return [h for h in self.horses if not self.is_busy(horse_id=h.id)]

    # ────────────────────── 序列化（存档用） ──────────────────────
    def to_dict(self) -> dict:
        return {
            "version": 3,
            "seed": self.seed,
            "night": self.night,
            "faith": self.faith,
            "gold": self.gold,
            "oil": self.oil,
            "riders": [r.to_dict() for r in self.riders],
            "horses": [h.to_dict() for h in self.horses],
            "route_distance": dict(self.route_distance),
            "route_repaired": sorted(self.route_repaired),
            "weather": self.weather,
            "forecast": self.forecast,
            "dispatches": [d.to_dict() for d in self.dispatches],
            "trips": [t.to_dict() for t in self.trips],
            "over": self.over,
            "result": self.result,
            "log": self.log[-100:],
            "history": [nr.to_dict() for nr in self.history[-12:]],
            "rng_state": repr(self.rng.getstate()),
            "event_rng_state": repr(self.event_rng.getstate()),
            "used_names": sorted(self._used_names),
            "used_horse_names": sorted(self._used_horse_names),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GameState":
        """从存档恢复。

        坑：`models._id_counter` 是模块级自增。如果直接构造对象，新 id 会从
        当前计数器继续往上走——但读档时计数器可能比存档里的 id 小，
        于是新雇的骑手会和存档里的骑手**撞号**。
        所以恢复完立刻把计数器推到所有已有 id 之上。
        """
        from dataclasses import fields as _fields
        from . import models as _m

        # 绕开 __init__：它会把整局重开一遍
        gs = cls.__new__(cls)

        gs.seed = d.get("seed")
        gs.rng = random.Random()
        if d.get("rng_state"):
            try:
                gs.rng.setstate(ast.literal_eval(d["rng_state"]))
            except (ValueError, SyntaxError):
                # 随机状态坏了不至于让存档作废，只是这局不再可复现
                gs.rng.seed(0 if gs.seed is None else gs.seed)

        # 事件随机流独立，单独恢复。
        # 旧存档（v3 之前）没有这个字段：用同样的派生规则重建，
        # 不追求和旧局完全一致——旧局本来就没有这个流。
        gs.event_rng = random.Random()
        seed = gs.seed
        gs.event_rng.seed(None if seed is None else seed ^ 0x5EED_E7E17)
        if d.get("event_rng_state"):
            try:
                gs.event_rng.setstate(ast.literal_eval(d["event_rng_state"]))
            except (ValueError, SyntaxError):
                pass

        gs.night = int(d.get("night", 1))
        gs.faith = int(d.get("faith", B.START_FAITH))
        gs.gold = float(d.get("gold", B.START_GOLD))
        gs.oil = float(d.get("oil", B.START_OIL))

        gs.riders = [Rider.from_dict(x) for x in d.get("riders", [])]
        gs.horses = [Horse.from_dict(x) for x in d.get("horses", [])]

        gs.route_distance = dict(d.get("route_distance")
                                 or {k: v["distance"] for k, v in B.ROUTES.items()})
        gs.route_repaired = set(d.get("route_repaired") or [])

        gs.weather = d.get("weather")
        gs.forecast = d.get("forecast")
        gs.dispatches = [Dispatch.from_dict(x) for x in d.get("dispatches", [])]
        gs.trips = [ActiveTrip.from_dict(x) for x in d.get("trips", [])]

        gs.over = bool(d.get("over", False))
        gs.result = d.get("result")
        gs.log = list(d.get("log") or [])

        # 历史必须一起恢复。
        # 早先这里写的是 gs.history = []，而 to_dict() 明明存了 —— 于是：
        #   1. 读档后累计送达率只统计读档之后的部分，终局显示的数字是错的；
        #   2. 更糟：如果读档后一封信都没派，_finish() 会看到 total==0，
        #      判成「十二夜过去了，你一封也没派出去」直接失败。
        #      玩家存了档反而更容易输。
        gs.history = [NightResult.from_dict(x) for x in d.get("history", [])]

        # 名字池（供后续雇佣/买马取名）
        gs._name_pool = [
            "阿石", "老周", "七斤", "顺子", "哑叔", "小六", "阿桃",
            "铁头", "麻子", "栓柱", "阿绣", "黑娃",
        ]
        gs._horse_pool = [
            "踏雪", "赤云", "墨点", "黄骠", "白尾", "青鬃", "驮山", "小月",
        ]
        gs._used_names = set(d.get("used_names") or
                             [r.name for r in gs.riders])
        gs._used_horse_names = set(d.get("used_horse_names") or
                                   [h.name for h in gs.horses])

        # 把模块级 id 计数器推到所有已用 id 之上，避免撞号
        max_id = 0
        for obj in (list(gs.riders) + list(gs.horses)
                    + list(gs.dispatches) + list(gs.trips)):
            try:
                max_id = max(max_id, int(obj.id.lstrip("rhd")))
            except (ValueError, AttributeError):
                continue
        if max_id > 0:
            _m._id_counter = itertools.count(max_id + 1)

        return gs
