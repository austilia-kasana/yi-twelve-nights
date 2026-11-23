# -*- coding: utf-8 -*-
"""批量模拟：检验平衡性。

用一个「还算聪明但不完美」的 AI 策略跑很多局，看胜率落在哪。

策略要点（刻意做得像人类玩家，不是最优解）：
  · 先派最划算的信（赏 / 难度）
  · 预报差的时候保守（不给快到期的信配慢骑手）
  · 骑手体力低了就让他歇
  · 有钱先补马料和油，再考虑雇人

用法：
  python tools/sim_balance.py            # 默认 500 局
  python tools/sim_balance.py -n 2000
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


def choose_plan(gs: GameState):
    """返回 (assignments, resting_ids)。"""
    riders = [r for r in gs.riders if r.state == "idle"]
    horses = list(gs.horses)
    if not riders or not horses:
        return [], set()

    # 体力太低的先歇
    resting = set()
    ready = []
    for r in riders:
        if r.stamina < 30:
            resting.add(r.id)
        else:
            ready.append(r)
    if not ready:
        return [], resting

    # 给每封信算「最划算的组合」
    scored = []
    for d in gs.dispatches:
        best = None
        for r in ready:
            for h in horses:
                # 关键：用 gs.forecast 而不是默认的 gs.weather。
                # 不传天气时 travel_nights 会用真实天气，等于让 AI 偷看答案，
                # 测出来的难度比玩家实际面对的偏低一大截。
                nights = gs.travel_nights(d, r, h, gs.forecast)
                on_time = nights <= d.deadline
                # 预期收益：准时给赏，否则吃罚
                ev = d.reward if on_time else -d.penalty * 3
                # 偏好快的组合（留余量给坏天气）
                ev -= nights * 2
                if best is None or ev > best[0]:
                    best = (ev, r, h, nights)
        if best:
            scored.append((best[0], d, best[1], best[2]))

    # 按收益排序，贪心分配
    scored.sort(key=lambda x: -x[0])
    used_r, used_h = set(), set()
    assignments = []
    for ev, d, r, h in scored:
        if ev <= 0:
            continue
        if r.id in used_r or h.id in used_h:
            continue
        used_r.add(r.id)
        used_h.add(h.id)
        assignments.append((d, r, h))

    return assignments, resting


def improve(gs: GameState):
    """每夜结束后的采购。刻意保守：先保命再扩张。"""
    # 油低于 40 就补
    if gs.oil < 40 and gs.gold >= B.PRICES["oil"]:
        gs.buy_oil()

    # 有低状态马就喂
    for h in sorted(gs.horses, key=lambda x: x.condition):
        if h.condition < 45 and gs.gold >= B.PRICES["feed"] + 60:
            gs.feed(h.id)
            break

    # 骑手少于马就雇人（人多才排得开）
    avail = len([r for r in gs.riders if r.state != "injured"])
    if len(gs.horses) > avail and gs.gold >= B.PRICES["hire_rider"] + 100:
        gs.hire_rider()

    # 马少于骑手就买马
    idle_riders = len([r for r in gs.riders if r.state == "idle"])
    if len(gs.horses) < idle_riders and gs.gold >= B.PRICES["buy_horse"] + 120:
        gs.buy_horse()

    # 后期有余钱修最短的路
    if gs.night >= 8 and gs.gold > 400:
        for rk in ("north", "ford"):
            if rk not in gs.route_repaired and gs.gold >= B.ROUTES[rk]["repair_cost"] + 60:
                gs.repair_route(rk)
                break


def play_one(seed: int) -> dict:
    gs = GameState(seed=seed)
    guard = 0
    while not gs.over and guard < 60:
        guard += 1
        plan, resting = choose_plan(gs)
        gs.advance(plan, resting)
        if not gs.over:
            improve(gs)
    return {
        "seed": seed,
        "faith": gs.faith,
        "gold": gs.gold,
        "night": gs.night,
        "survived": gs.result["survived"] if gs.result else False,
        "won": (gs.result["survived"] and gs.faith >= B.SURVIVE_FAITH) if gs.result else False,
        "rating": gs.result["rating"] if gs.result else "—",
        "rate": gs.result["rate"] if gs.result else 0.0,
        "why": gs.result["why"] if gs.result else "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--count", type=int, default=500)
    args = ap.parse_args()

    results = [play_one(s) for s in range(args.count)]

    won = sum(1 for r in results if r["won"])
    bank = sum(1 for r in results if not r["survived"])
    faiths = [r["faith"] for r in results]
    rates = [r["rate"] for r in results]
    ratings = Counter(r["rating"] for r in results)
    whys = Counter(r["why"] for r in results)

    print("=" * 62)
    print("《驿 · 十二夜》平衡模拟  n=%d" % args.count)
    print("=" * 62)
    print("  通关（信>=%d）      %d   %.1f%%" % (B.SURVIVE_FAITH, won, 100.0 * won / args.count))
    print("  撑过12夜但没达标     %d" % (sum(1 for r in results if r["survived"] and not r["won"])))
    print("  信归零被撤          %d   %.1f%%" % (bank, 100.0 * bank / args.count))
    print()
    print("  终局信   最低 %3.0f  中位 %3.0f  最高 %3.0f  平均 %5.1f" % (
        min(faiths), statistics.median(faiths), max(faiths), statistics.mean(faiths)))
    print("  送达率   最低 %3.0f%%  中位 %3.0f%%  最高 %3.0f%%  平均 %5.1f%%" % (
        min(rates) * 100, statistics.median(rates) * 100, max(rates) * 100,
        statistics.mean(rates) * 100))
    print()
    print("  评价分布: " + "  ".join("%s=%d" % (k, v) for k, v in sorted(ratings.items())))
    print()
    print("  结局:")
    for w, c in whys.most_common(6):
        print("    %-30s %d" % (w, c))
    print()
    v = statistics.mean(faiths)
    if won / args.count > 0.75:
        verdict = "偏简单"
    elif won / args.count < 0.30:
        verdict = "偏难"
    else:
        verdict = "合适"
    print("  判定: 平均信 %.1f，通关率 %.0f%% → %s" % (v, 100.0 * won / args.count, verdict))
    print("=" * 62)


if __name__ == "__main__":
    main()
