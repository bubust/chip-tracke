"""B93 她 11/4 的方法（@fanny55520 台指期）：多週期逐層驗證——小級的「大、中、小」五段＋兩道關卡；台指期跟個股共用。

她 11/4：47,607 起跌到 42,050 是 60 分「大、中、小」三段動能逐漸收斂（大 47,607→44,052、中 45,487→42,925、小 44,069→42,050）
- 第一道關（安全門）＝小級第 (1) 段終點 44,052（1、4 不重疊）＋整段 47,607→42,050 的 0.382（44,173）＋日線 5 均（44,154）：
  彈過並站穩＝這組跌勢在 42,050 走完五段、轉入修正反彈，短線連續破底的危機才化解；在這裡遇壓折返＝小級還沒跌完、還有破底段
- 第二道關＝大級第 (1) 段終點 45,523：大級第 (4) 段反彈在 0.5（44,829）～日線 10 均（45,357）～45,523 受阻 → 大級再殺第 (5) 段
  （或至少回測底部）；就算越過 45,523，也先當「大 B 波反彈震盪」，要站穩、回測、看籌碼換手才分辨
- 進場：短線看 0.382 有沒有真過，壓回的第二隻腳落在這段反彈的 0.382～0.5 才做多（還要技術面確認止跌），目標整段 0.5；追高沒有肉

級數：台指期＝日 K（大級）＋60 分（小級）；個股只有日 K → 大級＝日 K 中級轉折（平均一段約 38 天）、小級＝日 K 小級轉折（約 10 天）。
方向對稱：跌勢看反彈的關卡；漲勢（大級第 3 段創高）看拉回的關卡。只描述結構與價位，不是買賣建議。"""
from __future__ import annotations

from typing import Optional

import numpy as np


def _fmt(p) -> str:
    """千以上取整（四捨五入，44,828.5 → 44,829，跟她寫的一樣）；以下留兩位"""
    import math
    x = float(p)
    if abs(x) >= 1000:
        return f"{int(math.floor(x + 0.5)):,}"
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def _drop_smallest(seq: list) -> Optional[list]:
    """把最小的一段（相鄰兩個轉折）併掉；起點、極值、最後一點不動（同 wave.nest.drop_smallest）"""
    from wave.nest import drop_smallest
    return drop_smallest(seq)


def tentative(piv: list, h, l) -> Optional[dict]:
    """最後一個確認轉折之後、反方向走到現在的極值（還沒確認的轉折）"""
    if not piv:
        return None
    last = piv[-1]
    i0 = last["i"] + 1
    if i0 >= len(h):
        return None
    if last["t"] == "H":
        k = i0 + int(np.argmin(l[i0:]))
        return {"i": k, "p": float(l[k]), "t": "L"}
    k = i0 + int(np.argmax(h[i0:]))
    return {"i": k, "p": float(h[k]), "t": "H"}


