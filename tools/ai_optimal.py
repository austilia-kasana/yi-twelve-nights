# -*- coding: utf-8 -*-
"""策略搜索：扫一组参数，看哪种打法最容易拿到 S。

和 sim_balance.py 用**同一套策略实现**（tools/ai.py），
所以两个工具报出来的难度数据是可比的。

用法:
    python tools/ai_optimal.py              # 每组跑 100 局
    python tools/ai_optimal.py -n 300
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from relay.core import balance as B          # noqa: E402
from ai import Strategy, run_many            # noqa: E402


# 待扫的策略变体：(名字, Strategy 关键字参数)
VARIANTS = [
    ("基准",                 dict()),
    ("激进（歇得少）",         dict(rest_at=35)),
    ("保守（歇得多）",         dict(rest_at=55)),
    ("极保守",               dict(rest_at=65)),
    ("人多（雇到 3）",         dict(hire_below=3)),
    ("人多（雇到 5）",         dict(hire_below=5)),
    ("爱喂马",               dict(feed_at=70)),
    ("只接有余量的",           dict(min_margin=1)),
    ("优先金而非信",          dict(prefer_faith=False)),
    ("勤添油",               dict(oil_at=60)),
    ("组合：保守+爱喂马",       dict(rest_at=55, feed_at=70)),
    ("组合：人多+保守",         dict(hire_below=5, rest_at=55)),
]


def evaluate(strat: Strategy, n: int, seed_offset: int = 0):
    games = run_many(n, strat, seed_offset=seed_offset)
    faiths = [g.faith for g in games]
    ratings = [(g.result or {}).get("rating", "—") for g in games]
    s_rate = ratings.count("S") / n
    # 「达标」=信 >= SURVIVE_FAITH，不是「活到第 12 夜」。
    # survived 只表示没被提前撤驿，而撤驿要求信恰好掉到 0——几乎碰不到。
    win_rate = sum(1 for g in games
                   if (g.result or {}).get("survived")
                   and g.faith >= B.SURVIVE_FAITH) / n
    dist = {}
    for r in ratings:
        dist[r] = dist.get(r, 0) + 1
    return {
        "s_rate": s_rate,
        "win_rate": win_rate,
        "median_faith": statistics.median(faiths),
        "dist": dist,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--num", type=int, default=100)
    ap.add_argument("--seed-offset", type=int, default=0)
    args = ap.parse_args(argv)

    print("=" * 78)
    print("策略搜索   n=%d（每组 %d 局）" % (len(VARIANTS), args.num))
    print("=" * 78)
    print()

    rows = []
    for name, kw in VARIANTS:
        strat = Strategy(**kw)
        r = evaluate(strat, args.num, args.seed_offset)
        rows.append((name, r, kw))

    rows.sort(key=lambda x: -x[1]["s_rate"])

    print("%-22s %8s %8s %8s   %s" % ("策略", "S率", "通关", "信中位", "评价"))
    print("-" * 78)
    for name, r, kw in rows:
        d = r["dist"]
        line = " ".join("%s=%d" % (k, d[k]) for k in ("S", "A", "B", "C", "D", "E")
                        if k in d)
        print("%-22s %7.1f%% %7.1f%% %7.0f   %s" % (
            name, r["s_rate"] * 100, r["win_rate"] * 100,
            r["median_faith"], line))

    best_name, best_r, best_kw = rows[0]
    print()
    print("最佳: %s   S率 %.1f%%" % (best_name, best_r["s_rate"] * 100))
    if best_kw:
        print("  参数: " + ", ".join("%s=%s" % (k, v) for k, v in best_kw.items()))
    else:
        print("  参数: 全默认")
    print()
    print("提示: 这些是「只看预报」的 AI 成绩，和真实玩家拿到的信息一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
