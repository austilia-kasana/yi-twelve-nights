# -*- coding: utf-8 -*-
"""核心数据模型：骑手、马、信、路线、天气。

这里只有数据结构，没有游戏规则。规则在 sim.py。
所有对象都是可变 dataclass，因为 get_state / set_state 之类的存档会需要。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Optional

# 全局自增 id，保证同局内唯一
_id_counter = itertools.count(1)


def _next_id(prefix: str) -> str:
    return "%s%d" % (prefix, next(_id_counter))


# ────────────────────────── 骑手 ──────────────────────────
@dataclass
class Rider:
    name: str
    speed: float
    stamina: float = 100.0
    state: str = "idle"            # idle | out | injured
    injured_nights: int = 0
    id: str = field(default_factory=lambda: _next_id("r"))

    def is_available(self) -> bool:
        return self.state == "idle"

    def effective_speed(self) -> float:
        """考虑体力衰减后的实际脚力。"""
        from . import balance as B
        s = self.speed
        if self.stamina < B.STAMINA_LOW:
            s *= B.STAMINA_PENALTY
        return s

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "speed": self.speed,
            "stamina": self.stamina, "state": self.state,
            "injured_nights": self.injured_nights,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Rider":
        return cls(
            name=d["name"], speed=d["speed"], stamina=d["stamina"],
            state=d.get("state", "idle"), injured_nights=d.get("injured_nights", 0),
            id=d["id"],
        )


# ────────────────────────── 马 ──────────────────────────
@dataclass
class Horse:
    name: str
    speed: float
    condition: float = 100.0
    id: str = field(default_factory=lambda: _next_id("h"))

    def effective_speed(self) -> float:
        from . import balance as B
        s = self.speed
        if self.condition < B.HORSE_LOW:
            s *= B.HORSE_PENALTY
        return s

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "speed": self.speed,
                "condition": self.condition}

    @classmethod
    def from_dict(cls, d: dict) -> "Horse":
        return cls(name=d["name"], speed=d["speed"], condition=d["condition"], id=d["id"])


# ────────────────────────── 信 ──────────────────────────
@dataclass
class Dispatch:
    route: str                 # north | ford | mine
    kind: str                  # normal | urgent | express
    deadline: int              # 夜数
    reward: int
    penalty: int
    text: str = ""
    id: str = field(default_factory=lambda: _next_id("d"))

    def label(self) -> str:
        from . import balance as B
        return B.DISPATCH_KINDS[self.kind]["name"]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "route": self.route, "kind": self.kind,
            "deadline": self.deadline, "reward": self.reward,
            "penalty": self.penalty, "text": self.text,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Dispatch":
        return cls(route=d["route"], kind=d["kind"], deadline=d["deadline"],
                   reward=d["reward"], penalty=d["penalty"],
                   text=d.get("text", ""), id=d["id"])


# ────────────────────────── 排班 ──────────────────────────
@dataclass
class Assignment:
    """一封被接下的信 + 派给它的骑手和马。"""
    dispatch: Dispatch
    rider: Rider
    horse: Horse

    def to_dict(self) -> dict:
        return {
            "dispatch": self.dispatch.id,
            "rider": self.rider.id,
            "horse": self.horse.id,
        }


# ────────────────────────── 在途任务 ──────────────────────────
@dataclass
class ActiveTrip:
    """一趟还在路上的运送。

    这是「谁在途」的**唯一事实来源**：Rider 和 Horse 上都不存 out 状态，
    可用性由 GameState 查这个列表得出。这样就不会出现「任务结束了但骑手
    还挂着 out」这类状态不同步。

    时间语义（见 docs/TRANSPORT.md 第 1 节）：
        第 N 夜出发 → 当夜推进第一次
        第 N+1 夜    → 推进第二次，抵达
        第 N+2 夜    → 人马归队
    """

    dispatch: Dispatch
    rider_id: str
    horse_id: str
    route: str
    distance: float            # 出发时锁定（修路不影响已出发的任务）
    progress: float = 0.0
    depart_night: int = 1
    elapsed_nights: int = 0
    due_night: int = 1         # 绝对夜数 = depart_night + deadline - 1
    light_factor: float = 1.0  # 出发时锁定，整趟不变
    events: list = field(default_factory=list)
    id: str = field(default_factory=lambda: _next_id("t"))

    @property
    def remaining(self) -> float:
        return max(0.0, self.distance - self.progress)

    @property
    def ratio(self) -> float:
        """走了几成。给 UI 用。"""
        if self.distance <= 0:
            return 1.0
        return min(1.0, self.progress / self.distance)

    def arrived(self) -> bool:
        return self.progress >= self.distance

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "dispatch": self.dispatch.to_dict(),
            "rider_id": self.rider_id,
            "horse_id": self.horse_id,
            "route": self.route,
            "distance": self.distance,
            "progress": self.progress,
            "depart_night": self.depart_night,
            "elapsed_nights": self.elapsed_nights,
            "due_night": self.due_night,
            "light_factor": self.light_factor,
            "events": list(self.events),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ActiveTrip":
        return cls(
            dispatch=Dispatch.from_dict(d["dispatch"]),
            rider_id=d["rider_id"],
            horse_id=d["horse_id"],
            route=d.get("route", "north"),
            distance=float(d.get("distance", 1)),
            progress=float(d.get("progress", 0.0)),
            depart_night=int(d.get("depart_night", 1)),
            elapsed_nights=int(d.get("elapsed_nights", 0)),
            due_night=int(d.get("due_night", 1)),
            light_factor=float(d.get("light_factor", 1.0)),
            events=list(d.get("events") or []),
            id=d.get("id", _next_id("t")),
        )


# ────────────────────────── 行进结果 ──────────────────────────
@dataclass
class TripResult:
    dispatch: Dispatch
    rider_name: str
    horse_name: str
    route: str
    nights_taken: int
    delivered: bool
    lost: bool                 # 信件彻底丢失（遇劫）
    event: str = "calm"        # 事件 key
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "dispatch": self.dispatch.to_dict(),
            "rider_name": self.rider_name, "horse_name": self.horse_name,
            "route": self.route, "nights_taken": self.nights_taken,
            "delivered": self.delivered, "lost": self.lost,
            "event": self.event, "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TripResult":
        return cls(
            dispatch=Dispatch.from_dict(d["dispatch"]),
            rider_name=d.get("rider_name", ""),
            horse_name=d.get("horse_name", ""),
            route=d.get("route", "north"),
            nights_taken=int(d.get("nights_taken", 0)),
            delivered=bool(d.get("delivered", False)),
            lost=bool(d.get("lost", False)),
            event=d.get("event", "calm"),
            note=d.get("note", ""),
        )


# ────────────────────────── 一夜的结算 ──────────────────────────
@dataclass
class NightResult:
    night: int
    weather: str               # 实际天气
    forecast: str              # 预报天气
    forecast_was_right: bool
    trips: list = field(default_factory=list)     # list[TripResult]
    gold_delta: int = 0
    faith_delta: int = 0
    dropped: list = field(default_factory=list)   # 拒收的 dispatch

    def to_dict(self) -> dict:
        return {
            "night": self.night, "weather": self.weather,
            "forecast": self.forecast,
            "forecast_was_right": self.forecast_was_right,
            "trips": [t.to_dict() for t in self.trips],
            "gold_delta": self.gold_delta, "faith_delta": self.faith_delta,
            "dropped": [d.to_dict() for d in self.dropped],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NightResult":
        return cls(
            night=int(d.get("night", 1)),
            weather=d.get("weather", "clear"),
            forecast=d.get("forecast", "clear"),
            forecast_was_right=bool(d.get("forecast_was_right", False)),
            trips=[TripResult.from_dict(x) for x in d.get("trips", [])],
            gold_delta=int(d.get("gold_delta", 0)),
            faith_delta=int(d.get("faith_delta", 0)),
            dropped=[Dispatch.from_dict(x) for x in d.get("dropped", [])],
        )