def structure(big: list, small: list, price: float, ma5: Optional[float] = None, ma10: Optional[float] = None,
              labels: Optional[dict] = None) -> Optional[dict]:
    """big：大級轉折（舊→新，含最後還沒確認的那個），至少 [T, L1, H2, X]；small：小級轉折，從 H2 開始、到現在（含暫定）。
    price：現價；ma5／ma10：大級的 5、10 均（台指期＝日線）。labels：{"big": "日線", "small": "60 分"}（顯示用）。
    回 {dir, case, big:{...}, small:{...}, gate1, gate2, entry, status, lines}；結構不夠回 None"""
    lb = {"big": "大級", "small": "小級", **(labels or {})}
    if len(big) < 4 or len(small) < 2:
        return None
    T, L1, H2, X = big[-4], big[-3], big[-2], big[-1]
    d = -1 if H2["t"] == "H" else 1                                   # 現在這段大級的方向（-1＝從 H2 往下跌）
    if X["t"] == H2["t"] or T["t"] != H2["t"]:
        return None
    s_dn, s_up = ("跌", "反彈") if d < 0 else ("漲", "拉回")
    v_cross, v_fail = ("站穩", "跌破") if d < 0 else ("跌破", "站穩")
    lo_hi = "低" if d < 0 else "高"
    # 現在這段大級的極值（第 3 段到現在最遠的點）＝小級序列裡順方向最遠的
    seq = [q for q in small if q.get("p") is not None]
    if not seq or seq[0]["t"] != H2["t"]:
        seq = [{"i": H2.get("i"), "p": H2["p"], "t": H2["t"]}] + [q for q in seq if q["t"] != H2["t"] or q["p"] != H2["p"]]
    ek = max(range(len(seq)), key=lambda k: d * seq[k]["p"])
    ext = seq[ek]["p"]
    after = seq[ek + 1:]
    R = (max if d < 0 else min)([float(price)] + [q["p"] for q in after])   # 極值之後反向走到哪（現價或之後的轉折）
    S = seq[:ek + 1]
    while len(S) > 6:                                                # 併到最多五段（大、(2)、中、(4)、小）
        nxt = _drop_smallest(S + [{"p": R, "t": "H" if d < 0 else "L"}])
        if nxt is None:
            break
        S = nxt[:-1]
    k = len(S) - 1
    span = abs(H2["p"] - ext)
    fib = {r: ext - d * r * span for r in (0.382, 0.5, 0.618)}
    legs = [abs(S[j]["p"] - S[j + 1]["p"]) for j in range(0, k, 2)]  # 順方向的段：大、中、小
    names = ["大", "中", "小"]
    small_out = {"seq": [{"p": q["p"], "t": q["t"], "i": q.get("i")} for q in S], "legs": [round(x, 2) for x in legs], "n_seg": k,
                 "contract": k >= 5 and all(legs[j] > legs[j + 1] for j in range(len(legs) - 1)),
                 "overlap": k >= 5 and (S[4]["p"] - S[1]["p"]) * -d > 0}
    case = "3" if (ext - L1["p"]) * d > 0 else "2"                   # 3＝已經破了大級第 1 段終點（她的日線第 (3) 段）
    # 第一道關：小級第 (1) 段終點（1、4 不重疊）＋整段 0.382；5 均靠近就一起列
    g1_lv = [(S[1]["p"], f"{lb['small']}第 (1) 段{lo_hi}點（1、4 不重疊）")] if k >= 3 else []
    g1_lv.append((fib[0.382], f"{_fmt(H2['p'])}→{_fmt(ext)} 的 0.382"))
    if ma5 and abs(ma5 / fib[0.382] - 1) < 0.015:
        g1_lv.append((ma5, f"{lb['big']} 5 均"))
    g1_lo, g1_hi = sorted(v for v, _ in g1_lv)[0], sorted(v for v, _ in g1_lv)[-1]
    far1 = g1_hi if d < 0 else g1_lo                                  # 要越過的那一邊
    beyond = lambda v: (price - v) * -d > 0                           # noqa: E731  反向越過 v
    gate1 = {"lo": round(g1_lo, 2), "hi": round(g1_hi, 2), "far": round(far1, 2), "lv": [(round(v, 2), t) for v, t in g1_lv],
             "passed": beyond(far1), "touched": any(beyond(v) for v, _ in g1_lv)}
    # 第二道關：大級第 1 段終點（大級第 4 段不能碰到它）；前面先過 0.5、10 均
    gate2 = None
    if case == "3":
        g2_lv = [(fib[0.5], f"{_fmt(H2['p'])}→{_fmt(ext)} 的 0.5")]
        if ma10 and (ma10 - fib[0.5]) * -d > 0 and (L1["p"] - ma10) * -d > 0:
            g2_lv.append((ma10, f"{lb['big']} 10 均"))
        g2_lv.append((L1["p"], f"{lb['big']}第 (1) 段{lo_hi}點（4 不重疊 1）"))
        gate2 = {"price": L1["p"], "zone": [round(v, 2) for v, _ in g2_lv], "lv": [(round(v, 2), t) for v, t in g2_lv],
                 "passed": beyond(L1["p"])}
    # 進場（她：0.382 真過以後，壓回第二隻腳落在這段反彈的 0.382～0.5）
    reb = abs(R - ext)
    entry = None
    if gate1["passed"] and reb > 0:
        z = sorted([R + d * 0.382 * reb, R + d * 0.5 * reb])
        entry = {"zone": [round(z[0], 2), round(z[1], 2)], "from": [ext, round(R, 2)], "target": round(fib[0.5], 2),
                 "t": f"等{s_up}的第二隻腳：壓回到這段{s_up}（{_fmt(ext)}→{_fmt(R)}）的 0.382～0.5＝{_fmt(z[0])}～{_fmt(z[1])}，"
                      f"技術面確認止{s_dn}才進場，目標 0.5 {_fmt(fib[0.5])}；追{'高' if d < 0 else '低'}沒有肉"}
    # 結構文字
    leg_t = "、".join(f"{names[j]} {_fmt(legs[j])}" for j in range(min(3, len(legs))))
    if k >= 5:
        shape = (f"{lb['small']}「大、中、小」五段（{leg_t}）" + ("，動能逐漸收斂" if small_out["contract"] else "，但沒有一段比一段小")
                 + ("；第 (4) 段碰到第 (1) 段的領地＝收斂楔形（結束型）" if small_out["overlap"] else "") + "：具備走完的條件")
    elif k == 3:
        shape = f"{lb['small']}只走了「大、中」兩段（{leg_t}）：第 (3) 段還在走，後面通常還有一段"
    else:
        shape = f"{lb['small']}一路{s_dn}、還沒有像樣的{s_up}（{_fmt(H2['p'])}→{_fmt(ext)}）"
    if case == "3":
        head = (f"{lb['big']}：{_fmt(T['p'])}→{_fmt(L1['p'])}＝(1)、→{_fmt(H2['p'])}＝(2)、{_fmt(H2['p'])} 起{s_dn}＝(3)"
                f"（也可能是 A-B-C 的 C），{s_dn}到 {_fmt(ext)}")
    else:
        head = (f"{lb['big']}：{_fmt(T['p'])}→{_fmt(L1['p'])}→{_fmt(H2['p'])}，現在這段{s_dn}到 {_fmt(ext)} 還沒{'跌破' if d < 0 else '漲過'} "
                f"{_fmt(L1['p'])}（還在 (2)／B 的範圍）")
    if gate2 and gate2["passed"]:
        status = (f"已經{v_cross}第二道關 {_fmt(L1['p'])}：三段式告一段落，但先當「大 B 波{s_up}震盪」，"
                  f"要{v_cross}之後回測守住、看籌碼換手，才分辨是不是新的一波")
        tag = "B"
    elif gate1["passed"]:
        status = (f"已經{v_cross}第一道關 {_fmt(gate1['lo'])}～{_fmt(gate1['hi'])}：{lb['small']}這組{s_dn}勢先當走完、轉入修正{s_up}"
                  + (f"（{lb['big']}第 (4) 段）；下一道關 {_fmt(L1['p'])}" if gate2 else ""))
        tag = "4"
    elif gate1["touched"]:
        status = (f"正在第一道關 {_fmt(gate1['lo'])}～{_fmt(gate1['hi'])}：過了一部分、還沒站穩；在這裡被壓回＝{lb['small']}還沒{s_dn}完，"
                  f"隨時再{s_dn}出一段破{lo_hi}")
        tag = "at1"
    else:
        status = (f"還在第一道關 {_fmt(gate1['lo'])}～{_fmt(gate1['hi'])} 前面：{s_up}只是止{s_dn}反應（單根長{'下' if d < 0 else '上'}影線不等於落底），"
                  f"過不去轉弱＝還有一段破{lo_hi}")
        tag = "below1"
    lines = [head, shape, status]
    lines.append(f"第一道關（安全門）{_fmt(gate1['lo'])}～{_fmt(gate1['hi'])}：" + "、".join(f"{t} {_fmt(v)}" for v, t in gate1["lv"])
                 + f" → {v_cross}＝{lb['small']}{s_dn}勢在 {_fmt(ext)} " + ("走完五段" if k >= 5 else "先告一段落")
                 + f"、轉入修正；遇壓折返＝還沒{s_dn}完")
    if gate2:
        lines.append(f"第二道關 {_fmt(L1['p'])}：{lb['big']}第 (4) 段在 " + "～".join(_fmt(v) for v in gate2["zone"])
                     + f" 受阻（4 不重疊 1）→ {lb['big']}再{s_dn}第 (5) 段破 {_fmt(ext)}（或至少回測）；"
                     + f"就算{v_cross} {_fmt(L1['p'])}，也先當大 B 波{s_up}震盪")
    if entry:
        lines.append(entry["t"])
    else:
        lines.append(f"進場：先看 0.382 {_fmt(fib[0.382])} 有沒有真的{'過' if d < 0 else '破'}，之後壓回的第二隻腳（{s_up}的 0.382～0.5）才考慮；"
                     "現在追沒有肉")
    return {"dir": d, "case": case, "tag": tag, "labels": lb,
            "big": {"T": T["p"], "L1": L1["p"], "H2": H2["p"], "ext": ext},
            "small": small_out, "fib": {str(r): round(v, 2) for r, v in fib.items()}, "rebound": round(R, 2),
            "gate1": gate1, "gate2": gate2, "entry": entry, "status": status, "lines": lines}


