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

def init_db() -> int:
    """建表＋一次性資料修正；回傳修正的筆數（>0 時呼叫端要重算近期因子）"""
    with db() as conn:
        conn.executescript(SCHEMA)
        conn.execute("CREATE TABLE IF NOT EXISTS regime_meta (key TEXT PRIMARY KEY, value TEXT)")
        return normalize_dates(conn)


def iso_date(d) -> str:
    """'20260923'、'2026-09-23'、'2026/09/23'、date、datetime → '2026-09-23'（PLAN-B74：唯一寫入口統一）"""
    if hasattr(d, "strftime"):
        return d.strftime("%Y-%m-%d")
    s = str(d).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    s = s.replace("/", "-")
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s


def normalize_dates(conn) -> int:
    """8 碼日期轉 ISO（同一天兩筆留 updated_at 新的）；
    廣度一次性重建（breadth_v2）：舊的 BREADTH_50MA（站上 50 日線比例、整體市場含權證）和 AD_LINE、
    MEDIAN_RET 代理值刪掉，啟動後 fetch_twse_market_breadth 用「股票」家數重抓最近 90 天（淨廣度 −100～100）"""
    n = 0
    done = conn.execute("SELECT value FROM regime_meta WHERE key='breadth_v2'").fetchone()
    if not done:
        n += conn.execute("DELETE FROM market_daily WHERE series IN ('BREADTH_50MA','AD_LINE') "
                          "OR (series='MEDIAN_RET' AND source='TWSE_MI_PROXY')").rowcount
        conn.execute("INSERT OR REPLACE INTO regime_meta(key,value) VALUES('breadth_v2', datetime('now'))")
    rows = conn.execute("SELECT rowid, date, series, updated_at FROM market_daily WHERE date NOT LIKE '____-__-__'").fetchall()
    for r in rows:
        iso = iso_date(r["date"])
        if iso == r["date"]:
            continue
        ex = conn.execute("SELECT rowid, updated_at FROM market_daily WHERE date=? AND series=?", (iso, r["series"])).fetchone()
        if ex:
            if (r["updated_at"] or "") > (ex["updated_at"] or ""):
                conn.execute("DELETE FROM market_daily WHERE rowid=?", (ex["rowid"],))
                conn.execute("UPDATE market_daily SET date=? WHERE rowid=?", (iso, r["rowid"]))
            else:
                conn.execute("DELETE FROM market_daily WHERE rowid=?", (r["rowid"],))
        else:
            conn.execute("UPDATE market_daily SET date=? WHERE rowid=?", (iso, r["rowid"]))
        n += 1
    return n


def count_non_iso(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM market_daily WHERE date NOT LIKE '____-__-__'").fetchone()[0]


def upsert_series(conn, date: str, series: str, value, source: str = ""):
    date = iso_date(date)
    conn.execute("""
        INSERT INTO market_daily(date, series, value, source, updated_at)
        VALUES(?, ?, ?, ?, datetime('now'))
        ON CONFLICT(date, series) DO UPDATE SET
            value=excluded.value, source=excluded.source, updated_at=excluded.updated_at
    """, (date, series, value, source))
