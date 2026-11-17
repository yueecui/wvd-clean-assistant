# -*- coding: utf-8 -*-
"""自动强化白装（铁匠铺 → 装备强化 → 持有一览）。

目标：把列表里所有「白色」的装备逐个强化到 +5（不限制星级，白色就行）。

一轮（900x1600 实测）：
  从列表**当前所在位置**开始（不回到顶部）→ 点一件白装 → 右下「强化」连点
  → 跨过 +5 时弹「附加加护解锁 · 会心+n」，点「点击后关闭」关掉
  → +5 后名字变绿、行尾出现 MAX、按钮变红「前往合一」→ 换下一件
  → 当前屏幕没有可强化的白装了 → 往下滚一屏；滚不动就是到底了

识别要点：
  · 白 / 绿看名字文字颜色（parse.name_color）：白色=待强化，绿色=已到位。
    +5 一定会变绿，所以「白色」就是「还没到 +5」的充要条件，星级不用管；
    星级只在日志里显示，方便回看，不参与筛选。
  · 到顶判据：按钮区红色像素（正常 ≈13，前往合一 ≈9000）——差 700 倍，很稳；
    这一步绝不能靠 OCR，漏一个字就会点进「合一」界面
  · 强化值读名字后缀（match.split_reinforce），+0 时名字上没有后缀
  · 点按节奏：像玩家一样连点（比需要的次数多按 1 下做容错），而不是点一下确认一下；
    一次点按要几秒才落地，所以连点完再轮询名字里的 +N，等它跳到 5
    （或连续 SETTLE_QUIET 秒不动）再收手。到 +5 弹出的浮层会挡住点击、吃掉多余那一下，
    红色「前往合一」只在最后一下之后出现，那时已经停手，不会误碰。
"""
from __future__ import annotations

import io
import threading
import time

import numpy as np
from PIL import Image

import capture
import match
import parse
import perf

# ---------- 区域常量（按 900x1600 设计，其余分辨率按比例换算） ----------
BASE_W, BASE_H = 900, 1600

BTN = (0.510, 0.941)             # 底部「强化」/「前往合一」
RECT_BTN = (280, 1440, 680, 1600)   # 按钮区（判红）
RECT_POPUP = (300, 950, 620, 1030)  # 「附加加护解锁」弹窗里的「点击后关闭」
POPUP_TAP = (0.501, 0.621)          # 点它关掉解锁弹窗
RECT_TITLE = (0, 20, 900, 130)      # 顶部标题「装备强化」

RED_MIN = 2000      # 按钮区红色像素 ≥ 它 → 已经是红色「前往合一」
TARGET = 5          # 目标强化值
# 连点节奏：玩家也是连点「强化」，一次到底所需的次数连按下去就行。
# 到 +5 那一瞬间会弹「附加加护解锁」浮层，浮层会挡住点击、吃掉多余的点按，
# 所以连点比「点一次确认一次」既快又不容易误碰（红色「前往合一」只可能出现一次，
# 就是最后一下落地之后，那时我们已经停手了）。
TAP_GAP = 0.55      # 连点间隔
BURST_WAIT = 14.0   # 连点之后最多等多久让数值稳定
SETTLE_QUIET = 2.5  # 数值连续这么久没变化 → 认定这轮点按已经处理完
MAX_ROUNDS = 3      # 一件最多补点几轮（有点按被游戏丢掉时补）
MAX_TRIES = 2       # 同一个名字最多试几次（同名白装可能好几件，不能一次就拉黑）
MAX_STREAK = 4      # 连续这么多次没强化成功就往下翻一屏，避免原地打转
# 列表首行文字大概在 y=300（900x1600）。比这更靠上的行只露出一截，
# 点它的坐标会点到列表外面（选中的还是上一件），然后就会反复「已经是绿色，跳过」。
LIST_TOP = 300

