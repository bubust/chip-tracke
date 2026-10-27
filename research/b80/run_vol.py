"""B80 量能規則回測（PLAN-B80 §7，事先判準；門檻全部事先定好、不調整）
資料
- D1：加權日 K 2000～（wave.db idx_daily 官方開高低收）＋證交所 FMTQIK 成交金額（data/turnover.csv）
- D2：加權 60 分 K（Yahoo 730 天，data/twii_60m.csv）＋證交所 MI_5MINS 每天彙總成同一小時（data/mi5/*.csv）
- D3：台指期 60 分 K（wave.db bars5，約 45 天）只報告
防偷看：每個事件在當根收盤判斷，只用確認時間 ≤ 當根的轉折（ci ≤ t）、rvol 只用之前的資料；結果從下一根開始算
檢定
- V1 帶量突破：收盤第一次越過上一個已確認轉折高（低）點；A＝rvol≥1.3、B＝<1.0；成功＝H 根內先多走 1 ATR、不是先收回關卡內 0.3 ATR
- V2 最後一推：順向段第一次超過前一個同方向轉折；①幅度小 ②量沒放大 ③動能背離；A＝≥2 項、B＝0 項（三項都算得出來）；
  結果＝H 根內先回吐這段 50%（見頂）、不是先再多走 1 ATR
- V2b：V2 事件後第 3 根收盤回到前高以下（站不住）vs 沒有；結果同 V2（從第 4 根起算）
- V3 成熟度：修正段第一次「空間 ≥0.362 且時間 ≥0.8」vs 第一次「空間 ≥0.362 但時間 <0.5」；結果＝H 根內先順原方向走 1 ATR、不是修正再延伸 1 ATR
- V4 修正量能：修正段第一次空間 ≥0.236 時，A＝量縮（≤0.85）、B＝帶量（≥1.15）；結果同 V3
- V5 成交密集區：每 5 根算一次成交密集區（wave.volume.vol_zones，跟網站同一份）；之後 20 根內第一次碰到 → 先反彈 1 ATR、不是先穿過 0.5 ATR；
  對照＝同樣距離分布、同一邊的隨機價位帶
- 隨機漫步對照（實作時加的，比計畫嚴格）：每筆事件依「離兩邊的距離」算隨機走勢先碰到成功那邊的機率 p＝d反向÷(d成功＋d反向)，
  比的是「實際−p」（扣掉距離造成的差異；例：站不住那組本來就離回吐 50% 比較近）
- ✅：扣掉隨機漫步後的差距（A−B）≥ 8 個百分點、每組 ≥30 筆、同一年內打亂組別 2,000 次的置換檢定 p 值經 BH（D1、D2 全部一起）<0.05、
  D1 四個時期（2000–06／07–12／13–19／20–26）、D2 前後半方向都一樣；否則 △
輸出 results/vol.json、REPORT.md；merge 進 wave/stats.json 的 volume"""
import csv
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
from wave import engine as E, futdata as FD, volume as VO  # noqa: E402

DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "results")
STATS = os.path.join(ROOT, "wave", "stats.json")
TW = timezone(timedelta(hours=8))
RNG = np.random.default_rng(20261022)
N_PERM = 2000
MIN_N = 30
MIN_DIFF = 0.08
H = {"D1": 10, "D2": 15, "D3": 15}
INTRA_M = 2.0           # stats.json intraday（B75 校準）
PERIODS_D1 = (("2000", "2006"), ("2007", "2012"), ("2013", "2019"), ("2020", "2026"))


