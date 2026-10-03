"""收購併購資料表（chip_data/mna.db，WAL）"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "chip_data" / "mna.db"

FIELDS = ["target_id", "target_name", "acquirer", "deal_type", "announce_date", "offer_price",
          "min_shares", "max_shares", "offer_pct", "scope", "period_start", "period_end",
          "consideration", "status_override", "source", "subject", "notes"]


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
        CREATE TABLE IF NOT EXISTS mna_deal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id TEXT NOT NULL,          -- 被收購（標的）公司代號
            target_name TEXT,
            acquirer TEXT,                    -- 收購方 / 合併存續公司
            deal_type TEXT,                   -- 公開收購 / 合併 / 股份轉換 / 收購股權 / 其他
            announce_date TEXT,               -- 公告日 YYYY-MM-DD
            offer_price REAL,                 -- 每股收購價（元）
            min_shares REAL,                  -- 最低收購數量（股）
            max_shares REAL,                  -- 預定收購數量上限（股）
            offer_pct REAL,                   -- 預定收購比例（佔已發行 %）
            scope TEXT,                       -- 完全收購 / 部分收購 / 未知
            period_start TEXT,                -- 收購期間起
            period_end TEXT,                  -- 收購期間迄
            consideration TEXT,               -- 現金 / 換股 / 現金＋換股
            status_override TEXT,             -- 手動狀態（取消、完成…）
            source TEXT,                      -- MOPS / 手動 / 匯入
            subject TEXT,                     -- 重大訊息主旨原文
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE (target_id, announce_date, subject)
        );
        CREATE TABLE IF NOT EXISTS mna_status (key TEXT PRIMARY KEY, value TEXT);
    """)
    c.commit()
    c.close()


def upsert_auto(recs: list, db_path=None) -> dict:
    """自動發現的資料：同公司同日同主旨視為同一筆；只補空欄位，不蓋掉手動填的值"""
    c = get_conn(db_path)
    ins = upd = 0
    for r in recs:
        row = c.execute("SELECT * FROM mna_deal WHERE target_id=? AND announce_date=? AND subject=?",
                        (r["target_id"], r.get("announce_date"), r.get("subject"))).fetchone()
        if row is None:
            cols = [f for f in FIELDS if r.get(f) not in (None, "")]
            c.execute(f"INSERT INTO mna_deal ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                      [r[k] for k in cols])
            ins += 1
        else:
            fill = {f: r[f] for f in FIELDS if r.get(f) not in (None, "") and row[f] in (None, "")}
            if fill:
                c.execute(f"UPDATE mna_deal SET {','.join(k + '=?' for k in fill)},updated_at=datetime('now','localtime') WHERE id=?",
                          [*fill.values(), row["id"]])
                upd += 1
    c.commit()
    c.close()
    return {"inserted": ins, "updated": upd}


def save_manual(data: dict, deal_id: int = None, db_path=None) -> int:
    vals = {f: data.get(f) for f in FIELDS if f in data}
    c = get_conn(db_path)
    if deal_id:
        if vals:
            c.execute(f"UPDATE mna_deal SET {','.join(k + '=?' for k in vals)},updated_at=datetime('now','localtime') WHERE id=?",
                      [*vals.values(), deal_id])
        new_id = deal_id
    else:
        vals.setdefault("source", "手動")
        vals.setdefault("subject", "")
        cols = list(vals)
        cur = c.execute(f"INSERT INTO mna_deal ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [vals[k] for k in cols])
        new_id = cur.lastrowid
    c.commit()
    c.close()
    return new_id


def delete(deal_id: int, db_path=None):
    c = get_conn(db_path)
    c.execute("DELETE FROM mna_deal WHERE id=?", (deal_id,))
    c.commit()
    c.close()


def all_rows(since: str = None, db_path=None) -> list:
    c = get_conn(db_path)
    q, a = "SELECT * FROM mna_deal", []
    if since:
        q += " WHERE COALESCE(announce_date,'') >= ? OR COALESCE(period_end,'') >= ?"
        a = [since, since]
    rows = [dict(r) for r in c.execute(q + " ORDER BY COALESCE(announce_date,'') DESC, id DESC", a)]
    c.close()
    return rows


def get_status(db_path=None) -> dict:
    c = get_conn(db_path)
    out = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM mna_status")}
    out["rows"] = c.execute("SELECT COUNT(*) FROM mna_deal").fetchone()[0]
    c.close()
    return out


def set_status(db_path=None, **kv):
    c = get_conn(db_path)
    for k, v in kv.items():
        c.execute("INSERT OR REPLACE INTO mna_status(key, value) VALUES (?,?)", (k, None if v is None else str(v)))
    c.commit()
    c.close()
