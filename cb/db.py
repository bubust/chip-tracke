"""可轉債資料表（chip_data/cb.db，WAL）"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "chip_data" / "cb.db"


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
        CREATE TABLE IF NOT EXISTS cb_bond (
            code TEXT PRIMARY KEY,            -- 債券代號（例 11011）
            name TEXT,                        -- 簡稱（台泥一永）
            sid TEXT,                         -- 發行公司股票代號
            issuer TEXT,
            issue_date TEXT, maturity_date TEXT,      -- YYYY-MM-DD
            issue_amt REAL, outstanding REAL,         -- 發行／流通在外面額（元）
            conv_price_issue REAL,            -- 發行時轉換價
            conv_start TEXT, conv_end TEXT,
            put_date TEXT, put_price REAL,    -- 賣回日／賣回價
            updated TEXT
        );
        CREATE TABLE IF NOT EXISTS cb_quote (
            date TEXT, code TEXT,             -- date YYYY-MM-DD
            close REAL, chg REAL, volume REAL, amount REAL, avg REAL, ref REAL,
            PRIMARY KEY (date, code)
        );
        CREATE TABLE IF NOT EXISTS cb_stock (
            date TEXT, sid TEXT,              -- 發行公司每日快照：收盤、融券餘額（張）
            close REAL, short_bal REAL,
            PRIMARY KEY (date, sid)
        );
        CREATE TABLE IF NOT EXISTS cb_rev (
            sid TEXT PRIMARY KEY, ym TEXT, yoy REAL, mom REAL, cum_yoy REAL, updated TEXT
        );
        CREATE TABLE IF NOT EXISTS cb_conv_adj (   -- 重大訊息裡的「轉換價格調整」
            sid TEXT, series INTEGER, date TEXT, price REAL, subject TEXT,
            PRIMARY KEY (sid, series, date)
        );
        CREATE TABLE IF NOT EXISTS cb_manual (     -- 手動補：目前轉換價、CB 股東人數、備註
            code TEXT PRIMARY KEY, conv_price REAL, holders INTEGER, note TEXT
        );
        CREATE TABLE IF NOT EXISTS cb_status (key TEXT PRIMARY KEY, value TEXT);
    """)
    c.commit()
    c.close()


def set_status(db_path=None, **kv):
    c = get_conn(db_path)
    for k, v in kv.items():
        c.execute("INSERT OR REPLACE INTO cb_status(key, value) VALUES (?, ?)", (k, None if v is None else str(v)))
    c.commit()
    c.close()


def get_status(db_path=None) -> dict:
    c = get_conn(db_path)
    s = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM cb_status")}
    s["bonds"] = c.execute("SELECT COUNT(*) FROM cb_bond").fetchone()[0]
    s["quote_days"] = c.execute("SELECT COUNT(DISTINCT date) FROM cb_quote").fetchone()[0]
    s["last_quote"] = c.execute("SELECT MAX(date) FROM cb_quote").fetchone()[0]
    c.close()
    return s
