# -*- coding: utf-8 -*-
"""评分规则系统。

规则 = 一个 JSON 文件（rules/<id>.json），可自由交换。结构：

{
  "id": "r_a1b2c3",
  "name": "高强化输出武器",
  "priority": 10,                       # 数字大的先匹配
  "enabled": true,
  "note": "",
  "target": {
    "reinforce": "lt20",                # "lt20" = 强化<20 / "eq20" = 强化=20（必选，没有更高）
    "rank": {"op": ">=", "value": 0},   # 阶级条件：op 取 >= > = < <=，value 为阶级数字（默认 >=0）
    "stars": {"op": ">=", "value": 1},  # 星级条件：同上，value 取 1~5（默认 >=1 不限制）
    "color": {"op": ">=", "value": 1},  # 品质色条件：value 1~5 = 白/绿/蓝/紫/红（默认 >=1 不限制）
    "mode": "types",                    # "types" | "equipment"
    "types": [101, 103],                # EquipmintType.id（不同武器分别算类型）
    "equipment_ids": [100100000],       # Equipment.id
    "attrs": ["攻击力"],                # 必有属性：全部命中（空 = 不限制）
    "attrs_opt": ["会心", "命中"],      # 可选属性：至少命中 attr_need 个（空 = 不限制）
    "attr_need": 1                      # 可选属性至少命中几个（1 ~ min(可选属性数, 4)）
  },
  "attr": { "攻击力": 1.0, "会心": 0.8 },
  "combos": [ { "attrs": ["攻击力", "会心", "命中"], "tiers": {"2": 100, "3": 200} } ],
  "rank_scores": { "4": 20, "5": 50, "6": 80 },   # 阶级分：按装备阶级（0~6）加分
  "star_scores": { "4": 10, "5": 30 },            # 星级分：按装备星级（1~5）加分
  "base_score": 30                      # 命中 target 就先加的基础分，默认 0
}

评分 = 基础分 + 阶级分 + 星级分 + Σ(词条数值 × 属性权重) + 类型分
组合按顺序判定，取第一组能得分的（后面的不再计算）；组内按阶梯给分：
满足 k 个属性拿 tiers[k]，档位 1 ~ min(属性数, 4)，取实际满足个数可达的最高档。
同一件装备只取一条规则：先看「按特定装备」的规则（命中就优先，与 priority 无关），
再看「按类型」的规则（priority 大的先）；未命中任何规则 = 0 分。
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid

import master
import store

_LOCK = threading.Lock()

_BLESSING_RE = re.compile(
    r"^(?P<attr>.+?)\s*[+\-−]\s*(?P<val>\d+(?:\.\d+)?)\s*(?P<pct>[%％])?$")

DEFAULT_ATTRS = ["攻击力", "魔力", "神力", "命中", "回避", "会心", "防御力",
                 "法术防御力", "抵抗", "行动速度"]

# 阶级条件的比较运算符（前端下拉同值）
RANK_OPS = (">=", ">", "=", "<", "<=")


def rank_cmp(v: float, op: str, target: float) -> bool:
    if op == ">":
        return v > target
    if op == "=":
        return v == target
    if op == "<":
        return v < target
    if op == "<=":
        return v <= target
    return v >= target  # 默认 / 非法运算符一律按 >=


def _normalize_cond(v, default: int, lo: int | None = None, hi: int | None = None) -> dict:
    """条件归一：{op, value}；也容忍老写法直接给数字。"""
    op, val = ">=", default
    if isinstance(v, dict):
        op = str(v.get("op") or ">=").strip()
        raw = v.get("value", v.get("num", default))
    elif v is not None:
        raw = v
    else:
        raw = default
    if op not in RANK_OPS:
        op = ">="
    try:
        val = int(float(raw))
    except (TypeError, ValueError):
        val = default
    if lo is not None:
        val = max(lo, val)
    if hi is not None:
        val = min(hi, val)
    return {"op": op, "value": val}


def _normalize_rank(v) -> dict:
    """阶级条件归一：{op, value}，默认 >= 0。"""
    return _normalize_cond(v, MIN_RANK)


def _normalize_stars(v) -> dict:
    """星级条件归一：{op, value}，默认 >= 1（不限制）；数值夹在 1~5。"""
    return _normalize_cond(v, MIN_STARS, MIN_STARS, MAX_STARS)


def _normalize_quality(v) -> dict:
    """装备品质色条件归一：{op, value}，value 1~5 = 白/绿/蓝/紫/红，默认 >= 1（不限制）。

    注意别和 `_normalize_color`（规则自身的显示颜色）搞混。
    """
    return _normalize_cond(v, MIN_COLOR, MIN_COLOR, MAX_COLOR)


# ---------- 词条解析 ----------

def parse_blessing(text: str) -> tuple[str, float] | None:
    """『魔力+3』→('魔力',3.0)；『行动速度+6%』→('行动速度%',6.0)；非数值词条→None。

    除「会心」外每种属性都有固定值和百分比两条记录，权重按 key 区分：
    固定值用属性名，百分比用「属性名%」。
    """
    m = _BLESSING_RE.match((text or "").strip())
    if not m:
        return None
    attr = m.group("attr").strip()
    if not attr or "/" in attr:
        return None
    if m.group("pct"):
        attr += "%"
    return attr, float(m.group("val"))


def split_blessings(blessings: list[str]) -> list[tuple[str, float]]:
    out = []
    for b in blessings or []:
        p = parse_blessing(b)
        if p:
            out.append(p)
    return out


# ---------- 存储 ----------

def rules_dir() -> str:
    return store.rules_dir()


# Windows 文件名非法字符 → 全角同形字：规则名不允许出现这些字符（前后端都会拦）
_FILENAME_MAP = str.maketrans({"\\": "＼", "/": "／", ":": "：", "*": "＊", "?": "？",
                               '"': "＂", "<": "＜", ">": "＞", "|": "｜",
                               "\r": "", "\n": "", "\t": ""})

ILLEGAL_NAME_CHARS = '\\/:*?"<>|'


def _clean_name(name) -> str:
    """规则名 = 文件名：非法字符转全角，去掉首尾空格/点。"""
    s = str(name or "").strip().translate(_FILENAME_MAP).strip(" .")
    return s or "未命名规则"


def name_error(name: str) -> str:
    """规则名合法性检查，返回错误信息（空串表示合法）。"""
    s = str(name or "").strip()
    if not s:
        return "规则名称不能为空"
    bad = sorted({c for c in s if c in ILLEGAL_NAME_CHARS})
    if bad:
        return "规则名称不能包含 " + " ".join(bad) + '（\\ / : * ? " < > |）'
    return ""


MIN_COMBO_TIER = 1  # 组合阶梯最低档：满足 1 个属性就能给分
MAX_COMBO_TIER = 4  # 组合阶梯最高档：满足 4 个以上一律按 4 档算

# 装备阶级范围（masterdata 里 rank 只有 0~6），阶级分按这个范围配置
MIN_RANK = 0
MAX_RANK = 6

# 装备星级范围（扫描只能读出 1~5 星），星级分按这个范围配置
MIN_STARS = 1
MAX_STARS = 5


def tier_keys(n_attrs: int) -> list[int]:
    """组合阶梯档位：1 ~ min(属性个数, 4)。"""
    top = max(MIN_COMBO_TIER, min(n_attrs, MAX_COMBO_TIER))
    return list(range(MIN_COMBO_TIER, top + 1))


def _normalize_combo(c: dict) -> dict | None:
    """组合：attrs 不限个数，tiers = {满足个数: 该档分数}，档位 1 ~ min(属性数, 4)。

    老格式 {need, bonus}（满足 need 个给 bonus）自动转成单档，行为保持不变。
    """
    attrs = [str(a) for a in (c.get("attrs") or []) if str(a).strip()]
    if not attrs:  # 空组合没意义；只留 1 个属性的组合仍可给 1 档分
        return None
    keys = tier_keys(len(attrs))
    raw = c.get("tiers")
    if not isinstance(raw, dict):  # 老格式兼容
        try:
            need = int(c.get("need") or len(attrs))
        except (TypeError, ValueError):
            need = len(attrs)
        need = max(keys[0], min(need, keys[-1]))
        raw = {need: c.get("bonus") or 0}
    tiers = {}
    for k in keys:
        v = _to_float(raw.get(str(k), raw.get(k)))
        if v:
            tiers[str(k)] = v
    return {"attrs": attrs, "tiers": tiers}


def combo_score_of(c: dict, got: int) -> float:
    """阶梯给分：取「实际满足个数」可达的最高档分数，中间空档自动往下找。"""
    tiers = c.get("tiers") or {}
    for k in range(min(got, MAX_COMBO_TIER), MIN_COMBO_TIER - 1, -1):
        v = _to_float(tiers.get(str(k)))
        if v:
            return v
    return 0.0


def _to_float(v) -> float:
    """基础分之类的数值：缺省 / 非法值一律按 0，别让一条坏数据毁掉整条规则。"""
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


DEFAULT_RULE_COLOR = "#e4e4e7"  # 规则默认色（白），与前端 rule-colors.ts 的 DEFAULT_RULE_COLOR 一致


def _normalize_color(v) -> str:
    """规则颜色：收 #rrggbb（也接受不带 # 的六位），空/非法一律回默认白。"""
    s = str(v or "").strip().lstrip("#")
    return "#" + s.lower() if re.fullmatch(r"[0-9a-fA-F]{6}", s) else DEFAULT_RULE_COLOR


