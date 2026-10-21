"""B75 台指期＋分 K 資料（PLAN-B75 §3、§4.1）
- fut_daily：FinMind TaiwanFuturesDaily（TX），每個交易日選「日盤＋夜盤總量最大」的月份（排除價差、週契約）；
  夜盤屬於下一個交易日（期交所慣例，FinMind after_market 的 date 就是那個交易日）；夜盤另存 ref_close＝同一個月份前一個交易日的日盤收盤
- bars5：5 分 K（K 棒開始時間 epoch 秒）。台指期：鉅亨當前交易日（夜盤＋日盤）＋期交所逐筆檔回補近 30 天；加權：Yahoo 5m 60 天＋鉅亨當天
- fut_chips：小台總未平倉、三大法人小台多空、散戶小台多空比、外資選擇權未平倉金額淨多
- 彙總：5 分 K → 30／60 分 K，錨點依盤別（加權 09:00、台指期日盤 08:45、夜盤 15:00）；收盤撮合那根併進最後一根
純函式（parse_*、select_*、agg_*、in_session）不碰網路；fetch／update 才連網"""
from __future__ import annotations

import io
import logging
import math
import threading
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

import httpx
import numpy as np
import pandas as pd

from . import data as D

log = logging.getLogger(__name__)
TW = timezone(timedelta(hours=8))
CNYES_SYM = {"TX": "TWF:TXF:FUTURES", "TWII": "TWS:TSE01:INDEX"}
CNYES_HIST = "https://ws.api.cnyes.com/ws/api/v1/charting/history"
CNYES_QUOTE = "https://ws.api.cnyes.com/ws/api/v1/quote/quotes/"
TAIFEX_ZIP = "https://www.taifex.com.tw/file/taifex/Dailydownload/DailydownloadCSV/Daily_{d}.zip"
# 盤別：(開始時:分, 結束時:分, 跨日)；結束那一刻的撮合併入最後一根
SESSIONS = {"TWII": [("day", (9, 0), (13, 30))],
            "TX": [("day", (8, 45), (13, 45)), ("night", (15, 0), (5, 0))]}
DAY_MIN_BARS = {"TWII": 54, "TX": 54}       # 完整一盤的 5 分 K 根數（判斷要不要回補；台指期結算日日盤到 13:30＝57 根）
NIGHT_MIN_BARS = 150                         # 夜盤 168 根，假日前提早收盤也不會低於這個
_bf_lock = threading.Lock()


# ── 時間 ─────────────────────────────────────────────────────────────────────
def tw_dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, TW)


def in_session(sym: str, now: Optional[datetime] = None) -> bool:
    """TWII 週一～五 09:00～13:35；TX 日盤 週一～五 08:45～13:50、夜盤 週一～五 15:00～24:00＋週二～六 00:00～05:05（PLAN §5）"""
    now = now or D.tw_now()
    wd, hm = now.weekday(), (now.hour, now.minute)
    if sym == "TWII":
        return wd < 5 and (9, 0) <= hm <= (13, 35)
    if wd < 5 and (8, 45) <= hm <= (13, 50):
        return True
    if wd < 5 and hm >= (15, 0):
        return True
    return 1 <= wd <= 5 and hm <= (5, 5)


def session_of(sym: str, ts: float):
    """5 分 K 開始時間 → (盤別, 這一盤開始的 epoch 秒, 結束的 epoch 秒)；不在任何盤內 → None"""
    t = tw_dt(ts)
    for name, (sh, sm), (eh, em) in SESSIONS[sym]:
        start = t.replace(hour=sh, minute=sm, second=0, microsecond=0)
        if name == "night" and (t.hour, t.minute) < (sh, sm):
            start -= timedelta(days=1)
        end = start.replace(hour=eh, minute=em)
        if end <= start:
            end += timedelta(days=1)
        if start <= t <= end:
            return name, start.timestamp(), end.timestamp()
    return None


