# -*- coding: utf-8 -*-
"""两个模拟器共用的 AI 策略。

## 为什么要统一

`tools/sim_balance.py` 和 `tools/ai_optimal.py` 原本各写了一套策略，
而且两边都有同一个毛病：**调用 `travel_nights()` 时不传天气**，
于是拿到的是 `self.weather`（本夜**实际**天气）。

这等于让 AI 偷看答案。测出来的难度比玩家实际面对的偏低约 8 个百分点
（通关 81% vs 73%）——而当时这两个工具一直在给我「平衡合适」的假信号。

现在两边都从这里取策略，且**只用预报**（`gs.forecast`），和真实玩家拿到的
信息完全一致。改这里 = 同时改两个工具。

## 策略是什么

一个懂行的玩家会做的事：

1. 优先派「信/罚」比高、且按预报能赶上的信
2. 留一点余量给坏天气（余量为 0 的派单降低评分）
3. 骑手体力低于阈值就让他歇
4. 有钱就补人/补马/喂料/添油

参数都在 `Strategy` 上，`ai_optimal.py` 会扫这些参数找最优解。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from relay.core import balance as B      # noqa: E402
from relay.core.sim import GameState     # noqa: E402


@dataclass
class Strategy:
    """一组可调的行为参数。"""

    rest_at: float = 45.0        # 体力低于这个值就不派，让他歇
    feed_at: float = 55.0        # 马的状态低于这个值就喂
    hire_below: int = 4          # 可用骑手少于这个数就雇
    horse_cap: int = 4           # 马最多买到几匹
    oil_at: float = 40.0         # 油低于这个值就添
    min_margin: int = 0          # 只要余量 >= 这个值的信（0=不限）
    prefer_faith: bool = True    # 按「信」权重排序，否则按金

    # ── 估值 ──
    def value(self, d) -> float:
        """一封值的分数。信是主目标，金是手段。"""
        faith = B.FAITH_PER_DELIVER * B.FAITH_DELIVER_MULT[d.kind]
        if self.prefer_faith:
            return faith * 10.0 + d.reward * 0.15 - d.penalty * 0.05
        return d.reward * 1.0 + faith * 2.0

    # ── 排班 ──
    def plan(self, gs: GameState):
        """返回 (assignments, 用掉的骑手 id 集合)。

        信息约束：**只看 gs.forecast**，不看 gs.weather。
        这是整个模拟器的可信度基准——一旦这里读了实际天气，
        测出来的难度就比玩家实际面对的低。

        在途模型下，可用性必须走 GameState 查询（骑手/马不能在路上），
        不能只看 Rider.state——那是 v0.3.x 留下的坑。
        """
        riders = gs.available_riders()
        ready = [r for r in riders if r.stamina >= self.rest_at]
        horses = gs.available_horses()

        cands = []
        for d in gs.dispatches:
            best = None
            for r in ready:
                for h in horses:
                    n = gs.travel_nights(d, r, h, gs.forecast)
                    if n > d.deadline:
                        continue
                    margin = d.deadline - n
                    if margin < self.min_margin:
                        continue
                    # 零余量的派单打九折：坏天气一来就废
                    score = self.value(d) * (1.0 if margin > 0 else 0.9)
                    if best is None or score > best[0]:
                        best = (score, r, h)
            if best:
                cands.append((best[0], d, best[1], best[2]))

        cands.sort(key=lambda x: -x[0])

        used_r, used_h, plan = set(), set(), []
        for _score, d, r, h in cands:
            if r.id in used_r or h.id in used_h:
                continue
            used_r.add(r.id)
            used_h.add(h.id)
            plan.append((d, r, h))
        return plan, used_r

    # ── 采购 ──
    def shop(self, gs: GameState, used_r: set) -> list[str]:
        """按优先级花钱，返回做了什么（给日志用）。"""
        done = []

        # 油是刚需：没灯全队减速 35%
        if gs.oil < self.oil_at and gs.gold >= B.PRICES["oil"]:
            if gs.buy_oil():
                done.append("添油")

        # 喂最瘦的马
        if gs.gold >= B.PRICES["feed"] + 60:
            worst = min(gs.horses, key=lambda x: x.condition, default=None)
            if worst and worst.condition < self.feed_at:
                if gs.feed(worst.id):
                    done.append("喂" + worst.name)

        # 人不够就雇——人力才是真正的瓶颈。
        # 注意：这里要用 available_riders（排除在途），
        # 不能用 state != "injured"——那会把在途的人也算成可用。
        avail = len(gs.available_riders())
        if avail < self.hire_below and gs.gold >= B.PRICES["hire_rider"] + 80:
            r = gs.hire_rider()
            if r:
                done.append("雇" + r.name)
                return done

        # 马比骑手少就补马
        usable = len(gs.available_horses())
        if (usable < min(avail, self.horse_cap)
                and gs.gold >= B.PRICES["buy_horse"] + 100):
            h = gs.buy_horse()
            if h:
                done.append("买" + h.name)

        return done


def play(gs: GameState, strat: Optional[Strategy] = None,
         max_turns: int = 40) -> GameState:
    """用一套策略把一局打完。"""
    strat = strat or Strategy()
    guard = 0
    while not gs.over and guard < max_turns:
        guard += 1
        plan, used = strat.plan(gs)
        gs.advance(plan)
        if not gs.over:
            strat.shop(gs, used)
    return gs


def run_many(n: int, strat: Optional[Strategy] = None,
             seed_offset: int = 0) -> list[GameState]:
    """跑 n 局，返回每局的终态。"""
    out = []
    for i in range(n):
        gs = GameState(seed=seed_offset + i)
        out.append(play(gs, strat))
    return out