def _clean_attrs(v) -> list[str]:
    """属性名列表：去空、去重，保持顺序。"""
    return list(dict.fromkeys(str(a) for a in (v or []) if str(a).strip()))


def _normalize(rule: dict) -> dict:
    t = rule.get("target") or {}
    mode = t.get("mode") if t.get("mode") in ("types", "equipment") else "types"
    # 目标拥有属性分两段：
    #   attrs     必有属性：全部命中才算命中这条规则
    #   attrs_opt 可选属性：从中至少命中 attr_need 个（1 ~ min(可选属性数, 4)）
    # 老规则没有 attrs_opt 键：那套语义本来就是「从 attrs 里至少命中 need 个」，整体搬进可选
    if "attrs_opt" in t:
        t_must = _clean_attrs(t.get("attrs"))
        t_opt = _clean_attrs(t.get("attrs_opt"))
    else:
        t_must = []
        t_opt = _clean_attrs(t.get("attrs"))
    try:
        t_need = int(t.get("attr_need") or 1)
    except (TypeError, ValueError):
        t_need = 1
    t_need = max(1, min(t_need, min(len(t_opt), 4))) if t_opt else 1
    # 阶级分：{阶级: 分数}，只收 0~6 且非 0 的项
    rank_scores = {}
    for k, v in (rule.get("rank_scores") or {}).items():
        try:
            kk = int(k)
        except (TypeError, ValueError):
            continue
        f = _to_float(v)
        if MIN_RANK <= kk <= MAX_RANK and f:
            rank_scores[str(kk)] = f
    # 星级分：{星级: 分数}，只收 1~5 且非 0 的项
    star_scores = {}
    for k, v in (rule.get("star_scores") or {}).items():
        try:
            kk = int(k)
        except (TypeError, ValueError):
            continue
        f = _to_float(v)
        if MIN_STARS <= kk <= MAX_STARS and f:
            star_scores[str(kk)] = f
    return {
        "id": str(rule.get("id") or "r_" + uuid.uuid4().hex[:8]),
        "name": _clean_name(rule.get("name")),
        "priority": int(rule.get("priority") or 100),
        "enabled": bool(rule.get("enabled", True)),
        "note": str(rule.get("note") or ""),
        # 规则颜色（#rrggbb）：规则名在列表/结果/hover 里都按它上色，空 = 默认灰
        "color": _normalize_color(rule.get("color")),
        "base_score": _to_float(rule.get("base_score")),
        "target": {
            # 强化没有 >20，只有 <20 / =20；老规则里的 gte20 归一到 eq20
            "reinforce": "eq20" if str(t.get("reinforce")) in ("gte20", "eq20") else "lt20",
            # 阶级：{op, value}，默认 >= 0（不限制）
            "rank": _normalize_rank(t.get("rank")),
            # 星级：{op, value}，默认 >= 1（不限制）
            "stars": _normalize_stars(t.get("stars")),
            # 品质色：{op, value}，1~5 = 白/绿/蓝/紫/红，默认 >= 1（不限制）
            "color": _normalize_quality(t.get("color")),
            "mode": mode,
            "types": [int(x) for x in (t.get("types") or []) if str(x).isdigit()],
            "equipment_ids": [int(x) for x in (t.get("equipment_ids") or []) if str(x).isdigit()],
            # 必有属性：全部命中；空列表 = 不限制
            "attrs": t_must,
            # 可选属性：至少命中 attr_need 个；空列表 = 不限制
            "attrs_opt": t_opt,
            "attr_need": t_need,
        },
        "attr": {str(k): float(v) for k, v in (rule.get("attr") or {}).items()
                 if isinstance(v, (int, float)) or str(v).replace(".", "", 1).lstrip("-").isdigit()},
        "combos": [c for c in (_normalize_combo(x) for x in (rule.get("combos") or [])) if c],
        "rank_scores": {k: rank_scores[k] for k in sorted(rank_scores, key=int)},
        "star_scores": {k: star_scores[k] for k in sorted(star_scores, key=int)},
    }


