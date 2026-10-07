"""
chip_course.py — 上課筆記的籌碼面選股（2026-10-04 新增，掃描完價格策略後另外算）

  S_TRUST5     投信連續買超＋強勢股回測 5 日線打橫 2~3 天不破（跌破 10／20 日線出場）
  S_SHORT_UP   強勢股融券持續大增：軋空／套利熱絡，股價還有高點，拉回是買點
  S_SHORT_EBB  融券退潮：高檔強勢股的融券從高點連續減少 → 拉回不再是買點，減碼／出場
  S_BIGHOLD    千張大戶持股比率上升、散戶持股比率下降（創新低更好）＝籌碼集中
  S_TRUST_DUMP 投信高檔連續賣超（之前有佈局、股價拉高後連續倒貨 → 出場）

資料來源（2026-10 GitHub Actions 實測可用）：
- 投信：TWSE rwd fund/T86（可指定日期）；櫃買 OpenAPI tpex_3insti_daily_trading（只有最新一天，每天累積）
- 融券餘額：cb.fetcher.fetch_short_day（TWSE rwd MI_MARGN＋櫃買 margin/balance，可指定日期）
- 集保分級：TDCC OpenAPI 1-5（每週一份，每週累積）
- 三大法人每日（深度分析用，PLAN-DEEP2 §4）：TWSE rwd fund/T86＋櫃買 www/zh-tw/insti/dailyTrade（兩邊都可指定日期）
- 融資融券餘額每日：TWSE rwd MI_MARGN＋櫃買 margin/balance（cb.fetcher.fetch_margin_day）
資料存 chip_data/course.db。
"""
from __future__ import annotations

import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent / "chip_data" / "course.db"
_TW = timezone(timedelta(hours=8))

CHIP_STRATEGIES = {
    "S_TRUST5":    "🏦 投信連買＋5日線打橫",
    "S_SHORT_UP":  "🩳 強勢股融券大增（拉回買）",
    "S_SHORT_EBB": "🌊 融券退潮（減碼／出場）",
    "S_BIGHOLD":   "🐋 大戶增、散戶減（籌碼集中）",
    "S_TRUST_DUMP": "🏃 投信高檔連續賣超（出場）",
}
CHIP_SHORT = {"S_SHORT_EBB", "S_TRUST_DUMP"}
_MP = {"key": "min_price", "label": "最低股價", "type": "number", "default": 10, "min": 1, "max": 500, "step": 1}
CHIP_PARAMS = {
    "S_TRUST_DUMP": [_MP, {"key": "sell_days", "label": "投信連續賣超天數（≥）", "type": "number", "default": 3, "min": 2, "max": 10, "step": 1},
                     {"key": "rise_pct", "label": "距60日低點漲幅%（≥，高檔）", "type": "number", "default": 20, "min": 5, "max": 100, "step": 5},
                     {"key": "near_high_pct", "label": "離60日高點%（≤）", "type": "number", "default": 10, "min": 2, "max": 30, "step": 1}],
    "S_TRUST5": [_MP, {"key": "trust_days", "label": "投信連續買超天數（≥）", "type": "number", "default": 3, "min": 2, "max": 10, "step": 1},
                 {"key": "flat_days", "label": "打橫天數", "type": "number", "default": 2, "min": 2, "max": 5, "step": 1},
                 {"key": "flat_pct", "label": "打橫：收盤高低差%（≤）", "type": "number", "default": 3, "min": 1, "max": 8, "step": 0.5}],
    "S_SHORT_UP": [_MP, {"key": "up_pct", "label": "融券 5 日增加%（≥）", "type": "number", "default": 30, "min": 10, "max": 200, "step": 5},
                   {"key": "min_lots", "label": "融券增加張數（≥）", "type": "number", "default": 200, "min": 50, "max": 5000, "step": 50}],
    "S_SHORT_EBB": [_MP, {"key": "down_days", "label": "融券連續減少天數（≥）", "type": "number", "default": 3, "min": 2, "max": 8, "step": 1},
                    {"key": "from_peak_pct", "label": "距融券高點減少%（≥）", "type": "number", "default": 15, "min": 5, "max": 80, "step": 5}],
    "S_BIGHOLD": [_MP, {"key": "retail_lots", "label": "散戶定義：持股幾張以下（10／50／400）", "type": "number", "default": 50, "min": 10, "max": 400, "step": 10},
                  {"key": "min_big_chg", "label": "大戶比率週增加（百分點 ≥）", "type": "number", "default": 0.1, "min": 0, "max": 5, "step": 0.1}],
}

