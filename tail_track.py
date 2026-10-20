"""
tail_track.py — 🎯 尾盤追蹤（2026-10-20）

追蹤「13:10 假跌破：收盤前還成立」清單裡的股票之後的走勢（尾盤進場）：
- 每天 13:10 清單出來時自動加入（fbd_live 呼叫 add_from_fbd）；也可以手動新增、貼上 Telegram 訊息匯入、編輯、刪除
- 進場價＝13:10 的價格（可改）；停損＝進場價跌 8%（可調）：進場之後任一天盤中最低觸到就移到「停損區」，
  停損價＝停損線（那天開盤就跳空跌破 → 用開盤價），跟網站回測「盤中觸價 8%」同一套
- 其他留在「觀察區」；手動移區之後不再自動移（zone_manual）
資料：chip_data/tail_track.db；股價＝price_daily 快取＋盤中鉅亨／Yahoo 即時價
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()
DB_PATH = Path(__file__).parent / "chip_data" / "tail_track.db"
TW = timezone(timedelta(hours=8))
DEFAULT_STOP = 8.0

# 2026-10-20 13:10 的清單（功能上線前就發了，第一次建表時補進去）
_SEED_DAY = "2026-10-20"
_SEED = [("1809", "中釉", 47.6, 44.11), ("2419", "仲琦", 27.55, 27.37), ("3062", "建漢", 22.6, 22.36),
         ("3231", "緯創", 188.0, 185.3), ("3234", "光環", 184.0, 178.7), ("3490", "單井", 44.35, 44.12),
         ("6224", "聚鼎", 76.8, 76.26), ("8215", "明基材", 29.2, 28.11), ("9933", "中鼎", 43.15, 43.1)]


def get_conn(db_path=None):
    p = Path(db_path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p), timeout=10.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c


def init_db(db_path=None, seed: bool = True):
    c = get_conn(db_path)
    c.executescript("""
        CREATE TABLE IF NOT EXISTS tail_track (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id TEXT NOT NULL,
            name TEXT,
            entry_date TEXT NOT NULL,          -- YYYY-MM-DD（尾盤進場那天）
            entry_price REAL NOT NULL,         -- 13:10 價格（可改）
            ma10 REAL,                         -- 進場時的 MA10
            broke_date TEXT,                   -- 跌破 MA10 那天
            source TEXT,                       -- 13:10 假跌破／手動／匯入
            note TEXT,
            zone TEXT DEFAULT 'watch',         -- watch 觀察區／stop 停損區
            zone_manual INTEGER DEFAULT 0,     -- 1＝手動移過區，不再自動移
            stop_date TEXT, stop_price REAL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE (stock_id, entry_date)
        );
        CREATE TABLE IF NOT EXISTS tail_meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    if seed and not c.execute("SELECT 1 FROM tail_meta WHERE key='seeded'").fetchone():
        for sid, name, px, ma10 in _SEED:
            c.execute("INSERT OR IGNORE INTO tail_track (stock_id, name, entry_date, entry_price, ma10, broke_date, source) "
                      "VALUES (?,?,?,?,?,?,?)", (sid, name, _SEED_DAY, px, ma10, "2026-10-19", "13:10 假跌破"))
        c.execute("INSERT OR REPLACE INTO tail_meta VALUES ('seeded', ?)", (_SEED_DAY,))
    c.commit()
    c.close()


def stop_pct(conn=None) -> float:
    own = conn is None
    c = conn or get_conn()
    r = c.execute("SELECT value FROM tail_meta WHERE key='stop_pct'").fetchone()
    if own:
        c.close()
    try:
        return float(r["value"]) if r else DEFAULT_STOP
    except (TypeError, ValueError):
        return DEFAULT_STOP


def _iso(d: str) -> Optional[str]:
    s = re.sub(r"\D", "", str(d or ""))
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else None


def add(stock_id: str, entry_price: float, entry_date: str, name: str = "", ma10=None, broke_date=None,
        source: str = "手動", note: str = "", db_path=None) -> bool:
    c = get_conn(db_path)
    cur = c.execute("INSERT OR IGNORE INTO tail_track (stock_id, name, entry_date, entry_price, ma10, broke_date, source, note) "
                    "VALUES (?,?,?,?,?,?,?,?)", (stock_id, name, entry_date, entry_price, ma10, broke_date, source, note or None))
    c.commit()
    c.close()
    return cur.rowcount > 0