def _order_key(r: dict) -> tuple:
    """匹配顺序：按特定装备的规则永远排在按类型之前；同组内 priority 大的先。"""
    return (0 if r["target"]["mode"] == "equipment" else 1, -r["priority"], r["name"])


def load_rules() -> list[dict]:
    out = []
    for fn in os.listdir(rules_dir()):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(rules_dir(), fn), encoding="utf-8") as f:
                rule = _normalize(json.load(f))
            rule["id"] = fn[:-len(".json")]  # id 恒等于文件名（= 规则名）
            out.append(rule)
        except Exception:
            continue
    out.sort(key=_order_key)
    return out


def _file_id(name: str) -> str:
    """规则 id = 文件名 = 规则名。"""
    return _clean_name(name)


def save_rule(rule: dict) -> dict:
    r = _normalize(rule)
    old_id = str(rule.get("id") or "")
    r["id"] = _file_id(r["name"])
    p = os.path.join(rules_dir(), r["id"] + ".json")
    with _LOCK:
        if old_id and old_id != r["id"]:
            old = os.path.join(rules_dir(), old_id + ".json")
            if os.path.isfile(old):
                try:
                    os.remove(old)
                except OSError:
                    pass
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    return r


def delete_rule(rule_id: str) -> bool:
    p = os.path.join(rules_dir(), rule_id + ".json")
    with _LOCK:
        if os.path.isfile(p):
            os.remove(p)
            return True
    return False


