"""
資料層 — 合約檔、盤後資料、永豐 BIV backfill
"""
import json
import os
import re
import time
import logging
from pathlib import Path
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
        # 使用欄位獨立萃取，不依賴順序
        block_pat = re.compile(r"w=\{([^}]*)\}")
        field_pat = re.compile(r"(\w+):'([^']*)'")
        result = {}
        for bm in block_pat.finditer(text):
            block = bm.group(1)
            fields = dict(field_pat.findall(block))
            code = fields.get("s", "")
            if not code:
                continue
            result[code] = {
                "code": code,
                "name": fields.get("n", ""),
                "kind": "CALL" if fields.get("k") == "C" else "PUT",
                "issuer": fields.get("d", ""),
                "underlying_code": fields.get("i", "") or None,
            }
        # 如果新格式解析失敗，嘗試舊格式
        if not result:
            old_pat = re.compile(
                r"w=\{[^}]*s:'(\w+)'[^}]*n:'([^']*)'[^}]*k:'([CP])'[^}]*d:'([^']*)'[^}]*i:'([^']*)'",
            )
            for m in old_pat.finditer(text):
                code, name, k, issuer, underlying = m.groups()
                result[code] = {
                    "code": code,
                    "name": name,
                    "kind": "CALL" if k == "C" else "PUT",
                    "issuer": issuer,
                    "underlying_code": underlying or None,
                }
        _sinopac_warrant_map = result
        _sinopac_loaded_at = datetime.now()
        log.info(f"[ingester] basic.js 載入 {len(result)} 筆")
        return result
    except Exception as e:
        log.warning(f"[ingester] basic.js 失敗: {e}")
        return _sinopac_warrant_map


# ── TWSE / TPEx 合約檔 ──────────────────────────────────────────────
# 證交所合約 JSON 約 45MB（4.5 萬檔）、櫃買約 17MB：以前 r.json() 整包載入，記憶體一次多 200MB 以上，
# 正式站（512MB）跑全系統更新時被系統砍掉（2026-10-21 OOM）。PLAN-B77 A1：串流下載到暫存檔，ijson 一筆一筆讀。
TWSE_URLS = [
    "https://openapi.twse.com.tw/v1/opendata/t187ap37_L",
    "https://www.twse.com.tw/rwd/zh/warrant/t187ap37_L?response=json",
]
TPEX_URLS = [
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap37_O",
    "https://www.tpex.org.tw/web/bond/warrant/q_warrant/warrant_detail_lists.php?o=json",
]
TMP_DIR = Path(__file__).parent.parent / "chip_data" / "tmp"
MAX_DOWNLOAD = 200 * 1024 * 1024     # 超過就中止（正常約 45MB）


