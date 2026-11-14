# -*- coding: utf-8 -*-
"""ADB 截图封装：优先用户配置，其次程序目录自带 adb.exe，再次 MuMu 自带 adb。"""
from __future__ import annotations

import os
import subprocess
import sys

MUMU_ADB_CANDIDATES = [
    r"C:\Program Files\Netease\MuMu\nx_main\adb.exe",
    r"C:\Program Files\Netease\MuMu\shell\adb.exe",
    r"D:\Program Files\Netease\MuMu\nx_main\adb.exe",
]
DEFAULT_SERIAL = "127.0.0.1:16384"


def resolve_adb(configured: str | None) -> str | None:
    if configured and os.path.isfile(configured):
        return configured
    # PyInstaller 冻结时 adb.exe 放在 exe 同目录；源码运行时放程序根目录
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(sys.executable))
    roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 工程根
    for root in roots:
        p = os.path.join(root, "adb.exe")
        if os.path.isfile(p):
            return p
    for p in MUMU_ADB_CANDIDATES:
        if os.path.isfile(p):
            return p
    return "adb"  # 交给 PATH


def run_adb(adb: str, serial: str, *args: str, timeout: int = 15) -> subprocess.CompletedProcess:
    cmd = [adb]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def list_devices(adb: str) -> list[str]:
    try:
        r = run_adb(adb, "", "devices", timeout=10)
        out = r.stdout.decode("utf-8", "replace")
    except Exception:
        return []
    serials = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def tap(adb: str, serial: str, x: int, y: int) -> None:
    run_adb(adb, serial, "shell", "input", "tap", str(int(x)), str(int(y)))


def long_press(adb: str, serial: str, x: int, y: int, ms: int = 400) -> None:
    """长按：DOWN → 停顿 → UP（input swipe 原地按住，部分界面用它触发选中）。"""
    run_adb(adb, serial, "shell", "input", "swipe",
            str(int(x)), str(int(y)), str(int(x)), str(int(y)), str(int(ms)))


def drag(adb: str, serial: str, x1: int, y1: int, x2: int, y2: int,
         steps: int = 10, ms: int = 500, hold: float = 0.25) -> bool:
    """精确拖动：按住 → 分步移动 → 停 hold 秒再抬起（不会产生惯性滑动）。

    直接用 `input swipe` 是线性甩动，游戏会给惯性，滚动量不可控。
    返回 False 表示设备不支持 motionevent，调用方可回退。
    """
    import time as _t
    r = run_adb(adb, serial, "shell", "input", "motionevent", "DOWN", str(int(x1)), str(int(y1)))
    if r.returncode != 0:
        return False
    step_sleep = ms / 1000.0 / max(1, steps)
    for i in range(1, steps + 1):
        _t.sleep(step_sleep)
        x = int(x1 + (x2 - x1) * i / steps)
        y = int(y1 + (y2 - y1) * i / steps)
        run_adb(adb, serial, "shell", "input", "motionevent", "MOVE", str(x), str(y))
    _t.sleep(hold)
    run_adb(adb, serial, "shell", "input", "motionevent", "UP", str(int(x2)), str(int(y2)))
    return True


def screenshot(adb: str, serial: str) -> bytes:
    """截屏，返回 PNG 字节。exec-out 失败时退回 /sdcard 中转。"""
    r = run_adb(adb, serial, "exec-out", "screencap", "-p", timeout=20)
    if r.returncode == 0 and r.stdout[:8] == b"\x89PNG\r\n\x1a\n":
        return r.stdout
    # 兜底：写到设备再 pull
    run_adb(adb, serial, "shell", "screencap", "-p", "/sdcard/wvd_scan_tmp.png", timeout=20)
    r2 = run_adb(adb, serial, "exec-out", "cat", "/sdcard/wvd_scan_tmp.png", timeout=20)
    if r2.returncode == 0 and r2.stdout[:8] == b"\x89PNG\r\n\x1a\n":
        return r2.stdout
    raise RuntimeError(f"截屏失败: rc={r.returncode} err={r.stderr[:200]!r}")
