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
        """用某骑手+某马送这封信，要跑几夜。

        light_factor 显式传入时用它，否则读当前油量。
        夜初算一次、整夜复用——见 advance() 里的说明。
        """
        w = weather or self.weather or "clear"
        dist = self.route_distance[dispatch.route]
        wf = B.WEATHER[w]["route_factor"][dispatch.route]
        light = self.current_light_factor() if light_factor is None else light_factor
        speed = (rider.effective_speed() * horse.effective_speed()
                 * wf * light * B.BASE_TRAVEL)
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
    def advance(self, assignments: Iterable[tuple],
                resting: Iterable[str] = ()) -> NightResult:
        """推进一夜。

        assignments: [(dispatch, rider, horse), ...]

        resting 参数已废弃：现在自动推断——**本夜没被指派、也没受伤的骑手
        就是歇着**。保留这个参数只是为了让旧调用不报错，传了也不生效。

        早先必须由调用方显式传 resting，一旦 UI 或测试漏传，就会出现
        「站着发呆一整晚却不回体力」。这种「调用方必须记得做某件事」的
        设计迟早会出问题，所以改成规则内建。
        """
        if self.over:
            raise RuntimeError("本局已经结束")

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

        # 按信 id 排序后再结算。
        #
        # 这是「派遣顺序不影响结果」的第二层保障。第一层是灯系数在夜初定死，
        # 但还有一层更隐蔽的：random 是按派单顺序逐个消耗的，
        # `_roll_event()` 抽到顺风还是落石，取决于它是第几个被结算的。
        # 于是「同样这封信、同样这个骑手」，点它在第一位还是第二位，
        # 结果可能完全不同——而这同样不是玩家能控制的。
        #
        # 排序之后，随机数消耗顺序与点击顺序无关，结果完全确定。
        # 附带好处：日志里同一夜的多封总是按固定顺序出现。
        assignments.sort(key=lambda a: a[0].id)

        weather = self.weather or "clear"
        result = NightResult(
            night=self.night,
            weather=weather,
            forecast=self.forecast or weather,
            forecast_was_right=(self.forecast == weather),
        )

        # 灯的系数在夜初定死，整夜所有派单都用同一个值。
        #
        # 早先这里是每次算行进时现读 self.oil，而油又在同一夜里边派边扣。
        # 结果：第一趟还看得见，第二趟就没灯了——「谁先派」直接决定了谁快谁慢。
        # 实测同一个局面只换点击顺序：
        #   顺序 A 老陈 2 夜 / 小满 4 夜
        #   顺序 B 小满 2 夜 / 老陈 5 夜
        # 而顺序取决于字典遍历顺序，玩家根本控制不了。这是纯粹的公平性 bug。
        light = self.current_light_factor()

        # 拒收的信
        taken_ids = {d.id for d, _, _ in assignments}
        result.dropped = [d for d in self.dispatches if d.id not in taken_ids]

        injured_tonight: set[str] = set()
        revoked_at: Optional[int] = None

        for idx, (d, r, h) in enumerate(assignments):
            # 信已归零 = 驿被撤了，剩下的派单不该再出去。
            # 早先这里会把后面的信继续结算完——已经判定失败了还在扣资源、
            # 还在让骑手受伤，日志里也照常记一笔。
            if self.faith <= 0:
                revoked_at = idx
                break

            nights = self.travel_nights(d, r, h, weather, light)
            event = self._roll_event(d, weather)

            delivered = False
            lost = False
            event_note = ""     # 顺风 / 迷路 / 落石 / 遇劫
            outcome_note = ""   # 送到了 / 晚了 N 夜 / 没能送出去

            if event == "tailwind":
                nights = max(1, nights - 1)
                event_note = "顺风，快了一夜。"
            elif event == "lost":
                nights += 1
                event_note = "迷路，慢了一夜。"
            elif event == "rockfall":
                nights = 99
                event_note = "落石，原路折返。"
            elif event == "robbery":
                lost = True
                nights = 99
                event_note = "遇劫，信没了。"

            if not lost:
                delivered = (nights <= d.deadline)
                if delivered:
                    self.gold += d.reward
                    # 信按整数累加。
                    # 差额必须记「实际变化」，不是「打算加多少」——
                    # 撞到 0 或 100 的边界时两者不同：信 99 时送达八百里（+7），
                    # 实际只加到 100（+1），但早先记录的是 +7，
                    # 结算页的「本夜信 +7」就和真实状态对不上。
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
                    if nights >= 99:
                        outcome_note = "没能送出去。"
                    else:
                        outcome_note = "晚了 %d 夜。" % (nights - d.deadline)
            else:
                # 遇劫：信按「一半罚款」计。
                # 早先这里是全额罚——八百里一次 -20 信，相当于总信量的 1/4，
                # 而触发概率只有 5%。打满一局才发现：一次骰子就能抹掉四夜的进度，
                # 那不是难度，是方差。现在保留痛感（-7~10），但不再致命。
                old = self.faith
                rob_pen = max(1, d.penalty // 2)
                self.faith = _clamp(old - rob_pen, 0, B.MAX_FAITH)
                result.faith_delta += self.faith - old

            # 事件和结果是两件事，都要留在日志里。
            # 早先只有一个 note，顺风一触发就把后面「超时失败」的原因盖掉了：
            # 日志写着「顺风，快了一夜」，实际这封信没送到。
            note = event_note
            if outcome_note:
                note = (event_note + " " + outcome_note).strip() if event_note else outcome_note

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
                injured_tonight.add(r.id)
                trip.note += " 骑手受了伤。"

        # 归零后没来得及出去的派单，补进拒收列表。
        #
        # 索引从 revoked_at（不是 revoked_at + 1）开始：
        # revoked_at 是「发现已经归零、因此 break 掉」的那一封，它自己也没出去。
        # 早先从 +1 开始，那一封就凭空消失了——拒收少算一封、日志也少一条。
        if revoked_at is not None:
            for d, _, _ in assignments[revoked_at:]:
                if d not in result.dropped:
                    result.dropped.append(d)
            remaining = len(assignments) - revoked_at
            self.note("信已见底，驿被撤了。剩下 %d 封信没能发出。" % remaining, "end")

        # 休息：自动推断，不靠调用方传参
        for r in self.riders:
            if r.state == "idle" and r.id not in used_r:
                r.stamina = _clamp(r.stamina + B.REST_STAMINA_GAIN, 0, 100)

        # 伤兵恢复。
        #
        # 关键：**本夜刚受伤的骑手不参与倒计时**。
        # 早先这里是遍历所有 injured 骑手一律 -1，而受伤判定就在同一函数里、
        # 就在上面——于是「抽到 1 夜的伤」当晚立刻被减到 0 直接痊愈。
        # 实测 400 次强制失败：36 次保持受伤、20 次当场就好，
        # 也就是说受伤机制有一半是失效的。
        for r in self.riders:
            if r.state == "injured" and r.id not in injured_tonight:
                r.injured_nights -= 1
                if r.injured_nights <= 0:
                    r.state = "idle"
                    r.injured_nights = 0
                    self.note("%s 的伤好了。" % r.name)

        # 马每夜自然恢复一点——**只给今晚没出勤的马**。
        # 早先这里是无条件遍历所有马，跑完任务的马当晚也会 +2，
        # 于是实际净消耗变成「扣 15 再回 2」，和 README 写的
        # 「不跑也会自己回一点」不符。
        for h in self.horses:
            if h.id not in used_h and h.condition < 100:
                h.condition = _clamp(h.condition + B.HORSE_NATURAL_RECOVERY, 0, 100)

        self.history.append(result)
        self.log_trips(result)

        # 预报准不准，当场告诉玩家。
        # 早先这个信息只在结算日志里有，游戏过程中完全没有反馈——
        # 而「预报只有七成准」正是整个游戏的信息核心，
        # 玩家却永远学不到它到底准到什么程度。
        if not result.forecast_was_right:
            self.note("昨夜预报 %s，实际 %s —— 没准。" % (
                B.WEATHER[result.forecast]["name"],
                B.WEATHER[result.weather]["name"]), "weather")

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
            "version": 2,
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
        for obj in list(gs.riders) + list(gs.horses) + list(gs.dispatches):
            try:
                max_id = max(max_id, int(obj.id.lstrip("rhd")))
            except (ValueError, AttributeError):
                continue
        if max_id > 0:
            _m._id_counter = itertools.count(max_id + 1)

        return gs
