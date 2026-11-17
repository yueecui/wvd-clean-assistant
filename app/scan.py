# -*- coding: utf-8 -*-
"""自动逐件扫描引擎。

思路：
  1. 逐行点击 → 读右侧详情（名称/星级/未锁加护/锁定）→ 记入结果。
  2. 一屏扫完 → 向上滑动 → 重新 OCR 列表。
  3. 滚动量不可控（swipe 有惯性）→ 用「选中行高亮」作视觉锚点：
     滚前点击最后一行（锚点），滚后检测高亮行落在第几行，即可反推每行的全局索引。
     锚点丢失时退回内容序列匹配。
  4. 全局索引去重，因此滚动多少都不会重复或漏扫。
"""
from __future__ import annotations

import io
import os
import queue
import sys
import threading
import time

from PIL import Image

import capture
import match
import notify
import parse
import perf
import rules
import runtime
import store

SCROLL_PX = 720          # 约 7 行：一屏 8 行，留 1 行重叠供高亮锚点定位
SCROLL_MS = 1100         # 距离加大后同步放慢拖动，避免惯性滚过头
TAP_WAIT = 0.45          # 点击后等详情刷新
SCROLL_WAIT = 1.15       # 滑动后等列表停稳

SAVE_EVERY = 20          # 扫描中途落盘：每新增 20 件存一次
SAVE_INTERVAL = 30.0     # 或者距上次落盘超过 30 秒（件数少时兜底）

# 流水线：主线程只做「点击 + 截图」，识图交给 OCR 线程，两者并行。
# 队列上限控制提前量（一张 PNG 约 1~2MB），满了主线程会等一下，不会堆爆内存。
# OCR 单线程消费：多线程能再快一点，但会打乱落库顺序、还要按倍数吃 CPU，
# 真正的瓶颈收益来自「截图不等识别」，所以先只做流水线不做并发识别。
QUEUE_MAX_DEFAULT = 4    # 队列上限默认值：越大越能提前截，越吃内存
QUEUE_MAX_MIN = 1
QUEUE_MAX_MAX = 8


