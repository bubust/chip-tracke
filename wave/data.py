"""B74 資料層（PLAN-B74 §3）：chip_data/wave.db（持久磁碟）
- idx_daily：TWII、SOX、IXIC、GSPC、N225、KS11、TWD 日 K。初次 Yahoo 2000 起；加權 Yahoo 失敗 → 證交所 MI_5MINS_HIST 每月回補
- 每天：Yahoo 近 25 天；加權最近 2 個月用證交所官方開高低收覆蓋；只存「收完」的 K 棒（市場還沒收盤的今天那根不存）
- mkt_chips：FinMind 外資／投信／自營（億元）、外資台指期淨未平倉（口）、融資金額（億元）；
  FinMind 失敗 → 外資現貨用證交所 BFI82U、期貨用總經面板已抓的 FOREIGN_FUTURES_NET；融資沒有備援（照實標暫缺）
- src_status：每個來源上次成功時間、連續失敗次數（連續 ≥2 次寫 log 警告）
- B80：vol5（加權 5 分 K 成交金額，證交所 MI_5MINS）、turnover（每日成交金額，FMTQIK）—— 抓取在 wave/voldata.py"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd

from .features import chips_from_finmind

log = logging.getLogger(__name__)
DB_PATH = Path(__file__).resolve().parent.parent / "chip_data" / "wave.db"
TW = timezone(timedelta(hours=8))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
SYMS = {"TWII": "^TWII", "SOX": "^SOX", "IXIC": "^IXIC", "GSPC": "^GSPC", "N225": "^N225", "KS11": "^KS11", "TWD": "TWD=X"}
SYM_NAME = {"TWII": "加權指數", "SOX": "費城半導體", "IXIC": "那斯達克", "GSPC": "S&P 500", "N225": "日經 225",
            "KS11": "韓國 KOSPI", "TWD": "美元/台幣"}
BACKFILL_START = 946684800      # 2000-01-01
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS idx_daily (sym TEXT, date TEXT, o REAL, h REAL, l REAL, c REAL, v REAL, src TEXT,
    PRIMARY KEY (sym, date));
CREATE TABLE IF NOT EXISTS mkt_chips (date TEXT PRIMARY KEY, f_net REAL, t_net REAL, d_net REAL, fut_f_oi REAL,
    margin_amt REAL, opt_f_net REAL, src TEXT);
CREATE TABLE IF NOT EXISTS wave_snapshot (day TEXT, kind TEXT, created_at TEXT, json TEXT, PRIMARY KEY (day, kind));
CREATE TABLE IF NOT EXISTS ai_panel (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, created_at TEXT, ok INTEGER, json TEXT);
CREATE TABLE IF NOT EXISTS ai_usage (day TEXT, model TEXT, tokens INTEGER, PRIMARY KEY (day, model));
CREATE TABLE IF NOT EXISTS src_status (src TEXT PRIMARY KEY, last_ok TEXT, fails INTEGER DEFAULT 0, last_err TEXT, last_try TEXT);
CREATE TABLE IF NOT EXISTS fut_daily (date TEXT, sess TEXT, contract TEXT, o REAL, h REAL, l REAL, c REAL, v REAL, oi REAL,
    ref_close REAL, src TEXT, PRIMARY KEY (date, sess));
CREATE TABLE IF NOT EXISTS fut_settle (date TEXT PRIMARY KEY, settle REAL, src TEXT);
CREATE TABLE IF NOT EXISTS credit_keep (date TEXT PRIMARY KEY, keep REAL, below_acc REAL, call_acc REAL, call_amt REAL, exe_acc REAL,
    exe_amt REAL, credit_acc REAL, credit_rate REAL, crd_amt REAL);
CREATE TABLE IF NOT EXISTS sbl_stock (date TEXT, sid TEXT, mkt TEXT, name TEXT, prev REAL, sell REAL, ret REAL, adj REAL, bal REAL,
    PRIMARY KEY (date, sid));
CREATE TABLE IF NOT EXISTS bars5 (sym TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL, src TEXT, PRIMARY KEY (sym, ts));
CREATE TABLE IF NOT EXISTS fut_chips (date TEXT PRIMARY KEY, mtx_oi REAL, mtx_inst_long REAL, mtx_inst_short REAL,
    retail_ratio REAL, opt_f_bull REAL, src TEXT);
CREATE TABLE IF NOT EXISTS vol5 (sym TEXT, ts INTEGER, v REAL, src TEXT, PRIMARY KEY (sym, ts));
CREATE TABLE IF NOT EXISTS turnover (date TEXT PRIMARY KEY, amt REAL, shares REAL, src TEXT);
"""


