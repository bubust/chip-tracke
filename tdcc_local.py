"""
tdcc_local.py — 本機執行的 TDCC 千張大戶資料爬蟲
必須在台灣 IP 環境下執行（TDCC 封鎖境外 IP）。

用法：
    python tdcc_local.py

功能：
    1. 爬 TDCC 最近兩週資料（級距 15~17 加總）
    2. 自動讀取 watchlist.json 或手動指定股票清單
    3. 上傳至 Render 的 /api/chip/import 端點
"""

import asyncio
import json
import re
import sys
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path

import httpx

# ── 設定 ─────────────────────────────────────────────────────────────────────

RENDER_URL = "https://chip-tracker.onrender.com"   # Render 部署網址

TDCC_WEB = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
THOUSAND_LOT_TIERS = {15, 16, 17}
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"

# 若 watchlist.json 不在同目錄，也可直接在這裡指定股票清單：
MANUAL_STOCK_LIST: list[str] = []   # 空 = 自動從 watchlist.json 讀取，或爬全市場


# ── HTML 解析（同 tdcc_chip.py）────────────────────────────────────────────

class _TableParser(HTMLParser):
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

    def get_thousand_lot_pct(self) -> float:
        total = 0.0
        for row in self._rows:
            if len(row) < 5:
                continue
            try:
                tier = int(row[0])
            except ValueError:
                continue
            if tier in THOUSAND_LOT_TIERS:
                try:
                    pct_str = row[4].replace(",", "").replace("%", "").strip()
                    total += float(pct_str)
                except (ValueError, IndexError):
                    pass
        return round(total, 2)


def _parse_html(html: str) -> float:
    parser = _TableParser()
    parser.feed(html)
    pct = parser.get_thousand_lot_pct()
    if pct > 0:
        return pct
    # fallback regex
    total = 0.0
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
    for row_html in rows:
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.DOTALL | re.IGNORECASE)
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        cells = [c for c in cells if c and c != '\xa0']
        if len(cells) < 5:
            continue
        try:
            tier = int(cells[0])
        except ValueError:
            continue
        if tier in THOUSAND_LOT_TIERS:
            try:
                total += float(cells[4].replace(',', '').replace('%', '').strip())
            except (ValueError, IndexError):
                pass
    return round(total, 2)


def _extract_token(html: str) -> str | None:
    m = re.search(
        r'name=["\']?SYNCHRONIZER_TOKEN["\']?[^>]*value=["\']([^"\']+)["\']',
        html, re.IGNORECASE
    )
    if m:
        return m.group(1)
    m = re.search(
        r'value=["\']([^"\']+)["\'][^>]*name=["\']?SYNCHRONIZER_TOKEN["\']?',
        html, re.IGNORECASE
    )
    return m.group(1) if m else None


def _extract_available_dates(html: str, n: int = 2) -> list[str]:
    m = re.search(
        r'<select[^>]*name=["\']?scaDate["\']?[^>]*>(.*?)</select>',
        html, re.DOTALL | re.IGNORECASE
    )
    if not m:
        return []
    dates = re.findall(r'<option[^>]*value=["\'](\d{8})["\']', m.group(1), re.IGNORECASE)
    return dates[:n]


# ── 爬蟲 ─────────────────────────────────────────────────────────────────────

async def _get_session(client: httpx.AsyncClient):
    r = await client.get(TDCC_WEB)
    if r.status_code != 200:
        raise RuntimeError(f"GET TDCC 失敗，status={r.status_code}")
    token = _extract_token(r.text)
    if not token:
        raise RuntimeError("無法取得 SYNCHRONIZER_TOKEN")
    dates = _extract_available_dates(r.text, n=2)
    if not dates:
        raise RuntimeError("無法取得可用日期")
    print(f"[TDCC] token OK，可用日期：{dates}")
    return token, dates, dict(r.cookies)


async def _fetch_one(client, sem, token, stock_id, date_str) -> float | None:
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
            print(f"  [!] {stock_id} 失敗：{e}")
            return None


async def fetch_batch(stock_ids: list[str], date_str: str) -> dict[str, float]:
    print(f"[TDCC] 爬取 {len(stock_ids)} 支股票，日期 {date_str} ...")
    sem = asyncio.Semaphore(10)
    timeout = httpx.Timeout(20.0, connect=10.0)
    async with httpx.AsyncClient(
        headers={"User-Agent": _UA, "Referer": TDCC_WEB},
        timeout=timeout, verify=False, follow_redirects=True,
    ) as client:
        session = await _get_session(client)
        token, available_dates, cookies = session
        client.cookies.update(cookies)
        actual = date_str if date_str in available_dates else available_dates[0]
        if actual != date_str:
            print(f"  日期 {date_str} 不在可用清單，改用 {actual}")
        tasks = [_fetch_one(client, sem, token, sid, actual) for sid in stock_ids]
        pcts = await asyncio.gather(*tasks, return_exceptions=True)

    results = {}
    for sid, pct in zip(stock_ids, pcts):
        if isinstance(pct, (int, float)):
            results[sid] = float(pct)
    print(f"[TDCC] 完成：{len(results)}/{len(stock_ids)} 支成功")
    return results