# 集保持股分級上限（股）：1:1-999 2:1,000-5,000 3:-10,000 4:-15,000 5:-20,000 6:-30,000 7:-40,000 8:-50,000
# 9:-100,000 10:-200,000 11:-400,000 12:-600,000 13:-800,000 14:-1,000,000 15:>1,000,000（16 差異數調整、17 合計）
_TIER_MAX_LOTS = {1: 1, 2: 5, 3: 10, 4: 15, 5: 20, 6: 30, 7: 40, 8: 50, 9: 100, 10: 200, 11: 400, 12: 600, 13: 800, 14: 1000}


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), timeout=10.0)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    c.executescript("""
        CREATE TABLE IF NOT EXISTS inst_trust (date TEXT, sid TEXT, net REAL, PRIMARY KEY (date, sid));   -- 投信買賣超（股）
        CREATE TABLE IF NOT EXISTS short_bal (date TEXT, sid TEXT, bal REAL, PRIMARY KEY (date, sid));    -- 融券餘額（張）
        CREATE TABLE IF NOT EXISTS tdcc_tier (date TEXT, sid TEXT, tier INTEGER, people REAL, shares REAL,
                                              PRIMARY KEY (date, sid, tier));
        CREATE TABLE IF NOT EXISTS course_status (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS inst_daily (date TEXT, sid TEXT, foreign_net REAL, trust_net REAL, dealer_net REAL,
                                               PRIMARY KEY (date, sid));                                   -- 三大法人買賣超（股）
        CREATE TABLE IF NOT EXISTS margin_bal (date TEXT, sid TEXT, margin REAL, short REAL,
                                               PRIMARY KEY (date, sid));                                   -- 融資／融券餘額（張）
        CREATE TABLE IF NOT EXISTS fetch_log (kind TEXT, date TEXT, market TEXT, rows INTEGER,
                                              PRIMARY KEY (kind, date, market));                           -- 抓成功的日期（假日／還沒公布不記，下次再抓）
    """)
    return c


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ── 解析 ─────────────────────────────────────────────────────────────────────

def parse_t86(j: dict) -> dict:
    """TWSE T86 → {sid: 投信買賣超股數}"""
    f = (j or {}).get("fields") or []
    if "投信買賣超股數" not in f:
        return {}
    i = f.index("投信買賣超股數")
    out = {}
    for r in j.get("data") or []:
        v = _num(r[i]) if i < len(r) else None
        if v is not None:
            out[str(r[0]).strip()] = v
    return out


def parse_t86_inst(j: dict) -> dict:
    """TWSE T86 → {sid: (外資不含外資自營商, 投信, 自營商)} 買賣超股數；欄名對不上回空 dict"""
    f = (j or {}).get("fields") or []
    keys = ("外陸資買賣超股數(不含外資自營商)", "投信買賣超股數", "自營商買賣超股數")
    if not all(k in f for k in keys):
        return {}
    idx = [f.index(k) for k in keys]
    out = {}
    for r in j.get("data") or []:
        if len(r) <= max(idx):
            continue
        vals = [_num(r[i]) for i in idx]
        if any(v is None for v in vals):
            continue
        out[str(r[0]).strip()] = tuple(vals)
    return out