# ── 5 分 K → 30／60 分 K ─────────────────────────────────────────────────────
def agg_bars(rows: Iterable, sym: str, tf_min: int) -> list:
    """rows：[(ts, o, h, l, c, v)]（ts＝5 分 K 開始時間，升冪）→ [{time, open, high, low, close, volume}]（time＝該根開始時間）
    錨點＝每一盤的開始；剛好在收盤那一刻（13:30／13:45／05:00）的撮合 K 棒併進最後一根"""
    out: dict = {}
    order = []
    step = tf_min * 60
    for ts, o, h, l, c, v in rows:
        if c is None or not math.isfinite(c):
            continue
        s = session_of(sym, ts)
        if s is None:
            continue
        _, st, en = s
        t = min(ts, en - 300)                    # 收盤撮合 → 最後一根 5 分 K
        k = st + int((t - st) // step) * step
        o = c if o is None or not math.isfinite(o) else o
        h = max(o, c) if h is None or not math.isfinite(h) else h
        l = min(o, c) if l is None or not math.isfinite(l) else l
        v = float(v) if v is not None and math.isfinite(float(v)) else 0.0      # NaN 量當 0（審查 Groq F1）
        b = out.get(k)
        if b is None:
            out[k] = {"time": int(k), "open": o, "high": h, "low": l, "close": c, "volume": v}
            order.append(k)
        else:
            b["high"] = max(b["high"], h)
            b["low"] = min(b["low"], l)
            b["close"] = c
            b["volume"] += v
    return [out[k] for k in sorted(order)]


# ── FinMind 日 K → 連續月 ───────────────────────────────────────────────────
def _plain_month(s) -> bool:
    s = str(s).strip()
    return len(s) == 6 and s.isdigit()


def select_continuous(df: pd.DataFrame) -> pd.DataFrame:
    """FinMind TaiwanFuturesDaily（單一商品）→ 每個交易日一個月份（日盤＋夜盤總量最大）的 day／night 列。
    回傳欄位 date, sess, contract, o, h, l, c, v, oi, ref_close（ref_close 只有夜盤：同月份前一個交易日的日盤收盤）"""
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "sess", "contract", "o", "h", "l", "c", "v", "oi", "ref_close"])
    x = df[df["contract_date"].map(_plain_month)].copy()
    x["contract"] = x["contract_date"].astype(str).str.strip()
    x["sess"] = np.where(x["trading_session"].astype(str) == "after_market", "night", "day")
    for k in ("open", "max", "min", "close", "volume", "open_interest"):
        x[k] = pd.to_numeric(x[k], errors="coerce")
    x = x.dropna(subset=["open", "max", "min", "close"])          # 缺值列直接丟（審查 Groq F2）
    x = x[(x["close"] > 0) & (x["open"] > 0) & (x["max"] >= x["min"])]
    vol = x.groupby(["date", "contract"])["volume"].sum().reset_index()
    vol = vol.sort_values(["date", "volume", "contract"], ascending=[True, False, True]).drop_duplicates("date")
    sel = x.merge(vol[["date", "contract"]], on=["date", "contract"], how="inner")
    # 同月份「這個交易日之前最後一個」日盤收盤（夜盤報酬的分母；結算日換月不會有假跳空）
    day_by = {c: (g["date"].astype(str).values, g["close"].values)
              for c, g in x[x["sess"] == "day"].sort_values("date").groupby("contract")}
    out = []
    for r in sel.itertuples():
        rc = None
        if r.sess == "night" and r.contract in day_by:
            ds, cs = day_by[r.contract]
            k = int(np.searchsorted(ds, str(r.date), side="left")) - 1
            rc = float(cs[k]) if k >= 0 else None
        out.append({"date": str(r.date)[:10], "sess": r.sess, "contract": r.contract, "o": float(r.open), "h": float(r.max),
                    "l": float(r.min), "c": float(r.close), "v": float(r.volume or 0),
                    "oi": None if pd.isna(r.open_interest) or r.sess == "night" else float(r.open_interest), "ref_close": rc})
    return pd.DataFrame(out).sort_values(["date", "sess"]).reset_index(drop=True)


