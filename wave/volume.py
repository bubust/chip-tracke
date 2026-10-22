"""B80 成交量（PLAN-B80 §5.3、§5.4、§6.3）：純函式，不碰網路與資料庫；網站和 research/b80 用同一份。
- 相對量 rvol：分 K＝這根量 ÷ 之前已收完的最多 20 個交易日「同一時段」的平均（不含今天、不含這根；開盤收盤量本來就大）；
  日 K／週 K＝÷ 前 20 根平均。分 K 同時段樣本 <5 → 不判斷（不退回一般平均，開盤那幾根會永遠被算成放量）
- 波段：用該週期自己的 ZigZag（只用確認時間 ≤ t 的轉折）。現在這段越過前一個同方向轉折＝「最後一推檢查」；
  還沒越過＝修正中，看空間（回幾 %）、時間（K 棒數比）、修正量能
- 帶量突破：收盤第一次越過上一個已確認轉折高（低）點，那根 rvol ≥1.3＝帶量、<1.0＝沒量
- 成交密集區：顯示範圍內按 0.25 ATR 分格、每根的量平均攤到最低～最高經過的格子（沒有量就算停留根數），取最大、彼此距離 ≥1 ATR、不重疊的前 2 區，每區最寬 1.5 ATR
量是 0 或缺＝沒有資料（不是量縮）"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

RV_HOT, RV_UP, RV_LOW = 2.0, 1.3, 0.7       # 爆量、放量、量縮
N_REF, MIN_N = 20, 5
BREAK_UP, BREAK_LOW = 1.3, 1.0              # 帶量／沒量突破
LEG_SHRINK, LEG_SWELL = 0.85, 1.15          # 修正量縮／帶量
MAT_SPACE, MAT_TIME, SPACE_MIN = 0.362, 0.8, 0.236
PUSH_LAST, PUSH_OK = 3, 1                   # ≥3 項像最後一推、≤1 項像續推
MIN_LEG_RV = 3                              # 一段至少幾根有 rvol 才比量
FIBS = (0.236, 0.382, 0.5, 0.618, 0.786)
ZONE_EXPAND, ZONE_MAX_BINS = 0.7, 6         # 成交密集區：格子 ≥ 高峰 70% 才併進來、最寬 6 格（1.5 ATR）
BREAK_LOOK = {"15m": 40, "30m": 20, "60m": 12, "1d": 10, "1wk": 30}   # 週 K 的力道／突破用日 K 中級轉折算（B76 起週 K 分析用日 K），所以是 30 根日 K


def vol_of(b) -> Optional[float]:
    v = b.get("volume") if isinstance(b, dict) else b
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def rv_label(r: Optional[float]) -> str:
    if r is None:
        return "—"
    return "爆量" if r >= RV_HOT else "放量" if r >= RV_UP else "量縮" if r <= RV_LOW else "正常"


# ── 相對量 ──────────────────────────────────────────────────────────────────
def rvol_slots(bars: list, slot_fn, n: int = N_REF, min_n: int = MIN_N) -> tuple:
    """分 K：slot_fn(bar)→同時段的鍵（盤別, 第幾根）。回傳 (每根 rvol, 每個時段最後的參考均量)。
    每根只跟「之前」的同時段比；進行中（partial）那根不放進參考"""
    hist: dict = {}
    out = []
    for b in bars:
        k = slot_fn(b)
        v = vol_of(b)
        q = hist.get(k) if k is not None else None
        ref = (sum(q) / len(q)) if q and len(q) >= min_n else None
        out.append(None if v is None or not ref else v / ref)
        if k is not None and v is not None and not b.get("partial"):
            q = hist.setdefault(k, [])
            q.append(v)
            if len(q) > n:
                q.pop(0)
    refs = {k: sum(q) / len(q) for k, q in hist.items() if len(q) >= min_n}
    return out, refs


def rvol_plain(vols: list, n: int = N_REF, min_n: int = MIN_N) -> list:
    """日 K／週 K：÷ 前 n 根（有量的）平均，不含這根"""
    out = []
    past: list = []
    for v in vols:
        v = vol_of(v)
        ref = (sum(past) / len(past)) if len(past) >= min_n else None
        out.append(None if v is None or not ref else v / ref)
        if v is not None:
            past.append(v)
            if len(past) > n:
                past.pop(0)
    return out


PARTIAL_MIN = 0.2                           # 進行中那根走不到 20% 的時間不判斷（R2 Gemini F1）


def partial_rvol(v: Optional[float], ref: Optional[float], elapsed_s: float, length_s: float) -> Optional[float]:
    """進行中那根：目前量 ÷（同時段平均 × 已經過的比例）；比例 <0.2 → None（剛開始，不判斷），之後不設下限"""
    v = vol_of(v)
    if v is None or not ref or length_s <= 0:
        return None
    frac = min(1.0, elapsed_s / length_s)
    if frac < PARTIAL_MIN:
        return None
    return v / (ref * frac)


def day_estimate(cum_now: Optional[float], frac_samples: list) -> Optional[dict]:
    """日 K 盤中預估：今天累計 ÷ 過去各天「同一時間累計占全天」的中位數"""
    cum_now = vol_of(cum_now)
    fr = [f for f in frac_samples if f is not None and 0.03 <= f <= 1.0]
    if cum_now is None or len(fr) < MIN_N:
        return None
    f = float(np.median(fr))
    return {"est": cum_now / f, "frac": f, "n": len(fr)}


# ── 波段力道、修正成熟度 ────────────────────────────────────────────────────
def ema(x: np.ndarray, n: int) -> np.ndarray:
    out = np.empty(len(x))
    a = 2.0 / (n + 1)
    m = np.nan
    for i, v in enumerate(x):
        m = v if not np.isfinite(m) else m + a * (v - m)
        out[i] = m
    return out


def macd_dif(c: np.ndarray) -> np.ndarray:
    c = np.asarray(c, float)
    return ema(c, 12) - ema(c, 26)


def _mean_rv(rv: list, a: int, b: int) -> Optional[float]:
    """第 a+1～b 根（含 b）的平均 rvol；有值的不到 MIN_LEG_RV 根 → None"""
    xs = [rv[k] for k in range(max(0, a + 1), min(len(rv), b + 1)) if rv[k] is not None]
    return float(np.mean(xs)) if len(xs) >= MIN_LEG_RV else None


def _nearest_fib(r: float) -> float:
    return min(FIBS, key=lambda f: abs(f - r))


def leg_info(h, l, c, rv: list, dif, piv: list, t: Optional[int] = None, price: Optional[float] = None) -> Optional[dict]:
    """piv：確認時間 ≤ t 的轉折（{i, p, t:'H'/'L'}，時間順序）。現在這段＝最後一個轉折 → t。
    回傳 mode＝push（越過前一個同方向轉折）或 corr（修正中）及各項"""
    t = len(c) - 1 if t is None else t
    piv = [p for p in piv if p["i"] <= t]
    if len(piv) < 3:
        return None
    P1, P2, P3 = piv[-1], piv[-2], piv[-3]
    if P1["i"] >= t:
        return None
    d = 1 if P1["t"] == "L" else -1
    lo, hi = P1["i"], t
    if d > 0:
        k_ext = lo + int(np.argmax(h[lo:hi + 1]))
        ext = float(h[k_ext])
    else:
        k_ext = lo + int(np.argmin(l[lo:hi + 1]))
        ext = float(l[k_ext])
    px = float(c[t]) if price is None else float(price)
    if price is not None:                        # 盤中現價可能已經超過收完那根的極值
        if (px - ext) * d > 0:
            ext = px
    out = {"dir": d, "start": {"i": P1["i"], "p": P1["p"]}, "ext": ext, "k_ext": k_ext, "bars": t - P1["i"],
           "price": px}
    if (ext - P2["p"]) * d > 0:                  # 越過前一個同方向轉折＝這一推
        amp_cur, amp_prev = abs(ext - P1["p"]), abs(P2["p"] - P3["p"])
        vc, vp = _mean_rv(rv, P1["i"], t), _mean_rv(rv, P3["i"], P2["i"])
        s1 = amp_cur < amp_prev
        s2 = None if vc is None or vp is None else vc < vp
        s3 = None
        if dif is not None and len(dif) > max(k_ext, P2["i"]) and np.isfinite(dif[k_ext]) and np.isfinite(dif[P2["i"]]):
            s3 = bool((dif[k_ext] - dif[P2["i"]]) * d < 0)
        s4 = (px - P2["p"]) * d < 0
        sig = [s1, s2, s3, s4]
        n = sum(1 for s in sig if s)
        known = sum(1 for s in sig if s is not None)
        span = ext - P1["p"]
        out.update(mode="push", prev={"from": P3["p"], "to": P2["p"], "bars": P2["i"] - P3["i"]},
                   amp_ratio=amp_cur / amp_prev if amp_prev else None, vol_cur=vc, vol_prev=vp,
                   vol_ratio=(vc / vp) if vc is not None and vp else None,
                   signals={"amp": s1, "vol": s2, "mom": s3, "hold": s4}, n=n, known=known,
                   retain=(px - P1["p"]) / span if span else None,
                   verdict="last" if n >= PUSH_LAST else "ok" if n <= PUSH_OK and known >= 3 else "mixed")
    else:                                        # 還沒越過＝修正前一段（P2 → P1）
        amp_opp = abs(P1["p"] - P2["p"])
        space = abs(ext - P1["p"]) / amp_opp if amp_opp else None
        tr = (t - P1["i"]) / max(1, P1["i"] - P2["i"])
        vc, vp = _mean_rv(rv, P1["i"], t), _mean_rv(rv, P2["i"], P1["i"])
        vr = (vc / vp) if vc is not None and vp else None
        out.update(mode="corr", prev={"from": P2["p"], "to": P1["p"], "bars": P1["i"] - P2["i"]},
                   space=space, fib=_nearest_fib(space) if space is not None else None, time=tr,
                   vol_cur=vc, vol_prev=vp, vol_ratio=vr,
                   vol_state=None if vr is None else "shrink" if vr <= LEG_SHRINK else "swell" if vr >= LEG_SWELL else "flat",
                   mature=bool(space is not None and space >= MAT_SPACE and tr >= MAT_TIME),
                   shallow=bool(space is not None and space < SPACE_MIN))
    return out


# ── 帶量突破 ────────────────────────────────────────────────────────────────
def breakouts(c, rv: list, piv: list, look: int, t: Optional[int] = None, k_max: int = 3) -> list:
    """最近 look 根裡，收盤第一次越過「上一個已確認轉折高（低）點」的那根（piv 要有 ci＝確認的那根）"""
    t = len(c) - 1 if t is None else t
    ev = []
    for k in range(max(1, t - look + 1), t + 1):
        for typ, d in (("H", 1), ("L", -1)):
            last = None
            for p in piv:
                ci = p.get("ci")
                if p["t"] == typ and ci is not None and ci < k:
                    last = p
            if last is None:
                continue
            lv = last["p"]
            if (c[k] - lv) * d > 0 and (c[k - 1] - lv) * d <= 0:
                r = rv[k] if k < len(rv) else None
                ev.append({"k": k, "dir": d, "level": float(lv), "rv": r,
                           "kind": None if r is None else "vol" if r >= BREAK_UP else "dry" if r < BREAK_LOW else "mid"})
    return ev[-k_max:]


# ── 成交密集區 ──────────────────────────────────────────────────────────────
def vol_zones(h, l, c, v: list, atr: float, look: int, k: int = 2) -> list:
    """最近 look 根的量（沒有量就用 1）攤到最低～最高的格子；回傳 [{lo, hi, mid, share, by}]（share＝這區占總量）"""
    n = len(c)
    if n == 0 or not atr or not np.isfinite(atr) or atr <= 0:
        return []
    a = max(0, n - look)
    hh, ll, cc = np.asarray(h[a:], float), np.asarray(l[a:], float), np.asarray(c[a:], float)
    vv = [vol_of(x) for x in v[a:]] if v is not None else []
    has_v = sum(1 for x in vv if x is not None) >= 0.8 * len(cc)
    w = np.array([(x if x is not None else 0.0) for x in vv], float) if has_v else np.ones(len(cc))
    width = 0.25 * atr
    lo0 = float(np.nanmin(ll))
    nb = int((float(np.nanmax(hh)) - lo0) / width) + 1
    if nb < 3 or w.sum() <= 0:
        return []
    bins = np.zeros(nb)
    for x0, x1, ww in zip(ll, hh, w):          # 一根的量平均攤到最低～最高經過的每一格（R2 Gemini F2）
        if not (np.isfinite(x0) and np.isfinite(x1)) or ww <= 0:
            continue
        j0 = min(nb - 1, int((x0 - lo0) / width))
        j1 = min(nb - 1, max(j0, int((x1 - lo0) / width)))
        bins[j0:j1 + 1] += ww / (j1 - j0 + 1)
    tot = bins.sum()
    picked = []
    used = np.zeros(nb, bool)
    for b in np.argsort(-bins):
        if bins[b] <= 0 or len(picked) >= k:
            break
        mid = lo0 + (b + 0.5) * width
        if used[b] or any(abs(mid - z["mid"]) < atr for z in picked):
            continue
        # 往兩邊擴：那一格 ≥ 高峰 70%、整區最寬 1.5 ATR（6 格）、不跟已經選的區重疊
        j0 = j1 = int(b)
        while j1 - j0 + 1 < ZONE_MAX_BINS:
            left = bins[j0 - 1] if j0 - 1 >= 0 and not used[j0 - 1] else -1
            right = bins[j1 + 1] if j1 + 1 < nb and not used[j1 + 1] else -1
            if max(left, right) < ZONE_EXPAND * bins[b]:
                break
            if left >= right:
                j0 -= 1
            else:
                j1 += 1
        used[j0:j1 + 1] = True
        picked.append({"lo": round(lo0 + j0 * width, 2), "hi": round(lo0 + (j1 + 1) * width, 2), "mid": round(mid, 2),
                       "share": round(float(bins[j0:j1 + 1].sum() / tot), 3), "by": "vol" if has_v else "time"})
    return picked


# ── 白話（AI 圓桌、推播用；網站前端自己組字）──────────────────────────────────
def describe(vx: Optional[dict], tfn: str = "") -> str:
    """快照 volume[tf] → 一句白話"""
    if not vx or not vx.get("ok"):
        return f"{tfn}：量能算不出來"
    if not vx.get("has_vol"):
        return f"{tfn}：{vx.get('note') or '沒有量的資料'}"
    s = []
    la = vx.get("last") or {}
    if la.get("rv") is not None:
        s.append(f"最後一根量 {la['rv']:.1f} 倍（{la.get('label')}）")
    lg = vx.get("leg") or {}
    word = "上漲" if lg.get("dir") == 1 else "下跌"
    if lg.get("mode") == "push":
        sg = lg.get("signals") or {}
        names = [nm for k, nm in (("amp", "漲幅縮小" if lg.get("dir") == 1 else "跌幅縮小"), ("vol", "量沒放大"), ("mom", "動能背離"),
                                  ("hold", "過了又站不住")) if sg.get(k)]
        v = {"last": "像最後一推", "ok": "像續推", "mixed": "力道轉弱中"}.get(lg.get("verdict"), "")
        s.append(f"這段{word}已過前{'高' if lg.get('dir') == 1 else '低'}：{('、'.join(names) or '四項都沒出現')}（{lg.get('n')}/4）→ {v}")
    elif lg.get("mode") == "corr":
        sp = lg.get("space")
        tm = lg.get("time")
        m = "空間、時間都到了" if lg.get("mature") else "空間不足" if lg.get("shallow") else "還沒到"
        vs = {"shrink": "量縮修正（健康）", "swell": "帶量修正（賣壓重）" if lg.get("dir") == -1 else "帶量反彈", "flat": "量能持平"}.get(lg.get("vol_state"), "")
        if sp is not None:
            s.append(f"修正前一段 {sp * 100:.0f}%（接近 {lg.get('fib')}）、時間 {tm:.1f} 倍 → {m}" + (f"；{vs}" if vs else ""))
    br = (vx.get("breaks") or [])[-1:] or []
    for e in br:
        k = {"vol": "帶量", "dry": "沒量", "mid": "量普通"}.get(e.get("kind"), "")
        s.append(f"{e.get('t') or ''} {k}{'突破' if e['dir'] == 1 else '跌破'} {e['level']:,.0f}".strip())   # 原始 breakouts() 沒有 t（審查 R2 F1）
    return f"{tfn}：" + "；".join(s) if s else f"{tfn}：量能沒有特別訊號"
