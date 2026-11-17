# -*- coding: utf-8 -*-
"""自动提炼（铁匠铺 → 提炼 → 持有一览）。

一轮流程（900x1600 实测）：
  列表页底部「全选」→ 弹出「一键提炼」筛选对话框 → 点 OK
  → 弹出确认对话框（列出本次要提炼的装备）→ 点 OK
  → 提炼动画 → 「提炼结果」面板 → 点「关闭」→ 回到列表页 → 重复

终止：对话框里的「OK」按钮变暗（不可点）或全选后不再弹对话框
      —— 也就是没有可提炼的装备了。

界面识别只用底部按钮区的亮像素统计，不做 OCR（快且稳）：
  对话框   = 左下「取消」按钮亮
  提炼结果 = 只有中间「关闭」亮，两侧按钮全暗
  列表页   = 右下「全选」复选框亮
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

BTN_SELECT_ALL = (0.722, 0.922)     # 底部「全选」复选框
BTN_OK = (0.749, 0.909)             # 对话框「OK」
BTN_CANCEL = (0.322, 0.909)         # 对话框「取消」
BTN_CLOSE = (0.481, 0.919)          # 提炼结果「关闭」

RECT_CANCEL = (200, 1400, 380, 1510)   # 取消按钮（始终可点，用来判「有没有对话框」）
RECT_OK = (500, 1400, 720, 1510)       # OK 按钮（亮 = 可点，暗 = 无可提炼物品）
RECT_CLOSE = (380, 1440, 495, 1505)    # 提炼结果「关闭」
RECT_SELECT_ALL = (620, 1445, 680, 1505)  # 列表页「全选」复选框
RECT_CARDS = (60, 380, 850, 1300)      # 对话框中部：确认框是整片橙色装备卡

BRIGHT = 140        # 亮像素阈值
DIALOG_MIN = 1000   # 「取消」亮像素数 ≥ 它 → 对话框打开
OK_MIN = 400        # 「OK」亮像素数 ≥ 它 → 可点击
RESULT_MIN = 300    # 「关闭」亮像素数 ≥ 它 → 提炼结果面板
SELECT_MIN = 250    # 「全选」亮像素数 ≥ 它 → 列表页
CARD_MIN = 35000    # 橙色像素数 ≥ 它 → 确认对话框（筛选框只有约 1 万）

LIST, DIALOG, RESULT, BUSY, STOPPED = "list", "dialog", "result", "busy", "stopped"
FILTER, CONFIRM = "filter", "confirm"   # 对话框的两副面孔

TASK = "自动提炼"
LOG_KIND = "refine"     # log/refine_*.json

TAP_WAIT = 0.6
DIALOG_WAIT = 6.0
ANIM_WAIT = 25.0
LIST_WAIT = 8.0
MAX_BATCHES = 100


def _open(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def _rect(img: Image.Image, x0, y0, x1, y1) -> tuple[int, int, int, int]:
    sx, sy = img.width / BASE_W, img.height / BASE_H
    return (int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy))


def _bright(img: Image.Image, base: tuple, thresh: int = BRIGHT) -> int:
    a = np.asarray(img.crop(_rect(img, *base)), dtype=np.int16)[:, :, :3]
    return int((a.mean(axis=2) > thresh).sum())


def page_state(img: Image.Image) -> str:
    """按底部按钮区判断当前界面（不依赖 OCR）。"""
    cancel = _bright(img, RECT_CANCEL)
    if cancel >= DIALOG_MIN:
        return DIALOG
    ok = _bright(img, RECT_OK)
    close = _bright(img, RECT_CLOSE)
    if close >= RESULT_MIN and cancel < 200 and ok < 200:
        return RESULT
    if _bright(img, RECT_SELECT_ALL) >= SELECT_MIN:
        return LIST
    return BUSY


def ok_enabled(img: Image.Image) -> bool:
    return _bright(img, RECT_OK) >= OK_MIN


def dialog_kind(img: Image.Image) -> str:
    """筛选对话框（等级/品质/材质勾选）还是确认对话框（整片橙色装备卡）。"""
    a = np.asarray(img.crop(_rect(img, *RECT_CARDS)), dtype=np.int16)[:, :, :3]
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    orange = int(((r > 120) & (r - b > 60) & (g > b)).sum())
    return CONFIRM if orange >= CARD_MIN else FILTER


_RESULT_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


def read_result(img: Image.Image) -> tuple[int, int, bool]:
    """提炼结果面板的「成功 X/Y」→ (成功数, 总数, 是否读到)。

    这行字又小又淡，直接 OCR 检测不到；先二值化再放大 2 倍才能稳读。
    """
    c = img.crop(_rect(img, 200, 190, 720, 270)).convert("L")
    mask = ((np.asarray(c).astype(np.int16) > 110) * 255).astype("uint8")
    big = Image.fromarray(mask).convert("RGB")
    big = big.resize((big.width * 2, big.height * 2), Image.LANCZOS)
    text = "".join(l["text"] for l in parse.ocr_lines(big)).replace(" ", "")
    m = _RESULT_RE.search(text)
    if not m:
        return 0, 0, False
    return int(m.group(1)), int(m.group(2)), True


# ---------- 稀有改造石（下级全改造石 / 全改造石）----------
# 出的时候一定排在结果列表最上面（行底色高亮），一次可能好几个，所以只看前几行。
STONE_ROW_Y0 = 300      # 第 1 行文字上沿
STONE_ROW_H = 86.5      # 行距
STONE_X0, STONE_X1 = 535, 800   # 改造石名字区
STONE_SCAN_ROWS = 5     # 最多看 5 行
STONE_LOWER_W = 115     # 文字宽度 ≥ 它算「下级全改造石」（实测 136 / 96）


def _stone_row(img: Image.Image, i: int) -> tuple[str, int]:
    """结果面板第 i 行（0 起）的改造石名字 + 文字宽度。"""
    y0 = int(STONE_ROW_Y0 + i * STONE_ROW_H)
    c = img.crop(_rect(img, STONE_X0, y0, STONE_X1, y0 + 44))
    big = c.resize((c.width * 3, c.height * 3), Image.LANCZOS)
    lines = parse.ocr_lines(big)
    text = "".join(l["text"] for l in lines).replace(" ", "")
    width = max((l["w"] // 3 for l in lines), default=0)
    return text, width


def _row_highlighted(img: Image.Image, i: int) -> bool:
    """稀有石头那几行的底色是高亮青绿（实测 RGB≈(23,96,104)，普通行 (32,46,48)）。"""
    y0 = int(STONE_ROW_Y0 + i * STONE_ROW_H)
    a = np.asarray(img.crop(_rect(img, 780, y0 + 10, 830, y0 + 34)), dtype=np.int16)
    g = float(a[:, :, 1].mean())
    return g >= 70


def read_special_stones(img: Image.Image) -> tuple[int, int, int]:
    """结果面板顶部出现的高级改造石 → (下级全改造石, 全改造石, 认不出的高亮行数)。

    普通行是「改造石（属性+范围）」带数字、底色暗；两种稀有石头没有数值后缀、
    行底色高亮，且一定连着排在最上面。所以从第 1 行往下数，遇到既不高亮、
    也不是稀有名字的行就停。
    """
    lower = full = unknown = 0
    for i in range(STONE_SCAN_ROWS):
        hl = _row_highlighted(img, i)
        text, width = _stone_row(img, i)
        if "全改造" in text:
            if "下" in text[:2] or width >= STONE_LOWER_W:
                lower += 1
            else:
                full += 1
            continue
        if "改造" in text and not re.search(r"\d", text):
            # 认漏了字：没有数值后缀的改造石只可能是稀有石头，按文字宽度分
            if width >= STONE_LOWER_W:
                lower += 1
            else:
                full += 1
            continue
        if hl:
            unknown += 1      # 高亮了但认不出名字：别硬猜，留给日志报警
            continue
        break
    return lower, full, unknown


def clock_text(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def duration_text(seconds: float) -> str:
    n = max(0, int(seconds))
    h, m, s = n // 3600, (n // 60) % 60, n % 60
    if h:
        return f"{h}小时{m}分{s}秒"
    return f"{m}分{s}秒" if m else f"{s}秒"


class Refiner:
    """自动提炼：反复「全选 → OK → OK → 关闭结果」，直到 OK 变暗。"""

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
        print("[refine]", msg)
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
        return {"running": False, "phase": "idle", "batch": 0,
                "items": 0, "success": 0, "lower": 0, "full": 0,
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
                    "stats": {"batch": st.get("batch", 0), "items": st.get("items", 0),
                              "success": st.get("success", 0),
                              "lower": st.get("lower", 0), "full": st.get("full", 0)},
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
                           "items": int(stats.get("items") or 0),
                           "success": int(stats.get("success") or 0),
                           "lower": int(stats.get("lower") or 0),
                           "full": int(stats.get("full") or 0),
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

        再次开始不清列表：日志、每批结果、总数、开始时间都沿用上次的，
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

    def _ensure_list(self, timeout: float = 8.0) -> bool:
        """回到提炼列表页：结果面板点关闭、对话框点取消（确认框 → 筛选框 → 列表）。

        过渡动画期间认不出界面时只等待、不乱点；超时才放弃。
        """
        end = time.time() + timeout
        while time.time() < end:
            st = self._state()
            if st == STOPPED:
                return False
            if st == LIST:
                return True
            if st == RESULT:
                if self._close_result():
                    return True
                continue
            if st == DIALOG:
                self._log("· 关闭残留对话框")
                self._tap_pct(BTN_CANCEL)
                time.sleep(TAP_WAIT)
                continue
            time.sleep(0.5)       # 动画 / 过渡：等一下再看
        return self._state() == LIST

    def _is_refine_list(self) -> bool:
        """列表页（有全选复选框）+ 顶部标题「提炼」，防止在别的界面乱点。

        「持有一览」那行小字 OCR 经常漏，只能靠标题判断。
        """
        img = self._img()
        if page_state(img) != LIST:
            return False
        text = "".join(l["text"] for l in parse.ocr_lines(img, _rect(img, 0, 60, 900, 520)))
        return "提炼" in text

    def _close_dialog(self) -> None:
        """点「取消」退出残留对话框，把游戏留在列表页（不影响结论）。"""
        self._log("· 关闭对话框")
        self._tap_pct(BTN_CANCEL)
        time.sleep(TAP_WAIT)

    def _close_result(self) -> bool:
        """点「关闭」退出提炼结果面板；按钮刚出现时点不动，所以最多试两次。"""
        for _ in range(2):
            if page_state(self._img()) == LIST:
                return True
            self._log("· 关闭提炼结果")
            time.sleep(0.5)          # 面板淡入动画期间点击无效
            self._tap_pct(BTN_CLOSE)
            if self._wait_state((LIST,), LIST_WAIT) == LIST:
                return True
        return False

    # ---------- 执行 ----------
    def start(self, mode: str = "new") -> dict:
        """mode: new = 新建日志从头统计；resume = 接着当前日志继续累加。"""
        import threading

        if self._thread and self._thread.is_alive():
            return {"ok": False, "error": "已有提炼任务在运行"}
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
            if not self._ensure_list() or not self._is_refine_list():
                self._fail("当前不在「铁匠铺 → 提炼 → 持有一览」界面："
                           "请先停到提炼的持有一览，并配好过滤器")
                return
            self._log("界面确认：铁匠铺 · 提炼 · 持有一览")
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
                    self._log("回不到提炼列表，结束")
                    break
                got, note = self._one_batch()
                if self._stop:
                    break                                # 中途停止：这一批不计入
                if got == "disabled":
                    self._log("OK 按钮已变暗（没有可提炼的装备），结束")
                    break
                if got == "none":
                    empty += 1
                    self._log(f"{note}，没有出现提炼结果")
                    if empty >= 2:
                        self._log("连续 2 批没有提炼结果，判断已无可提炼的装备，结束")
                        break
                    continue
                empty = 0
                success, total, lower, full = note
                with self._lock:
                    self.status["batch"] = batch
                    self.status["items"] += total
                    self.status["success"] += success
                    self.status["lower"] += lower
                    self.status["full"] += full
                    self.results.append({"batch": batch, "success": success,
                                         "total": total, "lower": lower,
                                         "full": full, "at": time.time()})
                self._log(f"第 {batch} 批：提炼 {total} 件，成功 {success} 件")
                if lower or full:
                    self._log(f"  ★ 下级全改造石 ×{lower}，全改造石 ×{full}")
                if total <= 0:
                    self._log("提炼结果为空，结束")
                    break
            self._finish()
        except Exception as e:  # noqa: BLE001
            self._fail(f"执行异常: {e}")

    def _one_batch(self) -> tuple[str, object]:
        """一轮：全选 → OK（筛选框）→ OK（确认框）→ 关闭结果。

        返回 ("ok", (成功数, 总数, 下级全改造石, 全改造石))
             / ("disabled", "") / ("none", 原因)。
        """
        self._tap_pct(BTN_SELECT_ALL)
        st = self._wait_dialog(FILTER, DIALOG_WAIT)
        if st == STOPPED:
            return "none", "已停止"
        if st != FILTER:
            return "none", "全选后没有弹出「一键提炼」对话框"
        if not ok_enabled(self._img()):
            self._close_dialog()
            return "disabled", ""

        self._tap_pct(BTN_OK)                   # 筛选框 → 确认框
        st = self._wait_dialog(CONFIRM, DIALOG_WAIT)
        if st == STOPPED:
            return "none", "已停止"
        if st != CONFIRM:
            return "none", "筛选框点 OK 后没有出现确认框"
        if not ok_enabled(self._img()):
            return "disabled", ""

        self._tap_pct(BTN_OK)                   # 确认框 → 开始提炼
        st = self._wait_state((RESULT,), ANIM_WAIT)
        if st == STOPPED:
            return "none", "已停止"
        if st != RESULT:
            return "none", "没有出现提炼结果面板"
        time.sleep(0.35)                        # 等面板淡入完成，字才清晰
        img = self._img()
        success, total, parsed = read_result(img)
        if not parsed:
            self._log("  ⚠ 结果面板的「成功 X/Y」没读到，按未知处理")
        lower, full, unknown = read_special_stones(img)
        for _ in range(2):                      # 有高亮行认不出名字就重截一次
            if not unknown:
                break
            time.sleep(0.5)
            l2, f2, u2 = read_special_stones(self._img())
            if u2 < unknown or l2 > lower or f2 > full:
                lower, full, unknown = max(lower, l2), max(full, f2), u2
        if unknown:
            self._log(f"  ⚠ 有 {unknown} 行高亮但认不出名字，可能漏统计稀有改造石")
        self._close_result()
        return "ok", (success, total, lower, full)

    def _fail(self, msg: str) -> None:
        self._end("error", msg, msg)

    def _finish(self) -> None:
        with self._lock:
            items = self.status["items"]
            success = self.status["success"]
            batch = self.status["batch"]
            lower = self.status["lower"]
            full = self.status["full"]
        stone = f"，下级全改造石 {lower} 个，全改造石 {full} 个" if (lower or full) else ""
        if self._stop:
            self._end("stopped", f"已停止：处理 {batch} 批，提炼 {items} 件，成功 {success} 件{stone}")
        else:
            self._end("done", f"完成：处理 {batch} 批，提炼 {items} 件，成功 {success} 件{stone}")
