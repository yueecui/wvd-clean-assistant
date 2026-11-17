# -*- coding: utf-8 -*-
"""自动出售（道具店 → 出售 → 持有一览）。

一轮流程（900x1600 实测）：
  列表页底部「全部出售」→ 弹出「全部出售」筛选对话框（等级/品质/材质/特性）
  → 点 OK → 弹出确认对话框（整片橙色装备卡 + 金币变化）→ 点 OK
  → 与服务器交互（列表页右下「正在连接…」）→ 结果弹窗「获得了 X 金币」→ 点「关闭」
  → 回到列表页 → 重复

终止：筛选对话框里的「OK」按钮变暗（没有符合条件的物品）或点了「全部出售」不弹框
      —— 也就是没有可出售的物品了。

界面识别不做 OCR（快且稳），只看固定区域的亮像素：
  对话框 = 左下「取消」亮 + 右上「OK」右边缘亮（列表页这一带有「全部出售」图标，
           所以必须两个条件同时成立）
  结果弹窗 = 屏幕中部「关闭」按钮亮，底部按钮区全暗
  列表页  = 底部按钮区是列表页的样子（没有对话框 / 弹窗特征）
"""
from __future__ import annotations

import io
import re
import time

import numpy as np
from PIL import Image

import parse
import perf
import runtime

# ---------- 区域常量（按 900x1600 设计，其余分辨率按比例换算） ----------
BASE_W, BASE_H = 900, 1600

BTN_SELL_ALL = (0.702, 0.925)       # 底部「全部出售」（图标 + 文字，点文字更稳）
BTN_OK = (0.676, 0.911)             # 对话框「OK」
BTN_CANCEL = (0.324, 0.911)         # 对话框「取消」
BTN_CLOSE_POPUP = (0.500, 0.559)    # 结果弹窗「关闭」

RECT_CANCEL_L = (200, 1420, 330, 1500)   # 对话框「取消」左半（列表页这里是「返回」的一小角）
RECT_POPUP = (330, 862, 570, 928)        # 结果弹窗「关闭」
RECT_CARDS = (60, 380, 850, 1300)        # 对话框中部：确认框是整片橙色装备卡
RECT_GOLD_TEXT = (100, 680, 800, 900)    # 结果弹窗「出售持有物品，获得了 X 金币。」

BRIGHT = 140        # 亮像素阈值
DIALOG_L_MIN = 700  # 「取消」左半亮像素数 ≥ 它 → 对话框打开（列表页同区域只有约 330）
POPUP_MIN = 300     # 结果弹窗「关闭」亮像素数 ≥ 它（弹窗时底部按钮区被压暗，左半为 0）
LIST_L_MAX = 500    # 列表页「取消」左半区域只有约 330
OK_MIN = 400        # 「OK」整块亮像素数 ≥ 它 → 可点击（变暗时接近 0）
CARD_MIN = 35000    # 橙色像素数 ≥ 它 → 确认对话框（筛选框只有约 1 万）

LIST, DIALOG, POPUP, BUSY, STOPPED = "list", "dialog", "popup", "busy", "stopped"
FILTER, CONFIRM = "filter", "confirm"   # 对话框的两副面孔

TASK = "自动出售"
LOG_KIND = "sell"       # log/sell_*.json

TAP_WAIT = 0.6
DIALOG_WAIT = 12.0   # 「全部出售」要先问服务器，弹框慢
CONFIRM_WAIT = 8.0
POPUP_WAIT = 25.0    # 确认后要和服务器交互，出结果弹窗慢
LIST_WAIT = 8.0
MAX_BATCHES = 200


def _open(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def _rect(img: Image.Image, x0, y0, x1, y1) -> tuple[int, int, int, int]:
    sx, sy = img.width / BASE_W, img.height / BASE_H
    return (int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy))


def _bright(img: Image.Image, base: tuple, thresh: int = BRIGHT) -> int:
    a = np.asarray(img.crop(_rect(img, *base)), dtype=np.int16)[:, :, :3]
    return int((a.mean(axis=2) > thresh).sum())


def page_state(img: Image.Image) -> str:
    """按固定区域的亮像素判断当前界面（不依赖 OCR）。

    只看「取消」按钮：它始终是亮的，OK 在没有可出售物品时会变暗，
    所以不能拿 OK 当对话框的判据。
    """
    left = _bright(img, RECT_CANCEL_L)
    if left >= DIALOG_L_MIN:
        return DIALOG
    popup = _bright(img, RECT_POPUP)
    if popup >= POPUP_MIN:
        return POPUP
    if left <= LIST_L_MAX:
        return LIST
    return BUSY