@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as c:
        c.executescript(SCHEMA)


def tw_now() -> datetime:
    return datetime.now(TW)


# ── 來源健康 ─────────────────────────────────────────────────────────────────
def mark(src: str, ok: bool, err: str = ""):
    now = tw_now().strftime("%Y-%m-%d %H:%M")
    try:
        with db() as c:
            row = c.execute("SELECT fails FROM src_status WHERE src=?", (src,)).fetchone()
            fails = 0 if ok else (row["fails"] if row else 0) + 1
            if ok:
                c.execute("INSERT INTO src_status(src,last_ok,fails,last_err,last_try) VALUES(?,?,0,'',?) "
                          "ON CONFLICT(src) DO UPDATE SET last_ok=excluded.last_ok, fails=0, last_err='', last_try=excluded.last_try",
                          (src, now, now))
            else:
                c.execute("INSERT INTO src_status(src,last_ok,fails,last_err,last_try) VALUES(?,NULL,?,?,?) "
                          "ON CONFLICT(src) DO UPDATE SET fails=?, last_err=?, last_try=?",
                          (src, fails, err[:200], now, fails, err[:200], now))
        if not ok and fails >= 2:
            log.warning(f"[wave] 資料來源 {src} 連續失敗 {fails} 次：{err[:120]}")
    except Exception as e:     # noqa: BLE001
        log.warning(f"[wave] 記錄來源狀態失敗 {src}: {e}")


def status() -> list:
    with db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM src_status ORDER BY src").fetchall()]


# ── Yahoo ────────────────────────────────────────────────────────────────────
def parse_yahoo(j: dict, now_ts: Optional[float] = None) -> list:
    """Yahoo chart JSON → [(date, o, h, l, c, v)]；市場還沒收盤的今天那根丟掉（只存收完的）"""
    r = j["chart"]["result"][0]
    m = r.get("meta") or {}
    off = int(m.get("gmtoffset") or 0)
    q = (r.get("indicators", {}).get("quote") or [{}])[0]
    ts = r.get("timestamp") or []
    now_ts = time.time() if now_ts is None else now_ts
    reg = ((m.get("currentTradingPeriod") or {}).get("regular") or {})
    end = reg.get("end")
    today_local = datetime.fromtimestamp(now_ts + off, timezone.utc).strftime("%Y-%m-%d")
    out = []
    for i, t in enumerate(ts):
        c = (q.get("close") or [None])[i] if i < len(q.get("close") or []) else None
        if c is None:
            continue
        d = datetime.fromtimestamp(t + off, timezone.utc).strftime("%Y-%m-%d")
        g = lambda k: (q.get(k) or [None] * len(ts))[i]
        out.append((d, g("open"), g("high"), g("low"), float(c), g("volume")))
    if out and out[-1][0] == today_local and end and now_ts < float(end):
        out = out[:-1]                       # 今天還沒收盤
    # 同一天只留最後一筆
    dd = {}
    for row in out:
        dd[row[0]] = row
    return [dd[k] for k in sorted(dd)]


def fetch_yahoo(sym: str, period1: int, get=None) -> list:
    get = get or (lambda url, params: httpx.get(url, params=params, headers=UA, timeout=40, follow_redirects=True))
    last = None
    for host in ("query1", "query2"):
        try:
            r = get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{SYMS[sym]}",
                    {"interval": "1d", "period1": period1, "period2": int(time.time()) + 86400})
            rows = parse_yahoo(r.json())
            if rows:
                return rows
            last = "空資料"
        except Exception as e:     # noqa: BLE001
            last = repr(e)[:150]
    raise RuntimeError(f"Yahoo {sym}: {last}")


