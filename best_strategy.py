"""
best_strategy.py — 🔬 研究選出的方法（PLAN-BEST；研究在 research/best/，結果 research/best/results/）

掃描（S_BEST）、交易計畫（明天怎麼買、停損、出場、最晚哪天）、觀察清單出場狀態、Telegram、說明頁共用。
訊號、出場規則跟研究版（research/best/run.py、engine.py）同一套算法，tests/test_best.py 抽樣比對逐日一致。
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SUMMARY_PATH = os.path.join(HERE, "research", "best", "results", "summary.json")

# ── 研究結果（research/best/run.py＋report.py；重跑研究後更新這裡）────────────────
# 2026-10-09：18,426 個組合沒有一個通過全部標準（REPORT.md）。這是最接近的：每筆統計樣本內外都合格、
# 勝過隨機基準、bootstrap 下限 > 0，只差「整個帳戶照做的最大回撤 ≤ 30%」（實際 −35.8%）→ 網站標「研究候選（未全過）」
CONFIG = {"signal": "C1_S_BIAS+S_BREAKBOTTOM", "regime": "none", "exit": "E3_t1_s2_20d"}
PASSED = False             # True＝通過全部關卡（主推）；False＝最接近、未全過
KEY = "S_BEST"
LABEL = "🔬 研究候選（負乖離＋破底翻抄底，未全過）"
NOTE_TAGS = ("🔬 研究候選", "研究候選", "🏆", "研究最佳")    # 觀察清單「來源」含這些字＝從這個方法加入

WINDOW = 520           # 正式站掃描讀最近 520 根（yahoo_price._fetch_for_scan），研究也這樣算
MIN_PRICE, MIN_VOL20, MIN_BARS = 10.0, 500.0, 120


# ── 指標（跟 research/best/engine.features 同一套）──────────────────────────
def _arrays(df: pd.DataFrame) -> dict:
    from price_levels import atr_series
    from scanner_course import rsi
    d = df.dropna(subset=["close"]).reset_index(drop=True)
    c = d["close"].astype(float)
    v = d["volume"].astype(float)
    A = {"date": [str(x).replace("-", "")[:8] for x in d["date"]], "c": c.values, "o": d["open"].astype(float).values,
         "h": d["high"].astype(float).values, "l": d["low"].astype(float).values, "v": v.values}
    for n in (5, 10, 20, 60, 120, 200):
        A[f"ma{n}"] = c.rolling(n).mean().values
    A["atr"] = atr_series(A["h"], A["l"], A["c"])
    A["rsi2"] = rsi(c, 2).values
    vol20 = v.rolling(20).mean()
    A["vol20"], A["vol20p"] = vol20.values, vol20.shift(1).values
    A["ma60_5"] = pd.Series(A["ma60"]).shift(5).values
    A["c3"] = c.shift(3).values
    A["ph"] = d["high"].astype(float).shift(1).values
    A["n"] = len(c)
    A["df"] = d
    return A


def gap_guard(A: dict, i: int) -> bool:
    """最近 60 根（含今天）有沒有單日跳動 > 10.5%（台股漲跌幅上限 10% → 一定是除權息／減資之類的事件）。
    有的話不還原價格的均線、乖離、ATR 都被扭曲，不出訊號（研究版 engine.features 的 gap60 同一套）"""
    if "gap" not in A:
        c, o = A["c"], A["o"]
        pc = np.r_[np.nan, c[:-1]]
        with np.errstate(invalid="ignore", divide="ignore"):
            j = (np.abs(c / pc - 1) > 0.105) | (np.abs(o / pc - 1) > 0.105)
        A["gap"] = pd.Series(j.astype(float)).rolling(60, min_periods=1).max().values > 0
    return bool(A["gap"][i])


def liquid(A: dict, i: int) -> bool:
    """股票池：收盤 ≥ 10、20 日均量 ≥ 500 張、至少 120 根"""
    with np.errstate(invalid="ignore"):
        return bool(A["c"][i] >= MIN_PRICE and A["vol20"][i] >= MIN_VOL20 and i + 1 >= MIN_BARS)


# ── 訊號（名稱跟研究一樣：B1_ma200_rsi5、C1_S1+S_FBD …）──────────────────────
def _a_hit(A: dict, key: str, i: int, cache: dict) -> bool:
    """現有策略 key 在第 i 根（用截至第 i 根、最多 520 根的資料）有沒有出現；研究只在股票池的日子算"""
    ck = (key, i)
    if ck not in cache:
        ok = False
        if i >= 0 and liquid(A, i):
            from scanner import PRICE_STRATEGY_FNS
            sub = A["df"].iloc[max(0, i - WINDOW + 1):i + 1]
            try:
                ok = bool(PRICE_STRATEGY_FNS[key]({"BT": sub}, {"BT": ""}, params=None))
            except Exception:
                ok = False
        cache[ck] = ok
    return cache[ck]


def _deep_raw(A: dict) -> np.ndarray:
    if "deep_raw" not in A:
        from deep_verdict import tech_series
        ts = tech_series(A["df"])
        raw = _tech_raw_vec(ts)
        raw[:129] = np.nan
        A["deep_raw"] = raw
    return A["deep_raw"]


def _tech_raw_vec(ts: pd.DataFrame) -> np.ndarray:
    """deep_verdict.tech_raw 的向量版（research/best/run.py 同一份）"""
    def tier(x, cuts, pts):
        out = np.zeros(len(x)); done = np.zeros(len(x), bool)
        for cut, p in zip(cuts, pts):
            h = ~done & (x >= cut); out[h] = p; done |= h
        return out
    trend = np.where(ts["bull"], 8, np.where(ts["above60"], 4, 0))
    p52 = ts["pos52"].to_numpy(float); r120 = ts["r120"].to_numpy(float)
    return (trend + np.where(ts["ma60_up"], 6, 0) + np.where(ts["dif_pos"], 6, 0)
            + tier(np.nan_to_num(p52, nan=-9), (.8, .6, .4, .2), (10, 7, 4, 2))
            + tier(np.nan_to_num(r120, nan=-9), (.3, .1, 0, -.1), (10, 7, 4, 2)))


def signal_at(A: dict, i: int, name: Optional[str] = None, cache: Optional[dict] = None) -> bool:
    """第 i 根收盤後，訊號 name 成立嗎（不含大盤濾網；含股票池）"""
    name = name or CONFIG["signal"]
    cache = {} if cache is None else cache
    if i < 0 or i >= A["n"] or not liquid(A, i) or gap_guard(A, i):
        return False
    c, l, o = A["c"], A["l"], A["o"]
    with np.errstate(invalid="ignore", divide="ignore"):
        atr, rsi2 = A["atr"][i], A["rsi2"][i]
        vr = A["v"][i] / A["vol20p"][i] if A["vol20p"][i] else np.nan
        m = re.match(r"B1_ma(\d+)_(rsi|dev|drop)([\d.]+)$", name)
        if m:
            n, kind, k = int(m.group(1)), m.group(2), float(m.group(3))
            if not c[i] > A[f"ma{n}"][i]:
                return False
            if kind == "rsi":
                return bool(rsi2 <= k)
            if kind == "dev":
                return bool((A["ma20"][i] - c[i]) / atr >= k)
            return bool((A["c3"][i] - c[i]) / atr >= k)
        trend = bool(A["ma20"][i] > A["ma60"][i] and A["ma60"][i] > A["ma60_5"][i])
        m = re.match(r"B2_pull_ma(\d+)$", name)
        if m:
            ma = A[f"ma{m.group(1)}"][i]
            return bool(trend and l[i] <= ma <= c[i])
        m = re.match(r"B3_brk(\d+)_v([\d.]+)$", name)
        if m:
            n, k = int(m.group(1)), float(m.group(2))
            if i < n:
                return False
            return bool(c[i] > np.max(c[i - n:i]) and vr >= k)
        if name == "B4_deep_strong":
            raw = _deep_raw(A)
            return bool(i >= 1 and raw[i] >= 32 and raw[i - 1] < 32)
        if name == "B5_gap":
            return bool(o[i] > A["ph"][i] * 1.01 and c[i] >= o[i] and vr >= 2)
        m = re.match(r"C4_strong_(rsi|dev)([\d.]+)$", name)
        if m:
            if not _deep_raw(A)[i] >= 32:
                return False
            k = float(m.group(2))
            return bool(rsi2 <= k) if m.group(1) == "rsi" else bool((A["ma20"][i] - c[i]) / atr >= k)
        m = re.match(r"A_(.+)$", name)
        if m:
            return _a_hit(A, m.group(1), i, cache)
        m = re.match(r"C1_(.+)\+(.+)$", name)
        if m:
            x, y = m.groups()
            win = lambda k: any(_a_hit(A, k, j, cache) for j in (i, i - 1, i - 2))
            return bool((_a_hit(A, x, i, cache) and win(y)) or (_a_hit(A, y, i, cache) and win(x)))
        m = re.match(r"C2_(.+)&(c60|c200|up)$", name)
        if m:
            k, t = m.groups()
            tm = {"c60": c[i] > A["ma60"][i], "c200": c[i] > A["ma200"][i], "up": trend}[t]
            return bool(tm and _a_hit(A, k, i, cache))
        m = re.match(r"C3_consensus(\d)$", name)
        if m:
            from scanner import PRICE_STRATEGY_FNS, SHORT_STRATEGIES
            keys = [k for k in PRICE_STRATEGY_FNS if k not in SHORT_STRATEGIES and k != KEY]
            today = any(_a_hit(A, k, i, cache) for k in keys)
            cnt = sum(1 for k in keys if any(_a_hit(A, k, j, cache) for j in (i, i - 1, i - 2)))
            return bool(today and cnt >= int(m.group(1)))
    raise ValueError(f"不認得的訊號 {name}")


# ── 大盤濾網（加權指數）────────────────────────────────────────────────────
_TAIEX: dict = {"t": 0.0, "s": None}
import threading as _threading
_TAIEX_LOCK = _threading.Lock()          # 掃描 4 個 worker 同時要，只抓一次


def _taiex_twse_months(n_months: int = 11) -> dict:
    """證交所 FMTQIK（每月每日成交＋加權指數），往回抓 n_months 個月：{YYYYMMDD: 收盤}"""
    import httpx, time
    out, d = {}, date.today().replace(day=1)
    for _ in range(n_months):
        try:
            j = httpx.get("https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK",
                          params={"date": d.strftime("%Y%m%d"), "response": "json"},
                          headers={"User-Agent": "Mozilla/5.0"}, timeout=15).json()
            for r in j.get("data") or []:
                y, m, dd = (int(x) for x in str(r[0]).split("/"))
                out[f"{y + 1911:04d}{m:02d}{dd:02d}"] = float(str(r[4]).replace(",", ""))
        except Exception:
            pass
        d = (d - timedelta(days=1)).replace(day=1)
        time.sleep(0.5)
    return out


def taiex_series() -> Optional[pd.Series]:
    """加權指數收盤（YYYYMMDD → 收盤）：regime 資料庫 market_daily；不到 210 天就用證交所每月指數表補（大盤濾網要 200 日線），10 分鐘快取"""
    import time
    with _TAIEX_LOCK:
        if _TAIEX["s"] is not None and time.time() - _TAIEX["t"] < 600:
            return _TAIEX["s"]
        return _taiex_load()


def _taiex_load() -> Optional[pd.Series]:
    import time
    vals = {}
    try:
        from regime.db import db
        with db() as conn:
            rows = conn.execute("SELECT date, value FROM market_daily WHERE series='TAIEX' ORDER BY date").fetchall()
        vals = {str(d).replace("-", ""): float(v) for d, v in rows if v}
    except Exception:
        pass
    if len(vals) < 210 and CONFIG["regime"] != "none":
        vals.update(_taiex_twse_months())
    s = pd.Series(vals, dtype=float).sort_index() if vals else None
    _TAIEX.update(t=time.time(), s=s)
    return s


def regime_ok(day: str, regime: Optional[str] = None, tx: Optional[pd.Series] = None) -> Optional[bool]:
    """訊號日的大盤濾網：none 一律 True；tx60／tx200＝加權指數收盤 > 60／200 日線。資料不夠回 None"""
    regime = regime or CONFIG["regime"]
    if regime == "none":
        return True
    if tx is None:
        tx = taiex_series()
        if tx is not None and day not in tx.index:           # 18:00 掃描時 regime 還沒更新今天 → 補這個月
            with _TAIEX_LOCK:
                tx = _TAIEX["s"]
                if tx is not None and day not in tx.index and not _TAIEX.get(f"tried:{day}"):
                    _TAIEX[f"tried:{day}"] = True
                    extra = _taiex_twse_months(1)
                    if extra:
                        tx = pd.concat([tx, pd.Series(extra, dtype=float)])
                        tx = tx[~tx.index.duplicated(keep="last")].sort_index()
                        _TAIEX["s"] = tx
    if tx is None:
        return None
    n = 60 if regime == "tx60" else 200
    s = tx[tx.index <= day]
    if len(s) < n or s.index[-1] != day:
        return None
    return bool(s.iloc[-1] > s.iloc[-n:].mean())


# ── 出場規則 ────────────────────────────────────────────────────────────────
def exit_rule(name: Optional[str] = None) -> dict:
    name = name or CONFIG["exit"]
    m = re.match(r"E1_(\d+)d$", name)
    if m:
        return {"kind": "time", "max": int(m.group(1))}
    m = re.match(r"E2_ma5rsi_(\d+)d$", name)
    if m:
        return {"kind": "ma5", "max": int(m.group(1))}
    m = re.match(r"E3_t([\d.]+)_s([\d.]+)_(\d+)d$", name)
    if m:
        return {"kind": "atr", "tgt": float(m.group(1)), "stp": float(m.group(2)), "max": int(m.group(3))}
    m = re.match(r"E4_ma(\d+)$", name)
    if m:
        return {"kind": f"ma{m.group(1)}", "max": 60}
    m = re.match(r"E5_roll_(\d+)d$", name)
    if m:
        return {"kind": "roll", "max": int(m.group(1))}
    raise ValueError(f"不認得的出場 {name}")


def _fmt(x, nd=2):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def _add_trading_days(day: str, n: int) -> str:
    """大約的第 n 個交易日（只跳週末，國定假日不算 → 實際可能晚 1～2 天）"""
    d = date(int(day[:4]), int(day[4:6]), int(day[6:]))
    k = 0
    while k < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            k += 1
    return d.strftime("%Y%m%d")


def plan_for(A: dict, sig_idx: int, entry_idx: Optional[int] = None, rule: Optional[dict] = None,
             entry_price: Optional[float] = None) -> dict:
    """訊號在第 sig_idx 根收盤出現 → 交易計畫。entry_idx＝實際買進那根（隔天開盤）；還沒買（就是今天的訊號）給 None。
    回傳 {buy, stop, target, max_days, last_day, exit_today, exit_reason, held_days, status}；
    exit_today＝最新一根收盤出場條件成立（明天開盤賣）。"""
    rule = rule or exit_rule()
    c, o = A["c"], A["o"]
    last = A["n"] - 1
    kind, M = rule["kind"], rule["max"]
    a = A["atr"][sig_idx]
    ref = c[sig_idx] if entry_idx is None else (entry_price or o[entry_idx])   # 還沒買：用今天收盤估；有成本用成本
    out = {"signal_date": A["date"][sig_idx], "max_days": M, "kind": kind, "atr": _fmt(a),
           "buy": "明天開盤買（開盤一價漲停就不追）" if entry_idx is None else f"{A['date'][entry_idx]} 開盤 {_fmt(o[entry_idx])}",
           "entry_price": _fmt(ref) if entry_idx is not None else None,
           "stop": None, "target": None, "stop_note": "", "exit_today": False, "exit_reason": "", "held_days": 0}
    if kind == "atr":
        out["stop"] = _fmt(ref - rule["stp"] * a)
        out["target"] = _fmt(ref + rule["tgt"] * a)
        out["stop_note"] = f"收盤 < 買進價 − {rule['stp']:g} 倍 ATR" + ("（還沒買，用今天收盤估）" if entry_idx is None else "")
    elif kind == "roll":
        import price_levels as pl
        r = pl.rolling_stop(A["df"].iloc[:last + 1], sig_idx, kind="cost")
        out["stop"] = r["price"] if not r.get("breached") else r["breached"]["stop"]
        out["entry_stop"] = r["entry_stop"]
        out["stop_note"] = "滾動停損（結構低點進場、平台低點上修，只上不下）"
        out["roll"] = r
    elif kind in ("ma10", "ma20"):
        out["stop_note"] = f"收盤跌破 {kind[2:]} 日線"
        out["stop"] = _fmt(A[kind][last])
    elif kind == "ma5":
        out["stop_note"] = "沒有價格停損（收盤站上 5 日線或 RSI(2) > 70 就賣、最多抱 {} 天）".format(M)
    else:
        out["stop_note"] = f"沒有價格停損（固定抱 {M} 個交易日）"
    e = entry_idx if entry_idx is not None else None
    if e is None:
        out["last_day"] = _add_trading_days(A["date"][sig_idx], M + 1)
        out["status"] = "signal"
        return out
    out["last_day"] = A["date"][e + M] if e + M <= last else _add_trading_days(A["date"][last], e + M - last)
    out["held_days"] = last - e + 1
    reason = ""
    for j in range(e, last + 1):                       # 進場那天起，每天收盤檢查
        if j - e >= M:
            break
        cj = c[j]
        if kind == "atr":
            if cj >= ref + rule["tgt"] * a:
                reason = "收盤到停利價"
            elif cj < ref - rule["stp"] * a:
                reason = "收盤跌破停損"
        elif kind == "ma5":
            if cj > A["ma5"][j] or A["rsi2"][j] > 70:
                reason = "收盤站上 5 日線" if cj > A["ma5"][j] else "RSI(2) > 70"
        elif kind in ("ma10", "ma20"):
            if cj < A[kind][j]:
                reason = f"收盤跌破 {kind[2:]} 日線"
        elif kind == "roll":
            br = out["roll"].get("breached")
            if br and br["date"] == A["date"][j]:
                reason = "收盤跌破滾動停損"
        if reason:
            out["exit_reason"] = reason
            out["exit_date"] = A["date"][j]
            break
    if not reason and last - e + 1 >= M:
        out["exit_reason"] = f"抱滿 {M} 天"
        out["exit_date"] = A["date"][min(e + M - 1, last)]
    if out["exit_reason"]:
        out["exit_today"] = out.get("exit_date") == A["date"][last]
        out["status"] = "exit_today" if out["exit_today"] else "exited"
    else:
        out["status"] = "holding"
    return out


def plan_text(p: dict) -> str:
    """一行字：買｜損｜出場｜最晚"""
    ld = p.get("last_day") or ""
    parts = [f"買：{'明天開盤' if p.get('status') == 'signal' else p.get('buy')}"]
    if p.get("stop") is not None:
        parts.append(f"損 {p['stop']}")
    if p.get("target") is not None:
        parts.append(f"利 {p['target']}")
    parts.append(f"最晚 {ld[4:6]}/{ld[6:]}" if ld else "")
    return "｜".join(x for x in parts if x)


# ── 掃描（scanner 介面）──────────────────────────────────────────────────────
def screen_best(prices: dict, names: dict = None, params: dict = None) -> list:
    if not CONFIG["signal"]:
        return []
    out = []
    for sid, df in prices.items():
        if sid != "BT" and not re.fullmatch(r"[1-9]\d{3}", str(sid)):
            continue
        if df is None or len(df) < MIN_BARS:
            continue
        try:
            r = _screen_one(sid, df.tail(WINDOW), names)
        except Exception as e:                          # 這個方法出錯不能拖累同一檔的其他策略
            print(f"[S_BEST] {sid} 計算失敗：{type(e).__name__}: {e}")
            r = None
        if r:
            out.append(r)
    return out


def _screen_one(sid: str, df: pd.DataFrame, names: Optional[dict]) -> Optional[dict]:
    from scanner import _name, _change_pct, calc_bb_score
    A = _arrays(df)
    i = A["n"] - 1
    if not signal_at(A, i):
        return None
    rg = regime_ok(A["date"][i]) if sid != "BT" else True
    if rg is False:
        return None
    p = plan_for(A, i)
    # 連續出現（3 天內都算）：往回找這一串的第一天；研究裡持有中再出現的訊號不會再買
    first, cache = i, {}
    for j in range(i - 1, max(-1, i - 10), -1):
        if not signal_at(A, j, cache=cache):
            break
        first = j
    run_note = "" if first == i else f"連續第 {i - first + 1} 天出現（第一次 {A['date'][first][4:6]}/{A['date'][first][6:]}）：已經買的照原計畫，不要加碼"
    return {"stock_id": sid, "name": _name(sid, names or {}), "close": round(float(A["c"][i]), 2),
            "change_pct": _change_pct(df), "volume": round(float(A["v"][i])), "bb_score": calc_bb_score(df),
            "strategy": KEY, "stop": p["stop"], "target": p["target"], "last_day": p["last_day"],
            "plan": plan_text(p), "stop_note": p["stop_note"],
            "regime_note": "" if rg else "大盤資料不足，請自己確認加權指數在均線上",
            "first_date": A["date"][first], "note": run_note}


def summary() -> dict:
    try:
        with open(SUMMARY_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}