TAP_WAIT = 0.5      # 点一行后等详情刷新
SCROLL_WAIT = 1.0
# 一屏最多显示 8 行，行距约 117px。一次拖 7 行、只留 1 行重叠做容错（原来拖 5 行太慢）。
# 注意手指位移 ≠ 滚动距离：实测拖 820px 只滚 765px（丢掉的约等于第一个 MOVE 段，
# 触摸滑动有起始死区），拖 878px 才滚 821px ≈ 7.0 行，所以这里写 878。
SCROLL_PX = 878
LIST_SWIPE = (150, 1200, 150, 1200 - SCROLL_PX)

TASK = "强化白装"


def _open(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def _rect(img: Image.Image, x0, y0, x1, y1) -> tuple[int, int, int, int]:
    sx, sy = img.width / BASE_W, img.height / BASE_H
    return (int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy))


def _red_pixels(img: Image.Image, box: tuple[int, int, int, int]) -> int:
    x0, y0, x1, y1 = _rect(img, *box)
    a = np.asarray(img.crop((x0, y0, x1, y1)), dtype=np.int16)[:, :, :3]
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    return int(((r > 120) & (r - g > 45) & (r - b > 35)).sum())


def at_max(img: Image.Image) -> bool:
    """按钮已经是红色「前往合一」= 这件到顶了（再点会进合一界面，绝不能点）。

    只认红色像素：正常「强化」按钮实测 13 个红像素，红色「前往合一」9373 个，
    差 700 倍，不需要 OCR（OCR 每轮跑一次太慢，而且漏字就会误点进合一界面）。
    """
    return _red_pixels(img, RECT_BTN) >= RED_MIN


def popup_open(img: Image.Image) -> bool:
    """「附加加护解锁」浮层：中间有一条「点击后关闭」。"""
    return any("点击后关闭" in l["text"] for l in parse.ocr_lines(img, _rect(img, *RECT_POPUP)))


def rows_of(png: bytes) -> list[dict]:
    """左侧持有一览：名称 / 星级 / 品质色 / 点击坐标。"""
    img = _open(png)
    W, H = img.size
    return parse.parse_list(img, parse._list_lines(img, W, H), W, H)


def _key(rows: list[dict]) -> tuple:
    return tuple((r["name"], r["stars"], r["color"], r["y"]) for r in rows)