def save_idx(sym: str, rows: list, src: str):
    with db() as c:
        c.executemany("INSERT INTO idx_daily(sym,date,o,h,l,c,v,src) VALUES(?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(sym,date) DO UPDATE SET o=excluded.o,h=excluded.h,l=excluded.l,c=excluded.c,"
                      "v=COALESCE(excluded.v, idx_daily.v),src=excluded.src",
                      [(sym, d, o, h, l, cl, v, src) for d, o, h, l, cl, v in rows])


# ── 證交所加權（官方開高低收）────────────────────────────────────────────────
def parse_twse_hist(j: dict) -> list:
    """MI_5MINS_HIST → [(date, o, h, l, c, None)]；日期是民國 115/10/20"""
    out = []
    if not isinstance(j, dict) or j.get("stat") != "OK":
        return out
    num = lambda s: float(str(s).replace(",", ""))
    for row in j.get("data") or []:
        try:
            y, m, d = str(row[0]).split("/")
            out.append((f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}", num(row[1]), num(row[2]), num(row[3]), num(row[4]), None))
        except Exception:     # noqa: BLE001
            continue
    return out


def fetch_twse_month(ym: date, get=None) -> list:
    get = get or (lambda url, params: httpx.get(url, params=params, headers={**UA, "Referer": "https://www.twse.com.tw/"}, timeout=20))
    r = get("https://www.twse.com.tw/indicesReport/MI_5MINS_HIST", {"date": ym.strftime("%Y%m01"), "response": "json"})
    return parse_twse_hist(r.json())


def update_twse_official(months: int = 2) -> int:
    today = tw_now().date()
    n = 0
    try:
        for k in range(months):
            y, m = today.year, today.month - k
            while m <= 0:
                y, m = y - 1, m + 12
            rows = fetch_twse_month(date(y, m, 1))
            # 今天盤中官方表不會有今天；有的話一定是收盤後
            save_idx("TWII", rows, "TWSE")
            n += len(rows)
            time.sleep(1)
        mark("twse_hist", True)
    except Exception as e:     # noqa: BLE001
        mark("twse_hist", False, repr(e))
    return n


def backfill_twii_twse(start_year: int = 2000):
    """Yahoo 拿不到加權時：證交所每個月一個請求回補（間隔 3 秒）"""
    today = tw_now().date()
    y, m = start_year, 1
    while (y, m) <= (today.year, today.month):
        try:
            save_idx("TWII", fetch_twse_month(date(y, m, 1)), "TWSE")
        except Exception as e:     # noqa: BLE001
            log.warning(f"[wave] 證交所回補 {y}-{m:02d} 失敗：{e}")
        time.sleep(3)
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)


def count_idx(sym: str) -> int:
    with db() as c:
        return c.execute("SELECT COUNT(*) FROM idx_daily WHERE sym=?", (sym,)).fetchone()[0]


def ensure_history(background: bool = True):
    """沒有歷史就回補（Yahoo 2000 起；加權失敗改證交所）"""
    need = [s for s in SYMS if count_idx(s) < 500]
    if not need:
        return False

    def _run():
        for s in need:
            try:
                save_idx(s, fetch_yahoo(s, BACKFILL_START), "YAHOO")
                mark(f"yahoo_{s}", True)
            except Exception as e:     # noqa: BLE001
                mark(f"yahoo_{s}", False, repr(e))
                if s == "TWII":
                    backfill_twii_twse()
            time.sleep(1)
    if background:
        threading.Thread(target=_run, daemon=True).start()
    else:
        _run()
    return True


def update_indices(days: int = 25):
    p1 = int(time.time()) - days * 86400
    for s in SYMS:
        try:
            save_idx(s, fetch_yahoo(s, p1), "YAHOO")
            mark(f"yahoo_{s}", True)
        except Exception as e:     # noqa: BLE001
            mark(f"yahoo_{s}", False, repr(e))
        time.sleep(0.5)
    update_twse_official(2)


