"""
可轉債 API

GET  /api/cb/list           篩選結果（tier：buy 可以買 / chance 有機會 / exit 該出場 / watch 觀察）
GET  /api/cb/status         資料狀態＋更新進度
POST /api/cb/refresh        背景更新（發行資料、行情、融券、營收、轉換價調整）
PUT  /api/cb/manual/{code}  手動補目前轉換價、CB 股東人數、備註
"""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from . import db
from . import fetcher as F
from .parser import series_of
from .screener import evaluate

router = APIRouter()
_TW = timezone(timedelta(hours=8))
_job = {"running": False, "step": "", "progress": 0, "total": 0}
_lock = threading.Lock()
_cache = {"t": 0, "data": None}


def tw_today() -> date:
    return datetime.now(_TW).date()


def _step(name, done=0, total=0):
    with _lock:
        _job.update(step=name, progress=done, total=total)


def _weekdays_back(n_days: int) -> list:
    d, out = tw_today(), []
    for _ in range(n_days):
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def run_refresh(full: bool = False) -> dict:
    with _lock:
        if _job["running"]:
            return {"ok": False, "message": "已在更新中"}
        _job.update(running=True, step="開始", progress=0, total=0)
    msgs, errs = [], []
    try:
        c = db.get_conn()
        with F.client() as cl:
            # 1. 發行資料
            _step("可轉債發行資料")
            try:
                bonds = F.fetch_bonds(cl)
                now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M")
                for b in bonds:
                    c.execute("""INSERT OR REPLACE INTO cb_bond(code,name,sid,issuer,issue_date,maturity_date,issue_amt,
                                 outstanding,conv_price_issue,conv_start,conv_end,put_date,put_price,updated)
                                 VALUES (:code,:name,:sid,:issuer,:issue_date,:maturity_date,:issue_amt,:outstanding,
                                 :conv_price_issue,:conv_start,:conv_end,:put_date,:put_price,:u)""", {**b, "u": now})
                live = {b["code"] for b in bonds}
                if live:
                    old = [r[0] for r in c.execute("SELECT code FROM cb_bond")]
                    for code in old:
                        if code not in live:
                            c.execute("DELETE FROM cb_bond WHERE code=?", (code,))
                c.commit()
                msgs.append(f"{len(bonds)} 檔掛牌可轉債")
            except Exception as e:
                errs.append(f"發行資料：{e}")
            # 2. 每日行情（缺的日子補；第一次補 45 天）
            have = {r[0] for r in c.execute("SELECT DISTINCT date FROM cb_quote")}
            days = _weekdays_back(65 if (full or len(have) < 20) else 8)
            todo = [d for d in days if d.isoformat() not in have]
            n_q = 0
            for k, d in enumerate(todo, 1):
                _step("可轉債每日行情", k, len(todo))
                try:
                    rows = F.fetch_quotes(cl, d)
                except Exception as e:
                    errs.append(f"{d} 行情：{e}")
                    continue
                for q in rows:
                    c.execute("INSERT OR REPLACE INTO cb_quote(date,code,close,chg,volume,amount,avg,ref) VALUES (?,?,?,?,?,?,?,?)",
                              (d.isoformat(), q["code"], q["close"], q["chg"], q["volume"], q["amount"], q["avg"], q["ref"]))
                if rows:
                    n_q += 1
                c.commit()
                time.sleep(0.4)
            msgs.append(f"行情補 {n_q} 天")
            # 3. 融券餘額（有行情的交易日、最近 25 天，只存有發可轉債的公司）
            sids = {r[0] for r in c.execute("SELECT DISTINCT sid FROM cb_bond")}
            qdays = [r[0] for r in c.execute("SELECT DISTINCT date FROM cb_quote ORDER BY date DESC LIMIT 25")]
            have_s = {r[0] for r in c.execute("SELECT DISTINCT date FROM cb_stock")}
            todo_s = [d for d in qdays if d not in have_s]
            for k, ds in enumerate(todo_s, 1):
                _step("融券餘額", k, len(todo_s))
                m = F.fetch_short_day(cl, date.fromisoformat(ds))
                if not m and ds == qdays[0]:
                    m = F.fetch_short_latest(cl)
                for sid in sids:
                    if sid in m:
                        c.execute("INSERT OR REPLACE INTO cb_stock(date,sid,short_bal) VALUES (?,?,?)", (ds, sid, m[sid]))
                c.commit()
                time.sleep(0.8)
            # 4. 月營收
            _step("月營收")
            rev = F.fetch_revenue(cl)
            now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M")
            for sid, v in rev.items():
                if sid in sids:
                    c.execute("INSERT OR REPLACE INTO cb_rev(sid,ym,yoy,mom,cum_yoy,updated) VALUES (?,?,?,?,?,?)",
                              (sid, v["ym"], v["yoy"], v["mom"], v["cum_yoy"], now))
            c.commit()
            # 5. 轉換價格調整（第一次回補約一年）
            first = not c.execute("SELECT value FROM cb_status WHERE key='conv_scanned'").fetchone()
            n_days = 260 if (first or full) else 6
            adj = F.scan_conv_adjust(cl, n_days, progress=lambda k, t: _step("轉換價格調整公告", k, t))
            for a in adj:
                c.execute("INSERT OR REPLACE INTO cb_conv_adj(sid,series,date,price,subject) VALUES (?,?,?,?,?)",
                          (a["sid"], a["series"], a["date"], a["price"], a["subject"]))
            c.commit()
            if adj or n_days >= 200:
                c.execute("INSERT OR REPLACE INTO cb_status(key,value) VALUES ('conv_scanned', ?)", (tw_today().isoformat(),))
                c.commit()
            msgs.append(f"轉換價調整公告 {len(adj)} 則")
        c.close()
        msg = "、".join(msgs)
        db.set_status(last_refresh=datetime.now(_TW).strftime("%Y-%m-%d %H:%M"), last_message=msg,
                      last_errors="\n".join(errs[:6]) or None)
        _cache["data"] = None
        return {"ok": True, "message": msg}
    except Exception as e:
        db.set_status(last_refresh=datetime.now(_TW).strftime("%Y-%m-%d %H:%M"), last_message=f"更新失敗：{e}")
        return {"ok": False, "message": str(e)}
    finally:
        with _lock:
            _job.update(running=False, step="")