def parse_tpex_insti_daily(j: dict) -> tuple:
    """櫃買 www/zh-tw/insti/dailyTrade（type=Daily, sect=EW）→ (YYYY-MM-DD 或 None, {sid: (外資不含自營, 投信, 自營合計)})
    欄位 24 個：代號、名稱、外資不含自營(3)、外資自營(3)、外資合計(3)、投信(3)、自營自行(3)、自營避險(3)、自營合計(3)、三大合計
    每組最後一欄是買賣超；用「外資合計＋投信＋自營合計＝三大合計」驗算，對不上的列丟掉"""
    tb = ((j or {}).get("tables") or [None])[0] or {}
    f = tb.get("fields") or []
    if (len(f) != 24 or f[0] != "代號" or "合計" not in f[23]
            or any(f[i] != "買賣超股數" for i in (4, 7, 10, 13, 16, 19, 22))):
        return None, {}
    d = None
    s = str(tb.get("date") or "").strip()
    if len(s) == 9 and s[3] == "/" and s[6] == "/":
        d = f"{int(s[:3]) + 1911}-{s[4:6]}-{s[7:]}"
    out = {}
    for r in tb.get("data") or []:
        if len(r) < 24:
            continue
        fo, fa, tr, de, tot = (_num(r[i]) for i in (4, 10, 13, 22, 23))
        if None in (fo, fa, tr, de, tot) or abs(fa + tr + de - tot) > 1:
            continue
        out[str(r[0]).strip()] = (fo, tr, de)
    return d, out


def parse_tpex_insti(rows: list) -> tuple:
    """櫃買 tpex_3insti_daily_trading → (YYYY-MM-DD, {sid: 投信買賣超股數})"""
    out, d = {}, None
    for x in rows or []:
        sid = str(x.get("SecuritiesCompanyCode") or "").strip()
        key = next((k for k in x if "InvestmentTrust" in k and "Difference" in k), None)
        if not sid or not key:
            continue
        v = _num(x[key])
        if v is not None:
            out[sid] = v
        if not d and x.get("Date"):
            s = str(x["Date"]).strip()
            if len(s) == 7:
                d = f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:]}"
    return d, out


def parse_tdcc(rows: list) -> tuple:
    """TDCC 1-5 → (YYYY-MM-DD, [(sid, tier, people, shares)])"""
    if not rows:
        return None, []
    keys = list(rows[0].keys())
    k_sid = next(k for k in keys if "代號" in k)
    k_tier = next(k for k in keys if "分級" in k)
    k_sh = next(k for k in keys if "股數" in k)
    k_pp = next((k for k in keys if "人數" in k), None)
    k_dt = next(k for k in keys if "日期" in k)
    s = str(rows[0][k_dt]).strip()
    d = f"{s[:4]}-{s[4:6]}-{s[6:]}" if len(s) == 8 else None
    out = []
    for r in rows:
        sid = str(r[k_sid]).strip()
        if not (sid[:1].isdigit() and 4 <= len(sid) <= 6):
            continue
        try:
            tier = int(r[k_tier])
        except (TypeError, ValueError):
            continue
        out.append((sid, tier, _num(r.get(k_pp)) if k_pp else None, _num(r[k_sh]) or 0.0))
    return d, out


def holder_ratios(tiers: dict, retail_lots: int = 50) -> tuple:
    """{tier: shares} → (千張大戶 %, 散戶 %)；分母用 17 級（合計）＝ 1~15 級加總 − 16 級（差異數調整）"""
    total = tiers.get(17) or (sum(v for t, v in tiers.items() if 1 <= t <= 15) - tiers.get(16, 0))
    if total <= 0:
        return None, None
    big = tiers.get(15, 0) / total * 100
    retail = sum(v for t, v in tiers.items() if 1 <= t <= 14 and _TIER_MAX_LOTS[t] <= retail_lots) / total * 100
    return round(big, 3), round(retail, 3)


# ── 抓資料 ───────────────────────────────────────────────────────────────────

def _weekdays_back(n):
    d, out = datetime.now(_TW).date(), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def _logged(c, kind):
    return {(d, m) for d, m in c.execute("SELECT date, market FROM fetch_log WHERE kind=?", (kind,))}


def _log(c, kind, ds, market, n):
    if n > 0:
        c.execute("INSERT OR REPLACE INTO fetch_log VALUES (?,?,?,?)", (kind, ds, market, n))


