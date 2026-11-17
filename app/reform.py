# -*- coding: utf-8 -*-
"""装备改造界面（铁匠铺 → 装备改造）的解析。

与「装备强化」界面的差异（900x1600 实测）：
  列表：名字 x 100~330，y 330~1310，行距约 117；星级在名字左侧 x 20~100。
  详情：名称 y≈380（x>420），属性表 y 540~880，◆附加加护 y≈905，加护行 y≈946，
        强度上限 y≈1197。
  改造页：4 个加护槽（绿装只占第 1 个，y≈548），素材一览 y 880 起，行距约 97。

素材列表（改造石）翻页要点：
  · 界面里最多显示 5 行，一次手势只滚 4 行（≈390px），留 1 行重叠，
    否则底部那行只露一半、点不准，滚过去就漏了（原来是滚 5 行多，基本不重叠）；
  · ms=900/steps=15 的手势实测 1.9 秒仍稳定滚 4 行（比 1500/25 快 1/3，再快就只滚 3 行）；
  · 列表顺序是固定的，全量扫描时把真实顺序记进 materials_order，
    执行改造时按它估算目标在第几页，连续盲翻几页再截图确认，不用每页停一次；
  · 进改造页时素材列表总在顶部（实测：退出再进来会重置），所以只有连着找几块
    石头才需要回滚，回滚也是连翻 6 页再确认一次。

素材定位两种方式（配置 materials_jump，界面可切）：
  · slider（默认）：右侧有一条滚动条（900x1600 实测滑块 x≈851、轨道 y 948~1399、
    95 行时滑块高 37px、可走 414px）。慢速 motionevent 拖滑块能直接跳到任意位置，
    一次约 3 秒；回顶部也是一次拖到轨道顶端（约 2 秒）。滑块认不出来 / 拖不动时
    自动退回逐页滚动。
  · scroll（老方案）：完全没有滑块相关动作，纯拖列表翻页。
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


def _page_of(order: list[str], key: str) -> int | None:
    """这块石头在扫描顺序里的第几页（每页滚 MAT_SCROLL_ROWS 行）；没记录过返回 None。"""
    try:
        return int(order.index(key) / MAT_SCROLL_ROWS)
    except (ValueError, AttributeError):
        return None


def _match_stone(m: dict, stone: dict) -> bool:
    """素材行是不是要找的那块石头（属性 + 区间 + 是否百分比）。"""
    return (m["attr"] == stone["attr"] and m["lo"] == stone["lo"]
            and m["hi"] == stone["hi"] and bool(m["pct"]) == bool(stone.get("pct")))


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

    **启动时不判定「有没有」**：配置里保存的数量可能早就过期（扫描过但后来用掉 /
    又攒回来了），所以一律按「数量未知」处理，执行时到游戏列表里现找；
    真的一整轮都找不到，才把这块石头记为 0 并换下一块，全都没找到就停。
    unscanned=True 的老配置（没扫过素材）同样按未知处理。
    """
    ok, blocked = [], []
    for s in refresh_stones(raw):
        if s.get("grade") not in (1, 2):
            blocked.append(f"{s.get('key') or s.get('text') or '?'}"
                           f"({s.get('grade') or '无法判定'}★)")
            continue
        s = dict(s)
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


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """把布尔序列切成连续 True 的区间 [(起, 止)]（止为下标本身）。"""
    d = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1) - 1))


def _mat_bar(png: bytes) -> tuple[int, int, int, int, int] | None:
    """定位素材列表右侧的滚动条：(x, 滑块顶, 滑块底, 轨道顶, 轨道底)。

    轨道用实测常量（界面固定），只动态找滑块那条亮条：轨道细线太暗，
    阈值识别不稳（会把滑块顶端当成轨道顶端，导致算出的可拖动距离为 0）。
    找不到滑块就返回 None，调用方退回逐页滚动，不会卡死。
    """
    img = _open(png)
    sx, sy = _scale(img)
    a = np.asarray(img.convert("L"))
    ty0 = int(MAT_BAR_TRACK[0] * sy)
    ty1 = min(a.shape[0] - 1, int(MAT_BAR_TRACK[1] * sy))
    x0, x1 = int(MAT_BAR_X[0] * sx), int(MAT_BAR_X[1] * sx)
    y0 = max(0, ty0 - int(12 * sy))
    y1 = min(a.shape[0], ty1 + int(12 * sy))
    best = None      # (长度, x, 顶, 底)
    for c in range(x0, min(x1, a.shape[1])):
        for seg in _runs(a[y0:y1, c] > 100):
            ln = int(seg[1] - seg[0])
            if ln < 8 or ln > (ty1 - ty0) // 2:
                continue
            if best is None or ln > best[0]:
                best = (ln, c, int(seg[0] + y0), int(seg[1] + y0))
    if best is None:
        return None
    _, c, th0, th1 = best
    if th1 < ty0 - 8 or th0 > ty1 + 8:   # 不像这段轨道上的滑块
        return None
    return c, th0, th1, ty0, ty1


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