def full_bars(fd: pd.DataFrame) -> pd.DataFrame:
    """fut_daily（day／night）→ 全盤日 K：開＝夜盤開（沒有夜盤用日盤）、高低＝兩盤、收＝日盤收、量相加；沒有日盤的那天不出（還沒收）"""
    if fd is None or fd.empty:
        return pd.DataFrame(columns=["date", "o", "h", "l", "c", "v", "contract"])
    rows = []
    for d, g in fd.groupby("date", sort=True):
        day = g[g.sess == "day"]
        if day.empty:
            continue
        dy = day.iloc[0]
        nt = g[g.sess == "night"]
        ok = lambda v: v is not None and not pd.isna(v) and float(v) > 0
        n0 = nt.iloc[0] if len(nt) else None
        o = float(n0.o) if n0 is not None and ok(n0.o) else float(dy.o)
        h = max([float(dy.h)] + ([float(n0.h)] if n0 is not None and ok(n0.h) else []))
        l = min([float(dy.l)] + ([float(n0.l)] if n0 is not None and ok(n0.l) else []))
        rows.append({"date": str(d), "o": o, "h": h, "l": l, "c": float(dy.c),
                     "v": float(dy.v or 0) + (float(nt.iloc[0].v or 0) if len(nt) else 0), "contract": dy.contract})
    return pd.DataFrame(rows)


def night_returns(fd: pd.DataFrame) -> pd.DataFrame:
    """每個交易日的夜盤報酬＝夜盤收／同月份前一日盤收−1（PLAN §3.2）"""
    if fd is None or fd.empty:
        return pd.DataFrame(columns=["date", "night_ret", "night_c", "ref_close"])
    n = fd[(fd.sess == "night") & fd.ref_close.notna() & (fd.ref_close > 0)]
    return pd.DataFrame({"date": n.date.values, "night_ret": (n.c / n.ref_close - 1).values,
                         "night_c": n.c.values, "night_h": n.h.values, "night_l": n.l.values, "ref_close": n.ref_close.values})


# ── 小台散戶、外資選擇權 ─────────────────────────────────────────────────────
def fut_chips_from_finmind(mtx_daily: Optional[pd.DataFrame], mtx_inst: Optional[pd.DataFrame],
                           txo_inst: Optional[pd.DataFrame]) -> pd.DataFrame:
    """散戶多＝小台總未平倉−法人多、散戶空＝總未平倉−法人空 → retail_ratio＝(法人空−法人多)÷總未平倉；
    opt_f_bull＝外資未平倉金額（買方買權−賣方買權）−（買方賣權−賣方賣權）（千元）"""
    parts = []
    if mtx_daily is not None and not mtx_daily.empty:
        m = mtx_daily[(mtx_daily["trading_session"].astype(str) != "after_market") & mtx_daily["contract_date"].map(_plain_month)]
        oi = m.groupby("date")["open_interest"].apply(lambda s: pd.to_numeric(s, errors="coerce").sum())
        parts.append(pd.DataFrame({"mtx_oi": oi}))
    if mtx_inst is not None and not mtx_inst.empty:
        g = mtx_inst.groupby("date")
        parts.append(pd.DataFrame({"mtx_inst_long": g["long_open_interest_balance_volume"].sum().astype(float),
                                   "mtx_inst_short": g["short_open_interest_balance_volume"].sum().astype(float)}))
    if txo_inst is not None and not txo_inst.empty:
        f = txo_inst[txo_inst["institutional_investors"].astype(str).str.contains("外資")].copy()
        sign = np.where(f["call_put"].astype(str).str.contains("買"), 1.0, -1.0)
        f["bull"] = sign * (f["long_open_interest_balance_amount"].astype(float) - f["short_open_interest_balance_amount"].astype(float))
        parts.append(pd.DataFrame({"opt_f_bull": f.groupby("date")["bull"].sum()}))
    if not parts:
        return pd.DataFrame(columns=["date"])
    out = pd.concat(parts, axis=1).sort_index()
    if {"mtx_oi", "mtx_inst_long", "mtx_inst_short"} <= set(out.columns):
        ok = out["mtx_oi"] > 0
        out["retail_ratio"] = np.where(ok, (out["mtx_inst_short"] - out["mtx_inst_long"]) / out["mtx_oi"].where(ok), np.nan)
    out.index.name = "date"
    return out.reset_index()


# ── 鉅亨 ─────────────────────────────────────────────────────────────────────
def parse_cnyes_hist(j: dict) -> list:
    """charting/history → [(ts, o, h, l, c, v)] 升冪（鉅亨回傳是降冪；ts＝K 棒開始時間）"""
    d = (j or {}).get("data") or {}
    t = d.get("t") or []
    if not t:
        return []
    g = lambda k: d.get(k) or [None] * len(t)
    o, h, l, c, v = g("o"), g("h"), g("l"), g("c"), g("v")
    rows = {}
    for i, ts in enumerate(t):
        if c[i] is None:
            continue
        rows[int(ts)] = (int(ts), o[i], h[i], l[i], float(c[i]), v[i])
    return [rows[k] for k in sorted(rows)]