def refresh(progress=None) -> dict:
    """補最近幾個交易日的三大法人（含投信）、融資融券，以及最新一週集保分級。
    三大法人每日表不到 20 天 → 回補 25 個平日（第一次約 1～2 分鐘），之後每次 8 天；只抓還沒成功抓過的日期／市場
    （假日、還沒公布的今天回空 → 不記錄，下次再試）"""
    import httpx
    from cb.fetcher import client as _client, fetch_margin_day
    c = get_conn()
    msgs = []
    with _client() as cl:
        n_inst = c.execute("SELECT COUNT(DISTINCT date) FROM inst_daily").fetchone()[0]
        days = _weekdays_back(25 if n_inst < 20 else 8)
        have_t = {r[0] for r in c.execute("SELECT DISTINCT date FROM inst_trust")}
        have_s = {r[0] for r in c.execute("SELECT DISTINCT date FROM short_bal")}
        got_i, got_m = _logged(c, "inst"), _logged(c, "margin")
        for k, d in enumerate(days, 1):
            ds = d.isoformat()
            if progress:
                progress(f"法人／融資券 {ds}", k, len(days))
            if (ds, "twse") not in got_i or ds not in have_t:
                try:
                    r = cl.get("https://www.twse.com.tw/rwd/zh/fund/T86",
                               params={"date": d.strftime("%Y%m%d"), "selectType": "ALLBUT0999", "response": "json"})
                    j = r.json()
                    m = parse_t86(j)
                    c.executemany("INSERT OR REPLACE INTO inst_trust VALUES (?,?,?)", [(ds, s, v) for s, v in m.items()])
                    mi = parse_t86_inst(j)
                    c.executemany("INSERT OR REPLACE INTO inst_daily VALUES (?,?,?,?,?)",
                                  [(ds, s, *v) for s, v in mi.items()])
                    _log(c, "inst", ds, "twse", len(mi))
                except Exception as e:
                    msgs.append(f"T86 {ds}：{type(e).__name__}")
                time.sleep(0.6)
            if (ds, "tpex") not in got_i:
                try:
                    r = cl.get("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade",
                               params={"type": "Daily", "sect": "EW", "date": d.strftime("%Y/%m/%d"), "response": "json"})
                    dd, mi = parse_tpex_insti_daily(r.json())
                    if mi and dd == ds:
                        c.executemany("INSERT OR REPLACE INTO inst_daily VALUES (?,?,?,?,?)",
                                      [(ds, s, *v) for s, v in mi.items()])
                        c.executemany("INSERT OR REPLACE INTO inst_trust VALUES (?,?,?)",
                                      [(ds, s, v[1]) for s, v in mi.items()])
                        _log(c, "inst", ds, "tpex", len(mi))
                except Exception as e:
                    msgs.append(f"櫃買法人 {ds}：{type(e).__name__}")
                time.sleep(0.6)
            if (ds, "twse") not in got_m or (ds, "tpex") not in got_m or ds not in have_s:
                tw, tp = fetch_margin_day(cl, d)
                for mk, mm in (("twse", tw), ("tpex", tp)):
                    c.executemany("INSERT OR REPLACE INTO margin_bal VALUES (?,?,?,?)",
                                  [(ds, s, v[0], v[1]) for s, v in mm.items()])
                    c.executemany("INSERT OR REPLACE INTO short_bal VALUES (?,?,?)",
                                  [(ds, s, v[1]) for s, v in mm.items() if v[1] is not None])
                    _log(c, "margin", ds, mk, len(mm))
                time.sleep(0.6)
            c.commit()
        try:
            dd, m = parse_tpex_insti(cl.get("https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading").json())
            if dd and m:
                c.executemany("INSERT OR REPLACE INTO inst_trust VALUES (?,?,?)", [(dd, s, v) for s, v in m.items()])
                c.commit()
        except Exception as e:
            msgs.append(f"櫃買法人：{type(e).__name__}")
        try:
            if progress:
                progress("集保分級", 0, 0)
            r = httpx.get("https://openapi.tdcc.com.tw/v1/opendata/1-5", timeout=httpx.Timeout(90.0, connect=15.0))
            dd, rows = parse_tdcc(r.json())
            if dd and rows and not c.execute("SELECT 1 FROM tdcc_tier WHERE date=? LIMIT 1", (dd,)).fetchone():
                c.executemany("INSERT OR REPLACE INTO tdcc_tier VALUES (?,?,?,?,?)", [(dd, *x) for x in rows])
                c.commit()
                msgs.append(f"集保 {dd}")
        except Exception as e:
            msgs.append(f"集保：{type(e).__name__}")
    c.execute("INSERT OR REPLACE INTO course_status VALUES ('last_refresh', ?)",
              (datetime.now(_TW).strftime("%Y-%m-%d %H:%M") + ("：" + "、".join(msgs) if msgs else ""),))
    c.commit()
    c.close()
    return {"messages": msgs}