def add_from_fbd(day: str, items: list, db_path=None) -> int:
    """fbd_live 13:10 清單 → 自動加入（day＝YYYYMMDD；同一天同一檔不重複）"""
    n = 0
    for x in items or []:
        try:
            if add(x["stock_id"], float(x["price"]), _iso(day), x.get("name") or "", x.get("ma10"),
                   _iso(x.get("broke_date")), "13:10 假跌破", db_path=db_path):
                n += 1
        except Exception:
            pass
    return n


_LINE = re.compile(r"(\d{4,6}[A-Z]?)\s+(\S+?)\s+(\d+(?:\.\d+)?)\s*[（(]")
_MA = re.compile(r"MA10\s*(\d+(?:\.\d+)?)")
_BROKE = re.compile(r"(\d{1,2})/(\d{1,2})\s*跌破")


def parse_message(text: str) -> list:
    """貼上的 Telegram 13:10 訊息 → [{stock_id, name, price, ma10, broke_md}]（只取「• 代號 名稱 價格（漲跌）」的列；
    「盤中出現過、現在不成立」那行沒有價格，不會被抓進來）"""
    out = []
    for raw in re.split(r"[\n•]", text or ""):
        line = raw.strip()
        m = _LINE.search(line)
        if not m:
            continue
        ma = _MA.search(line)
        br = _BROKE.search(line)
        out.append({"stock_id": m.group(1), "name": m.group(2), "price": float(m.group(3)),
                    "ma10": float(ma.group(1)) if ma else None,
                    "broke_md": (int(br.group(1)), int(br.group(2))) if br else None})
    return out


# ── 走勢計算 ─────────────────────────────────────────────────────────────────

def _bars(sids, since: str) -> dict:
    """{sid: [(YYYY-MM-DD, open, high, low, close), ...]}（since 當天起，舊到新）"""
    out = {}
    try:
        from chip_tracker_v2 import DB_PATH as PDB
        pc = sqlite3.connect(str(PDB), timeout=5.0)
        for sid in sids:
            rows = pc.execute("SELECT date, open, high, low, close FROM price_daily WHERE stock_id=? AND date>=? AND close>0 "
                              "ORDER BY date", (sid, since.replace("-", ""))).fetchall()
            out[sid] = [(_iso(r[0]), r[1], r[2], r[3], r[4]) for r in rows]
        pc.close()
    except Exception:
        pass
    return out


def _ma10(sid: str, last_close: Optional[float], last_date: Optional[str]) -> Optional[float]:
    try:
        from chip_tracker_v2 import DB_PATH as PDB
        pc = sqlite3.connect(str(PDB), timeout=5.0)
        rows = pc.execute("SELECT date, close FROM price_daily WHERE stock_id=? AND close>0 ORDER BY date DESC LIMIT 10",
                          (sid,)).fetchall()
        pc.close()
    except Exception:
        return None
    closes = [r[1] for r in rows]
    if last_close is not None and last_date and (not rows or _iso(rows[0][0]) < last_date):
        closes = [last_close] + closes[:9]                 # 盤中：今天的即時價當今天那根
    return round(sum(closes) / 10, 2) if len(closes) >= 10 else None


def evaluate(row: dict, bars: list, live: Optional[dict], pct: float) -> dict:
    """row＝資料表一列；bars＝進場日起的日 K；live＝今天即時報價 {close, high, low, open, date}"""
    r = dict(row)
    e = r["entry_price"]
    level = e * (1 - pct / 100)
    after = [b for b in bars if b[0] > r["entry_date"]]
    if live and live.get("date") and live["date"] > r["entry_date"] and not any(b[0] == live["date"] for b in after):
        after.append((live["date"], live.get("open"), live.get("high"), live.get("low"), live["close"]))
    entry_bar = next((b for b in bars if b[0] == r["entry_date"]), None)
    hit = None
    if entry_bar and entry_bar[4] is not None and entry_bar[4] <= level:
        hit = (entry_bar[0], entry_bar[4])                   # 進場當天收盤就跌破
    if not hit:
        for d, o, h, lo, cl in after:
            if lo is not None and lo <= level:
                hit = (d, round(o, 2) if o is not None and o < level else round(level, 2))
                break
    last = after[-1] if after else entry_bar
    price = last[4] if last else None
    r["price"], r["price_date"] = price, last[0] if last else None
    r["days"] = len(after)
    r["ret_pct"] = round((price / e - 1) * 100, 2) if price else None
    highs = [b[2] for b in after if b[2] is not None]
    lows = [b[3] for b in after if b[3] is not None]
    r["max_up_pct"] = round((max(highs) / e - 1) * 100, 2) if highs else None
    r["max_down_pct"] = round((min(lows) / e - 1) * 100, 2) if lows else None
    r["stop_level"] = round(level, 2)
    r["to_stop_pct"] = round((price / level - 1) * 100, 2) if price else None
    r["hit"] = hit
    return r


