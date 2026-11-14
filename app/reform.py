# -*- coding: utf-8 -*-
"""装备改造界面（铁匠铺 → 装备改造）的解析。

与「装备强化」界面的差异（900x1600 实测）：
  列表：名字 x 100~330，y 330~1310，行距约 117；星级在名字左侧 x 20~100。
  详情：名称 y≈380（x>420），属性表 y 540~880，◆附加加护 y≈905，加护行 y≈946，
        强度上限 y≈1197。
  改造页：4 个加护槽（绿装只占第 1 个，y≈548），素材一览 y 880 起，行距约 97。
"""
from __future__ import annotations

import io
import re
import time

import numpy as np
from PIL import Image

import parse
import perf

# ---------- 区域常量（按 900x1600 设计，其余分辨率按比例换算） ----------
BASE_W, BASE_H = 900, 1600

LIST_X = (100, 330)
LIST_Y = (330, 1310)
DETAIL_X = (420, 900)
SLOT_Y = (450, 545)          # 改造页第 1 个加护槽（实测 y≈475）
MAT_Y = (880, 1470)          # 素材一览

_SKIP = {"仓库", "持有一览", "附加加护", "强度上限", "详细", "决定", "改造",
         "获取概率", "素材一览", "ALL", "Blacksmith", "装备改造"}
# 素材名：属性+1~3x24（固定值） / 命中+1~3%x82（百分比）
_MAT_RE = re.compile(
    r"^(?P<attr>[^\d+]+)\+(?P<lo>\d+)~(?P<hi>\d+)(?P<pct>%)?\s*x\s*(?P<n>\d+)$")
_SLOT_RE = re.compile(r"^(?P<attr>[\u4e00-\u9fa5]{2,8})\+(?P<num>\d+)(?P<pct>%)?$")

# 数值表来自 masterdata/EquipmentEffectUpgrade：每种属性 5 档，rarity=1..5，
# 数值越高等级越高。下面是与解包数据一致的内置副本，仅在绿色版没带 masterdata 时兜底。
_PCT_SEQ = [(1, 2), (1, 3), (2, 4), (3, 5), (4, 6)]
_FLAT_SEQ = [(1, 3), (2, 4), (3, 5), (4, 6), (5, 7)]
_FLAT_SPECIAL_SEQ = [(1, 2), (2, 3), (3, 4), (3, 5), (4, 6)]
FALLBACK_GRADE_TABLE = {
    "flat": {"*": _FLAT_SEQ, "会心": _FLAT_SPECIAL_SEQ, "行动速度": _FLAT_SPECIAL_SEQ},
    "pct": {"*": _PCT_SEQ},
}
# OCR 常见的属性名错字 / 截断
_ATTRS = ["攻击力", "魔力", "神力", "抵抗", "行动速度", "命中",
          "防御力", "法术防御力", "会心", "会心回避", "回避"]


_ATTR_ALIAS = {"攻击": "攻击力", "魔刀": "魔力", "神刀": "神力",
               "法术防御": "法术防御力", "法防": "法术防御力"}


def canon_attr(s: str) -> str:
    import difflib
    s = s.replace(" ", "")
    if s in _ATTRS:
        return s
    if s in _ATTR_ALIAS:
        return _ATTR_ALIAS[s]
    hit = difflib.get_close_matches(s, _ATTRS, 1, cutoff=0.5)
    return hit[0] if hit else s


def fix_mat_text(t: str) -> str:
    """补 OCR 常见缺字：攻击+1~324 → 攻击+1~3x24；魔力+12%x30 → 魔力+1~2%x30。"""
    m = re.match(r"^(?P<attr>[^\d+]+)\+(?P<lo>\d+)~(?P<tail>\d+)(?P<pct>%)?$", t)
    if m:
        tail = m.group("tail")
        for hi in range(1, 10):
            s = str(hi)
            if tail.startswith(s) and len(tail) > len(s):
                return f"{m.group('attr')}+{m.group('lo')}~{hi}{m.group('pct') or ''}x{tail[len(s):]}"
    m = re.match(r"^(?P<attr>[^\d+]+)\+(?P<d>\d{2})(?P<pct>%)?x(?P<n>\d+)$", t)
    if m:
        d = m.group("d")
        return f"{m.group('attr')}+{d[0]}~{d[1]}{m.group('pct') or ''}x{m.group('n')}"
    return t


_GRADE_TAB: dict | None = None


def grade_table() -> dict:
    """优先按 masterdata 动态生成，缺失时回落到内置表；"*" 用于未知属性名。"""
    global _GRADE_TAB
    if _GRADE_TAB is None:
        tab = None
        try:
            import master
            dyn = master.upgrade_grades()
            if dyn["flat"] and dyn["pct"]:
                tab = {unit: dict(dyn[unit]) for unit in ("flat", "pct")}
        except Exception:
            pass
        if tab is None:
            tab = {unit: dict(FALLBACK_GRADE_TABLE[unit]) for unit in ("flat", "pct")}
        for unit in ("flat", "pct"):
            tab[unit].setdefault("*", FALLBACK_GRADE_TABLE[unit]["*"])
        _GRADE_TAB = tab
    return _GRADE_TAB


