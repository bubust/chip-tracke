"""價格改回「不還原」（跟一般看盤軟體一樣）的一次性修正，2026-10-08 B52。

Yahoo 把台股配股、減資、分割都當成 split：重抓一檔時，事件日之前的整段歷史會換成還原價，
再 INSERT OR REPLACE 進 price_daily → K 線、BB、選股都跟看盤軟體對不上（例：1815 富喬 9/8 存 128.57，官方 135）。
yahoo_price._parse_yahoo_json 已經改成用 split 事件乘回實際成交價，這裡把資料庫裡已經存成還原價的舊資料修掉：

1. 從 price_daily 挑約 26 個交易日（兩年內每 20 個交易日一天），抓證交所 MI_INDEX、櫃買 otc 官方全部收盤
2. 收盤跟官方差超過 0.4% 的股票 → 重抓 Yahoo（新的 parser 會乘回去）覆蓋 price_daily
3. 重抓的股票再跟官方比一次，結果存 chip_data/unadjust_fix.json（/api/admin/unadjust/status 看）
"""
import datetime
import json
import sqlite3
import threading
import time
from pathlib import Path

import httpx

VERSION = 1
RESULT_FILE = Path(__file__).parent / "chip_data" / "unadjust_fix.json"
TOL = 0.004                      # 收盤差超過 0.4% 才算對不上（官方、Yahoo 小數位差很小）
_H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
_state = {"running": False, "phase": "", "done": 0, "total": 0}
_lock = threading.Lock()


def _num(v):
    try:
        x = float(str(v).replace(",", "").strip())
        return x if x > 0 else None
    except Exception:
        return None


def official_closes(date8: str) -> dict:
    """{代號: 收盤}：證交所 MI_INDEX（上市）＋櫃買 otc（上櫃）；當天休市或抓失敗就少那一邊"""
    out = {}
    try:
        j = httpx.get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                      params={"date": date8, "type": "ALLBUT0999", "response": "json"}, headers=_H, timeout=30).json()
        for t in j.get("tables") or []:
            f = [str(x).strip() for x in (t.get("fields") or [])]
            if "證券代號" in f and "收盤價" in f:
                ci, pi = f.index("證券代號"), f.index("收盤價")
                for row in t.get("data") or []:
                    v = _num(row[pi])
                    if v:
                        out[str(row[ci]).strip()] = v
    except Exception as e:
        print(f"[UNADJ] 證交所 {date8} 失敗: {e}")
    time.sleep(3)                # 證交所有頻率限制
    try:
        j = httpx.get("https://www.tpex.org.tw/www/zh-tw/afterTrading/otc",
                      params={"date": f"{date8[:4]}/{date8[4:6]}/{date8[6:]}", "type": "EW", "response": "json"},
                      headers=_H, timeout=30).json()
        for t in j.get("tables") or []:
            f = [str(x).strip() for x in (t.get("fields") or [])]
            if "代號" in f and "收盤" in f:
                ci, pi = f.index("代號"), f.index("收盤")
                for row in t.get("data") or []:
                    v = _num(row[pi])
                    if v:
                        out.setdefault(str(row[ci]).strip(), v)
    except Exception as e:
        print(f"[UNADJ] 櫃買 {date8} 失敗: {e}")
    time.sleep(2)
    return out


def sample_dates(db_path, every: int = 20, span: int = 500) -> list:
    """price_daily 裡有 500 檔以上的交易日（排除今天），取最近 span 天中每 every 天一天＋最後一天"""
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y%m%d")
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT date FROM price_daily WHERE date < ? GROUP BY date HAVING COUNT(*) > 500 ORDER BY date",
                        (today,)).fetchall()
    conn.close()
    dates = [r[0] for r in rows][-span:]
    if not dates:
        return []
    picked = dates[::-1][::every][::-1]       # 從最後一天往回每 every 天取一天
    return picked