def parse_cnyes_quote(j: dict) -> Optional[dict]:
    """quote → {price, ref, high, low, open, ts}（6 成交、21 參考價（昨收）、12 高、13 低、19 開、200007 時間）"""
    try:
        x = (j.get("data") or [])[0]
        f = lambda k: float(x[k]) if x.get(k) not in (None, "", "-") else None
        p = f("6")
        if p is None:
            return None
        return {"price": p, "ref": f("21"), "high": f("12"), "low": f("13"), "open": f("19"), "ts": int(x.get("200007") or 0)}
    except Exception:     # noqa: BLE001
        return None


def _cnyes_get(url: str, params: Optional[dict] = None, get=None) -> dict:
    get = get or (lambda u, p: httpx.get(u, params=p, headers=D.UA, timeout=8).json())
    last = None
    for _ in range(2):                         # 失敗重試 1 次（PLAN §3.4）
        try:
            return get(url, params)
        except Exception as e:     # noqa: BLE001
            last = e
            time.sleep(0.5)
    raise RuntimeError(f"鉅亨：{last!r}"[:200])


def fetch_cnyes(sym: str, resolution: str = "5", days: int = 3, get=None) -> list:
    now = int(time.time())
    j = _cnyes_get(CNYES_HIST, {"resolution": resolution, "symbol": CNYES_SYM[sym], "from": now, "to": now - days * 86400}, get)
    if j.get("statusCode") not in (200, None):
        raise RuntimeError(f"鉅亨 {sym}：{j.get('message')}")
    return parse_cnyes_hist(j)


def fetch_cnyes_quote(sym: str, get=None) -> Optional[dict]:
    return parse_cnyes_quote(_cnyes_get(CNYES_QUOTE + CNYES_SYM[sym], {"column": "G"}, get))


# ── 期交所逐筆檔 ─────────────────────────────────────────────────────────────
def parse_taifex_ticks(fh, product: str = "TX") -> dict:
    """逐筆 CSV（cp950 文字串流）單次掃描 → {月份: {5 分 K 開始 epoch: [o,h,l,c,v]}}。
    欄位：成交日期,商品代號,到期月份(週別),成交時間,成交價格,成交數量(B+S),…；量是買賣合計 → ÷2；排除價差（月份含 /）"""
    agg: dict = {}
    head = f",{product} "
    head2 = f",{product},"
    for line in fh:
        if head not in line[:20] and head2 not in line[:20]:
            continue
        p = line.split(",")
        if len(p) < 6:
            continue
        mon = p[2].strip()
        if not _plain_month(mon):
            continue
        try:
            d, tm = p[0].strip(), p[3].strip().zfill(6)
            px, q = float(p[4]), float(p[5]) / 2
            dt = datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), int(tm[:2]), int(tm[2:4]), int(tm[4:6]), tzinfo=TW)
        except Exception:     # noqa: BLE001
            continue
        ts = int(dt.timestamp())
        k = ts - ts % 300
        b = agg.setdefault(mon, {}).get(k)
        if b is None:
            agg[mon][k] = [px, px, px, px, q]
        else:
            if px > b[1]:
                b[1] = px
            if px < b[2]:
                b[2] = px
            b[3] = px
            b[4] += q
    return agg


def select_tick_month(agg: dict) -> list:
    """逐筆彙總 → 量最大的月份（日盤＋夜盤合計，跟 fut_daily 同一規則）的 5 分 K [(ts,o,h,l,c,v)]"""
    if not agg:
        return []
    mon = max(agg, key=lambda m: (sum(b[4] for b in agg[m].values()), -int(m)))
    return [(k, *agg[mon][k]) for k in sorted(agg[mon])]


def fetch_taifex_day(day: date, get=None) -> list:
    """下載某交易日的逐筆檔（含前一晚夜盤）→ 5 分 K；串流讀、不整檔載入"""
    url = TAIFEX_ZIP.format(d=day.strftime("%Y_%m_%d"))
    get = get or (lambda u: httpx.get(u, headers={**D.UA, "Referer": "https://www.taifex.com.tw/cht/3/dlFutPrevious30DataView"},
                                      timeout=60, follow_redirects=True))
    r = get(url)
    if getattr(r, "status_code", 200) != 200 or not r.content[:2] == b"PK":
        raise FileNotFoundError(f"期交所逐筆檔 {day} 沒有資料（{getattr(r, 'status_code', '?')}）")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = z.namelist()[0]
        with z.open(name) as raw:
            agg = parse_taifex_ticks(io.TextIOWrapper(raw, encoding="cp950", errors="replace"))
    rows = select_tick_month(agg)
    del agg
    return rows


