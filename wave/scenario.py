"""B131 推演引擎：把她的方法寫成只看轉折的規則（research/b131/PLAN.md §3，2026-11-27 寫死）。純函式，不碰網路、資料庫、日期。

R0 轉折｜R1 併段｜R2 重疊線｜R3 回撤｜R3b 母級｜R4 等幅｜R5 均線｜R6 起推底座｜R7 箱體｜R8 套牢區
沒有任何一條用到她的數字或日期；網站之後用同一份。"""
from __future__ import annotations

from typing import Optional

import numpy as np

from . import engine as E
from . import volume as VO

RET = (0.236, 0.382, 0.5, 0.618, 0.786)
RET3 = (0.382, 0.5, 0.618)
TAIL = 6                       # 結構從併段後最近 6 個轉折裡找最新的極端點


def _pt(q: dict) -> dict:
    return {"i": q["i"], "p": float(q["p"]), "t": q["t"]}


def merge_all(piv: list) -> list:
    """R1 併段：H a、L b、H c、L d、H e、L x——c 沒過 a、d 破 b、x 又破 d，且 b→c 反彈 < a→b 的一半 → 拿掉 b、c（方向相反同理）；
    整串反覆做到不能再併"""
    q = [_pt(x) for x in piv]
    changed = True
    while changed:
        changed = False
        for k in range(len(q) - 6, -1, -1):
            a, b, c, d, e, x = q[k:k + 6]
            if not (a["t"] == c["t"] == e["t"] != b["t"] == d["t"] == x["t"]):
                continue
            s = 1 if a["t"] == "H" else -1
            if (d["p"] - x["p"]) * s <= 0 or (a["p"] - c["p"]) * s <= 0 or (b["p"] - d["p"]) * s <= 0:
                continue
            if abs(c["p"] - b["p"]) >= 0.5 * abs(a["p"] - b["p"]):
                continue
            del q[k + 1:k + 3]
            changed = True
            break
    return q


def daily_pivots(h, l, c, deg: str = "small") -> list:
    """最後一根收盤時看得到的轉折（確認過的＋進行中的極值）"""
    h, l, c = (np.asarray(x, dtype=float) for x in (h, l, c))
    piv = E.zigzag(h, l, E.thresholds(h, l, c, deg))
    conf, tent = E.state_at(piv, h, l, len(c) - 1)
    return conf + ([tent] if tent else [])


def structure(m: list, h, l, price: float) -> Optional[dict]:
    """併段後的轉折 m → T、L1、H2、X（X＝最近 6 個轉折裡最新的極端點）、d（H2→X 的方向）、rb（X 之後反向走到哪）"""
    if len(m) < 4:
        return None
    tail = m[-TAIL:]
    hi = max(tail, key=lambda q: q["p"])
    lo = min(tail, key=lambda q: q["p"])
    X = hi if hi["i"] > lo["i"] else lo
    k = next(j for j in range(len(m)) if m[j]["i"] == X["i"] and m[j]["t"] == X["t"])
    if k < 3:
        return None
    T, L1, H2 = m[k - 3], m[k - 2], m[k - 1]
    d = 1 if X["t"] == "H" else -1
    h, l = np.asarray(h, dtype=float), np.asarray(l, dtype=float)
    after = slice(X["i"] + 1, len(h))
    if after.start < len(h):
        rb = float(np.min(l[after])) if d > 0 else float(np.max(h[after]))
        rb_i = X["i"] + 1 + int(np.argmin(l[after]) if d > 0 else np.argmax(h[after]))
    else:
        rb, rb_i = float(price), X["i"]
    if (rb - price) * d > 0:                                          # 現價比 rb 更反向（盤中延伸）
        rb = float(price)
    return {"T": T, "L1": L1, "H2": H2, "X": X, "d": d, "rb": rb, "rb_i": rb_i, "k": k,
            "beyond": (X["p"] - L1["p"]) * d > 0}


def _ret(a: float, b: float, rs=RET) -> list:
    """a→b 這段的回撤價位（從 b 往 a 回 r）"""
    return [(b - r * (b - a), r) for r in rs]


def _ma(c, n: int) -> Optional[float]:
    c = np.asarray(c, dtype=float)
    return float(np.mean(c[-n:])) if len(c) >= n else None


