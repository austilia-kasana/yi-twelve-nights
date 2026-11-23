# -*- coding: utf-8 -*-
"""平衡模拟：跑 N 局，看通关率和评价分布。

策略统一走 tools/ai.py（和 ai_optimal.py 用同一套），
且只用**预报**信息——和真实玩家一致。

用法:
    python tools/sim_balance.py            # 默认 200 局
    python tools/sim_balance.py -n 500
    python tools/sim_balance.py -n 200 -v  # 逐局打印
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from relay.core import balance as B          # noqa: E402
from ai import Strategy, run_many            # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--num", type=int, default=200)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--seed-offset", type=int, default=0)
    args = ap.parse_args(argv)

    games = run_many(args.num, Strategy(), seed_offset=args.seed_offset)

    # 「达标」= 守住了（信 >= SURVIVE_FAITH），不是「活到第 12 夜」。
    # 这两个差别很大：survived 只表示没被提前撤驿，而提前撤驿要求信掉到
    # 恰好 0——起点 50、每笔罚 3~10，几乎碰不到。所以真正的胜负线是 60。
    def is_win(g):
        return bool((g.result or {}).get("survived")) and g.faith >= B.SURVIVE_FAITH

    won, lost = [], []
    for g in games:
        (won if is_win(g) else lost).append(g)

    def rating_dist(gs_list):
        c = {}
        for g in gs_list:
            r = (g.result or {}).get("rating", "—")
            c[r] = c.get(r, 0) + 1
        return c

    faiths = [g.faith for g in games]
    rates = [(g.result or {}).get("rate", 0) for g in games]

    print("=" * 62)
    print("平衡模拟   %d 局   种子 %d..%d" % (
        args.num, args.seed_offset, args.seed_offset + args.num - 1))
    print("=" * 62)
    print()
    zero = sum(1 for g in games if g.faith <= 0)
    print("  达标（信 >= %d）    %3d   %.0f%%" % (
        B.SURVIVE_FAITH, len(won), len(won) / args.num * 100))
    print("  没达标               %3d   %.0f%%" % (
        len(lost), len(lost) / args.num * 100))
    print("    其中 信归零被撤     %3d   %.0f%%" % (zero, zero / args.num * 100))
    print()
    print("  终局信   最低 %3.0f  中位 %3.0f  最高 %3.0f  平均 %.1f" % (
        min(faiths), statistics.median(faiths), max(faiths),
        statistics.mean(faiths)))
    print("  送达率   最低 %3.0f%% 中位 %3.0f%% 最高 %3.0f%% 平均 %.1f%%" % (
        min(rates) * 100, statistics.median(rates) * 100, max(rates) * 100,
        statistics.mean(rates) * 100))
    print()

    dist = rating_dist(games)
    order = ["S", "A", "B", "C", "D", "E", "—"]
    print("  评价分布: " + "  ".join(
        "%s=%d(%.0f%%)" % (k, dist[k], dist[k] / args.num * 100)
        for k in order if k in dist))
    print()

    endings = {}
    for g in games:
        why = (g.result or {}).get("why", "?")
        endings[why] = endings.get(why, 0) + 1
    print("  结局:")
    for why, n in sorted(endings.items(), key=lambda x: -x[1]):
        print("    %-34s %3d" % (why, n))
    print()

    # 一句话结论
    s_rate = dist.get("S", 0) / args.num
    win_rate = len(won) / args.num
    if win_rate < 0.45:
        verdict = "偏难"
    elif win_rate > 0.85:
        verdict = "偏简单"
    else:
        verdict = "合适"
    print("  判定: 通关率 %.0f%%，S %.0f%% → %s" % (
        win_rate * 100, s_rate * 100, verdict))
    print("=" * 62)

    if args.verbose:
        print()
        for i, g in enumerate(games[:20]):
            r = g.result or {}
            print("  #%-3d 信 %-3d 金 %-4d 送达 %-3s %s" % (
                i, g.faith, int(g.gold),
                "%d%%" % (r.get("rate", 0) * 100), r.get("rating", "—")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