# ---------- 匹配与评分 ----------

def kind_of(item: dict):
    """装备类型（EquipmentType.id）。老结果里可能没存，按 equipment_id 反查。"""
    k = item.get("kind")
    if k is not None:
        return k
    rec = master.equipment_by_id().get(item.get("equipment_id"))
    return rec.get("kind") if rec else None


def rank_of(item: dict):
    """装备阶级（Equipment.rank）。老结果里可能没存，按 equipment_id 反查。"""
    k = item.get("rank")
    if k is not None:
        return k
    rec = master.equipment_by_id().get(item.get("equipment_id"))
    return rec.get("rank") if rec else None


# 装备品质色：白 1 / 绿 2 / 蓝 3 / 紫 4 / 红 5（识别不出按白算）
COLOR_RANK = {"white": 1, "green": 2, "blue": 3, "purple": 4, "red": 5}
MIN_COLOR = 1
MAX_COLOR = 5


def color_rank(item: dict) -> int:
    """装备品质色的数字档位（扫描存的是 white/green/...）。"""
    return COLOR_RANK.get(str(item.get("color") or ""), MIN_COLOR)


def _match_target(item: dict, rule: dict) -> bool:
    t = rule["target"]
    reinf = item.get("reinforce") or 0
    if t["reinforce"] == "eq20" and reinf != 20:
        return False
    if t["reinforce"] == "lt20" and reinf >= 20:
        return False
    cond = t.get("rank") or {"op": ">=", "value": 0}
    rk = rank_of(item)
    if not rank_cmp(float(0 if rk is None else rk), cond["op"], float(cond["value"])):
        return False
    # 星级条件：老结果没存 stars 时按最低星算，默认 >=1 不会误杀
    star_cond = t.get("stars") or {"op": ">=", "value": MIN_STARS}
    try:
        st = int(item.get("stars")) if item.get("stars") is not None else MIN_STARS
    except (TypeError, ValueError):
        st = MIN_STARS
    if not rank_cmp(float(st), star_cond["op"], float(star_cond["value"])):
        return False
    # 品质色条件：白 1 / 绿 2 / 蓝 3 / 紫 4 / 红 5，识别不出按白算
    color_cond = t.get("color") or {"op": ">=", "value": MIN_COLOR}
    if not rank_cmp(float(color_rank(item)), color_cond["op"], float(color_cond["value"])):
        return False
    # 目标拥有属性（精确匹配，与组合分同口径）：
    #   必有属性要全中，可选属性至少命中 attr_need 个
    must = t.get("attrs") or []
    opt = t.get("attrs_opt")
    if opt is None:            # 心跳兜底：内存里理论都已归一
        opt, must = must, []
    if must or opt:
        present = {name for name, _ in split_blessings(item.get("blessings") or [])}
        if any(a not in present for a in must):
            return False
        if opt and sum(1 for a in opt if a in present) < int(t.get("attr_need") or 1):
            return False
    if t["mode"] == "types":
        return kind_of(item) in t["types"]
    return item.get("equipment_id") in t["equipment_ids"]


