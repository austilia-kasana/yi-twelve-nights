# -*- coding: utf-8 -*-
"""对局日志。

一局打完之后，把每一夜发生了什么完整写下来：
  · 纯文本（人看）
  · JSON（脚本分析用）

写在 exe 同级的 logs/ 目录里。打包成单文件后，__file__ 在临时解包目录，
所以必须用 sys.executable 定位——不能用 __file__。
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

from . import balance as B


def logs_dir() -> str:
    """日志目录。

    打包后 sys.frozen 为真，sys.executable 指向 exe，
    就写在 exe 旁边的 logs/ 里（玩家找得到）。
    开发时写在项目根的 logs/ 里。
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
    d = os.path.join(base, "logs")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return os.path.join(base)
    return d


def _fmt_weather(key: str) -> str:
    return B.WEATHER.get(key, {}).get("name", key)


def _fmt_route(key: str) -> str:
    return B.ROUTES.get(key, {}).get("name", key)


def _fmt_kind(key: str) -> str:
    return B.DISPATCH_KINDS.get(key, {}).get("name", key)


def is_win(gs) -> bool:
    """真正的「赢」= 熬过十二夜 且 信 >= 达标线。

    只看 result["survived"] 会把「熬过来了但信已经没了」也算成守住，
    日志里就会出现「结果：守住了 / 评价：D」这种自相矛盾。
    """
    r = gs.result or {}
    return bool(r.get("survived")) and gs.faith >= B.SURVIVE_FAITH


def build_text(gs) -> str:
    """把一整局渲染成可读文本。"""
    r = gs.result or {}
    L = []
    a = L.append

    a("=" * 62)
    a("《驿 · 十二夜》 对局记录")
    a("=" * 62)
    a("时间      %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    a("种子      %s" % (gs.seed if gs.seed is not None else "随机"))
    a("结果      %s" % ("守住了" if is_win(gs) else "没守住"))
    a("评价      %s" % r.get("rating", "—"))
    a("最终信    %d / %d（达标线 %d）" % (
        int(gs.faith), B.MAX_FAITH, B.SURVIVE_FAITH))
    a("最终金    %d" % int(gs.gold))
    a("送达率    %.0f%%  (%d / %d)" % (
        r.get("rate", 0) * 100, r.get("delivered", 0), r.get("total", 0)))
    a("结局      %s" % r.get("why", ""))
    a("")

    # 按夜展开
    if gs.history:
        a("-" * 62)
        a("逐夜明细")
        a("-" * 62)
        for nr in gs.history:
            fc = _fmt_weather(nr.forecast)
            ac = _fmt_weather(nr.weather)
            hit = "准" if nr.forecast_was_right else "错"
            a("")
            a("第 %d 夜   预报 %s / 实际 %s（%s）" % (
                nr.night, fc, ac, hit))
            if nr.dropped:
                names = "、".join(
                    "%s%s" % (_fmt_route(d.route), _fmt_kind(d.kind))
                    for d in nr.dropped)
                a("  拒收    %s" % names)
            if not nr.trips:
                a("  派出    无（全员休息）")
            for t in nr.trips:
                mark = "送到" if t.delivered else ("丢失" if t.lost else "未达")
                a("  %-4s  %-4s + %-4s  %s·%s  需%d夜/限%d夜  %s" % (
                    mark, t.rider_name, t.horse_name,
                    _fmt_route(t.route), _fmt_kind(t.dispatch.kind),
                    t.nights_taken, t.dispatch.deadline, t.note))
                if t.delivered:
                    a("        赏 %+d 金" % t.dispatch.reward)
                else:
                    a("        罚 -%d 信" % t.dispatch.penalty)
            a("  收支    金 %+d   信 %+d" % (nr.gold_delta, nr.faith_delta))

    # 完整流水
    if gs.log:
        a("")
        a("-" * 62)
        a("完整流水")
        a("-" * 62)
        for e in gs.log:
            a("  D%-3d %s" % (e.get("night", 0), e.get("text", "")))

    # 终局状态
    a("")
    a("-" * 62)
    a("终局状态")
    a("-" * 62)
    for rider in gs.riders:
        a("  骑手  %-6s 脚力 %.2f  体力 %3.0f  %s" % (
            rider.name, rider.speed, rider.stamina, rider.state))
    for h in gs.horses:
        a("  马    %-6s 脚力 %.2f  状态 %3.0f" % (h.name, h.speed, h.condition))
    a("  油    %d" % int(gs.oil))
    a("")
    a("=" * 62)
    return "\n".join(L)


def save(gs, also_json=True) -> dict:
    """写一份对局日志，返回 {text: 路径, json: 路径}。"""
    d = logs_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tag = "win" if is_win(gs) else "lose"
    base = os.path.join(d, "run-%s-%s" % (stamp, tag))

    out = {"win": is_win(gs)}
    try:
        txt = build_text(gs)
        p = base + ".txt"
        with open(p, "w", encoding="utf-8") as f:
            f.write(txt)
        out["text"] = p
    except Exception as e:
        out["text_error"] = str(e)

    if also_json:
        try:
            data = {
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "seed": gs.seed,
                "result": gs.result,
                "final": {
                    "night": gs.night, "faith": gs.faith,
                    "gold": gs.gold, "oil": gs.oil,
                    "riders": [r.to_dict() for r in gs.riders],
                    "horses": [h.to_dict() for h in gs.horses],
                },
                "nights": [nr.to_dict() for nr in gs.history],
            }
            p = base + ".json"
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            out["json"] = p
        except Exception as e:
            out["json_error"] = str(e)

    return out


def latest_runs(n=5) -> list[str]:
    """最近的几份日志（按时间倒序）。"""
    d = logs_dir()
    try:
        files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".txt")]
    except Exception:
        return []
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[:n]
