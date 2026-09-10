"""
Regime Engine — 資料庫層 (SQLite)
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent.parent / "chip_data" / "regime.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_daily (
    date            TEXT NOT NULL,
    series          TEXT NOT NULL,
    value           REAL,
    source          TEXT,
    updated_at      TEXT,
    PRIMARY KEY (date, series)
);

CREATE TABLE IF NOT EXISTS factors (
    date            TEXT NOT NULL,
    trend           REAL,
    breadth         REAL,
    positioning     REAL,
    macro_factor    REAL,
    direction       REAL,
    leverage_risk   REAL,
    concentration   REAL,
    divergence      REAL,
    risk_score      REAL,
    exhaustion      REAL,
    regime_label    TEXT,
    updated_at      TEXT,
    PRIMARY KEY (date)
);
"""

@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)

def upsert_series(conn, date: str, series: str, value, source: str = ""):
    conn.execute("""
        INSERT INTO market_daily(date, series, value, source, updated_at)
        VALUES(?, ?, ?, ?, datetime('now'))
        ON CONFLICT(date, series) DO UPDATE SET
            value=excluded.value, source=excluded.source, updated_at=excluded.updated_at
    """, (date, series, value, source))