def _top_char(path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(256).lstrip(b"\xef\xbb\xbf \t\r\n")
    return chr(head[0]) if head else ""


def iter_rows(path: Path):
    """逐筆讀合約檔：頂層陣列 [{...}] 或 rwd 格式 {"fields":[...], "data":[[...]]}；每次只有一筆在記憶體"""
    import ijson
    top = _top_char(path)
    with open(path, "rb") as f:
        if top == "[":
            for row in ijson.items(f, "item", use_float=True):
                if isinstance(row, dict):
                    yield row
        elif top == "{":
            fields = list(ijson.items(f, "fields.item"))
            if not fields:
                return
            f.seek(0)                                   # 第二次從頭讀（審查 Gemini 第 3 輪 F1）
            for row in ijson.items(f, "data.item", use_float=True):
                if isinstance(row, list):
                    yield dict(zip(fields, row))


def download_rows_file(urls: list, label: str) -> Optional[Path]:
    """依序試每個網址，串流存成暫存檔，至少讀得到 1 筆才算成功；回傳檔案路徑（用完要自己刪）"""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    for url in urls:
        tmp = TMP_DIR / f"{label}_{os.getpid()}_{int(time.time() * 1000)}.json"
        try:
            log.info(f"[ingester] 抓 {label} 權證: {url}")
            size = 0
            with requests.get(url, headers=HEADERS, timeout=90, stream=True) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        size += len(chunk)
                        if size > MAX_DOWNLOAD:
                            raise RuntimeError(f"檔案超過 {MAX_DOWNLOAD // 1024 // 1024}MB，中止")
                        f.write(chunk)
            if next(iter_rows(tmp), None) is not None:
                log.info(f"[ingester] {label} 下載 {size / 1e6:.1f}MB")
                return tmp
            log.warning(f"[ingester] {label} {url} 沒有資料")
        except Exception as e:
            log.warning(f"[ingester] {label} {url} 失敗: {e}")
        try:
            tmp.unlink()
        except Exception:
            pass
    return None


def _fetch_rows(urls: list, label: str, limit: Optional[int]) -> list:
    path = download_rows_file(urls, label)
    if not path:
        raise RuntimeError(f"{label} 所有端點均失敗")
    try:
        out = []
        for row in iter_rows(path):
            out.append(row)
            if limit and len(out) >= limit:
                break
        return out
    finally:
        try:
            path.unlink()
        except Exception:
            pass


def fetch_twse_warrants(limit: Optional[int] = None) -> list:
    """證交所合約（診斷用；limit 只拿前幾筆。整批更新用 ingest_contracts，它不會整包放進記憶體）"""
    return _fetch_rows(TWSE_URLS, "TWSE", limit)


def fetch_tpex_warrants(limit: Optional[int] = None) -> list:
    return _fetch_rows(TPEX_URLS, "TPEx", limit)


def count_rows(urls: list, label: str) -> dict:
    """診斷：串流數筆數＋前 3 筆，不整包載入"""
    path = download_rows_file(urls, label)
    if not path:
        return {"error": f"{label} 所有端點均失敗"}
    try:
        n, head = 0, []
        for row in iter_rows(path):
            n += 1
            if len(head) < 3:
                head.append(row)
        return {"count": n, "head": head}
    finally:
        try:
            path.unlink()
        except Exception:
            pass


def release_sinopac():
    """永豐對照表（4.4 萬筆）用完就放掉；flow.py 需要時會重新下載"""
    global _sinopac_warrant_map, _sinopac_loaded_at
    _sinopac_warrant_map = {}
    _sinopac_loaded_at = None


def _parse_warrant_row(row: dict, market: str, sinopac_map: dict, name_to_code: dict = {}) -> Optional[dict]:
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

    # 標的代號：優先永豐 basic.js（有 code），fallback 從標的名稱查
    sp = sinopac_map.get(code, {})
    underlying_code = sp.get("underlying_code") or None
    # fallback 1: TWSE/TPEx 直接欄位（部分格式有 標的代號）
    if not underlying_code:
        underlying_code = row.get("標的代號", "").strip() or \
                          row.get("標的證券代號", "").strip() or None
    # fallback 2: 從「標的有價證券代號及名稱」解析（格式 "2330 台積電" 或 "2330　台積電"）
    if not underlying_code:
        combined = row.get("標的有價證券代號及名稱", "").strip() or \
                   row.get("標的證券代號及名稱", "").strip()
        if combined:
            for part in re.split(r"[\s\u3000]+", combined):
                if re.match(r"^\d{4,6}$", part):
                    underlying_code = part
                    break
    # fallback 3: 從標的名稱查 name_to_code
    if not underlying_code:
        ul_name = row.get("標的證券/指數", "").strip()
        if ul_name:
            underlying_code = name_to_code.get(ul_name) or None
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
    """每日 08:00＋全系統更新：更新合約檔（串流兩趟，記憶體只放對照表，PLAN-B77 A1）"""
    # 永豐 basic.js（失敗不中斷，繼續用 TWSE 欄位解析）
    try:
        sinopac_map = load_sinopac_basic()
    except Exception as e:
        log.warning(f"[ingester] sinopac basic.js 失敗，繼續: {e}")
        sinopac_map = {}

    files = []
    warrants_upserted = 0
    underlyings_upserted = set()
    try:
        twse_path = download_rows_file(TWSE_URLS, "TWSE")
        if twse_path:
            files.append(twse_path)                 # 下載好就登記，中途出錯 finally 也刪得到（審查 Gemini B-F3）
        else:
            log.error("[ingester] TWSE 合約抓取失敗")
        tpex_path = download_rows_file(TPEX_URLS, "TPEx")
        if tpex_path:
            files.append(tpex_path)
        else:
            log.error("[ingester] TPEx 合約抓取失敗")
        sources = [(p, m) for p, m in ((twse_path, "TSE"), (tpex_path, "OTC")) if p]
        if not sources:
            log.error("[ingester] TWSE 與 TPEx 皆無資料，嘗試用現有 DB 重建 underlyings")
            rebuild_underlyings_from_warrants()
            return 0

        # ── 第 1 趟：標的名稱 → 標的代號 對照表 ────────────────────────────
        # 方法：用 TWSE/TPEx 的 '標的證券/指數'（名稱）+ 永豐 basic.js（代號）交叉比對
        # 例：TWSE 資料有 "04004S": 標的="台積電"；永豐有 "04004S": underlying_code="2330"
        # → 推導出 "台積電" → "2330"
        warrant_to_ul_name: dict = {}
        for path, market in sources:
            n = 0
            for row in iter_rows(path):
                n += 1
                w_code = str(row.get("權證代號", "") or "").strip()
                ul_name = str(row.get("標的證券/指數", "") or "").strip()
                if w_code and ul_name:
                    warrant_to_ul_name[w_code] = ul_name
            log.info(f"[ingester] {'TWSE' if market == 'TSE' else 'TPEx'} 合約: {n} 筆")

        name_to_code: dict = {}
        for w_code, sp in sinopac_map.items():
            ul_code = sp.get("underlying_code", "")
            ul_name = warrant_to_ul_name.get(w_code, "")
            if ul_code and ul_name and ul_name not in name_to_code:
                name_to_code[ul_name] = ul_code
        del warrant_to_ul_name

        # fallback: 從 stocks.csv 建立股名→股號對照（涵蓋 sinopac 未覆蓋的股票）
        try:
            import csv as _csv
            _csv_path = Path(__file__).parent.parent / "stocks.csv"
            if _csv_path.exists():
                with open(_csv_path, encoding="utf-8") as _f:
                    for _row in _csv.DictReader(_f):
                        _sid = _row.get("stock_id", "").strip()
                        _sname = _row.get("stock_name", "").strip()
                        if _sid and _sname and _sname not in name_to_code:
                            name_to_code[_sname] = _sid
        except Exception as _e:
            log.warning(f"[ingester] stocks.csv fallback 失敗: {_e}")

        log.info(f"[ingester] name_to_code: {len(name_to_code)} 個標的（含 stocks.csv）")

        # ── 第 2 趟：逐筆解析＋寫入（同一個交易，跟以前一樣）────────────────
        with db() as conn:
            for path, market in sources:
                for row in iter_rows(path):
                    w = _parse_warrant_row(row, market, sinopac_map, name_to_code)
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
    finally:
        for p in files:
            try:
                p.unlink()
            except Exception:
                pass
        release_sinopac()

    log.info(f"[ingester] 合約檔更新完成: {warrants_upserted} 筆, "
             f"{len(underlyings_upserted)} 個標的")

    # 若 underlyings 幾乎為空（可能因 API 欄位變動），自動從 warrants 重建
    with db() as conn:
        ul_cnt = conn.execute("SELECT COUNT(*) FROM underlyings").fetchone()[0]
    if ul_cnt < len(underlyings_upserted) * 0.5 or ul_cnt < 10:
        log.warning(f"[ingester] underlyings 僅 {ul_cnt} 筆，自動 rebuild...")
        rebuild_underlyings_from_warrants()

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


def rebuild_underlyings_from_warrants() -> int:
    """
    從 warrants 表重建 underlyings 表（當 ingest_contracts 無法取得標的代號時的補救措施）。
    使用 stocks.csv 補充股名。
    """
    import csv as _csv
    from pathlib import Path as _Path

    name_map: dict = {}
    try:
        csv_path = _Path(__file__).parent.parent / "stocks.csv"
        with open(csv_path, encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                sid  = row.get("stock_id", "").strip()
                name = row.get("stock_name", "").strip()
                if sid and name:
                    name_map[sid] = name
    except Exception as e:
        log.warning(f"[ingester] stocks.csv 讀取失敗: {e}")

    rebuilt = 0
    with db() as conn:
        rows = conn.execute("""
            SELECT DISTINCT underlying_code, market FROM warrants
            WHERE underlying_code IS NOT NULL AND underlying_code != ''
              AND is_active=1
        """).fetchall()
        for r in rows:
            code = r["underlying_code"]
            mkt  = "TSE" if r["market"] == "TSE" else "OTC"
            uname = name_map.get(code, code)
            upsert_underlying(conn, code, uname, mkt)
            rebuilt += 1

    log.info(f"[ingester] rebuild_underlyings_from_warrants: {rebuilt} 個標的")
    return rebuilt


def get_active_underlying_codes() -> list[str]:
    """取 watchlist 或所有有效權證的標的代號"""
    with db() as conn:
        rows = conn.execute("""
            SELECT DISTINCT underlying_code FROM warrants
            WHERE is_active=1 AND underlying_code IS NOT NULL
              AND last_trade_date >= date('now')
        """).fetchall()
        return [r[0] for r in rows if r[0]]
