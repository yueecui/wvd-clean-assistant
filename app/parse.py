# -*- coding: utf-8 -*-
"""截图 → 装备数据：名称 / 星级 / 附加加护（仅未锁）/ 装备锁定状态。

界面布局（900x1600 实测）：
  左侧列表：每行 = 物品图标 + 名称 + 位置 + 星级(白星) + 加护角标(橙菱形)
  右侧详情：名称(顶部) → 星级/锁图标(其下一行) → 属性表 → ◆附加加护 → 锁定词条
"""
from __future__ import annotations

import io
import re
import threading

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

# ---------- 像素工具 ----------

def _arr(img: Image.Image, x0, y0, x1, y1) -> np.ndarray | None:
    x0 = max(0, int(x0)); y0 = max(0, int(y0))
    x1 = min(img.width, int(x1)); y1 = min(img.height, int(y1))
    if x1 <= x0 or y1 <= y0:
        return None
    return np.asarray(img.crop((x0, y0, x1, y1)), dtype=np.int16)[:, :, :3]


def white_clusters(img: Image.Image, x0, y0, x1, y1,
                   thresh: int = 170, min_w: int = 5,
                   min_col: int = 2) -> list[tuple[int, int]]:
    """白色像素按列聚类 → 数星星。米黄色锁图标会被 b 通道条件排除。

    min_col：一列至少要有几个白像素才算「星体」。默认 2，偶尔会把相邻两颗星
    （中间那列只有 1~2 个像素）粘成一颗，4★ 读成 2★；数 4~5★ 白装时传 4 更稳。
    """
    a = _arr(img, x0, y0, x1, y1)
    if a is None:
        return []
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mask = (r > thresh) & (g > thresh) & (b > thresh * 0.85)
    cols = mask.sum(axis=0)
    out, start = [], None
    for x, n in enumerate(cols):
        if n >= min_col and start is None:
            start = x
        elif n < min_col and start is not None:
            if x - start >= min_w:
                out.append((x0 + start, x0 + x))
            start = None
    if start is not None and len(cols) - start >= min_w:
        out.append((x0 + start, x0 + len(cols)))
    return out


# ---------- 锁定图标 ----------
# 锁定 = 米黄色挂锁；未锁定 = 中性灰的「开锁」图标。
# 只数米黄像素会被金色装备（光精 / 极光系列）的图标光芒骗到：光晕是饱和黄，
#   b 通道很低（≈60）、r-b 高达 170；而挂锁是米黄，b ≈ 110~126、r-b 只有 40~56。
# 光晕边缘还有少量抗锯齿像素正好落进米黄区间（实测最多 35 像素、15x10），
# 所以再加一道连通域门槛：够大、够高才算锁。
LOCK_GOLD_MIN_AREA = 45     # 区域里米黄像素总量下限（光晕碎片实测 ≤35）
LOCK_GOLD_MIN_H = 12        # 最大米黄连通域的高度下限（光晕碎片 ≤10）
LOCK_GOLD_MIN_W = 8
LOCK_GOLD_MIN_ASPECT = 0.7  # 高/宽：挂锁是竖的或方的，横向金色光带排除


def _gold_lock_mask(a: np.ndarray) -> np.ndarray:
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    return (r > 150) & (g > 125) & (b > 100) & (r - b > 40) & (r - b < 120) & (g - b > 20)


def has_lock_icon(img: Image.Image, x0, y0, x1, y1) -> bool:
    """区域内是否有米黄挂锁图标（锁定时为 True）。"""
    a = _arr(img, x0, y0, x1, y1)
    if a is None:
        return False
    mask = _gold_lock_mask(a)
    if int(mask.sum()) < LOCK_GOLD_MIN_AREA:
        return False
    # 详情面板的锁被暗色锁孔 / 圆环切成几块（实测 48+46+31），所以尺寸看最大的那块
    lab, n = ndimage.label(ndimage.binary_dilation(mask, iterations=1))
    if n == 0:
        return False
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    ys, xs = np.nonzero(lab == int(np.argmax(sizes)) + 1)
    h = int(ys.max() - ys.min() + 1)
    w = int(xs.max() - xs.min() + 1)
    return (h >= LOCK_GOLD_MIN_H and w >= LOCK_GOLD_MIN_W
            and h / max(1, w) >= LOCK_GOLD_MIN_ASPECT)


