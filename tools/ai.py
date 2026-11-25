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


@dataclass
class SmartStrategy(Strategy):
    """更会玩的玩家：先算「同时能跑几趟」，再决定买什么。

    ## 为什么需要它

    Round 0 指标显示 base 策略会雇到 4 个骑手，却只买 2 匹马：
    买马要求 255 金（155 + 100 余量），雇人只要 130，所以钱都花在人上了。
    结果「人一堆，马两匹」，最多同时跑 2 趟，派遣利用率只有 35.7%。

    **但这不能直接证明「数值有问题」** —— 也可能只是这个 AI 不会算账。
    所以先做一个会算账的 AI，再看基准数据。

    ## 三条设计（按 GPT/Gemini 裁决）

    1. **编制目标用总数**：`target = min(len(gs.riders), horse_cap)`。
       用**总骑手数**，不用 `available_riders()`——在途的人也是编制的一部分，
       用可用数会让目标随当天在途人数缩水，永远追不上。

    2. **买马保护添油预算**：买之前先扣掉两夜的油钱，
       否则会出现「马买了、油没了、全队减速 35%」的净亏。

    3. **余量筛选**：`min_margin=1`。Round 0 数据显示零余量派单是亏损的。

    ## 这个字段以前只写在文档里

    v0.5.0 收尾时发现：上面第 3 条只写在 docstring 里，**类上没有这个字段**，
    于是 `SmartStrategy()` 的 `min_margin` 一直是继承来的 0——等于「三条设计」
    只实现两条。

    后果不是小事：`docs/CHANGELOG.md`、`ISSUES.md`、`balance.py` 里那套
    「500 局实测 达标 71.2% / S 27.2%」只有 `SmartStrategy(min_margin=1)`
    才复现得出来；而仓库自带的 `tools/sim_balance.py` 走的是 `Strategy()`，
    同一份代码跑出来是 达标 48% / S 16%。**同一份代码，两套数，没人发现。**
    """

    # 文档里的第 3 条，现在真的在这里。改它之前先跑 sim_balance.py 看曲线。
    min_margin: int = 1

    # 编制目标上限（只用于这个策略的买马判断）
    team_cap: int = 4
    # 买马前要留几夜的油钱
    oil_reserve_nights: int = 2

    def shop(self, gs: GameState, used_r: set) -> list[str]:
        done = []

        # ① 油是刚需：没灯全队减速 35%
        if gs.oil < self.oil_at and gs.gold >= B.PRICES["oil"]:
            if gs.buy_oil():
                done.append("添油")

        # ② 喂最瘦的马
        if gs.gold >= B.PRICES["feed"] + 60:
            worst = min(gs.horses, key=lambda x: x.condition, default=None)
            if worst and worst.condition < self.feed_at:
                if gs.feed(worst.id):
                    done.append("喂" + worst.name)

        # ③ 算「同时能跑几趟」= min(骑手总数, 马总数)
        #    这才是吞吐天花板，不是可用人数。
        target_horses = min(len(gs.riders), self.team_cap)
        oil_floor = B.PRICES["oil"] * self.oil_reserve_nights

        # ④ 马不够就先补马（人比马便宜，先雇人就永远缺马）
        if len(gs.horses) < target_horses:
            if gs.gold - B.PRICES["buy_horse"] >= oil_floor:
                h = gs.buy_horse()
                if h:
                    done.append("买" + h.name)
                    return done

        # ⑤ 人不够再雇
        if len(gs.riders) < self.hire_below:
            if gs.gold - B.PRICES["hire_rider"] >= oil_floor:
                r = gs.hire_rider()
                if r:
                    done.append("雇" + r.name)

        return done


@dataclass
class SmartAltStrategy(SmartStrategy):
    """`smart` 的对照变体：编制目标按 Q1 的另一种公式算。

    `target = min(骑手总数, 马总数)` —— 「马够配人就行」。
    用来回答 RELAY_Q1 的 Q1：两种公式哪个更能打通吞吐。
    """

    def shop(self, gs: GameState, used_r: set) -> list[str]:
        # 只在买马判断上不同，其他照抄父类
        done = []
        if gs.oil < self.oil_at and gs.gold >= B.PRICES["oil"]:
            if gs.buy_oil():
                done.append("添油")
        if gs.gold >= B.PRICES["feed"] + 60:
            worst = min(gs.horses, key=lambda x: x.condition, default=None)
            if worst and worst.condition < self.feed_at:
                if gs.feed(worst.id):
                    done.append("喂" + worst.name)

        target = min(len(gs.riders), len(gs.horses))
        oil_floor = B.PRICES["oil"] * self.oil_reserve_nights

        # 这个公式在「人 4 马 2」时 target=2，马数已等于目标 → 不会买马。
        # 保留它是为了用数据证明这个公式不行。
        if len(gs.horses) < min(target, self.team_cap):
            if gs.gold - B.PRICES["buy_horse"] >= oil_floor:
                h = gs.buy_horse()
                if h:
                    done.append("买" + h.name)
                    return done

        if len(gs.riders) < self.hire_below:
            if gs.gold - B.PRICES["hire_rider"] >= oil_floor:
                r = gs.hire_rider()
                if r:
                    done.append("雇" + r.name)
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