class Enhancer:
    """自动强化白装：白装（不限星级）→ +5（变绿）→ 下一件。"""

    def __init__(self, adb: str, serial: str):
        self.adb = adb
        self.serial = serial
        self._thread: threading.Thread | None = None
        self._stop = False
        self._lock = threading.Lock()
        self._wh: tuple[int, int] | None = None
        self.logs: list[str] = []
        self.results: list[dict] = []
        self.status = self._fresh_status()

    # ---------- 基础 ----------
    @staticmethod
    def _fresh_status() -> dict:
        return {"running": False, "phase": "idle", "done": 0, "failed": 0,
                "skipped": 0, "current": "", "error": None, "task": TASK,
                "started_at": None, "finished_at": None,
                "elapsed": 0.0, "run_started_at": None}

    def _png(self) -> bytes:
        return capture.screenshot(self.adb, self.serial)

    def _list_top(self) -> int:
        """列表内容的上边界（按实际分辨率换算）。"""
        if self._wh is None:
            self._wh = self._img().size
        return int(LIST_TOP * self._wh[1] / BASE_H)

    def _tap(self, xy) -> None:
        capture.tap(self.adb, self.serial, int(xy[0]), int(xy[1]))

    def _tap_pct(self, base: tuple[float, float], img: Image.Image | None = None) -> None:
        """按比例点按钮。分辨率固定，尺寸缓存下来，省掉一次截图。"""
        if img is not None:
            self._wh = img.size
        elif self._wh is None:
            self._wh = self._img().size
        w, h = self._wh
        self._tap((int(w * base[0]), int(h * base[1])))

    def _img(self) -> Image.Image:
        return _open(self._png())

    def _log(self, msg: str) -> None:
        with self._lock:
            self.logs.append(msg)
            if len(self.logs) > 200:
                self.logs = self.logs[-200:]
        print("[enhance]", msg)

    def snapshot(self) -> dict:
        with self._lock:
            return {"status": dict(self.status), "logs": self.logs[-80:],
                    "results": list(self.results)}

    def stop(self) -> dict:
        self._stop = True
        with self._lock:
            if self.status.get("running"):
                self.status["phase"] = "stopping"
        return {"ok": True}

    # ---------- 页面 ----------
    def _on_enhance_page(self, png: bytes | None = None) -> bool:
        img = _open(png) if png else self._img()
        text = "".join(l["text"] for l in parse.ocr_lines(img, _rect(img, *RECT_TITLE)))
        return "强化" in text and "改造" not in text

    def _rows(self, png: bytes | None = None) -> list[dict]:
        return rows_of(png or self._png())

    def _swipe(self, x1, y1, x2, y2, ms: int = 900) -> None:
        if capture.drag(self.adb, self.serial, x1, y1, x2, y2,
                        steps=10, ms=max(300, int(ms * 0.7)), hold=0.25):
            return
        capture.run_adb(self.adb, self.serial, "shell", "input", "swipe",
                        str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(ms)))

    def _scroll(self) -> bool:
        """往上滚一屏；返回 False 表示滚不动了（到底）。"""
        before = _key(self._rows())
        self._swipe(*LIST_SWIPE)
        time.sleep(SCROLL_WAIT)
        after = _key(self._rows())
        return after != before

    # ---------- 单件 ----------
    def _burst(self, count: int) -> None:
        """有节奏地连点 count 次「强化」。"""
        for i in range(count):
            if self._stop:
                return
            self._tap_pct(BTN)
            if i + 1 < count:
                time.sleep(TAP_GAP)

    def _wait_settle(self, start_n: int) -> tuple[str, int]:
        """连点之后等数值稳定：返回 ("ok"/"max"/"stop"/"timeout", 当前强化值)。

        数值要几秒才逐级跳完，所以轮询只在「连点结束之后」做，且只 OCR 名字那一段；
        中途弹出「附加加护解锁」浮层就先关掉（浮层会挡住名字，也可能吃掉后面的点按）。
        """
        time.sleep(0.8)
        end = time.time() + BURST_WAIT
        last = start_n
        quiet_since = time.time()
        while time.time() < end:
            if self._stop:
                return "stop", last
            png = self._png()
            img = _open(png)
            if popup_open(img):
                self._log("· 关闭「附加加护解锁」弹窗")
                self._tap_pct(POPUP_TAP, img)
                time.sleep(0.7)
                continue                      # 关掉后再看一次，确认到底了没
            if at_max(img):
                name = parse.detail_name_only(png)
                return "max", (match.split_reinforce(name)[1] if name else last)
            name = parse.detail_name_only(png)
            n = match.split_reinforce(name)[1] if name else last
            if n >= TARGET:
                return "ok", n
            if n != last:
                last = n
                quiet_since = time.time()
            elif time.time() - quiet_since > SETTLE_QUIET:
                return "ok", n                # 跳完了，还没到 5（有点按被丢掉）
            time.sleep(0.3)
        return "timeout", last

    def _enhance_one(self, row: dict) -> tuple[str, int, int, int]:
        """把一件强化到 +5；返回 ("ok"/"skip"/"fail", 原强化值, 新强化值, 星级)。

        列表里只做粗筛（白色 + 星星面积够 4★），点开详情后以详情为准：
        星级、颜色、当前 +N 都从详情读，避免列表星星数错把 3★ 当成 4★。
        """
        self._tap(row["tap"])
        time.sleep(TAP_WAIT)
        d = None
        for _ in range(3):
            d = parse.parse_detail_only(self._png())
            if d and d.get("name") and d.get("stars"):
                break
            d = None
            time.sleep(0.4)
        if not d:
            self._log(f"✗ 「{row['name']}」详情读不到，跳过")
            return "fail", 0, 0, 0
        name, n = match.split_reinforce(d["name"])
        stars = d["stars"]
        # 只看颜色：+5 一定变绿，所以「白色」就等于「还没到 +5」，星级不限
        # （用户想强化低星白装也随他）。也不校验「详情名字 == 列表名字」，
        # 这游戏字体偏糊，同一个名字两边 OCR 经常差一个字（脆之忍足袋 / 之忍足袋），
        # 一比就误跳过；点歪则是点到绿装，会被下面这道颜色校验拦住。
        if d.get("color") and d["color"] != "white":
            self._log(f"· 「{name}」已经是{d['color']}色，跳过")
            return "skip", n, n, stars
        if n >= TARGET:
            self._log(f"· 「{name}」已 +{n}，跳过")
            return "skip", n, n, stars
        if at_max(self._img()):
            self._log(f"· 「{name}」按钮已是「前往合一」，跳过")
            return "skip", n, n, stars

        start_n = n
        rounds = 0
        while not self._stop and n < TARGET and rounds < MAX_ROUNDS:
            # 多按 1 下做容错：游戏时不时会吞掉一下（例如 +0 就按 6 下）。
            # 到 +5 弹的「附加加护解锁」浮层会挡住点击，多出来那一下落不到红按钮上。
            need = TARGET - n + 1
            self._burst(need)                # 连点，不再一下一下确认
            rounds += 1
            got, n2 = self._wait_settle(n)
            if got == "stop":
                # 用户点了停止：这一件不算失败，下次接着强化
                return "stop", start_n, n, stars
            if got == "max":
                n = max(n, n2)
                break
            if n2 <= n:
                # 一下都没生效：别硬点，多半是金币不够或按钮不可点
                self._log(f"⚠ 「{name}」连点 {need} 次强化没有变化，跳过（金币不够？）")
                return "fail", start_n, n, stars
            n = n2
        if self._stop and n < TARGET:
            # 停止键是在读详情 / 准备连点的时候按下的，一件都没点：不算失败
            return "stop", start_n, n, stars
        with self._lock:
            self.status["current"] = f"{name} +{n}"
        ok = n >= TARGET
        self._log(f"{'✔' if ok else '⚠'} {name} {stars}★ +{start_n} → +{n}")
        return ("ok" if ok else "fail"), start_n, n, stars

    # ---------- 主流程 ----------
    def start(self) -> dict:
        if self._thread and self._thread.is_alive():
            return {"ok": False, "error": "强化任务在运行中"}
        self._stop = False
        ts = time.time()
        with self._lock:
            self.logs = []
            self.results = []
            self.status = self._fresh_status()
            self.status.update({"running": True, "phase": "start", "started_at": ts,
                                "elapsed": 0.0, "run_started_at": ts})
        self._log(f"[{time.strftime('%H:%M:%S', time.localtime(ts))}] {TASK}开始")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return {"ok": True}

    def _run(self) -> None:
        perf.begin_task()
        try:
            png = self._png()
            if not self._on_enhance_page(png):
                self._fail("当前不在「铁匠铺 → 装备强化 → 持有一览」界面：请先停到装备强化列表")
                return
            if not rows_of(png):
                self._fail("没识别到装备列表，请确认停在「装备强化 → 持有一览」")
                return
            self._log("界面确认：铁匠铺 · 装备强化 · 持有一览")
            self._log("从当前列表位置开始（不回到顶部），只在没有待强化白装时往下翻页")
            with self._lock:
                self.status["phase"] = "running"

            # 同名白装可能是好几件（+0 时名字里没有后缀，区分不了），强化成功后
            # 那件会变绿，下一轮自然不会再把挑出来，同名的那几件依次处理。
            # 失败过的名字按 名字→次数 记着，试满 MAX_TRIES 次才放弃，
            # 计数只认名字（列表星级 OCR 不准，带上星级会导致去重永远不生效）。
            tries: dict[str, int] = {}
            streak = 0                       # 连续没强化成功的次数
            fails = 0
            while not self._stop:
                rows = self._rows()
                pick = None
                for r in rows:
                    # 只要名字是白色的就做：+5 一定变绿，白色就等于没到 +5
                    if r["color"] != "white":
                        continue
                    if r["y"] < self._list_top():
                        continue             # 顶部只露一截的行点了会点到别人
                    if tries.get(match.split_reinforce(r["name"])[0], 0) >= MAX_TRIES:
                        continue
                    pick = r
                    break
                if pick is None:
                    with self._lock:
                        self.status["phase"] = "scrolling"
                    if not self._scroll():
                        self._log("已到列表末尾，没有可强化的白装了")
                        break
                    continue
                base = match.split_reinforce(pick["name"])[0]
                self._set_current(base)
                res, before, after, stars = self._enhance_one(pick)
                if res == "stop":
                    self._log(f"· 已停止，「{base}」当前 +{after}，下次接着强化")
                    break
                if res == "ok":
                    with self._lock:
                        self.status["done"] += 1
                        self.results.append({"name": base, "stars": stars,
                                             "before": before, "after": after,
                                             "at": time.time()})
                    tries.pop(base, None)
                    fails = 0
                    streak = 0
                elif res == "skip":
                    with self._lock:
                        self.status["skipped"] += 1
                    tries[base] = tries.get(base, 0) + 1
                    streak += 1
                else:
                    with self._lock:
                        self.status["failed"] += 1
                    tries[base] = tries.get(base, 0) + 1
                    fails += 1
                    streak += 1
                    if fails >= 3:
                        self._log("连续 3 件失败，可能金币不足或界面变了，先停下")
                        break
                # 一直点同一件又没效果：多半是挑到了顶部半截行，往下翻一屏换一批
                if streak >= MAX_STREAK:
                    self._log(f"· 连续 {streak} 次没强化成功，先往下翻一屏")
                    if not self._scroll():
                        self._log("已到列表末尾，没有可强化的白装了")
                        break
                    streak = 0
                perf.idle_sleep()
            self._finish()
        except Exception as e:  # noqa: BLE001
            self._fail(f"执行异常: {e}")
        finally:
            perf.end_task()

    def _set_current(self, text: str) -> None:
        with self._lock:
            self.status["current"] = text

    def _fail(self, msg: str) -> None:
        self._end("error", msg, msg)

    def _finish(self) -> None:
        with self._lock:
            done = self.status["done"]
            failed = self.status["failed"]
            skipped = self.status["skipped"]
        body = f"强化 {done} 件到 +{TARGET}"
        if failed:
            body += f"，失败 {failed} 件"
        if skipped:
            body += f"，跳过 {skipped} 件"
        if self._stop:
            self._end("stopped", f"已停止：{body}")
        else:
            self._end("done", f"完成：{body}")

    def _end(self, phase: str, msg: str, error: str | None = None) -> None:
        import notify

        ts = time.time()
        with self._lock:
            t0 = self.status.get("run_started_at")
            if t0:
                self.status["elapsed"] = float(self.status.get("elapsed") or 0.0) + max(0.0, ts - t0)
            self.status.update({"running": False, "phase": phase, "current": "",
                                "finished_at": ts, "error": error, "run_started_at": None})
            task = self.status.get("task") or TASK
            total_sec = self.status.get("elapsed") or 0.0
        total = _duration(total_sec)
        self._log(f"[{time.strftime('%H:%M:%S', time.localtime(ts))}] {msg} · 运行 {total}")
        notify.task_finished(task, phase, msg, total)


def _duration(seconds: float) -> str:
    n = max(0, int(seconds))
    h, m, s = n // 3600, (n // 60) % 60, n % 60
    if h:
        return f"{h}小时{m}分{s}秒"
    return f"{m}分{s}秒" if m else f"{s}秒"
