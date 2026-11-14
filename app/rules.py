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
    "mode": "types",                    # "types" | "equipment"
    "types": [101, 103],                # EquipmintType.id（不同武器分别算类型）
    "equipment_ids": [100100000]        # Equipment.id
  },
  "attr": { "攻击力": 1.0, "会心": 0.8 },
  "combos": [ { "attrs": ["攻击力", "会心"], "bonus": 30 } ],
  "base_score": 30                      # 命中 target 就先加的基础分，默认 0
}

评分 = 基础分 + Σ(词条数值 × 属性权重) + Σ(命中的组合额外分)
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


def _normalize_rank(v) -> dict:
    """阶级条件归一：{op, value}，默认 >= 0；也容忍老写法直接给数字。"""
    op, val = ">=", 0
    if isinstance(v, dict):
        op = str(v.get("op") or ">=").strip()
        raw = v.get("value", v.get("num", 0))
    elif v is not None:
        raw = v
    else:
        raw = 0
    if op not in RANK_OPS:
        op = ">="
    try:
        val = int(float(raw or 0))
    except (TypeError, ValueError):
        val = 0
    return {"op": op, "value": val}


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


def _normalize_combo(c: dict) -> dict | None:
    """组合：attrs 不限个数，need = 满足其中几个就得分（没写就是全部满足）。"""
    attrs = [str(a) for a in (c.get("attrs") or []) if str(a).strip()]
    if len(attrs) < 2:
        return None
    try:
        need = int(c.get("need") or len(attrs))
    except (TypeError, ValueError):
        need = len(attrs)
    need = max(2, min(need, len(attrs)))
    return {"attrs": attrs, "need": need, "bonus": float(c.get("bonus") or 0)}


def _to_float(v) -> float:
    """基础分之类的数值：缺省 / 非法值一律按 0，别让一条坏数据毁掉整条规则。"""
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize(rule: dict) -> dict:
    t = rule.get("target") or {}
    mode = t.get("mode") if t.get("mode") in ("types", "equipment") else "types"
    return {
        "id": str(rule.get("id") or "r_" + uuid.uuid4().hex[:8]),
        "name": _clean_name(rule.get("name")),
        "priority": int(rule.get("priority") or 100),
        "enabled": bool(rule.get("enabled", True)),
        "note": str(rule.get("note") or ""),
        "base_score": _to_float(rule.get("base_score")),
        "target": {
            # 强化没有 >20，只有 <20 / =20；老规则里的 gte20 归一到 eq20
            "reinforce": "eq20" if str(t.get("reinforce")) in ("gte20", "eq20") else "lt20",
            # 阶级：{op, value}，默认 >= 0（不限制）
            "rank": _normalize_rank(t.get("rank")),
            "mode": mode,
            "types": [int(x) for x in (t.get("types") or []) if str(x).isdigit()],
            "equipment_ids": [int(x) for x in (t.get("equipment_ids") or []) if str(x).isdigit()],
        },
        "attr": {str(k): float(v) for k, v in (rule.get("attr") or {}).items()
                 if isinstance(v, (int, float)) or str(v).replace(".", "", 1).lstrip("-").isdigit()},
        "combos": [c for c in (_normalize_combo(x) for x in (rule.get("combos") or [])) if c],
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
    """返回 {score, rule_id, rule_name, base_score, attr_score, combo_score, hit_combos}。"""
    rule = pick_rule(item, rules)
    pairs = split_blessings(item.get("blessings") or [])
    if rule is None:
        return {"score": 0.0, "rule_id": None, "rule_name": "", "base_score": 0.0,
                "attr_score": 0.0, "combo_score": 0.0, "hit_combos": []}

    # 命中目标装备条件即可获得基础分；老规则没有该字段时按 0
    base_score = _to_float(rule.get("base_score"))
    weights = rule["attr"]
    attr_score = 0.0
    for name, val in pairs:
        w = weights.get(name)
        if w is None and name.endswith("%"):
            # 老规则只写了属性名：百分比词条退回到同一个权重
            w = weights.get(name[:-1])
        attr_score += val * (w or 0.0)

    present = {name for name, _ in pairs}

    def has_attr(a: str) -> bool:
        """组合需求项命中：写基础名时，百分比词条也算（老规则兼容）；
        写「抵抗%」则要求确实出现百分比形式。"""
        return a in present or (not a.endswith("%") and a + "%" in present)

    combo_score = 0.0
    hit = []
    for c in rule["combos"]:
        attrs = c["attrs"]
        want = c.get("need") or len(attrs)  # 满足其中 want 个就得分
        got = sum(1 for a in attrs if has_attr(a))
        if got >= want:
            combo_score += c["bonus"]
            hit.append("+".join(attrs))

    return {"score": round(base_score + attr_score + combo_score, 1),
            "rule_id": rule["id"], "rule_name": rule["name"],
            "base_score": round(base_score, 1), "attr_score": round(attr_score, 1),
            "combo_score": round(combo_score, 1), "hit_combos": hit}


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
    "base_score": 0,
    "target": {
        "reinforce": "eq20",
        "rank": {"op": ">=", "value": 0},
        "mode": "types",
        "types": [100, 101, 103, 104, 105, 106, 108, 109, 110,
                  200, 201, 202, 203, 204, 205, 206, 207],
        "equipment_ids": [],
    },
    "attr": {"攻击力": 1.0, "魔力": 1.0, "命中": 0.5, "会心": 0.5, "回避": 0.5,
             "神力": 0.5, "行动速度": 0.3},
    "combos": [{"attrs": ["攻击力", "会心"], "bonus": 30},
               {"attrs": ["魔力", "神力", "回避"], "bonus": 50}],
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
