"""
market_rank.py — 全市場「法人買賣超排行」（B70，PLAN-B70.md §5）

以前（/api/market/scan 舊版）：只抓上市 T86；「法人合計」是加權數（外資×1＋投信×0.95＋自營自行買賣×0.7）；
前端「連買連賣」讀 consecutive_buy/sell 但後端從沒算 → 永遠「—」。
現在：chip_course.db inst_daily（上市＋上櫃，外資不含外資自營／投信／自營合計，股）
- 三大合計＝外資＋投信＋自營（不加權）
- 外資、投信各自的連買／連賣天數（從最新一天往回同號，0 或缺資料就斷）
- 5 日合計、占成交量 %（price_daily 同一天的量，有才算）
純函式 build_rows／filter_sort 可測；load_inst／attach_prices 讀資料庫。
"""
from __future__ import annotations

import sqlite3
from contextlib import closing


def streak(seq: list, i: int) -> int:
    """seq＝新→舊 [(外資, 投信, 自營) 或 None]；回第 i 欄最後連續同號天數（+連買、−連賣、0）"""
    n, sign = 0, 0
    for x in seq:
        if x is None:
            break
        v = x[i]
        sg = (v > 0) - (v < 0)
        if sg == 0 or (sign and sg != sign):
            break
        sign, n = sg, n + 1
    return n * sign


def is_etf(sid: str) -> bool:
    return sid.startswith("00")


def keep_code(sid: str) -> bool:
    """4 碼股票或 00 開頭 ETF（排除權證、牛熊證等 6 碼）"""
    return (len(sid) == 4 and sid.isdigit()) or (is_etf(sid) and len(sid) <= 6)


def build_rows(dates: list, by: dict) -> list:
    """dates＝新→舊交易日；by＝{sid: {date: (外資, 投信, 自營)（張）}} → 最新一天有資料的股票列"""
    if not dates:
        return []
    latest = dates[0]
    out = []
    for sid, m in by.items():
        if latest not in m or not keep_code(sid):
            continue
        f, t, de = m[latest]
        seq = [m.get(d) for d in dates]
        last5 = [x for x in seq[:5] if x is not None]
        out.append({
            "stock_id": sid, "foreign_lots": round(f), "trust_lots": round(t), "dealer_lots": round(de),
            "total_lots": round(f + t + de),
            "whale_flow_lots": round(f + t + de),          # 舊欄位名保留（值改為真正三者相加），推播／舊前端相容
            "foreign_streak": streak(seq, 0), "trust_streak": streak(seq, 1),
            "sum5_total": round(sum(x[0] + x[1] + x[2] for x in last5)),
            "sum5_foreign": round(sum(x[0] for x in last5)), "sum5_trust": round(sum(x[1] for x in last5)),
            "is_etf": is_etf(sid),
        })
    return out


SORT_KEYS = {"total": "total_lots", "foreign": "foreign_lots", "trust": "trust_lots", "ratio": "vol_ratio_pct",
             "sum5": "sum5_total"}


def filter_sort(rows: list, side: str = "buy", sort: str = "total", market: str = "all", etf: bool = False,
                top: int = 50) -> list:
    key = SORT_KEYS.get(sort, "total_lots")
    sel = [r for r in rows if (etf or not r.get("is_etf"))
           and (market == "all" or r.get("market") == market)
           and r.get(key) is not None]
    if side == "sell":
        sel = [r for r in sel if r[key] < 0]
        sel.sort(key=lambda r: r[key])
    else:
        sel = [r for r in sel if r[key] > 0]
        sel.sort(key=lambda r: -r[key])
    return sel[:top]


def load_inst(n_days: int = 25) -> tuple:
    """(dates 新→舊 YYYY-MM-DD, by)；inst_daily 是股 → 張"""
    import chip_course
    with closing(chip_course.get_conn()) as c:
        dates = [r[0] for r in c.execute("SELECT DISTINCT date FROM inst_daily ORDER BY date DESC LIMIT ?", (n_days,))]
        if not dates:
            return [], {}
        by: dict = {}
        for d, sid, f, t, de in c.execute("SELECT date, sid, foreign_net, trust_net, dealer_net FROM inst_daily "
                                          "WHERE date >= ?", (dates[-1],)):
            by.setdefault(str(sid), {})[d] = ((f or 0) / 1000, (t or 0) / 1000, (de or 0) / 1000)
    return dates, by


def attach_prices(rows: list, latest: str, price_db) -> bool:
    """price_daily 同一天收盤、量（張）、前一天收盤 → close／change_pct／vol_ratio_pct；回 True＝有當天價格"""
    ymd = latest.replace("-", "")
    try:
        with closing(sqlite3.connect(str(price_db), timeout=5.0)) as c:
            cur = {r[0]: (r[1], r[2]) for r in c.execute("SELECT stock_id, close, volume FROM price_daily WHERE date=?", (ymd,))}
            prev_d = c.execute("SELECT MAX(date) FROM price_daily WHERE date<?", (ymd,)).fetchone()[0]
            prev = {r[0]: r[1] for r in c.execute("SELECT stock_id, close FROM price_daily WHERE date=?", (prev_d,))} if prev_d else {}
    except Exception:
        cur, prev = {}, {}
    for r in rows:
        x = cur.get(r["stock_id"])
        if not x:
            r.update(close=None, change_pct=None, vol_ratio_pct=None)
            continue
        close, vol = x
        pc = prev.get(r["stock_id"])
        r["close"] = round(float(close), 2) if close else None
        r["change_pct"] = round((close / pc - 1) * 100, 2) if close and pc else None
        r["vol_ratio_pct"] = round(r["total_lots"] / vol * 100, 1) if vol and vol > 0 else None
    return bool(cur)