def analyze_daily(df, price: Optional[float] = None) -> Optional[dict]:
    """個股日 K → structure()：大級＝日 K 中級轉折、小級＝日 K 小級轉折；5、10 均＝日線"""
    from wave import engine as E
    if df is None or len(df) < 120:
        return None
    h = df["high"].astype(float).to_numpy()
    l = df["low"].astype(float).to_numpy()
    c = df["close"].astype(float).to_numpy()
    if np.isnan(h[-120:]).any() or np.isnan(l[-120:]).any():
        return None
    px = float(price if price is not None else c[-1])
    bp = E.zigzag(h, l, E.thresholds(h, l, c, "mid"))
    tb = tentative(bp, h, l)
    big = bp + ([tb] if tb else [])
    if len(big) < 4:
        return None
    H2 = big[-2]
    sp = E.zigzag(h, l, E.thresholds(h, l, c, "small"))
    ts = tentative(sp, h, l)
    small = [q for q in sp if q["i"] > H2["i"]] + ([ts] if ts and ts["i"] > H2["i"] else [])
    small = [{"i": H2["i"], "p": H2["p"], "t": H2["t"]}] + small
    ma5 = float(np.mean(c[-5:])) if len(c) >= 5 else None
    ma10 = float(np.mean(c[-10:])) if len(c) >= 10 else None
    out = structure(big, small, px, ma5, ma10, {"big": "中級（日 K 波段）", "small": "小級（日 K 短線）"})
    if out:
        dates = [str(x) for x in df["date"].tolist()] if "date" in df.columns else None
        if dates:
            for q in out["small"]["seq"]:
                if q.get("i") is not None and 0 <= q["i"] < len(dates):
                    q["date"] = dates[q["i"]]
            out["big"]["dates"] = {k: dates[q["i"]] for k, q in zip(("T", "L1", "H2", "X"), big[-4:]) if 0 <= q["i"] < len(dates)}
    return out
