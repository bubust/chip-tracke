"""戰略討論區資料表（chip_data/discuss.db，WAL）
- discuss_session：每次貼對話分析一筆（原文、讀出來的逐字稿、AI 結果 JSON、對話日期）
- discuss_stock：這次提到／同族群的股票＋當時價格（追蹤「老大哥提過的股票後來表現」）
- discuss_alias：使用者確認過的暱稱 → 股票（「新棒」選過一次就記住，下次直接對上）
"""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "chip_data" / "discuss.db"


def get_conn(db_path=None):
    p = Path(db_path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p), timeout=10.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c


def init_db(db_path=None):
    c = get_conn(db_path)
    c.executescript("""
        CREATE TABLE IF NOT EXISTS discuss_session (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            chat_date TEXT,                   -- 對話日期 YYYY-MM-DD（記錄價用這天收盤）
            title TEXT,                       -- 題材名稱（列表顯示）
            source_text TEXT,                 -- 使用者貼的文字
            image_count INTEGER DEFAULT 0,
            transcript TEXT,                  -- 截圖讀出來＋文字的逐字稿
            result_json TEXT,                 -- AI 結果（已對過股票代號）
            sources_json TEXT,                -- Google 搜尋來源
            model TEXT,
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS discuss_stock (
            session_id INTEGER NOT NULL,
            stock_id TEXT NOT NULL,
            name TEXT,
            kind TEXT,                        -- mentioned 對話提到 / related 同族群
            role TEXT,                        -- leader 大哥 / follower 小弟 / ''
            mention_text TEXT,                -- 對話裡的寫法
            price_at REAL,                    -- 對話日期當天（或之前最近一天）收盤
            price_date TEXT,
            PRIMARY KEY (session_id, stock_id)
        );
        CREATE INDEX IF NOT EXISTS idx_ds_stock ON discuss_stock(stock_id);
        CREATE TABLE IF NOT EXISTS discuss_alias (
            alias TEXT PRIMARY KEY,           -- 對話裡的寫法（暱稱、錯字）
            stock_id TEXT NOT NULL,
            name TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
    """)
    c.commit()
    c.close()


def get_aliases(db_path=None) -> dict:
    c = get_conn(db_path)
    rows = c.execute("SELECT alias, stock_id, name FROM discuss_alias").fetchall()
    c.close()
    return {r["alias"]: {"stock_id": r["stock_id"], "name": r["name"] or ""} for r in rows}


def set_alias(alias: str, stock_id: str, name: str, db_path=None):
    c = get_conn(db_path)
    c.execute("INSERT INTO discuss_alias(alias, stock_id, name, updated_at) VALUES (?,?,?,datetime('now','localtime')) "
              "ON CONFLICT(alias) DO UPDATE SET stock_id=excluded.stock_id, name=excluded.name, updated_at=excluded.updated_at",
              (alias, stock_id, name))
    c.commit()
    c.close()


def delete_alias(alias: str, db_path=None):
    c = get_conn(db_path)
    c.execute("DELETE FROM discuss_alias WHERE alias=?", (alias,))
    c.commit()
    c.close()


def save_session(row: dict, stocks: list, db_path=None) -> int:
    c = get_conn(db_path)
    cur = c.execute(
        "INSERT INTO discuss_session(chat_date, title, source_text, image_count, transcript, result_json, sources_json, model) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (row["chat_date"], row.get("title"), row.get("source_text"), row.get("image_count", 0), row.get("transcript"),
         json.dumps(row.get("result"), ensure_ascii=False), json.dumps(row.get("sources") or [], ensure_ascii=False),
         row.get("model")))
    sid = cur.lastrowid
    _write_stocks(c, sid, stocks)
    c.commit()
    c.close()
    return sid


def _write_stocks(c, session_id: int, stocks: list):
    c.execute("DELETE FROM discuss_stock WHERE session_id=?", (session_id,))
    for s in stocks:
        c.execute("INSERT OR REPLACE INTO discuss_stock(session_id, stock_id, name, kind, role, mention_text, price_at, price_date) "
                  "VALUES (?,?,?,?,?,?,?,?)",
                  (session_id, s["stock_id"], s.get("name"), s.get("kind"), s.get("role") or "", s.get("mention_text") or "",
                   s.get("price_at"), s.get("price_date")))


def update_session(session_id: int, result: dict, stocks: list, title: str = None, db_path=None):
    c = get_conn(db_path)
    c.execute("UPDATE discuss_session SET result_json=?, title=COALESCE(?, title) WHERE id=?",
              (json.dumps(result, ensure_ascii=False), title, session_id))
    _write_stocks(c, session_id, stocks)
    c.commit()
    c.close()


def update_price_at(rows: list, db_path=None):
    """rows: [(session_id, stock_id, price, date)]"""
    if not rows:
        return
    c = get_conn(db_path)
    c.executemany("UPDATE discuss_stock SET price_at=?, price_date=? WHERE session_id=? AND stock_id=?",
                  [(p, d, s, sid) for s, sid, p, d in rows])
    c.commit()
    c.close()


def update_note(session_id: int, note: str, db_path=None):
    c = get_conn(db_path)
    c.execute("UPDATE discuss_session SET note=? WHERE id=?", (note, session_id))
    c.commit()
    c.close()


def get_session(session_id: int, db_path=None):
    c = get_conn(db_path)
    r = c.execute("SELECT * FROM discuss_session WHERE id=?", (session_id,)).fetchone()
    if not r:
        c.close()
        return None
    stocks = [dict(x) for x in c.execute("SELECT * FROM discuss_stock WHERE session_id=?", (session_id,))]
    c.close()
    out = dict(r)
    out["result"] = json.loads(out.pop("result_json") or "{}")
    out["sources"] = json.loads(out.pop("sources_json") or "[]")
    out["stocks"] = stocks
    return out


def list_sessions(limit: int = 200, db_path=None) -> list:
    c = get_conn(db_path)
    rows = [dict(r) for r in c.execute(
        "SELECT id, created_at, chat_date, title, image_count, model, note FROM discuss_session ORDER BY chat_date DESC, id DESC LIMIT ?",
        (limit,))]
    by = {}
    for s in c.execute("SELECT * FROM discuss_stock WHERE session_id IN (SELECT id FROM discuss_session ORDER BY id DESC LIMIT ?)",
                       (limit,)):
        by.setdefault(s["session_id"], []).append(dict(s))
    c.close()
    for r in rows:
        r["stocks"] = by.get(r["id"], [])
    return rows


def delete_session(session_id: int, db_path=None):
    c = get_conn(db_path)
    c.execute("DELETE FROM discuss_stock WHERE session_id=?", (session_id,))
    c.execute("DELETE FROM discuss_session WHERE id=?", (session_id,))
    c.commit()
    c.close()


def count_today(db_path=None) -> int:
    c = get_conn(db_path)
    n = c.execute("SELECT COUNT(*) FROM discuss_session WHERE date(created_at)=date('now','localtime')").fetchone()[0]
    c.close()
    return n