def pick_rule(item: dict, rules: list[dict]) -> dict | None:
    """取第一条命中的规则：按特定装备的规则无条件优先，其次才是按类型的。"""
    for r in rules:
        if r["enabled"] and r["target"]["mode"] == "equipment" and _match_target(item, r):
            return r
    for r in rules:
        if r["enabled"] and r["target"]["mode"] != "equipment" and _match_target(item, r):
            return r
    return None


def score_item(item: dict, rules: list[dict]) -> dict:
    """返回 {score, rule_id, rule_name, base_score, rank_score, star_score,
    attr_score, combo_score, hit_combos, attr_details}。

    attr_details 是每条词条的明细（数值 × 权重 = 分），并标出是否属于命中的组合，
    前端评分浮层直接照着画，不用再猜权重。
    """
    rule = pick_rule(item, rules)
    if rule is None:
        return {"score": 0.0, "rule_id": None, "rule_name": "", "rule_color": "",
                "base_score": 0.0, "rank_score": 0.0, "star_score": 0.0, "attr_score": 0.0,
                "combo_score": 0.0, "hit_combos": [], "attr_details": []}

    # 解析词条时保留原文，浮层里要照抄「攻击力+5%」这种写法
    parsed = []
    for text in item.get("blessings") or []:
        p = parse_blessing(text)
        if p:
            parsed.append((text, p[0], p[1]))
    present = {key for _, key, _ in parsed}

    # 组合按顺序判定：第一组能得分的就取它的分，后面的不再计算
    # 需求项精确匹配：『攻击力』只吃固定值词条，『攻击力%』只吃百分比词条，
    # 否则同一条「攻击力+5%」会同时顶掉两项，把满足个数虚增。
    combo_score = 0.0
    hit = []
    combo_attrs: set[str] = set()
    for c in rule["combos"]:
        attrs = c["attrs"]
        matched = [a for a in attrs if a in present]
        sc = combo_score_of(c, len(matched))
        if sc:
            combo_score = sc
            combo_attrs = set(attrs)
            hit.append(f"{'+'.join(matched)}（{len(matched)}/{len(attrs)} 项）")
            break

    # 命中目标装备条件即可获得基础分；老规则没有该字段时按 0
    base_score = _to_float(rule.get("base_score"))
    # 阶级分：命中规则后按装备阶级（0~6）取对应分数
    rk = rank_of(item)
    try:
        rk = int(rk) if rk is not None else MIN_RANK
    except (TypeError, ValueError):
        rk = MIN_RANK
    rank_score = _to_float((rule.get("rank_scores") or {}).get(str(rk)))
    # 星级分：命中规则后按装备星级（1~5）取对应分数
    try:
        star = int(item.get("stars") or 0)
    except (TypeError, ValueError):
        star = 0
    star_score = _to_float((rule.get("star_scores") or {}).get(str(star)))
    weights = rule["attr"]
    attr_score = 0.0
    details = []
    for text, key, val in parsed:
        w = weights.get(key)
        if w is None and key.endswith("%"):
            # 老规则只写了属性名：百分比词条退回到同一个权重
            w = weights.get(key[:-1])
        w = float(w or 0.0)
        pts = val * w
        attr_score += pts
        details.append({"text": text, "key": key, "value": val, "weight": w,
                        "pts": round(pts, 2), "combo": key in combo_attrs})

    return {"score": round(base_score + rank_score + star_score + attr_score + combo_score, 1),
            "rule_id": rule["id"], "rule_name": rule["name"],
            "rule_color": rule.get("color") or DEFAULT_RULE_COLOR,
            "base_score": round(base_score, 1), "rank_score": round(rank_score, 1),
            "star_score": round(star_score, 1),
            "attr_score": round(attr_score, 1),
            "combo_score": round(combo_score, 1), "hit_combos": hit,
            "attr_details": details}


