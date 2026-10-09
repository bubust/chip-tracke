"""
course_live.py — 講義訊號正式站（PLAN-COURSE 項目 4、7、9、10、11）

每晚 18:00 掃描後 nightly() 算一次、存 cache.db 的 course_daily（kind, date, JSON）：
- dist      出貨日（下跌出量／量大不漲），全部股票最近 3 個交易日（course2.sig_distribution，研究同一個函式）
- sector    主流族群（20 日成交金額前 5 名）今天有沒有同步大跌（成員 ≥ 60% 跌 ≥ 3%、等權 ≤ −3%、量 ≥ 1.2 倍）
- daytrade  明天的當沖多空名單（個股期貨標的 ∪ 成交金額前 100、昨天剛起漲／剛起跌，各前 10）
- limit     連續跳空漲停 ≥ 2 天的候選（明天盤中盯「爆量打開」）＋今天收盤已經打開的
- market    大盤出貨日（最近 5 天過熱指數 > 0.5＋加權第一次跌破 d 點）
盤中 limit_tick() 每分鐘用鉅亨即時報價看候選有沒有「打開」（現價 < 漲停價、量 ≥ 昨量 × 3），打開就 Telegram（同股同日一次）。
研究結果（research/course/results）：這些多數沒有通過驗證，網頁照實標示；推播只是提醒，不是買賣建議。
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import numpy as np

import course2 as C

log = logging.getLogger(__name__)
_LOCK = threading.Lock()
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

# 研究挑出的參數（research/course/results；沒通過的也用研究裡樣本最多／講義原意的那組，網頁標示）
LIMIT_N, LIMIT_M = 2, 3.0          # 連續 ≥ 2 天跳空漲停、打開量 ≥ 昨量 × 3
MARKET_K, MARKET_HOT = 3, 0.5      # d 點用 k=3 波段低點；過熱指數 > 0.5
DT_TOP = 10


def _conn():
    from chip_tracker_v2 import DB_PATH
    c = sqlite3.connect(str(DB_PATH), timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _init(c):
    c.execute("CREATE TABLE IF NOT EXISTS course_daily (kind TEXT, date TEXT, data TEXT, at TEXT, PRIMARY KEY (kind, date))")
    c.execute("CREATE TABLE IF NOT EXISTS revenue_month (ym TEXT, stock_id TEXT, yoy REAL, cum_yoy REAL, PRIMARY KEY (ym, stock_id))")
    c.execute("CREATE TABLE IF NOT EXISTS course_meta (k TEXT PRIMARY KEY, v TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS overheat_daily (date TEXT PRIMARY KEY, ratio REAL)")


def save(kind: str, day: str, data) -> None:
    c = _conn()
    _init(c)
    c.execute("INSERT OR REPLACE INTO course_daily VALUES (?,?,?,?)", (kind, day, json.dumps(data, ensure_ascii=False, default=_js), datetime.now().isoformat()))
    c.commit()
    c.close()


def latest(kind: str, before: str | None = None):
    """最新一筆（before＝只要日期 < before 的）"""
    c = _conn()
    _init(c)
    if before:
        r = c.execute("SELECT date, data FROM course_daily WHERE kind=? AND date<? ORDER BY date DESC LIMIT 1", (kind, before)).fetchone()
    else:
        r = c.execute("SELECT date, data FROM course_daily WHERE kind=? ORDER BY date DESC LIMIT 1", (kind,)).fetchone()
    c.close()
    return json.loads(r["data"]) if r else None


def _js(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def _f(x, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if np.isfinite(x) else None


# ── 資料 ─────────────────────────────────────────────────────────────────────
def load_recent(days: int = 300):
    """price_daily 最近 days 個交易日（4 碼股票）→ dates, ids, names, O H L C V（日期 × 股票，float32；逐列讀，不建 pandas 大寬表）"""
    c = _conn()
    cnt = c.execute("SELECT date, COUNT(*) FROM price_daily WHERE stock_id GLOB '[1-9][0-9][0-9][0-9]' "
                    "GROUP BY date ORDER BY date DESC LIMIT ?", (days + 40,)).fetchall()
    if not cnt:
        c.close()
        return None
    med = float(np.median([n for _, n in cnt]))
    # 只收「股票數 ≥ 中位數 6 成」的日子：只有零星幾檔的日子（官方日行情還沒寫、只有 Yahoo 補到幾檔）整天不算，免得最後一天變成 NaN
    ds = sorted(d for d, n in cnt if n >= 0.6 * med)[-days:]
    if not ds:
        c.close()
        return None
    di = {d: i for i, d in enumerate(ds)}
    q = "FROM price_daily WHERE date >= ? AND stock_id GLOB '[1-9][0-9][0-9][0-9]'"
    ids = sorted(r[0] for r in c.execute(f"SELECT DISTINCT stock_id {q}", (ds[0],)))
    names = {}
    for sid, nm in c.execute("SELECT stock_id, name FROM price_daily WHERE date >= ? AND stock_id GLOB '[1-9][0-9][0-9][0-9]' "
                             "AND name IS NOT NULL AND name != '' ORDER BY date", (ds[-min(5, len(ds))],)):
        names[sid] = nm
    si = {s: j for j, s in enumerate(ids)}
    A = {k: np.full((len(ds), len(ids)), np.nan, dtype=np.float32) for k in "ohlcv"}
    for d, sid, o, h, l, cl, v in c.execute(f"SELECT date, stock_id, open, high, low, close, volume {q}", (ds[0],)):
        i, j = di.get(d), si.get(sid)
        if i is None or j is None:
            continue
        for k, x in (("o", o), ("h", h), ("l", l), ("c", cl), ("v", v)):
            if x is not None:
                A[k][i, j] = x
    c.close()
    return {"dates": ds, "ids": ids, "names": names, **A}


def _stock(P, j):
    """第 j 檔：去掉沒交易的日子 → (列號, o, h, l, c, v)（float64）"""
    ok = np.isfinite(P["c"][:, j]) & np.isfinite(P["o"][:, j])
    rows = np.nonzero(ok)[0]
    return rows, *(P[k][ok, j].astype(float) for k in "ohlcv")


def _pool_ok(c, o, v, min_vol=500.0):
    if len(c) < 120 or c[-1] < 10 or np.nanmean(v[-20:]) < min_vol:
        return False
    pc = c[-61:-1]
    with np.errstate(invalid="ignore", divide="ignore"):
        j = (np.abs(c[-60:] / pc - 1) > 0.105) | (np.abs(o[-60:] / pc - 1) > 0.105)
    return not bool(j.any())


# ── 7 出貨日 ─────────────────────────────────────────────────────────────────
DIST_NAME = {C.DIST_DOWNVOL: "下跌出量", C.DIST_STALL: "量大不漲"}


def calc_dist(P, back: int = 3) -> dict:
    T = len(P["dates"])
    items = []
    for j, sid in enumerate(P["ids"]):
        rows, o, h, l, c, v = _stock(P, j)
        if len(c) < 80:
            continue
        typ = C.sig_distribution(o, h, l, c, v)
        for k in range(1, back + 1):
            if len(typ) < k or rows[-k] < T - back:
                continue
            if typ[-k]:
                i = len(c) - k
                items.append({"stock_id": sid, "name": P["names"].get(sid, ""), "date": P["dates"][rows[i]], "type": int(typ[-k]),
                              "type_name": DIST_NAME[int(typ[-k])], "close": _f(c[i]), "chg": _f(c[i] / c[i - 1] - 1, 4),
                              "vol_x": _f(v[i] / np.nanmean(v[max(0, i - 20):i]), 1)})
    items.sort(key=lambda x: (x["date"], x["vol_x"] or 0), reverse=True)
    return {"date": P["dates"][-1], "items": items}


def dist_of(sid: str, days: int = 300) -> list:
    """單一檔：最近 days 天的出貨日（K 線標記、詳細）"""
    c = _conn()
    rows = c.execute("SELECT date, open, high, low, close, volume FROM price_daily WHERE stock_id=? ORDER BY date DESC LIMIT ?", (sid, days)).fetchall()
    c.close()
    rows = [r for r in rows[::-1] if r["close"] is not None and r["open"] is not None]
    if len(rows) < 80:
        return []
    o, h, l, cl, v = (np.array([float(r[k] or 0) for r in rows]) for k in ("open", "high", "low", "close", "volume"))
    typ = C.sig_distribution(o, h, l, cl, v)
    return [{"date": rows[i]["date"], "type": int(typ[i]), "type_name": DIST_NAME[int(typ[i])]} for i in np.nonzero(typ)[0]]


# ── 9 主流族群同步大跌 ───────────────────────────────────────────────────────
def calc_sector(P) -> dict:
    import linkage
    secs = linkage.sector_map()
    ids = P["ids"]
    si = {s: j for j, s in enumerate(ids)}
    c, o, v = P["c"].astype(float), P["o"].astype(float), P["v"].astype(float)
    T = len(P["dates"])
    if T < 62:
        return {"date": P["dates"][-1], "main": [], "crash": [], "note": "資料不夠"}
    pool = np.zeros(len(ids), bool)
    for j in range(len(ids)):
        cc = c[:, j]
        ok = np.isfinite(cc)
        if ok.sum() >= 120 and np.isfinite(cc[-1]):
            pool[j] = _pool_ok(cc[ok], o[ok, j], v[ok, j])
    turn = np.nan_to_num(c * v, nan=0.0)[-20:]
    mkt = (turn * pool).sum()
    with np.errstate(invalid="ignore", divide="ignore"):
        r1 = c[-1] / c[-2] - 1
    groups = {}
    for sid, sec in secs.items():
        j = si.get(sid)
        if j is not None and pool[j]:
            groups.setdefault(sec, []).append(j)
    rows = []
    for sec, mem in groups.items():
        if len(mem) < 5:
            continue
        mem = np.array(mem)
        rr = r1[mem]
        rr = rr[np.isfinite(rr)]
        if len(rr) < 5:
            continue
        vv = np.nan_to_num(v[:, mem], nan=0.0).sum(1)
        vr = vv[-1] / vv[-21:-1].mean() if vv[-21:-1].mean() > 0 else None
        rows.append({"sector": sec, "share": float(turn[:, mem].sum() / mkt) if mkt > 0 else 0.0, "n": int(len(rr)),
                     "ew": float(rr.mean()), "breadth": float((rr <= -0.03).mean()), "vr": _f(vr, 2),
                     "top": [{"id": ids[j], "name": P["names"].get(ids[j], ""), "chg": _f(r1[j], 4)}
                             for j in mem[np.argsort(-np.nan_to_num(turn[-1, mem]))][:5]]})
    rows.sort(key=lambda x: -x["share"])
    for k, r in enumerate(rows):
        r["rank"] = k + 1
        r["crash"] = bool(r["breadth"] >= 0.6 and r["ew"] <= -0.03 and (r["vr"] or 0) >= 1.2)
    main = rows[:5]
    return {"date": P["dates"][-1], "main": main, "crash": [r for r in main if r["crash"]],
            "other_crash": [r for r in rows[5:] if r["crash"]]}


# ── 11 當沖名單 ──────────────────────────────────────────────────────────────
def stock_futures(force: bool = False) -> set:
    """期交所股票期貨標的（每 7 天更新一次，存 course_meta）"""
    c = _conn()
    _init(c)
    r = c.execute("SELECT v FROM course_meta WHERE k='stock_futures'").fetchone()
    c.close()
    if r and not force:
        d = json.loads(r["v"])
        if time.time() - d.get("t", 0) < 7 * 86400 and d.get("ids"):
            return set(d["ids"])
    ids = []
    try:
        import httpx
        t = httpx.get("https://www.taifex.com.tw/cht/2/stockLists", headers=UA, timeout=40, follow_redirects=True).text
        for row in re.findall(r"<tr>(.*?)</tr>", t, re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            if len(tds) >= 6 and "是股票期貨標的" in tds[4]:
                sid = re.sub("<[^>]+>", "", tds[2]).strip()
                if re.fullmatch(r"\d{4}", sid):
                    ids.append(sid)
    except Exception as e:
        log.warning(f"[course] 股票期貨清單: {e}")
    if ids:
        c = _conn()
        c.execute("INSERT OR REPLACE INTO course_meta VALUES ('stock_futures', ?)", (json.dumps({"t": time.time(), "ids": ids}),))
        c.commit()
        c.close()
        return set(ids)
    return set(json.loads(r["v"]).get("ids", [])) if r else set()


def calc_daytrade(P, futs: set, taiex: dict | None = None) -> dict:
    ids = P["ids"]
    c, o, h, l, v = (P[k].astype(float) for k in "cohlv")
    T = len(P["dates"])
    with np.errstate(invalid="ignore", divide="ignore"):
        t20 = np.nanmean((c * v)[-20:], axis=0)
    rank = (-np.nan_to_num(t20, nan=-1)).argsort().argsort()
    out = {"long": [], "short": []}
    for j, sid in enumerate(ids):
        if not (sid in futs or rank[j] < 100):
            continue
        rows, oo, hh, ll, cc, vv = _stock(P, j)
        if len(cc) < 120 or rows[-1] != T - 1 or cc[-1] < 20:
            continue
        pc = cc[-61:-1]
        with np.errstate(invalid="ignore", divide="ignore"):
            if ((np.abs(cc[-60:] / pc - 1) > 0.105) | (np.abs(oo[-60:] / pc - 1) > 0.105)).any():
                continue
            chg = cc[-1] / cc[-2] - 1
            rg = hh[-1] - ll[-1]
            vr = vv[-1] / np.mean(vv[-21:-1])
        hi20, lo20 = cc[-21:-1].max(), cc[-21:-1].min()
        base = {"stock_id": sid, "name": P["names"].get(sid, ""), "close": _f(cc[-1]), "chg": _f(chg, 4), "vol_x": _f(vr, 1),
                "amp": _f(rg / cc[-2], 4), "turnover": _f(cc[-1] * vv[-1] / 1e5, 1), "futures": sid in futs,
                "score": float(cc[-1] * vv[-1] * rg / cc[-2])}
        if chg >= 0.03 and cc[-1] >= hh[-1] - 0.25 * rg and cc[-1] > hi20 and vr >= 1.5:
            out["long"].append(base)
        elif chg <= -0.03 and cc[-1] <= ll[-1] + 0.25 * rg and cc[-1] < lo20 and vr >= 1.5:
            out["short"].append(base)
    for k in out:
        out[k].sort(key=lambda x: -x["score"])
        out[k] = out[k][:DT_TOP]
    mk = None
    if taiex:
        ks = sorted(taiex)
        if len(ks) >= 5:
            last = taiex[ks[-1]]
            ma5 = float(np.mean([taiex[k] for k in ks[-5:]]))
            mk = {"date": ks[-1], "taiex": _f(last), "ma5": _f(ma5), "side": "多" if last > ma5 else "空"}
    return {"date": P["dates"][-1], "market": mk, **out}


# ── 4 漲停打開候選 ───────────────────────────────────────────────────────────
def revenue_lookup(sids: list, day: str) -> dict:
    """{sid: {ym, yoy, cum_yoy}}：day 那天已經公布的最新月營收（次月 13 日起才算數）"""
    ym = C.latest_revenue_ym(day)
    c = _conn()
    _init(c)
    out = {}
    for sid in sids:
        r = c.execute("SELECT ym, yoy, cum_yoy FROM revenue_month WHERE stock_id=? AND ym<=? ORDER BY ym DESC LIMIT 1", (sid, ym)).fetchone()
        if r:
            out[sid] = {"ym": r["ym"], "yoy": r["yoy"], "cum_yoy": r["cum_yoy"]}
    c.close()
    return out


_ROW = re.compile(r"<td align=center>(\d{4})</td><td align=left>[^<]*</td>"
                  r"<td nowrap>([^<]*)</td><td nowrap>([^<]*)</td><td nowrap>([^<]*)</td>"
                  r"<td nowrap>([^<]*)</td><Td nowrap>([^<]*)</td><td nowrap>([^<]*)</td>"
                  r"<td nowrap>([^<]*)</td><td nowrap>([^<]*)</td>", re.I)


def refresh_revenue(day: str | None = None) -> int:
    """公開資訊觀測站月營收彙總表（上市／上櫃 × 國內／國外）：最近 2 個月份，寫進 revenue_month"""
    import httpx
    day = day or datetime.now().strftime("%Y%m%d")
    y, m = int(day[:4]), int(day[4:6])
    months = []
    for back in (1, 2):
        mm, yy = m - back, y
        while mm <= 0:
            mm += 12
            yy -= 1
        months.append((yy, mm))
    n = 0
    c = _conn()
    _init(c)
    with httpx.Client(headers=UA, timeout=60, follow_redirects=True) as cl:
        for yy, mm in months:
            for mkt in ("sii", "otc"):
                for sub in (0, 1):
                    try:
                        t = cl.get(f"https://mopsov.twse.com.tw/nas/t21/{mkt}/t21sc03_{yy - 1911}_{mm}_{sub}.html").content.decode("big5", "ignore")
                    except Exception as e:
                        log.warning(f"[course] 月營收 {yy}{mm:02d} {mkt}: {e}")
                        continue
                    rows = []
                    for g in _ROW.findall(t.replace("\r", "").replace("\n", "")):
                        def num(x):
                            try:
                                return float(str(x).replace(",", "").strip())
                            except ValueError:
                                return None
                        rows.append((f"{yy}{mm:02d}", g[0], num(g[5]), num(g[8])))
                    c.executemany("INSERT OR REPLACE INTO revenue_month VALUES (?,?,?,?)", rows)
                    n += len(rows)
                    time.sleep(1)
    c.commit()
    c.close()
    return n


def calc_limit(P) -> dict:
    T = len(P["dates"])
    cand, opened = [], []
    for j, sid in enumerate(P["ids"]):
        rows, o, h, l, c, v = _stock(P, j)
        if len(c) < 30 or rows[-1] != T - 1:
            continue
        st = C.limit_streak(o, c)
        if st[-1] >= LIMIT_N:
            cand.append({"stock_id": sid, "name": P["names"].get(sid, ""), "streak": int(st[-1]), "close": _f(c[-1]),
                         "limit_next": C.limit_up_price(float(c[-1])), "vol": _f(v[-1], 0)})
        sig, info = C.sig_limit_open(o, h, l, c, v, n=LIMIT_N, m=LIMIT_M, opened="close")
        if sig[-1]:
            opened.append({"stock_id": sid, "name": P["names"].get(sid, ""), "streak": int(info["streak"][-1]), "close": _f(c[-1]),
                           "chg": _f(c[-1] / c[-2] - 1, 4), "vol_x": _f(info["vol_x"][-1], 1), "stop": _f(l[-1])})
    rev = revenue_lookup([x["stock_id"] for x in cand + opened], P["dates"][-1])
    for x in cand + opened:
        x["revenue"] = rev.get(x["stock_id"])
    cand.sort(key=lambda x: -x["streak"])
    return {"date": P["dates"][-1], "candidates": cand, "opened_close": opened}


# ── 10 大盤出貨日 ────────────────────────────────────────────────────────────
def _mi5(day: str):
    import httpx
    try:
        j = httpx.get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_5MINS", params={"date": day, "response": "json"},
                      headers={**UA, "Referer": "https://www.twse.com.tw/"}, timeout=30, verify=False).json()
        rows = j.get("data") or []
        if j.get("stat") != "OK" or not rows:
            return None
        last = rows[-1]
        buy = float(str(last[2]).replace(",", ""))
        deal = float(str(last[6]).replace(",", ""))
        return deal / buy if buy > 0 else None
    except Exception as e:
        log.warning(f"[course] MI_5MINS {day}: {e}")
        return None


def overheat_series(days: list) -> dict:
    """{YYYYMMDD: 過熱指數}：先看自己的表，沒有就抓證交所 MI_5MINS（同一天收盤後才完整，抓到就存）"""
    c = _conn()
    _init(c)
    have = {r["date"]: r["ratio"] for r in c.execute("SELECT date, ratio FROM overheat_daily")}
    c.close()
    today = datetime.now().strftime("%Y%m%d")
    for d in days:
        if d in have:
            continue
        if d == today and datetime.now().hour < 14:
            continue
        r = _mi5(d)
        time.sleep(1.5)
        if r is not None:
            have[d] = r
            c = _conn()
            c.execute("INSERT OR REPLACE INTO overheat_daily VALUES (?,?)", (d, r))
            c.commit()
            c.close()
    return {d: have.get(d) for d in days}


def calc_market(trade_days=None) -> dict:
    """trade_days：價格表的交易日（加權指數表偶爾有週末的假資料，例 2026-10-04 星期日 → 只留真的交易日）"""
    from best_strategy import taiex_series
    s = taiex_series()
    if s is None or len(s) < 60:
        return {"error": "加權指數資料不夠"}
    s = s.sort_index()
    s.index = s.index.astype(str)
    if trade_days:
        td = set(trade_days)
        s = s[[d in td or d > max(td) for d in s.index]]
    s = s[[datetime.strptime(d, "%Y%m%d").weekday() < 5 for d in s.index]]
    if len(s) < 60:
        return {"error": "加權指數資料不夠"}
    days = [str(d) for d in s.index[-40:]]
    oh = overheat_series(days[-10:])
    close = s.to_numpy(float)[-40:]
    ratio = np.array([oh.get(d) if oh.get(d) is not None else np.nan for d in days], float)
    md, brk, dpt = C.market_dist_day(close, ratio, k=MARKET_K, hot=MARKET_HOT)
    recent = [{"date": d, "ratio": _f(oh.get(d), 3)} for d in days[-10:]]
    return {"date": days[-1], "taiex": _f(close[-1]), "d_point": _f(dpt[-1]), "dist_day": bool(md[-1]), "dbreak": bool(brk[-1]),
            "hot5": bool(np.nanmax(np.nan_to_num(ratio[-5:], nan=0)) > MARKET_HOT), "overheat": recent,
            "recent_dist": [days[i] for i in np.nonzero(md)[0]]}


# ── 排程入口 ─────────────────────────────────────────────────────────────────
def nightly(push: bool = True) -> dict:
    """18:00 掃描後：全部算一次、存起來、推播（同一天只推一次）"""
    if not _LOCK.acquire(blocking=False):
        return {"busy": True}
    try:
        t0 = time.time()
        res = {}
        try:
            day = datetime.now().strftime("%Y%m%d")
            if int(day[6:]) <= 16 or not latest("revenue_ok"):
                res["revenue"] = refresh_revenue(day)
                save("revenue_ok", day, {"n": res["revenue"]})
        except Exception as e:
            log.warning(f"[course] 月營收更新失敗: {e}")
        P = load_recent(300)
        if P is None:
            return {"error": "沒有價格資料"}
        day = P["dates"][-1]
        for kind, fn in (("dist", lambda: calc_dist(P)), ("sector", lambda: calc_sector(P)), ("limit", lambda: calc_limit(P))):
            try:
                d = fn()
                save(kind, day, d)
                res[kind] = len(d.get("items", d.get("candidates", d.get("main", []))))
            except Exception as e:
                log.warning(f"[course] {kind}: {e}")
                res[kind] = f"失敗：{e}"
        try:
            from best_strategy import taiex_series
            s = taiex_series()
            tx = {str(k): float(v) for k, v in s.items()} if s is not None else None
            d = calc_daytrade(P, stock_futures(), tx)
            save("daytrade", day, d)
            res["daytrade"] = (len(d["long"]), len(d["short"]))
        except Exception as e:
            log.warning(f"[course] daytrade: {e}")
            res["daytrade"] = f"失敗：{e}"
        try:
            d = calc_market(P["dates"])
            if not d.get("error"):
                save("market", d["date"], d)
            res["market"] = d.get("dist_day", d.get("error"))
        except Exception as e:
            log.warning(f"[course] market: {e}")
            res["market"] = f"失敗：{e}"
        del P
        if push:
            try:
                res["push"] = push_nightly(day)
            except Exception as e:
                log.warning(f"[course] 推播失敗: {e}")
        res["sec"] = round(time.time() - t0, 1)
        log.info(f"[course] nightly {res}")
        return res
    finally:
        _LOCK.release()


def _sent(key: str) -> bool:
    c = _conn()
    r = c.execute("SELECT 1 FROM push_log WHERE stock_id='COURSE' AND signal_title=? AND ok=1 LIMIT 1", (key,)).fetchone()
    c.close()
    return r is not None


def _sent_since(prefix: str, days: int) -> bool:
    c = _conn()
    since = (datetime.now() - timedelta(days=days)).isoformat()
    r = c.execute("SELECT 1 FROM push_log WHERE stock_id='COURSE' AND signal_title LIKE ? AND ok=1 AND pushed_at >= ? LIMIT 1",
                  (prefix + "%", since)).fetchone()
    c.close()
    return r is not None


def _send(key: str, text: str) -> bool:
    import asyncio
    try:
        from server import tg_send
        ok = bool(asyncio.run(tg_send(text)))
    except Exception as e:                            # 推播失敗不影響排程；記 ok=0，下次再試
        log.warning(f"[course] Telegram {key}: {e}")
        ok = False
    c = _conn()
    c.execute("INSERT INTO push_log (stock_id, signal_emoji, signal_title, pushed_at, ok) VALUES (?,?,?,?,?)",
              ("COURSE", "📋", key, datetime.now().isoformat(), 1 if ok else 0))
    c.commit()
    c.close()
    return ok


def _md(d):
    return f"{d[4:6]}/{d[6:8]}"


def push_nightly(day: str) -> dict:
    import html
    out = {}
    # 出貨日：觀察清單（含持有）今天觸發的
    d = latest("dist")
    if d and d.get("date") == day:
        c = _conn()
        wl = {r["stock_id"]: (r["name"], r["cost"]) for r in c.execute("SELECT stock_id, name, cost FROM watchlist")}
        c.close()
        hits = [x for x in d["items"] if x["date"] == day and x["stock_id"] in wl]
        key = f"dist:{day}"
        if hits and not _sent(key):
            lines = [f"⚠ <b>出貨日提醒</b>　{_md(day)}（觀察清單／持有）"]
            for x in hits[:20]:
                hold = "（持有）" if wl[x["stock_id"]][1] else ""
                lines.append(f"• {x['stock_id']} {html.escape(x['name'])}{hold}：{x['type_name']}，{(x['chg'] or 0) * 100:+.1f}%、量 {x['vol_x']} 倍")
            lines.append("講義：高檔下跌出量／量大不漲＝可能出貨。5 年研究結果見網站，這是提醒不是賣出訊號。")
            out["dist"] = _send(key, "\n".join(lines))
    # 主流族群同步大跌
    s = latest("sector")
    if s and s.get("date") == day:
        for r in s.get("crash", []):
            key = f"sector:{r['sector']}:{day}"
            if _sent_since(f"sector:{r['sector']}:", 7) or _sent(key):
                continue
            txt = (f"📉 <b>主流族群同步大跌</b>　{_md(day)}\n{html.escape(r['sector'])}（成交金額第 {r['rank']} 名）"
                   f"等權 {r['ew'] * 100:+.1f}%、{r['breadth'] * 100:.0f}% 成員跌 ≥ 3%、量 {r['vr']} 倍\n"
                   + "、".join(f"{t['id']} {html.escape(t['name'])} {(t['chg'] or 0) * 100:+.1f}%" for t in r["top"][:5]))
            out[f"sector:{r['sector']}"] = _send(key, txt)
    # 大盤出貨日
    m = latest("market")
    if m and m.get("dist_day") and m.get("date") == day:
        key = f"market:{day}"
        if not _sent(key) and not _sent_since("market:", 14):
            oh = [x for x in m["overheat"] if x["ratio"] is not None]
            txt = (f"🚨 <b>大盤出貨日</b>　{_md(day)}\n加權 {m['taiex']} 收盤跌破 d 點 {m['d_point']}，"
                   f"最近 5 天過熱指數最高 {max(x['ratio'] for x in oh[-5:]) if oh else '—'}（> {MARKET_HOT}）\n"
                   "講義：過熱＋跌破 d 點＝出貨日，減碼／避險。研究結果見網站（樣本很少）。")
            out["market"] = _send(key, txt)
    return out


def push_premarket() -> dict:
    """08:30：今天的當沖多空名單＋漲停打開候選（前一晚算好的）"""
    import html
    today = datetime.now().strftime("%Y%m%d")
    d = latest("daytrade", before=today)
    lim = latest("limit", before=today)
    if not d:
        return {"sent": False}
    key = f"premarket:{today}"
    if _sent(key):
        return {"sent": False, "dup": True}
    mk = d.get("market") or {}
    lines = [f"⚡ <b>盤前當沖名單</b>　{_md(today)}（{_md(d['date'])} 收盤算）",
             f"加權 {mk.get('taiex', '—')}，在 5 日線{'上 → 順勢偏多' if mk.get('side') == '多' else '下 → 順勢偏空' if mk.get('side') else '—'}"]
    for side, lab in (("long", "🔴 多（剛起漲）"), ("short", "🟢 空（剛起跌）")):
        xs = d.get(side) or []
        lines.append(lab + "：" + ("、".join(f"{x['stock_id']} {html.escape(x['name'])}{'⁽期⁾' if x.get('futures') else ''}" for x in xs) if xs else "無"))
    if lim and lim.get("candidates"):
        lines.append("🚪 漲停打開候選（盤中打開會再通知）：" + "、".join(
            f"{x['stock_id']} {html.escape(x['name'])} 連{x['streak']}" for x in lim["candidates"][:10]))
    lines.append("研究：日線代理回測見網站；當沖守紀律：進場同時設停損、單日虧損 ≤ 資金 2%。")
    return {"sent": _send(key, "\n".join(lines))}


# ── 盤中：漲停打開偵測 ───────────────────────────────────────────────────────
_LIVE = {"day": None, "opened": {}, "checked": None, "cands": 0}


def limit_tick(now: datetime | None = None, quotes_fn=None, push: bool = True) -> list:
    """盤中每分鐘：候選（昨天收盤為止連續 ≥ 2 天跳空漲停）現價 < 今天漲停價、累計量 ≥ 昨量 × 3 → 打開"""
    now = now or datetime.now()
    hm = now.hour * 100 + now.minute
    if now.weekday() >= 5 or not (900 <= hm <= 1335):
        return []
    today = now.strftime("%Y%m%d")
    if _LIVE["day"] != today:
        _LIVE.update(day=today, opened={})
    lim = latest("limit", before=today)
    cands = (lim or {}).get("candidates") or []
    _LIVE["cands"] = len(cands)
    if not cands:
        return []
    if quotes_fn is None:
        from yahoo_price import _prefetch_rt_for_scan as quotes_fn
    q = quotes_fn([x["stock_id"] for x in cands], today)
    _LIVE["checked"] = now.strftime("%H:%M")
    new = []
    for x in cands:
        b = q.get(x["stock_id"])
        if not b or x["stock_id"] in _LIVE["opened"] or not (x.get("close") or 0) > 0 or not x.get("limit_next"):
            continue
        lim_px = x["limit_next"]
        tick = C.tick_size(lim_px)
        yv = x.get("vol") or 0
        if b["close"] < lim_px - tick * 0.5 and yv > 0 and b["volume"] >= LIMIT_M * yv:
            ev = {**x, "time": now.strftime("%H:%M"), "price": b["close"], "low": b["low"], "vol_now": b["volume"],
                  "vol_x": round(b["volume"] / yv, 1), "chg": round(b["close"] / x["close"] - 1, 4)}
            _LIVE["opened"][x["stock_id"]] = ev
            new.append(ev)
    if push:
        import html
        for ev in new:
            key = f"limitopen:{today}:{ev['stock_id']}"
            if _sent(key):
                continue
            rv = ev.get("revenue") or {}
            yoy = f"月營收年增 {rv['yoy']:+.0f}%（{rv['ym'][4:]}月）" if rv.get("yoy") is not None else "月營收：查無"
            good = rv.get("yoy") is not None and rv["yoy"] >= 20
            txt = (f"🚪 <b>漲停打開</b>　{ev['time']}\n{ev['stock_id']} {html.escape(ev['name'])}：連 {ev['streak']} 天跳空漲停後爆量打開\n"
                   f"現價 {ev['price']}（{ev['chg'] * 100:+.1f}%，漲停 {ev['limit_next']}）、量 {ev['vol_x']} 倍、今天最低 {ev['low']}\n"
                   f"{yoy}{'' if good else '　⚠ 業績前提不成立，先確認有沒有真利多'}\n"
                   "講義：真利多＋爆量打開＝小金額短線；停損＝打開當天最低。")
            _send(key, txt)
    return new


def live_status() -> dict:
    return {"day": _LIVE["day"], "checked": _LIVE["checked"], "candidates": _LIVE["cands"], "opened": list(_LIVE["opened"].values())}
