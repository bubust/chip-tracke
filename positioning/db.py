import sqlite3
from pathlib import Path
from datetime import date

DB_PATH = Path(__file__).parent.parent / "chip_data" / "positioning.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Raw tables – store exactly what TAIFEX returns, for reprocessing
    c.executescript("""
        CREATE TABLE IF NOT EXISTS raw_taifex_inst_futures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_date TEXT NOT NULL,
            identity TEXT NOT NULL,       -- 自營商/投信/外資及陸資
            contract TEXT NOT NULL,       -- 臺股期貨/小型臺指/臺灣永續
            trade_long INTEGER,
            trade_short INTEGER,
            trade_net INTEGER,
            oi_long INTEGER,
            oi_short INTEGER,
            oi_net INTEGER,
            downloaded_at TEXT DEFAULT (datetime('now','localtime')),
            formula_version TEXT DEFAULT 'v1',
            UNIQUE(observation_date, identity, contract)
        );

        CREATE TABLE IF NOT EXISTS raw_taifex_inst_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_date TEXT NOT NULL,
            identity TEXT NOT NULL,
            buy_call_oi INTEGER,
            sell_call_oi INTEGER,
            buy_put_oi INTEGER,
            sell_put_oi INTEGER,
            buy_call_value INTEGER,
            sell_call_value INTEGER,
            buy_put_value INTEGER,
            sell_put_value INTEGER,
            net_value INTEGER,
            net_oi_value INTEGER,
            downloaded_at TEXT DEFAULT (datetime('now','localtime')),
            formula_version TEXT DEFAULT 'v1',
            UNIQUE(observation_date, identity)
        );

        CREATE TABLE IF NOT EXISTS raw_taifex_large_trader (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_date TEXT NOT NULL,
            contract TEXT NOT NULL,       -- TX/MTX/TMF/全部
            top5_long INTEGER,
            top5_short INTEGER,
            top10_long INTEGER,
            top10_short INTEGER,
            market_long INTEGER,
            market_short INTEGER,
            downloaded_at TEXT DEFAULT (datetime('now','localtime')),
            formula_version TEXT DEFAULT 'v1',
            UNIQUE(observation_date, contract)
        );

        CREATE TABLE IF NOT EXISTS raw_taifex_options_pcr (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_date TEXT NOT NULL,
            scope TEXT NOT NULL,          -- ALL / NEAR
            call_oi INTEGER,
            put_oi INTEGER,
            call_volume INTEGER,
            put_volume INTEGER,
            downloaded_at TEXT DEFAULT (datetime('now','localtime')),
            formula_version TEXT DEFAULT 'v1',
            UNIQUE(observation_date, scope)
        );

        CREATE TABLE IF NOT EXISTS raw_twse_institutional (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_date TEXT NOT NULL,
            foreign_net_bn REAL,          -- 億元
            trust_net_bn REAL,
            dealer_net_bn REAL,
            downloaded_at TEXT DEFAULT (datetime('now','localtime')),
            formula_version TEXT DEFAULT 'v1',
            UNIQUE(observation_date)
        );

        CREATE TABLE IF NOT EXISTS positioning_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_date TEXT NOT NULL UNIQUE,

            -- Market
            taiex_close REAL,
            tpex_close REAL,
            market_volume_bn REAL,

            -- Cash institutions (億元)
            foreign_cash_net REAL,
            trust_cash_net REAL,
            dealer_cash_net REAL,

            -- Foreign futures OI (TX-equivalent lots)
            foreign_futures_long_oi REAL,
            foreign_futures_short_oi REAL,
            foreign_futures_net_oi REAL,

            -- Large trader OI
            top5_long_oi INTEGER,
            top5_short_oi INTEGER,
            top5_net_oi INTEGER,
            top10_long_oi INTEGER,
            top10_short_oi INTEGER,
            top10_net_oi INTEGER,

            -- Options PCR
            pcr_oi_all REAL,
            pcr_oi_near REAL,
            pcr_volume_all REAL,

            -- Foreign options
            foreign_option_long_value REAL,
            foreign_option_short_value REAL,
            foreign_option_net_value REAL,
            foreign_option_net_oi_value REAL,

            -- Retail MTX proxy
            retail_mtx_long INTEGER,
            retail_mtx_short INTEGER,
            retail_mtx_net INTEGER,
            retail_mtx_ratio REAL,

            -- Total OI
            total_tx_oi INTEGER,
            total_mtx_oi INTEGER,
            total_tmf_oi INTEGER,
            tx_equivalent_total_oi REAL,

            -- 1D / 5D deltas
            delta_foreign_cash_1d REAL,
            delta_foreign_cash_5d REAL,
            delta_foreign_futures_1d REAL,
            delta_foreign_futures_5d REAL,
            delta_top5_1d INTEGER,
            delta_top5_5d INTEGER,
            delta_top10_1d INTEGER,
            delta_top10_5d INTEGER,
            delta_retail_1d REAL,
            delta_oi_1d REAL,
            delta_oi_5d REAL,

            -- Cumulative flows
            foreign_cash_3d REAL,
            foreign_cash_5d REAL,
            foreign_cash_10d REAL,
            foreign_cash_20d REAL,

            -- Percentiles (250D rolling)
            foreign_futures_pct250 REAL,
            top5_pct250 REAL,
            top10_pct250 REAL,
            pcr_pct250 REAL,
            retail_pct250 REAL,
            oi_pct250 REAL,

            -- States
            positioning_state TEXT,
            positioning_transition TEXT,
            positioning_divergence TEXT,
            positioning_exhaustion TEXT,
            positioning_summary TEXT,

            data_status TEXT DEFAULT 'COMPLETE',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
    """)
    conn.commit()
    conn.close()


def upsert_positioning(conn, row: dict):
    """Insert or replace a positioning_daily row."""
    row["updated_at"] = "datetime('now','localtime')"
    cols = [k for k in row if k != "updated_at"]
    placeholders = ", ".join(["?" for _ in cols])
    col_str = ", ".join(cols)
    vals = [row[k] for k in cols]
    conn.execute(
        f"""INSERT INTO positioning_daily ({col_str}, updated_at)
            VALUES ({placeholders}, datetime('now','localtime'))
            ON CONFLICT(observation_date) DO UPDATE SET
            {', '.join(f'{c}=excluded.{c}' for c in cols)},
            updated_at=datetime('now','localtime')""",
        vals,
    )
    conn.commit()


def get_history(conn, days: int = 60):
    rows = conn.execute(
        """SELECT * FROM positioning_daily
           WHERE foreign_futures_net_oi IS NOT NULL OR pcr_oi_all IS NOT NULL
           ORDER BY observation_date DESC LIMIT ?""",
        (days,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_latest(conn):
    row = conn.execute(
        "SELECT * FROM positioning_daily ORDER BY observation_date DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def get_series(conn, column: str, up_to_date: str = None, limit: int = 500):
    """Get a single column series ordered by date."""
    if up_to_date:
        rows = conn.execute(
            f"SELECT observation_date, {column} FROM positioning_daily "
            f"WHERE observation_date <= ? AND {column} IS NOT NULL "
            f"ORDER BY observation_date DESC LIMIT ?",
            (up_to_date, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT observation_date, {column} FROM positioning_daily "
            f"WHERE {column} IS NOT NULL "
            f"ORDER BY observation_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [(r[0], r[1]) for r in reversed(rows)]
