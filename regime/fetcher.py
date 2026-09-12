"""
Regime Engine — 資料抓取
Sprint 1: Yahoo Finance TAIEX/OTC/SOX/VIX/US10Y/USDTWD/TSM_ADR/SP500/NASDAQ
Sprint 2: 市場廣度(>50MA%) + A/D線 + TAIFEX外資期貨 + 中位數漲跌幅
Sprint 3: TWSE MI_INDEX 直接抓漲跌家數（不依賴 price_daily）
Sprint 4: MI_5MINS 過熱/恐慌指數，MI_MARGN 更健壯解析
"""
import logging
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
import httpx

from .db import db, upsert_series

log = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

YAHOO_TICKERS = {
    "TAIEX":   "^TWII",
    "OTC":     "^TWOII",
    "SOX":     "^SOX",
    "VIX":     "^VIX",
    "US10Y":   "^TNX",
    "USDTWD":  "TWD=X",
    "TSM_ADR": "TSM",
    "SP500":   "^GSPC",
    "NASDAQ":  "^IXIC",
}

def _yahoo_close(ticker: str, days: int = 30) -> list[tuple[str, float]]:
    """回傳 [(date_str, close), ...] 最近 days 天"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": "1d", "range": f"{days}d"}
    try:
        with httpx.Client(timeout=12, headers={"User-Agent": _UA}) as c:
            r = c.get(url, params=params)
            data = r.json()
        result = data.get("chart", {}).get("result") or []
        if not result:
            return []
        r0 = result[0]
        timestamps = r0.get("timestamp", [])
        closes = r0["indicators"]["quote"][0].get("close", [])
        out = []
        import pandas as pd
        tw_offset = pd.Timedelta(hours=8)
        for ts, close in zip(timestamps, closes):
            if close is None:
                continue
            dt = (pd.Timestamp(ts, unit="s", tz="UTC") + tw_offset).strftime("%Y-%m-%d")
            out.append((dt, round(float(close), 6)))
        return out
    except Exception as e:
        log.warning(f"[fetcher] {ticker} 失敗: {e}")
        return []


def fetch_all(days: int = 60):
    """抓取所有 Yahoo Finance 系列並寫入 DB"""
    inserted = 0
    with db() as conn:
        for series, ticker in YAHOO_TICKERS.items():
            rows = _yahoo_close(ticker, days)
            for dt, val in rows:
                upsert_series(conn, dt, series, val, "YAHOO")
                inserted += 1
            log.info(f"[fetcher] {series}({ticker}): {len(rows)} 筆")
    log.info(f"[fetcher] 共寫入 {inserted} 筆")
    return inserted


def fetch_twse_margin(days: int = 5):
    """TWSE MI_MARGN — 融資餘額 (市場合計) → series: MARGIN_BALANCE
    嘗試多個端點，更健壯的解析邏輯。
    """
    # 嘗試 openapi 端點（回傳 JSON array）
    urls_to_try = [
        ("openapi", "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"),
        ("twse_json", "https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json"),
    ]

    for source_tag, url in urls_to_try:
        try:
            with httpx.Client(timeout=20, headers={"User-Agent": _UA}, verify=False) as c:
                r = c.get(url)
                r.raise_for_status()
                content_type = r.headers.get("content-type", "")

            # openapi 回傳 JSON array
            if source_tag == "openapi":
                rows = r.json()
                if not isinstance(rows, list):
                    log.warning(f"[fetcher] MI_MARGN openapi 非陣列格式")
                    continue
                inserted = 0
                with db() as conn:
                    for row in rows:
                        date_str = str(row.get("Date", "")).strip()
                        # 格式 YYYYMMDD
                        if len(date_str) == 8 and date_str.isdigit():
                            dt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
                        else:
                            continue
                        # MarginPurchaseAmount = 融資買進 (股)
                        # 嘗試多個欄位名稱
                        val = None
                        for field in ["MarginPurchaseAmount", "MarginBalance", "TotalMarginPurchaseAmount"]:
                            raw = str(row.get(field, "")).replace(",", "").strip()
                            if raw and raw not in ("", "-", "--"):
                                try:
                                    val = float(raw)
                                    break
                                except Exception:
                                    pass
                        if val is None:
                            continue
                        upsert_series(conn, dt, "MARGIN_BALANCE", val, f"TWSE_{source_tag.upper()}")
                        inserted += 1
                log.info(f"[fetcher] MARGIN_BALANCE ({source_tag}): {inserted} 筆")
                if inserted > 0:
                    return  # 成功就不再嘗試下一個端點

            # twse_json 端點：回傳包含 data/fields 的結構
            elif source_tag == "twse_json":
                jdata = r.json()
                if jdata.get("stat") != "OK":
                    continue
                fields = jdata.get("fields", [])
                data_rows = jdata.get("data", [])
                if not data_rows:
                    continue
                # 找 融資餘額 欄位索引
                margin_idx = None
                date_idx = 0  # 通常第一欄是日期
                for i, f in enumerate(fields):
                    if "融資" in str(f) and ("餘額" in str(f) or "買進" in str(f)):
                        margin_idx = i
                        break
                if margin_idx is None and len(fields) >= 3:
                    margin_idx = 2  # 通常第3欄
                inserted = 0
                with db() as conn:
                    for row in data_rows[-days:]:
                        try:
                            date_raw = str(row[date_idx]).strip()
                            # 可能是 民國年 格式 如 "115/01/02"
                            if "/" in date_raw:
                                parts = date_raw.split("/")
                                year = int(parts[0]) + 1911
                                dt = f"{year}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
                            elif len(date_raw) == 8 and date_raw.isdigit():
                                dt = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}"
                            else:
                                continue
                            if margin_idx is not None:
                                val_raw = str(row[margin_idx]).replace(",", "").strip()
                                val = float(val_raw)
                                upsert_series(conn, dt, "MARGIN_BALANCE", val, "TWSE_JSON")
                                inserted += 1
                        except Exception:
                            continue
                log.info(f"[fetcher] MARGIN_BALANCE (twse_json): {inserted} 筆")
                if inserted > 0:
                    return

        except Exception as e:
            log.warning(f"[fetcher] MI_MARGN ({source_tag}) 失敗: {e}")

    log.warning("[fetcher] MARGIN_BALANCE: 所有端點均失敗")


def fetch_mi5mins():
    """
    TWSE MI_5MINS — 盤中5分鐘資料，取累計值計算：
    - 過熱指數 OVERHEATING_INDEX = 成交股數 / 委買股數 (threshold: 0.5)
    - 恐慌指數 PANIC_INDEX       = 成交股數 / 委賣股數 (threshold: 0.75)
    回傳 (overheating_ratio, panic_ratio) 或 (None, None)
    """
    url = "https://www.twse.com.tw/exchangeReport/MI_5MINS"
    params = {"response": "json"}
    try:
        with httpx.Client(timeout=15, headers={
            "User-Agent": _UA,
            "Referer": "https://www.twse.com.tw/",
        }, verify=False) as c:
            r = c.get(url, params=params)
            data = r.json()

        if data.get("stat") != "OK":
            log.info(f"[fetcher] MI_5MINS stat={data.get('stat')} (市場休市或尚未開盤)")
            return None, None

        rows = data.get("data", [])
        if not rows:
            log.info("[fetcher] MI_5MINS: 無資料列")
            return None, None

        fields = data.get("fields", [])
        log.debug(f"[fetcher] MI_5MINS fields: {fields}")

        # MI_5MINS 每列已是累積值，直接取最後一列
        # 欄位順序: 時間, 累積委託買進筆數, 累積委託買進數量, 累積委託賣出筆數, 累積委託賣出數量, 累積成交筆數, 累積成交數量, 累積成交金額
        last = rows[-1]
        if len(last) < 7:
            log.info("[fetcher] MI_5MINS: 最後列欄位不足")
            return None, None

        try:
            buy_order  = int(str(last[2]).replace(",", "").strip() or "0")   # 累積委託買進數量
            sell_order = int(str(last[4]).replace(",", "").strip() or "0")   # 累積委託賣出數量
            trade_vol  = int(str(last[6]).replace(",", "").strip() or "0")   # 累積成交數量
        except Exception as e:
            log.warning(f"[fetcher] MI_5MINS: 解析最後列失敗: {e}")
            return None, None

        if buy_order == 0 or sell_order == 0:
            log.info("[fetcher] MI_5MINS: 委買/委賣為 0，跳過")
            return None, None

        overheating = round(trade_vol / buy_order, 4)
        panic = round(trade_vol / sell_order, 4)

        log.info(f"[fetcher] MI_5MINS: 成交={trade_vol:,} 委買={buy_order:,} 委賣={sell_order:,}"
                 f" → 過熱={overheating:.4f} 恐慌={panic:.4f}")

        # 寫入 DB
        dt = date.today().strftime("%Y-%m-%d")
        with db() as conn:
            upsert_series(conn, dt, "OVERHEATING_INDEX", overheating, "TWSE_MI5MINS")
            upsert_series(conn, dt, "PANIC_INDEX", panic, "TWSE_MI5MINS")

        return overheating, panic

    except Exception as e:
        log.warning(f"[fetcher] MI_5MINS 失敗: {e}")
        return None, None


def fetch_twse_foreign_spot():
    """TWSE T86 外資現貨買賣超 → series: FOREIGN_NET_LOT (張)"""
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"
    from datetime import date as _date
    dt_str = _date.today().strftime("%Y%m%d")
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": _UA, "Referer": "https://www.twse.com.tw/"}, verify=False) as c:
            r = c.get(url, params={"date": dt_str, "selectType": "ALL", "response": "json"})
            t86 = r.json()
        if t86.get("stat") != "OK":
            return
        total_foreign_net = 0
        for row in t86.get("data", []):
            try:
                total_foreign_net += float(str(row[4]).replace(",", "")) / 1000
            except Exception:
                pass
        dt = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:]}"
        with db() as conn:
            upsert_series(conn, dt, "FOREIGN_NET_LOT", round(total_foreign_net), "TWSE_T86")
        log.info(f"[fetcher] FOREIGN_NET_LOT: {round(total_foreign_net)} 張")
    except Exception as e:
        log.warning(f"[fetcher] T86 失敗: {e}")


# ── Sprint 2 ──────────────────────────────────────────────────────────────────

# 主 DB 路徑（cache.db 有 price_daily）
_MAIN_DB = Path(__file__).parent.parent / "chip_data" / "cache.db"


def _open_main_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_MAIN_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def fetch_breadth_ad(lookback: int = 90):
    """
    從 price_daily 計算並寫入:
    - BREADTH_50MA: 全市場站上50日均線比例(0~100)
    - AD_LINE     : 漲家數 - 跌家數（每日）
    - MEDIAN_RET  : 全市場中位數漲跌幅(%)
    lookback: 計算最近幾天的資料
    """
    if not _MAIN_DB.exists():
        log.warning("[fetcher] cache.db 不存在，跳過 breadth 計算")
        return

    try:
        conn = _open_main_db()
        # 取最近 (lookback + 60) 天資料，多抓 60 天供 50MA 計算
        cutoff = (date.today() - timedelta(days=lookback + 65)).strftime("%Y-%m-%d")
        rows = conn.execute(
            "SELECT date, stock_id, close FROM price_daily WHERE date >= ? AND close IS NOT NULL ORDER BY stock_id, date",
            (cutoff,),
        ).fetchall()
        conn.close()
    except Exception as e:
        log.warning(f"[fetcher] 讀取 price_daily 失敗: {e}")
        return

    if not rows:
        return

    # 按股票分組取收盤序列
    from collections import defaultdict
    stock_closes: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        stock_closes[r["stock_id"]].append((r["date"], float(r["close"])))

    # 取所有需計算的日期（最近 lookback 天）
    cutoff_target = (date.today() - timedelta(days=lookback)).strftime("%Y-%m-%d")
    all_dates_in_range: set[str] = set()
    for closes in stock_closes.values():
        for dt, _ in closes:
            if dt >= cutoff_target:
                all_dates_in_range.add(dt)
    sorted_dates = sorted(all_dates_in_range)

    # 對每個日期計算廣度指標
    date_above50: dict[str, list[int]] = defaultdict(list)
    date_changes:  dict[str, list[float]] = defaultdict(list)
    date_ad:       dict[str, int] = defaultdict(int)

    for sid, closes in stock_closes.items():
        if len(closes) < 2:
            continue
        prices_arr = [c for _, c in closes]
        dates_arr  = [d for d, _ in closes]

        for i, (dt, px) in enumerate(closes):
            if dt < cutoff_target:
                continue
            # 50MA: 使用到當日為止的最多50筆
            start = max(0, i - 49)
            window = prices_arr[start:i + 1]
            if len(window) >= 10:  # 至少10筆才算
                ma50 = sum(window) / len(window)
                date_above50[dt].append(1 if px > ma50 else 0)

            # A/D + 中位數漲跌幅：比前一日
            if i > 0:
                prev_px = prices_arr[i - 1]
                if prev_px > 0:
                    chg_pct = (px - prev_px) / prev_px * 100
                    date_changes[dt].append(chg_pct)
                    date_ad[dt] += (1 if chg_pct > 0 else (-1 if chg_pct < 0 else 0))

    with db() as conn:
        for dt in sorted_dates:
            # BREADTH_50MA
            above50 = date_above50.get(dt, [])
            if above50:
                pct = round(sum(above50) / len(above50) * 100, 2)
                upsert_series(conn, dt, "BREADTH_50MA", pct, "PRICE_DAILY")

            # AD_LINE
            ad = date_ad.get(dt)
            if ad is not None:
                upsert_series(conn, dt, "AD_LINE", ad, "PRICE_DAILY")

            # MEDIAN_RET
            changes = date_changes.get(dt, [])
            if changes:
                sorted_chgs = sorted(changes)
                n = len(sorted_chgs)
                med = (sorted_chgs[n // 2] if n % 2 == 1
                       else (sorted_chgs[n // 2 - 1] + sorted_chgs[n // 2]) / 2)
                upsert_series(conn, dt, "MEDIAN_RET", round(med, 4), "PRICE_DAILY")

    log.info(f"[fetcher] Breadth/AD/MedianRet: {len(sorted_dates)} 天 寫入完成")


def _parse_mi_index_ad(data: dict):
    """
    解析 TWSE MI_INDEX response 中的漲跌家數 (table[7])
    回傳 (上漲+上櫃合計, 下跌+上櫃合計, 持平合計) 或 (None, None, None)
    """
    for table in data.get("tables", []):
        rows = table.get("data", [])
        if not rows:
            continue
        up, down, flat = None, None, None
        for row in rows:
            if len(row) < 2:
                continue
            label = str(row[0]).strip()

            def _parse(s):
                # '6,805(58)' → 6805; '607(12)' → 607
                s = str(s).split("(")[0].replace(",", "").strip()
                try:
                    return int(s)
                except Exception:
                    return None

            if "\u4e0a\u6f32" in label:      # 上漲
                v1 = _parse(row[1]) if len(row) > 1 else None
                v2 = _parse(row[2]) if len(row) > 2 else 0
                if v1 is not None:
                    up = v1 + (v2 or 0)
            elif "\u4e0b\u8dcc" in label:    # 下跌
                v1 = _parse(row[1]) if len(row) > 1 else None
                v2 = _parse(row[2]) if len(row) > 2 else 0
                if v1 is not None:
                    down = v1 + (v2 or 0)
            elif "\u6301\u5e73" in label or "\u5e73\u76e4" in label:  # 持平 / 平盤
                v1 = _parse(row[1]) if len(row) > 1 else None
                v2 = _parse(row[2]) if len(row) > 2 else 0
                if v1 is not None:
                    flat = v1 + (v2 or 0)

        if up is not None and down is not None:
            return up, down, flat or 0

    return None, None, None


def fetch_twse_market_breadth(lookback: int = 90):
    """
    Sprint 3: 從 TWSE MI_INDEX 抓歷史漲跌家數，不依賴 price_daily。
    寫入:
    - AD_LINE: 上漲家數(TSE+OTC) - 下跌家數(TSE+OTC)
    - BREADTH_50MA: 上漲/(上漲+下跌+持平)*100（當 price_daily 無資料時的代理指標）
    - MEDIAN_RET_PROXY: 若 MEDIAN_RET 缺失，使用 (up-down)/total*2 作為代理
    """
    import time as _time

    today = date.today()

    # 找出哪些日期已有 AD_LINE（跳過）
    with db() as conn:
        existing_ad = set(
            r[0] for r in conn.execute(
                "SELECT date FROM market_daily WHERE series='AD_LINE'"
            ).fetchall()
        )
        existing_median = set(
            r[0] for r in conn.execute(
                "SELECT date FROM market_daily WHERE series='MEDIAN_RET'"
            ).fetchall()
        )

    # 過去 lookback 天的工作日（週一~週五），最新在後
    targets = []
    for i in range(lookback, -1, -1):
        d = today - timedelta(days=i)
        if d.weekday() < 5:
            ds = d.strftime("%Y-%m-%d")
            if ds not in existing_ad:
                targets.append(d)

    if not targets:
        log.info("[fetcher] TWSE breadth: 無需補充資料")
        return

    log.info(f"[fetcher] TWSE breadth: 待補 {len(targets)} 天")
    inserted = 0
    _MI_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"

    for d in targets:
        dt_param = d.strftime("%Y%m%d")
        dt_iso   = d.strftime("%Y-%m-%d")
        try:
            with httpx.Client(timeout=12, headers={
                "User-Agent": _UA, "Referer": "https://www.twse.com.tw/"
            }) as c:
                r = c.get(_MI_URL, params={"date": dt_param, "response": "json"})
                data = r.json()

            if data.get("stat") != "OK":
                continue  # 假日/無資料 → 跳過

            up, down, flat = _parse_mi_index_ad(data)
            if up is None:
                log.debug(f"[fetcher] MI_INDEX {dt_param}: 解析失敗")
                continue

            ad_val      = up - down
            total       = max(up + down + flat, 1)
            breadth_pct = round(up / total * 100, 2)

            with db() as conn:
                upsert_series(conn, dt_iso, "AD_LINE", ad_val, "TWSE_MI")
                # BREADTH_50MA: 只在 price_daily 未填入時才用代理值
                has_b = conn.execute(
                    "SELECT 1 FROM market_daily WHERE date=? AND series='BREADTH_50MA'",
                    (dt_iso,)
                ).fetchone()
                if not has_b:
                    upsert_series(conn, dt_iso, "BREADTH_50MA", breadth_pct, "TWSE_MI_PROXY")

                # MEDIAN_RET 代理：若 price_daily 無資料時補充
                if dt_iso not in existing_median:
                    # (上漲-下跌) / 總家數 * 2 → 粗估中位數方向 (-1 ~ +1 之間)
                    median_proxy = round((up - down) / total * 2, 4)
                    has_m = conn.execute(
                        "SELECT 1 FROM market_daily WHERE date=? AND series='MEDIAN_RET'",
                        (dt_iso,)
                    ).fetchone()
                    if not has_m:
                        upsert_series(conn, dt_iso, "MEDIAN_RET", median_proxy, "TWSE_MI_PROXY")

            inserted += 1
            log.debug(f"[fetcher] {dt_iso} 上漲:{up} 下跌:{down} 持平:{flat} "
                      f"→ AD:{ad_val} breadth:{breadth_pct}%")

        except Exception as e:
            log.warning(f"[fetcher] MI_INDEX {dt_param}: {e}")

        _time.sleep(0.4)   # 避免被 TWSE 封鎖

    log.info(f"[fetcher] TWSE breadth 完成: 寫入 {inserted} 天")


def fetch_taifex_foreign_futures():
    """
    TAIFEX 外資期貨未平倉淨部位 → series: FOREIGN_FUTURES_NET (張)
    資料來源: TAIFEX 盤後資訊 - 交易人期貨與選擇權未平倉量彙整表
    """
    today_str = date.today().strftime("%Y/%m/%d")
    url = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": _UA, "Referer": "https://www.taifex.com.tw/"}, verify=False) as c:
            r = c.post(url, data={
                "queryStartDate": today_str,
                "queryEndDate": today_str,
                "commodityId": "TXF",  # 台指期
            })
        # 解析 CSV (TAIFEX 回傳格式為 CSV)
        lines = r.text.strip().split("\n")
        net_lot = None
        for line in lines:
            if "外資" in line or "Foreign" in line.lower():
                parts = line.replace('"', '').split(",")
                # 外資買方 - 賣方未平倉
                try:
                    # 典型格式: 日期, 商品名稱, 身份別, 多方口數, 多方契約金額, 空方口數, 空方契約金額, 多空淨額口數, ...
                    net_str = parts[7].replace(",", "").strip()
                    net_lot = int(net_str)
                    break
                except Exception:
                    continue
        if net_lot is not None:
            dt = date.today().strftime("%Y-%m-%d")
            with db() as conn:
                upsert_series(conn, dt, "FOREIGN_FUTURES_NET", net_lot, "TAIFEX")
            log.info(f"[fetcher] FOREIGN_FUTURES_NET: {net_lot} 張")
    except Exception as e:
        log.warning(f"[fetcher] TAIFEX 外資期貨 失敗: {e}")
