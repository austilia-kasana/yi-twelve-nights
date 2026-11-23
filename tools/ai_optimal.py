# -*- coding: utf-8 -*-
"""找「能稳定拿 S」的打法。

S 需要终局信 >= 80。这个脚本用几个不同的策略跑很多局，
比较哪个策略的 S 率最高，并把最优策略的参数打出来。

用法：
  python tools/ai_optimal.py -n 300
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from relay.core import balance as B          # noqa: E402
from relay.core.sim import GameState         # noqa: E402


class Strategy:
    """一个可调参数的贪心策略。

    关键参数：
      rest_at      体力低于多少就让他歇
      feed_at      马状态低于多少就喂
      hire_below   可用骑手少于多少就雇人
      min_margin   期限富余多少夜才接（越大越保守）
      faith_weight 加权的重点：按「信/趟」还是按「金/趟」排序
    """

    def __init__(self, rest_at=45, feed_at=55, hire_below=3,
                 min_margin=0, prefer_faith=True, oil_at=30):
        self.rest_at = rest_at
        self.feed_at = feed_at
        self.hire_below = hire_below
        self.min_margin = min_margin
        self.prefer_faith = prefer_faith
        self.oil_at = oil_at

    # 一封送的「价值」：送达能得多少信 + 多少金
    def value(self, d):
        faith = B.FAITH_PER_DELIVER * B.FAITH_DELIVER_MULT[d.kind]
        if self.prefer_faith:
            return faith * 10.0 + d.reward * 0.15
        return d.reward * 1.0 + faith * 3.0

    def plan(self, gs):
        riders = [r for r in gs.riders if r.state == "idle"]
        ready = [r for r in riders if r.stamina >= self.rest_at]
        resting = {r.id for r in riders if r.stamina < self.rest_at}
        horses = list(gs.horses)

        cands = []
        for d in gs.dispatches:
            best = None
            for r in ready:
                for h in horses:
                    n = gs.travel_nights(d, r, h)
                    if n > d.deadline:
                        continue                      # 时限内到不了，直接不派
                    if d.deadline - n < self.min_margin:
                        continue
                    # 预期收益 = 价值；风险按「余量」打折
                    slack = d.deadline - n
                    risk = 1.0 - 0.10 * (1 if slack == 0 else 0)
                    score = self.value(d) * risk
                    if best is None or score > best[0]:
                        best = (score, r, h)
            if best:
                cands.append((best[0], d, best[1], best[2]))

        cands.sort(key=lambda x: -x[0])
        ur, uh = set(), set()
        plan = []
        for sc, d, r, h in cands:
            if r.id in ur or h.id in uh:
                continue
            ur.add(r.id)
            uh.add(h.id)
            plan.append((d, r, h))
        return plan, resting, ur

    def shop(self, gs, used_rider_ids):
        # 油不够就补
        if gs.oil < self.oil_at and gs.gold >= B.PRICES["oil"]:
            gs.buy_oil()
        # 马状态低就喂（留点钱）
        if gs.gold >= B.PRICES["feed"] + 60:
            for h in sorted(gs.horses, key=lambda x: x.condition):
                if h.condition < self.feed_at:
                    gs.feed(h.id)
                    break
        # 骑手不够就雇
        avail = len([r for r in gs.riders if r.state != "injured"])
        if avail < self.hire_below and gs.gold >= B.PRICES["hire_rider"] + 80:
            gs.hire_rider()
            return
        # 骑手比马多就买马
        idle = len([r for r in gs.riders if r.state == "idle"])
        if len(gs.horses) < idle and gs.gold >= B.PRICES["buy_horse"] + 100:
            gs.buy_horse()
            return


def play(seed, strat: Strategy):
    gs = GameState(seed=seed)
    guard = 0
    while not gs.over and guard < 40:
        guard += 1
        plan, resting, used = strat.plan(gs)
        gs.advance(plan, resting)
        if not gs.over:
            strat.shop(gs, used)
    r = gs.result or {}
    win = bool(r.get("survived")) and gs.faith >= B.SURVIVE_FAITH
    return {
        "faith": gs.faith, "gold": gs.gold, "rating": r.get("rating", "—"),
        "win": win, "rate": r.get("rate", 0),
        "delivered": r.get("delivered", 0), "total": r.get("total", 0),
        "riders": len(gs.riders), "horses": len(gs.horses),
    }


def evaluate(strat: Strategy, n=200, label=""):
    res = [play(s, strat) for s in range(n)]
    s_rate = sum(1 for r in res if r["rating"] == "S") / n
    win = sum(1 for r in res if r["win"]) / n
    faiths = [r["faith"] for r in res]
    ratings = Counter(r["rating"] for r in res)
    print("  %-42s S率 %5.1f%%  通关 %5.1f%%  信中位 %3.0f  %s" % (
        label, s_rate * 100, win * 100, statistics.median(faiths),
        " ".join("%s=%d" % (k, v) for k, v in sorted(ratings.items()))))
    return s_rate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--count", type=int, default=200)
    args = ap.parse_args()

    print("=" * 90)
    print("策略搜索  n=%d" % args.count)
    print("=" * 90)

    trials = []
    # 1) 基准：按信价值排，45 歇
    trials.append(("基准 rest45 faith-weight", Strategy()))
    # 2) 更早休息（保状态）
    trials.append(("rest55 保守", Strategy(rest_at=55)))
    trials.append(("rest65 极保守", Strategy(rest_at=65)))
    # 3) 更晚休息（榨干）
    trials.append(("rest35 激进", Strategy(rest_at=35, hire_below=3)))
    # 4) 多雇人
    trials.append(("hire>=3 rest45", Strategy(hire_below=4)))
    trials.append(("hire>=4 rest45", Strategy(hire_below=5)))
    # 5) 勤喂马
    trials.append(("feed70 rest45", Strategy(feed_at=70)))
    trials.append(("feed70 hire4 rest45", Strategy(feed_at=70, hire_below=5)))
    # 6) 只要余量
    trials.append(("margin1 rest45", Strategy(min_margin=1)))
    # 7) 金优先
    trials.append(("gold-weight rest45", Strategy(prefer_faith=False)))
    # 8) 组合拳
    trials.append(("combo A", Strategy(rest_at=50, feed_at=70, hire_below=4)))
    trials.append(("combo B", Strategy(rest_at=45, feed_at=65, hire_below=5, min_margin=0)))
    trials.append(("combo C", Strategy(rest_at=50, feed_at=70, hire_below=5)))

    best = None
    for label, st in trials:
        sr = evaluate(st, args.count, label)
        if best is None or sr > best[0]:
            best = (sr, label, st)

    print()
    print("最佳: %s  S率 %.1f%%" % (best[1], best[0] * 100))
    st = best[2]
    print("  参数: rest_at=%d feed_at=%d hire_below=%d min_margin=%d prefer_faith=%s" % (
        st.rest_at, st.feed_at, st.hire_below, st.min_margin, st.prefer_faith))


if __name__ == "__main__":
    main()
