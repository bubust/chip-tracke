"""
資料庫層 — SQLite (本機開發)
Schema 對應規格書 §8
"""
import sqlite3
import os
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent.parent / "data" / "warrants.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS underlyings (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    market      TEXT NOT NULL,   -- 'TSE' | 'OTC'
    hv20        REAL,
    hv60        REAL,
    dividend_yield REAL DEFAULT 0,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS warrants (
    code            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    market          TEXT NOT NULL,   -- 'TSE' | 'OTC'
    issuer          TEXT NOT NULL,
    kind            TEXT NOT NULL,   -- 'CALL' | 'PUT'
    style           TEXT NOT NULL,   -- 'PLAIN' | 'RESET' | 'CAPPED'
    underlying_code TEXT REFERENCES underlyings(code),
    strike          REAL NOT NULL,
    exercise_ratio  REAL NOT NULL,   -- N (formula) = api_field / 1000
    listed_date     TEXT,
    last_trade_date TEXT NOT NULL,
    expiry_date     TEXT NOT NULL,
    issued_lots     INTEGER,
    settlement      TEXT,
    is_active       INTEGER DEFAULT 1,
    updated_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_warrants_underlying
    ON warrants(underlying_code, kind, is_active);

CREATE TABLE IF NOT EXISTS warrant_terms_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    warrant_code    TEXT NOT NULL,
    changed_on      TEXT NOT NULL,
    old_strike      REAL,
    new_strike      REAL,
    old_ratio       REAL,
    new_ratio       REAL
);

CREATE TABLE IF NOT EXISTS warrant_daily (
    warrant_code    TEXT NOT NULL,
    trade_date      TEXT NOT NULL,
    close_price     REAL,
    volume_lots     INTEGER,
    outstanding_lots INTEGER,
    PRIMARY KEY (warrant_code, trade_date)
);

CREATE TABLE IF NOT EXISTS iv_snapshots (
    warrant_code    TEXT NOT NULL,
    snapshot_at     TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'SELF',
    underlying_px   REAL,
    bid             REAL,
    ask             REAL,
    bid_iv          REAL,
    ask_iv          REAL,
    delta           REAL,
    vega            REAL,
    PRIMARY KEY (warrant_code, snapshot_at, source)
);

CREATE TABLE IF NOT EXISTS iv_daily (
    warrant_code    TEXT NOT NULL,
    trade_date      TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'SELF',
    bid_iv          REAL NOT NULL,
    PRIMARY KEY (warrant_code, trade_date, source)
);

CREATE TABLE IF NOT EXISTS issuer_ratings (
    issuer          TEXT NOT NULL,
    quarter         TEXT NOT NULL,
    score           REAL,
    PRIMARY KEY (issuer, quarter)
);

CREATE TABLE IF NOT EXISTS watchlist (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    underlying_code TEXT NOT NULL,
    sort_order      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS config (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);
"""


def init_db():
    """建立資料庫與 schema"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA)
    print(f"[DB] 初始化完成: {DB_PATH}")


def upsert_underlying(conn, code, name, market):
    conn.execute("""
        INSERT INTO underlyings(code, name, market, updated_at)
        VALUES(?, ?, ?, datetime('now'))
        ON CONFLICT(code) DO UPDATE SET
            name=excluded.name, market=excluded.market,
            updated_at=excluded.updated_at
    """, (code, name, market))


def upsert_warrant(conn, w: dict):
    old = conn.execute("SELECT strike, exercise_ratio FROM warrants WHERE code=?",
                       (w["code"],)).fetchone()
    if old:
        changed = (abs(old["strike"] - w["strike"]) > 0.01 or
                   abs(old["exercise_ratio"] - w["exercise_ratio"]) > 0.00001)
        if changed:
            conn.execute("""
                INSERT INTO warrant_terms_history
                    (warrant_code, changed_on, old_strike, new_strike, old_ratio, new_ratio)
                VALUES(?,date('now'),?,?,?,?)
            """, (w["code"], old["strike"], w["strike"],
                  old["exercise_ratio"], w["exercise_ratio"]))
            print(f"[DB] K/N changed: {w['code']} K {old['strike']}→{w['strike']}")

    conn.execute("""
        INSERT INTO warrants
            (code,name,market,issuer,kind,style,underlying_code,
             strike,exercise_ratio,listed_date,last_trade_date,expiry_date,
             issued_lots,settlement,is_active,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,datetime('now'))
        ON CONFLICT(code) DO UPDATE SET
            name=excluded.name, issuer=excluded.issuer,
            style=excluded.style, underlying_code=excluded.underlying_code,
            strike=excluded.strike, exercise_ratio=excluded.exercise_ratio,
            last_trade_date=excluded.last_trade_date,
            expiry_date=excluded.expiry_date,
            issued_lots=excluded.issued_lots,
            is_active=1, updated_at=excluded.updated_at
    """, (w["code"], w["name"], w["market"], w["issuer"], w["kind"], w["style"],
          w.get("underlying_code"), w["strike"], w["exercise_ratio"],
          w.get("listed_date"), w["last_trade_date"], w["expiry_date"],
          w.get("issued_lots"), w.get("settlement")))