# ── 籌碼 ─────────────────────────────────────────────────────────────────────
def _finmind(dataset: str, start: str, **kw) -> pd.DataFrame:
    tok = os.environ.get("FINMIND_TOKEN", "")
    # 金鑰放標頭（B75：放網址參數會被 httpx 的 log 印出來）
    r = httpx.get("https://api.finmindtrade.com/api/v4/data", params={"dataset": dataset, "start_date": start, **kw},
                  headers={"Authorization": f"Bearer {tok}"} if tok else None, timeout=60)
    j = r.json()
    if j.get("status") != 200:
        raise RuntimeError(f"{dataset}: {j.get('msg')}")
    return pd.DataFrame(j.get("data") or [])


def save_chips(df: pd.DataFrame, src: str):
    if df is None or df.empty:
        return 0
    cols = ["f_net", "t_net", "d_net", "fut_f_oi", "margin_amt"]
    rows = []
    for r in df.to_dict("records"):
        vals = [None if pd.isna(r.get(k)) else float(r.get(k)) for k in cols]
        rows.append((str(r["date"])[:10], *vals, src))
    with db() as c:
        # 只覆蓋有值的欄位（不同來源補不同欄）
        for d, *v, s in rows:
            c.execute("INSERT INTO mkt_chips(date) VALUES(?) ON CONFLICT(date) DO NOTHING", (d,))
            for k, x in zip(cols, v):
                if x is not None:
                    c.execute(f"UPDATE mkt_chips SET {k}=?, src=? WHERE date=?", (x, s, d))
    return len(rows)


def update_chips(days: int = 12, full: bool = False):
    start = "2016-01-01" if full else (tw_now().date() - timedelta(days=days)).strftime("%Y-%m-%d")
    inst = fut = mg = None
    try:
        inst = _finmind("TaiwanStockTotalInstitutionalInvestors", start)
        mark("finmind_inst", True)
    except Exception as e:     # noqa: BLE001
        mark("finmind_inst", False, repr(e))
    try:
        fut = _finmind("TaiwanFuturesInstitutionalInvestors", "2018-06-01" if full else start, data_id="TX")
        mark("finmind_fut", True)
    except Exception as e:     # noqa: BLE001
        mark("finmind_fut", False, repr(e))
    try:
        mg = _finmind("TaiwanStockTotalMarginPurchaseShortSale", start)
        mark("finmind_margin", True)
    except Exception as e:     # noqa: BLE001
        mark("finmind_margin", False, repr(e))
    df = chips_from_finmind(inst, fut, mg)
    n = save_chips(df, "FINMIND")
    if inst is None or inst.empty:
        n += _fallback_bfi82u(days)
    if fut is None or fut.empty:
        n += _fallback_regime_futures(days)
    return n


def parse_bfi82u(j: dict) -> Optional[float]:
    """證交所 BFI82U 三大法人買賣金額 → 外資（含外資自營商）買賣差額（億元）"""
    if not isinstance(j, dict) or j.get("stat") != "OK":
        return None
    tot = 0.0
    hit = False
    for row in j.get("data") or []:
        name = str(row[0])
        if "外資" in name:
            try:
                tot += float(str(row[3]).replace(",", ""))
                hit = True
            except Exception:     # noqa: BLE001
                pass
    return round(tot / 1e8, 2) if hit else None


def _fallback_bfi82u(days: int) -> int:
    n = 0
    today = tw_now().date()
    for k in range(days):
        d = today - timedelta(days=k)
        if d.weekday() >= 5:
            continue
        try:
            r = httpx.get("https://www.twse.com.tw/rwd/zh/fund/BFI82U",
                          params={"dayDate": d.strftime("%Y%m%d"), "type": "day", "response": "json"},
                          headers={**UA, "Referer": "https://www.twse.com.tw/"}, timeout=15)
            v = parse_bfi82u(r.json())
            if v is not None:
                n += save_chips(pd.DataFrame([{"date": d.strftime("%Y-%m-%d"), "f_net": v}]), "TWSE_BFI82U")
            time.sleep(0.6)
        except Exception as e:     # noqa: BLE001
            mark("twse_bfi82u", False, repr(e))
            return n
    if n:
        mark("twse_bfi82u", True)
    return n


