# -*- coding: utf-8 -*-
"""B3 验证：存档持久化 + 确定性。

核心命题：**同种子下，读档续跑和不中断运行，结果必须完全一致。**

这是龙娘列为必测的一条。如果这条不成立，存档就只是「看起来能用」——
玩家的实际对局和存档记录的会悄悄分叉。

用法: python tools/verify_determinism.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from relay.core.sim import GameState          # noqa: E402
from ai import Strategy                       # noqa: E402


def fingerprint(gs: GameState) -> dict:
    """一局的可比对指纹。"""
    return {
        "night": gs.night,
        "faith": gs.faith,
        "gold": round(gs.gold, 6),
        "oil": round(gs.oil, 6),
        "over": gs.over,
        "weather": gs.weather,
        "forecast": gs.forecast,
        # 用「序号」而不是绝对 id：id 是模块级自增，两个 GameState 实例
        # 的 id 区间不同，拿 id 比会永远不等。
        "riders": sorted((r.name, round(r.stamina, 6), r.state, r.injured_nights)
                         for r in gs.riders),
        "horses": sorted((h.name, round(h.condition, 6)) for h in gs.horses),
        "trips": sorted((t.route, t.dispatch.kind, round(t.progress, 6),
                         t.depart_night, t.elapsed_nights, t.due_night)
                        for t in gs.trips),
        "dispatches": sorted((d.route, d.kind, d.deadline, d.reward, d.penalty)
                             for d in gs.dispatches),
        "history": [(
            nr.night, nr.weather, nr.forecast, nr.gold_delta, nr.faith_delta,
            sorted((t.rider_name, t.route, t.delivered, t.nights_taken)
                   for t in nr.trips),
        ) for nr in gs.history],
    }


def run_straight(seed: int, split_at: int | None = None,
                 total_nights: int = 12) -> GameState:
    """跑一局。split_at 不为 None 时，在第 split_at 夜之后走一遍存档往返。"""
    gs = GameState(seed=seed)
    strat = Strategy()

    guard = 0
    while not gs.over and guard < 60:
        guard += 1
        plan, used = strat.plan(gs)
        gs.advance(plan)
        if gs.over:
            break
        strat.shop(gs, used)

        if split_at is not None and gs.night == split_at + 1 and not gs.over:
            # 落盘再读回来，模拟关窗口重开
            raw = json.dumps(gs.to_dict(), ensure_ascii=False)
            gs = GameState.from_dict(json.loads(raw))
            strat = Strategy()          # 策略无状态，重建等价
            split_at = None             # 只往返一次
    return gs


def main() -> int:
    ok = True
    print("=" * 66)
    print("B3 确定性验证：读档续跑 == 不中断运行")
    print("=" * 66)
    print()

    # 1) 纯确定性：同种子跑两次
    print("① 同种子跑两次结果一致")
    diff = 0
    for seed in range(40):
        a = fingerprint(run_straight(seed))
        b = fingerprint(run_straight(seed))
        if a != b:
            diff += 1
    print("   40 组对比，不一致 %d 组  %s" % (diff, "✅" if diff == 0 else "❌"))
    ok &= diff == 0

    # 2) 中途存档往返
    print()
    print("② 第 N 夜存档往返后继续，和一口气跑完一致")
    bad = []
    for seed in range(40):
        straight = fingerprint(run_straight(seed))
        for split in (1, 3, 5, 7, 9):
            resumed = fingerprint(run_straight(seed, split_at=split))
            if straight != resumed:
                bad.append((seed, split))
                break
    print("   40 个种子 × 5 个切点 = 200 组")
    print("   不一致 %d 组  %s" % (len(bad), "✅" if not bad else "❌"))
    if bad:
        for s, sp in bad[:5]:
            print("     种子 %d 在第 %d 夜切分后分叉" % (s, sp))
    ok &= not bad

    # 3) 在途任务必须能往返
    print()
    print("③ 在途任务在存档往返后仍在途、进度不丢")
    gs = GameState(seed=3)
    gs.weather = "clear"
    gs.forecast = "clear"
    gs.night_progress = lambda *a, **k: 1.0      # 保证多夜
    riders, horses = gs.available_riders(), gs.available_horses()
    d = gs.dispatches[0]
    d.route = "mine"
    d.deadline = 3
    gs.advance([(d, riders[0], horses[0])])
    before = [(t.id, round(t.progress, 6), t.due_night, t.depart_night)
              for t in gs.trips]
    back = GameState.from_dict(json.loads(json.dumps(gs.to_dict(), ensure_ascii=False)))
    after = [(t.id, round(t.progress, 6), t.due_night, t.depart_night)
             for t in back.trips]
    print("   存前 %s" % (before,))
    print("   读后 %s" % (after,))
    same = before == after
    print("   %s" % ("✅ 一致" if same else "❌ 不一致"))
    ok &= same

    # 4) 读档后在途任务还能继续推进
    print()
    print("④ 读档后在途任务继续推进并正常抵达")
    back.night_progress = lambda *a, **k: 5.0    # 下一夜一定到
    back.advance([])
    arrived = len(back.history[-1].trips) if back.history else 0
    print("   推进一夜后结算 %d 封  在途剩 %d 支  %s" % (
        arrived, len(back.trips), "✅" if arrived == 1 and not back.trips else "❌"))
    ok &= (arrived == 1 and not back.trips)

    # 5) RNG 状态必须精确往返
    print()
    print("⑤ RNG 状态精确往返")
    gs = GameState(seed=99)
    gs.advance([])
    # 先存档，再抽随机数——否则比的是两个不同位置的状态
    snapshot = json.dumps(gs.to_dict(), ensure_ascii=False)
    nxt_a = [gs.rng.random() for _ in range(5)]
    gs2 = GameState.from_dict(json.loads(snapshot))
    nxt_b = [gs2.rng.random() for _ in range(5)]
    same = all(abs(x - y) < 1e-12 for x, y in zip(nxt_a, nxt_b))
    print("   读档后前 5 个随机数: %s" % ("✅ 完全一致" if same else "❌ 不一致"))
    ok &= same

    print()
    print("=" * 66)
    print("结论: " + ("✅ 全部通过" if ok else "❌ 有失败项"))
    print("=" * 66)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