def _auto_zone(c, r: dict) -> dict:
    """觸到停損線 → 移到停損區（手動移過的不動）"""
    if r["hit"] and r["zone"] == "watch" and not r["zone_manual"]:
        c.execute("UPDATE tail_track SET zone='stop', stop_date=?, stop_price=? WHERE id=?", (r["hit"][0], r["hit"][1], r["id"]))
        r["zone"], r["stop_date"], r["stop_price"] = "stop", r["hit"][0], r["hit"][1]
    if r["zone"] == "stop" and r.get("stop_price"):
        r["stop_ret_pct"] = round((r["stop_price"] / r["entry_price"] - 1) * 100, 2)
    return r


async def build_list(db_path=None, live_fn=None) -> dict:
    c = get_conn(db_path)
    rows = [dict(x) for x in c.execute("SELECT * FROM tail_track ORDER BY entry_date DESC, stock_id")]
    pct = stop_pct(c)
    sids = sorted({r["stock_id"] for r in rows})
    since = min((r["entry_date"] for r in rows), default=datetime.now(TW).date().isoformat())
    bars = _bars(sids, since)
    live = {}
    if sids:
        try:
            if live_fn is None:
                from server import _fetch_rt_quotes
                from yahoo_price import get_stock_list
                df = get_stock_list()
                live = await _fetch_rt_quotes(sids, dict(zip(df["stock_id"], df["type"])))
            else:
                live = await live_fn(sids)
        except Exception:
            live = {}
    out = []
    for r in rows:
        q = live.get(r["stock_id"])
        if q and q.get("date"):
            q = {**q, "date": _iso(q["date"]) or q["date"]}
        x = _auto_zone(c, evaluate(r, bars.get(r["stock_id"], []), q, pct))
        x["ma10_now"] = _ma10(r["stock_id"], x["price"], x["price_date"])
        x["above_ma10"] = (x["price"] >= x["ma10_now"]) if x["price"] and x["ma10_now"] else None
        x.pop("hit", None)
        out.append(x)
    c.commit()
    c.close()
    return {"rows": out, "stop_pct": pct}


# ── API ──────────────────────────────────────────────────────────────────────

def _check_sid(sid: str) -> str:
    sid = (sid or "").strip().upper()
    if not re.fullmatch(r"[0-9A-Z]{4,6}", sid):
        raise HTTPException(400, "股票代號格式不正確")
    return sid


def _today() -> str:
    return datetime.now(TW).date().isoformat()


@router.get("/api/tail/list")
async def api_list():
    return await build_list()


class Item(BaseModel):
    stock_id: str
    entry_price: Optional[float] = None
    entry_date: Optional[str] = None
    name: Optional[str] = ""
    note: Optional[str] = ""


def _clean_note(v) -> Optional[str]:
    v = "".join(ch for ch in str(v or "") if ch >= " ").strip()[:200]
    return v or None


@router.post("/api/tail")
async def api_add(it: Item):
    sid = _check_sid(it.stock_id)
    d = _iso(it.entry_date) or _today()
    px, name = it.entry_price, (it.name or "").strip()[:20]
    if not px or not name:
        try:
            from server import _rt_quote_sync
            q = _rt_quote_sync(sid) or {}
        except Exception:
            q = {}
        px = px or q.get("close")
        if not name:
            try:
                from yahoo_price import get_stock_list
                df = get_stock_list()
                name = dict(zip(df["stock_id"], df["stock_name"])).get(sid, "")
            except Exception:
                pass
    if not px or px <= 0:
        raise HTTPException(400, "抓不到現價，請自己填進場價")
    if not add(sid, round(float(px), 2), d, name, source="手動", note=_clean_note(it.note) or ""):
        raise HTTPException(400, f"{sid} 在 {d} 已經在追蹤清單裡")
    return {"ok": True}