def detail_lock_box(name: dict) -> tuple[int, int, int, int]:
    """详情面板「锁定」图标的位置：名称下方第一行最左侧的圆形图标（星级白星在它右边）。

    只框这一个图标 —— 往左上会吃到装备图标的金色光芒（光精 / 极光系列），
    往右会框进星星，所以固定成 name.x 左侧 70~15px、名称下方 8~58px 的小窗口。
    """
    x, y, h = name["x"], name["y"], name["h"]
    return (x - 70, y + h + 8, x - 15, y + h + 58)


def orange_bbox(img: Image.Image, x0, y0, x1, y1) -> tuple[int, int, int, int] | None:
    """橙色加护角标的包围盒。"""
    a = _arr(img, x0, y0, x1, y1)
    if a is None:
        return None
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mask = (r > 170) & (g > 50) & (g < 140) & (b < 110)
    ys, xs = np.nonzero(mask)
    if len(xs) < 40:
        return None
    return (x0 + int(xs.min()), y0 + int(ys.min()), x0 + int(xs.max()), y0 + int(ys.max()))


def row_highlight(img: Image.Image, y: int, x0=380, x1=460) -> float:
    """行背景的暖色程度（r-b）。选中行明显更高。"""
    a = _arr(img, x0, y - 12, x1, y + 25)
    if a is None:
        return 0.0
    m = a.reshape(-1, 3).mean(axis=0)
    return float(m[0] - m[2])


# ---------- 品质颜色 ----------
# 装备名按品质上色：白 / 绿 / 蓝 / 紫 / 红（hue 分段，红色跨 0°）
_QUALITY_NAMES = ("white", "green", "blue", "purple", "red")


def _hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """RGB(0-255) → H(0-360) / S(0-1) / V(0-1)。"""
    a = rgb.astype(np.float32) / 255.0
    mx = a.max(axis=-1)
    mn = a.min(axis=-1)
    diff = mx - mn
    h = np.zeros_like(mx)
    m = diff > 1e-6
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    i = m & (mx == r)
    h[i] = (60 * ((g[i] - b[i]) / diff[i])) % 360
    i = m & (mx == g)
    h[i] = 60 * ((b[i] - r[i]) / diff[i]) + 120
    i = m & (mx == b)
    h[i] = 60 * ((r[i] - g[i]) / diff[i]) + 240
    s = np.where(mx > 1e-6, diff / np.maximum(mx, 1e-6), 0.0)
    return h, s, mx


def _hue_to_quality(hue: float) -> str:
    if hue < 20 or hue >= 330:
        return "red"
    if hue < 60:
        return "red"
    if hue < 165:
        return "green"
    if hue < 265:
        return "blue"
    return "purple"


def name_color(img: Image.Image, box) -> str:
    """名字文字的品质色：white / green / blue / purple / red；判断不出返回空串。

    做法：取名字包围盒内「亮且有色」的文字像素，最鲜的一批求圆形平均色相；
    高明度低饱和像素占多数则视为白色。
    """
    if not box:
        return ""
    x, y, w, h = box
    a = _arr(img, x - 4, y - 5, x + w + 5, y + h + 6)
    if a is None or a.size == 0:
        return ""
    hue, sat, val = _hsv(a)
    vmax = float(val.max())
    if vmax < 0.35:
        return ""
    # 只取最亮的一批像素＝文字笔画；选中行的暖色底/图标不会被算进来
    body = val >= max(0.45, vmax * 0.72)
    if int(body.sum()) < 12:
        body = val >= max(0.45, vmax * 0.55)
    if int(body.sum()) < 12:
        return ""
    hh, ss, vv = hue[body], sat[body], val[body]
    k = max(8, int(len(vv) * 0.4))
    idx = np.argsort(vv)[-k]
    if float(np.median(ss[idx])) < 0.18:      # 亮且几乎不吃色 → 白色
        return "white"
    ang = np.deg2rad(hh[idx])
    mean_h = float(np.degrees(np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())) % 360)
    return _hue_to_quality(mean_h)


# ---------- 角标数字 ----------