def _fallback_regime_futures(days: int) -> int:
    try:
        from regime.db import db as rdb
        with rdb() as c:
            rows = c.execute("SELECT date, value FROM market_daily WHERE series='FOREIGN_FUTURES_NET' ORDER BY date DESC LIMIT ?",
                             (days,)).fetchall()
        df = pd.DataFrame([{"date": str(r["date"])[:10], "fut_f_oi": r["value"]} for r in rows])
        return save_chips(df, "REGIME_TAIFEX")
    except Exception as e:     # noqa: BLE001
        log.warning(f"[wave] 期貨備援失敗：{e}")
        return 0


def ensure_chips_history(background: bool = True):
    with db() as c:
        n = c.execute("SELECT COUNT(*) FROM mkt_chips").fetchone()[0]
    if n >= 500:
        return False
    if background:
        threading.Thread(target=lambda: update_chips(full=True), daemon=True).start()
    else:
        update_chips(full=True)
    return True


# ── 讀取 ─────────────────────────────────────────────────────────────────────
def load_idx(sym: str) -> pd.DataFrame:
    with db() as c:
        rows = c.execute("SELECT date,o,h,l,c,v FROM idx_daily WHERE sym=? AND c IS NOT NULL ORDER BY date", (sym,)).fetchall()
    df = pd.DataFrame([dict(r) for r in rows], columns=["date", "o", "h", "l", "c", "v"])
    if not df.empty:
        for k in ("o", "h", "l"):
            df[k] = df[k].fillna(df["c"])
        df = df[(df.h >= df.l) & (df.c > 0)].reset_index(drop=True)
    return df


def load_chips() -> pd.DataFrame:
    with db() as c:
        rows = c.execute("SELECT date,f_net,t_net,d_net,fut_f_oi,margin_amt FROM mkt_chips ORDER BY date").fetchall()
    return pd.DataFrame([dict(r) for r in rows], columns=["date", "f_net", "t_net", "d_net", "fut_f_oi", "margin_amt"])


# ── 盤中即時加權（MIS；只拿來顯示／當現價，不寫進資料庫、不確認轉折）──────────
def is_tw_session(now: Optional[datetime] = None) -> bool:
    now = now or tw_now()
    return now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (13, 35)


def live_taiex() -> Optional[dict]:
    try:
        base = "https://mis.twse.com.tw"
        with httpx.Client(timeout=8, verify=False, follow_redirects=True, headers={**UA, "Accept-Language": "zh-TW"}) as c:
            r = c.get(f"{base}/stock/api/getStockInfo.jsp",
                      headers={"Referer": f"{base}/stock/index.jsp", "X-Requested-With": "XMLHttpRequest"},
                      params={"ex_ch": "tse_t00.tw", "json": "1", "delay": "0"})
            it = (r.json().get("msgArray") or [{}])[0]
        z = float(it.get("z"))
        d = str(it.get("d") or "")
        f = lambda k: float(it.get(k)) if it.get(k) not in (None, "-", "") else z
        mark("mis", True)
        return {"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "o": f("o"), "h": f("h"), "l": f("l"), "c": z,
                "y": f("y"), "time": it.get("t") or ""}
    except Exception as e:     # noqa: BLE001
        mark("mis", False, repr(e))
        return None


# ── B115 全市場整戶擔保維持率、追繳／處分（證交所台股儀表板 BFIJ3U，上市＋上櫃、融資＋融券合併計算）─────────────
BFIJ3U = "https://www.twse.com.tw/rwd/zh/marginTrading/BFIJ3U_TREND"
CREDIT_COLS = (("keepRate", "keep"), ("belowAccNum", "below_acc"), ("callAccNum", "call_acc"), ("callAmt", "call_amt"),
               ("exeAccNum", "exe_acc"), ("exeAmt", "exe_amt"), ("marginAccNum", "credit_acc"), ("marginAccRate", "credit_rate"),
               ("crdAmt", "crd_amt"))