# ── 深度分析讀取（PLAN-DEEP2 §4）────────────────────────────────────────────

def inst_series(sid: str, n: int = 20) -> list:
    """最近 n 個有資料的交易日 [(YYYY-MM-DD, 外資, 投信, 自營)]（股），舊→新"""
    from contextlib import closing
    try:
        with closing(get_conn()) as c:
            rows = c.execute("SELECT date, foreign_net, trust_net, dealer_net FROM inst_daily WHERE sid=? "
                             "ORDER BY date DESC LIMIT ?", (sid, n)).fetchall()
    except Exception:
        return []
    return [tuple(r) for r in reversed(rows)]


def margin_series(sid: str, n: int = 6) -> list:
    """最近 n 個交易日 [(YYYY-MM-DD, 融資餘額, 融券餘額)]（張），舊→新"""
    from contextlib import closing
    try:
        with closing(get_conn()) as c:
            rows = c.execute("SELECT date, margin, short FROM margin_bal WHERE sid=? ORDER BY date DESC LIMIT ?",
                             (sid, n)).fetchall()
    except Exception:
        return []
    return [tuple(r) for r in reversed(rows)]


# ── 選股 ─────────────────────────────────────────────────────────────────────

def _series(c, table, col, since):
    out = {}
    for d, sid, v in c.execute(f"SELECT date, sid, {col} FROM {table} WHERE date>=? ORDER BY date", (since,)):
        out.setdefault(sid, []).append((d, v))
    return out


def _row(sid, df, names, key, **extra):
    from scanner import _change_pct, calc_bb_score
    last = df.iloc[-1]
    d = {"stock_id": sid, "name": (names or {}).get(sid, ""), "close": round(float(last["close"]), 2),
         "change_pct": _change_pct(df), "volume": round(float(last.get("volume", 0) or 0)),
         "bb_score": calc_bb_score(df), "strategy": key, "last_date": str(last.get("date", ""))}
    d.update(extra)
    return d


def _strong(df):
    c = df["close"].astype(float)
    m5, m10, m20 = (c.rolling(k).mean().iloc[-1] for k in (5, 10, 20))
    return bool(m5 > m10 > m20) and c.iloc[-1] >= df["high"].astype(float).iloc[-60:].max() * 0.85


def screen_trust5(trust: dict, get_df, names, p):
    need, fd, fp = int(p.get("trust_days", 3)), int(p.get("flat_days", 2)), float(p.get("flat_pct", 3)) / 100
    out = []
    for sid, ser in trust.items():
        streak = 0
        for _, v in reversed(ser):
            if v > 0:
                streak += 1
            else:
                break
        if streak < need:
            continue
        df = get_df(sid)
        if df is None or len(df) < 25 or float(df.iloc[-1]["close"]) < float(p.get("min_price", 10)) or not _strong(df):
            continue
        c, lo = df["close"].astype(float), df["low"].astype(float)
        ma5, ma10 = c.rolling(5).mean(), c.rolling(10).mean()
        last = c.iloc[-fd:]
        if (last.max() - last.min()) / last.min() > fp:
            continue
        if (lo.iloc[-fd:] < ma5.iloc[-fd:] * 0.995).any() or c.iloc[-1] < ma5.iloc[-1]:
            continue
        out.append(_row(sid, df, names, "S_TRUST5", trust_days=streak,
                        trust_lots=round(sum(v for _, v in ser[-streak:]) / 1000),
                        ma5=round(ma5.iloc[-1], 2), stop=round(float(lo.iloc[-fd:].min()), 2), exit_ma10=round(ma10.iloc[-1], 2),
                        note="回測 5 日線打橫不破時介入，停損點極短；跌破 10 日線或 20 日線出場"))
    return out