# ── 資料庫 ───────────────────────────────────────────────────────────────────
def save_bars5(sym: str, rows: list, src: str, now_ts: Optional[float] = None) -> int:
    """只存「已經收完」的 5 分 K（開始時間＋5 分鐘 ≤ 現在）"""
    now_ts = time.time() if now_ts is None else now_ts
    rows = [r for r in rows if r[0] + 300 <= now_ts and r[4] is not None]
    if not rows:
        return 0
    with D.db() as c:
        c.executemany("INSERT INTO bars5(sym,ts,o,h,l,c,v,src) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(sym,ts) DO UPDATE SET "
                      "o=excluded.o,h=excluded.h,l=excluded.l,c=excluded.c,v=excluded.v,src=excluded.src",
                      [(sym, int(ts), o, h, l, cl, v, src) for ts, o, h, l, cl, v in rows])
    return len(rows)


def load_bars5(sym: str, since_ts: Optional[int] = None) -> list:
    with D.db() as c:
        rs = c.execute("SELECT ts,o,h,l,c,v FROM bars5 WHERE sym=? AND ts>=? ORDER BY ts", (sym, int(since_ts or 0))).fetchall()
    return [tuple(r) for r in rs]


def save_fut_daily(df: pd.DataFrame, src: str) -> int:
    if df is None or df.empty:
        return 0
    with D.db() as c:
        c.executemany("INSERT INTO fut_daily(date,sess,contract,o,h,l,c,v,oi,ref_close,src) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(date,sess) DO UPDATE SET contract=excluded.contract,o=excluded.o,h=excluded.h,l=excluded.l,"
                      "c=excluded.c,v=excluded.v,oi=excluded.oi,ref_close=excluded.ref_close,src=excluded.src",
                      [(r["date"], r["sess"], r["contract"], r["o"], r["h"], r["l"], r["c"], r["v"],
                        None if r.get("oi") is None or (isinstance(r.get("oi"), float) and math.isnan(r["oi"])) else r["oi"],
                        None if r.get("ref_close") is None or (isinstance(r.get("ref_close"), float) and math.isnan(r["ref_close"])) else r["ref_close"],
                        src) for r in df.to_dict("records")])
    return len(df)


def load_fut_daily() -> pd.DataFrame:
    with D.db() as c:
        rs = c.execute("SELECT date,sess,contract,o,h,l,c,v,oi,ref_close FROM fut_daily ORDER BY date, sess").fetchall()
    return pd.DataFrame([dict(r) for r in rs], columns=["date", "sess", "contract", "o", "h", "l", "c", "v", "oi", "ref_close"])


def save_fut_chips(df: pd.DataFrame, src: str) -> int:
    if df is None or df.empty:
        return 0
    cols = ["mtx_oi", "mtx_inst_long", "mtx_inst_short", "retail_ratio", "opt_f_bull"]
    with D.db() as c:
        for r in df.to_dict("records"):
            d = str(r["date"])[:10]
            c.execute("INSERT INTO fut_chips(date) VALUES(?) ON CONFLICT(date) DO NOTHING", (d,))
            for k in cols:
                v = r.get(k)
                if v is not None and not (isinstance(v, float) and math.isnan(v)):
                    c.execute(f"UPDATE fut_chips SET {k}=?, src=? WHERE date=?", (float(v), src, d))
    return len(df)


def load_fut_chips() -> pd.DataFrame:
    with D.db() as c:
        rs = c.execute("SELECT date,mtx_oi,mtx_inst_long,mtx_inst_short,retail_ratio,opt_f_bull FROM fut_chips ORDER BY date").fetchall()
    return pd.DataFrame([dict(r) for r in rs], columns=["date", "mtx_oi", "mtx_inst_long", "mtx_inst_short", "retail_ratio", "opt_f_bull"])