def ok_enabled(img: Image.Image) -> bool:
    return _bright(img, (485, 1420, 735, 1500)) >= OK_MIN


def dialog_kind(img: Image.Image) -> str:
    """筛选对话框（等级/品质/材质勾选）还是确认对话框（整片橙色装备卡）。"""
    a = np.asarray(img.crop(_rect(img, *RECT_CARDS)), dtype=np.int16)[:, :, :3]
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    orange = int(((r > 120) & (r - b > 60) & (g > b)).sum())
    return CONFIRM if orange >= CARD_MIN else FILTER


_GOLD_RE = re.compile(r"(\d{2,})\s*金币")


def read_gold(img: Image.Image) -> int | None:
    """结果弹窗「出售持有物品，获得了 X 金币。」里的金币数。"""
    lines = parse.ocr_lines(img, _rect(img, *RECT_GOLD_TEXT))
    text = "".join(l["text"] for l in lines).replace(" ", "").replace(",", "")
    m = _GOLD_RE.search(text)
    return int(m.group(1)) if m else None


def clock_text(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def duration_text(seconds: float) -> str:
    n = max(0, int(seconds))
    h, m, s = n // 3600, (n // 60) % 60, n % 60
    if h:
        return f"{h}小时{m}分{s}秒"
    return f"{m}分{s}秒" if m else f"{s}秒"


class Seller:
    """自动出售：反复「全部出售 → OK → OK → 关闭」，直到 OK 变暗。"""

    def __init__(self, adb: str, serial: str):
        import threading

        self.adb = adb
        self.serial = serial
        self._thread = None
        self._stop = False
        self._lock = threading.Lock()
        self.logs: list[str] = []
        self.results: list[dict] = []
        self.log_file = ""          # log/ 下的当前日志文件名
        self._loaded = False
        self.status = self._fresh_status("")

    # ---------- 基础 ----------
    def _png(self) -> bytes:
        import capture
        return capture.screenshot(self.adb, self.serial)

    def _img(self) -> Image.Image:
        return _open(self._png())

    def _tap(self, xy: tuple[int, int]) -> None:
        import capture
        capture.tap(self.adb, self.serial, *xy)

    def _tap_pct(self, base: tuple[float, float], img: Image.Image | None = None) -> None:
        img = img or self._img()
        self._tap((int(img.width * base[0]), int(img.height * base[1])))

    def _log(self, msg: str) -> None:
        with self._lock:
            self.logs.append(msg)
            if len(self.logs) > 200:
                self.logs = self.logs[-200:]
        print("[sell]", msg)
        self._persist()

    def snapshot(self) -> dict:
        self._ensure_loaded()
        with self._lock:
            status = dict(self.status)
            status["log_file"] = self.log_file
            return {"status": status, "logs": list(self.logs[-60:]),
                    "results": list(self.results)}

    def stop(self) -> dict:
        self._stop = True
        with self._lock:
            if self.status.get("running"):
                self.status["phase"] = "stopping"
        return {"ok": True}

    # ---------- 日志文件 ----------
    @staticmethod
    def _fresh_status(task: str) -> dict:
        return {"running": False, "phase": "idle", "batch": 0, "gold": 0,
                "current": "", "error": None,
                "task": task, "started_at": None, "finished_at": None,
                "elapsed": 0.0, "run_started_at": None}

    def _dump(self) -> dict:
        with self._lock:
            st = self.status
            return {"kind": LOG_KIND, "task": st.get("task") or TASK,
                    "started_at": st.get("started_at"),
                    "finished_at": st.get("finished_at"),
                    "elapsed": round(runtime.used(st), 1),
                    "stats": {"batch": st.get("batch", 0), "gold": st.get("gold", 0)},
                    "logs": list(self.logs), "results": list(self.results)}

    def _persist(self) -> None:
        """落盘到当前日志文件（没有就新建一份）。失败不影响跑任务。"""
        import store

        try:
            self.log_file = store.save_log(LOG_KIND, self._dump(), self.log_file)
        except Exception:  # noqa: BLE001
            pass

    def _restore(self, data: dict) -> None:
        if not data:
            return
        stats = data.get("stats") or {}
        elapsed = data.get("elapsed")
        if not isinstance(elapsed, (int, float)):
            # 老日志没有 elapsed：退回「结束 - 开始」当作累计运行时间
            a, b = data.get("started_at"), data.get("finished_at")
            elapsed = max(0.0, b - a) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else 0.0
        with self._lock:
            self.logs = [str(x) for x in (data.get("logs") or [])]
            self.results = [r for r in (data.get("results") or []) if isinstance(r, dict)]
            self.status = {"running": False, "phase": "idle",
                           "batch": int(stats.get("batch") or 0),
                           "gold": int(stats.get("gold") or 0),
                           "current": "", "error": None,
                           "task": data.get("task") or TASK,
                           "started_at": data.get("started_at"),
                           "finished_at": data.get("finished_at"),
                           "elapsed": float(elapsed),
                           "run_started_at": None}

    def _ensure_loaded(self) -> None:
        """进程刚起来 / 刷新页面时，把上次的当前日志读进来。"""
        if self._loaded or self.status.get("running"):
            return
        self._loaded = True
        import store

        name = store.current_log(LOG_KIND)
        if name:
            self.log_file = name
            self._restore(store.load_log(LOG_KIND, name))

    def open_log(self, name: str) -> dict:
        """打开某份历史日志（运行中不允许）。"""
        if self.status.get("running"):
            return {"ok": False, "error": "任务运行中，先停止再切换日志"}
        import store

        data = store.open_log(LOG_KIND, name)
        if not data:
            return {"ok": False, "error": "日志文件不存在"}
        self.log_file = store.current_log(LOG_KIND) or name
        self._loaded = True
        self._restore(data)
        return {"ok": True, "log_file": self.log_file}

    # ---------- 任务计时 ----------
    def _begin(self, task: str) -> None:
        """开始（或改完过滤器再次开始）。

        再次开始不清列表：日志、每批结果、金币总数、开始时间都沿用上次的，
        批号接着往下排；运行时间接着累加（停着的时候不算）。
        """
        perf.begin_task()
        ts = time.time()
        with self._lock:
            started = bool(self.status.get("started_at")) or bool(self.results) or bool(self.logs)
            if started:
                self.status.update({"running": True, "phase": "start",
                                    "current": "", "error": None, "finished_at": None})
                if not self.status.get("started_at"):
                    self.status["started_at"] = ts
                done = self.status.get("batch", 0)
                runtime.begin(self.status, ts)      # 累计运行时间接着往下加
            else:
                self.logs = []
                self.results = []
                self.status = self._fresh_status(task)
                self.status.update({"running": True, "phase": "start",
                                    "started_at": ts})
                runtime.begin(self.status, ts)
                done = 0
        self._log(f"[{clock_text(ts)}] {task}开始" if not done else
                  f"[{clock_text(ts)}] {task}继续（已完成 {done} 批，接着累加）")

    def _end(self, phase: str, msg: str, error: str | None = None) -> None:
        import notify

        perf.end_task()
        ts = time.time()
        with self._lock:
            self.status.update({"running": False, "phase": phase, "current": "",
                                "finished_at": ts, "error": error})
            elapsed = runtime.end(self.status, ts)
            task = self.status.get("task") or "任务"
        total = duration_text(elapsed)
        self._log(f"[{clock_text(ts)}] {msg} · 运行 {total}")
        self._persist()
        notify.task_finished(task, phase, msg, total)

    def _set_current(self, text: str) -> None:
        with self._lock:
            self.status["current"] = text

    # ---------- 状态 ----------
    def _state(self) -> str:
        if self._stop:
            return STOPPED
        return page_state(self._img())

    def _wait_state(self, want: tuple[str, ...], timeout: float) -> str:
        end = time.time() + timeout
        while time.time() < end:
            if self._stop:
                return STOPPED
            st = self._state()
            if st in want:
                return st
            time.sleep(0.4)
        return self._state()

    def _wait_dialog(self, want: str, timeout: float) -> str:
        """等到指定形态的对话框出现（筛选框 / 确认框外观差很多，必须区分）。"""
        end = time.time() + timeout
        while time.time() < end:
            if self._stop:
                return STOPPED
            img = self._img()
            if page_state(img) == DIALOG and dialog_kind(img) == want:
                return want
            time.sleep(0.35)
        return "timeout"

    def _is_sell_list(self) -> bool:
        """列表页 + 顶部标题「出售」，防止在别的界面乱点。"""
        img = self._img()
        if page_state(img) != LIST:
            return False
        text = "".join(l["text"] for l in parse.ocr_lines(img, _rect(img, 0, 60, 900, 520)))
        return "出售" in text

    def _ensure_list(self, timeout: float = 10.0) -> bool:
        """回到出售列表页：结果弹窗点关闭、对话框点取消；过渡动画期间只等待。"""
        end = time.time() + timeout
        while time.time() < end:
            st = self._state()
            if st == STOPPED:
                return False
            if st == LIST:
                return True
            if st == POPUP:
                if self._close_popup():
                    return True
                continue
            if st == DIALOG:
                self._close_dialog()
                continue
            time.sleep(0.5)
        return self._state() == LIST

    def _close_dialog(self) -> None:
        self._log("· 关闭对话框")
        self._tap_pct(BTN_CANCEL)
        time.sleep(TAP_WAIT)

    def _close_popup(self) -> bool:
        """点「关闭」退出结果弹窗；按钮刚出现时点不动，所以最多试两次。"""
        for _ in range(2):
            if page_state(self._img()) == LIST:
                return True
            self._log("· 关闭结果弹窗")
            time.sleep(0.5)
            self._tap_pct(BTN_CLOSE_POPUP)
            if self._wait_state((LIST,), LIST_WAIT) == LIST:
                return True
        return False

    # ---------- 执行 ----------
    def start(self, mode: str = "new") -> dict:
        """mode: new = 新建日志从头统计；resume = 接着当前日志继续累加。"""
        import threading

        if self._thread and self._thread.is_alive():
            return {"ok": False, "error": "已有出售任务在运行"}
        import store

        self._stop = False
        self._loaded = True
        if mode == "resume":
            name = store.current_log(LOG_KIND)
            if not name:
                return {"ok": False, "error": "没有可继续的日志"}
            self.log_file = name
            self._restore(store.load_log(LOG_KIND, name))
        else:
            self.log_file = store.new_log(LOG_KIND)
            with self._lock:
                self.logs = []
                self.results = []
                self.status = self._fresh_status(TASK)
        self._begin(TASK)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return {"ok": True, "log_file": self.log_file}

    def _run(self) -> None:
        try:
            if not self._ensure_list() or not self._is_sell_list():
                self._fail("当前不在「道具店 → 出售 → 持有一览」界面："
                           "请先停到出售的持有一览，并配好过滤器")
                return
            self._log("界面确认：道具店 · 出售 · 持有一览")
            with self._lock:
                self.status["phase"] = "running"
            empty = 0
            for _ in range(MAX_BATCHES):
                if self._stop:
                    break
                with self._lock:
                    batch = self.status["batch"] + 1     # 批号接着上次往下排
                self._set_current(f"第 {batch} 批")
                if not self._ensure_list():
                    self._log("回不到出售列表，结束")
                    break
                got, note = self._one_batch()
                if self._stop:
                    break                                # 中途停止：这一批不计入
                if got == "disabled":
                    self._log("OK 按钮已变暗（没有可出售的物品），结束")
                    break
                if got == "none":
                    empty += 1
                    self._log(f"{note}，没有出售结果")
                    if empty >= 2:
                        self._log("连续 2 批没有出售结果，判断已无可出售的物品，结束")
                        break
                    continue
                empty = 0
                gold = note
                with self._lock:
                    self.status["batch"] = batch
                    if gold:
                        self.status["gold"] += gold
                    self.results.append({"batch": batch, "gold": gold or 0, "at": time.time()})
                self._log(f"第 {batch} 批：出售完成，获得 {gold if gold else '未知'} 金币")
            self._finish()
        except Exception as e:  # noqa: BLE001
            self._fail(f"执行异常: {e}")

    def _one_batch(self) -> tuple[str, object]:
        """一轮：全部出售 → OK（筛选框）→ OK（确认框）→ 关闭结果弹窗。"""
        self._tap_pct(BTN_SELL_ALL)
        st = self._wait_dialog(FILTER, DIALOG_WAIT)
        if st == STOPPED:
            return "none", "已停止"
        if st != FILTER:
            return "none", "点了「全部出售」没有弹出对话框"
        if not ok_enabled(self._img()):
            self._close_dialog()
            return "disabled", ""

        self._tap_pct(BTN_OK)                   # 筛选框 → 确认框
        st = self._wait_dialog(CONFIRM, CONFIRM_WAIT)
        if st == STOPPED:
            return "none", "已停止"
        if st != CONFIRM:
            return "none", "筛选框点 OK 后没有出现确认框"
        if not ok_enabled(self._img()):
            self._close_dialog()
            return "disabled", ""

        self._tap_pct(BTN_OK)                   # 确认框 → 与服务器交互
        st = self._wait_state((POPUP,), POPUP_WAIT)
        if st == STOPPED:
            return "none", "已停止"
        if st != POPUP:
            return "none", "没有出现出售结果弹窗"
        img = self._img()
        gold = read_gold(img)
        if gold is None:
            self._log("  ⚠ 结果弹窗的金币数没读到")
        self._close_popup()
        return "ok", gold

    def _fail(self, msg: str) -> None:
        self._end("error", msg, msg)

    def _finish(self) -> None:
        with self._lock:
            batch = self.status["batch"]
            gold = self.status["gold"]
        if self._stop:
            self._end("stopped", f"已停止：处理 {batch} 批，获得 {gold} 金币")
        else:
            self._end("done", f"完成：处理 {batch} 批，获得 {gold} 金币")