def compare(db_path, official: dict, sids=None) -> dict:
    """{代號: [(日期, 存的收盤, 官方收盤), ...]}：對不上的"""
    bad: dict = {}
    conn = sqlite3.connect(str(db_path))
    for d, off in official.items():
        q = "SELECT stock_id, close FROM price_daily WHERE date=?"
        for sid, c in conn.execute(q, (d,)).fetchall():
            if sids is not None and sid not in sids:
                continue
            o = off.get(sid)
            if not o or not c:
                continue
            if abs(float(c) / o - 1) > TOL:
                bad.setdefault(sid, []).append((d, round(float(c), 2), o))
    conn.close()
    return bad


def run(force: bool = False) -> dict:
    """主流程；同時間只跑一個"""
    from price_cache import DB_PATH, save_stock_ohlcv
    from yahoo_price import fetch_yahoo, get_stock_list
    with _lock:
        if _state["running"]:
            return {"error": "running"}
        _state.update(running=True, phase="抽樣日期", done=0, total=0)
    started = time.time()
    try:
        dates = sample_dates(DB_PATH)
        _state.update(phase="抓官方收盤", total=len(dates))
        official = {}
        for d in dates:
            got = official_closes(d)
            if len(got) > 500:
                official[d] = got
            _state["done"] += 1
        if len(official) < max(5, len(dates) // 2):     # 官方抓不到大半 → 不記結果，下次開機再跑
            return {"error": f"官方收盤只抓到 {len(official)}/{len(dates)} 天"}
        bad = compare(DB_PATH, official)
        try:
            sl = get_stock_list()
            mkt = dict(zip(sl["stock_id"], sl["type"]))
        except Exception:
            mkt = {}
        flagged = sorted(bad)
        _state.update(phase="重抓 Yahoo（不還原）", done=0, total=len(flagged))
        fetched, failed = [], []
        for sid in flagged:
            df = None
            for attempt in range(3):
                df = fetch_yahoo(sid, str(mkt.get(sid, "twse")))
                if df is not None and not df.empty and len(df) >= 20:
                    break
                time.sleep(4 + attempt * 4)       # Yahoo 限流：等一下再試
            if df is not None and not df.empty and len(df) >= 20:
                save_stock_ohlcv(sid, df)
                fetched.append(sid)
            else:
                failed.append(sid)
            _state["done"] += 1
            time.sleep(0.6)
        still = compare(DB_PATH, official, set(flagged))
        res = {
            "version": VERSION, "at": (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"),
            "seconds": round(time.time() - started), "sample_dates": sorted(official),
            "flagged": len(flagged), "fetched": len(fetched), "fetch_failed": failed[:50],
            "fixed": len([s for s in flagged if s not in still]),
            "still_bad": {s: v[:3] for s, v in list(still.items())[:40]}, "still_bad_count": len(still),
            "examples_before": {s: bad[s][:2] for s in flagged[:15]},
        }
        RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
        RESULT_FILE.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[UNADJ] 完成：對不上 {len(flagged)} 檔、重抓 {len(fetched)}、修好 {res['fixed']}、還對不上 {len(still)}")
        return res
    except Exception as e:
        print(f"[UNADJ] 失敗: {e}")
        return {"error": str(e)}
    finally:
        _state.update(running=False, phase="")


def status() -> dict:
    out = {"state": dict(_state)}
    try:
        out["result"] = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    except Exception:
        out["result"] = None
    return out


def start_if_needed(delay: int = 120):
    """還沒修過（或版本舊）就在背景跑一次；delay 秒後才開始，不拖慢開機"""
    try:
        done = json.loads(RESULT_FILE.read_text(encoding="utf-8")).get("version") == VERSION
    except Exception:
        done = False
    if done:
        return

    def _go():
        time.sleep(delay)
        run()
    threading.Thread(target=_go, daemon=True, name="unadjust-fix").start()
