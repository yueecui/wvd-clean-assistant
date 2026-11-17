# -*- coding: utf-8 -*-
"""任务运行时间统计：只算真正在跑的时间。

自动出售 / 自动提炼支持「停止后再继续」，如果直接用 finished_at - started_at，
中间停着的那几分钟也会被算进「总用时」。这里在 status 里维护两个字段：

    elapsed         已经跑完的几轮累计秒数
    run_started_at  本轮开始时间（只有运行中有值，结束时清空）

落盘时只存 elapsed（= 截至落盘已跑的秒数），进程重启后继续累加不会倒退。
"""
from __future__ import annotations

import time


def reset(status: dict) -> None:
    """新建任务：运行时间从 0 起算。"""
    status["elapsed"] = 0.0
    status["run_started_at"] = None


def begin(status: dict, ts: float | None = None) -> float:
    """开始（或继续）一轮：记下本轮起点，累计秒数保留。"""
    ts = time.time() if ts is None else ts
    status.setdefault("elapsed", 0.0)
    status["run_started_at"] = ts
    return ts


def end(status: dict, ts: float | None = None) -> float:
    """结束一轮：本轮时长累加进 elapsed，返回累计运行秒数。"""
    ts = time.time() if ts is None else ts
    t0 = status.get("run_started_at")
    if t0:
        status["elapsed"] = float(status.get("elapsed") or 0.0) + max(0.0, ts - t0)
    status["run_started_at"] = None
    return float(status.get("elapsed") or 0.0)


def used(status: dict, now: float | None = None) -> float:
    """累计运行秒数；运行中把本轮已经跑掉的时间也算上。"""
    total = float(status.get("elapsed") or 0.0)
    t0 = status.get("run_started_at")
    if t0:
        total += max(0.0, (time.time() if now is None else now) - t0)
    return total
