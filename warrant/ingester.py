"""
資料層 — 合約檔、盤後資料、永豐 BIV backfill
"""
import json
import re
import time
import logging
from datetime import date, datetime
from typing import Optional

import httpx
import requests

from .db import db, upsert_warrant, upsert_underlying

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ── 民國年 → 西元 ──────────────────────────────────────────────────
def minguo_to_date(s: str) -> Optional[str]:
    """'1151021' → '2026-10-21'"""
    if not s or len(s) < 7:
        return None
    try:
        yr = int(s[:3]) + 1911
        mo = int(s[3:5])
        dd = int(s[5:7])
        return f"{yr:04d}-{mo:02d}-{dd:02d}"
    except Exception:
        return None


# ── 類別 → style ────────────────────────────────────────────────────
def parse_style(category: str) -> str:
    if "重設" in category or "上限" in category or "下限" in category:
        if "上限" in category or "下限" in category:
            return "CAPPED"
        return "RESET"
    return "PLAIN"


# ── 發行商識別（從簡稱萃取）─────────────────────────────────────────
ISSUERS = [
    "元大","凱基","富邦","群益","國泰","統一","永豐","日盛","兆豐",
    "中信","台新","國票","第一金","宏遠","華南","玉山","安泰","陽信",
    "大昌","致和","合庫","遠東","大眾","福邦","大展","士林","上海",
]

def parse_issuer(name: str) -> str:
    for iss in ISSUERS:
        if iss in name:
            return iss
    # fallback: 取簡稱前 2~3 個字
    return name[:3] if name else "未知"


# ── 永豐 basic.js（標的代號 + 發行商補充）──────────────────────────
_sinopac_warrant_map: dict = {}     # code → {i: underlying_code, d: issuer, k: CALL/PUT}
_sinopac_loaded_at: Optional[datetime] = None

def load_sinopac_basic() -> dict:
    global _sinopac_warrant_map, _sinopac_loaded_at

    if (_sinopac_loaded_at and
            (datetime.now() - _sinopac_loaded_at).total_seconds() < 3600):
        return _sinopac_warrant_map

    log.info("[ingester] 載入永豐 basic.js ...")
    try:
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            client.get("https://warrant.sinotrade.com.tw/want/wHistBidIV.aspx",
                       headers=HEADERS)
            r = client.get("https://warrant.sinotrade.com.tw/wdataV2/res/basic.js",
                           headers=HEADERS)
        text = r.content.decode("big5", errors="replace")

        # Parse: w={ s:'064692', n:'...', k:'C', xLa:T, d:'元大', i:'2330' };
        pattern = re.compile(
            r"w=\{[^}]*s:'(\w+)'[^}]*n:'([^']*)'[^}]*k:'([CP])'[^}]*d:'([^']*)'[^}]*i:'([^']*)'",
        )
        result = {}
        for m in pattern.finditer(text):
            code, name, k, issuer, underlying = m.groups()
            result[code] = {
                "code": code,
                "name": name,
                "kind": "CALL" if k == "C" else "PUT",
                "issuer": issuer,
                "underlying_code": underlying,
            }
        _sinopac_warrant_map = result
        _sinopac_loaded_at = datetime.now()
        log.info(f"[ingester] basic.js 載入 {len(result)} 筆")
        return result
    except Exception as e:
        log.warning(f"[ingester] basic.js 失敗: {e}")
        return _sinopac_warrant_map


# ── TWSE / TPEx 合約檔 ──────────────────────────────────────────────
def fetch_twse_warrants() -> list[dict]:
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap37_L"
    log.info("[ingester] 抓 TWSE t187ap37_L ...")
    r = requests.get(url, headers=HEADERS, timeout=90)
    return json.loads(r.content.decode("utf-8"))


def fetch_tpex_warrants() -> list[dict]:
    url = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap37_O"
    log.info("[ingester] 抓 TPEx t187ap37_O ...")
    r = requests.get(url, headers=HEADERS, timeout=90)
    return json.loads(r.content.decode("utf-8"))