def parse_credit_keep(j: dict) -> list:
    """BFIJ3U_TREND（或單日 BFIJ3U）的 JSON → [{date: YYYY-MM-DD, keep, below_acc, ...}]；格式不對回 []"""
    if not isinstance(j, dict) or j.get("stat") != "OK":
        return []
    rows = j.get("data") if isinstance(j.get("data"), list) else [j]
    out = []
    for r in rows:
        d = str(r.get("date") or "")
        if len(d) != 8 or not d.isdigit() or r.get("keepRate") in (None, ""):
            continue
        x = {"date": f"{d[:4]}-{d[4:6]}-{d[6:]}"}
        for k, c in CREDIT_COLS:
            try:
                x[c] = float(r[k]) if r.get(k) not in (None, "") else None
            except (TypeError, ValueError):
                x[c] = None
        out.append(x)
    return out


def update_credit_keep(days: int = 120, get=None) -> int:
    """抓近 days 個交易日的全市場整戶擔保維持率、追繳／處分 → credit_keep（證交所約晚上公布當天的）"""
    get = get or (lambda u, p: httpx.get(u, params=p, headers=UA, timeout=30).json())
    try:
        rows = parse_credit_keep(get(BFIJ3U, {"response": "json", "days": int(days)}))
        if rows:
            with db() as c:
                c.executemany("INSERT OR REPLACE INTO credit_keep(date," + ",".join(c_ for _, c_ in CREDIT_COLS) + ") VALUES (?" + ",?" * len(CREDIT_COLS) + ")",
                              [tuple([r["date"]] + [r[c_] for _, c_ in CREDIT_COLS]) for r in rows])
        mark("twse_credit_keep", bool(rows), "" if rows else "沒有資料")
        return len(rows)
    except Exception as e:     # noqa: BLE001
        mark("twse_credit_keep", False, repr(e)[:200])
        return 0


# ── B128 借券賣出餘額（證交所 TWT93U＋櫃買「信用額度總量管制餘額表」，逐檔、單位：股）─────────────
# 兩邊表格一樣 15 欄：代號、名稱、融券 6 欄、借券賣出 6 欄（前日餘額、當日賣出、當日還券、當日調整、當日餘額、次一營業日可限額）、備註
TWT93U = "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U"          # 舊的 /rwd/zh/SBL/TWT93U 已經 404（2026-11 實測）
TPEX_SBL = "https://www.tpex.org.tw/www/zh-tw/margin/sbl"
SBL_KEEP_DAYS = 90         # 逐檔資料留幾個交易日
SBL_MAX_FETCH = 15         # 一次最多補幾天（每天上市＋上櫃各 1 次請求、間隔 2 秒；第一次上線分幾次排程慢慢補到 60 天）


def _n(v) -> Optional[float]:
    try:
        t = str(v).replace(",", "").strip()
        return float(t) if t not in ("", "-", "--") else None
    except (TypeError, ValueError):
        return None


def parse_sbl(j: dict, mkt: str) -> list:
    """TWT93U／櫃買 sbl 的 JSON → [{sid, mkt, name, prev, sell, ret, adj, bal}]（股）；沒資料或格式不對回 []"""
    if not isinstance(j, dict) or str(j.get("stat", "")).lower() != "ok":
        return []
    t = (j.get("tables") or [j])[0] if isinstance(j.get("tables"), list) else j
    fields, data = t.get("fields") or [], t.get("data") or []
    if len(fields) < 13 or "前日餘額" not in fields[8] or "當日餘額" not in fields[12]:
        return []
    out = []
    for r in data:
        if not isinstance(r, list) or len(r) < 13:
            continue
        sid = str(r[0]).strip()
        bal = _n(r[12])
        if not sid or bal is None:
            continue
        out.append({"sid": sid, "mkt": mkt, "name": str(r[1]).strip(), "prev": _n(r[8]), "sell": _n(r[9]), "ret": _n(r[10]),
                    "adj": _n(r[11]), "bal": bal})
    return out