# 素材一览翻页：行距约 97px，界面里最多显示 5 行。
# 一次只滚 4 行（实测拖 394px 滚 4 行），和上一屏重叠 1 行 —— 原来滚 ≈500px（5 行多），
# 一屏几乎不重叠，底部那行只露一半、点不准，滚过去就漏掉了。
MAT_ROW_H = 97
MAT_SCROLL_ROWS = 4
# 手指位移比想要的滚动量多一点：实测 25 步时几乎 1:1（丢约 55px 的前一版是 10 步的情况）
MAT_DRAG_PX = int(MAT_SCROLL_ROWS * MAT_ROW_H) + 6
TOP_BATCH = 6          # 回顶部时连续盲翻几页再确认一次
JUMP_BATCH = 6         # 按顺序估算位置时，一次最多连续盲翻几页

# 素材列表右侧滚动条（900x1600 实测）：滑块 x≈851，轨道 y 948~1399，滑块高≈37。
# 95 行时滑块只有 37px、能走 414px；慢速 motionevent 拖它能直接跳到任意位置，
# 比逐页盲翻快得多（翻 90 行≈20 次手势、40 秒以上）。
# 轨道上下端是固定界面元素，直接写常量：那条细线太暗，逐帧阈值识别会把滑块顶端当成轨道顶端。
MAT_BAR_X = (838, 866)
MAT_BAR_TRACK = (948, 1399)
MAT_ROWS_ON_SCREEN = 5  # 素材列表一屏最多几行（列表区约 590px / 行距 97px）


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
        self._wh: tuple[int, int] | None = None
        self._stones: list[dict] = []
        self._targets: list[str] = []   # 需要改造的属性（勾选才会改）
        self._stock: dict[str, int] = {}
        self._max_try = 2
        self._jump = "slider"   # 素材定位方式：slider=拖右侧滚动条，scroll=逐页滚动
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

    def _scroll_materials(self, pages: int = 1, up: bool = False) -> None:
        """翻素材列表。一次手势滚 4 行（≈390px），pages>1 就连续做几个手势。

        实测（900x1600）：ms=700/steps=12 一次手势 1.6 秒仍能稳定滚 4 行，
        比原来 ms=1500/steps=25 的 2.9 秒快 45%；再快（ms=600）就只滚 3 行了。
        中间不截图：连续翻几页再确认一次。
        """
        if self._stop:
            return
        # 分辨率固定，尺寸缓存下来：翻页很频繁，每页都截一张图只为算坐标太浪费
        if self._wh is None:
            self._wh = self._img().size
        w, h = self._wh
        x = int(w * 0.5)
        dy = int(MAT_DRAG_PX * h / BASE_H)
        y_lo = int(h * 0.86)
        y_hi = y_lo - dy
        y_from, y_to = (y_hi, y_lo) if up else (y_lo, y_hi)
        for i in range(max(1, pages)):
            if self._stop:
                return
            self._drag(x, y_from, x, y_to, ms=700, steps=12, hold=0.30)
            if i + 1 < pages:
                time.sleep(0.2)
        time.sleep(0.4)

    def _top_materials(self) -> None:
        """回到素材顶部：先看一眼首行是不是顺序里的第一项，是就直接返回。

        不是就用滑块（slider 模式）把滚动条拖回顶端，一次就到位；
        没认出滑块时仍按原来的做法连续盲翻 TOP_BATCH 页再确认。
        """
        order = self._mat_order()
        for _ in range(8):
            if self._stop:
                return
            png = self._png()
            mats = parse_materials(png)
            if order and mats and mats[0]["key"] == order[0]:
                return
            before = [m["key"] for m in mats]
            bar = _mat_bar(png) if self._jump == "slider" else None
            if bar:
                # 滑块方案：直接拖回轨道顶端，一次就到位（2px≈1 行，别用像素判断是否到顶）
                x, th0, th1, tk0, _tk1 = bar
                h = th1 - th0
                self._drag(x, th0 + h // 2, x, tk0 + h // 2,
                           ms=760, steps=14, hold=0.30)
                time.sleep(0.45)
            else:
                self._scroll_materials(pages=TOP_BATCH, up=True)
            if [m["key"] for m in parse_materials(self._png())] == before:
                return

    def _slider_jump(self, target_idx: int, order: list[str], mats: list[dict]) -> bool:
        """拖右侧滚动条把目标石头挪到屏幕中间（滑块方案，一次 1~2 秒）。

        位移按「当前首行在扫描顺序里的行号」算，所以跳不准的话下一轮会自己修正；
        返回 False 表示这次用不了（没认出滑块 / 拖不动），调用方退回逐页滚动。
        """
        bar = _mat_bar(self._png())
        if not bar or not mats:
            return False
        x, th0, th1, tk0, tk1 = bar
        h = th1 - th0
        travel = max(1, tk1 - tk0 - h)                  # 滑块可走的总距离
        span = max(1, len(order) - MAT_ROWS_ON_SCREEN)  # 可滚动的「首行」范围
        try:
            cur_idx = order.index(mats[0]["key"])
        except ValueError:
            # 顺序和游戏里对不上（有石头被用掉）：只能按目标绝对位置估一次
            frac = (target_idx - MAT_ROWS_ON_SCREEN // 2) / span
            want_top = tk0 + int(round(max(0.0, min(1.0, frac)) * travel))
        else:
            # 让目标落在屏幕中间：首行应该滚到 target_idx - 半屏
            dy_rows = (target_idx - MAT_ROWS_ON_SCREEN // 2) - cur_idx
            want_top = th0 + int(round(dy_rows / span * travel))
        want_top = int(max(tk0, min(tk1 - h, want_top)))
        if abs(want_top - th0) < 4:
            return False
        self._drag(x, th0 + h // 2, x, want_top + h // 2, ms=760, steps=14, hold=0.30)
        time.sleep(0.45)
        return True

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
            # 从持有一览刚点进来时，素材列表本来就在顶部（实测退出再进会重置），
            # 不用先回滚 —— 原来这里要白花 20 多秒。
            if from_list:
                self._log("素材列表在顶部，直接往下扫")
            seen: dict[str, dict] = {}
            order: list[str] = []          # 从上到下的真实顺序（只有全量扫描才有效）
            same = 0
            mats = parse_materials(self._png())
            for _ in range(60):
                if self._stop:
                    break
                for m in mats:
                    if from_list and m["key"] not in order:
                        order.append(m["key"])
                    prev = seen.get(m["key"])
                    if prev is None or m["count"] > prev["count"]:
                        seen[m["key"]] = {
                            "text": m["text"], "key": m["key"], "attr": m["attr"],
                            "lo": m["lo"], "hi": m["hi"], "pct": m["pct"],
                            "grade": m["grade"], "count": m["count"],
                        }
                # 每屏落盘：扫描中或中途停止，前端都能看到已扫到的数据
                items = self._merge_scan_items(seen, mode, base)
                store.save_reform_materials(items, mode, order=order if from_list else None)
                with self._lock:
                    self.status["current"] = f"已更新 {len(seen)} 种素材"
                    self.status["done"] = len(items)
                if mode == "flat" and any(m["pct"] for m in mats):
                    self._log("扫到第一个百分比石头，固定值部分已结束")
                    break
                if self._stop:
                    break
                self._scroll_materials()
                sig = [m["key"] for m in mats]
                nxt = parse_materials(self._png())
                # 这一屏的解析结果直接留给下一轮，别又截一次图 OCR 一遍
                if not nxt or [m["key"] for m in nxt] == sig:
                    same += 1
                    if same >= 2:
                        break
                else:
                    same = 0
                mats = nxt
            items = self._merge_scan_items(seen, mode, base)
            store.save_reform_materials(items, mode, order=order if from_list else None)
            if from_list and order:
                self._log(f"已记录素材在列表里的顺序（{len(order)} 项），"
                          f"执行改造时按它连续翻页定位")
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
        self._jump = "scroll" if conf.get("materials_jump") == "scroll" else "slider"
        with self._lock:
            self.results = []
        self._begin("装备改造", "start")
        self._log(f"开始：只改造 {'、'.join(targets)}；石头顺序 "
                  + " > ".join(_stone_id(s) for s in stones))
        self._log("素材定位：拖右侧滚动条跳到目标"
                  if self._jump == "slider" else "素材定位：逐页滚动")
        self._log("启动时不判定持有量（配置里的数量可能过期），按顺序到游戏列表里现找；"
                  "一整轮都找不到才换下一块石头，全都找不到才停")
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
            self._log("配置里的改造石全都在游戏列表里找不到（或已用完），停止")
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

        列表顺序固定（全量扫描时记在 materials_order 里），所以先按顺序估算目标
        在第几页，连续盲翻过去再确认一次；估算不准或没有顺序记录时，退回逐页扫描。

        返回 (是否选中, 原因)：ok / not_found（列表拉完也没有）/
        select_failed（找到但选中失败）/ stopped（用户停止）。
        """
        key = stone_key(stone["attr"], stone["lo"], stone["hi"], bool(stone.get("pct")))
        want = _norm(key)
        self._top_materials()
        # 列表顺序是固定的，全量扫描时记下了真实顺序 → 知道目标大概在第几页，
        # 可以连续盲翻几页再确认一次，不用每页都停下来截图。
        order = self._mat_order()
        want_page = _page_of(order, key)
        want_idx = order.index(key) if key in order else None
        slider = want_idx is not None and self._jump == "slider"
        jumps = 0        # 滑块方案这次已经跳了几次，跳不准就退回逐页滚动
        nudged = False
        for _ in range(24):
            if self._stop:
                return False, "stopped"
            mats = parse_materials(self._png())
            self._record_materials(mats)
            sig = [m["key"] for m in mats]
            hit = next((m for m in mats if _match_stone(m, stone)), None)
            if hit is not None:
                if not nudged and hit["y"] > MAT_Y[1] - 140:
                    # 贴在列表底边、多半只露半行的位置点不准：先往上挪一页再选
                    nudged = True
                    self._scroll_materials(pages=1)
                    continue
                for _try in range(self._max_try + 1):
                    self._long((hit["tap"][0], hit["tap"][1]), 420)
                    time.sleep(0.9)
                    slot = parse_slot(self._png())
                    got = _norm(slot["after"])
                    if got and got.startswith(want):
                        return True, "ok"
                    self._log(f"  选中校验不符（预览「{slot['after'] or '空'}」），重试")
                return False, "select_failed"
            if not mats:
                return False, "not_found"
            if slider and jumps < 3:
                jumps += 1
                if self._slider_jump(int(want_idx), order, mats):
                    if self._stop:
                        return False, "stopped"
                    nxt = parse_materials(self._png())
                    self._record_materials(nxt)
                    if nxt and [m["key"] for m in nxt] != sig:
                        continue          # 跳过去了：下一轮从头判断目标在不在
                    jumps = 3             # 拖了但画面没动 —— 这块界面不认拖动
                    self._log("  滑块拖动没生效，改回逐页滚动")
                elif jumps >= 3:
                    self._log("  滑块跳了几次没到位，改回逐页滚动")
            pages = 1
            if want_page is not None:
                cur = _page_of(order, mats[0]["key"])
                if cur is not None and cur > want_page:
                    # 记下的顺序比游戏里旧（中间的石头被用掉了），估算会偏后：
                    # 放弃跳页，回顶部老老实实逐页找，保证不漏
                    self._log("  顺序和游戏里对不上（有石头被用掉），改成逐页查找")
                    want_page = None
                    self._top_materials()
                    continue
                if cur is not None and want_page > cur:
                    pages = max(1, min(want_page - cur - 1, JUMP_BATCH))
            self._scroll_materials(pages=pages)
            if self._stop:
                return False, "stopped"
            nxt = parse_materials(self._png())
            self._record_materials(nxt)
            if not nxt or [m["key"] for m in nxt] == sig:
                return False, "not_found"
        return False, "not_found"

    @staticmethod
    def _mat_order() -> list[str]:
        import store
        return list(store.load_reform_config().get("materials_order") or [])

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
