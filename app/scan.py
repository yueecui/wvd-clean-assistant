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
import threading
import time

from PIL import Image

import capture
import match
import notify
import parse
import perf
import rules

SCROLL_PX = 720          # 约 7 行：一屏 8 行，留 1 行重叠供高亮锚点定位
SCROLL_MS = 1100         # 距离加大后同步放慢拖动，避免惯性滚过头
TAP_WAIT = 0.45          # 点击后等详情刷新
SCROLL_WAIT = 1.15       # 滑动后等列表停稳


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
        self._thread: threading.Thread | None = None
        self._stop = False
        self._lock = threading.Lock()
        self.items: list[dict] = []
        self.logs: list[str] = []
        self._scanned: set[int] = set()
        self._anchor_idx = 0
        self.status = {"running": False, "phase": "idle", "scanned": 0,
                       "current": "", "error": None, "task": "",
                       "started_at": None, "finished_at": None}

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
        print("[scan]", msg)

    def snapshot(self) -> dict:
        with self._lock:
            return {"status": dict(self.status), "items": list(self.items),
                    "logs": self.logs[-60:]}

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
                           "started_at": ts, "finished_at": None}
        self._log(f"[{_clock(ts)}] 装备扫描开始")
        # 去重集合只对本次扫描有效：列表位置每次都变，沿用上次的会整屏跳过
        self._scanned = set()
        self._anchor_idx = 0
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
            # 不回列表顶部：直接从当前看到的列表位置开始（重复可接受）
            self._log("从当前列表位置开始扫描…" if not self.items
                      else f"续扫：已有 {len(self.items)} 件，从当前列表位置继续…")
            time.sleep(0.4)

            rows = self._read_rows()
            if not rows:
                self._fail("未识别到列表行：请确认游戏停在装备列表界面")
                return
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
            self._finish(f"扫描完成：{len(self.items)} 件")
        except Exception as e:  # noqa: BLE001
            self._fail(f"扫描异常: {e}")
        finally:
            perf.end_task()

    def _fail(self, msg: str) -> None:
        self._end("error", msg, msg)

    def _finish(self, msg: str) -> None:
        self._end("stopped" if self._stop else "done", "已停止" if self._stop else msg)

    def _end(self, phase: str, msg: str, error: str | None = None) -> None:
        ts = time.time()
        with self._lock:
            self.status.update({"running": False, "phase": phase, "error": error,
                                "current": "", "finished_at": ts})
            started = self.status.get("started_at") or ts
            task = self.status.get("task") or "装备扫描"
        total = _duration(ts - started)
        self._log(f"[{_clock(ts)}] {msg} · 总用时 {total}")
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
        with self._lock:
            # 已请求停止时不要覆盖「正在停止」提示
            if not self._stop:
                self.status["phase"] = "scanning"
            self.status["current"] = row["name"]
        t0 = time.time()
        self._tap(*row["tap"])
        self._anchor_idx = row["idx"]
        time.sleep(TAP_WAIT)
        t1 = time.time()
        png = self._png()
        t2 = time.time()
        detail = parse.parse_detail_only(png)
        t3 = time.time()
        if detail is None:
            self._log(f"✗ 「{row['name']}」详情解析失败，跳过")
            self._scanned.add(row["idx"])
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
            # 列表行与详情面板各有一处锁图标，任一命中即视为锁定
            "locked": detail["locked"] or row["locked"],
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
            "list_locked": row["locked"],
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
        self._scanned.add(row["idx"])
        if dup:
            self._log(f"↺ 「{item['name']}」与已有第 {dup} 条相同，跳过")
            return
        flag = {"ok": "✔", "alias": "✔*", "fuzzy": "?", "none": "✗"}.get(item["match_status"], "?")
        self._log(f"[{len(self.items)}] {flag} {item['name']}"
                  f"{'+%d' % item['reinforce'] if item['reinforce'] else ''} "
                  f"{'★' * item['stars'] or '无星'} "
                  f"{' / '.join(item['blessings']) if item['blessings'] else '无加护'}"
                  f"{' 🔒' if item['locked'] else ''}  {item['score']}分 ({t3 - t0:.1f}s)")

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
