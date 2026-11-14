# -*- coding: utf-8 -*-
"""本地持久化（绿色便携）。

目录结构（根目录 = 绿色版 exe 同目录 / 源码工程根，或环境变量 WVD_SCAN_DATA）：
    config/   settings.json（界面设置） aliases.json（名称校准） current.json（当前结果文件）
              reform.json（改造配置） filter_notes.json（过滤器笔记） port.txt（运行时端口）
    rules/    <规则名>.json（评分规则，运行时按需创建）
    result/   scan_YYYYmmdd_HHMMSS.json（扫描结果，运行时按需创建）

绿色版不随包带 config/ rules/ result/，三者都由运行时按需创建，
升级替换 exe / web 时不会覆盖用户自己的配置与笔记。
早期版本用的是 data/ 目录，首次启动由 migrate() 搬到根目录下。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

_LOCK = threading.Lock()


# ---------- 目录 ----------

def data_dir() -> str:
    """数据根目录：config/ rules/ result/ 都直接挂在它下面。"""
    d = os.environ.get("WVD_SCAN_DATA")
    if not d:
        d = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
             else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.makedirs(d, exist_ok=True)
    return d


def _sub(name: str) -> str:
    p = os.path.join(data_dir(), name)
    os.makedirs(p, exist_ok=True)
    return p


def config_dir() -> str:
    return _sub("config")


def rules_dir() -> str:
    return _sub("rules")


def result_dir() -> str:
    return _sub("result")


# ---------- 读写 ----------

def _read(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def _sane(name: str) -> str:
    bad = '\\/:*?"<>|'
    s = "".join("_" if c in bad else c for c in str(name or "")).strip(" .")
    return s


# ---------- 过滤器笔记 ----------
# 单独文件：只在运行时由用户编辑写入，不随绿色版发布，升级替换 exe/web 时不会被覆盖。

FILTER_NOTE_KEYS = ("scan", "reform")
FILTER_NOTES_FILE = "filter_notes.json"


def load_filter_notes() -> dict:
    """返回 {"scan": "...", "reform": "..."}；文件不存在时返回空描述。"""
    d = _read(os.path.join(config_dir(), FILTER_NOTES_FILE), {})
    if not isinstance(d, dict):
        d = {}
    return {k: str(d.get(k) or "") for k in FILTER_NOTE_KEYS}


def save_filter_notes(key: str, text: str) -> dict:
    if key not in FILTER_NOTE_KEYS:
        raise ValueError("未知的过滤器笔记类型")
    with _LOCK:
        notes = load_filter_notes()
        notes[key] = str(text or "")
        _write(os.path.join(config_dir(), FILTER_NOTES_FILE), notes)
    return notes


# ---------- 设置 ----------

def load_settings() -> dict:
    return _read(os.path.join(config_dir(), "settings.json"), {}) or {}


def save_settings(cfg: dict) -> None:
    with _LOCK:
        _write(os.path.join(config_dir(), "settings.json"), cfg)


# ---------- 强化绿装（改造）配置 ----------

_REFORM_DEFAULT = {"reform_attrs": [], "stones": [], "max_try": 2,
                   "materials": [], "materials_at": 0, "materials_mode": ""}
# 前端「保存配置」只能写这些；materials 由扫描流程单独落盘，避免被普通保存覆盖
_REFORM_SAVE_FIELDS = ("reform_attrs", "stones", "max_try")


def load_reform_config() -> dict:
    cfg = _read(os.path.join(config_dir(), "reform.json"), {}) or {}
    out = dict(_REFORM_DEFAULT)
    out.update({k: v for k, v in cfg.items() if k in _REFORM_DEFAULT})
    return out


def save_reform_config(cfg: dict) -> dict:
    with _LOCK:
        out = load_reform_config()
        out.update({k: v for k, v in (cfg or {}).items() if k in _REFORM_SAVE_FIELDS})
        _write(os.path.join(config_dir(), "reform.json"), out)
    return out


def save_reform_materials(items: list, mode: str) -> dict:
    """保存素材扫描结果（含时间/模式），刷新页面后直接复用。"""
    with _LOCK:
        out = load_reform_config()
        out["materials"] = items
        out["materials_at"] = int(time.time())
        out["materials_mode"] = mode
        _write(os.path.join(config_dir(), "reform.json"), out)
    return out


# ---------- 扫描结果 ----------

def _current_path() -> str:
    return os.path.join(config_dir(), "current.json")


def current_file() -> str:
    """当前结果文件名（不含目录）；文件不存在时返回空串。"""
    cfg = _read(_current_path(), {}) or {}
    name = _sane(cfg.get("file") or "")
    if name and os.path.isfile(os.path.join(result_dir(), name)):
        return name
    return ""


def set_current(name: str) -> None:
    with _LOCK:
        _write(_current_path(), {"file": _sane(name)})


def new_scan_file(title: str = "") -> str:
    """新建一份空的扫描结果文件并设为当前，返回文件名。"""
    base = _sane(title) or ("scan_" + time.strftime("%Y%m%d_%H%M%S"))
    name = base + ".json"
    n = 1
    while os.path.exists(os.path.join(result_dir(), name)):
        n += 1
        name = f"{base}_{n}.json"
    with _LOCK:
        _write(os.path.join(result_dir(), name), [])
        _write(_current_path(), {"file": name})
    return name


def renumber(items: list[dict]) -> list[dict]:
    """按列表顺序把 idx 重排为 1..N（累加扫描会让序号重复）。"""
    for n, it in enumerate(items, 1):
        if isinstance(it, dict):
            it["idx"] = n
    return items


def save_results(items: list[dict]) -> str:
    """写到当前结果文件（没有就新建一份）。"""
    name = current_file() or new_scan_file()
    renumber(items)
    with _LOCK:
        _write(os.path.join(result_dir(), name), items)
    return name


def load_results() -> list[dict]:
    name = current_file()
    if not name:
        return []
    with _LOCK:
        data = _read(os.path.join(result_dir(), name), [])
    return renumber(data) if isinstance(data, list) else []


def clear_results() -> None:
    save_results([])


def list_results() -> list[dict]:
    """[{file, title, count, mtime}]，最近修改的在前。"""
    out = []
    for fn in os.listdir(result_dir()):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(result_dir(), fn)
        try:
            st = os.stat(p)
        except OSError:
            continue
        items = _read(p, [])
        out.append({"file": fn, "title": fn[: -len(".json")],
                    "count": len(items) if isinstance(items, list) else 0,
                    "mtime": st.st_mtime})
    out.sort(key=lambda x: -x["mtime"])
    return out


def open_result(name: str) -> list[dict]:
    """打开某份历史结果并设为当前。"""
    name = _sane(name)
    p = os.path.join(result_dir(), name)
    if not os.path.isfile(p):
        return []
    set_current(name)
    data = _read(p, [])
    return renumber(data) if isinstance(data, list) else []


# ---------- 迁移旧目录 ----------

def migrate() -> None:
    """旧版 data/ 下的 config/rules/result 及散落 json → 根目录同名子目录。"""
    root = data_dir()
    old = os.path.join(root, "data")
    if not os.path.isdir(old):
        return

    # 上一版结构：data/config、data/rules、data/result → 根目录
    for name in ("config", "rules", "result"):
        src_dir = os.path.join(old, name)
        if not os.path.isdir(src_dir):
            continue
        dst_dir = os.path.join(root, name)
        os.makedirs(dst_dir, exist_ok=True)
        for fn in os.listdir(src_dir):
            s, d = os.path.join(src_dir, fn), os.path.join(dst_dir, fn)
            if not os.path.isfile(s) or os.path.exists(d):
                continue
            try:
                os.replace(s, d)
            except OSError:
                pass

    # 更早期：散落在 data/ 根目录的 json
    for fn in ("aliases.json", "settings.json"):
        src = os.path.join(old, fn)
        dst = os.path.join(config_dir(), fn)
        if os.path.isfile(src) and not os.path.exists(dst):
            try:
                os.replace(src, dst)
            except OSError:
                pass

    legacy = os.path.join(old, "scan_result.json")
    if os.path.isfile(legacy) and not current_file():
        dst = os.path.join(result_dir(), "scan_result.json")
        try:
            if not os.path.exists(dst):
                os.replace(legacy, dst)
            if os.path.isfile(dst):
                set_current("scan_result.json")
        except OSError:
            pass