def screen_trust_dump(trust: dict, get_df, names, p):
    """投信高檔連續賣超：原本有佈局（之前淨買）的投信，在股價拉高後連續賣超 → 知情人士獲利了結，跟著出場"""
    need = int(p.get("sell_days", 3))
    rise, near = float(p.get("rise_pct", 20)) / 100, float(p.get("near_high_pct", 10)) / 100
    out = []
    for sid, ser in trust.items():
        streak = 0
        for _, v in reversed(ser):
            if v < 0:
                streak += 1
            else:
                break
        if streak < need or sum(v for _, v in ser[:-streak] if v > 0) <= 0:     # 之前要有買進佈局
            continue
        df = get_df(sid)
        if df is None or len(df) < 60 or float(df.iloc[-1]["close"]) < float(p.get("min_price", 10)):
            continue
        c, h, lo = df["close"].astype(float), df["high"].astype(float), df["low"].astype(float)
        hi60, lo60 = float(h.iloc[-60:].max()), float(lo.iloc[-60:].min())
        if lo60 <= 0 or c.iloc[-1] / lo60 - 1 < rise or c.iloc[-1] < hi60 * (1 - near):
            continue
        out.append(_row(sid, df, names, "S_TRUST_DUMP", sell_days=streak,
                        sell_lots=round(-sum(v for _, v in ser[-streak:]) / 1000),
                        buy_lots=round(sum(v for _, v in ser[:-streak] if v > 0) / 1000),
                        high60=round(hi60, 2), ma10=round(float(c.rolling(10).mean().iloc[-1]), 2),
                        note="投信在高檔連續倒貨＝知情人士獲利了結，易大回檔：跟著賣出避險（地緣分點大賣要另外手動查）"))
    return out


def screen_short_up(shorts: dict, get_df, names, p):
    up, lots = float(p.get("up_pct", 30)) / 100, float(p.get("min_lots", 200))
    out = []
    for sid, ser in shorts.items():
        if len(ser) < 6:
            continue
        now, prev = ser[-1][1], ser[-6][1]
        if now is None or prev is None or now - prev < lots or now < max(prev, 1) * (1 + up):
            continue
        df = get_df(sid)
        if df is None or len(df) < 60 or float(df.iloc[-1]["close"]) < float(p.get("min_price", 10)) or not _strong(df):
            continue
        c = df["close"].astype(float)
        pull = c.iloc[-1] < c.iloc[-5:].max() * 0.99
        out.append(_row(sid, df, names, "S_SHORT_UP", short_now=now, short_chg5=now - prev,
                        short_chg5_pct=round((now / prev - 1) * 100, 1) if prev else None,
                        pullback="拉回中" if pull else "創高中", stop=round(float(df["low"].astype(float).iloc[-5:].min()), 2),
                        note="融券持續大增＝軋空／套利熱絡，股價還有高點，拉回是買點；融券開始連續減少就不是買點"))
    return out


def screen_short_ebb(shorts: dict, get_df, names, p):
    nd, fp = int(p.get("down_days", 3)), float(p.get("from_peak_pct", 15)) / 100
    out = []
    for sid, ser in shorts.items():
        vals = [v for _, v in ser if v is not None]
        if len(vals) < nd + 3:
            continue
        if not all(vals[-i] < vals[-i - 1] for i in range(1, nd + 1)):
            continue
        peak = max(vals[-10:])
        if peak < 300 or vals[-1] > peak * (1 - fp):
            continue
        df = get_df(sid)
        if df is None or len(df) < 60 or float(df.iloc[-1]["close"]) < float(p.get("min_price", 10)):
            continue
        hi = df["high"].astype(float).iloc[-60:].max()
        if float(df.iloc[-1]["close"]) < hi * 0.85:                 # 只看高檔強勢股
            continue
        out.append(_row(sid, df, names, "S_SHORT_EBB", short_now=vals[-1], short_peak=peak,
                        from_peak_pct=round((vals[-1] / peak - 1) * 100, 1), down_days=nd,
                        note="融券退潮：軋空／套利推力消失，拉回不再是買點 → 減碼或出場"))
    return out