# ── 資料 ─────────────────────────────────────────────────────────────────────
def load_d1():
    con = sqlite3.connect(os.path.join(ROOT, "chip_data", "wave.db"))
    rows = con.execute("SELECT date,o,h,l,c FROM idx_daily WHERE sym='TWII' AND date>='2000-01-01' ORDER BY date").fetchall()
    to = {}
    with open(os.path.join(DATA, "turnover.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            to[r["date"]] = float(r["amt"])
    d = [r[0] for r in rows]
    o, h, l, c = (np.array([r[k] for r in rows], float) for k in (1, 2, 3, 4))
    v = [to.get(x) for x in d]
    return {"name": "D1", "dates": d, "years": np.array([int(x[:4]) for x in d]), "o": o, "h": h, "l": l, "c": c, "v": v,
            "th": E.thresholds(h, l, c, "small"), "slot": None}


def _mi5(day: str):
    p = os.path.join(DATA, "mi5", day.replace("-", "") + ".csv")
    if not os.path.exists(p):
        return None
    out = []
    with open(p, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            hh, mm, ss = (int(x) for x in r["time"].split(":"))
            out.append((hh * 3600 + mm * 60 + ss, float(r["cum_amt"])))
    return out


def _cum_at(cum, T):
    v = 0.0
    for s, x in cum:
        if s <= T:
            v = x
        else:
            break
    return v


def load_d2():
    rows = []
    with open(os.path.join(DATA, "twii_60m.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append((int(r["ts"]), float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"])))
    rows.sort()
    cache = {}
    vols, keep = [], []
    for ts, o, h, l, c in rows:
        dt = datetime.fromtimestamp(ts, TW)
        day = dt.strftime("%Y-%m-%d")
        if day not in cache:
            cache[day] = _mi5(day)
        cum = cache[day]
        s = dt.hour * 3600 + dt.minute * 60
        if s < 9 * 3600 or s >= 13 * 3600 + 30 * 60:
            continue
        e = min(s + 3600, 13 * 3600 + 30 * 60)
        v = None
        if cum:
            v = _cum_at(cum, e) - (0.0 if s == 9 * 3600 else _cum_at(cum, s))
            v = v if v > 0 else None
        keep.append((ts, o, h, l, c, day, s))
        vols.append(v)
    ts = [k[0] for k in keep]
    o, h, l, c = (np.array([k[i] for k in keep], float) for i in (1, 2, 3, 4))
    th = np.maximum(0.005, INTRA_M * np.where(np.isnan(E.atr_pct_median(h, l, c)), 0.005 / INTRA_M, E.atr_pct_median(h, l, c)))
    return {"name": "D2", "dates": [k[5] for k in keep], "years": np.array([int(k[5][:4]) for k in keep]), "ts": ts,
            "o": o, "h": h, "l": l, "c": c, "v": vols, "th": th, "slot": [k[6] for k in keep]}


def load_d3():
    con = sqlite3.connect(os.path.join(ROOT, "chip_data", "wave.db"))
    rows = [tuple(r) for r in con.execute("SELECT ts,o,h,l,c,v FROM bars5 WHERE sym='TX' ORDER BY ts").fetchall()]
    bars = FD.agg_bars(rows, "TX", 60)
    o, h, l, c = (np.array([b[k] for b in bars], float) for k in ("open", "high", "low", "close"))
    th = np.maximum(0.005, INTRA_M * np.where(np.isnan(E.atr_pct_median(h, l, c)), 0.005 / INTRA_M, E.atr_pct_median(h, l, c)))
    slots = []
    for b in bars:
        s = FD.session_of("TX", b["time"])
        slots.append(None if not s else (s[0], int((b["time"] - s[1]) // 3600)))
    days = [FD.tw_dt(b["time"]).strftime("%Y-%m-%d") for b in bars]
    return {"name": "D3", "dates": days, "years": np.array([int(x[:4]) for x in days]), "o": o, "h": h, "l": l, "c": c,
            "v": [b["volume"] for b in bars], "th": th, "slot": slots}


def prep(D):
    h, l, c = D["h"], D["l"], D["c"]
    D["atr"] = E.atr(h, l, c)
    D["piv"] = E.zigzag(h, l, D["th"])
    if D["slot"] is None:
        D["rv"] = VO.rvol_plain(D["v"])
    else:
        bars = [{"volume": v, "slot": s} for v, s in zip(D["v"], D["slot"])]
        D["rv"], _ = VO.rvol_slots(bars, lambda b: b["slot"])
    D["dif"] = VO.macd_dif(c)
    D["n_vol"] = sum(1 for x in D["v"] if VO.vol_of(x) is not None)
    return D


def conf_at(piv, t):
    return [p for p in piv if p["ci"] is not None and p["ci"] <= t]


# ── 結果判斷（從 t+1 起） ────────────────────────────────────────────────────
def rw(c0, up_lv, dn_lv, success_up: bool) -> float:
    """隨機漫步（沒有漂移）先碰到成功那邊的機率：先碰上緣＝d下÷(d上＋d下)"""
    du, dd = max(0.0, up_lv - c0), max(0.0, c0 - dn_lv)
    if du + dd <= 0:
        return 0.5
    pu = dd / (du + dd)
    return pu if success_up else 1.0 - pu


def first_hit(D, t, Hn, up_lv=None, dn_lv=None, close_dn=None, close_up=None):
    """t+1～t+Hn：先碰到哪一邊。up_lv＝最高價碰到、dn_lv＝最低價碰到、close_dn／close_up＝收盤越過；回傳 'up'／'dn'／None"""
    h, l, c = D["h"], D["l"], D["c"]
    for k in range(t + 1, min(len(c), t + 1 + Hn)):
        u = (up_lv is not None and h[k] >= up_lv) or (close_up is not None and c[k] >= close_up)
        d = (dn_lv is not None and l[k] <= dn_lv) or (close_dn is not None and c[k] <= close_dn)
        if u and d:
            return "both"
        if u:
            return "up"
        if d:
            return "dn"
    return None


# ── 事件 ─────────────────────────────────────────────────────────────────────
def ev_v1(D):
    out = []
    piv, c, atr, rv = D["piv"], D["c"], D["atr"], D["rv"]
    used = set()
    Hn = H[D["name"]]
    for t in range(30, len(c) - 1):
        a = atr[t]
        if not np.isfinite(a):
            continue
        for typ, d in (("H", 1), ("L", -1)):
            last = None
            for p in piv:
                if p["ci"] is None or p["ci"] >= t:
                    break
                if p["t"] == typ:
                    last = p
            if last is None or (typ, last["i"]) in used:
                continue
            lv = last["p"]
            if (c[t] - lv) * d > 0 and (c[t - 1] - lv) * d <= 0:
                used.add((typ, last["i"]))
                r = rv[t]
                if r is None:
                    continue
                g = "A" if r >= VO.BREAK_UP else "B" if r < VO.BREAK_LOW else None
                if g is None:
                    continue
                if d > 0:
                    res = first_hit(D, t, Hn, up_lv=lv + a, close_dn=lv - 0.3 * a)
                    pr = rw(c[t], lv + a, lv - 0.3 * a, True)
                else:
                    res = first_hit(D, t, Hn, dn_lv=lv - a, close_up=lv + 0.3 * a)
                    pr = rw(c[t], lv + 0.3 * a, lv - a, False)
                ok = (res == "up") if d > 0 else (res == "dn")
                out.append({"t": t, "g": g, "y": bool(ok), "p": pr})
    return out


def _push_events(D):
    """順向段第一次超過前一個同方向轉折的那根 → (t, leg_info)"""
    piv, h, l, c, rv, dif = D["piv"], D["h"], D["l"], D["c"], D["rv"], D["dif"]
    seen = set()
    out = []
    for t in range(30, len(c) - 1):
        cf = conf_at(piv, t)
        if len(cf) < 3:
            continue
        P1, P2 = cf[-1], cf[-2]
        if P1["i"] >= t or (P1["i"], P2["i"]) in seen:
            continue
        d = 1 if P1["t"] == "L" else -1
        prev_ext = (np.max(h[P1["i"]:t]) if d > 0 else np.min(l[P1["i"]:t])) if t > P1["i"] else P1["p"]
        now_ext = h[t] if d > 0 else l[t]
        if (now_ext - P2["p"]) * d > 0 and (prev_ext - P2["p"]) * d <= 0:
            seen.add((P1["i"], P2["i"]))
            lg = VO.leg_info(h, l, c, rv, dif, cf, t)
            if lg and lg.get("mode") == "push":
                out.append((t, lg, P1, P2, d))
    return out


def _top(D, t0, P1, d, ext):
    """t0 之後：先回吐這段 50%（見頂＝True）還是先再多走 1 ATR（False）→ (結果, 隨機漫步機率)"""
    a = D["atr"][t0]
    c0 = D["c"][t0]
    half = P1["p"] + 0.5 * (ext - P1["p"])
    if d > 0:
        res = first_hit(D, t0, H[D["name"]], up_lv=ext + a, dn_lv=half)
        return res == "dn", rw(c0, ext + a, half, False)
    res = first_hit(D, t0, H[D["name"]], up_lv=half, dn_lv=ext - a)
    return res == "up", rw(c0, half, ext - a, True)


def ev_v2(D, pe):
    out = []
    for t, lg, P1, P2, d in pe:
        sg = lg["signals"]
        three = [sg["amp"], sg["vol"], sg["mom"]]
        if any(x is None for x in three) or not np.isfinite(D["atr"][t]):
            continue
        n = sum(1 for x in three if x)
        g = "A" if n >= 2 else "B" if n == 0 else None
        if g:
            y, pr = _top(D, t, P1, d, lg["ext"])
            out.append({"t": t, "g": g, "y": bool(y), "p": pr})
    return out


def ev_v2b(D, pe):
    out = []
    c = D["c"]
    for t, lg, P1, P2, d in pe:
        t3 = t + 3
        if t3 >= len(c) - 1 or not np.isfinite(D["atr"][t3]):
            continue
        ext = float(np.max(D["h"][P1["i"]:t3 + 1])) if d > 0 else float(np.min(D["l"][P1["i"]:t3 + 1]))
        fail = (c[t3] - P2["p"]) * d < 0
        y, pr = _top(D, t3, P1, d, ext)
        out.append({"t": t3, "g": "A" if fail else "B", "y": bool(y), "p": pr})
    return out


def _corr_points(D):
    """每根：修正中的 leg_info（只取 corr）"""
    piv, h, l, c, rv, dif = D["piv"], D["h"], D["l"], D["c"], D["rv"], D["dif"]
    out = []
    for t in range(30, len(c) - 1):
        cf = conf_at(piv, t)
        if len(cf) < 3:
            continue
        lg = VO.leg_info(h, l, c, rv, dif, cf, t)
        if lg and lg.get("mode") == "corr" and lg.get("space") is not None:
            out.append((t, lg, cf[-1]["i"]))
    return out


def _end(D, t, lg):
    """修正結束＝先順原方向（跟修正反向）走 1 ATR，而不是修正再延伸 1 ATR"""
    a = D["atr"][t]
    d = lg["dir"]                     # 修正段方向
    c0 = D["c"][t]
    if d < 0:                         # 往下修正：先漲 1 ATR？
        res = first_hit(D, t, H[D["name"]], up_lv=c0 + a, dn_lv=lg["ext"] - a)
        return res == "up", rw(c0, c0 + a, lg["ext"] - a, True)
    res = first_hit(D, t, H[D["name"]], up_lv=lg["ext"] + a, dn_lv=c0 - a)
    return res == "dn", rw(c0, lg["ext"] + a, c0 - a, False)


def ev_v3(D, cp):
    out, doneA, doneB = [], set(), set()
    for t, lg, leg in cp:
        if not np.isfinite(D["atr"][t]):
            continue
        if lg["space"] >= VO.MAT_SPACE and lg["time"] >= VO.MAT_TIME and leg not in doneA:
            doneA.add(leg)
            y, pr = _end(D, t, lg)
            out.append({"t": t, "g": "A", "y": bool(y), "p": pr})
        elif lg["space"] >= VO.MAT_SPACE and lg["time"] < 0.5 and leg not in doneB:
            doneB.add(leg)
            y, pr = _end(D, t, lg)
            out.append({"t": t, "g": "B", "y": bool(y), "p": pr})
    return out


def ev_v4(D, cp):
    out, done = [], set()
    for t, lg, leg in cp:
        if leg in done or lg["space"] < VO.SPACE_MIN or not np.isfinite(D["atr"][t]):
            continue
        done.add(leg)
        vr = lg.get("vol_ratio")
        if vr is None:
            continue
        g = "A" if vr <= VO.LEG_SHRINK else "B" if vr >= VO.LEG_SWELL else None
        if g:
            y, pr = _end(D, t, lg)
            out.append({"t": t, "g": g, "y": bool(y), "p": pr})
    return out


def ev_v5(D, look):
    h, l, c, atr = D["h"], D["l"], D["c"], D["atr"]
    real = []
    for t in range(look, len(c) - 21, 5):
        a = atr[t]
        if not np.isfinite(a):
            continue
        zs = VO.vol_zones(h[:t + 1], l[:t + 1], c[:t + 1], D["v"][:t + 1], a, look)
        for z in zs:
            if z["by"] != "vol" or z["lo"] <= c[t] <= z["hi"]:
                continue
            real.append((t, z["lo"], z["hi"], 1 if z["mid"] < c[t] else -1))
    dists = [((c[t] - (lo + hi) / 2) * s, hi - lo) for t, lo, hi, s in real]
    out = []

    def touch(t, lo, hi, s):
        a = atr[t]
        for k in range(t + 1, min(len(c), t + 21)):
            if (s > 0 and l[k] <= hi) or (s < 0 and h[k] >= lo):
                if s > 0:
                    r = first_hit(D, k, H[D["name"]], up_lv=hi + a, dn_lv=lo - 0.5 * a)
                    return r == "up", rw(c[k], hi + a, lo - 0.5 * a, True)
                r = first_hit(D, k, H[D["name"]], up_lv=hi + 0.5 * a, dn_lv=lo - a)
                return r == "dn", rw(c[k], hi + 0.5 * a, lo - a, False)
        return None
    for t, lo, hi, s in real:
        y = touch(t, lo, hi, s)
        if y is not None:
            out.append({"t": t, "g": "A", "y": bool(y[0]), "p": y[1]})
    for t, lo, hi, s in real:                         # 對照：同一邊、距離和寬度從真的密集區分布抽
        dd, w = dists[RNG.integers(len(dists))]
        mid = c[t] - s * dd
        y = touch(t, mid - w / 2, mid + w / 2, s)
        if y is not None:
            out.append({"t": t, "g": "B", "y": bool(y[0]), "p": y[1]})
    return out


# ── 統計 ─────────────────────────────────────────────────────────────────────
def summarize(D, evs, periods):
    A = [e for e in evs if e["g"] == "A"]
    B = [e for e in evs if e["g"] == "B"]
    ra = float(np.mean([e["y"] for e in A])) if A else None
    rb = float(np.mean([e["y"] for e in B])) if B else None
    pa = float(np.mean([e["p"] for e in A])) if A else None
    pb = float(np.mean([e["p"] for e in B])) if B else None
    r4 = lambda x: None if x is None else round(x, 4)   # noqa: E731
    res = {"nA": len(A), "nB": len(B), "rateA": r4(ra), "rateB": r4(rb), "rwA": r4(pa), "rwB": r4(pb)}
    if ra is None or rb is None:
        res.update(diff=None, raw_diff=None, p=None, sub=[])
        return res
    diff = (ra - pa) - (rb - pb)                       # 扣掉隨機漫步（距離）後的差距
    years = D["years"]
    yr = np.array([years[e["t"]] for e in evs])
    gs = np.array([e["g"] == "A" for e in evs])
    ys = np.array([e["y"] - e["p"] for e in evs], float)
    cnt = 0
    for _ in range(N_PERM):
        g2 = gs.copy()
        for y in np.unique(yr):
            m = np.where(yr == y)[0]
            g2[m] = RNG.permutation(g2[m])
        if g2.sum() == 0 or (~g2).sum() == 0:
            continue
        dperm = ys[g2].mean() - ys[~g2].mean()
        if abs(dperm) >= abs(diff) - 1e-12:
            cnt += 1
    sub = []
    for lo, hi in periods:
        m = [(e, years[e["t"]]) for e in evs]
        a = [e["y"] - e["p"] for e, y in m if e["g"] == "A" and lo <= str(y) <= hi]
        b = [e["y"] - e["p"] for e, y in m if e["g"] == "B" and lo <= str(y) <= hi]
        sub.append({"period": f"{lo}–{hi}", "nA": len(a), "nB": len(b),
                    "diff": None if not a or not b else round(float(np.mean(a) - np.mean(b)), 4)})
    res.update(diff=round(diff, 4), raw_diff=round(ra - rb, 4), p=round((cnt + 1) / (N_PERM + 1), 4), sub=sub)
    return res


def bh(ps: dict) -> dict:
    items = sorted([(p, k) for k, p in ps.items() if p is not None])
    m = len(items)
    out = {}
    prev = 1.0
    for rank in range(m, 0, -1):
        p, k = items[rank - 1]
        prev = min(prev, p * m / rank)
        out[k] = round(prev, 4)
    return out


TEXT = {"V1": "帶量（≥1.3 倍）突破前一個轉折高低點 vs 沒量（<1.0 倍）→ 之後先多走 1 ATR 的比例",
        "V2": "已過前高時「漲幅縮小、量沒放大、動能背離」≥2 項 vs 都沒有 → 之後先回吐這段 50% 的比例",
        "V2b": "過前高後第 3 根收回前高以下（站不住）vs 站住 → 之後先回吐這段 50% 的比例",
        "V3": "修正「空間 ≥0.382、時間 ≥0.8 倍」vs「空間夠但時間 <0.5 倍」→ 之後先順原方向走 1 ATR 的比例",
        "V4": "修正量縮（≤0.85 倍）vs 帶量（≥1.15 倍）→ 之後先順原方向走 1 ATR 的比例",
        "V5": "成交密集區 vs 同距離隨機價位帶 → 碰到後先反彈 1 ATR 的比例"}


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    sets = {}
    for loader in (load_d1, load_d2, load_d3):
        try:
            D = prep(loader())
            sets[D["name"]] = D
            print(D["name"], "bars", len(D["c"]), "with vol", D["n_vol"], "pivots", len(D["piv"]), flush=True)
        except Exception as e:     # noqa: BLE001
            print("load fail", loader.__name__, repr(e), flush=True)
    res = {}
    for nm, D in sets.items():
        if nm == "D2":
            ud = sorted(set(D["dates"]))
            cut = ud[len(ud) // 2]
            D["years"] = np.array([0 if d < cut else 1 for d in D["dates"]])      # D2 用前後半當「時期」（置換也在半段內打亂）
            periods = (("0", "0"), ("1", "1"))
            look = 260
        elif nm == "D1":
            periods = PERIODS_D1
            look = 120
        else:
            D["years"] = np.zeros(len(D["c"]), int)
            periods = (("0", "0"),)
            look = 260
        pe = _push_events(D)
        cp = _corr_points(D)
        evs = {"V1": ev_v1(D), "V2": ev_v2(D, pe), "V2b": ev_v2b(D, pe), "V3": ev_v3(D, cp), "V4": ev_v4(D, cp), "V5": ev_v5(D, look)}
        res[nm] = {k: summarize(D, v, periods) for k, v in evs.items()}
        print(nm, {k: (x["nA"], x["nB"], x["rateA"], x["rateB"], x.get("rwA"), x.get("rwB"), x["diff"], x["p"]) for k, x in res[nm].items()}, flush=True)
    ps = {f"{nm}:{k}": x["p"] for nm in ("D1", "D2") if nm in res for k, x in res[nm].items()}
    q = bh(ps)
    tests = {}
    for k in TEXT:
        row = {"text": TEXT[k]}
        for nm in ("D1", "D2"):
            x = (res.get(nm) or {}).get(k)
            if not x:
                continue
            qv = q.get(f"{nm}:{k}")
            subs = [s["diff"] for s in x["sub"] if s["diff"] is not None]
            same = bool(subs) and len(subs) == len(x["sub"]) and all(s > 0 for s in subs)
            ok = (x["diff"] is not None and x["diff"] >= MIN_DIFF and x["nA"] >= MIN_N and x["nB"] >= MIN_N
                  and qv is not None and qv < 0.05 and same)
            x.update(q=qv, same_sign=same, pass_=ok)
            row[nm.lower()] = x
            row[f"pass_{nm.lower()}"] = ok
        def tag(nm):
            x = row.get(nm.lower())
            if not x or x["rateA"] is None:
                return f"{'日 K' if nm == 'D1' else '60 分'} 樣本不夠"
            return (f"{'日 K' if nm == 'D1' else '60 分'} {x['rateA'] * 100:.0f}% vs {x['rateB'] * 100:.0f}%"
                    f"（隨機走勢 {x['rwA'] * 100:.0f}% vs {x['rwB'] * 100:.0f}%；{x['nA']}／{x['nB']} 筆）{'✅' if x.get('pass_') else '△'}")
        row["text"] = TEXT[k] + "：" + "；".join(tag(nm) for nm in ("D1", "D2"))
        tests[k] = row
    if "D3" in res:
        for k in TEXT:
            x = res["D3"].get(k) or {}
            tests[k]["d3"] = x
    out = {"generated": datetime.now(TW).strftime("%Y-%m-%d %H:%M"), "tests": tests,
           "data": {nm: {"bars": len(D["c"]), "with_vol": D["n_vol"], "from": D["dates"][0], "to": D["dates"][-1]} for nm, D in sets.items()},
           "rule": "扣掉隨機漫步（距離）後差距 ≥8 個百分點、每組 ≥30 筆、置換檢定 BH <0.05、各時期方向一樣才算 ✅（門檻事先定好）"}
    with open(os.path.join(OUT, "vol.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(json.dumps({k: (v.get("pass_d1"), v.get("pass_d2"), v["text"]) for k, v in tests.items()}, ensure_ascii=False, indent=1))
    # REPORT.md
    L = ["# B80 量能規則回測（research/b80/run_vol.py）", "",
         f"產生時間：{out['generated']}；規則：{out['rule']}", "",
         "比的是「實際比例 − 隨機漫步理論比例」：每筆事件依現價離成功、失敗兩邊的距離算隨機走勢先碰到成功那邊的機率，"
         "扣掉之後 A 組比 B 組好多少（不扣的話，例如「突破後站不住」那組本來就離回吐 50% 比較近，會看起來很準）。", "",
         "| 資料 | K 棒 | 有量 | 期間 |", "|---|---|---|---|"]
    for nm, x in out["data"].items():
        L.append(f"| {nm} | {x['bars']} | {x['with_vol']} | {x['from']}～{x['to']} |")
    L += ["", "| 檢定 | 資料 | A 筆數 | B 筆數 | A 實際 | A 隨機 | B 實際 | B 隨機 | 扣掉後差距 | p | BH q | 各時期 | 結果 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    pc = lambda v: "—" if v is None else f"{v * 100:.1f}%"   # noqa: E731
    for k in TEXT:
        for nm in ("d1", "d2", "d3"):
            x = tests[k].get(nm)
            if not x:
                continue
            subs = "、".join("—" if s["diff"] is None else f"{s['diff'] * 100:+.0f}" for s in x.get("sub") or [])
            res_ = "只報告" if nm == "d3" else ("✅" if x.get("pass_") else "△")
            L.append(f"| {k} | {nm.upper()} | {x['nA']} | {x['nB']} | {pc(x['rateA'])} | {pc(x.get('rwA'))} | {pc(x['rateB'])} | {pc(x.get('rwB'))} | "
                     f"{'—' if x.get('diff') is None else format(x['diff'] * 100, '+.1f')} | {x.get('p') if x.get('p') is not None else '—'} | "
                     f"{x.get('q') if x.get('q') is not None else '—'} | {subs} | {res_} |")
    L += ["", "## 各檢定在測什麼"] + [f"- {k}：{v}" for k, v in TEXT.items()]
    with open(os.path.join(HERE, "REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
