"""B74 大盤解析快照（PLAN-B74 §4、§7）：引擎＋支撐壓力＋籌碼＋國際＋預判＋既有研究訊號 → 一份 JSON。
- 轉折只用收完的日 K；盤中即時價只當現價（算距離、判斷在支撐還是壓力那邊），並檢查「可能轉折」
- 研究結果讀 wave/stats.json（research/wave/run.py 產生）；沒通過的一律標 △
- 預測區間＝全部歷史分布（R6：相似狀態沒有比較準 → 只當參考）"""
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

from . import data as D, engine as E, features as F, forecast as FC, levels as LV

log = logging.getLogger(__name__)
STATS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.json")
INTRADAY_TTL = 120
_cache: dict = {"key": None, "t": 0.0, "data": None}
_lock = threading.Lock()
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
            ]}


_base: dict = {"key": None, "data": None}


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


def base() -> dict:
    """只跟「收完的資料」有關的部分；加權、籌碼、國外指數最新日期或研究檔沒變就不重算（盤中只重算現價相關）"""
    st = stats()
    tw = D.load_idx("TWII")
    if tw.empty or len(tw) < 300:
        return {"ok": False, "error": "加權歷史資料還在下載（第一次約 1～3 分鐘），請稍後重新整理"}
    frames = {s: D.load_idx(s) for s in GLOBAL_SYMS}
    chips = D.load_chips()
    key = (str(tw.date.iloc[-1]), len(tw), float(tw.c.iloc[-1]), None if chips.empty else str(chips.date.iloc[-1]),
           tuple(None if frames[s].empty else str(frames[s].date.iloc[-1]) for s in GLOBAL_SYMS), _stats["mtime"])
    if _base["key"] == key and _base["data"] is not None:
        return _base["data"]
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
    b = {"ok": True, "st": st, "tw": tw, "dates": dates, "o": o, "h": h, "l": l, "c": c, "an": an, "feat": feat,
         "atr": float(E.atr(h, l, c)[-1]), "trend": trend, "waves": waves, "weekly": weekly(tw),
         "chips": _chips(feat, st), "global": _global(tw, st, frames), "context": _context(tw), "research": _research(st)}
    _base.update(key=key, data=b)
    return b


def compute(live: Optional[dict] = None) -> dict:
    b = base()
    if not b.get("ok"):
        return b
    st, dates, o, h, l, c, an = b["st"], b["dates"], b["o"], b["h"], b["l"], b["c"], b["an"]
    t = len(c) - 1
    last_date = str(dates[-1])
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
    now = D.tw_now()
    stale_reason = None
    if not use_live and D.is_tw_session(now) and live is None:
        stale_reason = "盤中即時加權抓不到，顯示最近收盤"
    if now.weekday() < 5 and (now.hour, now.minute) >= (14, 30) and last_date < now.strftime("%Y-%m-%d"):
        stale_reason = f"今天收盤資料還沒進來（最新 {last_date}）"
    problems = [s for s in D.status() if (s.get("fails") or 0) >= 2]
    snap = {
        "ok": True, "generated": now.strftime("%Y-%m-%d %H:%M:%S"),
        "asof": {"date": last_date, "live": {"time": live.get("time"), "date": live["date"]} if use_live else None,
                 "stale": stale_reason is not None, "stale_reason": stale_reason},
        "price": _f(price), "prev_close": _f(prev), "chg": _f(price - prev), "chg_pct": _pct(price, prev),
        "atr": _f(b["atr"], 0), "trend240": b["trend"],
        "chart": {"bars": bars, "weekly": b["weekly"], "ma": mas},
        "waves": waves, "levels": lv, "forecast": fc,
        "chips": b["chips"], "global": b["global"], "context": b["context"], "research": b["research"],
        "problems": [{"src": p["src"], "fails": p["fails"], "last_ok": p["last_ok"]} for p in problems],
        "disclaimer": DISCLAIMER,
    }
    snap["scenario"] = _scenario(an, lv, price, fc)
    try:
        with D.db() as conn:
            conn.execute("INSERT INTO wave_snapshot(day,kind,created_at,json) VALUES(?,?,?,?) "
                         "ON CONFLICT(day,kind) DO UPDATE SET created_at=excluded.created_at, json=excluded.json",
                         (live["date"] if use_live else last_date, "live" if use_live else "close", snap["generated"],
                          json.dumps(snap, ensure_ascii=False)))
    except Exception as e:     # noqa: BLE001
        log.warning(f"[wave] 存快照失敗：{e}")
    return snap


def last_good() -> Optional[dict]:
    try:
        with D.db() as conn:
            r = conn.execute("SELECT json FROM wave_snapshot WHERE kind IN ('close','live') "
                             "ORDER BY day DESC, created_at DESC LIMIT 1").fetchone()
        return json.loads(r["json"]) if r else None
    except Exception:     # noqa: BLE001
        return None


def snapshot(force: bool = False) -> dict:
    """盤中：超過 2 分鐘用即時價重算；盤後：資料日期沒變就用快取。算失敗 → 上一次成功的快照（標過期）"""
    session = D.is_tw_session()
    with _lock:
        now = time.time()
        if not force and _cache["data"] is not None:
            if session and now - _cache["t"] < INTRADAY_TTL:
                return _cache["data"]
            if not session and _cache.get("session") is False and now - _cache["t"] < 600:
                return _cache["data"]
        try:
            live = D.live_taiex() if session else None
            snap = compute(live)
        except Exception as e:     # noqa: BLE001
            log.exception(f"[wave] 計算失敗：{e}")
            snap = last_good() or {"ok": False, "error": f"計算失敗：{e}"}
            if snap.get("ok"):
                snap = {**snap, "asof": {**(snap.get("asof") or {}), "stale": True, "stale_reason": "這次計算失敗，顯示上一次成功的結果"}}
        if snap.get("ok"):
            _cache.update(t=now, data=snap, session=session)
        return snap


def refresh_all(chips: bool = True) -> dict:
    """排程／按鈕：重抓資料＋重算"""
    D.init_db()
    D.ensure_history(background=False)
    D.update_indices()
    if chips:
        D.update_chips()
    return snapshot(force=True)