@router.post("/api/cb/refresh")
def refresh(full: bool = Query(False)):
    with _lock:
        if _job["running"]:
            return {"ok": False, "message": "已在更新中"}
    threading.Thread(target=run_refresh, args=(full,), daemon=True, name="cb-refresh").start()
    return {"ok": True, "message": "開始更新可轉債資料（第一次要回補行情與轉換價公告，約 10～15 分鐘）"}


@router.get("/api/cb/status")
def status():
    s = db.get_status()
    with _lock:
        s["job"] = dict(_job)
    return s


def _price_history(sids) -> dict:
    """{sid: [(YYYYMMDD, close), ...]}（約一年，舊到新）"""
    out = {}
    try:
        from chip_tracker_v2 import DB_PATH
        pc = sqlite3.connect(str(DB_PATH), timeout=5.0)
        since = (tw_today() - timedelta(days=420)).strftime("%Y%m%d")
        for sid in sids:
            rows = pc.execute("SELECT date, close FROM price_daily WHERE stock_id=? AND close>0 AND date>=? ORDER BY date",
                              (sid, since)).fetchall()
            if rows:
                out[sid] = [(r[0], float(r[1])) for r in rows]
        pc.close()
    except Exception:
        pass
    return out


def build_list(conn=None, today: date = None, prices: dict = None) -> list:
    today = today or tw_today()
    own = conn is None
    c = conn or db.get_conn()
    bonds = [dict(r) for r in c.execute("SELECT * FROM cb_bond WHERE maturity_date IS NULL OR maturity_date>=?",
                                        (today.isoformat(),))]
    since = (today - timedelta(days=60)).isoformat()
    quotes = {}
    for r in c.execute("SELECT * FROM cb_quote WHERE date>=? ORDER BY date", (since,)):
        quotes.setdefault(r["code"], []).append(dict(r))
    shorts = {}
    for r in c.execute("SELECT date, sid, short_bal FROM cb_stock ORDER BY date"):
        shorts.setdefault(r["sid"], []).append((r["date"], r["short_bal"]))
    revs = {r["sid"]: dict(r) for r in c.execute("SELECT * FROM cb_rev")}
    adjs = {}
    for r in c.execute("SELECT sid, series, date, price FROM cb_conv_adj ORDER BY date"):
        adjs[(r["sid"], r["series"])] = (r["date"], r["price"])
    manual = {r["code"]: dict(r) for r in c.execute("SELECT * FROM cb_manual")}
    if own:
        c.close()
    prices = prices if prices is not None else _price_history({b["sid"] for b in bonds})
    out = []
    for b in bonds:
        m = manual.get(b["code"]) or {}
        a = adjs.get((b["sid"], series_of(b["code"], b["sid"])))
        if m.get("conv_price"):
            conv, src = m["conv_price"], "手動"
        elif a and (not b.get("issue_date") or a[0] >= b["issue_date"][:7]):
            conv, src = a[1], f"{a[0]} 公告調整"
        else:
            conv, src = b.get("conv_price_issue"), "發行時"
        closes = prices.get(b["sid"], [])
        ma60 = sum(x[1] for x in closes[-60:]) / 60 if len(closes) >= 60 else None
        r = evaluate(b, conv, src, quotes.get(b["code"], []), closes, shorts.get(b["sid"], []),
                     revs.get(b["sid"]), today, ma60=ma60, holders=m.get("holders"))
        r["note"] = m.get("note")
        out.append(r)
    order = {"buy": 0, "chance": 1, "exit": 2, "watch": 3}
    out.sort(key=lambda r: (order[r["tier"]], -r["score"], r["code"]))
    return out


@router.get("/api/cb/list")
def list_cb():
    now = time.time()
    if not _cache["data"] or now - _cache["t"] > 300:
        _cache.update(t=now, data=build_list())
    rows = _cache["data"]
    counts = {}
    for r in rows:
        counts[r["tier"]] = counts.get(r["tier"], 0) + 1
    return {"rows": rows, "counts": counts, "status": status()}


class Manual(BaseModel):
    conv_price: Optional[float] = None
    holders: Optional[int] = None
    note: Optional[str] = ""


@router.put("/api/cb/manual/{code}")
def set_manual(code: str, m: Manual):
    if not code.isalnum() or len(code) > 8:
        raise HTTPException(400, "代號格式不正確")
    if m.conv_price is not None and not (0 < m.conv_price < 100000):
        raise HTTPException(400, "轉換價不合理")
    note = "".join(ch for ch in (m.note or "") if ch >= " ").strip()[:300] or None
    c = db.get_conn()
    c.execute("INSERT OR REPLACE INTO cb_manual(code, conv_price, holders, note) VALUES (?,?,?,?)",
              (code, m.conv_price, m.holders, note))
    c.commit()
    c.close()
    _cache["data"] = None
    return {"ok": True}
