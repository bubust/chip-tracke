"""
tdcc_chip.py — 集保所千張大戶持股分級週資料
改用 TDCC 網站爬蟲（per-stock POST），搭配 MA 預篩減少請求數。
千張大戶 = 持股分級 15~17（持股 >= 1,000,000 股 ≈ >= 1,000 張）

資料來源：https://www.tdcc.com.tw/portal/zh/smWeb/qryStock
每週四更新，每次查詢一支股票。
"""
import asyncio
import re
import sqlite3
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).parent / "chip_data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "cache.db"

TDCC_WEB = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
THOUSAND_LOT_TIERS = {15, 16, 17}
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("""
        CREATE TABLE IF NOT EXISTS tdcc_holding (
            stock_id TEXT,
            date     TEXT,
            kpct     REAL,
            PRIMARY KEY (stock_id, date)
        )
    """)
    c.commit()
    return c


def _last_thursday(d: date = None) -> date:
    """回傳最近的週四（含今天若為週四）"""
    d = d or date.today()
    return d - timedelta(days=(d.weekday() - 3) % 7)


def _has_date(date_str: str, min_count: int = 10) -> bool:
    try:
        c = _conn()
        n = c.execute(
            "SELECT COUNT(*) FROM tdcc_holding WHERE date=?", (date_str,)
        ).fetchone()[0]
        c.close()
        return n >= min_count
    except Exception:
        return False


def _save(date_str: str, data: dict):
    if not data:
        return
    c = _conn()
    c.executemany(
        "INSERT OR REPLACE INTO tdcc_holding (stock_id, date, kpct) VALUES (?,?,?)",
        [(sid, date_str, pct) for sid, pct in data.items()]
    )
    c.commit()
    c.close()


def get_tdcc_data() -> dict:
    """
    回傳 {stock_id: {current_pct, prev_pct, change, date}}
    從 SQLite 讀最近兩週；資料不足時回傳 {}。
    """
    try:
        c = _conn()
        dates = [r[0] for r in c.execute(
            "SELECT DISTINCT date FROM tdcc_holding ORDER BY date DESC LIMIT 2"
        ).fetchall()]
        if len(dates) < 2:
            c.close()
            return {}
        cur_date, prev_date = dates[0], dates[1]
        cur  = {r["stock_id"]: r["kpct"] for r in c.execute(
            "SELECT stock_id, kpct FROM tdcc_holding WHERE date=?", (cur_date,)
        ).fetchall()}
        prev = {r["stock_id"]: r["kpct"] for r in c.execute(
            "SELECT stock_id, kpct FROM tdcc_holding WHERE date=?", (prev_date,)
        ).fetchall()}
        c.close()
        result = {}
        for sid, cpct in cur.items():
            ppct = prev.get(sid, cpct)
            result[sid] = {
                "current_pct": cpct,
                "prev_pct":    ppct,
                "change":      round(cpct - ppct, 2),
                "date":        cur_date,
            }
        return result
    except Exception as e:
        print(f"[TDCC] get_tdcc_data error: {e}")
        return {}


# ── HTML 解析 ────────────────────────────────────────────────────────────────

class _TableParser(HTMLParser):
    """解析 TDCC 回應 HTML，擷取持股分級表中千張大戶比例"""
    def __init__(self):
        super().__init__()
        self._in_td = False
        self._cur_row: list[str] = []
        self._rows: list[list[str]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._cur_row = []
        elif tag in ("td", "th"):
            self._in_td = True

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._in_td = False
        elif tag == "tr":
            if self._cur_row:
                self._rows.append(self._cur_row[:])

    def handle_data(self, data):
        if self._in_td:
            text = data.strip()
            if text:
                self._cur_row.append(text)

    def handle_entityref(self, name):
        if self._in_td and name == "nbsp":
            pass  # 忽略空白

    def get_thousand_lot_pct(self) -> float:
        """累加千張大戶（級距15~17）的 占集保庫存數(%)"""
        total = 0.0
        for row in self._rows:
            if len(row) < 4:
                continue
            try:
                tier = int(row[0])
            except ValueError:
                continue
            if tier in THOUSAND_LOT_TIERS:
                try:
                    pct_str = row[3].replace(",", "").replace("%", "").strip()
                    total += float(pct_str)
                except (ValueError, IndexError):
                    pass
        return round(total, 2)


def _parse_html(html: str) -> float:
    """解析 TDCC 回應 HTML，累加千張大戶（級距15~17）的占集保庫存數(%)"""
    # 主要路徑：HTML parser
    parser = _TableParser()
    parser.feed(html)
    pct = parser.get_thousand_lot_pct()
    if pct > 0:
        return pct

    # fallback：regex 直接掃 table rows（防 parser 遇到特殊 HTML 失效）
    total = 0.0
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
    for row_html in rows:
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.DOTALL | re.IGNORECASE)
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        cells = [c for c in cells if c and c != '\xa0']
        if len(cells) < 4:
            continue
        try:
            tier = int(cells[0])
        except ValueError:
            continue
        if tier in THOUSAND_LOT_TIERS:
            try:
                total += float(cells[3].replace(',', '').replace('%', '').strip())
            except (ValueError, IndexError):
                pass
    return round(total, 2)


