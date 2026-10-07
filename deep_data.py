"""
deep_data.py — 深度分析的資料來源（PLAN-DEEP2 §4，2026-10-07）

以前的問題：本益比／籌碼靠 FinMind（免費額度常用完回 402）、財務用錯 dataset 名稱（永遠失敗）、
市值／Beta 靠 Yahoo quoteSummary（從 Fly 要 crumb，一律失敗）、FinMind 法人名稱是英文卻用中文比對（永遠對不上）。

現在：
- 官方整包表（免 token）：本益比、月營收、最新一季綜合損益、公司基本資料（上市 TWSE openapi／上櫃 TPEX openapi）
  模組層快取（本益比 3 小時、其他 12 小時），網路錯誤重試 1 次，失敗沿用上一份成功的表、沒有就負快取 10 分鐘
- 三大法人／融資融券：chip_course 每天累積的 inst_daily／margin_bal（掃描時更新）；該股不到 5 天才用 FinMind 備援
- 近 8 季 EPS：FinMind TaiwanStockFinancialStatements（選配，快取 24 小時，額度用完就不顯示）
所有函式都是同步的（server 用 asyncio.to_thread 呼叫），失敗回 None，不丟例外。
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import statistics
import threading
import time
from datetime import date, datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)
_TW = timezone(timedelta(hours=8))
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "application/json"}
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")

H3, H12 = 3 * 3600, 12 * 3600
# name: (url, ttl 秒, 代號欄, 必要欄)
TABLES = {
    "pe_twse":  ("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL", H3, "Code", "PEratio"),
    "pe_tpex":  ("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis", H3,
                 "SecuritiesCompanyCode", "PriceEarningRatio"),
    "rev_twse": ("https://openapi.twse.com.tw/v1/opendata/t187ap05_L", H12, "公司代號", "營業收入-當月營收"),
    "rev_tpex": ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O", H12, "公司代號", "營業收入-當月營收"),
    "inc_twse": ("https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci", H12, "公司代號", "基本每股盈餘（元）"),
    "inc_tpex": ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci", H12,
                 "SecuritiesCompanyCode", "基本每股盈餘（元）"),
    "co_twse":  ("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", H12, "公司代號", "已發行普通股數或TDR原股發行股數"),
    "co_tpex":  ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", H12, "SecuritiesCompanyCode", "IssueShares"),
}
NEG_TTL = 600
_cache: dict = {}            # name -> {"t": 抓到的時間, "idx": {sid: row}, "fail_t": 最近失敗時間}
_locks = {k: threading.Lock() for k in TABLES}


def num(v):
    """'1,234.5' → 1234.5；空字串、'-'、'N/A' → None"""
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _get_json(url: str):
    last = None
    for attempt in range(2):
        try:
            with httpx.Client(timeout=40.0, verify=False, follow_redirects=True, headers=_UA) as c:
                r = c.get(url)
                r.raise_for_status()
                return r.json()
        except Exception as e:      # noqa: BLE001
            last = e
            if attempt == 0:
                time.sleep(2)
    raise last


def build_index(rows, code_key: str, need_key: str) -> dict:
    """[{...}] → {sid: row}；必要欄名不在 → ValueError（官方改欄位時沿用上一份）"""
    if not isinstance(rows, list) or not rows:
        raise ValueError("empty")
    if code_key not in rows[0] or need_key not in rows[0]:
        raise ValueError(f"missing field {need_key}")
    return {str(r.get(code_key) or "").strip(): r for r in rows if r.get(code_key)}


def table(name: str, fresh: bool = False) -> dict:
    """官方整包表 {sid: row}；抓不到時回上一份成功的（可能是舊的），完全沒有回 {}"""
    url, ttl, code_key, need_key = TABLES[name]
    now = time.time()
    ent = _cache.get(name) or {}
    age = now - ent.get("t", 0)
    want = (not ent.get("idx")) or age > ttl or (fresh and age > 1800)
    if not want or now - ent.get("fail_t", 0) < NEG_TTL and ent.get("fail_t", 0) > ent.get("t", 0):
        return ent.get("idx") or {}
    with _locks[name]:
        ent = _cache.get(name) or {}
        if ent.get("idx") and time.time() - ent.get("t", 0) < min(ttl, 60):
            return ent["idx"]            # 別的執行緒剛抓完
        try:
            idx = build_index(_get_json(url), code_key, need_key)
            _cache[name] = {"t": time.time(), "idx": idx}
        except Exception as e:           # noqa: BLE001
            log.warning(f"[deep_data] {name}: {type(e).__name__} {e}")
            _cache[name] = {**ent, "fail_t": time.time()}
    return (_cache.get(name) or {}).get("idx") or {}


def _row(kind: str, sid: str, market: str, fresh: bool = False):
    """先查該股市場的表，查不到再查另一個市場（市場別有時不準）"""
    order = ("tpex", "twse") if market == "tpex" else ("twse", "tpex")
    for m in order:
        r = table(f"{kind}_{m}", fresh).get(sid)
        if r:
            return r, m
    return None, None


def roc_date(s) -> str | None:
    """'1151006' → '2026-10-06'；'11508' → '2026-08'"""
    s = str(s or "").strip()
    if len(s) == 7 and s.isdigit():
        return f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:]}"
    if len(s) == 5 and s.isdigit():
        return f"{int(s[:3]) + 1911}-{s[3:5]}"
    return None


def is_etf(sid: str) -> bool:
    return sid.startswith("00")


# ── 估值 ─────────────────────────────────────────────────────────────────────

def _pe_of(r: dict, m: str):
    if m == "twse":
        return num(r.get("PEratio")), num(r.get("PBratio")), num(r.get("DividendYield")), roc_date(r.get("Date"))
    return (num(r.get("PriceEarningRatio")), num(r.get("PriceBookRatio")), num(r.get("YieldRatio")),
            roc_date(r.get("Date")))


def peer_ids(sid: str) -> tuple:
    """(產業名稱, [同產業股票代號])，用 sector.db 的分類（產業輪動同一套）"""
    try:
        from sector.db import SECTOR_DB_PATH
        c = sqlite3.connect(str(SECTOR_DB_PATH), timeout=5.0)
        r = c.execute("SELECT m.sector_id, s.sector_name FROM stock_sector_map m LEFT JOIN sector_master s "
                      "USING(sector_id) WHERE m.stock_id=? ORDER BY m.effective_date DESC LIMIT 1", (sid,)).fetchone()
        if not r:
            c.close()
            return None, []
        peers = [x[0] for x in c.execute("SELECT DISTINCT stock_id FROM stock_sector_map WHERE sector_id=?", (r[0],))]
        c.close()
        return r[1] or r[0], peers
    except Exception:
        return None, []


def peer_pe_median(peers, fresh: bool = False) -> tuple:
    """(同產業本益比中位數, 檔數)；PE>0 的不到 5 檔回 (None, n)"""
    pes = []
    for p in peers:
        r, m = _row("pe", p, "twse", fresh)
        if r:
            pe = _pe_of(r, m)[0]
            if pe and pe > 0:
                pes.append(pe)
    if len(pes) < 5:
        return None, len(pes)
    return round(statistics.median(pes), 2), len(pes)


def valuation(sid: str, price: float | None, market: str = "twse", fresh: bool = False) -> dict:
    if is_etf(sid):
        return {"etf": True}
    out = {"etf": False}
    r, m = _row("pe", sid, market, fresh)
    if r:
        pe, pb, dy, d = _pe_of(r, m)
        out.update(per=pe if pe and pe > 0 else None, per_raw=pe, pbr=pb, dividend_yield=dy, date=d, source=m)
    co, cm = _row("co", sid, market, fresh)
    if co:
        cap = num(co.get("實收資本額") if cm == "twse" else co.get("Paidin.Capital.NTDollars"))
        sh = num(co.get("已發行普通股數或TDR原股發行股數") if cm == "twse" else co.get("IssueShares"))
        if cap:
            out["capital"] = round(cap / 1e8, 2)                        # 億元
        if sh:
            out["shares"] = round(sh / 1e8, 3)                          # 億股
            name = str(co.get("公司簡稱") or co.get("CompanyAbbreviation") or "")
            if price and price > 0 and not name.endswith("DR"):
                out["market_cap"] = round(price * sh / 1e8, 1)           # 億元
    sector, peers = peer_ids(sid)
    out["sector_name"] = sector
    if peers:
        med, n = peer_pe_median(peers, fresh)
        out["peer_pe_median"], out["peer_n"] = med, n
        if med and out.get("per"):
            out["pe_vs_peer"] = round(out["per"] / med, 2)
    return out


# ── 月營收／綜合損益 ─────────────────────────────────────────────────────────

def revenue(sid: str, market: str = "twse", fresh: bool = False) -> dict | None:
    if is_etf(sid):
        return None
    r, m = _row("rev", sid, market, fresh)
    if not r:
        return None
    return {
        "ym": roc_date(r.get("資料年月")),
        "revenue": num(r.get("營業收入-當月營收")),                     # 千元
        "mom": _r1(num(r.get("營業收入-上月比較增減(%)"))),
        "yoy": _r1(num(r.get("營業收入-去年同月增減(%)"))),
        "ytd": num(r.get("累計營業收入-當月累計營收")),
        "ytd_yoy": _r1(num(r.get("累計營業收入-前期比較增減(%)"))),
        "note": (str(r.get("備註") or "").strip() if str(r.get("備註") or "").strip() not in ("-", "") else None),
    }


def _r1(x):
    return round(x, 1) if x is not None else None


def income(sid: str, market: str = "twse", fresh: bool = False) -> dict | None:
    """最新一季（今年累計）綜合損益；金融保險業用別的格式，查不到回 None"""
    if is_etf(sid):
        return None
    r, m = _row("inc", sid, market, fresh)
    if not r:
        return None
    rev = num(r.get("營業收入"))
    gp = num(r.get("營業毛利（毛損）淨額")) or num(r.get("營業毛利（毛損）"))
    op = num(r.get("營業利益（損失）"))
    ni = num(r.get("淨利（淨損）歸屬於母公司業主")) or num(r.get("本期淨利（淨損）"))
    year = int(num(r.get("年度") if m == "twse" else r.get("Year")) or 0) + 1911
    season = int(num(r.get("季別") if m == "twse" else r.get("Season")) or 0)
    pct = lambda a: round(a / rev * 100, 1) if a is not None and rev else None   # noqa: E731
    return {"year": year, "season": season, "revenue": rev, "gross_margin": pct(gp), "op_margin": pct(op),
            "net_margin": pct(ni), "eps": num(r.get("基本每股盈餘（元）")),
            "label": f"{year} 年前 {season} 季累計" if season > 1 else f"{year} 年第 1 季"}


# ── FinMind（備援／選配）──────────────────────────────────────────────────────

_fm_cache: dict = {}         # (dataset, sid) -> (t, data or None)


def _finmind(dataset: str, sid: str, start: str, ttl: int, fresh: bool = False):
    key = (dataset, sid)
    hit = _fm_cache.get(key)
    if hit and not fresh:
        t, data = hit
        if (data is not None and time.time() - t < ttl) or (data is None and time.time() - t < NEG_TTL):
            return data
    data = None
    try:
        r = httpx.get("https://api.finmindtrade.com/api/v4/data",
                      params={"dataset": dataset, "data_id": sid, "start_date": start, "token": FINMIND_TOKEN},
                      timeout=15.0)
        j = r.json()
        if r.status_code == 200 and isinstance(j.get("data"), list) and j["data"]:
            data = j["data"]
        else:
            log.warning(f"[deep_data] FinMind {dataset} {sid}: {r.status_code} {str(j.get('msg'))[:80]}")
    except Exception as e:   # noqa: BLE001
        log.warning(f"[deep_data] FinMind {dataset} {sid}: {type(e).__name__}")
    _fm_cache[key] = (time.time(), data)
    return data


# FinMind 法人名稱是英文（chip_tracker_v2 同一套對照）；外資不含外資自營商、自營＝自行＋避險，跟 T86 一致
_FM_NAMES = {"Foreign_Investor": 0, "Investment_Trust": 1, "Dealer_self": 2, "Dealer_Hedging": 2}


def finmind_inst(rows) -> list:
    """FinMind TaiwanStockInstitutionalInvestorsBuySell → [(YYYY-MM-DD, 外資, 投信, 自營)]（股），舊→新"""
    by = {}
    for x in rows or []:
        i = _FM_NAMES.get(x.get("name"))
        d = str(x.get("date") or "")[:10]
        if i is None or not d:
            continue
        b, s = num(x.get("buy")) or 0.0, num(x.get("sell")) or 0.0
        by.setdefault(d, [0.0, 0.0, 0.0])[i] += b - s
    return [(d, *v) for d, v in sorted(by.items())]


def eps_history(sid: str, fresh: bool = False) -> dict | None:
    """FinMind TaiwanStockFinancialStatements（type=EPS，單季）→ 近 8 季、最新一季 YoY、近四季合計"""
    if is_etf(sid):
        return None
    start = (datetime.now(_TW).date() - timedelta(days=800)).isoformat()
    rows = _finmind("TaiwanStockFinancialStatements", sid, start, 24 * 3600, fresh)
    if not rows:
        return None
    q = {}
    for x in rows:
        if x.get("type") == "EPS":
            v = num(x.get("value"))
            d = str(x.get("date") or "")[:10]
            if v is not None and len(d) == 10:
                q[d] = v
    if not q:
        return None
    ds = sorted(q)[-8:]
    out = {"quarters": [{"q": f"{d[:4]}Q{(int(d[5:7]) - 1) // 3 + 1}", "eps": q[d]} for d in ds]}
    if len(ds) >= 4:
        out["ttm"] = round(sum(q[d] for d in ds[-4:]), 2)
    if len(ds) >= 5 and q[ds[-5]]:
        out["eps_yoy"] = round((q[ds[-1]] - q[ds[-5]]) / abs(q[ds[-5]]) * 100, 1)
    return out


# ── 籌碼 ─────────────────────────────────────────────────────────────────────

def _streak(vals) -> int:
    """最後連續同號天數：+3＝連買 3 天、−2＝連賣 2 天、0＝最後一天是 0"""
    n, sign = 0, 0
    for v in reversed(vals):
        s = (v > 0) - (v < 0)
        if s == 0 or (sign and s != sign):
            break
        sign, n = s, n + 1
    return n * sign


def chip(sid: str, fresh: bool = False) -> dict:
    """三大法人近 20 日＋融資融券；回 {"error": ...} 表示沒資料"""
    import chip_course
    ser = chip_course.inst_series(sid, 20)
    source = "證交所／櫃買每日（本機）"
    if len(ser) < 5:
        start = (datetime.now(_TW).date() - timedelta(days=45)).isoformat()
        fm = finmind_inst(_finmind("TaiwanStockInstitutionalInvestorsBuySell", sid, start, 6 * 3600, fresh))[-20:]
        if len(fm) >= len(ser) and fm:
            ser, source = fm, "FinMind"
    if not ser:
        return {"error": "沒有法人買賣資料（本機還沒累積、FinMind 額度用完或沒有這檔）"}
    lots = [(d, f / 1000, t / 1000, de / 1000) for d, f, t, de in ser]
    out = {"source": source, "date": lots[-1][0], "days": len(lots),
           "daily": [{"date": d, "foreign": round(f), "trust": round(t), "dealer": round(de)} for d, f, t, de in lots[-10:]]}
    for i, k in enumerate(("foreign", "trust", "dealer"), start=1):
        vals = [x[i] for x in lots]
        out[k] = {"d1": round(vals[-1]), "d5": round(sum(vals[-5:])), "d20": round(sum(vals)), "streak": _streak(vals)}
    ms = chip_course.margin_series(sid, 6)
    if ms:
        last, first = ms[-1], ms[0]
        out["margin"] = {"date": last[0], "margin": last[1], "short": last[2],
                         "margin_chg": (last[1] - first[1]) if last[1] is not None and first[1] is not None else None,
                         "short_chg": (last[2] - first[2]) if last[2] is not None and first[2] is not None else None,
                         "span": len(ms) - 1}
    return out


def clear_stock_cache(sid: str):
    """🔄 fresh：清掉這檔的 FinMind 快取"""
    for k in [k for k in _fm_cache if k[1] == sid]:
        _fm_cache.pop(k, None)
