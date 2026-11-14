# -*- coding: utf-8 -*-
"""装备名校验：+X 强化次数剥离 → 别名表 → 精确匹配 → 模糊候选。"""
from __future__ import annotations

import difflib
import json
import os
import re
import threading

import master
import store

_LOCK = threading.Lock()

# 名字末尾的 +N（半角 + 或全角 ＋，允许空格）；【XI】这类后缀不算
_REINFORCE_RE = re.compile(r"^(?P<base>.*?)(?:\s*[+＋]\s*(?P<n>\d{1,2}))?$")

_BRACKET = str.maketrans({"[": "【", "]": "】", "（": "(", "）": ")"})


def split_reinforce(raw: str) -> tuple[str, int]:
    """『水零轻斧+10』→ ('水零轻斧', 10)；『王者之剑【XI】』→ 原样，0。"""
    t = (raw or "").strip().translate(_BRACKET)
    m = _REINFORCE_RE.match(t)
    if not m:
        return t, 0
    base = (m.group("base") or "").strip()
    n = m.group("n")
    if not base or n is None:
        return t, 0
    return base, int(n)


def _alias_path() -> str:
    return os.path.join(store.config_dir(), "aliases.json")


def load_aliases() -> dict[str, str]:
    try:
        with open(_alias_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_alias(raw: str, target: str) -> dict[str, str]:
    key = split_reinforce(raw)[0]
    with _LOCK:
        data = load_aliases()
        data[key] = target
        tmp = _alias_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _alias_path())
    return data


def clear_alias(raw: str) -> dict[str, str]:
    key = split_reinforce(raw)[0]
    with _LOCK:
        data = load_aliases()
        data.pop(key, None)
        with open(_alias_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    return data


def fuzzy_candidates(name: str, limit: int = 6) -> list[dict]:
    idx = master.equipment_by_name()
    if not name:
        return []
    scored = []
    for cand, rec in idx.items():
        # 长度差太大直接跳过，省时间
        if abs(len(cand) - len(name)) > 3:
            continue
        r = difflib.SequenceMatcher(None, name, cand).ratio()
        if r >= 0.45:
            scored.append((r, cand, rec))
    scored.sort(key=lambda x: -x[0])
    out = []
    for r, cand, rec in scored[:limit]:
        out.append({"name": cand, "ratio": round(r, 3), "id": rec["id"],
                    "icon": rec["icon"], "rank": rec.get("rank")})
    return out


def match(raw: str) -> dict:
    """校验一条 OCR 名称，返回匹配结果。"""
    base, reinf = split_reinforce(raw)
    idx = master.equipment_by_name()
    aliases = load_aliases()

    if base in aliases and aliases[base] in idx:
        rec = idx[aliases[base]]
        return {"status": "alias", "raw": raw, "name": rec["name"], "reinforce": reinf,
                "id": rec["id"], "icon": rec["icon"], "rank": rec.get("rank"),
                "kind": rec.get("kind"),
                "is_special": rec.get("is_special", False),
                "part": master.part_text(rec.get("part")),
                "type_name": master.type_name(rec.get("kind")),
                "candidates": []}

    if base in idx:
        rec = idx[base]
        return {"status": "ok", "raw": raw, "name": rec["name"], "reinforce": reinf,
                "id": rec["id"], "icon": rec["icon"], "rank": rec.get("rank"),
                "kind": rec.get("kind"),
                "is_special": rec.get("is_special", False),
                "part": master.part_text(rec.get("part")),
                "type_name": master.type_name(rec.get("kind")),
                "candidates": []}

    cands = fuzzy_candidates(base)
    return {"status": "fuzzy" if cands else "none", "raw": raw, "name": base,
            "reinforce": reinf, "id": None, "icon": "", "rank": None, "kind": None,
            "is_special": False, "part": "", "type_name": "",
            "candidates": cands}
