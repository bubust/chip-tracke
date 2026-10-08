"""價格改回「不還原」（跟一般看盤軟體一樣），2026-10-08 B52／B53。

Yahoo 把台股配股、減資、分割當 split，重抓一檔時事件日之前的整段歷史換成還原價，再 INSERT OR REPLACE 進 price_daily
→ K 線、BB、選股都跟看盤軟體對不上（例：1815 富喬 9/8 存 128.57，官方 135）。
B52 用 Yahoo 的 split 事件乘回去只修好 251/351 檔：Yahoo 有的事件沒列（0050 一拆四完全沒有事件）、
有的舊價格又差好幾 %（1815 2024 年 21.2 vs 官方 21.8），有的根本抓不到 → 不能靠 Yahoo。

VERSION 2：直接用官方每日全部行情重建 price_daily（證交所 MI_INDEX、櫃買 otc，跟看盤軟體同一份）：
- 範圍：price_daily 裡近 760 天、有 500 檔以上的交易日（今天不算）
- 每天：抓官方 → 只寫 price_daily 原本就有的股票（不多塞 ETN／特別股），INSERT OR REPLACE
- 可續跑：進度存 chip_data/unadjust_fix.json，部署重開機會從沒做完的日子接著做
- 之後 Yahoo 只能補缺的日子、不能蓋掉已經有的（price_cache.save_stock_ohlcv 改 INSERT OR IGNORE）
"""
import datetime
import json
import sqlite3
import threading
import time
from pathlib import Path

import httpx

VERSION = 2
RESULT_FILE = Path(__file__).parent / "chip_data" / "unadjust_fix.json"
TOL = 0.004
_H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
_state = {"running": False, "phase": "", "done": 0, "total": 0}
_lock = threading.Lock()


def _num(v):
    try:
        x = float(str(v).replace(",", "").strip())
        return x if x > 0 else None
    except Exception:
        return None


def _rows_from_table(t: dict, date8: str, cols: tuple) -> list:
    """官方表格 → price_daily 列；cols＝(代號, 名稱, 成交股數, 開, 高, 低, 收) 的欄名"""
    f = [str(x).strip() for x in (t.get("fields") or [])]
    if any(c not in f for c in cols):
        return []
    ix = [f.index(c) for c in cols]
    out = []
    for row in t.get("data") or []:
        try:
            sid, name, sh, o, h, lo, c = (row[i] for i in ix)
        except Exception:
            continue
        c = _num(c)
        if not c:                      # 沒成交（--）不寫
            continue
        shares = _num(sh) or 0
        out.append({"date": date8, "stock_id": str(sid).strip(), "name": str(name).strip(),
                    "open": _num(o) or c, "high": _num(h) or c, "low": _num(lo) or c, "close": c,
                    "volume": round(shares / 1000)})
    return out


def official_day(date8: str):
    """(證交所列, 櫃買列)：抓失敗的那邊回 None"""
    twse = tpex = None
    try:
        j = httpx.get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                      params={"date": date8, "type": "ALLBUT0999", "response": "json"}, headers=_H, timeout=40).json()
        twse = []
        for t in j.get("tables") or []:
            twse += _rows_from_table(t, date8, ("證券代號", "證券名稱", "成交股數", "開盤價", "最高價", "最低價", "收盤價"))
    except Exception as e:
        print(f"[UNADJ] 證交所 {date8} 失敗: {e}")
    time.sleep(3)                       # 證交所頻率限制（約 5 秒 3 次）
    try:
        j = httpx.get("https://www.tpex.org.tw/www/zh-tw/afterTrading/otc",
                      params={"date": f"{date8[:4]}/{date8[4:6]}/{date8[6:]}", "type": "EW", "response": "json"},
                      headers=_H, timeout=40).json()
        tpex = []
        for t in j.get("tables") or []:
            tpex += _rows_from_table(t, date8, ("代號", "名稱", "成交股數", "開盤", "最高", "最低", "收盤"))
    except Exception as e:
        print(f"[UNADJ] 櫃買 {date8} 失敗: {e}")
    time.sleep(2)
    return twse, tpex