def clamp_queue_max(value, default: int = QUEUE_MAX_DEFAULT) -> int:
    """队列上限只接受 1~8 的整数；非法值回默认，超界夹紧。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(QUEUE_MAX_MIN, min(n, QUEUE_MAX_MAX))


def _clock(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def _duration(seconds: float) -> str:
    n = max(0, int(seconds))
    h, m, s = n // 3600, (n // 60) % 60, n % 60
    if h:
        return f"{h}小时{m}分{s}秒"
    return f"{m}分{s}秒" if m else f"{s}秒"


class Scanner:
    def __init__(self, adb: str, serial: str):
        self.adb = adb
        self.serial = serial
        self.queue_max = QUEUE_MAX_DEFAULT   # OCR 队列上限（1~8），由界面配置
        self._thread: threading.Thread | None = None
        self._ocr_thread: threading.Thread | None = None
        self._q: queue.Queue | None = None
        self._stop = False
        self._lock = threading.Lock()
        self.items: list[dict] = []
        self.logs: list[str] = []
        self._scanned: set[int] = set()
        self._anchor_idx = 0
        self._file = ""            # 本次扫描的目标结果文件（中途落盘用）
        self._base_count = 0       # 开始扫描时已有的件数（用来算本次新增）
        self._saved_count = 0      # 上次落盘时的件数
        self._saved_at = 0.0       # 上次落盘时间
        self.status = {"running": False, "phase": "idle", "scanned": 0,
                       "current": "", "error": None, "task": "",
                       "started_at": None, "finished_at": None,
                       "elapsed": 0.0, "run_started_at": None, "per_item": None}

    # ---------- 设备 ----------
    def _png(self) -> bytes:
        return capture.screenshot(self.adb, self.serial)

    def _img(self) -> Image.Image:
        return Image.open(io.BytesIO(self._png())).convert("RGB")

    def _tap(self, x, y) -> None:
        capture.run_adb(self.adb, self.serial, "shell", "input", "tap",
                        str(int(x)), str(int(y)))

    def _swipe(self, x1, y1, x2, y2, ms) -> None:
        """精确拖动：按住→分步移动→停一下→抬起，避免惯性导致滚动量失控。"""
        if capture.drag(self.adb, self.serial, x1, y1, x2, y2,
                        steps=10, ms=max(300, int(ms * 0.7)), hold=0.25):
            return
        capture.run_adb(self.adb, self.serial, "shell", "input", "swipe",
                        str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(ms)))

    # ---------- 状态 ----------
    def _log(self, msg: str) -> None:
        with self._lock:
            self.logs.append(msg)
            if len(self.logs) > 200:
                self.logs = self.logs[-200:]
        try:
            print("[scan]", msg)
        except Exception:  # noqa: BLE001
            # 控制台编码不支持 ✔✗🔒 这类字符时不能让 OCR 线程直接崩掉
            try:
                enc = sys.stdout.encoding or "utf-8"
                print("[scan]", msg.encode(enc, "replace").decode(enc, "replace"))
            except Exception:  # noqa: BLE001
                pass

    def snapshot(self) -> dict:
        with self._lock:
            return {"status": dict(self.status), "items": list(self.items),
                    "logs": self.logs[-60:]}

    def _persist(self, force: bool = False) -> None:
        """扫描途中定期落盘：每 SAVE_EVERY 件或每 SAVE_INTERVAL 秒一次。

        以前只在扫完（或手动保存）时写盘，中途崩溃/断线整轮数据都没了。
        写盘统一用开始时的目标文件，扫描期间打开历史结果也不会写串。
        """
        with self._lock:
            n = len(self.items)
            if not n:
                return
            if not force and n == self._saved_count:
                return
            now = time.time()
            if (not force and n - self._saved_count < SAVE_EVERY
                    and now - self._saved_at < SAVE_INTERVAL):
                return
            snap = [dict(it) for it in self.items]  # 快照：写盘期间 items 还会增长
            name = self._file
            self._saved_count = n
            self._saved_at = now
        try:
            name = (store.save_results_as(name, snap) if name
                    else store.save_results(snap))
        except Exception as e:  # noqa: BLE001  落盘失败不能让扫描挂掉
            self._log(f"⚠ 中途保存失败：{e}")
            return
        self._file = name
        self._log(f"已保存 {len(snap)} 件 → {name}")

    # ---------- 主流程 ----------
    def start(self, base_items: list[dict] | None = None) -> dict:
        """base_items：累加模式时传入已有结果；None/空 = 全新扫描。"""
        if self._thread and self._thread.is_alive():
            return {"ok": False, "error": "扫描进行中"}
        self._stop = False
        base = list(base_items or [])
        # 累加模式：已有结果序号重排为 1..N，新扫到的接着往后编，避免 # 重复
        for n, it in enumerate(base, 1):
            it["idx"] = n
        ts = time.time()
        with self._lock:
            self.items = base
            self.logs = []
            self.status = {"running": True, "phase": "start", "scanned": len(base),
                           "current": "", "error": None, "task": "装备扫描",
                           "started_at": ts, "finished_at": None,
                           "elapsed": 0.0, "run_started_at": None, "per_item": None}
            runtime.begin(self.status, ts)
        self._log(f"[{_clock(ts)}] 装备扫描开始")
        # 去重集合只对本次扫描有效：列表位置每次都变，沿用上次的会整屏跳过
        self._scanned = set()
        self._anchor_idx = 0
        # 中途落盘固定写这个文件（避免扫描期间用户打开历史结果导致写串）
        self._file = store.current_file()
        self._base_count = len(base)   # 续扫时用来算「本次新增」
        self._saved_count = len(base)
        self._saved_at = ts
        # 流水线队列 + 常驻 OCR 线程（每轮扫描新建，跑完即退出）
        self.queue_max = clamp_queue_max(self.queue_max)
        self._q = queue.Queue(maxsize=self.queue_max)
        self._ocr_thread = threading.Thread(target=self._ocr_loop, args=(self._q,),
                                            name="wvd-ocr", daemon=True)
        self._ocr_thread.start()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return {"ok": True}

    def stop(self) -> dict:
        self._stop = True
        with self._lock:
            if self.status.get("running"):
                self.status.update({"phase": "stopping"})
        return {"ok": True}

    def _run(self) -> None:
        perf.begin_task()
        try:
            error: str | None = None
            try:
                error = self._scan_all()
            except Exception as e:  # noqa: BLE001
                error = f"扫描异常: {e}"
            # 先等 OCR 线程把队列里的图跑完，报完成时的件数才准、落盘也不缺尾巴
            self._drain()
            if error:
                self._fail(error)
            else:
                self._finish(f"扫描完成：{len(self.items)} 件")
        finally:
            perf.end_task()

    def _scan_all(self) -> str | None:
        """主循环：只负责「点击 + 截图」并丢给 OCR 线程；出错时返回错误信息。"""
        # 不回列表顶部：直接从当前看到的列表位置开始（重复可接受）
        self._log("从当前列表位置开始扫描…" if not self.items
                  else f"续扫：已有 {len(self.items)} 件，从当前列表位置继续…")
        self._log("流水线：截图与 OCR 并行，OCR 队列上限 %d" % self.queue_max)
        time.sleep(0.4)

        rows = self._read_rows()
        if not rows:
            return "未识别到列表行：请确认游戏停在装备列表界面"
        self._assign_first(rows)
        self._log(f"识别到 {len(rows)} 行（{rows[0]['name']} … {rows[-1]['name']}）")

        while not self._stop:
            pending = [r for r in rows if r["idx"] not in self._scanned]
            if pending:
                self._scan_row(pending[0])
                perf.idle_sleep()
                continue
            nxt = self._scroll_forward(rows)
            if nxt is None:
                self._log(f"已到列表末尾，共 {len(self.items)} 件")
                break
            rows = nxt
        return None

    def _fail(self, msg: str) -> None:
        self._end("error", msg, msg)

    def _finish(self, msg: str) -> None:
        self._end("stopped" if self._stop else "done", "已停止" if self._stop else msg)

    def _end(self, phase: str, msg: str, error: str | None = None) -> None:
        ts = time.time()
        with self._lock:
            self.status.update({"running": False, "phase": phase, "error": error,
                                "current": "", "finished_at": ts})
            elapsed = runtime.end(self.status, ts)     # 只算真正在跑的时间
            task = self.status.get("task") or "装备扫描"
            count = len(self.items)
        added = max(0, count - self._base_count)
        per_sec = elapsed / added if added else None
        per = f"{per_sec:.1f} 秒/件" if per_sec else "-"
        total = _duration(elapsed)
        with self._lock:
            self.status["per_item"] = round(per_sec, 2) if per_sec else None
        self._log(f"[{_clock(ts)}] {msg} · 运行 {total}")
        self._log(f"[{_clock(ts)}] 本次新增 {added} 件（累计 {count} 件）· 平均 {per}")
        self._persist(force=True)  # 结束/异常时兜底落盘，浏览器关掉也不丢
        notify.task_finished(task, phase, msg, total)

    def apply_alias(self, raw: str) -> int:
        """用户校准后，把已扫结果里同名条目重新匹配并重算分。"""
        key = match.split_reinforce(raw or "")[0]
        n = 0
        with self._lock:
            for it in self.items:
                if match.split_reinforce(it.get("raw_name") or "")[0] != key:
                    continue
                m = match.match(it.get("raw_name") or "")
                it.update({
                    "name": m["name"], "reinforce": m["reinforce"],
                    "equipment_id": m["id"], "icon": m["icon"], "rank": m["rank"],
                    "kind": m["kind"], "type_name": m["type_name"], "part": m["part"],
                    "is_special": m["is_special"],
                    "match_status": m["status"], "candidates": m["candidates"],
                })
                n += 1
            rules.apply(self.items)
        if n:
            self._log(f"已按校准映射更新 {n} 条「{key}」")
        return n

    # ---------- 步骤 ----------
    def _read_rows(self) -> list[dict]:
        return parse.parse_rows(self._png())

    def _ensure_top(self) -> None:
        """手指下滑（内容下移）直到列表不再变化 → 已在顶部。"""
        prev = None
        for _ in range(6):
            self._swipe(150, 400, 150, 1100, 500)
            time.sleep(0.9)
            img = self._img()
            sig = self._screen_sig(img)
            if prev is not None and abs(sig - prev) < 0.3:
                break
            prev = sig
        time.sleep(0.3)

    @staticmethod
    def _screen_sig(img: Image.Image) -> float:
        a = parse._arr(img, 30, 290, 300, 1180)
        return float(a.mean()) if a is not None else 0.0

    def _assign_first(self, rows: list[dict]) -> None:
        hl = self._hl_pos(rows)
        base = -(hl if hl is not None else 0)
        for i, r in enumerate(rows):
            r["idx"] = base + i
        self._anchor_idx = rows[-1]["idx"] if rows else 0

    def _hl_pos(self, rows: list[dict]) -> int | None:
        vals = [(r.get("hl", 0.0), i) for i, r in enumerate(rows)]
        if not vals:
            return None
        v, i = max(vals)
        return i if v > 10 else None

    def _scan_row(self, row: dict) -> None:
        """流水线生产端：只做点击 + 截图，不等识别，图直接排进 OCR 队列。"""
        with self._lock:
            # 已请求停止时不要覆盖「正在停止」提示
            if not self._stop:
                self.status["phase"] = "scanning"
            self.status["current"] = row["name"]
        t0 = time.time()
        self._tap(*row["tap"])
        self._anchor_idx = row["idx"]
        time.sleep(TAP_WAIT)
        png = self._png()
        with self._lock:
            self._scanned.add(row["idx"])   # 图已到手：这行算扫过了，别再点一次
        q = self._q
        if q is None:
            return
        q.put((row, png, t0))               # 队列满时在这里等，限制提前量

    # ---------- OCR 消费端 ----------
    def _ocr_loop(self, q: queue.Queue) -> None:
        """单线程按入队顺序识别 → 保证落库顺序与列表顺序一致。"""
        while True:
            task = q.get()
            if task is None:
                return
            row, png, t0 = task
            try:
                self._commit_detail(row, png, t0)
            except Exception as e:  # noqa: BLE001  单件出错不能让线程死掉
                self._log(f"✗ 「{row.get('name')}」识别异常：{e}")

    def _drain(self) -> None:
        """让 OCR 线程把队列跑完再收工（否则最后几件会丢）。"""
        q, t = self._q, self._ocr_thread
        self._q = None
        self._ocr_thread = None
        if q is None or t is None:
            return
        for _ in range(int(getattr(q, "maxsize", 1) or 1) + 2):
            if not t.is_alive():      # 线程已挂（不该发生）：别再干等
                return
            try:
                q.put(None, timeout=1)
                break
            except queue.Full:
                continue
        t.join(timeout=180)

    def _commit_detail(self, row: dict, png: bytes, t0: float) -> None:
        """消费端：OCR 详情 → 建条目 → 去重 → 打分 → 落盘。"""
        t2 = time.time()
        detail = parse.parse_detail_only(png)
        t3 = time.time()
        if detail is None:
            self._log(f"✗ 「{row['name']}」详情解析失败，跳过")
            return
        raw_name = detail["name"] if len(detail["name"]) >= len(row["name"]) else row["name"]
        m = match.match(raw_name)
        item = {
            "idx": 0,               # 展示序号，追加时按顺序连续编号
            "pos": row["idx"],      # 列表中的位置（调试用，不参与续扫去重）
            "raw_name": raw_name,
            "name": m["name"],
            "reinforce": m["reinforce"],
            "stars": detail["stars"],
            "blessings": detail["blessings"],
            # 锁定只看详情面板（名字下方的米黄挂锁）：列表行图标配色杂，
            # 用列表锁图标判断容易把某些花哨图标误判成锁定
            "locked": detail["locked"],
            # 品质色（白/绿/蓝/紫/红）：优先详情名，退回列表行名
            "color": detail.get("color") or row.get("color") or "",
            "equipment_id": m["id"],
            "icon": m["icon"],
            "rank": m["rank"],
            "kind": m["kind"],
            "type_name": m["type_name"],
            "part": m["part"],
            "is_special": m["is_special"],
            "match_status": m["status"],
            "candidates": m["candidates"],
            "list_stars": row["stars"],
            "list_badge": row["badge"],
        }
        if detail["name"] != row["name"]:
            self._log(f"⚠ 名称不一致：列表「{row['name']}」/ 详情「{detail['name']}」")
        # 续扫/滚动重叠时同一件会被再读一次：名称+强化+星级+加护 全同即视为重复
        sig = (item["name"], item["reinforce"], item["stars"], tuple(item["blessings"]))
        dup = 0
        with self._lock:
            for i, old in enumerate(self.items, 1):
                if ((old.get("name"), old.get("reinforce") or 0, old.get("stars"),
                     tuple(old.get("blessings") or [])) == sig):
                    dup = i
                    break
            if not dup:
                item["idx"] = len(self.items) + 1
                self.items.append(item)
                rules.apply_one(item, self.items)
                self.status["scanned"] = len(self.items)
        if dup:
            self._log(f"↺ 「{item['name']}」与已有第 {dup} 条相同，跳过")
            return
        flag = {"ok": "✔", "alias": "✔*", "fuzzy": "?", "none": "✗"}.get(item["match_status"], "?")
        self._log(f"[{len(self.items)}] {flag} {item['name']}"
                  f"{'+%d' % item['reinforce'] if item['reinforce'] else ''} "
                  f"{'★' * item['stars'] or '无星'} "
                  f"{' / '.join(item['blessings']) if item['blessings'] else '无加护'}"
                  f"{' 🔒' if item['locked'] else ''}  {item['score']}分"
                  f" (OCR {t3 - t2:.1f}s / 共 {t3 - t0:.1f}s)")
        self._persist()

    def _scroll_forward(self, rows: list[dict]) -> list[dict] | None:
        """滚动一屏；返回新行（含全局索引），到底返回 None。"""
        if not rows:
            return None
        # 用最后一行做锚点，滚动后它仍在视野内
        if self._anchor_idx != rows[-1]["idx"]:
            self._tap(*rows[-1]["tap"])
            self._anchor_idx = rows[-1]["idx"]
            time.sleep(TAP_WAIT)

        before = [(r["y"], r["name"], r["stars"], r["badge"], r["locked"]) for r in rows]
        new_rows: list[dict] = []
        for attempt in range(2):
            self._swipe(150, 1000, 150, 1000 - SCROLL_PX, SCROLL_MS)  # 手指上移 → 看后面的物品
            time.sleep(SCROLL_WAIT)
            new_rows = self._read_rows()
            if not new_rows:
                time.sleep(0.6)       # 画面还没刷出来，再试一次
                continue
            after = [(r["y"], r["name"], r["stars"], r["badge"], r["locked"]) for r in new_rows]
            if after != before:
                break
            time.sleep(0.6)           # 滑动没生效（还没到列表/卡顿），再滚一次
        else:
            self._log("列表没有滚动，判定已到底")
            return None

        hl = self._hl_pos(new_rows)
        if hl is not None:
            base = self._anchor_idx - hl
        else:
            base = self._match_base(rows, new_rows)
            self._log("锚点丢失，改用内容匹配定位")
        for i, r in enumerate(new_rows):
            r["idx"] = base + i
        return new_rows

    def _match_base(self, old_rows: list[dict], new_rows: list[dict]) -> int:
        known = {r["idx"]: (r["name"], r["stars"], r["badge"], r["locked"]) for r in old_rows}
        best_base, best_score = self._anchor_idx, -1
        for base in range(self._anchor_idx - len(new_rows), self._anchor_idx + 2):
            score = sum(1 for i, r in enumerate(new_rows)
                        if known.get(base + i) == (r["name"], r["stars"], r["badge"], r["locked"]))
            if score > best_score:
                best_score, best_base = score, base
        return best_base