def _parse_warrant_row(row: dict, market: str, sinopac_map: dict) -> Optional[dict]:
    code = row.get("權證代號", "").strip()
    if not code:
        return None

    name      = row.get("權證簡稱", "")
    kind_raw  = row.get("權證類型", "")
    style_raw = row.get("類別", "")
    K_str     = row.get("最新履約價格(元)/履約指數", "0")
    N_str     = row.get("最新標的履約配發數量(每仟單位權證)", "0")
    last_td   = row.get("最後交易日", "")
    expiry    = row.get("履約截止日", "")
    listed    = row.get("履約開始日", "")
    issued    = row.get("發行單位數量(仟單位)", "0")
    settlement= row.get("結算方式(詳附註編號說明)", "")

    kind = "CALL" if kind_raw == "認購" else "PUT" if kind_raw == "認售" else None
    if kind is None:
        return None

    style = parse_style(style_raw)

    try:
        K = float(K_str or 0)
        N_api = float(N_str or 0)
        N = N_api / 1000        # ★ 轉換：每仟單位 → 每單位
        issued_lots = int(float(issued or 0) * 1000)  # 仟單位 → 張
    except Exception:
        return None

    if K <= 0 or N <= 0:
        return None

    last_trade_date = minguo_to_date(last_td)
    expiry_date     = minguo_to_date(expiry)
    listed_date     = minguo_to_date(listed)

    if not last_trade_date:
        return None

    # 標的代號：優先 TWSE/TPEx 官方欄位，fallback 永豐 basic.js
    ul_code_api = (
        row.get("標的有價證券代號", "").strip() or
        row.get("標的證券代號", "").strip() or
        row.get("標的代號", "").strip()
    )
    # 只接受 ASCII 英數字組成的股票代號（台股 4~6 碼，排除中文/指數名稱）
    if ul_code_api and not re.match(r'^[0-9A-Za-z]{2,6}$', ul_code_api):
        ul_code_api = ""
    sp = sinopac_map.get(code, {})
    underlying_code = ul_code_api or sp.get("underlying_code") or None
    issuer = sp.get("issuer") or parse_issuer(name)

    return {
        "code": code,
        "name": name,
        "market": market,
        "issuer": issuer,
        "kind": kind,
        "style": style,
        "underlying_code": underlying_code,
        "strike": K,
        "exercise_ratio": N,
        "listed_date": listed_date,
        "last_trade_date": last_trade_date,
        "expiry_date": expiry_date or last_trade_date,
        "issued_lots": issued_lots,
        "settlement": settlement,
    }


def ingest_contracts():
    """每日 08:00：更新合約檔"""
    sinopac_map = load_sinopac_basic()

    twse_rows = fetch_twse_warrants()
    tpex_rows = fetch_tpex_warrants()

    today_str = date.today().strftime("%Y-%m-%d")
    warrants_upserted = 0
    underlyings_upserted = set()

    with db() as conn:
        for row, market in [(r, "TSE") for r in twse_rows] + \
                           [(r, "OTC") for r in tpex_rows]:
            w = _parse_warrant_row(row, market, sinopac_map)
            if not w:
                continue

            # Upsert underlying（只用名稱，代號來自 basic.js）
            ul_code = w["underlying_code"]
            ul_name = row.get("標的證券/指數", "")
            if ul_code and ul_code not in underlyings_upserted:
                ul_market = "TSE" if market == "TSE" else "OTC"
                upsert_underlying(conn, ul_code, ul_name, ul_market)
                underlyings_upserted.add(ul_code)

            upsert_warrant(conn, w)
            warrants_upserted += 1

    log.info(f"[ingester] 合約檔更新完成: {warrants_upserted} 筆, "
             f"{len(underlyings_upserted)} 個標的")
    return warrants_upserted


# ── 永豐 BIV Backfill ────────────────────────────────────────────────
def fetch_sinopac_biv(underlying_code: str) -> Optional[dict]:
    """從永豐取某標的的歷史 BIV"""
    try:
        with httpx.Client(follow_redirects=True, timeout=30) as client:
            client.get("https://warrant.sinotrade.com.tw/want/wHistBidIV.aspx",
                       headers=HEADERS)
            r = client.get(
                "https://warrant.sinotrade.com.tw/j/json_biv.jsp",
                params={"ul": underlying_code, "callback": "cb"},
                headers=HEADERS,
            )
        text = r.content.decode("big5", errors="replace")
        m = re.search(r"cb\s*\(\s*(\{.*\})\s*\)", text, re.DOTALL)
        if not m:
            return None
        return json.loads(m.group(1))
    except Exception as e:
        log.warning(f"[ingester] sinopac_biv {underlying_code}: {e}")
        return None


def backfill_biv_for_underlyings(underlying_codes: list[str]):
    """每日 08:45：永豐 BIV backfill → iv_daily"""
    total = 0
    for code in underlying_codes:
        data = fetch_sinopac_biv(code)
        if not data or not data.get("wants"):
            continue

        sdates = data.get("sdates", [])
        sdkeys = data.get("sdkeys", [])

        with db() as conn:
            for want in data["wants"]:
                wcode = want.get("s")
                bivs = want.get("bivs", {})
                for skey, sdate in zip(sdkeys, sdates):
                    if skey not in bivs:
                        continue
                    biv = bivs[skey].get("biv")
                    if biv is None:
                        continue
                    trade_date = sdate.replace("/", "-")   # "2026/08/20" → "2026-08-20"
                    conn.execute("""
                        INSERT OR IGNORE INTO iv_daily
                            (warrant_code, trade_date, source, bid_iv)
                        VALUES(?,?,?,?)
                    """, (wcode, trade_date, "SINOPAC", biv / 100))
                    total += 1

        time.sleep(0.3)   # 防止過快

    log.info(f"[ingester] BIV backfill 完成: {total} 筆")
    return total


def get_active_underlying_codes() -> list[str]:
    """取 watchlist 或所有有效權證的標的代號"""
    with db() as conn:
        rows = conn.execute("""
            SELECT DISTINCT underlying_code FROM warrants
            WHERE is_active=1 AND underlying_code IS NOT NULL
              AND last_trade_date >= date('now')
        """).fetchall()
        return [r[0] for r in rows if r[0]]
