"""
sector/db.py — SQLite DB 管理（sector.db）
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SECTOR_DB_PATH = Path(__file__).parent.parent / "sector_data" / "sector.db"


@contextmanager
def db():
    """Context manager：回傳 sqlite3.Connection（row_factory = Row）"""
    SECTOR_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SECTOR_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """建立所有 tables（若不存在）"""
    SECTOR_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript("""
CREATE TABLE IF NOT EXISTS sector_master (
    sector_id   TEXT PRIMARY KEY,
    sector_name TEXT,
    exchange    TEXT DEFAULT 'ALL',
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS stock_sector_map (
    stock_id       TEXT,
    sector_id      TEXT,
    effective_date TEXT,
    PRIMARY KEY (stock_id, effective_date)
);
CREATE INDEX IF NOT EXISTS idx_ssm_sector ON stock_sector_map(sector_id);

CREATE TABLE IF NOT EXISTS sector_daily (
    observation_date       TEXT,
    sector_id              TEXT,
    stock_count            INTEGER,
    index_level            REAL,
    return_ew_1d           REAL,
    return_ew_5d           REAL,
    return_ew_20d          REAL,
    return_ew_60d          REAL,
    return_median_1d       REAL,
    return_median_5d       REAL,
    return_median_20d      REAL,
    return_median_60d      REAL,
    ma20                   REAL,
    ma60                   REAL,
    ma120                  REAL,
    ma20_slope             REAL,
    ma60_slope             REAL,
    swing_high             REAL,
    swing_low              REAL,
    swing_high_date        TEXT,
    swing_low_date         TEXT,
    trend_state            TEXT,
    relative_rank_5d       INTEGER,
    relative_rank_20d      INTEGER,
    relative_rank_60d      INTEGER,
    rank_change_5d         INTEGER,
    rank_change_20d        INTEGER,
    rank_trend             TEXT,
    market_relative_5d     REAL,
    market_relative_20d    REAL,
    market_relative_60d    REAL,
    breadth_up_ratio       REAL,
    above_ma20_ratio       REAL,
    above_ma60_ratio       REAL,
    median_return_1d       REAL,
    up_volume_ratio        REAL,
    top3_contribution      REAL,
    top10_contribution     REAL,
    internal_health        TEXT,
    structure_event        TEXT,
    structure_event_date   TEXT,
    structure_reference_price REAL,
    sector_regime          TEXT,
    transition_state       TEXT,
    PRIMARY KEY (observation_date, sector_id)
);
CREATE INDEX IF NOT EXISTS idx_sd_date ON sector_daily(observation_date);
CREATE INDEX IF NOT EXISTS idx_sd_sector ON sector_daily(sector_id);

CREATE TABLE IF NOT EXISTS sector_events (
    event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_date    TEXT,
    sector_id           TEXT,
    event_type          TEXT,
    reference_price     REAL,
    event_price         REAL,
    event_strength      TEXT,
    confirmation_status TEXT DEFAULT 'PENDING',
    created_at          TEXT
);
CREATE INDEX IF NOT EXISTS idx_se_date ON sector_events(observation_date);

CREATE TABLE IF NOT EXISTS sector_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
        """)