def screen_bighold(c, get_df, names, p):
    lots = int(p.get("retail_lots", 50))
    mbc = float(p.get("min_big_chg", 0.1))
    dates = [r[0] for r in c.execute("SELECT DISTINCT date FROM tdcc_tier ORDER BY date DESC LIMIT 8")]
    if len(dates) < 2:
        return []
    hist = {}
    for d, sid, tier, sh in c.execute(f"SELECT date, sid, tier, shares FROM tdcc_tier WHERE date IN ({','.join('?' * len(dates))})", dates):
        hist.setdefault(sid, {}).setdefault(d, {})[tier] = sh
    out = []
    for sid, by_d in hist.items():
        ws = sorted(by_d)
        if len(ws) < 2 or ws[-1] != dates[0]:
            continue
        ratios = [holder_ratios(by_d[d], lots) for d in ws]
        (b1, r1), (b0, r0) = ratios[-1], ratios[-2]
        if None in (b1, r1, b0, r0) or b1 - b0 < mbc or r1 >= r0:
            continue
        df = get_df(sid)
        if df is None or len(df) < 5 or float(df.iloc[-1]["close"]) < float(p.get("min_price", 10)):
            continue
        new_low = len(ratios) >= 3 and r1 <= min(r for _, r in ratios)
        big_up_weeks = 0
        for i in range(len(ratios) - 1, 0, -1):
            if ratios[i][0] > ratios[i - 1][0]:
                big_up_weeks += 1
            else:
                break
        out.append(_row(sid, df, names, "S_BIGHOLD", big_pct=round(b1, 2), big_chg=round(b1 - b0, 2),
                        retail_pct=round(r1, 2), retail_chg=round(r1 - r0, 2), big_up_weeks=big_up_weeks,
                        retail_low="創新低" if new_low else ("—" if len(ratios) < 3 else "下降"), tdcc_date=ws[-1],
                        note=f"千張大戶持股上升、散戶（{lots} 張以下）持股下降＝籌碼集中；散戶比率創新低更強（集保資料每週累積）"))
    return out


def run_all(names: dict = None, strategy_params: dict = None, do_refresh: bool = True) -> dict:
    """回傳 {策略: [結果]}；names = {sid: 名稱}"""
    from price_cache import get_stock_ohlcv
    if do_refresh:
        try:
            refresh()
        except Exception as e:
            print(f"[COURSE] 籌碼資料更新失敗：{e}")
    sp = strategy_params or {}
    p = lambda k: {**{x["key"]: x["default"] for x in CHIP_PARAMS[k]}, **(sp.get(k) or {})}
    cache = {}

    def get_df(sid):
        if sid not in cache:
            df = get_stock_ohlcv(sid, days=120)
            cache[sid] = df if df is not None and not df.empty else None
        return cache[sid]

    c = get_conn()
    since = (datetime.now(_TW).date() - timedelta(days=30)).isoformat()
    trust = _series(c, "inst_trust", "net", since)
    shorts = _series(c, "short_bal", "bal", since)
    out = {}
    for key, fn, arg in (("S_TRUST5", screen_trust5, trust), ("S_SHORT_UP", screen_short_up, shorts),
                         ("S_SHORT_EBB", screen_short_ebb, shorts), ("S_BIGHOLD", screen_bighold, c),
                         ("S_TRUST_DUMP", screen_trust_dump, trust)):
        try:
            out[key] = fn(arg, get_df, names, p(key))
        except Exception as e:
            print(f"[COURSE] {key} 失敗：{e}")
            out[key] = []
    c.close()
    return out
