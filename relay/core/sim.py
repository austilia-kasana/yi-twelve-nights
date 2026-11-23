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

import math
import random
from typing import Iterable, Optional

from . import balance as B
from .models import Dispatch, Horse, NightResult, Rider, TripResult


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
        self.rng = random.Random(seed)

        self.night = 1
        self.faith = float(B.START_FAITH)
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
                      weather: Optional[str] = None) -> int:
        """用某骑手+某马送这封信，要跑几夜。"""
        w = weather or self.weather or "clear"
        dist = self.route_distance[dispatch.route]
        wf = B.WEATHER[w]["route_factor"][dispatch.route]
        speed = (rider.effective_speed() * horse.effective_speed()
                 * wf * self.current_light_factor() * B.BASE_TRAVEL)
        if speed <= 0.01:
            return 99
        return max(1, int(math.ceil(dist / speed)))

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
    def advance(self, assignments: Iterable[tuple], resting: Iterable[str] = ()) -> NightResult:
        """推进一夜。

        assignments: [(dispatch, rider, horse), ...]
        resting:     休息的骑手 id 集合（+体力）
        """
        if self.over:
            raise RuntimeError("本局已经结束")

        resting = set(resting)
        assignments = list(assignments)

        # 用到的骑手/马不能重复
        used_r, used_h = set(), set()
        for d, r, h in assignments:
            if r.id in used_r:
                raise ValueError("同一个骑手被派了两次：%s" % r.name)
            if h.id in used_h:
                raise ValueError("同一匹马被用了两次：%s" % h.name)
            used_r.add(r.id)
            used_h.add(h.id)

        weather = self.weather or "clear"
        result = NightResult(
            night=self.night,
            weather=weather,
            forecast=self.forecast or weather,
            forecast_was_right=(self.forecast == weather),
        )

        # 拒收的信
        taken_ids = {d.id for d, _, _ in assignments}
        result.dropped = [d for d in self.dispatches if d.id not in taken_ids]

        for d, r, h in assignments:
            nights = self.travel_nights(d, r, h, weather)
            event = self._roll_event(d, weather)

            delivered = False
            lost = False
            note = ""

            if event == "tailwind":
                nights = max(1, nights - 1)
                note = "顺风，快了一夜。"
            elif event == "lost":
                nights += 1
                note = "迷路，慢了一夜。"
            elif event == "rockfall":
                nights = 99
                note = "落石，原路折返。"
            elif event == "robbery":
                lost = True
                nights = 99
                note = "遇劫，信没了。"

            if not lost:
                delivered = (nights <= d.deadline)
                if delivered:
                    self.gold += d.reward
                    faith_gain = B.FAITH_PER_DELIVER * B.FAITH_DELIVER_MULT[d.kind]
                    self.faith = _clamp(self.faith + faith_gain, 0, B.MAX_FAITH)
                    result.gold_delta += d.reward
                    result.faith_delta += int(round(faith_gain))
                    note = note or "送到了。"
                else:
                    self.faith = _clamp(self.faith - d.penalty, 0, B.MAX_FAITH)
                    result.faith_delta -= d.penalty
                    if not note:
                        note = "晚了一夜。" if nights < 99 else "没能送出去。"
            else:
                # 遇劫：信按「一半罚款」计。
                # 早先这里是全额罚——八百里一次 -20 信，相当于总信量的 1/4，
                # 而触发概率只有 5%。打满一局才发现：一次骰子就能抹掉四夜的进度，
                # 那不是难度，是方差。现在保留痛感（-7~10），但不再致命。
                rob_pen = max(1, d.penalty // 2)
                self.faith = _clamp(self.faith - rob_pen, 0, B.MAX_FAITH)
                result.faith_delta -= rob_pen

            trip = TripResult(
                dispatch=d, rider_name=r.name, horse_name=h.name,
                route=d.route, nights_taken=nights,
                delivered=delivered, lost=lost, event=event, note=note,
            )
            result.trips.append(trip)

            # 消耗
            r.stamina = _clamp(
                r.stamina - self.rng.uniform(B.STAMINA_COST_MIN, B.STAMINA_COST_MAX),
                0, 100)
            h.condition = _clamp(
                h.condition - self.rng.uniform(B.HORSE_COST_MIN, B.HORSE_COST_MAX),
                0, 100)
            # 油
            self.oil = max(0.0, self.oil - self.rng.uniform(4, 8))

            if not delivered and not lost and self.rng.random() < 0.15:
                r.state = "injured"
                r.injured_nights = self.rng.randint(1, 2)
                trip.note += " 骑手受了伤。"

        # 休息
        for r in self.riders:
            if r.id in resting and r.state == "idle":
                r.stamina = _clamp(r.stamina + B.REST_STAMINA_GAIN, 0, 100)

        # 伤兵恢复
        for r in self.riders:
            if r.state == "injured":
                r.injured_nights -= 1
                if r.injured_nights <= 0:
                    r.state = "idle"
                    r.injured_nights = 0
                    self.note("%s 的伤好了。" % r.name)

        # 马每夜自然恢复一点。
        # 早先马不跑就永远不动，玩家会在第 6 夜左右突然发现「全员瘫痪」，
        # 而且不知道是怎么走到那一步的。给一点自然恢复，让失误可挽回。
        for h in self.horses:
            if h.condition < 100:
                h.condition = _clamp(h.condition + B.HORSE_NATURAL_RECOVERY, 0, 100)

        self.history.append(result)
        self.log_trips(result)

        # 结束判定
        if self.faith <= 0:
            self._finish(False, "驿被撤了。")
        elif self.night >= B.TOTAL_NIGHTS:
            self._finish(True, None)
        else:
            self.night += 1
            self.begin_night()

        return result

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
        return [r for r in self.riders if r.is_available()]

    def usable_horses(self) -> list[Horse]:
        return list(self.horses)

    # ────────────────────── 序列化（存档用） ──────────────────────
    def to_dict(self) -> dict:
        return {
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
            "over": self.over,
            "result": self.result,
            "log": self.log[-100:],
            "history": [nr.to_dict() for nr in self.history[-12:]],
            "rng_state": repr(self.rng.getstate()),
        }
