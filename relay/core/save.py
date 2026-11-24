# -*- coding: utf-8 -*-
"""存档：读写磁盘。

设计：
  - 一个存档 = 一个 JSON 文件，放在 `logs/saves/` 旁边（exe 同目录）
  - 三个手动槽 + 一个自动槽
  - 带 version 字段，加载时做兼容
  - 存档坏了不能崩游戏：读失败返回 None，并保留原文件

存放位置和日志一致（`sys.executable` 所在目录），因为玩家要能找到。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from .sim import GameState

SAVE_VERSION = 3

SLOTS = ("auto", "slot1", "slot2", "slot3")


def saves_dir() -> Path:
    """存档目录。打包后放在 exe 旁边，开发时放在项目根。"""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent.parent
    d = base / "saves"
    d.mkdir(parents=True, exist_ok=True)
    return d


def slot_path(slot: str) -> Path:
    return saves_dir() / ("%s.json" % slot)


def save(gs: GameState, slot: str = "auto") -> Optional[Path]:
    """存盘。成功返回路径，失败返回 None。

    先写临时文件再替换，避免写到一半被打断留下半个存档。
    """
    try:
        d = gs.to_dict()
        d["version"] = SAVE_VERSION
        d["saved_at"] = int(time.time())
        p = slot_path(slot)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        return p
    except (OSError, TypeError, ValueError):
        return None


def load(slot: str = "auto") -> Optional[GameState]:
    """读盘。不存在、版本不认识、或坏掉都返回 None。

    不能因为存档坏了就让游戏起不来——宁可丢掉存档，也不能崩。
    """
    p = slot_path(slot)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None

    ver = d.get("version", 1)
    if ver > SAVE_VERSION:
        # 比本程序新的存档，别猜怎么读
        return None
    if ver < SAVE_VERSION:
        d = _migrate(d, ver)
        if d is None:
            return None

    try:
        gs = GameState.from_dict(d)
    except (KeyError, TypeError, ValueError):
        return None
    return gs


def _migrate(d: dict, from_ver: int) -> Optional[dict]:
    """把旧版存档升到当前版本。识别不了的版本返回 None。

    v1（0.2.0）：没有 history 的 from_dict 支持、faith 可能是浮点、
                 没有 used_names。能读，但历史会是空的。
    v2（0.3.0）：history 存了但读的时候没恢复（那个 bug 已修）。
                 结构上已经是当前格式，直接放行。
    """
    if from_ver == 2:
        # v2（0.3.x）没有在途任务；补一个空列表即可
        d.setdefault("trips", [])
        d["version"] = SAVE_VERSION
        return d
    if from_ver == 1:
        # 最老的一版：faith 可能是浮点，history 结构没有 from_dict
        d["version"] = SAVE_VERSION
        d.setdefault("faith", 50)
        try:
            d["faith"] = int(round(float(d["faith"])))
        except (TypeError, ValueError):
            d["faith"] = 50
        d.setdefault("history", [])
        d.setdefault("used_names", [])
        d.setdefault("used_horse_names", [])
        return d
    return None


def exists(slot: str = "auto") -> bool:
    return slot_path(slot).exists()


def info(slot: str = "auto") -> Optional[dict]:
    """不完整加载，只读元信息——给标题页显示「继续：第 7 夜，信 62」。"""
    p = slot_path(slot)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    return {
        "slot": slot,
        "night": d.get("night", 1),
        "faith": d.get("faith", 0),
        "gold": d.get("gold", 0),
        "seed": d.get("seed"),
        "saved_at": d.get("saved_at", 0),
        "version": d.get("version", 1),
    }


def delete(slot: str = "auto") -> bool:
    try:
        p = slot_path(slot)
        if p.exists():
            p.unlink()
            return True
    except OSError:
        pass
    return False


def list_saves() -> list[dict]:
    out = []
    for s in SLOTS:
        i = info(s)
        if i:
            out.append(i)
    return out