def count_bars5(sym: str, start_ts: float, end_ts: float) -> int:
    with D.db() as c:
        return c.execute("SELECT COUNT(*) FROM bars5 WHERE sym=? AND ts>=? AND ts<?", (sym, int(start_ts), int(end_ts))).fetchone()[0]


# ── 更新 ─────────────────────────────────────────────────────────────────────
def update_fut_daily(full: bool = False) -> int:
    """FinMind TX 日 K（日盤＋夜盤）→ fut_daily；失敗 → 鉅亨日 K 補最近缺的日子（全盤，沒有夜盤報酬）"""
    start = "2017-01-01" if full else (D.tw_now().date() - timedelta(days=45)).strftime("%Y-%m-%d")
    try:
        df = D._finmind("TaiwanFuturesDaily", start, data_id="TX")
        n = save_fut_daily(select_continuous(df), "FINMIND")
        D.mark("finmind_txdaily", True)
        return n
    except Exception as e:     # noqa: BLE001
        D.mark("finmind_txdaily", False, repr(e))
    try:
        rows = fetch_cnyes("TX", "D", days=40)
        have = set(load_fut_daily().query("sess == 'day'")["date"])
        add = [{"date": tw_dt(ts).strftime("%Y-%m-%d"), "sess": "day", "contract": "", "o": o, "h": h, "l": l, "c": c, "v": v,
                "oi": None, "ref_close": None} for ts, o, h, l, c, v in rows]
        today = D.tw_now().strftime("%Y-%m-%d")
        add = [r for r in add if r["date"] not in have and r["date"] < today]
        D.mark("cnyes_txdaily", True)
        return save_fut_daily(pd.DataFrame(add), "CNYES_D") if add else 0
    except Exception as e:     # noqa: BLE001
        D.mark("cnyes_txdaily", False, repr(e))
        return 0


def update_fut_chips(full: bool = False) -> int:
    start = "2017-01-01" if full else (D.tw_now().date() - timedelta(days=15)).strftime("%Y-%m-%d")
    got = {}
    for key, ds, did in (("mtx", "TaiwanFuturesDaily", "MTX"), ("mtx_inst", "TaiwanFuturesInstitutionalInvestors", "MTX"),
                         ("txo", "TaiwanOptionInstitutionalInvestors", "TXO")):
        try:
            got[key] = D._finmind(ds, start, data_id=did)
            D.mark(f"finmind_{key}", True)
        except Exception as e:     # noqa: BLE001
            D.mark(f"finmind_{key}", False, repr(e))
            got[key] = None
        time.sleep(1)
    return save_fut_chips(fut_chips_from_finmind(got.get("mtx"), got.get("mtx_inst"), got.get("txo")), "FINMIND")


def live_bars(sym: str, get=None) -> list:
    """鉅亨當前交易日 5 分 K（含盤中最後一根）；收完的順便存檔。失敗回 []"""
    try:
        rows = fetch_cnyes(sym, "5", days=3, get=get)
        save_bars5(sym, rows, "CNYES")
        D.mark(f"cnyes_{sym.lower()}5", True)
        return rows
    except Exception as e:     # noqa: BLE001
        D.mark(f"cnyes_{sym.lower()}5", False, repr(e))
        return []


def live_tx_day() -> Optional[dict]:
    """鉅亨台指期日 K 最新一根＝目前（或剛結束）交易日的全盤 K：{date, o, h, l, c, v}（日期用鉅亨的，自動處理假日；PLAN §5）"""
    try:
        rows = fetch_cnyes("TX", "D", days=6)
        if not rows:
            return None
        ts, o, h, l, c, v = rows[-1]
        D.mark("cnyes_txd", True)
        return {"date": tw_dt(ts).strftime("%Y-%m-%d"), "o": o, "h": h, "l": l, "c": c, "v": v}
    except Exception as e:     # noqa: BLE001
        D.mark("cnyes_txd", False, repr(e))
        return None


def backfill_twii_yahoo(get=None) -> int:
    """Yahoo ^TWII 5m 60 天 → bars5（第一次、或今天鉅亨不完整時補）"""
    get = get or (lambda u, p: httpx.get(u, params=p, headers=D.UA, timeout=40, follow_redirects=True).json())
    try:
        j = get("https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII", {"interval": "5m", "range": "60d"})
        r = j["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        rows = [(int(ts), q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i])
                for i, ts in enumerate(r.get("timestamp") or []) if q["close"][i] is not None]
        n = save_bars5("TWII", rows, "YAHOO")
        D.mark("yahoo_twii5", True)
        return n
    except Exception as e:     # noqa: BLE001
        D.mark("yahoo_twii5", False, repr(e))
        return 0


