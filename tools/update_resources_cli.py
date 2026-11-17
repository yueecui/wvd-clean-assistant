# -*- coding: utf-8 -*-
"""命令行更新游戏资源（masterdata / icons），可独立运行，不依赖后端服务。

两种来源，由 WVD_UNPACK 环境变量决定（update_resources.bat 顶部可配置）：
  - 已设置且指向解包 out 目录：从本地解包目录同步资源进项目，并刷新 manifest.json
  - 未设置：从 GitHub（manifest.resources.base）增量下载资源到项目

手动执行：
    python tools/update_resources_cli.py
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

import update  # noqa: E402

MASTER_FILES = ("Equipment.json", "EquipmentType.json",
                "EquipmentEffect.json", "EquipmentEffectUpgrade.json")
UNPACK_ICONS = os.path.join("assets.lib", "sprite", "ListIcon")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def same_file(src: str, dst: str) -> bool:
    if not os.path.isfile(dst) or os.path.getsize(src) != os.path.getsize(dst):
        return False
    return sha256(src) == sha256(dst)


def sync_from_unpack(unpack_dir: str) -> tuple[int, int, int]:
    """从解包 out 目录增量同步资源进项目，返回 (新增, 更新, 未变)。"""
    src_master = os.path.join(unpack_dir, "masterdata")
    src_icons = os.path.join(unpack_dir, UNPACK_ICONS)
    if not os.path.isfile(os.path.join(src_master, "Equipment.json")):
        raise RuntimeError(f"解包目录缺少 masterdata/Equipment.json：{unpack_dir}")
    if not os.path.isdir(src_icons):
        raise RuntimeError(f"解包目录缺少 {UNPACK_ICONS}：{unpack_dir}")

    counts = {"add": 0, "upd": 0, "same": 0}

    def copy_changed(src: str, dst: str, label: str) -> None:
        if same_file(src, dst):
            counts["same"] += 1
            return
        existed = os.path.isfile(dst)
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        tmp = dst + ".part"
        with open(src, "rb") as fsrc, open(tmp, "wb") as fdst:
            while True:
                chunk = fsrc.read(1 << 20)
                if not chunk:
                    break
                fdst.write(chunk)
        os.replace(tmp, dst)
        if existed:
            counts["upd"] += 1
            print(f"  更新 {label}")
        else:
            counts["add"] += 1
            print(f"  新增 {label}")

    for fn in MASTER_FILES:
        src = os.path.join(src_master, fn)
        if os.path.isfile(src):
            copy_changed(src, os.path.join(ROOT, "masterdata", fn), f"masterdata/{fn}")

    for fn in sorted(os.listdir(src_icons)):
        if not fn.lower().endswith(".png"):
            continue
        src = os.path.join(src_icons, fn)
        if os.path.isfile(src):
            copy_changed(src, os.path.join(ROOT, "icons", fn), f"icons/{fn}")

    return counts["add"], counts["upd"], counts["same"]


def refresh_manifest() -> None:
    """重算 manifest.json 的 resources 段（app 段保留）。"""
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "publish_resources.py")],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"刷新 manifest 失败：{(r.stderr or r.stdout).strip()}")
    for line in (r.stdout or "").splitlines():
        print(line)


def from_unpack(unpack_dir: str) -> int:
    print(f"来源：本地解包目录 {unpack_dir}")
    try:
        added, updated, skipped = sync_from_unpack(unpack_dir)
        print(f"同步完成：新增 {added} 个，更新 {updated} 个，未变 {skipped} 个")
        if added or updated:
            print("正在刷新 manifest.json ...")
            refresh_manifest()
            print()
            print("下一步：把资源推到仓库（CI 会用新 commit 重写 manifest 的资源基址）")
            print("  git add masterdata icons manifest.json")
            print('  git commit -m "chore: update game resources"')
            print("  git push")
        else:
            print("资源无变化，manifest 未改动，无需提交。")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"同步失败：{e}")
        return 1


def from_github() -> int:
    print("来源：GitHub（manifest.resources.base）")
    print("正在检查资源更新……")
    try:
        def progress(i: int, n: int, key: str) -> None:
            print(f"  [{i}/{n}] {key}")

        r = update.sync_resources(progress=progress)
        n = r["added"] + r["updated"]
        if n:
            print(f"完成：新增 {r['added']} 个，变更 {r['updated']} 个，资源版本 {r['version']}")
        else:
            print(f"资源已是最新（版本 {r['version']}）")
        print(f"数据来源：{r['source']}")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"更新失败：{e}")
        return 1


def main() -> int:
    unpack = os.environ.get("WVD_UNPACK", "").strip().strip('"')
    if unpack:
        return from_unpack(unpack)
    return from_github()


if __name__ == "__main__":
    sys.exit(main())
