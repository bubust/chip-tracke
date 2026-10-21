"""B74 支撐壓力區（PLAN-B74 §4.4）：候選價位 → 0.5×ATR 內合併成區 → 短線／波段各挑上下最近 3 區。
價位類型的定義（哪些轉折、哪些比例、哪些均線、整數間距）研究 research/wave/run.py 也用同一份。"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from . import engine as E

MA_LIST = (20, 60, 120, 240)
MA_NAME = {20: "月線", 60: "季線", 120: "半年線", 240: "年線"}
ZONE_FIB = (0.236, 0.382, 0.5, 0.618, 0.786)
EXT_RATIOS = (1.272, 1.618)
K3_LOOK = 60
SHORT_WIN, SWING_WIN = 0.06, 0.15

# 價位類型 → 大類（≥2 個大類重疊＝multi）
CATEGORY = {"pivot": "pivot", "pivot_k3": "pivot", "fib": "fib", "target": "wave", "ext": "fib",
            "ma20": "ma", "ma60": "ma", "ma120": "ma", "ma240": "ma", "round": "round"}
TYPE_NAME = {"pivot": "前高前低", "pivot_k3": "近期高低點", "fib": "費波那契回檔", "target": "波浪目標",
             "ext": "費波那契延伸", "ma20": "月線", "ma60": "季線", "ma120": "半年線", "ma240": "年線",
             "round": "整數關卡", "multi": "多重重疊"}


def round_step(price: float) -> float:
    """整數關卡間距：2 萬點以上每 1,000 點、以下每 500 點"""
    return 1000.0 if price >= 20000 else 500.0


def k3_pivots(h, l, t: int, look: int = K3_LOOK, k: int = 3) -> list:
    """近 look 天內左右各 k 根的高低點（第 i 根要到 i+k 收盤才確認 → 只取 i+k ≤ t）"""
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    out = []
    for i in range(max(k, t - look), t - k + 1):
        if h[i] > h[i - k:i].max() and h[i] >= h[i + 1:i + k + 1].max():
            out.append({"i": i, "p": float(h[i]), "t": "H", "ci": i + k})
        if l[i] < l[i - k:i].min() and l[i] <= l[i + 1:i + k + 1].min():
            out.append({"i": i, "p": float(l[i]), "t": "L", "ci": i + k})
    return out


def moving_averages(c, t: int) -> dict:
    c = np.asarray(c, dtype=float)
    return {n: float(c[t - n + 1:t + 1].mean()) for n in MA_LIST if t + 1 >= n}


def candidates(h, l, c, t: int, an: dict, dates=None, which: str = "short") -> list:
    """第 t 天收盤後的候選價位。an：{級數: engine.analyze(...)}。
    短線＝小級轉折＋小級回檔＋近期高低點＋月線＋整數；波段＝中／大級轉折＋中／大級回檔＋主要劇本目標＋季／半年／年線＋整數"""
    degs = ("small",) if which == "short" else ("mid", "big")
    out = []
    dt = (lambda i: str(dates[i])) if dates is not None else (lambda i: str(i))
    seen = set()
    for deg in degs:
        a = an.get(deg) or {}
        for p in (a.get("pivots") or [])[-12:]:
            key = (p["i"], p["t"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"type": "pivot", "price": p["p"], "deg": deg,
                        "label": f"{'前高' if p['t'] == 'H' else '前低'} {dt(p['i'])}"})
        f = a.get("fib")
        if f:
            for x in f["levels"]:
                out.append({"type": "fib", "price": x["price"], "deg": deg, "label": f"{E.DEGREES[deg]['label'][:2]}回檔 {x['ratio']:g}"})
        prim = a.get("primary")
        if which == "swing" and prim:
            for x in prim["targets"]:
                if x["kind"] == "end":
                    out.append({"type": "target", "price": x["price"], "deg": deg, "label": f"{E.DEGREES[deg]['label'][:2]}{x['label']}"})
    if which == "short":
        for p in k3_pivots(h, l, t):
            out.append({"type": "pivot_k3", "price": p["p"], "deg": "k3",
                        "label": f"近期{'高' if p['t'] == 'H' else '低'}點 {dt(p['i'])}"})
    mas = moving_averages(c, t)
    for n, v in mas.items():
        if (which == "short") == (n == 20):
            out.append({"type": f"ma{n}", "price": v, "deg": "", "label": f"{MA_NAME[n]}（MA{n}）"})
    price = float(c[t])
    step = round_step(price)
    win = SHORT_WIN if which == "short" else SWING_WIN
    base = math.floor(price * (1 - win) / step) * step
    while base <= price * (1 + win):
        if base > 0:
            out.append({"type": "round", "price": base, "deg": "", "label": f"整數關卡 {base:,.0f}"})
        base += step
    return [x for x in out if x["price"] and math.isfinite(x["price"])]


def zone_type(srcs: list) -> str:
    cats = {CATEGORY.get(s["type"], s["type"]) for s in srcs}
    if len(cats) >= 2:
        return "multi"
    return srcs[0]["type"] if len({s["type"] for s in srcs}) == 1 else next(iter(cats))


def make_zones(cands: list, price: float, atr_v: float, hold: Optional[dict] = None) -> list:
    """0.5×ATR 內的候選合併成一區；hold＝研究的守住率表 {類型: {...}}"""
    if not cands or not atr_v or not math.isfinite(atr_v):
        return []
    tol = 0.5 * atr_v
    cs = sorted(cands, key=lambda x: x["price"])
    groups, cur = [], [cs[0]]
    for x in cs[1:]:
        # 跟前一個差 ≤0.5 ATR 才併，而且整區寬度不超過 1 ATR（避免一路串成很寬的一區）
        if x["price"] - cur[-1]["price"] <= tol and x["price"] - cur[0]["price"] <= 2 * tol:
            cur.append(x)
        else:
            groups.append(cur)
            cur = [x]
    groups.append(cur)
    zones = []
    for g in groups:
        ps = [x["price"] for x in g]
        center = float(np.mean(ps))
        ztype = zone_type(g)
        st = (hold or {}).get(ztype) or (hold or {}).get(g[0]["type"])
        zones.append({
            "price": round(center, 0), "lo": round(min(ps), 0), "hi": round(max(ps), 0),
            "side": "support" if center < price else "resistance",
            "dist_pct": round((center / price - 1) * 100, 2),
            "type": ztype, "type_name": TYPE_NAME.get(ztype, ztype),
            "sources": [{"type": x["type"], "label": x["label"], "price": round(x["price"], 0)} for x in g],
            "hold": st,
        })
    return zones


def pick(zones: list, price: float, which: str = "short", n: int = 3) -> dict:
    """上下各挑最近 n 區（只在 ±6%／±15% 內）；不夠就照實回較少的"""
    win = SHORT_WIN if which == "short" else SWING_WIN
    sup = sorted([z for z in zones if z["side"] == "support" and z["price"] >= price * (1 - win)],
                 key=lambda z: -z["price"])[:n]
    res = sorted([z for z in zones if z["side"] == "resistance" and z["price"] <= price * (1 + win)],
                 key=lambda z: z["price"])[:n]
    return {"support": sup, "resistance": res}


def extensions(an: dict, deg: str = "mid") -> list:
    """上方（或下方）沒有歷史價位時補費波那契延伸：最近完成那段 ×1.272／1.618"""
    a = an.get(deg) or {}
    f = a.get("fib")
    if not f:
        return []
    A, B = f["from"]["p"], f["to"]["p"]
    out = []
    for r in EXT_RATIOS:
        v = A + r * (B - A)
        out.append({"type": "ext", "price": round(v, 2), "deg": deg, "label": f"延伸 {r:g}"})
    return out


def build(h, l, c, t: int, an: dict, atr_v: float, dates=None, hold: Optional[dict] = None) -> dict:
    """短線、波段兩組支撐壓力；某一邊沒有就補延伸／整數並標 note"""
    price = float(c[t])
    out = {}
    for which in ("short", "swing"):
        cands = candidates(h, l, c, t, an, dates, which)
        z = make_zones(cands, price, atr_v, hold)
        p = pick(z, price, which)
        note = []
        if not p["resistance"]:
            ext = [x for x in extensions(an, "mid" if which == "swing" else "small") if x["price"] > price]
            p["resistance"] = pick(make_zones(ext + cands, price, atr_v, hold), price, which)["resistance"] or \
                sorted([zz for zz in make_zones(ext, price, atr_v, hold) if zz["side"] == "resistance"], key=lambda zz: zz["price"])[:3]
            note.append("上方沒有歷史壓力，用費波那契延伸／整數關卡")
        if not p["support"]:
            note.append("下方 {:.0%} 內沒有支撐區".format(SHORT_WIN if which == "short" else SWING_WIN))
        p["note"] = note
        out[which] = p
    return out


# ── B75 超短線（60 分 K；PLAN-B75 §4.3）────────────────────────────────────────
ULTRA_WIN = 0.03
ULTRA_K3_LOOK = 100
CATEGORY.update({"prev": "pivot", "night": "pivot", "ipivot": "pivot", "ipivot_k3": "pivot", "ifib": "fib"})
TYPE_NAME.update({"prev": "昨天高低收", "night": "夜盤高低", "ipivot": "60 分 K 轉折", "ipivot_k3": "60 分 K 近期高低",
                  "ifib": "60 分 K 回檔"})


def candidates_ultra(h, l, c, t: int, an: dict, label=None, daily: dict | None = None) -> list:
    """60 分 K 第 t 根收完時的候選：轉折、k3 高低、回檔、昨天高低收、（台指期）夜盤高低、日 K 月線、整數關卡（500 點）
    label(i)＝第 i 根的顯示文字（例 10/20 13:00）；daily＝{prev_h, prev_l, prev_c, night_h, night_l, ma20, price}"""
    lb = label or (lambda i: str(i))
    out = []
    for p in (an.get("pivots") or [])[-12:]:
        out.append({"type": "ipivot", "price": p["p"], "deg": "intra", "label": f"60 分{'高' if p['t'] == 'H' else '低'}點 {lb(p['i'])}"})
    f = an.get("fib")
    if f:
        for x in f["levels"]:
            out.append({"type": "ifib", "price": x["price"], "deg": "intra", "label": f"60 分回檔 {x['ratio']:g}"})
    for p in k3_pivots(h, l, t, look=ULTRA_K3_LOOK):
        out.append({"type": "ipivot_k3", "price": p["p"], "deg": "k3", "label": f"近期 60 分{'高' if p['t'] == 'H' else '低'}點 {lb(p['i'])}"})
    dl = daily or {}
    for k, nm, typ in (("prev_h", "昨天最高", "prev"), ("prev_l", "昨天最低", "prev"), ("prev_c", "昨天收盤", "prev"),
                       ("night_h", "夜盤最高", "night"), ("night_l", "夜盤最低", "night"), ("ma20", "日 K 月線（MA20）", "ma20")):
        v = dl.get(k)
        if v is not None and math.isfinite(v):
            out.append({"type": typ, "price": float(v), "deg": "", "label": nm})
    price = float(dl.get("price") or c[t])
    step = 500.0
    base = math.floor(price * (1 - ULTRA_WIN) / step) * step
    while base <= price * (1 + ULTRA_WIN):
        if base > 0:
            out.append({"type": "round", "price": base, "deg": "", "label": f"整數關卡 {base:,.0f}"})
        base += step
    return [x for x in out if x["price"] and math.isfinite(x["price"])]


def build_ultra(h, l, c, t: int, an: dict, atr_v: float, price: float, label=None, daily: dict | None = None,
                hold: Optional[dict] = None) -> dict:
    """超短線支撐壓力：0.5×ATR60 內合併、±3% 內上下各 3 區"""
    cands = candidates_ultra(h, l, c, t, an, label, {**(daily or {}), "price": price})
    z = make_zones(cands, price, atr_v, hold)
    sup = sorted([x for x in z if x["side"] == "support" and x["price"] >= price * (1 - ULTRA_WIN)], key=lambda x: -x["price"])[:3]
    res = sorted([x for x in z if x["side"] == "resistance" and x["price"] <= price * (1 + ULTRA_WIN)], key=lambda x: x["price"])[:3]
    note = []
    if not sup:
        note.append("下方 3% 內沒有支撐區")
    if not res:
        note.append("上方 3% 內沒有壓力區")
    return {"support": sup, "resistance": res, "note": note}