def day_start(sym: str, d: str) -> float:
    """交易日 d 的日盤開始 epoch（加權 09:00、台指期 08:45）"""
    y, m, dd = (int(x) for x in d.split("-"))
    return datetime(y, m, dd, 9, 0, tzinfo=TW).timestamp() if sym == "TWII" else datetime(y, m, dd, 8, 45, tzinfo=TW).timestamp()


def incomplete_tx_days(trading_days: list, prev_of: dict) -> list:
    """bars5 裡日盤 < 60 根或夜盤 < 150 根的交易日（夜盤＝前一個交易日 15:00 起 14 小時）"""
    out = []
    for d in trading_days:
        ds = day_start("TX", d)
        day_n = count_bars5("TX", ds, ds + 300 * 60)
        night_n = NIGHT_MIN_BARS
        p = prev_of.get(d)
        if p:
            y, m, dd = (int(x) for x in p.split("-"))
            ns = datetime(y, m, dd, 15, 0, tzinfo=TW).timestamp()
            night_n = count_bars5("TX", ns, ns + 14 * 3600)
        if day_n < DAY_MIN_BARS["TX"] or night_n < NIGHT_MIN_BARS:
            out.append(d)
    return out


def backfill_taifex(max_files: int = 5, days: int = 30, get=None) -> int:
    """期交所逐筆檔補近 30 個交易日裡 bars5 不完整的（只看 fut_daily 有日盤的交易日；下載失敗記 src_status，下次排程再試）"""
    if not _bf_lock.acquire(blocking=False):
        return 0
    try:
        fd = load_fut_daily()
        tds = sorted(set(fd[fd.sess == "day"]["date"]))
        today = D.tw_now().strftime("%Y-%m-%d")
        tds = [d for d in tds if d < today or D.tw_now().hour >= 16][-days:]
        prev_of = {tds[i]: tds[i - 1] for i in range(1, len(tds))}
        todo = [d for d in incomplete_tx_days(tds, prev_of) if d in prev_of]   # 第一天沒有前一晚可比，略過
        n = 0
        for d in sorted(todo, reverse=True)[:max_files]:
            try:
                rows = fetch_taifex_day(date.fromisoformat(d), get)
                n += save_bars5("TX", rows, "TAIFEX")
                D.mark("taifex_tick", True)
            except FileNotFoundError as e:
                D.mark("taifex_tick", False, str(e))
                log.info(f"[wave] {e}")
            except Exception as e:     # noqa: BLE001
                D.mark("taifex_tick", False, repr(e))
            if get is None:
                time.sleep(3)
        return n
    finally:
        _bf_lock.release()


def ensure_history(background: bool = True) -> bool:
    """沒有台指期日 K／小台籌碼／分 K 就回補（依序、間隔 3 秒；PLAN §3.4）"""
    with D.db() as c:
        nfd = c.execute("SELECT COUNT(*) FROM fut_daily").fetchone()[0]
        nfc = c.execute("SELECT COUNT(*) FROM fut_chips").fetchone()[0]
        ntw = c.execute("SELECT COUNT(*) FROM bars5 WHERE sym='TWII'").fetchone()[0]
        ntx = c.execute("SELECT COUNT(*) FROM bars5 WHERE sym='TX'").fetchone()[0]
    need = nfd < 500 or nfc < 500 or ntw < 500 or ntx < 2000
    if not need:
        return False

    def _run():
        try:
            if nfd < 500:
                update_fut_daily(full=True)
                time.sleep(3)
            if nfc < 500:
                update_fut_chips(full=True)
                time.sleep(3)
            if ntw < 500:
                backfill_twii_yahoo()
                time.sleep(3)
            live_bars("TX")
            live_bars("TWII")
            if ntx < 2000:
                for _ in range(6):                     # 30 天，每次 5 檔
                    if backfill_taifex(max_files=5) == 0:
                        break
        except Exception as e:     # noqa: BLE001
            log.warning(f"[wave] 期貨回補失敗：{e}")
    if background:
        threading.Thread(target=_run, daemon=True).start()
    else:
        _run()
    return True
