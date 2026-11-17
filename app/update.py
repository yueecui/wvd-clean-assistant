# -*- coding: utf-8 -*-
"""自动更新：资源（masterdata / icons）增量 + 程序（exe / web）整包自替换。

默认不联网：只有调用 check() 才拉 manifest。
环境变量（便于测试 / 离线）：
    WVD_UPDATE_MANIFEST  manifest 地址（http(s):// 或本地文件路径）
    WVD_UPDATE_BASE      资源下载基址（覆盖 manifest.resources.base，可为本地目录）
    WVD_UPDATE_REPO      GitHub owner/repo
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

import master
import store
import version

_lock = threading.Lock()
_status = {"running": False, "phase": "idle", "message": "", "done": 0, "total": 0, "error": None}
_info: dict = {}
_pending_bat = ""

MANIFEST_ENV = "WVD_UPDATE_MANIFEST"
BASE_ENV = "WVD_UPDATE_BASE"


def manifest_url() -> str:
    env = os.environ.get(MANIFEST_ENV, "").strip()
    if env:
        return env
    repo = os.environ.get("WVD_UPDATE_REPO", "").strip() or version.DEFAULT_REPO
    return f"https://raw.githubusercontent.com/{repo}/main/manifest.json"


def load_state() -> dict:
    p = os.path.join(store.config_dir(), "update.json")
    d = store._read(p, {})
    return d if isinstance(d, dict) else {}


def save_state(state: dict) -> None:
    store._write(os.path.join(store.config_dir(), "update.json"), state)


def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def local_hashes() -> dict[str, str]:
    """扫描本地资源，返回 {相对路径: sha256}。"""
    root = master.resource_root()
    out: dict[str, str] = {}
    for sub, ext in (("icons", ".png"), ("masterdata", ".json")):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            if fn.lower().endswith(ext) and os.path.isfile(p):
                out[f"{sub}/{fn}"] = _hash_file(p)
    return out


def _fetch(url: str, timeout: int = 15) -> bytes:
    if url.lower().startswith(("http://", "https://")):
        req = urllib.request.Request(url, headers={"User-Agent": "wvd-clean-update"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    with open(url, "rb") as f:
        return f.read()


def fetch_manifest() -> tuple[dict, str]:
    """优先远端，拉取失败时回退到随包 / 入仓的基线 manifest。

    返回 (manifest, 实际来源)，前端据此显示数据来自网络还是本地基线。
    """
    url = manifest_url()
    try:
        m = json.loads(_fetch(url).decode("utf-8-sig"))
        if not isinstance(m, dict) or m.get("schema") != 1:
            raise ValueError("manifest 格式不认识（schema 需要为 1）")
        return m, url
    except Exception:  # noqa: BLE001
        local = os.path.join(master.resource_root(), "manifest.json")
        m = json.loads(_fetch(local).decode("utf-8-sig"))
        if not isinstance(m, dict) or m.get("schema") != 1:
            raise ValueError("manifest 格式不认识（schema 需要为 1）")
        return m, local


def _vtuple(s):
    try:
        return tuple(int(x) for x in str(s or "").split("."))
    except ValueError:
        return (0,)


def _set(phase, message="", done=0, total=0, error=None, running=None):
    with _lock:
        _status["phase"] = phase
        _status["message"] = message
        _status["done"] = done
        _status["total"] = total
        _status["error"] = error
        if running is not None:
            _status["running"] = running


def busy() -> bool:
    with _lock:
        return _status["running"]


def snapshot() -> dict:
    with _lock:
        st = dict(_status)
    return {"status": st, "info": _info,
            "app_version": version.VERSION, "state": load_state(),
            "manifest": manifest_url()}


def check() -> dict:
    """拉取 manifest 与本地对比；同步执行，结果缓存供 apply 使用。"""
    global _info
    if busy():
        raise RuntimeError("已有更新任务在进行中")
    _set("checking", "正在检查更新……", running=True)
    try:
        m, source = fetch_manifest()
        st = load_state()
        hashes = local_hashes()
        res = m.get("resources") or {}
        remote: dict[str, str] = {}
        for k, v in (res.get("icons") or {}).items():
            remote[f"icons/{k}"] = v
        for k, v in (res.get("masterdata") or {}).items():
            remote[f"masterdata/{k}"] = v

        to_add = sorted(k for k in remote if k not in hashes)
        to_update = sorted(k for k in remote if k in hashes and hashes[k] != remote[k])
        app = m.get("app") or {}
        info = {
            "checked_at": int(time.time()),
            "source": source,
            "local_app": version.VERSION,
            "local_resource": st.get("resource_version", ""),
            "remote_app": app.get("version", ""),
            "remote_resource": res.get("version", ""),
            "app_available": bool(app.get("url")) and _vtuple(app.get("version")) > _vtuple(version.VERSION),
            "resource_available": bool(to_add or to_update),
            "to_add": to_add,
            "to_update": to_update,
            "notes": app.get("notes", ""),
            "asset": app.get("asset", ""),
        }
        _info = info
        _set("done", "检查完成", running=False)
        return info
    except Exception as e:  # noqa: BLE001
        _info = {"error": str(e)}
        _set("error", error=str(e), running=False)
        raise


def _safe_key(key: str, manifest_res: dict) -> str:
    """资源 key 形如 icons/xxx.png、masterdata/xxx.json；返回对应远端哈希。"""
    parts = key.split("/")
    if len(parts) != 2 or parts[0] not in ("icons", "masterdata") \
            or ".." in parts or "\\" in key or not parts[1]:
        raise ValueError(f"非法的资源路径: {key}")
    table = manifest_res.get(parts[0]) or {}
    h = table.get(parts[1])
    if not h:
        raise ValueError(f"manifest 缺少哈希: {key}")
    return h


def _download(src: str, dest: str, expect_sha: str = "") -> None:
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    data = _fetch(src, timeout=90)
    if expect_sha and hashlib.sha256(data).hexdigest() != expect_sha:
        raise RuntimeError("下载内容校验失败，未覆盖本地文件")
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)


def sync_resources(progress=None) -> dict:
    """同步执行资源增量更新；progress(i, total, key) 可选。返回统计。

    后端接口与命令行 bat 共用这一份逻辑。
    """
    global _info
    m, source = fetch_manifest()
    res = m.get("resources") or {}
    base = os.environ.get(BASE_ENV, "").strip() or res.get("base", "")
    if not base:
        raise RuntimeError("manifest 没有资源下载地址")
    if not base.endswith(("/", "\\")):
        base += "/"
    hashes = local_hashes()
    remote: dict[str, str] = {}
    for k, v in (res.get("icons") or {}).items():
        remote[f"icons/{k}"] = v
    for k, v in (res.get("masterdata") or {}).items():
        remote[f"masterdata/{k}"] = v
    added = sorted(k for k in remote if k not in hashes)
    updated = sorted(k for k in remote if k in hashes and hashes[k] != remote[k])
    files = added + updated
    root = master.resource_root()
    for i, key in enumerate(files, 1):
        if progress:
            progress(i, len(files), key)
        h = _safe_key(key, res)
        _download(base + key, os.path.join(root, *key.split("/")), expect_sha=h)
    st = load_state()
    st["resource_version"] = res.get("version", "")
    st["hashes"] = local_hashes()
    st["resources_at"] = int(time.time())
    save_state(st)
    master.invalidate()
    if isinstance(_info, dict):
        _info["resource_available"] = False
        _info["to_add"] = []
        _info["to_update"] = []
        _info["local_resource"] = res.get("version", "")
    return {"added": len(added), "updated": len(updated), "files": files,
            "version": res.get("version", ""), "source": source}


def apply_resources() -> None:
    """在后台线程里同步资源；进度写进 _status 供前端轮询。"""
    if busy():
        raise RuntimeError("已有更新任务在进行中")

    def run() -> None:
        try:
            _set("resources", "检查资源更新……", running=True)
            r = sync_resources(
                lambda i, n, key: _set("resources", f"下载 {key}", i, n, running=True))
            n = r["added"] + r["updated"]
            _set("done", f"资源更新完成：新增 {r['added']} 个，变更 {r['updated']} 个",
                 n, n, running=False)
        except Exception as e:  # noqa: BLE001
            _set("error", error=str(e), running=False)

    threading.Thread(target=run, daemon=True).start()


def _safe_extract(zf: zipfile.ZipFile, dest: str) -> None:
    for info in zf.infolist():
        parts = [p for p in info.filename.replace("\\", "/").split("/") if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            raise ValueError(f"压缩包含非法路径: {info.filename}")
        target = os.path.join(dest, *parts)
        if info.is_dir():
            os.makedirs(target, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def _bat(appdir: str, staging: str) -> str:
    """等待本进程退出 → 替换 exe 与 web → 重启。bat 内全英文，避免编码问题。"""
    pid = os.getpid()
    lines = [
        "@echo off",
        f"set PID={pid}",
        ":wait_pid",
        'tasklist /FI "PID eq %PID%" 2>nul | findstr /I "%PID%" >nul',
        "if errorlevel 1 goto do_update",
        "ping -n 2 127.0.0.1 >nul",
        "goto wait_pid",
        ":do_update",
        f'set "APP={appdir}"',
        f'set "STG={staging}"',
        'if not exist "%STG%\\wvd-clean.exe" goto no_exe',
        'copy /y "%APP%\\wvd-clean.exe" "%APP%\\wvd-clean.exe.bak" >nul',
        'copy /y "%STG%\\wvd-clean.exe" "%APP%\\wvd-clean.exe" >nul',
        'if exist "%STG%\\web\\dist" xcopy /e /i /y "%STG%\\web\\dist" "%APP%\\web\\dist" >nul',
        'rd /s /q "%STG%" >nul 2>&1',
        'start "" "%APP%\\wvd-clean.exe"',
        'del /f /q "%~f0"',
        "exit /b 0",
        ":no_exe",
        "echo staged exe not found",
        'del /f /q "%~f0"',
    ]
    p = os.path.join(appdir, "apply_update.bat")
    with open(p, "w", encoding="ascii", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return p


def prepare_app() -> dict:
    """下载程序包 → 校验 → 解压到 staging → 生成替换脚本。仅绿色版可用。"""
    global _pending_bat
    if not getattr(sys, "frozen", False):
        return {"ok": False, "error": "源码运行模式不支持程序自更新；请用 git 拉取代码，或在绿色版中使用"}
    if busy():
        return {"ok": False, "error": "已有更新任务在进行中"}
    _set("app", "正在下载程序包", running=True)
    try:
        m, _ = fetch_manifest()
        app = m.get("app") or {}
        url = app.get("url")
        if not url:
            _set("done", "manifest 没有程序下载地址", running=False)
            return {"ok": False, "error": "manifest 没有程序下载地址"}
        ver = app.get("version") or "unknown"
        root = master.resource_root()
        dl = os.path.join(root, "update", "downloads")
        staging = os.path.join(root, "update", "staging", ver)
        os.makedirs(dl, exist_ok=True)
        if os.path.isdir(staging):
            shutil.rmtree(staging)
        zip_path = os.path.join(dl, app.get("asset") or f"wvd-clean-{ver}.zip")
        _set("app", "下载程序包……", running=True)
        with open(zip_path + ".part", "wb") as f:
            f.write(_fetch(url, timeout=300))
        os.replace(zip_path + ".part", zip_path)
        if app.get("sha256") and _hash_file(zip_path) != app["sha256"].lower():
            raise RuntimeError("程序包校验失败")
        _set("app", "解压程序包……", running=True)
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, staging)
        _pending_bat = _bat(root, staging)
        _set("done", f"程序包已就绪（{ver}），重启后完成更新", running=False)
        return {"ok": True, "need_restart": True, "version": ver}
    except Exception as e:  # noqa: BLE001
        _set("error", error=str(e), running=False)
        return {"ok": False, "error": str(e)}


def _launch_and_exit(bat: str) -> None:
    time.sleep(0.8)
    try:
        subprocess.Popen(["cmd", "/c", bat], shell=False)
    except Exception:  # noqa: BLE001
        pass
    os._exit(0)


def restart() -> dict:
    """启动替换脚本并退出当前进程。"""
    if not _pending_bat or not os.path.isfile(_pending_bat):
        return {"ok": False, "error": "没有待应用的程序更新"}
    threading.Thread(target=_launch_and_exit, args=(_pending_bat,), daemon=True).start()
    return {"ok": True}