def apply(items: list[dict], rules: list[dict] | None = None) -> list[dict]:
    """给扫描结果打规则分；并重算同装备名内排名。"""
    rules = load_rules() if rules is None else rules
    for it in items:
        it.update(score_item(it, rules))

    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(str(it.get("equipment_id") or it.get("name")), []).append(it)
    for g in groups.values():
        g.sort(key=lambda x: -x.get("score", 0))
        for i, it in enumerate(g):
            it["rank_in_id"] = i + 1
    return items


def apply_one(item: dict, items: list[dict], rules: list[dict] | None = None) -> None:
    """新增单件时增量评分：只给新条目打分，并重算同装备名内的排名。

    扫描时每件都重算全表是 O(n²)，件数多起来会明显吃 CPU。
    """
    rules = load_rules() if rules is None else rules
    item.update(score_item(item, rules))
    key = str(item.get("equipment_id") or item.get("name"))
    group = [it for it in items if str(it.get("equipment_id") or it.get("name")) == key]
    group.sort(key=lambda x: -x.get("score", 0))
    for i, it in enumerate(group):
        it["rank_in_id"] = i + 1


def known_attrs() -> list[str]:
    """属性全表（固定值 + 百分比） + 规则里出现过的自定义属性。"""
    attrs = set(DEFAULT_ATTRS)
    try:
        attrs.update(master.attr_keys())
    except Exception:  # noqa: BLE001  masterdata 缺失时退回默认表
        pass
    for r in load_rules():
        attrs.update(r["attr"].keys())
        for c in r["combos"]:
            attrs.update(c["attrs"])
    return sorted(attrs)


