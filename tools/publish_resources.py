# -*- coding: utf-8 -*-
"""生成 / 更新仓库根的 manifest.json（发布用，普通用户无需运行）。

    python tools/publish_resources.py                       # 只刷新 resources 段
    python tools/publish_resources.py --resource-version 20261118
    python tools/publish_resources.py --commit <sha>        # 指定资源快照 commit，写进 base

    # 发新版时同时更新 app 段：
    python tools/publish_resources.py --app-version 1.1.0 \
        --app-asset wvd-clean-v1.1.0.zip --app-sha <sha256> \
        --app-url https://github.com/.../releases/download/v1.1.0/wvd-clean-v1.1.0.zip \
        --notes "修复了xxx"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

if hasattr(sys.stdout, "reconfigure"):  # Windows runner 默认 cp1252，中文 print 会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
import version  # noqa: E402

REPO = os.environ.get("WVD_UPDATE_REPO", "").strip() or version.DEFAULT_REPO
MANIFEST = os.path.join(ROOT, "manifest.json")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=5)
        return (out.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def scan(folder: str, ext: str) -> dict[str, str]:
    d = os.path.join(ROOT, folder)
    if not os.path.isdir(d):
        return {}
    return {fn: sha256(os.path.join(d, fn))
            for fn in sorted(os.listdir(d))
            if fn.lower().endswith(ext) and os.path.isfile(os.path.join(d, fn))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", default="", help="资源快照 commit（默认取当前 HEAD；无 git 时用 main）")
    ap.add_argument("--resource-version", default=time.strftime("%Y%m%d"))
    ap.add_argument("--app-version", default="")
    ap.add_argument("--app-asset", default="")
    ap.add_argument("--app-sha", default="")
    ap.add_argument("--app-url", default="")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    old: dict = {}
    if os.path.isfile(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as f:
            try:
                old = json.load(f)
            except Exception:  # noqa: BLE001
                old = {}

    commit = args.commit or git_head() or "main"
    m = {
        "schema": 1,
        "app": dict(old.get("app") or {}),
        "resources": {
            "version": args.resource_version,
            "base": f"https://raw.githubusercontent.com/{REPO}/{commit}/",
            "masterdata": scan("masterdata", ".json"),
            "icons": scan("icons", ".png"),
        },
    }
    if args.app_version:
        m["app"] = {
            "version": args.app_version,
            "asset": args.app_asset,
            "url": args.app_url,
            "sha256": args.app_sha,
            "size": (old.get("app") or {}).get("size", 0),
            "notes": args.notes,
        }
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"manifest updated: {MANIFEST}")
    print(f"  res_ver={m['resources']['version']}  icons={len(m['resources']['icons'])}  "
          f"masterdata={len(m['resources']['masterdata'])}  base={m['resources']['base']}")


if __name__ == "__main__":
    main()