def _sbl_get(mkt: str, d: str):
    """d＝YYYY-MM-DD"""
    if mkt == "twse":
        return httpx.get(TWT93U, params={"response": "json", "date": d.replace("-", "")}, headers=UA, timeout=30).json()
    return httpx.post(TPEX_SBL, data={"date": d.replace("-", "/"), "response": "json"}, headers=UA, timeout=30).json()


def update_sbl(days: int = 60, max_fetch: int = SBL_MAX_FETCH, get=None, pause: float = 2.0) -> int:
    """近 days 個交易日（看加權日 K 有哪幾天）裡還沒抓到的，從最新的開始補，一次最多 max_fetch 天。回傳補到幾天"""
    get = get or _sbl_get
    try:
        with db() as c:
            dates = [r[0] for r in c.execute("SELECT date FROM idx_daily WHERE sym='TWII' AND c IS NOT NULL ORDER BY date DESC LIMIT ?",
                                             (int(days),))]
            have = {(d, m) for d, m in c.execute("SELECT DISTINCT date, mkt FROM sbl_stock")}
    except Exception as e:     # noqa: BLE001
        mark("sbl", False, repr(e)[:200])
        return 0
    got, tried, err = 0, 0, ""
    for d in dates:
        todo = [m for m in ("twse", "tpex") if (d, m) not in have]
        if not todo:
            continue
        if tried >= max_fetch:
            break
        tried += 1
        rows = []
        for m in todo:
            try:
                rows += parse_sbl(get(m, d), m)
            except Exception as e:     # noqa: BLE001
                err = repr(e)[:200]
            if pause:
                time.sleep(pause)
        if rows:
            with db() as c:
                c.executemany("INSERT OR REPLACE INTO sbl_stock(date,sid,mkt,name,prev,sell,ret,adj,bal) VALUES (?,?,?,?,?,?,?,?,?)",
                              [(d, r["sid"], r["mkt"], r["name"], r["prev"], r["sell"], r["ret"], r["adj"], r["bal"]) for r in rows])
            got += 1
    try:
        with db() as c:
            keep = c.execute("SELECT DISTINCT date FROM sbl_stock ORDER BY date DESC LIMIT 1 OFFSET ?", (SBL_KEEP_DAYS,)).fetchone()
            if keep:
                c.execute("DELETE FROM sbl_stock WHERE date<=?", (keep[0],))
    except Exception:     # noqa: BLE001
        pass
    if tried:
        mark("sbl", got > 0 or not err, err)
    return got


def load_sbl_one(sid: str, n: int = 61) -> list:
    """B138 個股：[(date, sell, ret, bal)]（股，舊→新），最近 n 個有這檔資料的交易日"""
    try:
        with db() as c:
            rs = c.execute("SELECT date, sell, ret, bal FROM sbl_stock WHERE sid=? ORDER BY date DESC LIMIT ?", (str(sid), int(n))).fetchall()
        return [(r[0], r[1] or 0.0, r[2] or 0.0, r[3] or 0.0) for r in reversed(rs)]
    except Exception:     # noqa: BLE001
        return []


def load_sbl(n: int = 61) -> dict:
    """{date: [{sid, mkt, name, sell, ret, bal}]}，最近 n 個交易日"""
    try:
        with db() as c:
            ds = [r[0] for r in c.execute("SELECT DISTINCT date FROM sbl_stock ORDER BY date DESC LIMIT ?", (int(n),))]
            if not ds:
                return {}
            out: dict = {d: [] for d in sorted(ds)}
            for r in c.execute("SELECT date,sid,mkt,name,sell,ret,bal FROM sbl_stock WHERE date>=?", (min(ds),)):
                out[r[0]].append({"sid": r[1], "mkt": r[2], "name": r[3], "sell": r[4] or 0, "ret": r[5] or 0, "bal": r[6] or 0})
        return out
    except Exception:     # noqa: BLE001
        return {}


def load_credit_keep(n: int = 120) -> list:
    try:
        with db() as c:
            rs = c.execute("SELECT * FROM credit_keep ORDER BY date DESC LIMIT ?", (int(n),)).fetchall()
        return [dict(r) for r in reversed(rs)]
    except Exception:     # noqa: BLE001
        return []