def attr_groups() -> dict:
    """给前端的属性表：同一属性的固定值/百分比并成一行，顺序沿用 masterdata 表。

    key 是评分用的键：固定值『攻击力』，百分比『攻击力%』（没有则为空串）。
    """
    try:
        g = master.effect_attrs()
    except Exception:  # noqa: BLE001
        g = {"flat": [], "pct": []}
    known = {a["key"] for a in g["flat"]} | {a["key"] for a in g["pct"]}
    custom = [a for a in known_attrs() if a not in known]

    pct_by_base = {a["base"]: a["key"] for a in g["pct"]}
    rows, seen = [], set()
    for a in g["flat"]:  # 固定值表顺序为主
        rows.append({"base": a["base"], "label": a["name"], "key": a["key"],
                     "pct_key": pct_by_base.get(a["base"], "")})
        seen.add(a["base"])
    for a in g["pct"]:  # 只有百分比形式的属性补在后面
        if a["base"] not in seen:
            rows.append({"base": a["base"], "label": a["name"], "key": "",
                         "pct_key": a["key"]})

    return {"flat": [{"key": a["key"], "label": a["name"]} for a in g["flat"]],
            "pct": [{"key": a["key"], "label": a["name"]} for a in g["pct"]],
            "custom": [{"key": a, "label": a} for a in custom],
            "rows": rows}


DEFAULT_RULE = {
    "id": "r_sample_weapon",
    "name": "示例：武器 · 强化=20",
    "priority": 100,
    "enabled": False,
    "note": "照着改就行：命中目标先加基础分，再加属性权重分与组合命中分",
    "color": DEFAULT_RULE_COLOR,
    "base_score": 0,
    "target": {
        "reinforce": "eq20",
        "rank": {"op": ">=", "value": 0},
        "stars": {"op": ">=", "value": 1},
        "color": {"op": ">=", "value": 1},
        "mode": "types",
        "types": [100, 101, 103, 104, 105, 106, 108, 110,
                  200, 201, 202, 203, 204, 205, 206, 207],
        "equipment_ids": [],
        "attrs": [],
        "attrs_opt": [],
        "attr_need": 1,
    },
    "attr": {"攻击力": 1.0, "魔力": 1.0, "命中": 0.5, "会心": 0.5, "回避": 0.5,
             "神力": 0.5, "行动速度": 0.3},
    "combos": [{"attrs": ["攻击力", "会心"], "tiers": {"2": 30}},
               {"attrs": ["魔力", "神力", "回避"], "tiers": {"2": 20, "3": 50}}],
    "rank_scores": {},
    "star_scores": {},
}


def migrate_filenames() -> int:
    """把旧的 r_xxxx.json 改名成「规则名.json」，便于直接看文件管理规则。"""
    n = 0
    with _LOCK:
        for fn in list(os.listdir(rules_dir())):
            if not fn.endswith(".json"):
                continue
            p = os.path.join(rules_dir(), fn)
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            name = _clean_name(data.get("name"))  # 名字里的非法字符转全角
            want = name + ".json"
            need_rewrite = data.get("name") != name or data.get("id") != name
            dst = p
            if want != fn:
                cand = os.path.join(rules_dir(), want)
                if not os.path.exists(cand):  # 重名就不动，避免覆盖
                    dst = cand
            if dst == p and not need_rewrite:
                continue
            try:
                if dst != p:
                    os.replace(p, dst)
                data["name"] = name
                data["id"] = os.path.basename(dst)[:-len(".json")]
                with open(dst, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                if dst != p:
                    n += 1
            except OSError:
                continue
    return n


def ensure_defaults() -> None:
    """不再自动放示例规则、也不预先建 rules/ 目录；已有规则时只修正历史文件名。"""
    d = os.path.join(store.data_dir(), "rules")
    if os.path.isdir(d) and os.listdir(d):
        migrate_filenames()


def summarize() -> dict:
    rules = load_rules()
    return {"count": len(rules), "enabled": sum(1 for r in rules if r["enabled"]),
            "attrs": known_attrs()}
