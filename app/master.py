# -*- coding: utf-8 -*-
"""masterdata 装备主数据：名称索引 + 图标路径。

数据来源（按优先级探测）：
    WVD_MASTER 环境变量 → <exe目录>/masterdata → 工程根/masterdata → 解包输出

图标：<master 同级>/assets.lib/sprite/ListIcon/<list_icon_resource>.png，
     可用 WVD_ICONS 覆盖；也支持 <exe目录>/icons/。
"""
from __future__ import annotations

import json
import os
import sys

_CACHE: dict = {}

UNPACK = r"D:\WizardyDaphne\WizardyDaphneUnpack\out"

# 属性全表里要隐藏的项：会心回避在装备词条中不存在（实测扫描数据从未出现）
HIDDEN_ATTRS = {"会心回避"}


def _base_dirs() -> list[str]:
    out = []
    if getattr(sys, "frozen", False):
        out.append(os.path.dirname(os.path.abspath(sys.executable)))
    out.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return out


def master_dir() -> str:
    for d in [os.environ.get("WVD_MASTER", "")] + [os.path.join(b, "masterdata") for b in _base_dirs()] \
             + [os.path.join(UNPACK, "masterdata")]:
        if d and os.path.isfile(os.path.join(d, "Equipment.json")):
            return d
    return ""


def icon_dirs() -> list[str]:
    cands = [os.environ.get("WVD_ICONS", "")]
    cands += [os.path.join(b, "icons") for b in _base_dirs()]
    m = master_dir()
    if m:
        cands.append(os.path.join(os.path.dirname(m), "assets.lib", "sprite", "ListIcon"))
        cands.append(os.path.join(os.path.dirname(m), "icons"))
    cands.append(os.path.join(UNPACK, "assets.lib", "sprite", "ListIcon"))
    return [c for c in cands if c and os.path.isdir(c)]


def icon_path(resource: str) -> str:
    if not resource:
        return ""
    fn = resource if resource.lower().endswith(".png") else resource + ".png"
    for d in icon_dirs():
        p = os.path.join(d, fn)
        if os.path.isfile(p):
            return p
    return ""


