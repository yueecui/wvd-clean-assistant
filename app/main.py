# -*- coding: utf-8 -*-
"""WVD 装备梳理（截图方案）—— 本地服务 + 网页 UI。

源码运行:  python app/main.py            # http://127.0.0.1:23456/（开发环境）
绿色版:    wvd-clean.exe                 # http://127.0.0.1:23333/，adb.exe 放 exe 同目录
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture  # noqa: E402
import enhance  # noqa: E402
import master   # noqa: E402
import match    # noqa: E402
import parse    # noqa: E402
import perf     # noqa: E402
import refine   # noqa: E402
import reform   # noqa: E402
import rules    # noqa: E402
import scan     # noqa: E402
import sell     # noqa: E402
import store    # noqa: E402

HOST = "127.0.0.1"
# 源码（开发环境）默认 23456，打包的绿色版默认 23333；WVD_SCAN_PORT 可覆盖
_DEFAULT_PORT = 23333 if getattr(sys, "frozen", False) else 23456
PORT = int(os.environ.get("WVD_SCAN_PORT", str(_DEFAULT_PORT)))


def _pick_static() -> str:
    """优先 serve Vue 构建产物 web/dist，回退到 app/static。

    打包后 __file__ 落在 PyInstaller 的临时目录，需额外探测 _MEIPASS 与 exe 同目录。
    """
    app_dir = os.path.dirname(os.path.abspath(__file__))
    roots = [os.path.dirname(app_dir), app_dir]
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            roots.insert(0, meipass)
        roots.insert(0, os.path.dirname(os.path.abspath(sys.executable)))
    for root in roots:
        for d in (os.path.join(root, "web", "dist"),
                  os.path.join(root, "static"),
                  os.path.join(root, "app", "static")):
            if os.path.isfile(os.path.join(d, "index.html")):
                return d
    return os.path.join(app_dir, "static")


STATIC_DIR = os.environ.get("WVD_SCAN_STATIC") or _pick_static()

_cfg = {"adb": None, "serial": capture.DEFAULT_SERIAL,
        "cpu_mode": perf.DEFAULT_MODE,
        "ocr_queue": scan.QUEUE_MAX_DEFAULT}   # 流水线队列上限 1~8
_scanner: scan.Scanner | None = None


def scanner() -> scan.Scanner:
    global _scanner
    adb = capture.resolve_adb(_cfg.get("adb"))
    if _scanner is None or _scanner.adb != adb or _scanner.serial != _cfg["serial"]:
        _scanner = scan.Scanner(adb, _cfg["serial"])
    _scanner.queue_max = scan.clamp_queue_max(_cfg.get("ocr_queue"))
    return _scanner


_reformer: reform.Reformer | None = None


def reformer() -> reform.Reformer:
    global _reformer
    adb = capture.resolve_adb(_cfg.get("adb"))
    if _reformer is None or _reformer.adb != adb or _reformer.serial != _cfg["serial"]:
        _reformer = reform.Reformer(adb, _cfg["serial"])
    return _reformer


_refiner: refine.Refiner | None = None


def refiner() -> refine.Refiner:
    global _refiner
    adb = capture.resolve_adb(_cfg.get("adb"))
    if _refiner is None or _refiner.adb != adb or _refiner.serial != _cfg["serial"]:
        _refiner = refine.Refiner(adb, _cfg["serial"])
    return _refiner


_seller: sell.Seller | None = None


def seller() -> sell.Seller:
    global _seller
    adb = capture.resolve_adb(_cfg.get("adb"))
    if _seller is None or _seller.adb != adb or _seller.serial != _cfg["serial"]:
        _seller = sell.Seller(adb, _cfg["serial"])
    return _seller


_enhancer: enhance.Enhancer | None = None


def enhancer() -> enhance.Enhancer:
    global _enhancer
    adb = capture.resolve_adb(_cfg.get("adb"))
    if _enhancer is None or _enhancer.adb != adb or _enhancer.serial != _cfg["serial"]:
        _enhancer = enhance.Enhancer(adb, _cfg["serial"])
    return _enhancer


def reform_config() -> dict:
    """返回配置（含已保存的素材扫描结果），并按当前数值表刷新星级。"""
    cfg = store.load_reform_config()
    cfg["stones"] = reform.refresh_stones(cfg.get("stones") or [])
    cfg["materials"] = reform.refresh_stones(cfg.get("materials") or [])
    cfg["stone_grid"] = reform.stone_grid()
    return cfg


def open_in_explorer(path: str) -> None:
    """在文件管理器里打开目录。"""
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        import subprocess
        subprocess.Popen(["xdg-open", path])


def pick_adb_exe() -> str:
    """弹系统文件选择框让用户挑 adb.exe（Windows），取消/失败返回空串。"""
    if os.name != "nt":
        return ""
    ps = ("Add-Type -AssemblyName System.Windows.Forms;"
          "$d = New-Object System.Windows.Forms.OpenFileDialog;"
          "$d.Title = 'Select adb.exe';"
          "$d.Filter = 'adb.exe|adb.exe|Executable (*.exe)|*.exe|All files (*.*)|*.*';"
          "if ($d.ShowDialog() -eq 'OK') { $d.FileName }")
    try:
        import subprocess
        out = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps],
                             capture_output=True, text=True, timeout=300)
        return (out.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def export_csv() -> str:
    import csv
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["序号", "名称", "阶", "类型", "强化", "星级", "附加加护", "锁定",
                "规则", "评分", "校验"])
    for it in store.load_results():
        w.writerow([it.get("idx"), it.get("name"), it.get("rank") or "",
                    it.get("type_name") or "", it.get("reinforce") or "",
                    it.get("stars"), " / ".join(it.get("blessings") or []),
                    "是" if it.get("locked") else "",
                    it.get("rule_name") or "", it.get("score", ""),
                    {"ok": "匹配", "alias": "校准", "fuzzy": "待确认", "none": "未匹配"}
                    .get(it.get("match_status", ""), "")])
    return out.getvalue()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n > 0 else {}

    def _rescore_all(self) -> int:
        """规则变动后重算：内存中的扫描结果 + 已落盘结果。"""
        rs = rules.load_rules()
        n = 0
        live = scanner().items
        if live:
            rules.apply(live, rs)
            n += len(live)
        saved = store.load_results()
        if saved:
            rules.apply(saved, rs)
            store.save_results(saved)
            n += len(saved)
        return n

    def _serve_icon(self, name: str) -> None:
        p = master.icon_path(name.split("?")[0])
        if not p or not os.path.isfile(p):
            self._send(404, b"not found", "image/png")
            return
        with open(p, "rb") as f:
            self._send(200, f.read(), "image/png")

    def _static(self, rel: str) -> None:
        rel = rel.lstrip("/") or "index.html"
        path = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not path.startswith(os.path.normpath(STATIC_DIR)) or not os.path.isfile(path):
            self._send(404, b"not found", "text/plain")
            return
        ctype = {"html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8",
                 "css": "text/css; charset=utf-8", "png": "image/png",
                 "svg": "image/svg+xml", "ico": "image/x-icon"}.get(
                     path.rsplit(".", 1)[-1], "application/octet-stream")
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    # ---------- routes ----------
    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path == "/api/settings":
                adb = capture.resolve_adb(_cfg.get("adb"))
                # 输入框只显示用户自己选的路径；留空 = 自动探测（adb_resolved）
                self._json({"adb": _cfg.get("adb") or "", "serial": _cfg["serial"],
                            "adb_resolved": adb, "devices": capture.list_devices(adb),
                            "cpu_mode": perf.mode(),
                            "ocr_queue": scan.clamp_queue_max(_cfg.get("ocr_queue"))})
            elif path == "/api/scan/status":
                snap = scanner().snapshot()
                if not snap["status"]["running"] and not snap["items"]:
                    # 空闲时展示当前结果文件（刷新页面不丢）
                    snap["items"] = store.load_results()
                snap["file"] = store.current_file()
                self._json(snap)
            elif path == "/api/reform/status":
                self._json(reformer().snapshot())
            elif path == "/api/reform/config":
                self._json(reform_config())
            elif path == "/api/refine/status":
                self._json(refiner().snapshot())
            elif path == "/api/sell/status":
                self._json(seller().snapshot())
            elif path == "/api/enhance/status":
                self._json(enhancer().snapshot())
            elif path == "/api/refine/logs":
                self._json({"files": store.list_logs("refine"),
                            "current": store.current_log("refine")})
            elif path == "/api/sell/logs":
                self._json({"files": store.list_logs("sell"),
                            "current": store.current_log("sell")})
            elif path == "/api/filter-notes":
                self._json({"notes": store.load_filter_notes()})
            elif path == "/api/results/list":
                self._json({"files": store.list_results(), "current": store.current_file()})
            elif path == "/api/export.csv":
                self._send(200, export_csv().encode("utf-8-sig"), "text/csv; charset=utf-8")
            elif path == "/api/results":
                self._json({"items": store.load_results()})
            elif path == "/api/catalog":
                self._json({"stats": master.stats(),
                            "items": [{"name": r["name"], "id": r["id"], "icon": r["icon"],
                                       "rank": r.get("rank"), "part": master.part_text(r.get("part")),
                                       "is_special": r.get("is_special", False)}
                                      for r in master.equipment_by_name().values()]})
            elif path == "/api/aliases":
                self._json({"aliases": match.load_aliases()})
            elif path == "/api/rules":
                self._json({"rules": rules.load_rules(),
                            "attrs": rules.known_attrs(),
                            "attr_groups": rules.attr_groups(),
                            "types": master.types()})
            elif path == "/api/rules.json":
                body = json.dumps(rules.load_rules(), ensure_ascii=False, indent=2)
                self._send(200, body.encode("utf-8"), "application/json; charset=utf-8")
            elif path.startswith("/api/rules/") and path.endswith(".json"):
                rid = unquote(path[len("/api/rules/"):-len(".json")])
                target = next((r for r in rules.load_rules() if r["id"] == rid), None)
                if target is None:
                    self._send(404, b"not found", "text/plain")
                else:
                    self._send(200, json.dumps(target, ensure_ascii=False, indent=2).encode("utf-8"),
                               "application/json; charset=utf-8")
            elif path.startswith("/api/icons/"):
                self._serve_icon(unquote(path[len("/api/icons/"):]))
            elif path.startswith("/static/"):
                self._static(path[len("/static/"):])
            elif path == "/" or not path.startswith("/api/"):
                # SPA：命中文件就发文件，否则回退 index.html
                rel = path.lstrip("/")
                full = os.path.join(STATIC_DIR, rel) if rel else ""
                if rel and os.path.isfile(full):
                    self._static(rel)
                else:
                    self._static("index.html")
            else:
                self._send(404, b"not found", "text/plain")
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            # 先无条件读完请求体：否则残留 body 会被当成下一个请求（表现为 501）
            body = self._body()
            if path == "/api/settings":
                b = body
                if "adb" in b:
                    _cfg["adb"] = b["adb"] or None
                if "serial" in b:
                    _cfg["serial"] = b["serial"]
                if "cpu_mode" in b:
                    _cfg["cpu_mode"] = perf.set_mode(str(b["cpu_mode"]))
                    parse.reset_ocr()
                if "ocr_queue" in b:
                    # 对下一次扫描生效（队列在 start() 时按上限新建）
                    _cfg["ocr_queue"] = scan.clamp_queue_max(b["ocr_queue"])
                    if _scanner is not None:
                        _scanner.queue_max = _cfg["ocr_queue"]
                store.save_settings(_cfg)
                self._json({"ok": True})
            elif path == "/api/filter-notes":
                try:
                    notes = store.save_filter_notes(str(body.get("key") or ""),
                                                    str(body.get("text") or ""))
                    self._json({"ok": True, "notes": notes})
                except ValueError as e:
                    self._json({"ok": False, "error": str(e)}, 400)
            elif path == "/api/scan/start":
                # mode=new：新建结果文件从零开始；mode=append：累加到当前结果
                mode = str(body.get("mode") or "new")
                if mode == "append":
                    base = store.load_results()
                else:
                    store.new_scan_file(str(body.get("name") or ""))
                    base = []
                self._json(scanner().start(base))
            elif path == "/api/scan/stop":
                self._json(scanner().stop())
            elif path == "/api/reform/materials":
                self._json(reformer().start_scan_materials(str(body.get("mode") or "full")))
            elif path == "/api/reform/config":
                body["stones"] = reform.refresh_stones(body.get("stones") or [])
                store.save_reform_config(body)
                self._json(reform_config())
            elif path == "/api/reform/start":
                self._json(reformer().start(body))
            elif path == "/api/reform/stop":
                self._json(reformer().stop())
            elif path == "/api/refine/start":
                self._json(refiner().start(str(body.get("mode") or "new")))
            elif path == "/api/refine/open-log":
                self._json(refiner().open_log(str(body.get("file") or "")))
            elif path == "/api/refine/stop":
                self._json(refiner().stop())
            elif path == "/api/sell/start":
                self._json(seller().start(str(body.get("mode") or "new")))
            elif path == "/api/sell/open-log":
                self._json(seller().open_log(str(body.get("file") or "")))
            elif path == "/api/sell/stop":
                self._json(seller().stop())
            elif path == "/api/enhance/start":
                self._json(enhancer().start())
            elif path == "/api/enhance/stop":
                self._json(enhancer().stop())
            elif path == "/api/scan/save":
                store.save_results(scanner().items)
                self._json({"ok": True, "count": len(scanner().items)})
            elif path == "/api/mark":
                idx = int(body.get("idx") or 0)
                marks = [str(m) for m in (body.get("marks") or []) if str(m) in MARKS]
                done = bool(body.get("done"))
                self._json({"ok": bool(mark_item(idx, marks, done))})
            elif path == "/api/results/open":
                items = store.open_result(str(body.get("file") or ""))
                rules.apply(items)
                store.save_results(items)
                self._json({"ok": True, "current": store.current_file(), "items": items})
            elif path == "/api/alias":
                b = body
                raw, target = str(b.get("raw") or ""), str(b.get("target") or "")
                if not raw or not target:
                    self._json({"ok": False, "error": "raw/target 必填"}, 400)
                    return
                aliases = match.save_alias(raw, target)
                n = _reapply_alias(raw)
                self._json({"ok": True, "aliases": aliases, "updated": n})
            elif path == "/api/alias/delete":
                aliases = match.clear_alias(str(body.get("raw") or ""))
                self._json({"ok": True, "aliases": aliases})
            elif path == "/api/pick-adb":
                p = pick_adb_exe()
                self._json({"ok": bool(p), "path": p})
            elif path == "/api/rules/open":
                d = rules.rules_dir()
                try:
                    open_in_explorer(d)
                    self._json({"ok": True, "dir": d})
                except Exception as e:  # noqa: BLE001
                    self._json({"ok": False, "error": str(e)}, 500)
            elif path == "/api/results/open-dir":
                d = store.result_dir()
                try:
                    open_in_explorer(d)
                    self._json({"ok": True, "dir": d})
                except Exception as e:  # noqa: BLE001
                    self._json({"ok": False, "error": str(e)}, 500)
            elif path == "/api/rules/save":
                raw = body.get("rule") or {}
                err = rules.name_error(raw.get("name"))
                if err:
                    self._json({"ok": False, "error": err}, 400)
                    return
                saved = rules.save_rule(raw)
                self._rescore_all()
                self._json({"ok": True, "rule": saved, "rules": rules.load_rules()})
            elif path == "/api/rules/delete":
                ok = rules.delete_rule(str(body.get("id") or ""))
                self._rescore_all()
                self._json({"ok": ok, "rules": rules.load_rules()})
            elif path == "/api/rules/import":
                raw = body.get("rule") or {}
                if isinstance(raw, list):  # 支持一次导入多个
                    saved = [rules.save_rule(r) for r in raw]
                else:
                    saved = [rules.save_rule(raw)]
                self._rescore_all()
                self._json({"ok": True, "saved": saved, "rules": rules.load_rules()})
            elif path == "/api/rules/rescore":
                n = self._rescore_all()
                self._json({"ok": True, "updated": n})
            elif path == "/api/clear":
                store.clear_results()
                self._json({"ok": True})
            elif path == "/api/capture":
                adb = capture.resolve_adb(_cfg.get("adb"))
                png = capture.screenshot(adb, _cfg["serial"])
                self._json({"ok": True,
                            "image": "data:image/png;base64," + base64.b64encode(png).decode(),
                            "parsed": _parse_one(png)})
            elif path == "/api/ocr":
                b = body
                png = base64.b64decode(b["image"].split(",", 1)[-1])
                self._json({"ok": True, "parsed": _parse_one(png)})
            else:
                self._send(404, b"not found", "text/plain")
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 500)


MARKS = ("1", "2", "3")


def mark_item(idx: int, marks: list[str], done: bool) -> int:
    """给某件装备打分组标记（1~3 可多选，√ = 已处理）。

    扫描进行中改内存并顺手落盘；空闲时直接改当前结果文件。
    """
    items = scanner().items or store.load_results()
    for it in items:
        if it.get("idx") == idx:
            it["marks"] = marks
            it["done"] = done
            store.save_results(items)
            return 1
    return 0


def _reapply_alias(raw: str) -> int:
    """校准后：内存里的扫描结果 + 已落盘的结果都重新匹配一遍。"""
    key = match.split_reinforce(raw or "")[0]
    n = scanner().apply_alias(raw)
    items = store.load_results()
    if not items:
        return n
    changed = 0
    for it in items:
        if match.split_reinforce(it.get("raw_name") or "")[0] != key:
            continue
        m = match.match(it.get("raw_name") or "")
        it.update({
            "name": m["name"], "reinforce": m["reinforce"], "equipment_id": m["id"],
            "icon": m["icon"], "rank": m["rank"], "kind": m["kind"],
            "type_name": m["type_name"], "part": m["part"],
            "is_special": m["is_special"], "match_status": m["status"],
            "candidates": m["candidates"],
        })
        changed += 1
    if changed:
        rules.apply(items)
        store.save_results(items)
    return n + changed


def _parse_one(png: bytes) -> dict:
    """单张截图：详情解析 → 名称校验 → 评分。"""
    d = parse.parse_detail_only(png)
    if d:
        m = match.match(d["name"])
        d.update({
            "match": m, "match_status": m["status"], "matched_name": m["name"],
            "reinforce": m["reinforce"], "icon": m["icon"], "equipment_id": m["id"],
            "kind": m["kind"], "type_name": m["type_name"], "part": m["part"],
            "rank": m["rank"], "is_special": m["is_special"],
            "candidates": m["candidates"],
        })
        d.update(rules.score_item(d, rules.load_rules()))
    return {"detail": d, "list_rows": parse.parse_rows(png)}


class _Server(ThreadingHTTPServer):
    """浏览器刷新 / 提前关闭连接会抛 ConnectionResetError(WinError 10054) 等，
    属于正常网络断开，不需要往控制台打印整段 traceback；其它异常照常打印。"""
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError,
                            BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def _bind(port: int) -> tuple[ThreadingHTTPServer, int]:
    for p in range(port, port + 20):
        try:
            return _Server((HOST, p), Handler), p
        except OSError:
            continue
    raise RuntimeError("没有可用端口")


def main() -> None:
    store.migrate()  # 旧 data/ 子目录 → 根目录下的 config/ · rules/ · result/
    cfg = store.load_settings()
    if cfg:
        _cfg.update({k: v for k, v in cfg.items() if k in _cfg})
    want = str(_cfg.get("cpu_mode") or perf.DEFAULT_MODE)
    _cfg["cpu_mode"] = perf.set_mode(want)
    _cfg["ocr_queue"] = scan.clamp_queue_max(_cfg.get("ocr_queue"))
    if cfg and (cfg.get("cpu_mode") != _cfg["cpu_mode"]
                or cfg.get("ocr_queue") != _cfg["ocr_queue"]):
        # 老配置里的档位已下线（如 fast）/ 队列上限缺失或越界：把规范化后的值写回
        cfg["cpu_mode"] = _cfg["cpu_mode"]
        cfg["ocr_queue"] = _cfg["ocr_queue"]
        try:
            store.save_settings(cfg)
        except Exception as e:  # noqa: BLE001
            print(f"[cfg] 配置归一化写盘失败：{e}")
    rules.ensure_defaults()
    srv, port = _bind(PORT)
    url = f"http://{HOST}:{port}/"
    try:
        with open(os.path.join(store.config_dir(), "port.txt"), "w") as f:
            f.write(str(port))
    except Exception:
        pass
    print(f"WVD 装备清理助手 已启动: {url}")
    if not os.environ.get("WVD_NO_BROWSER"):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n退出")


if __name__ == "__main__":
    main()
