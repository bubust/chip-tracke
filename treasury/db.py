"""庫藏股資料表（chip_data/treasury.db，WAL）"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "chip_data" / "treasury.db"

FIELDS = ["stock_id", "name", "market", "board_date", "purpose", "amount_cap", "plan_shares",
          "price_low", "price_high", "period_start", "period_end", "done", "bought_shares",
          "cancelled_shares", "exec_ratio", "bought_amount", "avg_price", "pct_of_capital",
          "not_done_reason"]


def get_conn(db_path=None):
    p = Path(db_path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(db_path=None):
    conn = get_conn(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS treasury_buyback (
            stock_id TEXT NOT NULL,
            name TEXT,
            market TEXT,                -- sii 上市 / otc 上櫃
            board_date TEXT NOT NULL,   -- 董事會決議日 YYYY-MM-DD
            purpose TEXT,
            amount_cap REAL,            -- 買回股份總金額上限（元）
            plan_shares REAL,           -- 預定買回股數（股）
            price_low REAL,
            price_high REAL,
            period_start TEXT,
            period_end TEXT,
            done INTEGER,               -- 是否執行完畢 1/0/NULL
            bought_shares REAL,         -- 本次已買回股數
            cancelled_shares REAL,      -- 已註銷或轉讓股數
            exec_ratio REAL,            -- 已買回佔預定比例 %
            bought_amount REAL,         -- 已買回總金額（元）
            avg_price REAL,             -- 平均每股買回價格
            pct_of_capital REAL,        -- 買回股數佔已發行股份比例 %
            not_done_reason TEXT,
            first_seen TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (stock_id, board_date)
        );
        CREATE INDEX IF NOT EXISTS idx_tb_period ON treasury_buyback(period_end);
        CREATE TABLE IF NOT EXISTS treasury_status (
            key TEXT PRIMARY KEY, value TEXT
        );
    """)
    conn.commit()
    conn.close()


def upsert(records: list, db_path=None) -> dict:
    """新增或更新（同公司同決議日視為同一次買回；後來申報的執行結果會覆蓋）。空值不覆蓋舊值。"""
    if not records:
        return {"inserted": 0, "updated": 0}
    conn = get_conn(db_path)
    ins = upd = 0
    for r in records:
        row = conn.execute("SELECT * FROM treasury_buyback WHERE stock_id=? AND board_date=?",
                           (r["stock_id"], r["board_date"])).fetchone()
        if row is None:
            cols = [f for f in FIELDS if f in r]
            conn.execute(f"INSERT INTO treasury_buyback ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                         [r[c] for c in cols])
            ins += 1
        else:
            changes = {f: r[f] for f in FIELDS
                       if f in r and r[f] not in (None, "") and r[f] != row[f]
                       and f not in ("stock_id", "board_date")}
            if changes:
                sets = ",".join(f"{k}=?" for k in changes) + ",updated_at=datetime('now','localtime')"
                conn.execute(f"UPDATE treasury_buyback SET {sets} WHERE stock_id=? AND board_date=?",
                             [*changes.values(), r["stock_id"], r["board_date"]])
                upd += 1
    conn.commit()
    conn.close()
    return {"inserted": ins, "updated": upd}


def all_rows(db_path=None, since: str = None) -> list:
    conn = get_conn(db_path)
    q = "SELECT * FROM treasury_buyback"
    args = []
    if since:
        q += " WHERE board_date >= ? OR period_end >= ?"
        args = [since, since]
    rows = [dict(r) for r in conn.execute(q + " ORDER BY board_date DESC", args).fetchall()]
    conn.close()
    return rows


def get_status(db_path=None) -> dict:
    conn = get_conn(db_path)
    out = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM treasury_status")}
    cnt = conn.execute("SELECT COUNT(*), MIN(board_date), MAX(board_date) FROM treasury_buyback").fetchone()
    conn.close()
    out.update(rows=cnt[0], earliest=cnt[1], latest=cnt[2])
    return out


def set_status(db_path=None, **kv):
    conn = get_conn(db_path)
    for k, v in kv.items():
        conn.execute("INSERT OR REPLACE INTO treasury_status(key, value) VALUES (?,?)",
                     (k, None if v is None else str(v)))
    conn.commit()
    conn.close()