def rebuild_dates(db_path, days: int = 760) -> list:
    tw_now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    today = tw_now.strftime("%Y%m%d")
    start = (tw_now - datetime.timedelta(days=days)).strftime("%Y%m%d")
    conn = sqlite3.connect(str(db_path), timeout=30)
    rows = conn.execute("SELECT date FROM price_daily WHERE date >= ? AND date < ? GROUP BY date HAVING COUNT(*) > 500 "
                        "ORDER BY date DESC", (start, today)).fetchall()
    conn.close()
    return [r[0] for r in rows]          # 新的先做：最近的資料最常用


def _load():
    try:
        return json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(res: dict):
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def run(force: bool = False) -> dict:
    """主流程（同時間只跑一個）；force＝已經做完也重做"""
    from price_cache import DB_PATH
    with _lock:
        if _state["running"]:
            return {"error": "running"}
        _state.update(running=True, phase="準備", done=0, total=0)
    started = time.time()
    try:
        prev = _load()
        if prev.get("version") != VERSION or force:
            prev = {}
        res = {"version": VERSION, "status": "running", "done_dates": prev.get("done_dates", []),
               "failed_dates": [], "rows_written": prev.get("rows_written", 0), "rows_changed": prev.get("rows_changed", 0),
               "examples": prev.get("examples", {}), "started": prev.get("started") or
               (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")}
        done = set(res["done_dates"])
        dates = [d for d in rebuild_dates(DB_PATH) if d not in done]
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        known = {r[0] for r in conn.execute("SELECT DISTINCT stock_id FROM price_daily").fetchall()}
        conn.close()
        _state.update(phase="官方行情重建 price_daily", done=0, total=len(dates))
        for i, d in enumerate(dates):
            twse, tpex = official_day(d)
            if twse is None or tpex is None or len(twse or []) + len(tpex or []) < 500:
                res["failed_dates"].append(d)
                _state["done"] += 1
                continue
            recs = [r for r in twse + tpex if r["stock_id"] in known]
            conn = sqlite3.connect(str(DB_PATH), timeout=30)
            old = dict(conn.execute("SELECT stock_id, close FROM price_daily WHERE date=?", (d,)).fetchall())
            for r in recs:
                o = old.get(r["stock_id"])
                if o and abs(float(o) / r["close"] - 1) > TOL:
                    res["rows_changed"] += 1
                    if len(res["examples"]) < 30 and r["stock_id"] not in res["examples"]:
                        res["examples"][r["stock_id"]] = [d, round(float(o), 2), r["close"]]
            conn.executemany("INSERT OR REPLACE INTO price_daily (date,stock_id,name,open,high,low,close,volume) "
                             "VALUES (:date,:stock_id,:name,:open,:high,:low,:close,:volume)", recs)
            conn.commit()
            conn.close()
            res["rows_written"] += len(recs)
            res["done_dates"].append(d)
            _state["done"] += 1
            if i % 5 == 0:
                _save(res)
        res["status"] = "done" if not res["failed_dates"] else "done_with_failures"
        res["finished"] = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
        res["seconds_this_run"] = round(time.time() - started)
        _save(res)
        print(f"[UNADJ] 完成：{len(res['done_dates'])} 天、寫 {res['rows_written']} 列、改 {res['rows_changed']} 列、失敗 {res['failed_dates']}")
        return res
    except Exception as e:
        print(f"[UNADJ] 失敗: {e}")
        return {"error": str(e)}
    finally:
        _state.update(running=False, phase="")


def status() -> dict:
    r = _load()
    if r.get("done_dates"):
        r = {**r, "done_dates": f"{len(r['done_dates'])} 天（{min(r['done_dates'])}～{max(r['done_dates'])}）"}
    return {"state": dict(_state), "result": r or None}


def start_if_needed(delay: int = 120):
    """還沒做完（或版本舊）就在背景跑；delay 秒後才開始，不拖慢開機"""
    r = _load()
    if r.get("version") == VERSION and r.get("status") == "done":
        return

    def _go():
        time.sleep(delay)
        run()
    threading.Thread(target=_go, daemon=True, name="unadjust-fix").start()
