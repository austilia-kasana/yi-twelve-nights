# -*- coding: utf-8 -*-
"""Phase C 指标工具。

## 为什么单独做

之前做过几次临时统计脚本，每次都要重写，而且只看均值。
但调平衡需要的是**分布**——比如「马的状态中位 60」和
「一半马在 80、一半马在 20」是完全不同的情况。

这个工具的输出固定覆盖龙娘列的那几项：

    骑手：体力分布、受伤率、出勤率
    马：  状态分布、低状态比例、喂料次数
    在途：任务数、行程夜数分布
    派遣：完成 / 超时 / 未完成 / 中断 的分类
    路线：使用比例、各路线的送达率
    事件：发生率、各事件的结果

## 用法

    python tools/metrics.py                    # 300 局，标准策略
    python tools/metrics.py -n 500             # 500 局
    python tools/metrics.py --strategy safe    # 指定策略变体
    python tools/metrics.py --list-strategies
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from relay.core import balance as B            # noqa: E402
from relay.core.sim import GameState           # noqa: E402
from ai import Strategy, play                  # noqa: E402


# ── 策略变体 ──
# 这些不是「最优解」，是**用来做对照**的几种玩家画像。
STRATEGIES = {
    # 基准：只看预报、留一点余量
    "base": Strategy(),
    # 纯保守：只接有余量的信，完全不冒险
    "safe": Strategy(min_margin=1, rest_at=55),
    # 激进：不挑余量，能派就派
    "bold": Strategy(min_margin=0, rest_at=35),
    # 省人：不雇人，靠两个初始骑手硬撑
    "lean": Strategy(hire_below=2, rest_at=45),
    # 扩编：拼命雇人买马
    "wide": Strategy(hire_below=5, horse_cap=5),
    # 只追信：不管金
    "faith": Strategy(prefer_faith=True, min_margin=0, rest_at=40),
}


def pct(x):
    return "%.1f%%" % (x * 100)


def dist_line(values, buckets, unit=""):
    """把一组值按区间统计成一行。"""
    c = Counter()
    for v in values:
        for lo, hi in buckets:
            if lo <= v < hi:
                c[(lo, hi)] += 1
                break
    total = len(values) or 1
    parts = []
    for lo, hi in buckets:
        n = c.get((lo, hi), 0)
        if n:
            parts.append("%d-%d%s:%d%%" % (lo, hi, unit, round(n / total * 100)))
    return "  ".join(parts) or "（无数据）"


def histogram(lo=0, hi=100, step=20):
    """生成区间桶，给 dist_line 用。"""
    return [(i, i + step) for i in range(lo, hi, step)]


class Collector:
    """逐局收集原始数据，最后统一算。"""

    def __init__(self):
        self.games = 0
        self.wins = 0
        self.ratings = Counter()
        self.final_faith = []
        self.final_gold = []
        self.final_oil = []
        # 逐局末态
        self.rider_stamina = []      # 每局所有骑手的终局体力
        self.horse_condition = []
        self.horse_low = 0
        self.horse_total = 0
        self.injured_count = 0
        self.rider_total = 0
        # 累计
        self.trips = []
        self.trip_events = Counter()
        self.route_use = Counter()
        self.route_delivered = Counter()
        self.route_trips = Counter()
        self.trip_nights = []
        self.trip_expected = []
        # 每局
        self.dispatch_per_game = []
        self.trips_per_game = []
        self.feeds_per_game = []

    def feed(self, gs: GameState):
        self.games += 1
        r = gs.result or {}
        if r.get("survived") and gs.faith >= B.SURVIVE_FAITH:
            self.wins += 1
        self.ratings[r.get("rating", "—")] += 1
        self.final_faith.append(gs.faith)
        self.final_gold.append(gs.gold)
        self.final_oil.append(gs.oil)

        for rd in gs.riders:
            self.rider_stamina.append(rd.stamina)
            self.rider_total += 1
            if rd.state == "injured":
                self.injured_count += 1
        for h in gs.horses:
            self.horse_condition.append(h.condition)
            self.horse_total += 1
            if h.condition < B.HORSE_LOW:
                self.horse_low += 1

        all_trips = [t for nr in gs.history for t in nr.trips]
        self.trips.extend(all_trips)
        self.trips_per_game.append(len(all_trips))
        self.dispatch_per_game.append(len(all_trips))

        for t in all_trips:
            self.route_use[t.route] += 1
            self.route_trips[t.route] += 1
            if t.delivered:
                self.route_delivered[t.route] += 1
            self.trip_nights.append(t.nights_taken)
            evs = [e.get("event") for e in getattr(t, "events", [])]
            if t.event == "robbery":
                evs.append("robbery")
            for e in set(evs):
                self.trip_events[e] += 1

        # 喂料次数：从 log 里抓
        self.feeds_per_game.append(
            sum(1 for e in gs.log if "喂了料" in e.get("text", "")))

    def report(self, label: str):
        n = self.games or 1
        print("=" * 74)
        print("指标  %-10s  %d 局" % (label, self.games))
        print("=" * 74)
        print()

        # ── 结果 ──
        print("【结果】")
        print("  达标率      %s" % pct(self.wins / n))
        dist = " ".join("%s=%d%%" % (k, round(self.ratings[k] / n * 100))
                        for k in ("S", "A", "B", "C", "D", "E") if self.ratings[k])
        print("  评价分布    %s" % dist)
        print("  终局信      中位 %d   均值 %.1f   范围 %d~%d" % (
            statistics.median(self.final_faith),
            statistics.mean(self.final_faith),
            min(self.final_faith), max(self.final_faith)))
        print("  终局金      中位 %d" % statistics.median(self.final_gold))
        print()

        # ── 骑手 ──
        print("【骑手】")
        print("  终局体力分布  %s" % dist_line(self.rider_stamina, histogram()))
        print("  中位体力      %.0f   低于门槛(%.0f)的比例 %s" % (
            statistics.median(self.rider_stamina), B.STAMINA_LOW,
            pct(sum(1 for v in self.rider_stamina if v < B.STAMINA_LOW)
                / (len(self.rider_stamina) or 1))))
        print("  终局受伤率    %s (%d/%d)" % (
            pct(self.injured_count / (self.rider_total or 1)),
            self.injured_count, self.rider_total))
        print()

        # ── 马 ──
        print("【马】")
        print("  终局状态分布  %s" % dist_line(self.horse_condition, histogram()))
        print("  中位状态      %.0f   低于门槛(%.0f)的比例 %s" % (
            statistics.median(self.horse_condition), B.HORSE_LOW,
            pct(self.horse_low / (self.horse_total or 1))))
        print("  每局喂料次数  中位 %.0f   均值 %.1f   最多 %d" % (
            statistics.median(self.feeds_per_game),
            statistics.mean(self.feeds_per_game), max(self.feeds_per_game)))
        print()

        # ── 派遣 ──
        print("【派遣】")
        trips = self.trips
        delivered = sum(1 for t in trips if t.delivered)
        late = sum(1 for t in trips if not t.delivered and t.event == "calm"
                   and not t.lost)
        lost = sum(1 for t in trips if t.lost)
        aborted = sum(1 for t in trips if t.event == "aborted")
        print("  每局派遣      %d 封（共 %d）" % (
            round(len(trips) / n), len(trips)))
        print("  送达          %d  %s" % (delivered, pct(delivered / (len(trips) or 1))))
        print("  超时          %d  %s" % (late, pct(late / (len(trips) or 1))))
        print("  遇劫          %d  %s" % (lost, pct(lost / (len(trips) or 1))))
        print("  中断          %d  %s" % (aborted, pct(aborted / (len(trips) or 1))))
        print()

        # ── 行程 ──
        print("【行程】")
        c = Counter(self.trip_nights)
        print("  实际夜数分布  %s" % "  ".join(
            "%d夜:%d%%" % (k, round(c[k] / len(self.trip_nights) * 100))
            for k in sorted(c)))
        print("  平均夜数      %.2f" % statistics.mean(self.trip_nights))
        print()

        # ── 路线 ──
        print("【路线】")
        for rk in ("north", "ford", "mine"):
            used = self.route_use.get(rk, 0)
            dl = self.route_delivered.get(rk, 0)
            if used:
                print("  %-6s 使用 %s   送达率 %s" % (
                    B.ROUTES[rk]["name"],
                    pct(used / len(trips)), pct(dl / used)))
        print()

        # ── 事件 ──
        print("【事件】")
        ev_total = len(trips) or 1
        any_ev = sum(self.trip_events.values())
        print("  至少一次事件  %s" % pct(any_ev / ev_total))
        for k, v in self.trip_events.most_common():
            name = B.EVENTS[k]["name"] if k in B.EVENTS else k
            print("    %-8s %s" % (name, pct(v / ev_total)))
        print()
        print("=" * 74)


def run(n: int, strat_name: str, seed_offset: int = 0) -> Collector:
    strat = STRATEGIES[strat_name]
    col = Collector()
    for i in range(n):
        gs = GameState(seed=seed_offset + i)
        play(gs, strat)
        col.feed(gs)
    return col


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase C 指标")
    ap.add_argument("-n", "--num", type=int, default=300)
    ap.add_argument("--strategy", default="base", choices=list(STRATEGIES))
    ap.add_argument("--seed-offset", type=int, default=0)
    ap.add_argument("--compare", action="store_true",
                    help="把所有策略跑一遍，只对比结果指标")
    ap.add_argument("--list-strategies", action="store_true")
    args = ap.parse_args(argv)

    if args.list_strategies:
        print("策略变体：")
        for k in STRATEGIES:
            print("  %-8s %s" % (k, STRATEGIES[k]))
        return 0

    if args.compare:
        print("=" * 74)
        print("策略对比  n=%d/策略" % args.num)
        print("=" * 74)
        print()
        print("%-8s %8s %8s %8s %8s %8s" % (
            "策略", "达标", "S率", "信 中位", "每局派遣", "送达率"))
        print("-" * 74)
        rows = []
        for name in STRATEGIES:
            col = run(args.num, name, args.seed_offset)
            trips = len(col.trips) or 1
            delivered = sum(1 for t in col.trips if t.delivered)
            rows.append((
                name,
                col.wins / col.games,
                col.ratings["S"] / col.games,
                statistics.median(col.final_faith),
                len(col.trips) / col.games,
                delivered / trips,
            ))
        for r in sorted(rows, key=lambda x: -x[1]):
            print("%-8s %7.1f%% %7.1f%% %8.0f %8.1f %7.1f%%" % (
                r[0], r[1] * 100, r[2] * 100, r[3], r[4], r[5] * 100))
        print()
        print("（这是「哪个打法更有效」的对照，不是平衡判定依据）")
        return 0

    col = run(args.num, args.strategy, args.seed_offset)
    col.report(args.strategy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
