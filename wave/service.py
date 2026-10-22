"""B74 大盤解析快照（PLAN-B74 §4、§7）：引擎＋支撐壓力＋籌碼＋國際＋預判＋既有研究訊號 → 一份 JSON。
- 轉折只用收完的日 K；盤中即時價只當現價（算距離、判斷在支撐還是壓力那邊），並檢查「可能轉折」
- 研究結果讀 wave/stats.json（research/wave/run.py 產生）；沒通過的一律標 △
- 預測區間＝全部歷史分布（R6：相似狀態沒有比較準 → 只當參考）
B75：sym＝TWII（加權）／TX（台指期近月、全盤含夜盤）分開算、分開快取；超短線（60 分 K）、轉折點、期貨＋籌碼綜合研判、融資增減"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from typing import Optional

import numpy as np
import pandas as pd

from . import advice as AD, composite as CP, data as D, engine as E, features as F, forecast as FC, futdata as FD, nest as NE, \
    intraday as I, keylevel as KL, levels as LV
from .plain import plain

log = logging.getLogger(__name__)
STATS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.json")
INTRADAY_TTL = 120
SYMS = ("TWII", "TX")
SYM_NAME = {"TWII": "加權指數", "TX": "台指期（近月，含夜盤）"}
_cache: dict = {s: {"t": 0.0, "data": None, "session": None} for s in SYMS}
_locks = {s: threading.Lock() for s in SYMS}
_stats = {"mtime": None, "data": {}}
DISCLAIMER = "劇本＝規則數浪＋歷史條件推估，不是投資建議"
CHIP_FACTORS = {   # 欄位 → (名稱, 高的意思, 低的意思)
    "f5_z": ("外資現貨 5 日", "外資買超（偏多方）", "外資賣超（偏空方）"),
    "fut_pct": ("外資台指期淨部位水位", "期貨淨多水位高（偏多方）", "期貨淨空水位高（偏空方）"),
    "fut_chg5": ("外資期貨 5 日變化", "期貨多單增加（偏多方）", "期貨空單增加（偏空方）"),
    "margin_chg20": ("融資 20 日變化", "融資增加（散戶加碼）", "融資減少（籌碼較乾淨）"),
}
GLOBAL_SYMS = ("SOX", "IXIC", "GSPC", "N225", "KS11")
US_SYMS = {"SOX", "IXIC", "GSPC"}


def stats() -> dict:
    try:
        mt = os.path.getmtime(STATS_PATH)
        if _stats["mtime"] != mt:
            with open(STATS_PATH, encoding="utf-8") as fh:
                _stats["data"] = json.load(fh)
            _stats["mtime"] = mt
    except Exception as e:     # noqa: BLE001
        log.warning(f"[wave] 讀 stats.json 失敗：{e}")
    return _stats["data"] or {}


def _f(x, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(x) else round(x, nd)


def _pct(a, b):
    return None if a is None or b in (None, 0) else _f((a / b - 1) * 100, 2)


def _with_dates(obj, dates):
    """引擎輸出的 i → 日期"""
    if obj is None:
        return None
    o = dict(obj)
    if "labels" in o:
        o["labels"] = [{**x, "date": str(dates[x["i"]])} for x in o["labels"]]
    return o


def _pts(lst, dates):
    return [{"date": str(dates[p["i"]]), "p": _f(p["p"]), "t": p["t"],
             "confirmed": None if p.get("ci") is None else str(dates[p["ci"]])} for p in lst]


def weekly(df: pd.DataFrame, n: int = 260) -> list:
    if df.empty:
        return []
    d = df.copy()
    d["dt"] = pd.to_datetime(d["date"])
    d["wk"] = d["dt"].dt.strftime("%G-%V")
    g = d.groupby("wk", sort=False).agg(date=("date", "last"), o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"))
    return [{"time": r.date, "open": _f(r.o), "high": _f(r.h), "low": _f(r.l), "close": _f(r.c)} for r in g.tail(n).itertuples()]


def _trend(c, t):
    if t + 1 < 240:
        return 0
    m = float(np.mean(c[t - 239:t + 1]))
    return 1 if c[t] > m else -1


def maybe_pivot(an: dict, live: Optional[dict], h, l, c, deg: str) -> Optional[str]:
    """盤中即時 K 棒若已經從進行中的極值反向走 θ → 「可能轉折，收盤後確認」"""
    if not live or not an or not an.get("tentative"):
        return None
    th = float(E.thresholds(h, l, c, deg)[-1])
    tent = an["tentative"]
    if tent["t"] == "H" and live["l"] <= tent["p"] * (1 - th):
        return f"盤中已從高點 {tent['p']:,.0f} 回落 {th:.0%} 以上：可能轉折，收盤後確認"
    if tent["t"] == "L" and live["h"] >= tent["p"] * (1 + th):
        return f"盤中已從低點 {tent['p']:,.0f} 反彈 {th:.0%} 以上：可能轉折，收盤後確認"
    if tent["t"] == "H" and live["h"] > tent["p"]:
        return f"盤中創新高 {live['h']:,.0f}（進行中這段延伸）"
    if tent["t"] == "L" and live["l"] < tent["p"]:
        return f"盤中創新低 {live['l']:,.0f}（進行中這段延伸）"
    return None


def _scenario(an: dict, lv: dict, price: float, fc: dict) -> dict:
    out = {"lines": []}
    mid, small = an.get("mid") or {}, an.get("small") or {}
    p, a = mid.get("primary"), mid.get("alternate")

    def tg(x):
        ends = [t for t in (x or {}).get("targets", []) if t["kind"] == "end"]
        return "、".join(f"{t['price']:,.0f}（{t['label']}）" for t in ends[:3])

    def inv(x):
        if not x or x.get("invalid") is None:
            return ""
        return f"{'跌破' if x['invalid_side'] == 'below' else '漲過'} {x['invalid']:,.0f} 這個劇本失效"
    if p:
        s = f"主要劇本（中級）：{p['text']}"
        if tg(p):
            s += f"；這一浪目標 {tg(p)}"
        if inv(p):
            s += f"；{inv(p)}"
        out["lines"].append(s)
        out["primary"] = p["text"]
        out["invalid"] = p.get("invalid")
        out["invalid_side"] = p.get("invalid_side")
    else:
        out["lines"].append("中級：結構不清楚，無法數浪（只看費波那契與支撐壓力）")
    if a:
        s = f"替代劇本：{a['text']}"
        if tg(a):
            s += f"；目標 {tg(a)}"
        if inv(a):
            s += f"；{inv(a)}"
        out["lines"].append(s)
        out["alternate"] = a["text"]
    sp = small.get("primary")
    sh = lv.get("short") or {}
    sup = (sh.get("support") or [None])[0]
    res = (sh.get("resistance") or [None])[0]
    s = "短線（小級）：" + (sp["text"] if sp else "結構不清楚")
    if sup:
        s += f"；最近支撐 {sup['price']:,.0f}"
    if res:
        s += f"、壓力 {res['price']:,.0f}"
    out["lines"].append(s)
    h20 = (fc or {}).get("h20") or {}
    if h20.get("p_up") is not None:
        out["lines"].append(f"歷史上任一天之後 20 個交易日：上漲 {h20['p_up'] * 100:.0f}%，"
                            f"八成落在 {h20['lo_px']:,.0f}～{h20['hi_px']:,.0f}（全部歷史分布，不是預測方向）")
    out["lines"].append(DISCLAIMER)
    return out


def _chips(feat: pd.DataFrame, st: dict) -> dict:
    if "f_net" not in feat:
        return {"ok": False, "note": "籌碼資料暫缺"}
    have = feat[feat[[k for k in ("f_net", "fut_f_oi", "margin_amt") if k in feat]].notna().any(axis=1)]
    if have.empty:
        return {"ok": False, "note": "籌碼資料暫缺"}
    r = have.iloc[-1]
    i = have.index[-1]
    t5 = feat["t_net"].iloc[max(0, i - 4):i + 1].sum(min_count=1) if "t_net" in feat else None
    out = {"ok": True, "date": r["date"],
           "f_net": _f(r.get("f_net")), "f5": _f(r.get("f5")), "f20": _f(r.get("f20")),
           "f_streak": int(r.get("f_streak") or 0) if "f_streak" in feat else 0,
           "t_net": _f(r.get("t_net")), "t5": _f(t5), "d_net": _f(r.get("d_net")),
           "fut_f_oi": _f(r.get("fut_f_oi"), 0), "fut_chg5": _f(r.get("fut_chg5"), 0), "fut_pct": _f(r.get("fut_pct"), 3),
           "margin_amt": _f(r.get("margin_amt"), 1), "margin_chg20": _f(r.get("margin_chg20"), 4), "factors": []}
    sc = st.get("chips") or {}
    for k, (name, hi, lo) in CHIP_FACTORS.items():
        v = r.get(k)
        ed = (sc.get(k) or {}).get("edges")
        state = None
        if v is not None and not (isinstance(v, float) and math.isnan(v)) and ed and None not in ed:
            state = hi if v > ed[1] else lo if v <= ed[0] else "中性"
        res = sc.get(k) or {}
        out["factors"].append({"key": k, "name": name, "value": _f(v, 4), "state": state,
                               "pass": bool((res.get("h20") or {}).get("pass")),
                               "oos_diff20": (res.get("h20") or {}).get("oos_diff")})
    return out


def _global(tw: pd.DataFrame, st: dict, frames: dict) -> dict:
    out = {"items": []}
    tw_ret = tw.set_index("date")["c"].pct_change()
    for s in GLOBAL_SYMS:
        df = frames.get(s)
        if df is None or df.empty or len(df) < 61:
            out["items"].append({"sym": s, "name": D.SYM_NAME[s], "ok": False})
            continue
        c = df["c"].values.astype(float)
        last = len(c) - 1
        ma60 = float(np.mean(c[-60:]))
        hi52 = float(np.max(c[-252:]))
        o_ret = df.set_index("date")["c"].pct_change()
        # 美股：台股當天對前一晚；日韓：同一天
        if s in US_SYMS:
            al = F.align_prev(pd.Series(tw_ret.index), o_ret.reset_index().rename(columns={"c": "r"}), "r")
        else:
            al = pd.Series(o_ret.reindex(tw_ret.index).values)
        x = pd.Series(tw_ret.values).tail(60).reset_index(drop=True)
        y = pd.Series(al.values).tail(60).reset_index(drop=True)
        corr = x.corr(y) if len(y) >= 60 else None
        tw20 = _pct(float(tw.c.iloc[-1]), float(tw.c.iloc[-21])) if len(tw) > 21 else None
        o20 = _pct(c[-1], c[-21])
        out["items"].append({"sym": s, "name": D.SYM_NAME[s], "ok": True, "date": str(df.date.iloc[-1]), "close": _f(c[-1]),
                             "chg1": _pct(c[-1], c[-2]), "chg5": _pct(c[-1], c[-6]), "chg20": o20,
                             "above_ma60": bool(c[-1] > ma60), "dd52": _pct(c[-1], hi52),
                             "corr60": _f(corr, 2), "rs20": None if tw20 is None or o20 is None else _f(tw20 - o20, 2)})
    # 費半：同一套中級數浪＋支撐壓力
    sox = frames.get("SOX")
    if sox is not None and len(sox) > 300:
        h, l, c = sox.h.values, sox.l.values, sox.c.values
        t = len(c) - 1
        an = {deg: E.analyze(sox.o.values, h, l, c, deg, trend=_trend(c, t)) for deg in ("small", "mid", "big")}
        lv = LV.build(h, l, c, t, an, float(E.atr(h, l, c)[-1]), dates=sox.date.values)
        p = an["mid"].get("primary")
        sw = lv.get("swing") or {}
        out["sox_wave"] = {"text": p["text"] if p else "結構不清楚", "invalid": p.get("invalid") if p else None,
                           "invalid_side": p.get("invalid_side") if p else None,
                           "support": [z["price"] for z in sw.get("support", [])][:2],
                           "resistance": [z["price"] for z in sw.get("resistance", [])][:2]}
        r1 = (c[-1] / c[-2] - 1) if len(c) > 1 else None
        sb = (st.get("global") or {}).get("sox_beta") or {}
        if r1 is not None and sb.get("beta") is not None:
            out["sox_overnight"] = {"date": str(sox.date.iloc[-1]), "sox_ret": _f(r1 * 100, 2),
                                    "tw_expect": _f((sb.get("alpha", 0) + sb["beta"] * r1) * 100, 2),
                                    "sd": _f((sb.get("resid_sd") or 0) * 100, 2), "beta": sb["beta"],
                                    "oos_r2": sb.get("oos_r2_with_is_beta"),
                                    "corr": (st.get("global") or {}).get("sox_overnight_corr")}
    return out


def _forecast(feat: pd.DataFrame, price: float, st: dict) -> dict:
    out = {}
    t = len(feat) - 1
    for hz in (5, 20, 60):
        y = feat[f"fwd{hz}"].dropna().values
        y = y[260:] if len(y) > 400 else y
        if len(y) < 100:
            continue
        k = int((y > 0).sum())
        q20, q50, q80 = np.quantile(y, [0.2, 0.5, 0.8])
        out[f"h{hz}"] = {"n": int(len(y)), "p_up": _f(k / len(y), 4), "ci": FC.wilson(k, len(y)),
                         "median": _f(q50, 5), "q20": _f(q20, 5), "q80": _f(q80, 5),
                         "lo_px": _f(price * (1 + q20), 0), "mid_px": _f(price * (1 + q50), 0), "hi_px": _f(price * (1 + q80), 0)}
    an = st.get("analog") or {}
    conds = an.get("conds") or ["above_ma60", "dd_b"]
    ref = {}
    for hz in (5, 20):
        a = FC.analog(feat, t, conds, horizon=hz, start=260)
        if a.get("n"):
            a["lo_px"] = _f(price * (1 + a["q20"]), 0)
            a["hi_px"] = _f(price * (1 + a["q80"]), 0)
        a["pass"] = bool((an.get(f"h{hz}") or {}).get("pass"))
        a["improve"] = (an.get(f"h{hz}") or {}).get("improve")
        ref[f"h{hz}"] = a
    out["analog"] = ref
    return out


def _context(tw: pd.DataFrame) -> dict:
    out = {}
    c = tw["c"].values.astype(float)
    try:
        from deep_patterns import trend_box, mslope_info
        if len(c) >= 100:
            out["box"] = trend_box(c[-1], float(np.mean(c[-20:])), float(np.mean(c[-100:])))
        ms = mslope_info(list(c[-60:]))
        if ms:
            out["mslope"] = {"slope": ms["slope"], "tier": ms.get("tier"), "streak": ms.get("streak")}
    except Exception as e:     # noqa: BLE001
        log.debug(f"[wave] 格局／斜率：{e}")
    try:
        import crash_routes
        cs = crash_routes.today_state()
        if not cs.get("error"):
            out["crash"] = {"dd": cs.get("dd"), "bias": cs.get("bias"), "deep": [k for k, v in (cs.get("deep") or {}).items() if v],
                            "hi60": cs.get("hi60"), "ma60": cs.get("ma60")}
    except Exception as e:     # noqa: BLE001
        log.debug(f"[wave] 大跌買點：{e}")
    try:
        import course_live
        mk = course_live.latest("market")
        if mk:
            out["dist_day"] = {"date": mk.get("date"), "dist_day": mk.get("dist_day"), "recent": (mk.get("recent_dist") or [])[-3:]}
    except Exception as e:     # noqa: BLE001
        log.debug(f"[wave] 出貨日：{e}")
    try:
        from regime.db import db as rdb
        with rdb() as conn:
            oh = {}
            for ser, k in (("OVERHEATING_INDEX", "overheating"), ("PANIC_INDEX", "panic")):
                x = conn.execute("SELECT date, value FROM market_daily WHERE series=? AND value IS NOT NULL ORDER BY date DESC LIMIT 1",
                                 (ser,)).fetchone()
                if x:
                    oh[k], oh["date"] = float(x["value"]), str(x["date"])
            if oh:
                out["oh"] = oh               # B76：操作建議用（總經面板的過熱／恐慌）
    except Exception as e:     # noqa: BLE001
        log.debug(f"[wave] 過熱恐慌：{e}")
    try:
        from regime.db import db as rdb
        with rdb() as conn:
            r = conn.execute("SELECT date, regime_label, direction, risk_score FROM factors ORDER BY date DESC LIMIT 1").fetchone()
        if r:
            from regime.factor import tw_label
            out["regime"] = {"date": r["date"], "label": tw_label(r["regime_label"]), "direction": r["direction"], "risk": r["risk_score"]}
    except Exception as e:     # noqa: BLE001
        log.debug(f"[wave] regime：{e}")
    return out


def _research(st: dict) -> dict:
    hold = st.get("hold") or {}
    fib = st.get("fib") or {}
    return {"generated": st.get("generated"), "data_end": st.get("data_end"), "n_tests": st.get("n_tests"),
            "hold": hold, "fib": fib, "wave_state": st.get("wave_state") or {}, "analog": st.get("analog") or {},
            "global": st.get("global") or {}, "coverage": st.get("coverage") or {},
            "summary": [
                "費波那契：加權的回檔比例沒有集中在 0.382／0.5／0.618；費波那契價位守住率跟普通比例差不多 △",
                "支撐壓力：前高前低、均線、整數、費波那契都沒有比隨機價位好到門檻；≥2 種來源重疊的區略好（+3 點）但沒過 △",
                "波浪狀態：每種浪別之後 5／20／60 天跟平常差不多 △",
                "籌碼（外資現貨、期貨、融資）：對之後 5／20 天加權沒有預測力 △",
                "國際：只有「前一晚費半 → 加權隔天」有效（樣本外 R² 約 0.2）✅",
                "過去相似狀態：比直接看全部歷史還略差 → 預測區間改用全部歷史 △",
            ] + _research_b75(st)}


def _research_b75(st: dict) -> list:
    fu = (st.get("futures") or {}).get("factors") or {}
    kl = (st.get("keylevel") or {}).get("modes") or {}
    out = []
    nx = (fu.get("night_ret") or {})
    if nx.get("open"):
        o, r = nx["open"], nx.get("next") or {}
        out.append(f"台指期夜盤 → 加權當天：開盤跳空樣本外 R² {o.get('oos_r2')}、全天 {r.get('oos_r2')}（2022 起 {o.get('years_same')} 年同方向）"
                   f"{'✅' if o.get('pass') else '△'}，比前一晚費半更準")
    bad = [CP.FACTORS[k][0] for k in ("fut_chg1", "opt_chg1", "retail_chg1", "f_net", "basis_z", "basis_d5", "opt_z", "retail", "margin_chg5")
           if k in fu and not any((v or {}).get("pass") for v in fu[k].values())]
    if bad:
        out.append("期貨籌碼（" + "、".join(bad) + "）：對隔天（扣掉夜盤之後）、1～2 週、1～3 個月都沒有預測力 △")
    if kl:
        out.append("轉折點：三個模式都用「最近的反向小轉折」（波浪失效點太遠）；跌破後會不會繼續走，回測跟隨便畫線差不多 △，當停損參考")
    return out


_base: dict = {s: {"key": None, "data": None} for s in SYMS}
KEY_LOOK = {"short": 60, "swing": 120}
MODE_DEG = {"short": "small", "swing": "mid"}


def wave_states(h, l, c, deg: str = "mid", start: int = 260) -> list:
    """每一天中級主要劇本的浪別（研究 R3／R6 的 wstate，同一套寫法）"""
    piv = E.zigzag(h, l, E.thresholds(h, l, c, deg))
    out = [None] * len(c)
    for t in range(start, len(c)):
        conf, tent = E.state_at(piv, h, l, t)
        p, _ = E.primary_alternate(E.count_waves(conf + ([tent] if tent else []), trend=_trend(c, t)))
        if p:
            out[t] = f"{p['kind'][:3]}{'+' if p['dir'] > 0 else '-'}:{p['current']}"
    return out


def _daily(sym: str) -> pd.DataFrame:
    if sym == "TX":
        fb = FD.full_bars(FD.load_fut_daily())
        return fb[["date", "o", "h", "l", "c", "v"]] if not fb.empty else fb
    return D.load_idx("TWII")


def base(sym: str = "TWII") -> dict:
    """只跟「收完的資料」有關的部分；最新日期、籌碼、國外指數或研究檔沒變就不重算（盤中只重算現價相關）"""
    st = stats()
    I.set_params(st)
    tw = _daily(sym)
    if tw.empty or len(tw) < 300:
        return {"ok": False, "error": ("台指期" if sym == "TX" else "加權") + "歷史資料還在下載（第一次約 1～3 分鐘），請稍後重新整理"}
    twii = tw if sym == "TWII" else D.load_idx("TWII")
    frames = {s: D.load_idx(s) for s in GLOBAL_SYMS}
    chips = D.load_chips()
    fchips = FD.load_fut_chips()
    fd = FD.load_fut_daily()
    key = (sym, str(tw.date.iloc[-1]), len(tw), float(tw.c.iloc[-1]), None if chips.empty else str(chips.date.iloc[-1]),
           None if fchips.empty else str(fchips.date.iloc[-1]), None if fd.empty else (str(fd.date.iloc[-1]), len(fd)),
           None if twii.empty else str(twii.date.iloc[-1]),
           tuple(None if frames[s].empty else str(frames[s].date.iloc[-1]) for s in GLOBAL_SYMS), _stats["mtime"])
    if _base[sym]["key"] == key and _base[sym]["data"] is not None:
        return _base[sym]["data"]
    dates = tw.date.values.astype(str)
    o, h, l, c = (tw[k].values.astype(float) for k in ("o", "h", "l", "c"))
    t = len(c) - 1
    trend = _trend(c, t)
    an = {deg: E.analyze(o, h, l, c, deg, trend=trend) for deg in ("small", "mid", "big")}
    feat = F.build(tw, chips if not chips.empty else None, frames.get("SOX"))
    if "wstate" in ((st.get("analog") or {}).get("conds") or []):
        feat["wstate"] = wave_states(h, l, c)
    waves = {}
    for deg, a in an.items():
        f = a["fib"]
        waves[deg] = {"label": a["label"], "pivots": _pts(a["pivots"][-14:], dates),
                      "tentative": _pts([a["tentative"]], dates)[0] if a["tentative"] else None,
                      "primary": _with_dates(a["primary"], dates), "alternate": _with_dates(a["alternate"], dates),
                      "fib": None if not f else {**f, "from": {**f["from"], "date": str(dates[f["from"]["i"]])},
                                                 "to": {**f["to"], "date": str(dates[f["to"]["i"]])}}}
    comp = CP.build(twii, fd if not fd.empty else None, chips if not chips.empty else None,
                    fchips if not fchips.empty else None, frames.get("SOX"))
    b = {"ok": True, "sym": sym, "st": st, "tw": tw, "dates": dates, "o": o, "h": h, "l": l, "c": c, "an": an, "feat": feat,
         "atr": float(E.atr(h, l, c)[-1]), "trend": trend, "waves": waves, "weekly": weekly(tw),
         "chips": _chips(feat, st), "global": _global(tw, st, frames), "context": _context(twii), "research": _research(st),
         "comp": comp, "chips_df": chips, "fchips": fchips, "fd": fd,
         "twii_last": None if twii.empty else {"date": str(twii.date.iloc[-1]), "c": float(twii.c.iloc[-1])}}
    _base[sym].update(key=key, data=b)
    return b


# ── 轉折點 ───────────────────────────────────────────────────────────────────
def _key_rule(st: dict, mode: str) -> tuple:
    m = ((st.get("keylevel") or {}).get("modes") or {}).get(mode) or {}
    return m.get("rule") or "K3", bool(m.get("sig"))


def _key_out(cands: dict, mode: str, price: float, atr_v: float, st: dict) -> Optional[dict]:
    rule, sig = _key_rule(st, mode)
    k = KL.pick(cands, rule, price, atr_v)
    if not k:
        return None
    k["sig"] = sig
    k["broken"] = bool((k["side"] == "below" and price < k["price"]) or (k["side"] == "above" and price > k["price"]))
    return k


# ── 夜盤 → 開盤參考 ──────────────────────────────────────────────────────────
def _night_info(b: dict, now=None) -> Optional[dict]:
    """台指期夜盤報酬：夜盤進行中或 05:05～08:45 → 鉅亨即時（價／參考價）；其他時間 → fut_daily 最新一筆夜盤（同月份基準）"""
    now = now or D.tw_now()
    hm = (now.hour, now.minute)
    night_live = FD.in_session("TX", now) and not ((8, 45) <= hm <= (13, 50))
    pre_open = now.weekday() < 5 and (5, 5) < hm < (8, 45)
    if night_live or pre_open:
        try:
            q = FD.fetch_cnyes_quote("TX")
            if q and q.get("ref"):
                return {"ret": q["price"] / q["ref"] - 1, "price": q["price"], "ref": q["ref"], "live": night_live,
                        "src": "鉅亨即時", "time": FD.tw_dt(q["ts"]).strftime("%H:%M") if q.get("ts") else ""}
        except Exception as e:     # noqa: BLE001
            log.info(f"[wave] 夜盤即時：{e}")
    fd = b.get("fd")
    if fd is None or fd.empty:
        return None
    n = fd[(fd.sess == "night") & fd.ref_close.notna()]
    if n.empty:
        return None
    r = n.iloc[-1]
    return {"ret": float(r.c / r.ref_close - 1), "price": float(r.c), "ref": float(r.ref_close), "live": False,
            "src": "期交所（FinMind）", "date": str(r.date), "h": float(r.h), "l": float(r.l)}


def _open_ref(b: dict, st: dict, night: Optional[dict]) -> Optional[dict]:
    fu = ((st.get("futures") or {}).get("factors") or {}).get("night_ret") or {}
    go, gr = fu.get("open") or {}, fu.get("next") or {}
    if not night or not go.get("pass") or go.get("beta") is None:
        return None
    x = night["ret"]
    return {"night_ret": _f(x * 100, 2), "gap": _f((go.get("alpha", 0) + go["beta"] * x) * 100, 2),
            "gap_sd": _f((go.get("resid_sd") or 0) * 100, 2),
            "r1": _f((gr.get("alpha", 0) + gr.get("beta", 0) * x) * 100, 2) if gr.get("beta") is not None else None,
            "r1_sd": _f((gr.get("resid_sd") or 0) * 100, 2), "oos_r2": go.get("oos_r2"), "live": night.get("live"),
            "src": night.get("src"), "date": night.get("date"), "time": night.get("time"), "price": _f(night.get("price"), 0)}


# ── 綜合研判 ─────────────────────────────────────────────────────────────────
def _latest(comp: pd.DataFrame, col: str):
    if comp is None or col not in comp:
        return None, None
    s = comp[["date", col]].dropna()
    return (None, None) if s.empty else (float(s[col].iloc[-1]), str(s["date"].iloc[-1]))


def _composite(b: dict, st: dict, night: Optional[dict]) -> dict:
    fu = ((st.get("futures") or {}).get("factors") or {})
    comp = b["comp"]
    rows, by_h = [], {h: [] for h in CP.HORIZONS}
    for key, (name, kind, meaning, unit) in CP.FACTORS.items():
        res = fu.get(key) or {}
        so = (b.get("global") or {}).get("sox_overnight") or {}
        if key == "night_ret" and night:
            val, d = night["ret"], night.get("date") or "即時"
        elif key == "sox_ret1" and so.get("sox_ret") is not None:
            val, d = so["sox_ret"] / 100, so.get("date")     # 最新那一晚的費半（跟「國際」區塊同一個），不是表格最後一列對齊的
        else:
            val, d = _latest(comp, key)
        hz = ["next"] if kind in ("night", "a") else ["w2", "m3"]
        cells = {}
        for h in hz:
            r = res.get(h) or {}
            stt = CP.state_of(key, val, r) if r else None
            cells[h] = {"state": stt, "pass": bool(r.get("pass")), "q": r.get("q"),
                        "eff": r.get("oos_r2") if r.get("kind") == "reg" else r.get("oos_diff")}
            by_h[h].append((key, stt, bool(r.get("pass"))))
        rows.append({"key": key, "name": name, "meaning": meaning, "unit": unit, "value": _f(val, 6), "date": d, "cells": cells})
    dirs = {h: CP.direction(v) for h, v in by_h.items()}
    return {"rows": rows, "dir": dirs, "horizons": CP.HORIZONS,
            "research": {k: (st.get("futures") or {}).get(k) for k in ("is", "oos", "generated", "n_tests")}}


def _fut_chips_out(fc: pd.DataFrame) -> dict:
    if fc is None or fc.empty or "retail_ratio" not in fc:
        return {"ok": False}
    r = fc.dropna(subset=["retail_ratio"]).tail(6)
    if r.empty:
        return {"ok": False}
    last = r.iloc[-1]
    return {"ok": True, "date": str(last.date), "retail_ratio": _f(last.retail_ratio, 4), "mtx_oi": _f(last.mtx_oi, 0),
            "retail_chg1": _f(last.retail_ratio - r.iloc[-2].retail_ratio, 4) if len(r) > 1 else None,
            "opt_f_bull": _f(last.opt_f_bull, 0), "opt_chg1": _f(last.opt_f_bull - r.iloc[-2].opt_f_bull, 0) if len(r) > 1 else None}


def _session_label(sym: str, now) -> str:
    if not FD.in_session(sym, now):
        return "休市"
    if sym == "TWII":
        return "盤中"
    return "日盤" if (8, 45) <= (now.hour, now.minute) <= (13, 50) else "夜盤"


def _intraday(sym: str, b: dict, price: float, lv_c, live_rows: list, st: dict) -> dict:
    b60 = I.bars(sym, 60, live_rows)
    b30 = I.bars(sym, 30, live_rows)
    # 「昨天」＝最後一根收完的日 K（盤中＝昨天；收盤後＝今天，給下一盤用）
    daily = {"prev_h": float(b["h"][-1]), "prev_l": float(b["l"][-1]), "prev_c": float(b["c"][-1]),
             "ma20": float(np.mean(lv_c[-20:])) if len(lv_c) >= 20 else None}
    if sym == "TX":
        nb = [x for x in b60 if (FD.session_of("TX", x["time"]) or ("",))[0] == "night"]
        if nb:
            s0 = FD.session_of("TX", nb[-1]["time"])[1]
            cur = [x for x in nb if FD.session_of("TX", x["time"])[1] == s0]
            daily["night_h"] = max(x["high"] for x in cur)
            daily["night_l"] = min(x["low"] for x in cur)
    trend = 0 if daily["ma20"] is None else (1 if price > daily["ma20"] else -1)
    a = I.analyze(sym, b60, b30, price, daily, trend)
    out = {"tf60": b60[-I.SHOW[60]:], "tf30": b30[-I.SHOW[30]:], "ok": a.get("ok"), "note": a.get("note")}
    out["nest"] = {"60m": _nest(a, 60, price, b), "30m": _nest(a.get("m30") or {}, 30, price, b)}
    if a.get("ok"):
        out["wave"] = I.wave_out(a)
        out["levels"] = a["levels"]
        out["key"] = _key_out(a["cands"], "ultra", price, a["atr"], st)
        out["atr"] = _f(a["atr"], 0)
    m30 = a.get("m30") or {}
    out["m30"] = {"ok": bool(m30.get("ok")), "note": m30.get("note")}
    if m30.get("ok"):
        out["m30"].update(wave=I.wave_out(m30), levels=m30["levels"], key=_key_out(m30["cands"], "m30", price, m30["atr"], st),
                          atr=_f(m30["atr"], 0))
    return out


def _nest(a: dict, tf: int, price: float, b: dict) -> dict:
    """B79 多層浪名（學 @fanny55520）：分 K 轉折從「日 K 這一浪的起點」開始拆成 C-1-4-b 式浪名＋關卡＋操作紀律"""
    if not a.get("ok"):
        return {"ok": False, "note": a.get("note")}
    times = a["times"]
    tdate = lambda i: FD.tw_dt(times[i]).date()                       # noqa: E731
    tlabel = lambda i: FD.tw_dt(times[i]).strftime("%m/%d %H:%M")     # noqa: E731
    try:
        out = NE.build(a["an"], times, price, I.TF[tf]["tfn"], daily_cnt=(b["an"].get("small") or {}).get("primary"),
                       daily_dates=b["dates"], tdate=tdate, tlabel=tlabel)
    except Exception as e:     # noqa: BLE001
        log.exception(f"[wave] 多層浪名失敗 {tf}：{e}")
        return {"ok": False, "note": f"多層浪名計算失敗：{e}"}
    if out.get("ok") and a.get("piv") is not None:
        try:
            out["timeline"] = _nest_timeline(a, tf, b, tdate, tlabel)
        except Exception as e:     # noqa: BLE001
            log.warning(f"[wave] 浪名演變失敗 {tf}：{e}")
    return out


def _nest_timeline(a: dict, tf: int, b: dict, tdate, tlabel, n_days: int = 10) -> list:
    """B79 浪名演變：最近 n_days 天，每天最後一根分 K 當時（只用那時候以前的資料）系統怎麼數（她：注意貼文上下文的時間）"""
    import bisect
    times = a["times"]
    h, l, c = a["hlc"]
    days = [tdate(k) for k in range(len(times))]
    ends = [k for k in range(len(times)) if k == len(times) - 1 or days[k + 1] != days[k]][-n_days:]
    small = b["an"].get("small") or {}
    dpiv = small.get("pivots") or []
    ddates = [str(x)[:10] for x in b["dates"]]
    cache: dict = {}

    def daily_at(i):
        k = bisect.bisect_right(ddates, days[i].isoformat()) - 1      # 那天（含）以前最後一根日 K
        if k < 0:
            return None
        if k not in cache:
            conf, tent = E.state_at(dpiv, b["h"], b["l"], k)
            cache[k] = E.primary_alternate(E.count_waves(conf + ([tent] if tent else []), trend=_trend(b["c"], k)))[0]
        return cache[k]
    return NE.timeline(a["piv"], h, l, c, times, ends, I.TF[tf]["tfn"], daily_at, b["dates"], tdate, tlabel)


# ── B76 多週期一覽 ─────────────────────────────────────────────────────────
# 週期 → (waves 的鍵, key／levels 的鍵)。舊鍵：ultra＝60 分、short＝日 K、swing＝週 K（B75 名稱沿用，AI 圓桌與推播相容）
TF_KEYS = {"30m": ("intra30", "m30"), "60m": ("intra", "ultra"), "1d": ("small", "short"), "1wk": ("mid", "swing")}
TF_LABEL = {"30m": "30 分", "60m": "60 分", "1d": "日 K", "1wk": "週 K"}


def _ladder(waves: dict, key: dict, lv: dict) -> list:
    rows = []
    for tf, (wk, kk) in TF_KEYS.items():
        w, k, l_ = waves.get(wk) or {}, key.get(kk), lv.get(kk) or {}
        d = (k or {}).get("dir")
        if d not in (1, -1):
            tent = w.get("tentative")
            d = (1 if tent["t"] == "H" else -1) if tent else 0
        p = plain(w.get("primary"))
        s1 = (l_.get("support") or [None])[0]
        r1 = (l_.get("resistance") or [None])[0]
        rows.append({"tf": tf, "label": TF_LABEL[tf], "dir": d, "title": p["title"] if p else ("結構不清楚" if w else "資料不足"),
                     "key": None if not k else {x: k.get(x) for x in ("kind", "price", "side", "dist_pct", "broken")},
                     "s1": None if not s1 else {"price": s1["price"], "dist_pct": s1["dist_pct"]},
                     "r1": None if not r1 else {"price": r1["price"], "dist_pct": r1["dist_pct"]}})
    return rows


def compute(sym: str = "TWII", live: Optional[dict] = None, live_rows: Optional[list] = None) -> dict:
    b = base(sym)
    if not b.get("ok"):
        return b
    st, dates, o, h, l, c, an = b["st"], b["dates"], b["o"], b["h"], b["l"], b["c"], b["an"]
    t = len(c) - 1
    last_date = str(dates[-1])
    now = D.tw_now()
    use_live = bool(live and live.get("date") and live["date"] > last_date and live.get("c"))
    price = float(live["c"]) if use_live else float(c[-1])
    prev = float(c[-1]) if use_live else float(c[-2])
    # 轉折與數浪只用收完的 K 棒；盤中多接一根（只給均線、近期高低點、現價在哪一邊用）
    if use_live:
        lv_c = np.r_[c, price]
        lv_h = np.r_[h, max(price, live.get("h") or price)]
        lv_l = np.r_[l, min(price, live.get("l") or price)]
        lv_dates = np.append(dates, str(live["date"]))
    else:
        lv_c, lv_h, lv_l, lv_dates = c, h, l, dates
    lv = LV.build(lv_h, lv_l, lv_c, len(lv_c) - 1, an, b["atr"], dates=lv_dates, hold=st.get("hold") or {})
    fc = _forecast(b["feat"], price, st)
    waves = {deg: {**w, "maybe_pivot": maybe_pivot(an[deg], live if use_live else None, h, l, c, deg)}
             for deg, w in b["waves"].items()}
    bars = [{"time": str(dates[i]), "open": _f(o[i]), "high": _f(h[i]), "low": _f(l[i]), "close": _f(c[i])}
            for i in range(max(0, t - 299), t + 1)]
    if use_live:
        bars.append({"time": live["date"], "open": _f(live.get("o")), "high": _f(live.get("h")), "low": _f(live.get("l")),
                     "close": _f(price), "partial": True})
    mas = {}
    off = len(lv_c) - len(bars)
    for n in (20, 60, 240):
        s = pd.Series(lv_c).rolling(n).mean().values
        mas[str(n)] = [{"time": bar["time"], "value": _f(s[off + k])} for k, bar in enumerate(bars) if np.isfinite(s[off + k])]
    # 轉折點（日 K：短線＝小級、波段＝中級；轉折只用收完的 K 棒，現價用即時）
    key = {}
    for mode, deg in MODE_DEG.items():
        cands = KL.candidates(an[deg], h, l, c, t, b["atr"], price=price, k=3, look=KEY_LOOK[mode])
        key[mode] = _key_out(cands, mode, price, b["atr"], st)
    # 超短線（60 分 K）
    try:
        intra = _intraday(sym, b, price, lv_c, live_rows or [], st)
    except Exception as e:     # noqa: BLE001
        log.exception(f"[wave] 分 K 失敗 {sym}：{e}")
        intra = {"ok": False, "note": f"分 K 計算失敗：{e}", "tf60": [], "tf30": [], "m30": {"ok": False, "note": f"分 K 計算失敗：{e}"}}
    if intra.get("ok"):
        waves["intra"] = intra["wave"]
        lv["ultra"] = intra["levels"]
        key["ultra"] = intra["key"]
    else:
        lv["ultra"] = {"support": [], "resistance": [], "note": [intra.get("note") or "60 分 K 資料不足"]}
        key["ultra"] = None
    m30 = intra.get("m30") or {}
    if m30.get("ok"):
        waves["intra30"] = m30["wave"]
        lv["m30"] = m30["levels"]
        key["m30"] = m30["key"]
    else:
        lv["m30"] = {"support": [], "resistance": [], "note": [m30.get("note") or "30 分 K 資料不足"]}
        key["m30"] = None
    stale_reason = None
    if not use_live and FD.in_session(sym, now) and live is None:
        stale_reason = ("盤中即時加權抓不到" if sym == "TWII" else "台指期即時抓不到") + "，顯示最近收盤"
    if sym == "TWII" and now.weekday() < 5 and (now.hour, now.minute) >= (14, 30) and last_date < now.strftime("%Y-%m-%d"):
        stale_reason = f"今天收盤資料還沒進來（最新 {last_date}）"
    problems = [s for s in D.status() if (s.get("fails") or 0) >= 2]
    night = _night_info(b, now)
    snap = {
        "ok": True, "sym": sym, "name": SYM_NAME[sym], "generated": now.strftime("%Y-%m-%d %H:%M:%S"),
        "asof": {"date": last_date, "live": {"time": live.get("time"), "date": live["date"]} if use_live else None,
                 "stale": stale_reason is not None, "stale_reason": stale_reason, "session": _session_label(sym, now)},
        "price": _f(price), "prev_close": _f(prev), "chg": _f(price - prev), "chg_pct": _pct(price, prev),
        "atr": _f(b["atr"], 0), "trend240": b["trend"],
        "chart": {"bars": bars, "weekly": b["weekly"], "ma": mas, "i60": intra.get("tf60") or [], "i30": intra.get("tf30") or []},
        "nest": intra.get("nest") or {},
        "v": 76,
        "intra": {"ok": bool(intra.get("ok")), "note": intra.get("note"), "atr": intra.get("atr"), "m": E.INTRA["m"],
                  "m30": {"ok": bool(m30.get("ok")), "note": m30.get("note"), "atr": m30.get("atr"), "m": E.INTRA30["m"]}},
        "waves": waves, "levels": lv, "key": key, "forecast": fc,
        "chips": b["chips"], "global": b["global"], "context": b["context"], "research": b["research"],
        "fut_chips": _fut_chips_out(b["fchips"]), "margin": CP.margin_block(b["chips_df"], now.strftime("%Y-%m-%d")),
        "night": None if not night else {k: (_f(v * 100, 2) if k == "ret" else v) for k, v in night.items()},
        "open_ref": _open_ref(b, st, night),          # 夜盤 → 加權開盤參考（B76：台指期頁的操作建議也用）
        "composite": _composite(b, st, night),
        "problems": [{"src": p["src"], "fails": p["fails"], "last_ok": p["last_ok"]} for p in problems],
        "disclaimer": DISCLAIMER,
    }
    if sym == "TX":
        tw_px, tw_when = None, None
        if D.is_tw_session(now):
            lt = D.live_taiex()
            if lt and lt.get("c"):
                tw_px, tw_when = float(lt["c"]), f"加權盤中 {lt.get('time', '')}"
        if tw_px is None and b.get("twii_last"):
            tw_px, tw_when = b["twii_last"]["c"], f"加權 {b['twii_last']['date'][5:]} 收盤"
        if tw_px:
            snap["basis"] = {"pts": _f(price - tw_px, 0), "pct": _pct(price, tw_px), "twii": _f(tw_px), "when": tw_when,
                             "label": "正價差" if price > tw_px else "逆價差"}
    snap["scenario"] = _scenario(an, lv, price, fc)
    # B79 她的「日線定位」寫法（母尺、防守區、鐵律底線、威脅版本）
    snap["positioning"] = {tf: NE.positioning(waves.get(dg, {}).get("primary"), waves.get(dg, {}).get("alternate"), price, nm)
                           for tf, dg, nm in (("1d", "small", "日 K"), ("1wk", "mid", "週 K"))}
    snap["ladder"] = _ladder(waves, key, lv)
    snap["ladder_text"] = AD.ladder_summary(snap["ladder"])
    snap["advice"] = AD.build(snap)
    kind = ("live" if use_live else "close") if sym == "TWII" else f"TX:{'live' if use_live else 'close'}"
    try:
        with D.db() as conn:
            conn.execute("INSERT INTO wave_snapshot(day,kind,created_at,json) VALUES(?,?,?,?) "
                         "ON CONFLICT(day,kind) DO UPDATE SET created_at=excluded.created_at, json=excluded.json",
                         (live["date"] if use_live else last_date, kind, snap["generated"], json.dumps(snap, ensure_ascii=False)))
    except Exception as e:     # noqa: BLE001
        log.warning(f"[wave] 存快照失敗：{e}")
    return snap


def last_good(sym: str = "TWII") -> Optional[dict]:
    kinds = ("close", "live") if sym == "TWII" else ("TX:close", "TX:live")
    try:
        with D.db() as conn:
            r = conn.execute("SELECT json FROM wave_snapshot WHERE kind IN (?,?) ORDER BY day DESC, created_at DESC LIMIT 1",
                             kinds).fetchone()
        return json.loads(r["json"]) if r else None
    except Exception:     # noqa: BLE001
        return None


def _live_day(sym: str) -> Optional[dict]:
    if sym == "TWII":
        return D.live_taiex()
    x = FD.live_tx_day()
    if not x:
        return None
    return {"date": x["date"], "o": x["o"], "h": x["h"], "l": x["l"], "c": x["c"], "time": D.tw_now().strftime("%H:%M:%S")}


def snapshot(force: bool = False, sym: str = "TWII") -> dict:
    """盤中（依商品：加權 09:00～13:35、台指期日盤＋夜盤）超過 2 分鐘用即時價重算；盤後資料日期沒變就用快取。
    算失敗 → 上一次成功的快照（標過期）"""
    if sym not in SYMS:
        raise ValueError(sym)
    session = FD.in_session(sym)
    cc = _cache[sym]
    with _locks[sym]:
        now = time.time()
        if not force and cc["data"] is not None:
            if session and now - cc["t"] < INTRADAY_TTL:
                return cc["data"]
            if not session and cc.get("session") is False and now - cc["t"] < 600:
                return cc["data"]
        try:
            live = _live_day(sym) if session else None
            rows = FD.live_bars(sym) if session else []
            snap = compute(sym, live, rows)
        except Exception as e:     # noqa: BLE001
            log.exception(f"[wave] 計算失敗 {sym}：{e}")
            snap = last_good(sym) or {"ok": False, "error": f"計算失敗：{e}"}
            if snap.get("ok"):
                snap = {**snap, "asof": {**(snap.get("asof") or {}), "stale": True, "stale_reason": "這次計算失敗，顯示上一次成功的結果"}}
        if snap.get("ok"):
            cc.update(t=now, data=snap, session=session)
        return snap


def fill_twii_today() -> int:
    """加權今天 5 分 K 不完整（< 54 根）→ Yahoo 補（PLAN §3.4，審查 R3 G-F1）"""
    now = D.tw_now()
    if now.weekday() >= 5 or (now.hour, now.minute) < (13, 35):
        return 0
    s = FD.day_start("TWII", now.strftime("%Y-%m-%d"))
    if FD.count_bars5("TWII", s, s + 270 * 60) >= FD.DAY_MIN_BARS["TWII"]:
        return 0
    return FD.backfill_twii_yahoo()


def refresh_all(chips: bool = True) -> dict:
    """排程／按鈕：重抓資料＋重算（加權、台指期都算）"""
    D.init_db()
    D.ensure_history(background=False)
    D.update_indices()
    FD.update_fut_daily()
    FD.live_bars("TX")
    FD.live_bars("TWII")
    if chips:
        D.update_chips()
        FD.update_fut_chips()
        FD.backfill_taifex(max_files=5)
        fill_twii_today()
    snapshot(force=True, sym="TX")
    return snapshot(force=True)


def panel_snapshot() -> dict:
    """AI 圓桌用：加權快照＋台指期快照（PLAN-B75 §8）"""
    s = snapshot()
    if not s.get("ok"):
        return s
    try:
        tx = snapshot(sym="TX")
    except Exception as e:     # noqa: BLE001
        log.warning(f"[wave] 圓桌台指期快照失敗：{e}")
        tx = None
    return {**s, "tx": tx if tx and tx.get("ok") else None}
