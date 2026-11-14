# -*- coding: utf-8 -*-
"""扫描 / 改造时的 CPU 资源控制。

rapidocr_onnxruntime 并不认 intra_op_num_threads 参数：它的 OrtInferSession 直接
用默认 SessionOptions()，ONNX Runtime 会按 CPU 核心数开满线程，扫描时把 CPU
占满、前台程序被抢卡。这里在 OCR 实例化前替换库里的 SessionOptions 工厂，真正
把线程数限下来；任务运行期间再把进程优先级降一档，让前台优先获得时间片。

档位（config/settings.json 的 cpu_mode）：
  fast      不限线程、正常优先级（旧行为，最快但会抢前台）
  balanced  2 线程 + 低优先级（默认）
  quiet     1 线程 + 低优先级 + 每件之间额外让出 0.15s
"""
from __future__ import annotations

import sys
import threading
import time

MODES: dict[str, tuple[int, bool, float]] = {
    "fast": (0, False, 0.0),
    "balanced": (2, True, 0.0),
    "quiet": (1, True, 0.15),
}
DEFAULT_MODE = "balanced"

_mode = DEFAULT_MODE
_lock = threading.Lock()
_tasks = 0

_NORMAL_PRIORITY_CLASS = 0x00000020
_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


def mode() -> str:
    return _mode


def set_mode(value: str) -> str:
    """切换档位；任务进行中切换也会立刻调整优先级。"""
    global _mode
    with _lock:
        _mode = value if value in MODES else DEFAULT_MODE
        low = _tasks > 0 and MODES[_mode][1]
    _set_priority(_BELOW_NORMAL_PRIORITY_CLASS if low else _NORMAL_PRIORITY_CLASS)
    return _mode


def ocr_threads() -> int:
    """0 = 不限，交给 ONNX Runtime 按核心数自动开。"""
    return MODES[_mode][0]


def configure_ocr() -> None:
    """必须在 RapidOCR() 实例化之前调用（会话一旦创建，线程数就固定了）。"""
    if ocr_threads() <= 0:
        return
    try:
        import onnxruntime
        from rapidocr_onnxruntime import utils as ru

        if getattr(ru.SessionOptions, "_wvd_low_cpu", False):
            return
        base = onnxruntime.SessionOptions

        def _factory():
            opt = base()
            opt.intra_op_num_threads = ocr_threads() or 0
            opt.inter_op_num_threads = 1
            return opt

        _factory._wvd_low_cpu = True
        ru.SessionOptions = _factory
    except Exception as e:  # noqa: BLE001
        # 库版本变了也要能跑：此时只剩进程优先级这一层保护
        print(f"[perf] OCR 线程限制未生效（{e}）")


def _set_priority(cls: int) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.SetPriorityClass.restype = ctypes.c_bool
        k.SetPriorityClass(k.GetCurrentProcess(), cls)
    except Exception:  # noqa: BLE001
        pass


def begin_task() -> None:
    global _tasks
    with _lock:
        _tasks += 1
        low = _tasks == 1 and MODES[_mode][1]
    if low:
        _set_priority(_BELOW_NORMAL_PRIORITY_CLASS)


def end_task() -> None:
    global _tasks
    with _lock:
        _tasks = max(0, _tasks - 1)
        restore = _tasks == 0
    if restore:
        _set_priority(_NORMAL_PRIORITY_CLASS)


def idle_sleep() -> None:
    """省资源档在两件装备之间多让出一点时间，摊平 OCR 尖峰。"""
    d = MODES[_mode][2]
    if d:
        time.sleep(d)
