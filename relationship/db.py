import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "chip_data" / "relationship.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS market_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_date TEXT NOT NULL UNIQUE,
            -- TAIEX
            taiex_open REAL,
            taiex_high REAL,
            taiex_low REAL,
            taiex_close REAL,
            taiex_volume REAL,
            taiex_return_1d REAL,
            -- TX futures (continuous)
            tx_open REAL,
            tx_high REAL,
            tx_low REAL,
            tx_close REAL,
            tx_volume REAL,
            tx_return_1d REAL,
            tx_relative_return REAL,   -- tx_return_1d - taiex_return_1d
            -- OI
            total_oi REAL,
            oi_change_1d REAL,
            oi_change_5d REAL,
            oi_state TEXT,  -- PRICE_UP_OI_UP / PRICE_UP_OI_DOWN / PRICE_DOWN_OI_UP / PRICE_DOWN_OI_DOWN
            -- MA
            taiex_ma20 REAL,
            taiex_ma60 REAL,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS market_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_date TEXT NOT NULL,
            event_type TEXT NOT NULL,   -- see spec
            event_level INTEGER DEFAULT 1,  -- 1=info, 2=notable, 3=important
            description TEXT,
            trigger_json TEXT,          -- JSON of triggering conditions
            future_return_5d REAL,
            future_return_10d REAL,
            future_return_20d REAL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(observation_date, event_type)
        );

        CREATE TABLE IF NOT EXISTS data_status (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
    """)
    conn.commit()
    conn.close()

def upsert_market_daily(conn, row: dict):
    cols = list(row.keys())
    placeholders = ", ".join(["?" for _ in cols])
    col_str = ", ".join(cols)
    vals = [row[k] for k in cols]
    conn.execute(
        f"INSERT INTO market_daily ({col_str}) VALUES ({placeholders}) "
        f"ON CONFLICT(observation_date) DO UPDATE SET "
        f"{', '.join(f'{c}=excluded.{c}' for c in cols if c != 'observation_date')}, "
        f"updated_at=datetime('now','localtime')",
        vals
    )

def upsert_event(conn, date_str: str, event_type: str, level: int, description: str, trigger: dict):
    import json
    conn.execute("""
        INSERT INTO market_events (observation_date, event_type, event_level, description, trigger_json)
        VALUES (?,?,?,?,?)
        ON CONFLICT(observation_date, event_type) DO UPDATE SET
        event_level=excluded.event_level,
        description=excluded.description,
        trigger_json=excluded.trigger_json
    """, (date_str, event_type, level, description, json.dumps(trigger, ensure_ascii=False)))

def get_history(conn, days: int = 90):
    rows = conn.execute(
        "SELECT * FROM market_daily ORDER BY observation_date DESC LIMIT ?", (days,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]

def get_events(conn, days: int = 90):
    rows = conn.execute(
        """SELECT e.*, d.taiex_close, d.taiex_return_1d
           FROM market_events e
           LEFT JOIN market_daily d ON d.observation_date=e.observation_date
           WHERE e.observation_date >= date('now', ?)
           ORDER BY e.observation_date DESC, e.event_level DESC""",
        (f"-{days} days",)
    ).fetchall()
    return [dict(r) for r in rows]

def get_date_detail(conn, date_str: str):
    market = conn.execute(
        "SELECT * FROM market_daily WHERE observation_date=?", (date_str,)
    ).fetchone()
    events = conn.execute(
        "SELECT * FROM market_events WHERE observation_date=? ORDER BY event_level DESC",
        (date_str,)
    ).fetchall()
    return {
        "market": dict(market) if market else None,
        "events": [dict(e) for e in events]
    }

def get_event_history(conn, event_type: str, days: int = 500):
    rows = conn.execute(
        """SELECT e.*, d.taiex_close, d.taiex_return_1d,
                  d.total_oi, d.oi_state
           FROM market_events e
           LEFT JOIN market_daily d ON d.observation_date=e.observation_date
           WHERE e.event_type=? AND e.observation_date >= date('now', ?)
           ORDER BY e.observation_date DESC""",
        (event_type, f"-{days} days")
    ).fetchall()
    return [dict(r) for r in rows]
