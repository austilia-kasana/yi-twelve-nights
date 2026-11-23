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