def _extract_token(html: str) -> str | None:
    """從 HTML 中取出 SYNCHRONIZER_TOKEN"""
    m = re.search(r'name="SYNCHRONIZER_TOKEN"\s+value="([^"]+)"', html, re.IGNORECASE)
    return m.group(1) if m else None


# ── TDCC 爬蟲 ────────────────────────────────────────────────────────────────

async def _get_session(client: httpx.AsyncClient) -> tuple[str, dict] | None:
    """GET TDCC 頁面，取 SYNCHRONIZER_TOKEN + cookies。失敗回傳 None。"""
    try:
        r = await client.get(TDCC_WEB)
        if r.status_code != 200:
            print(f"[TDCC] GET 頁面失敗，status={r.status_code}")
            return None
        token = _extract_token(r.text)
        if not token:
            print("[TDCC] 無法取得 SYNCHRONIZER_TOKEN，頁面可能已改版")
            return None
        return token, dict(r.cookies)
    except Exception as e:
        print(f"[TDCC] 取 session 失敗：{e}")
        return None


async def _fetch_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    token: str,
    stock_id: str,
    date_str: str,
) -> float | None:
    """POST 查詢單支股票的千張大戶持股%。失敗回傳 None，無資料回傳 0.0。"""
    form_data = {
        "SYNCHRONIZER_TOKEN": token,
        "SYNCHRONIZER_URI":   "/portal/zh/smWeb/qryStock",
        "method":             "submit",
        "firDate":            date_str,
        "scaDate":            date_str,
        "sqlMethod":          "StockNo",
        "stockNo":            stock_id,
    }
    async with sem:
        try:
            r = await client.post(TDCC_WEB, data=form_data)
            if r.status_code != 200:
                return None
            return _parse_html(r.text)
        except Exception as e:
            print(f"[TDCC] {stock_id} 請求失敗：{e}")
            return None


async def fetch_batch(stock_ids: list[str], date_str: str) -> dict[str, float]:
    """
    批次爬取多支股票的千張大戶持股%。
    - 同一 session token 重複使用
    - Semaphore(10) 控制並發，避免 TDCC 封鎖
    回傳 {stock_id: pct}，失敗的股票不在結果中。
    """
    if not stock_ids:
        return {}

    print(f"[TDCC] 開始爬 {len(stock_ids)} 支股票，日期 {date_str}")
    sem = asyncio.Semaphore(10)
    timeout_cfg = httpx.Timeout(20.0, connect=10.0)

    async with httpx.AsyncClient(
        headers={
            "User-Agent": _UA,
            "Referer":    TDCC_WEB,
            "Accept":     "text/html,application/xhtml+xml,*/*",
        },
        timeout=timeout_cfg,
        verify=False,
        follow_redirects=True,
    ) as client:
        session_info = await _get_session(client)
        if not session_info:
            print("[TDCC] 無法建立 session，跳過 TDCC 爬蟲")
            return {}
        token, cookies = session_info
        client.cookies.update(cookies)

        tasks = [
            _fetch_one(client, sem, token, sid, date_str)
            for sid in stock_ids
        ]
        pcts = await asyncio.gather(*tasks, return_exceptions=True)

    results: dict[str, float] = {}
    ok = 0
    for sid, pct in zip(stock_ids, pcts):
        if isinstance(pct, (int, float)) and pct is not None and not isinstance(pct, Exception):
            results[sid] = float(pct)
            ok += 1

    print(f"[TDCC] 完成：{ok}/{len(stock_ids)} 支成功，日期 {date_str}")
    return results


async def refresh_for_stocks(stock_ids: list[str]) -> dict:
    """
    為指定股票清單取得最近兩週 TDCC 資料並寫入快取。
    - 已有足夠快取的日期跳過（避免重複爬）
    - 供 run_market_scan() 的 MA 預篩後呼叫
    回傳 {date_str: count | "cached"}
    """
    today   = date.today()
    cur     = _last_thursday(today)
    prev    = cur - timedelta(days=7)
    report  = {}
    skip_threshold = max(10, len(stock_ids) // 2)

    for s in [cur, prev]:
        ds = s.strftime("%Y%m%d")
        if _has_date(ds, min_count=skip_threshold):
            print(f"[TDCC] {ds} 已有快取（>={skip_threshold} 筆），跳過")
            report[ds] = "cached"
            continue
        batch = await fetch_batch(stock_ids, ds)
        if batch:
            _save(ds, batch)
            report[ds] = len(batch)
        else:
            report[ds] = 0

    return report


async def refresh_tdcc() -> dict:
    """
    API 相容性保留（/api/tdcc/refresh 端點）。
    新架構中 TDCC 資料已整合至 run_market_scan() 的 MA 預篩後自動抓取，
    無需手動 refresh。
    """
    print("[TDCC] 注意：新架構下 TDCC 資料已整合至掃描流程，無需手動 refresh")
    return {
        "message": "TDCC 資料已整合至掃描流程，執行全市場掃描即會自動抓取",
        "skipped": True,
    }