def levels(d_h, d_l, d_c, price: float, b60: Optional[list] = None, dates60: Optional[list] = None,
           big: Optional[tuple] = None) -> dict:
    """R0～R8 的價位。d_h／d_l／d_c＝日 K（最後一根可以是進行中的）；b60＝60 分 K [{time, high, low, close, volume}]（舊→新，只放收完的）；
    dates60＝每根 60 分 K 屬於哪一天日 K 的 index（跟 d_* 對齊，用來把日線轉折對到 60 分 K）；big＝(h, l, c) 算母級的長日 K（沒給就用 d_*）。
    回 {levels:[{p, rule, note}], st: structure}"""
    out = []

    def add(p, rule, note):
        if p is not None and np.isfinite(p) and p > 0:
            out.append({"p": round(float(p), 2), "rule": rule, "note": note})

    d_h, d_l, d_c = (np.asarray(x, dtype=float) for x in (d_h, d_l, d_c))
    m = merge_all(daily_pivots(d_h, d_l, d_c, "small"))
    for q in m[-8:]:
        add(q["p"], "R0", "日線轉折")
    st = structure(m, d_h, d_l, price)
    if st:
        T, L1, H2, X, d, rb = st["T"], st["L1"], st["H2"], st["X"], st["d"], st["rb"]
        add(L1["p"], "R2", "重疊線（第 1 段終點）")
        for v, r in _ret(H2["p"], X["p"]):
            add(v, "R3", f"最後一段 {r:g}")
        if st["beyond"]:
            for v, r in _ret(T["p"], X["p"], RET3):
                add(v, "R3", f"三段 {r:g}")
        if abs(rb - X["p"]) > 0:
            for v, r in _ret(X["p"], rb):
                add(v, "R3", f"反向段 {r:g}")
        L = abs(T["p"] - L1["p"])
        for k_ in (1.0, 1.618):
            add(H2["p"] + d * k_ * L, "R4", f"等幅 {k_:g}")
        bh, bl, bc = big if big else (d_h, d_l, d_c)
        bp = daily_pivots(bh, bl, bc, "big")
        off = len(bh) - len(d_h)                                      # 長日 K 跟 d_* 的 index 差
        prior = [q for q in bp if q["i"] < T["i"] + off and q["t"] != T["t"]]
        if prior:
            full = prior[-1]["p"]
            for v, r in _ret(full, T["p"], RET3):
                add(v, "R3b", f"母級 {r:g}")
    for n in (5, 10, 12, 20, 60):
        add(_ma(np.r_[d_c[:-1], price], n), "R5", f"日線 {n}T")
    if b60 and len(b60) >= 30:
        h6, l6, c6 = (np.array([b[k] for b in b60], dtype=float) for k in ("high", "low", "close"))
        from . import intraday as I
        p6 = E.zigzag(h6, l6, I.theta(h6, l6, c6))
        conf, tent = E.state_at(p6, h6, l6, len(c6) - 1)
        s6 = conf + ([tent] if tent else [])
        for q in s6[-10:]:
            add(q["p"], "R0", "60 分轉折")
        if len(s6) >= 3:
            a, b, cc = s6[-3]["p"], s6[-2]["p"], s6[-1]["p"]
            for (x0, x1) in ((s6[-4]["p"], a) if len(s6) >= 4 else (None, None), (a, b), (b, cc)):
                if x0 is not None:
                    for v, r in _ret(x0, x1, RET3):
                        add(v, "R3", f"60 分 {r:g}")
            add(cc - 0.236 * (cc - b), "R3", "60 分 0.236")
            for k_ in (1.0, 1.618):                                   # C＝A：從 c 往 a→b 的方向量 k 倍 a→b
                add(cc + k_ * (b - a), "R4", f"60 分等幅 {k_:g}")
        for n in (5, 12, 20):
            add(_ma(c6, n), "R5", f"60 分 {n}T")
        if st and dates60 is not None:
            dd = np.asarray(dates60)
            i_h2, i_x = st["H2"]["i"], st["X"]["i"]
            j_h2 = np.where(dd >= i_h2)[0]
            j_x = np.where(dd >= i_x)[0]
            if len(j_h2):                                            # 60 分第 (1) 段終點（H2 之後、X 那一型的第一個轉折）
                q1 = next((q for q in s6 if q["i"] > j_h2[0] and q["t"] == st["X"]["t"]), None)
                if q1:
                    add(q1["p"], "R2", "60 分第 (1) 段終點")
            if len(j_x):
                jx0 = int(j_x[0])
                u = -st["d"]                                          # 反向段的方向
                ext_j = jx0 + int(np.argmin(l6[jx0:]) if u > 0 else np.argmax(h6[jx0:]))
                q2 = next((q for q in s6 if q["i"] > ext_j and q["t"] == ("H" if u > 0 else "L")), None)
                if q2:
                    add(q2["p"], "R2", "60 分反向段第 (1) 段終點")
                # R6 起推底座、R7 箱體（全部換成「往上」的座標算：y＝u×p）
                Xp, rb = st["X"]["p"], st["rb"]
                seq = [q for q in s6 if q["i"] >= ext_j]
                y = lambda p: u * p                                   # noqa: E731
                tops = [q for q in seq if q["t"] == ("H" if u > 0 else "L")]
                if tops:
                    top = max(tops, key=lambda q: (y(q["p"]), -q["i"]))
                    base = [q for q in seq if q["i"] < top["i"] and q["t"] != top["t"] and y(top["p"]) - y(q["p"]) >= 0.5 * abs(top["p"] - Xp)]
                    if base:
                        add(base[-1]["p"], "R6", "起推底座")
                    lows = [q for q in seq if q["i"] > top["i"] and q["t"] != top["t"]]
                    if lows:
                        lo = min(lows, key=lambda q: y(q["p"]))
                        if y(top["p"]) - y(lo["p"]) >= 0.382 * abs(top["p"] - Xp) and y(lo["p"]) > y(Xp):
                            his = [q for q in seq if q["i"] > lo["i"] and q["t"] == top["t"]]
                            if his:
                                hi = max(his, key=lambda q: y(q["p"]))
                                if y(hi["p"]) < y(top["p"]) and y(hi["p"]) - y(lo["p"]) >= 0.5 * abs(top["p"] - lo["p"]):
                                    add(top["p"], "R7", "箱頂")
                                    add(lo["p"], "R7", "箱底")
                                    add(hi["p"], "R7", "出箱門")
                                    fl = [q for q in seq if q["i"] > hi["i"] and q["t"] != top["t"]]
                                    if fl:
                                        add(min(fl, key=lambda q: y(q["p"]))["p"], "R7", "結構底線")
            if len(j_h2) and len(j_x):                               # R8 套牢區：H2→X 這段的 60 分成交分布
                k0 = int(j_h2[0]) + int(np.argmax(h6[int(j_h2[0]):]) if st["d"] < 0 else np.argmin(l6[int(j_h2[0]):]))
                k1 = int(j_x[0]) + int(np.argmin(l6[int(j_x[0]):]) if st["d"] < 0 else np.argmax(h6[int(j_x[0]):]))
                seg = b60[min(k0, k1):max(k0, k1) + 1]
                for z in VO.trapped(seg, price)[:2]:
                    add(z["lo"], "R8", "套牢區下緣")
                    add(z["hi"], "R8", "套牢區上緣")
    return {"levels": out, "st": st, "m": m}


# ── 考卷 B：每天收盤判一個方向 ────────────────────────────────────────────────
def call(m: list, h, l, price: float) -> dict:
    """PLAN §5：S1 還沒碰到重疊線 → 判 d；S2 越過重疊線、還沒到 W0.382 → 判 −d；S3 W0.382～0.618 → 不判；S4 越過 W0.618 → 判 −d"""
    st = structure(m, h, l, price)
    if not st or not st["beyond"]:
        return {"s": None, "call": 0}
    T, L1, X, d = st["T"]["p"], st["L1"]["p"], st["X"]["p"], st["d"]
    w382, w618 = X - 0.382 * (X - T), X - 0.618 * (X - T)
    y = lambda p: -d * p                                              # noqa: E731  反向段方向為正
    if y(price) < y(L1):
        return {"s": "S1", "call": d}
    if y(price) < y(w382):
        return {"s": "S2", "call": -d}
    if y(price) < y(w618):
        return {"s": "S3", "call": 0}
    return {"s": "S4", "call": -d}