class Edit(BaseModel):
    entry_price: Optional[float] = None
    entry_date: Optional[str] = None
    note: Optional[str] = None
    zone: Optional[str] = None


@router.put("/api/tail/{tid}")
def api_edit(tid: int, e: Edit):
    c = get_conn()
    row = c.execute("SELECT * FROM tail_track WHERE id=?", (tid,)).fetchone()
    if not row:
        c.close()
        raise HTTPException(404, "找不到這筆")
    sets, vals = [], []
    if e.entry_price is not None:
        if e.entry_price <= 0:
            c.close()
            raise HTTPException(400, "進場價要大於 0")
        sets += ["entry_price=?"]; vals += [round(e.entry_price, 2)]
    if e.entry_date:
        d = _iso(e.entry_date)
        if not d:
            c.close()
            raise HTTPException(400, "日期格式不正確")
        sets += ["entry_date=?"]; vals += [d]
    if e.note is not None:
        sets += ["note=?"]; vals += [_clean_note(e.note)]
    if e.zone in ("watch", "stop"):
        sets += ["zone=?", "zone_manual=1"]; vals += [e.zone]
        if e.zone == "watch":
            sets += ["stop_date=NULL", "stop_price=NULL"]
    if (e.entry_price is not None or e.entry_date) and e.zone is None:
        # 改了進場價／日期 → 重新判斷停損（清掉舊的自動停損）
        sets += ["zone=CASE WHEN zone_manual=1 THEN zone ELSE 'watch' END",
                 "stop_date=CASE WHEN zone_manual=1 THEN stop_date ELSE NULL END",
                 "stop_price=CASE WHEN zone_manual=1 THEN stop_price ELSE NULL END"]
    if sets:
        try:
            c.execute(f"UPDATE tail_track SET {', '.join(sets)} WHERE id=?", (*vals, tid))
            c.commit()
        except sqlite3.IntegrityError:
            c.close()
            raise HTTPException(400, "同一檔同一天已經有一筆")
    c.close()
    return {"ok": True}


@router.delete("/api/tail/{tid}")
def api_delete(tid: int):
    c = get_conn()
    c.execute("DELETE FROM tail_track WHERE id=?", (tid,))
    c.commit()
    c.close()
    return {"ok": True}


@router.post("/api/tail/import")
async def api_import(request: Request):
    """貼上 Telegram 13:10 訊息：body {text, date?}；日期沒給＝今天"""
    body = await request.json()
    text = str(body.get("text") or "")[:20000]
    d = _iso(body.get("date")) or _today()
    items = parse_message(text)
    if not items:
        raise HTTPException(400, "沒有找到「• 代號 名稱 價格（漲跌）」格式的股票")
    n = 0
    for x in items:
        y = int(d[:4])
        broke = f"{y}-{x['broke_md'][0]:02d}-{x['broke_md'][1]:02d}" if x["broke_md"] else None
        if add(x["stock_id"], x["price"], d, x["name"], x["ma10"], broke, "匯入"):
            n += 1
    return {"ok": True, "found": len(items), "added": n}


@router.put("/api/tail/settings/stop")
async def api_stop(request: Request):
    body = await request.json()
    try:
        v = float(body.get("stop_pct"))
    except (TypeError, ValueError):
        raise HTTPException(400, "停損 % 要是數字")
    if not 1 <= v <= 50:
        raise HTTPException(400, "停損 % 要在 1～50 之間")
    c = get_conn()
    c.execute("INSERT OR REPLACE INTO tail_meta VALUES ('stop_pct', ?)", (str(v),))
    # 改停損 % → 自動移進停損區的全部重新判斷
    c.execute("UPDATE tail_track SET zone='watch', stop_date=NULL, stop_price=NULL WHERE zone_manual=0")
    c.commit()
    c.close()
    return {"ok": True, "stop_pct": v}