def grade_of(attr: str, lo: int, hi: int, pct: bool) -> int | None:
    """按数值表反推 1~5 星（数值越高等级越高）；对不上返回 None，绝不猜等级。"""
    tab = grade_table()["pct" if pct else "flat"]
    seq = tab.get(attr) or tab["*"]
    for i, pair in enumerate(seq, 1):
        if pair == (lo, hi):
            return i
    return None


def stone_key(attr: str, lo: int, hi: int, pct: bool) -> str:
    return f"{attr}+{lo}~{hi}{'%' if pct else ''}"


def _stone_id(s: dict) -> str:
    return s.get("key") or stone_key(s["attr"], s["lo"], s["hi"], bool(s.get("pct")))


def stone_grid() -> list[dict]:
    """前端持有素材表的骨架：每个属性（固定值 / 百分比）× 1~5★ 的数值区间。

    有了骨架，初次使用不需要先扫描也能直接挑改造石。
    """
    tab = grade_table()
    out = []
    for unit in ("flat", "pct"):
        pct = unit == "pct"
        for attr, seq in tab[unit].items():
            if attr == "*":
                continue
            out.append({
                "attr": attr, "pct": pct, "label": attr + ("%" if pct else ""),
                "cells": [{"grade": g, "lo": lo, "hi": hi,
                           "key": stone_key(attr, lo, hi, pct)}
                          for g, (lo, hi) in enumerate(seq, 1)],
            })
    out.sort(key=lambda x: (x["attr"], x["pct"]))
    return out


def refresh_stones(raw: list[dict]) -> list[dict]:
    """按当前数值表重算每块石头的星级，并统一 key/text（配置可能来自旧版本）。"""
    out = []
    for s in raw or []:
        try:
            attr = str(s.get("attr") or "")
            lo, hi = int(s["lo"]), int(s["hi"])
            pct, count = bool(s.get("pct")), int(s.get("count") or 0)
        except (KeyError, TypeError, ValueError):
            out.append({**s, "grade": None})
            continue
        key = stone_key(attr, lo, hi, pct)
        out.append({**s, "attr": attr, "lo": lo, "hi": hi, "pct": pct,
                    "count": count, "grade": grade_of(attr, lo, hi, pct),
                    "key": key, "text": f"{key}x{count}"})
    return out


UNKNOWN_STOCK = 9999   # 未扫描素材时的占位库存，执行中按游戏内实际列表收敛


def normalize_stones(raw: list[dict]) -> tuple[list[dict], list[str]]:
    """执行前过滤：只留 1★/2★，返回 (可用石头, 被排除的说明)。

    unscanned=True 表示没扫过素材、数量未知：给占位库存，真正数量在执行改造
    拉动素材列表时由 _record_materials 回填；石头不存在则整轮拉完后置 0。
    """
    ok, blocked = [], []
    for s in refresh_stones(raw):
        count = int(s.get("count") or 0)
        unscanned = bool(s.get("unscanned"))
        if count <= 0 and not unscanned:
            continue
        if s.get("grade") not in (1, 2):
            blocked.append(f"{s.get('key') or s.get('text') or '?'}"
                           f"({s.get('grade') or '无法判定'}★)")
            continue
        s = dict(s)
        if unscanned:
            s["count"] = UNKNOWN_STOCK
            s["text"] = f"{s['key']}x?"
        ok.append(s)
    return ok, blocked


def _scale(img: Image.Image) -> tuple[float, float]:
    return img.width / BASE_W, img.height / BASE_H


def _box(img: Image.Image, x0, y0, x1, y1) -> tuple[int, int, int, int]:
    sx, sy = _scale(img)
    return (int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy))