def _to48(m: np.ndarray) -> np.ndarray:
    im = Image.fromarray((m * 255).astype(np.uint8))
    h, w = m.shape
    s = 48 / max(h, w)
    return np.asarray(im.resize((max(1, int(round(w * s))), max(1, int(round(h * s)))),
                                Image.LANCZOS)) > 100


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    H = max(a.shape[0], b.shape[0]); W = max(a.shape[1], b.shape[1])
    A = np.zeros((H, W), bool); B = np.zeros((H, W), bool)
    A[:a.shape[0], :a.shape[1]] = a
    B[H - b.shape[0]:, :b.shape[1]] = b
    u = (A | B).sum()
    return float((A & B).sum() / u) if u else 0.0


_templates: dict[str, np.ndarray] | None = None


def _digit_templates() -> dict[str, np.ndarray]:
    global _templates
    if _templates is not None:
        return _templates
    templates = {}
    for fname in ["segoeuib.ttf", "arialbd.ttf", "calibrib.ttf", "arial.ttf",
                  "seguisb.ttf", "msyhbd.ttc"]:
        try:
            font = ImageFont.truetype(fname, 40)
        except Exception:
            continue
        for d in "0123456789":
            if d in templates:
                continue
            im = Image.new("L", (48, 56), 0)
            ImageDraw.Draw(im).text((4, 4), d, fill=255, font=font)
            arr = np.asarray(im) > 100
            ys, xs = np.nonzero(arr)
            if len(xs) == 0:
                continue
            templates[d] = _to48(arr[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
        if len(templates) == 10:
            break
    _templates = templates
    return templates


def badge_digit(img: Image.Image, box: tuple[int, int, int, int]) -> str | None:
    """角标数字：白字连通域 + 字体模板匹配（OCR 对单数字不可靠）。"""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    a = _arr(img, x0 + w * 0.22, y0 + h * 0.04, x1 - w * 0.22, y1 - h * 0.04)
    if a is None:
        return None
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mask = ndimage.binary_dilation(
        (r > 170) & (g > 128) & (b > 115), iterations=2)
    lab, n = ndimage.label(mask)
    if n == 0:
        return None
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    best = int(np.argmax(sizes)) + 1
    ys, xs = np.nonzero(lab == best)
    if len(xs) < 8:
        return None
    m = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    mh, mw = m.shape
    if mw / mh < 0.55:
        return "1"
    q = _to48(m)
    best_d, best_v = None, 0.0
    for d, t in _digit_templates().items():
        v = _iou(q, t)
        if v > best_v:
            best_v, best_d = v, d
    return best_d


# ---------- OCR ----------

_ocr = None
# 流水线里主线程（滚动后识别列表）与 OCR 线程（识别详情）会同时调用引擎，
# RapiDOCR 实例内部并不保证并发安全，这里串行化：等待的只是同一时刻的那一次识别。
_OCR_LOCK = threading.Lock()


def get_ocr():
    global _ocr
    if _ocr is None:
        import perf
        from rapidocr_onnxruntime import RapidOCR

        # 库不接受 intra_op_num_threads 参数，必须在实例化前替换它的
        # SessionOptions 工厂才能真正限线程（默认均衡档 2 线程，见 perf.py）
        perf.configure_ocr()
        _ocr = RapidOCR()
    return _ocr


def reset_ocr() -> None:
    """切换 CPU 档位后丢弃旧会话，下次 OCR 按新线程数重建。

    持锁清空：避免 OCR 线程正在识别时又新建一份会话。
    """
    global _ocr
    with _OCR_LOCK:
        _ocr = None


def ocr_lines(img: Image.Image, region: tuple[int, int, int, int] | None = None) -> list[dict]:
    """OCR（可指定区域，提速），返回全图坐标的行。"""
    ox = oy = 0
    target = img
    if region:
        ox, oy = region[0], region[1]
        target = img.crop(region)
    with _OCR_LOCK:
        engine = get_ocr()          # 惰性初始化也放锁里，避免两个线程各建一份会话
        result, _ = engine(np.asarray(target)[:, :, ::-1])
    lines = []
    for box, text, score in (result or []):
        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        lines.append({
            "x": int(min(xs) + ox), "y": int(min(ys) + oy),
            "w": int(max(xs) - min(xs)), "h": int(max(ys) - min(ys)),
            "text": str(text).strip(), "score": float(score),
        })
    return lines


# ---------- 解析 ----------

_SKIP = {"①", "i", "I", "1)", "持有一览", "强化预测", "装备强化", "Blacksmith",
         "ALL", "详细", "强化", "详情", "持有", "仓库"}
_UNLOCKED_RE = re.compile(r"^[\u4e00-\u9fa5]{1,6}[+\-−][+\-−]?\d+")
# OCR 常把全角括号识别成半角，装备名里常见【XI】这类后缀
_BRACKET_FIX = str.maketrans({"[": "【", "]": "】"})


def _pick_name(lines: list[dict], W: int, H: int,
               limit: float | None = None) -> dict | None:
    """详情区第一行装备名（跳过标题 / 纯数字这类噪声）。"""
    right = [l for l in lines if l["x"] >= W * 0.45]
    if not right:
        return None
    if limit is None:
        hdr = next((l for l in right if "附加加护" in l["text"]), None)
        limit = hdr["y"] if hdr else H * 0.95
    cand = [l for l in sorted(right, key=lambda l: l["y"])
            if H * 0.15 < l["y"] < limit - 40
            and l["text"] not in _SKIP and l["score"] > 0.5
            and not re.fullmatch(r"[0-9+/%>\-. ]+", l["text"])]
    return cand[0] if cand else None


def parse_detail(img: Image.Image, lines: list[dict], W: int, H: int) -> dict | None:
    """详情面板：名称 / 星级 / 未锁加护 / 装备是否锁定。"""
    right = [l for l in lines if l["x"] >= W * 0.45]
    if not right:
        return None
    hdr = next((l for l in right if "附加加护" in l["text"]), None)
    limit = hdr["y"] if hdr else H * 0.95

    name = _pick_name(lines, W, H, limit)
    if name is None:
        return None

    out = {
        "name": name["text"].replace(" ", "").translate(_BRACKET_FIX),
        "stars": len(white_clusters(img, name["x"] - 15, name["y"] + name["h"] + 5,
                                    name["x"] + 260, name["y"] + name["h"] + 60)),
        # 名字下方图标行：左为锁(锁定=米黄挂锁 / 未锁=灰色开锁)，右为星级(白星)
        "locked": has_lock_icon(img, *detail_lock_box(name)),
        "box": [name["x"], name["y"], name["w"], name["h"]],
        "color": name_color(img, [name["x"], name["y"], name["w"], name["h"]]),
    }

    blessings = []
    if hdr:
        for l in sorted((x for x in right if x["y"] > hdr["y"] + hdr["h"]), key=lambda x: x["y"]):
            t = re.sub(r"^[^\u4e00-\u9fa5A-Za-z0-9+]+", "", l["text"].replace(" ", ""))
            if not t or "强度上限" in t:
                break
            if "解锁" in t or "强化值+" in t:   # 锁定词条：不要
                continue
            if _UNLOCKED_RE.match(t):
                blessings.append(t)
    out["blessings"] = blessings
    return out


_LOC_WORDS = {"仓库", "所持", "所持中", "装备中", "装備中"}


def parse_list(img: Image.Image, lines: list[dict], W: int, H: int) -> list[dict]:
    """左侧列表可见行：名称 / 星级 / 角标 / 选中高亮 / 点击坐标。

    锁定状态**不在列表上判**：图标右上角确实会叠一个挂锁，但金色装备的光晕就糊在
    那一块（光精 / 极光系列实测整行 500+ 米黄像素），怎么设阈值都不稳。
    统一以详情面板名称下方那个圆形图标为准（见 parse_detail）。
    """
    left = [l for l in lines if l["x"] < W * 0.42 and H * 0.16 < l["y"] < H * 0.80]
    names = [l for l in sorted(left, key=lambda l: l["y"])
             if l["text"] not in _LOC_WORDS
             and not re.fullmatch(r"[★☆0-9①iI]+", l["text"])
             and len(l["text"]) >= 2 and l["score"] > 0.35]
    rows, last_y = [], -999
    for n in names:
        if n["y"] - last_y < 60:      # 同一行重复命中
            continue
        ny = n["y"]
        last_y = ny
        bb = orange_bbox(img, 85, ny + 30, 132, ny + 100)
        rows.append({
            "name": n["text"].replace(" ", ""),
            "stars": len(white_clusters(img, 25, ny + 35, 112, ny + 100)),
            "badge": badge_digit(img, bb) if bb else None,
            "locked": False,   # 列表不判锁：只看详情面板（图标光晕会糊成挂锁形状）
            "color": name_color(img, [n["x"], n["y"], n["w"], n["h"]]),
            "y": ny,
            "hl": row_highlight(img, ny),
            "tap": [max(150, n["x"] + 60), ny + 12],
        })
    return rows


def _detail_lines(img: Image.Image, W: int, H: int) -> list[dict]:
    """详情区两块（名称+星级 / 加护词条）竖向拼接后一次 OCR，坐标映射回全图。

    名称区放大 2 倍再识别，减少漏字/多字（小字直接喂 rec 容易出错）。
    """
    r1 = (int(W * 0.48), int(H * 0.16), int(W * 0.98), int(H * 0.28))
    r2 = (int(W * 0.48), int(H * 0.49), int(W * 0.98), int(H * 0.72))
    c1 = img.crop(r1)
    c1 = c1.resize((c1.width * 2, c1.height * 2), Image.LANCZOS)
    c2 = img.crop(r2)
    gap = 24
    canvas = Image.new("RGB", (max(c1.width, c2.width), c1.height + gap + c2.height), (0, 0, 0))
    canvas.paste(c1, (0, 0))
    canvas.paste(c2, (0, c1.height + gap))
    lines = ocr_lines(canvas)
    for l in lines:
        if l["y"] < c1.height:
            l["x"] = l["x"] // 2 + r1[0]
            l["y"] = l["y"] // 2 + r1[1]
            l["w"] //= 2; l["h"] //= 2
        else:
            l["x"] += r2[0]; l["y"] += r2[1] - (c1.height + gap)
    return lines


def _list_lines(img: Image.Image, W: int, H: int) -> list[dict]:
    return ocr_lines(img, (0, int(H * 0.16), int(W * 0.44), int(H * 0.80)))


def parse_screen(png: bytes, need_list: bool = True) -> dict:
    img = Image.open(io.BytesIO(png)).convert("RGB")
    W, H = img.size
    detail = parse_detail(img, _detail_lines(img, W, H), W, H)
    rows = parse_list(img, _list_lines(img, W, H), W, H) if need_list else []
    return {"resolution": [W, H], "detail": detail, "rows": rows}


def parse_rows(png: bytes) -> list[dict]:
    """只解析列表（滚动后重新定位行）。"""
    img = Image.open(io.BytesIO(png)).convert("RGB")
    W, H = img.size
    return parse_list(img, _list_lines(img, W, H), W, H)


def parse_detail_only(png: bytes) -> dict | None:
    """只解析详情（逐件扫描时用，跳过列表 OCR 提速）。"""
    img = Image.open(io.BytesIO(png)).convert("RGB")
    W, H = img.size
    return parse_detail(img, _detail_lines(img, W, H), W, H)


def _name_lines(img: Image.Image, W: int, H: int) -> list[dict]:
    """只 OCR 详情里的名字那块（放大 2 倍提速、少漏字）。"""
    r = (int(W * 0.48), int(H * 0.16), int(W * 0.98), int(H * 0.28))
    c = img.crop(r)
    c = c.resize((c.width * 2, c.height * 2), Image.LANCZOS)
    lines = ocr_lines(c)
    for l in lines:
        l["x"] = l["x"] // 2 + r[0]
        l["y"] = l["y"] // 2 + r[1]
        l["w"] //= 2; l["h"] //= 2
    return lines


def detail_name_only(png: bytes) -> str:
    """只读详情里的装备名（含 +N）。

    自动强化要每 1 秒左右轮询一次「+N 变了没」，整块详情（名称 + 加护两段 OCR）
    太慢，只识别名称那一段，实测快一半以上。
    """
    img = Image.open(io.BytesIO(png)).convert("RGB")
    W, H = img.size
    name = _pick_name(_name_lines(img, W, H), W, H, H * 0.95)
    return name["text"].replace(" ", "").translate(_BRACKET_FIX) if name else ""