def _load_json(name: str) -> list:
    m = master_dir()
    if not m:
        return []
    p = os.path.join(m, name + ".json")
    if not os.path.isfile(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def zhs(v):
    return v.get("zhs") if isinstance(v, dict) else v


def equipment_list() -> list[dict]:
    """[{id, name, kind, part, rank, icon, is_special}]"""
    if "eq" in _CACHE:
        return _CACHE["eq"]
    rows = []
    for r in _load_json("Equipment"):
        name = zhs(r.get("name"))
        if not name:
            continue
        rows.append({
            "id": r.get("id"),
            "name": name,
            "kind": r.get("kind"),
            "part": r.get("part"),
            "rank": r.get("rank"),
            "icon": r.get("list_icon_resource") or "",
            "is_special": bool(r.get("is_special")),
        })
    _CACHE["eq"] = rows
    return rows


def equipment_by_name() -> dict[str, dict]:
    if "by_name" in _CACHE:
        return _CACHE["by_name"]
    idx: dict[str, dict] = {}
    for r in equipment_list():
        # 同名多条时保留 rank 最高的
        old = idx.get(r["name"])
        if old is None or (r.get("rank") or 0) > (old.get("rank") or 0):
            idx[r["name"]] = r
    _CACHE["by_name"] = idx
    return idx


def equipment_by_id() -> dict[int, dict]:
    if "by_id" in _CACHE:
        return _CACHE["by_id"]
    idx = {r["id"]: r for r in equipment_list()}
    _CACHE["by_id"] = idx
    return idx


def _has_kana(name: str) -> bool:
    """名字里有假名 = 没翻译的开发用条目（如「投擲（ボニー用）」）。"""
    return any("\u3040" <= ch <= "\u30ff" for ch in name or "")


def _usable_kinds() -> set:
    """哪些 kind 下至少有一件正常中文名的装备。

    极个别类型全表只有未翻译的开发用条目：109「投掷武器」就一件
    「投擲（ボニー用）」（邦妮专用投掷物，玩家拿不到），这类类型不往界面输出，
    避免规则里出现一个永远匹配不到的类型。
    """
    if "usable_kinds" in _CACHE:
        return _CACHE["usable_kinds"]
    kinds = {r["kind"] for r in equipment_list() if not _has_kana(r["name"])}
    _CACHE["usable_kinds"] = kinds
    return kinds


def types() -> list[dict]:
    """EquipmentType：装备类型（不同武器分开算），id 即 Equipment.kind。"""
    if "types" in _CACHE:
        return _CACHE["types"]
    usable = _usable_kinds()   # 没有装备数据的类型不输出
    rows = []
    for r in _load_json("EquipmentType"):
        if usable and r.get("id") not in usable:
            continue
        rows.append({
            "id": r.get("id"),
            "name": zhs(r.get("name")) or str(r.get("id")),
            "part": r.get("part"),
            "part_text": part_text(r.get("part")),
        })
    # 展示顺序与前端 @/parts 一致：单手武器 → 双手武器 → 头 → 手 → 胴 → 盾 → 脚 → 饰品
    rows.sort(key=lambda x: (part_rank(x["part"]), x["id"] or 0))
    _CACHE["types"] = rows
    return rows


def type_name(kind) -> str:
    for t in types():
        if t["id"] == kind:
            return t["name"]
    return str(kind or "")


def part_text(part) -> str:
    return {1: "单手武器", 2: "双手武器", 3: "盾", 4: "头", 5: "胴",
            6: "手", 7: "脚", 8: "饰品"}.get(part, str(part or ""))


# 部位展示顺序（与前端的类型筛选 / 规则分组一致），注意「胴」= 身体
PART_ORDER = (1, 2, 4, 6, 5, 3, 7, 8)


def part_rank(part) -> int:
    """部位排序权重：未列出的排最后。"""
    try:
        return PART_ORDER.index(int(part))
    except (TypeError, ValueError):
        return len(PART_ORDER)


def effect_format_names() -> dict[int, str]:
    """EquipmentEffect: id -> 中文格式串，如 '魔力+{0}'。"""
    if "eff" in _CACHE:
        return _CACHE["eff"]
    idx = {}
    for r in _load_json("EquipmentEffect"):
        idx[r.get("id")] = zhs(r.get("format_name")) or ""
    _CACHE["eff"] = idx
    return idx


def effect_attrs() -> dict[str, list[dict]]:
    """属性全表（EquipmentEffect）按「固定值 / 百分比」分组。

    除「会心」「会心回避」外，每种属性都有两条记录：
      百分比 effect_id 6~16（format 含 {0}%），固定值 17~27。
    返回 {"flat": [...], "pct": [...]}，每项 {key, base, unit, effect_id, name, format}。
    key：固定值 = 属性名，百分比 = 属性名 + "%"（评分权重按 key 区分）。
    只返回 visible=True 的，会心/会心回避的百分比版游戏内不显示；
    会心回避整体隐藏（装备词条数据里从未出现过）。
    """
    if "attr_groups" in _CACHE:
        return _CACHE["attr_groups"]
    flat, pct = [], []
    for r in sorted(_load_json("EquipmentEffect"), key=lambda x: x.get("id") or 0):
        fmt = (zhs(r.get("format_name")) or "").strip()
        if "{0}" not in fmt or not r.get("visible", True):
            continue
        unit = "pct" if "%" in fmt else "flat"
        base = fmt.split("{0}")[0].strip().rstrip("+＋ ").strip()
        if not base or base in HIDDEN_ATTRS:
            continue
        item = {"key": base + "%" if unit == "pct" else base, "base": base,
                "unit": unit, "effect_id": r.get("id"),
                "name": (zhs(r.get("name")) or base).strip(), "format": fmt}
        (pct if unit == "pct" else flat).append(item)
    _CACHE["attr_groups"] = {"flat": flat, "pct": pct}
    return _CACHE["attr_groups"]


def upgrade_grades() -> dict[str, dict[str, list[tuple[int, int]]]]:
    """改造石数值档位 → 星级（EquipmentEffectUpgrade）。

    每个属性（固定值 / 百分比）各有 5 档，rarity=1..5，数值越高等级越高：
      百分比（全部属性）        : 1-2 / 1-3 / 2-4 / 3-5 / 4-6
      固定值（通用属性）        : 1-3 / 2-4 / 3-5 / 4-6 / 5-7
      固定值（会心 / 行动速度） : 1-2 / 2-3 / 3-4 / 3-5 / 4-6
    kind=1/2 两条记录数值相同；同档出现冲突数值则丢弃该属性（宁可不判级）。
    返回 {"flat": {属性名: [(lo,hi)×5]}, "pct": {...}}；缺 masterdata 时为空。
    """
    if "upgrade_grades" in _CACHE:
        return _CACHE["upgrade_grades"]
    fmt = effect_format_names()
    pairs: dict[tuple[str, str, int], set[tuple[int, int]]] = {}
    for r in _load_json("EquipmentEffectUpgrade"):
        s = fmt.get(r.get("effect_id")) or ""
        rarity = int(r.get("rarity") or 0)
        if "{0}" not in s or not 1 <= rarity <= 5:
            continue
        base = s.split("{0}")[0].strip().rstrip("+＋ ").strip()
        if not base:
            continue
        unit = "pct" if "%" in s else "flat"
        pair = (int(r.get("param_min") or 0), int(r.get("param_max") or 0))
        pairs.setdefault((unit, base, rarity), set()).add(pair)
    out: dict[str, dict[str, list]] = {"flat": {}, "pct": {}}
    for unit, base in {(u, b) for u, b, _ in pairs}:
        seq = []
        for rarity in range(1, 6):
            v = pairs.get((unit, base, rarity))
            if not v or len(v) != 1:
                seq = []
                break
            seq.append(next(iter(v)))
        if len(seq) == 5:
            out[unit][base] = seq
    _CACHE["upgrade_grades"] = out
    return out


def upgrade_grade(attr: str, lo: int, hi: int, pct: bool) -> int | None:
    """按 masterdata 的 5 档数值反推 1~5 星；对不上返回 None。"""
    seq = upgrade_grades()["pct" if pct else "flat"].get(attr) or []
    for i, pair in enumerate(seq, 1):
        if pair == (lo, hi):
            return i
    return None


def attr_keys() -> list[str]:
    """属性全表的评分键（固定值在前，百分比在后）。"""
    g = effect_attrs()
    return [a["key"] for a in g["flat"]] + [a["key"] for a in g["pct"]]


def stats() -> dict:
    return {"equipment": len(equipment_list()),
            "names": len(equipment_by_name()),
            "icons": len(icon_dirs()) and len(os.listdir(icon_dirs()[0])),
            "master_dir": master_dir(),
            "icon_dir": (icon_dirs() or [""])[0]}