def _open(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


# ---------- 改造列表 ----------
def parse_rows(png: bytes) -> list[dict]:
    """左侧持有一览：名称 / 星级 / 品质色 / 点击坐标。"""
    img = _open(png)
    lines = parse.ocr_lines(img, _box(img, 30, 330, 340, 1310))
    sx, sy = _scale(img)
    names = [l for l in sorted(lines, key=lambda x: x["y"])
             if l["text"] not in _SKIP
             and "一览" not in l["text"]
             and not re.fullmatch(r"[★☆*0-9①iI]+", l["text"])
             and len(l["text"]) >= 2 and l["score"] > 0.35]
    rows, last_y = [], -999
    for n in names:
        if n["y"] - last_y < 55 * sy:
            continue
        ny = n["y"]
        last_y = ny
        x0, y0, x1, y1 = _box(img, 20, 0, 100, 0)
        rows.append({
            "name": n["text"].replace(" ", ""),
            "stars": len(parse.white_clusters(img, int(20 * sx), int(ny + 35 * sy),
                                              int(100 * sx), int(ny + 80 * sy))),
            "color": parse.name_color(img, [n["x"], n["y"], n["w"], n["h"]]),
            "y": ny,
            "tap": [int(n["x"] + 60 * sx), int(ny + 14 * sy)],
        })
    return rows


def parse_detail(png: bytes) -> dict | None:
    """右侧详情：名称 / 星级 / 唯一加护 / 强度上限。"""
    img = _open(png)
    sx, sy = _scale(img)
    lines = parse.ocr_lines(img, _box(img, 420, 330, 900, 1260))
    if not lines:
        return None
    right = sorted(lines, key=lambda x: x["y"])
    name = next((l for l in right if l["y"] < 430 * sy and l["text"] not in _SKIP
                 and l["score"] > 0.5), None)
    if name is None:
        return None
    hdr = next((l for l in right if "附加加护" in l["text"]), None)
    blessing = ""
    if hdr:
        for l in right:
            if l["y"] <= hdr["y"] + hdr["h"]:
                continue
            if "解锁" in l["text"] or "强度上限" in l["text"]:
                break
            if _SLOT_RE.match(l["text"].replace(" ", "")):
                blessing = l["text"].replace(" ", "")
                break
    limit = ""
    lim = next((l for l in right if "强度上限" in l["text"]), None)
    if lim:
        nxt = next((l for l in right if l["y"] > lim["y"] - 10 and re.match(r"^\d+\s*/\s*\d+$",
                                                                           l["text"].replace(" ", ""))), None)
        limit = nxt["text"].replace(" ", "") if nxt else ""
    return {
        "name": name["text"].replace(" ", ""),
        "color": parse.name_color(img, [name["x"], name["y"], name["w"], name["h"]]),
        "stars": len(parse.white_clusters(img, int(name["x"] - 5 * sx), int(name["y"] + name["h"] + 5 * sy),
                                          int(name["x"] + 300 * sx), int(name["y"] + name["h"] + 55 * sy))),
        "blessing": blessing,
        "limit": limit,
    }


# ---------- 改造页：素材一览 ----------
def parse_materials(png: bytes) -> list[dict]:
    """素材列表可见行：[{text, attr, lo, hi, count, y, tap}]。"""
    img = _open(png)
    sx, sy = _scale(img)
    lines = parse.ocr_lines(img, _box(img, 40, 880, 860, 1470))
    out = []
    for l in sorted(lines, key=lambda x: x["y"]):
        t = l["text"].replace(" ", "").replace("～", "~")
        m = _MAT_RE.match(t)
        if not m:
            m = _MAT_RE.match(fix_mat_text(t))
        if not m:
            continue
        attr = canon_attr(m.group("attr"))
        lo, hi = int(m.group("lo")), int(m.group("hi"))
        pct = bool(m.group("pct"))
        count = int(m.group("n"))
        key = stone_key(attr, lo, hi, pct)
        out.append({
            "text": f"{key}x{count}",
            "key": key,
            "attr": attr,
            "lo": lo, "hi": hi, "pct": pct,
            "grade": grade_of(attr, lo, hi, pct),
            "count": count,
            "y": l["y"],
            # 行中心 ≈ 名称下方 +30（"仓库"那行的高度中点）
            "tap": [int(l["x"] + 100 * sx), int(l["y"] + 30 * sy)],
        })
    return out


def parse_slot(png: bytes) -> dict:
    """改造页第 1 个加护槽：{'before': 原属性, 'after': 目标区间文本}。

    未选素材时只有原属性（居中）；选中后左半是原属性、右半是目标区间，
    中间的 ▶ 箭头 OCR 经常读不出来，所以按 x 坐标区分。
    """
    img = _open(png)
    sy = _scale(img)[1]
    # 必须整图 OCR：裁剪成小条后 RapidOCR 会把左右两段并成一行
    lines = [l for l in parse.ocr_lines(img)
             if SLOT_Y[0] * sy <= l["y"] <= SLOT_Y[1] * sy and l["x"] < img.width * 0.95]
    lines = sorted(lines, key=lambda x: x["x"])
    texts = [_norm(l["text"]) for l in lines]
    mid = img.width * 0.45
    before, after = "", ""
    for l, t in zip(lines, texts):
        if "~" in t and l["x"] >= mid:
            after = t
        elif not before and _SLOT_RE.match(t) and l["x"] < mid:
            before = t
    if not after and len(texts) >= 2:
        after = texts[-1]
    return {"raw": "".join(texts), "before": before, "after": after, "texts": texts}


def parse_slot_after(png: bytes) -> tuple[str, int]:
    """改造完成后的槽位：返回 (属性, 数值)。"""
    img = _open(png)
    sy = _scale(img)[1]
    lines = [l for l in parse.ocr_lines(img)
             if SLOT_Y[0] * sy <= l["y"] <= SLOT_Y[1] * sy]
    for l in sorted(lines, key=lambda x: x["x"]):
        t = l["text"].replace(" ", "")
        m = _SLOT_RE.match(t)
        if m:
            return m.group("attr") + ("%" if m.group("pct") else ""), int(m.group("num"))
    return "", 0


def is_selected(png: bytes) -> bool:
    """槽位是否已经出现「▶ 目标」预览（= 素材已选中、可以点改造）。"""
    s = parse_slot(png)
    return bool(s["after"])


def green_count(rows: list[dict]) -> int:
    return sum(1 for r in rows if r["color"] == "green")


def page_kind(png: bytes) -> str:
    """判断当前是「改造列表」还是「改造页」（两个界面的底部按钮坐标几乎重合，
    必须先判页面，否则会把列表页的『决定』点到改造页的『改造』上）。"""
    img = _open(png)
    lines = parse.ocr_lines(img, _box(img, 0, 200, 900, 380))
    t = "".join(l["text"] for l in lines)
    if "想要变更" in t or "请选择" in t:
        return "reform"
    if "持有一览" in t or "使用专属道具" in t:
        return "list"
    return "unknown"


def has_result_layer(png: bytes) -> bool:
    """改造完成后的结果层（点击后关闭）。"""
    img = _open(png)
    lines = parse.ocr_lines(img, _box(img, 150, 600, 750, 1200))
    return any("点击后关闭" in l["text"] or "已更改" in l["text"] for l in lines)


# ---------- 界面坐标（按 900x1600 比例） ----------
def _pct(x: float, y: float, img: Image.Image) -> tuple[int, int]:
    return int(img.width * x), int(img.height * y)


BTN_DECIDE = (0.497, 0.929)      # 改造列表底部「决定」
BTN_BACK = (0.066, 0.929)        # 改造页左下返回箭头
BTN_REFORM = (0.512, 0.938)      # 改造页底部「改造」
RESULT_CLOSE = (0.50, 0.669)     # 改造结果层「点击后关闭」

TAP_WAIT = 0.5
PAGE_WAIT = 1.6
ANIM_WAIT = 2.6


def _norm(s: str) -> str:
    return s.replace(" ", "").replace("～", "~").replace("−", "-").replace("＋", "+")


def _row_key(r: dict) -> tuple:
    """装备行身份：名称 + 星级 + 品质色（改造不会改变这三项）。"""
    return (r.get("name") or "", r.get("stars"), r.get("color") or "")


def clock_text(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def duration_text(seconds: float) -> str:
    n = max(0, int(seconds))
    h, m, s = n // 3600, (n // 60) % 60, n % 60
    if h:
        return f"{h}小时{m}分{s}秒"
    return f"{m}分{s}秒" if m else f"{s}秒"


class Reformer:
    """装备改造：扫描素材、逐件把不需要的加护改成目标属性。"""

    def __init__(self, adb: str, serial: str):
        import threading

        self.adb = adb
        self.serial = serial
        self._thread = None
        self._stop = False
        self._lock = threading.Lock()
        self._stones: list[dict] = []
        self._targets: list[str] = []   # 需要改造的属性（勾选才会改）
        self._stock: dict[str, int] = {}
        self._max_try = 2
        self.logs: list[str] = []
        self.results: list[dict] = []
        self.status = {"running": False, "phase": "idle", "total": 0, "done": 0,
                       "current": "", "error": None, "task": "",
                       "started_at": None, "finished_at": None}

    # ---------- 基础 ----------
    def _png(self) -> bytes:
        import capture
        return capture.screenshot(self.adb, self.serial)

    def _img(self) -> Image.Image:
        return _open(self._png())

    def _tap(self, xy: tuple[int, int]) -> None:
        import capture
        capture.tap(self.adb, self.serial, *xy)

    def _long(self, xy: tuple[int, int], ms: int = 400) -> None:
        import capture
        capture.long_press(self.adb, self.serial, *xy, ms=ms)

    def _drag(self, x1, y1, x2, y2, ms=500, steps=10, hold=0.25) -> None:
        import capture
        if not capture.drag(self.adb, self.serial, x1, y1, x2, y2,
                            steps=steps, ms=ms, hold=hold):
            capture.run_adb(self.adb, self.serial, "shell", "input", "swipe",
                            str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(ms))

    def _log(self, msg: str) -> None:
        with self._lock:
            self.logs.append(msg)
            if len(self.logs) > 200:
                self.logs = self.logs[-200:]
        print("[reform]", msg)

    def snapshot(self) -> dict:
        with self._lock:
            return {"status": dict(self.status), "logs": list(self.logs[-60:]),
                    "results": list(self.results)}

    def stop(self) -> dict:
        self._stop = True
        with self._lock:
            if self.status.get("running"):
                scanning = str(self.status.get("phase") or "").startswith("scan")
                self.status["phase"] = "scan_stopping" if scanning else "stopping"
        return {"ok": True}

    # ---------- 任务计时 ----------
    def _begin(self, task: str, phase: str, current: str = "") -> None:
        perf.begin_task()
        ts = time.time()
        with self._lock:
            self.logs = []
            self.status = {"running": True, "phase": phase, "total": 0, "done": 0,
                           "current": current, "error": None, "task": task,
                           "started_at": ts, "finished_at": None}
        self._log(f"[{clock_text(ts)}] {task}开始")

    def _end(self, phase: str, msg: str, error: str | None = None) -> None:
        import notify

        perf.end_task()
        ts = time.time()
        with self._lock:
            self.status.update({"running": False, "phase": phase, "current": "",
                                "finished_at": ts, "error": error})
            started = self.status.get("started_at") or ts
            task = self.status.get("task") or "任务"
        total = duration_text(ts - started)
        self._log(f"[{clock_text(ts)}] {msg} · 总用时 {total}")
        notify.task_finished(task, phase, msg, total)

    # ---------- 页面操作 ----------
    def _page(self) -> str:
        return page_kind(self._png())

    def _ensure_list(self) -> bool:
        """回到改造列表；认不出页面时不做任何点击（避免误触改造按钮）。"""
        for _ in range(3):
            kind = self._page()
            if kind == "list":
                return True
            if kind == "unknown":
                self._log("⚠ 页面无法识别，停止操作")
                return False
            if has_result_layer(self._png()):
                img = self._img()
                self._tap(_pct(*RESULT_CLOSE, img))
                time.sleep(1.0)
                continue
            img = self._img()
            self._tap(_pct(*BTN_BACK, img))
            time.sleep(PAGE_WAIT)
        return self._page() == "list"

    def _open_reform_page(self, row: dict) -> bool:
        """从改造列表点开某件装备，进入改造页。"""
        if not self._ensure_list():
            return False
        self._tap((int(row["tap"][0]), int(row["tap"][1])))
        time.sleep(TAP_WAIT)
        if self._page() != "list":
            self._log("⚠ 点行后不在列表页，放弃")
            return False
        img = self._img()
        self._tap(_pct(*BTN_DECIDE, img))
        time.sleep(PAGE_WAIT)
        return self._page() == "reform" and bool(parse_materials(self._png()))

    def _back_to_list(self) -> None:
        if self._page() == "reform":
            img = self._img()
            self._tap(_pct(*BTN_BACK, img))
            time.sleep(PAGE_WAIT)
        elif has_result_layer(self._png()):
            img = self._img()
            self._tap(_pct(*RESULT_CLOSE, img))
            time.sleep(1.0)

    def _scroll_materials(self) -> None:
        """一次拉一整页（约 5 行 / 500px）：必须慢速分步，快拖会被游戏忽略。"""
        if self._stop:
            return
        img = self._img()
        x = int(img.width * 0.5)
        self._drag(x, int(img.height * 0.86), x, int(img.height * 0.5475),
                   ms=1500, steps=25, hold=0.30)
        time.sleep(0.7)

    def _top_materials(self) -> None:
        img = self._img()
        x = int(img.width * 0.5)
        for _ in range(12):
            if self._stop:
                return
            before = [m["text"] for m in parse_materials(self._png())]
            self._drag(x, int(img.height * 0.5475), x, int(img.height * 0.86),
                       ms=1500, steps=25, hold=0.30)
            time.sleep(0.7)
            if [m["text"] for m in parse_materials(self._png())] == before:
                break

    # ---------- 素材扫描（后台任务，可停止） ----------
    def start_scan_materials(self, mode: str = "full") -> dict:
        """启动素材扫描线程；结果由 _scan_run 直接落盘，前端轮询 status。"""
        import threading

        if self._thread and self._thread.is_alive():
            return {"ok": False, "error": "已有任务在运行（扫描素材或改造）"}
        mode = "flat" if mode == "flat" else "full"
        self._stop = False
        self._begin("素材扫描", "scan", "准备扫描素材")
        self._thread = threading.Thread(target=self._scan_run, args=(mode,), daemon=True)
        self._thread.start()
        return {"ok": True}

    def _scan_run(self, mode: str) -> None:
        try:
            # 落盘由 _scan_materials 每屏执行，扫描过程中前端就能看到结果
            res = self._scan_materials(mode)
            if not res["ok"]:
                self._fail(res["error"])
                return
            items = res["materials"]
            with self._lock:
                self.status["done"] = len(items)
            tag = "（已停止，只保存已扫到的部分）" if self._stop else ""
            self._finish_scan(f"素材扫描{tag}完成：{len(items)} 种，已保存")
        except Exception as e:  # noqa: BLE001
            self._fail(f"素材扫描异常: {e}")

    def _finish_scan(self, msg: str) -> None:
        self._end("stopped" if self._stop else "done", msg)

    @staticmethod
    def _merge_scan_items(seen: dict, mode: str, base: list) -> list[dict]:
        """增量更新：只覆盖本次扫到的 key，没扫到的旧数据保留。"""
        idx = {m["key"]: dict(m) for m in (base or []) if m.get("key")}
        for k, m in seen.items():
            if mode == "flat" and m["pct"]:
                continue
            idx[k] = dict(m)
        return sorted(idx.values(), key=lambda x: (x.get("attr") or "",
                                                  bool(x.get("pct")), x.get("lo") or 0))

    def _scan_materials(self, mode: str) -> dict:
        """扫描持有素材。

        已在改造页：以用户当前的滚动位置为起点，不回顶部、不返回装备列表，
                    结果按 key 增量更新到已保存的素材表。
        在持有一览：自动进入改造页并回到素材顶部做全量刷新（结果替换）。
        mode=flat：固定值排在列表前半，扫到第一个 '%' 石头就停，只更新固定值。
        """
        import store

        png = self._png()
        if has_result_layer(png):
            self._tap(_pct(*RESULT_CLOSE, self._img()))
            time.sleep(1.0)
            png = self._png()
        # 素材一览（属性+1~3x数量）只有改造页才有，比顶部文案可靠：
        # 改造页 OCR 偶尔会一起读出「持有一览」，按文案判断会误判成列表页而点返回箭头。
        mats_now = parse_materials(png)
        kind = "reform" if mats_now else page_kind(png)
        from_list = False
        if mats_now or kind == "reform":
            self._log(f"已在改造页（可见素材 {len(mats_now)} 行）：从当前位置开始更新，"
                      "不回顶部、不返回装备列表")
        elif kind == "list":
            from_list = True
            rows = parse_rows(png)
            if not rows:
                return {"ok": False, "error": "没识别到改造列表，请先停在「装备改造」的持有一览界面"}
            self._log(f"在持有一览：进入改造页（{rows[0]['name']}）做全量扫描…")
            if not self._open_reform_page(rows[0]):
                self._back_to_list()
                return {"ok": False, "error": "进入改造页失败：未识别到素材列表"}
        else:
            # 认不出页面时宁可报错，绝不乱点返回/决定按钮
            return {"ok": False, "error": "无法识别当前页面：请停在改造页或持有一览"}
        # 增量更新以已保存结果为底；从列表页全量扫描则从零开始替换
        base = [] if from_list else (store.load_reform_config().get("materials") or [])
        try:
            if from_list:
                self._top_materials()
            seen: dict[str, dict] = {}
            same = 0
            for _ in range(30):
                if self._stop:
                    break
                mats = parse_materials(self._png())
                for m in mats:
                    prev = seen.get(m["key"])
                    if prev is None or m["count"] > prev["count"]:
                        seen[m["key"]] = {
                            "text": m["text"], "key": m["key"], "attr": m["attr"],
                            "lo": m["lo"], "hi": m["hi"], "pct": m["pct"],
                            "grade": m["grade"], "count": m["count"],
                        }
                # 每屏落盘：扫描中或中途停止，前端都能看到已扫到的数据
                items = self._merge_scan_items(seen, mode, base)
                store.save_reform_materials(items, mode)
                with self._lock:
                    self.status["current"] = f"已更新 {len(seen)} 种素材"
                    self.status["done"] = len(items)
                if mode == "flat" and any(m["pct"] for m in mats):
                    self._log("扫到第一个百分比石头，固定值部分已结束")
                    break
                if self._stop:
                    break
                self._scroll_materials()
                nxt = parse_materials(self._png())
                sig = [m["key"] for m in mats]
                if not nxt or [m["key"] for m in nxt] == sig:
                    same += 1
                    if same >= 2:
                        break
                else:
                    same = 0
            items = self._merge_scan_items(seen, mode, base)
            store.save_reform_materials(items, mode)
            return {"ok": True, "materials": items}
        finally:
            if from_list:
                self._back_to_list()
            else:
                self._log("扫描结束：保留在改造页，不返回装备列表")

    # ---------- 执行 ----------
    def start(self, cfg: dict | None = None) -> dict:
        import threading
        import store

        if self._thread and self._thread.is_alive():
            return {"ok": False, "error": "已有任务在运行（扫描素材或改造）"}
        conf = store.load_reform_config()
        if cfg:
            conf.update({k: v for k, v in cfg.items() if k in conf})
        # 只改造勾选的属性；未勾选一律跳过，空集合直接拒绝执行（防止误改）
        targets = [a for a in (conf.get("reform_attrs") or []) if a]
        if not targets:
            return {"ok": False, "error": "请先勾选「需要改造的属性」"}
        # 只用最低级的 1★ / 2★ 石头：星级必须按当前数值表重算，
        # 不信任配置里保存的 grade（旧数值表 / 手改配置都可能标错）。
        stones, blocked = normalize_stones(conf.get("stones") or [])
        if not stones:
            return {"ok": False, "error": "没有可用的 1★/2★ 改造石：先扫描素材并勾选低级石头"}
        self._stop = False
        self._stones = stones
        self._targets = targets
        self._stock = {_stone_id(s): int(s["count"]) for s in stones}
        self._max_try = int(conf.get("max_try") or 2)
        with self._lock:
            self.results = []
        self._begin("装备改造", "start")
        self._log(f"开始：只改造 {'、'.join(targets)}；石头顺序 "
                  + " > ".join(f"{_stone_id(s)}x{s['count']}" for s in stones))
        if blocked:
            self._log(f"已排除非 1★/2★ 配置 {len(blocked)} 项：" + "、".join(blocked))
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return {"ok": True}

    def _run(self) -> None:
        """逐屏处理装备列表。

        用「上一屏最后处理的一件」当锚点：即使只滚动了半屏，也只处理锚点之后的新行；
        到底判定看「滚动后屏幕底部装备是否变化」，比整屏签名稳定，避免到底后又重跑一屏。
        """
        try:
            if not self._ensure_list():
                self._fail("当前不是「装备改造」的持有一览界面")
                return
            if not parse_rows(self._png()):
                self._fail("没识别到改造列表：请停在「装备改造」的持有一览界面")
                return
            with self._lock:
                if self.status.get("phase") == "start":
                    self.status["phase"] = "running"
            anchor: tuple | None = None   # 上一屏最后处理的一件装备
            idle = 0                      # 连续没有新行的屏数
            for _ in range(40):
                if self._stop:
                    break
                rows = parse_rows(self._png())
                if not rows:
                    break
                before_sig = tuple(_row_key(r) for r in rows)
                # 从前往后找锚点：同名装备宁可多检查几行，也不跳过未处理的装备
                start = 0
                if anchor:
                    for i, r in enumerate(rows):
                        if _row_key(r) == anchor:
                            start = i + 1
                            break
                todo = rows[start:]
                if start:
                    self._log(f"跳过已检查的 {start} 行（本次只滚动了部分屏幕）")
                if not todo:
                    idle += 1
                    if idle >= 2:
                        self._log("已到列表末尾（连续两屏没有新装备）")
                        break
                else:
                    idle = 0
                    for r in todo:
                        if self._stop:
                            break
                        self._handle_row(r)
                    anchor = _row_key(todo[-1])
                if self._stop:
                    break
                if self._page() != "list":
                    self._log("⚠ 滚动前页面不对，中止")
                    break
                img = self._img()
                x = int(img.width * 0.22)
                # 慢速大位移（按住→拖动→停顿→抬起），尽量一次滚一整屏
                self._drag(x, int(img.height * 0.80), x, int(img.height * 0.30),
                           ms=1200, steps=20, hold=0.30)
                time.sleep(1.0)
                after = parse_rows(self._png())
                after_sig = tuple(_row_key(r) for r in after)
                if not after or after_sig == before_sig or after_sig[-1] == before_sig[-1]:
                    self._log("已到列表末尾（滚动后底部装备未变化）")
                    break
            self._finish("完成")
        except Exception as e:  # noqa: BLE001
            self._fail(f"执行异常: {e}")

    def _handle_row(self, row: dict) -> None:
        if self._page() != "list":
            self._log("⚠ 不在改造列表，中止（防止误触改造按钮）")
            self._stop = True
            return
        with self._lock:
            self.status["current"] = row["name"]
        if row["color"] != "green":
            return
        # 读详情确认加护属性
        self._tap(tuple(row["tap"]))
        time.sleep(TAP_WAIT)
        detail = parse_detail(self._png())
        if not detail:
            self._log(f"· {row['name']} 详情读取失败，跳过")
            return
        blessing = detail.get("blessing") or ""
        m = _SLOT_RE.match(blessing)
        attr = (m.group("attr") + ("%" if m.group("pct") else "")) if m else ""
        if not attr or attr not in self._targets:
            self._add_result(row, detail, "skip",
                             f"{blessing or '加护未识别'}（未勾选，跳过）")
            return
        stone = self._pick_stone()
        if not stone:
            self._log("石头用完，停止")
            self._stop = True
            return
        got = self._reform_one(row, stone)
        self._add_result(row, detail, "ok" if got else "fail", f"{blessing} → {got or '失败'}")

    def _add_result(self, row: dict, detail: dict, state: str, note: str) -> None:
        item = {"name": row["name"], "stars": row["stars"],
                "blessing": detail.get("blessing") or "", "state": state, "note": note}
        with self._lock:
            self.results.append(item)
            self.status["done"] = len(self.results)
        icon = {"skip": "=", "ok": "✔", "fail": "✗"}.get(state, "·")
        self._log(f"{icon} {row['name']}：{note}")

    def _pick_stone(self) -> dict | None:
        for s in self._stones:
            if self._stock.get(_stone_id(s), 0) > 0:
                return s
        return None

    @staticmethod
    def _sorted_materials(idx: dict) -> list[dict]:
        return sorted(idx.values(), key=lambda x: (x.get("attr") or "",
                                                  bool(x.get("pct")), x.get("lo") or 0))

    def _record_materials(self, mats: list[dict]) -> None:
        """执行改造时拉动素材列表，顺手把数量写回持久化表（初次可不扫描）。

        同时把本轮库存按游戏内实际持有量收敛：未扫描的占位库存会变成真实数量，
        用掉的 / 不存在的石头也会同步反映到前端表格。
        """
        import store
        cfg = store.load_reform_config()
        idx = {m["key"]: dict(m) for m in (cfg.get("materials") or []) if m.get("key")}
        changed = False
        for m in mats:
            k = m["key"]
            item = {f: m[f] for f in ("text", "key", "attr", "lo", "hi",
                                      "pct", "grade", "count") if f in m}
            old = idx.get(k)
            if old is None or old.get("count") != item["count"]:
                idx[k] = item
                changed = True
            if k in self._stock:
                n = int(item.get("count") or 0)
                if n < self._stock[k]:
                    self._stock[k] = n
        if changed:
            store.save_reform_materials(self._sorted_materials(idx),
                                        cfg.get("materials_mode") or "full")

    def _consume_material(self, stone: dict) -> None:
        """改造成功后把持久化数量 -1，前端能立刻看到库存变化。"""
        import store
        cfg = store.load_reform_config()
        idx = {m["key"]: dict(m) for m in (cfg.get("materials") or []) if m.get("key")}
        k = _stone_id(stone)
        m = idx.get(k)
        if not m:
            return
        n = max(0, int(m.get("count") or 0) - 1)
        m["count"] = n
        m["text"] = f"{k}x{n}"
        store.save_reform_materials(self._sorted_materials(idx),
                                    cfg.get("materials_mode") or "full")

    def _set_material_missing(self, stone: dict) -> None:
        """整轮拉完列表都没出现这块石头：把持有量记为 0，前端表格同步显示为 0。"""
        import store
        cfg = store.load_reform_config()
        idx = {m["key"]: dict(m) for m in (cfg.get("materials") or []) if m.get("key")}
        k = _stone_id(stone)
        m = idx.setdefault(k, {"key": k, "attr": stone["attr"], "lo": stone["lo"],
                               "hi": stone["hi"], "pct": bool(stone.get("pct")),
                               "grade": stone.get("grade")})
        if int(m.get("count") or 0) != 0:
            m["count"] = 0
            m["text"] = f"{k}x0"
            store.save_reform_materials(self._sorted_materials(idx),
                                        cfg.get("materials_mode") or "full")

    def _reform_one(self, row: dict, stone: dict) -> str:
        """在改造页按优先级依次尝试石头；某块拉完整列表仍找不到就切次一级。"""
        if not self._open_reform_page(row):
            self._log("  进入改造页失败")
            self._back_to_list()
            return ""
        for _ in range(len(self._stones) + 1):
            if self._stop:
                break
            ok, reason = self._select_stone(stone)
            if not ok:
                if reason == "not_found":
                    self._stock[_stone_id(stone)] = 0
                    self._set_material_missing(stone)
                    self._log(f"  列表里没有 {stone['text']}，切换次一级改造石")
                    nxt = self._pick_stone()
                    if not nxt:
                        self._log("  没有更多可用石头，停止")
                        self._stop = True
                        break
                    stone = nxt
                    continue
                if reason == "select_failed":
                    self._log(f"  没能选中 {stone['text']}，放弃这件（不点改造）")
                break
            # 提交前最后一道闸：页面 + 槽位预览都必须与预期石头一致
            want = _norm(stone_key(stone["attr"], stone["lo"], stone["hi"],
                                   bool(stone.get("pct"))))
            slot = parse_slot(self._png())
            if self._page() != "reform" or not _norm(slot["after"]).startswith(want):
                self._log(f"  ⚠ 提交前校验失败（预览「{slot['after'] or '空'}」），不点改造")
                break
            img = self._img()
            self._tap(_pct(*BTN_REFORM, img))
            time.sleep(ANIM_WAIT)
            for _ in range(5):
                if has_result_layer(self._png()):
                    self._tap(_pct(*RESULT_CLOSE, self._img()))
                    time.sleep(1.0)
                    break
                time.sleep(0.8)
            got_attr, got_num = parse_slot_after(self._png())
            sid = _stone_id(stone)
            self._stock[sid] = self._stock.get(sid, 0) - 1
            self._consume_material(stone)
            want_attr = stone["attr"] + ("%" if stone.get("pct") else "")
            self._back_to_list()
            if got_attr != want_attr:
                self._log(f"  ⚠ 校验不符：期望 {want_attr}，实际 {got_attr or '未识别'}")
                return ""
            return f"{got_attr}+{got_num}"
        self._back_to_list()
        return ""

    def _select_stone(self, stone: dict) -> tuple[bool, str]:
        """滚到目标石头 → 长按选中 → 槽位预览校验；沿途把素材数量写回持久化表。

        返回 (是否选中, 原因)：ok / not_found（列表拉完也没有）/
        select_failed（找到但选中失败）/ stopped（用户停止）。
        """
        want = _norm(stone_key(stone["attr"], stone["lo"], stone["hi"],
                               bool(stone.get("pct"))))
        self._top_materials()
        for _ in range(15):
            if self._stop:
                return False, "stopped"
            mats = parse_materials(self._png())
            self._record_materials(mats)
            for m in mats:
                if (m["attr"] != stone["attr"] or m["lo"] != stone["lo"]
                        or m["hi"] != stone["hi"]
                        or bool(m["pct"]) != bool(stone.get("pct"))):
                    continue
                for _try in range(self._max_try + 1):
                    self._long((m["tap"][0], m["tap"][1]), 420)
                    time.sleep(0.9)
                    slot = parse_slot(self._png())
                    got = _norm(slot["after"])
                    if got and got.startswith(want):
                        return True, "ok"
                    self._log(f"  选中校验不符（预览「{slot['after'] or '空'}」），重试")
                return False, "select_failed"
            sig = [m["key"] for m in mats]
            self._scroll_materials()
            if self._stop:
                return False, "stopped"
            nxt = parse_materials(self._png())
            self._record_materials(nxt)
            if not nxt or [m["key"] for m in nxt] == sig:
                return False, "not_found"
        return False, "not_found"

    def _fail(self, msg: str) -> None:
        self._end("error", msg, msg)

    def _finish(self, msg: str) -> None:
        self._end("stopped" if self._stop else "done",
                  f"{msg}：处理 {len(self.results)} 件")


if __name__ == "__main__":  # 手动调试：python app/reform.py tmp/xxx.png
    import sys

    data = open(sys.argv[1], "rb").read()
    print("rows:", parse_rows(data))
    print("detail:", parse_detail(data))
    print("materials:", parse_materials(data))
    print("slot:", parse_slot(data))