# ── 上傳至 Render ─────────────────────────────────────────────────────────────

def upload_to_render(date_str: str, data: dict[str, float]):
    if not data:
        print("[上傳] 無資料，跳過")
        return
    url = f"{RENDER_URL}/api/chip/import"
    payload = {"date": date_str, "data": data}
    print(f"[上傳] POST {url}，date={date_str}，{len(data)} 支 ...")
    try:
        r = httpx.post(url, json=payload, timeout=30)
        if r.status_code == 200:
            j = r.json()
            print(f"[上傳] 成功！date={j['date']}，count={j['count']}")
        else:
            print(f"[上傳] 失敗，status={r.status_code}，body={r.text[:200]}")
    except Exception as e:
        print(f"[上傳] 例外：{e}")


# ── 讀取股票清單 ──────────────────────────────────────────────────────────────

def load_stock_list() -> list[str]:
    """優先用 MANUAL_STOCK_LIST；其次讀 watchlist.json；最後讀 stocks.json"""
    if MANUAL_STOCK_LIST:
        print(f"[清單] 使用手動指定，共 {len(MANUAL_STOCK_LIST)} 支")
        return list(MANUAL_STOCK_LIST)

    # 嘗試讀 watchlist（同目錄）
    wl_path = Path(__file__).parent / "chip_data" / "watchlist.json"
    if wl_path.exists():
        try:
            wl = json.loads(wl_path.read_text(encoding="utf-8"))
            ids = list(wl.keys()) if isinstance(wl, dict) else list(wl)
            if ids:
                print(f"[清單] 從 watchlist.json 讀取，共 {len(ids)} 支")
                return ids
        except Exception:
            pass

    # fallback：讀 stocks.json（全市場清單，若存在）
    stocks_path = Path(__file__).parent / "chip_data" / "stocks.json"
    if stocks_path.exists():
        try:
            stocks = json.loads(stocks_path.read_text(encoding="utf-8"))
            ids = [s["stock_id"] for s in stocks] if isinstance(stocks[0], dict) else list(stocks)
            print(f"[清單] 從 stocks.json 讀取全市場，共 {len(ids)} 支（建議先跑 MA 篩選）")
            return ids
        except Exception:
            pass

    # 最後 fallback：硬編碼常見大型股
    default = [
        "2330","2317","2454","2382","2308","2881","2882","2891","2886","2884",
        "2303","2002","1301","1303","2412","2207","3711","2379","2357","3008",
    ]
    print(f"[清單] 無法讀取清單，使用預設 {len(default)} 支大型股")
    return default


# ── 主流程 ────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("TDCC 千張大戶本機爬蟲 → 上傳至 Render")
    print("請確認：本機 IP 為台灣 IP")
    print("=" * 60)

    stock_ids = load_stock_list()

    # 先取一次頁面，拿真實可用日期
    timeout = httpx.Timeout(20.0, connect=10.0)
    available_dates = []
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _UA}, timeout=timeout, verify=False, follow_redirects=True
        ) as client:
            r = await client.get(TDCC_WEB)
            available_dates = _extract_available_dates(r.text, n=2)
    except Exception as e:
        print(f"[!] 取可用日期失敗：{e}")

    if not available_dates:
        fri = date.today() - timedelta(days=(date.today().weekday() - 4) % 7)
        available_dates = [fri.strftime("%Y%m%d"), (fri - timedelta(days=7)).strftime("%Y%m%d")]
        print(f"[!] 改用計算值：{available_dates}")

    print(f"\nTDCC 可用日期：{available_dates}")
    print(f"準備爬取 {len(stock_ids)} 支股票，共 {len(available_dates)} 週\n")

    for ds in available_dates:
        print(f"\n── 日期 {ds} ──")
        data = await fetch_batch(stock_ids, ds)
        upload_to_render(ds, data)

    print("\n完成！請回到 Render 頁面查看 CHIP 篩選結果。")
    print("（可能需要重新執行全市場掃描讓 CHIP 策略更新）")


if __name__ == "__main__":
    asyncio.run(main())
