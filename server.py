"""
server.py — FastAPI 後端
資料來源：Yahoo Finance（同 tw-macd-scan，不受 TWSE 封鎖）
功能：觀察清單 / 策略篩選（全市場）/ 個股資料 / Telegram 推播
"""

import asyncio
import json
import os
import sqlite3
from dotenv import load_dotenv
load_dotenv()  # 本機從 .env 載入；Render 用 dashboard 環境變數
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import httpx
import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from warrant.router import router as warrant_router, init_warrant, start_warrant_scheduler, stop_warrant_scheduler
from regime.router import router as regime_router
from regime.db import init_db as regime_init_db
from regime.fetcher import fetch_all as regime_fetch_all, fetch_twse_margin, fetch_twse_foreign_spot, fetch_twse_market_breadth, fetch_taifex_foreign_futures, fetch_mi5mins
from regime.factor import calculate_factors as regime_calc_factors, backfill_factors as regime_backfill_factors
from sector.router import router as sector_router
from sector.db import init_db as sector_init_db
from sector.universe import fetch_and_build_mapping as sector_build_mapping, is_initialized as sector_is_initialized
from positioning.router import router as positioning_router, _run_refresh as positioning_run_refresh
from positioning.db import init_db as init_positioning_db
from relationship.router import router as relationship_router
from relationship.db import init_db as init_relationship_db

from chip_tracker_v2 import (
    DATA_DIR, DB_PATH,
    get_conn, init_db,
    load_stock_history, update_stocks,
    DEFAULT_WEIGHTS, DEFAULT_THRESHOLDS,
    get_weights, get_thresholds, save_params,
)
from scanner import STRATEGY_PARAMS_SCHEMA
import supabase_store as sb

BASE_DIR = Path(__file__).parent

import time as _time

_FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiYnVidXN0IiwiZW1haWwiOiJidWJ1c3RAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.LcLL157_bH6YbABE7JOlg0cAEwwzOV6GfJA6uK2cvIA")

def _safe_num(v):
    """將 NaN/Inf 轉 None，確保 JSON 序列化安全。"""
    try:
        import math as _m
        f = float(v)
        return None if (not _m.isfinite(f)) else round(f, 6)
    except Exception:
        return None


def _sanitize_for_json(obj):
    """遞迴將所有 NaN/Inf float 轉 None，防止 JSON 序列化失敗。"""
    import math as _m
    if isinstance(obj, float):
        return None if not _m.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    return obj

async def _fetch_finmind_prices(stock_ids: list) -> dict:
    """FinMind TaiwanStockPrice 最終兜底，每次只查一支但並發。"""
    from datetime import date, timedelta
    start = (date.today() - timedelta(days=5)).strftime("%Y-%m-%d")
    result: dict = {}
    sem = asyncio.Semaphore(8)

    async def _one(sid):
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=10, verify=False) as client:
                    r = await client.get(
                        "https://api.finmindtrade.com/api/v4/data",
                        params={"dataset": "TaiwanStockPrice", "data_id": sid,
                                "start_date": start, "token": _FINMIND_TOKEN},
                    )
                    rows = r.json().get("data", [])
                    if not rows:
                        return
                    rows.sort(key=lambda x: x.get("date", ""))
                    latest = rows[-1]
                    close = float(latest.get("close") or 0)
                    if close <= 0:
                        return
                    pct = None
                    if len(rows) >= 2:
                        prev = float(rows[-2].get("close") or 0)
                        pct = round((close - prev) / prev * 100, 2) if prev > 0 else None
                    result[sid] = {"close": round(close, 2), "change_pct": pct}
            except Exception:
                pass

    await asyncio.gather(*[_one(sid) for sid in stock_ids])
    return result

# ── 觀察清單即時現價快取（MIS）───────────────────────────────────────────────
# MIS z 欄位：每次成交後更新，無新成交時回傳 "-"
# _STOCK_PRICE_CACHE：記住每支股票上次查到的真實 z 值，避免 z="-" 時 fallback 到昨收(y)
_PRICE_ALL: dict = {}           # 相容舊呼叫點用（實際未使用）
_PRICE_ALL_TS: float = 0.0
_PRICE_ALL_TTL: float = 20.0
_STOCK_PRICE_CACHE: dict = {}   # {stock_id: {"close": float, "change_pct": float}}

def _sf_price(s) -> "float | None":
    try:
        v = str(s).replace(",", "").strip()
        return float(v) if v and v not in ("-", "--", "N/A", "+", "-", "除", "X", "") else None
    except Exception:
        return None


async def _fetch_mis_prices(stock_ids: list, mkt_map: dict) -> dict:
    """
    TWSE MIS 即時報價（盤中每筆成交更新）。
    先 GET index.jsp 建立 session cookie，再查 getStockInfo.jsp → z 欄位才會有真實成交價。
    TSE → tse_XXXX.tw；OTC → otc_XXXX.tw
    z（成交價）有值 → 顯示真實漲跌；z="-" → 顯示昨收 y + change_pct=None（前端顯示 --）
    """
    if not stock_ids:
        return {}
    parts = []
    for sid in stock_ids:
        prefix = "otc" if mkt_map.get(sid) == "tpex" else "tse"
        parts.append(f"{prefix}_{sid}.tw")

    MIS_BASE = "https://mis.twse.com.tw"
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    # 一批最多 30 支，單一 client 先建立 session 再查詢
    BATCH = 30
    batches = [parts[i:i+BATCH] for i in range(0, len(parts), BATCH)]
    all_items = []

    async with httpx.AsyncClient(
        timeout=15, follow_redirects=True, verify=False,
        headers={
            "User-Agent": UA,
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    ) as client:
        # ── Step 1: 建立 session（取得 JSESSIONID cookie）────────────────
        try:
            await client.get(f"{MIS_BASE}/stock/index.jsp", timeout=10)
        except Exception as e:
            print(f"[MIS] index.jsp session 建立失敗（繼續嘗試）: {e}")

        # ── Step 2: 批次查詢 ─────────────────────────────────────────────
        for batch in batches:
            try:
                r = await client.get(
                    f"{MIS_BASE}/stock/api/getStockInfo.jsp",
                    headers={
                        "Accept":           "application/json, text/javascript, */*; q=0.01",
                        "Referer":          f"{MIS_BASE}/stock/index.jsp",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    params={
                        "ex_ch": "|".join(batch),
                        "json":  "1",
                        "delay": "0",
                        "_":     str(int(_time.time() * 1000)),
                    },
                )
                r.raise_for_status()
                all_items.extend(r.json().get("msgArray", []))
            except Exception as e:
                print(f"[MIS] batch 查詢失敗: {e}")
    items = all_items
    print(f"[MIS] 回傳 {len(items)} 筆")

    result = {}
    z_ok = 0
    for item in items:
        sid = item.get("c", "")
        if not sid:
            continue
        z = _sf_price(item.get("z"))
        y = _sf_price(item.get("y"))
        if z is not None and y and y > 0:
            # z 有真實成交價：更新 cache 並回傳
            pct = round((z - y) / y * 100, 2)
            entry = {"close": round(z, 2), "change_pct": pct}
            _STOCK_PRICE_CACHE[sid] = entry
            result[sid] = entry
            z_ok += 1
        elif sid in _STOCK_PRICE_CACHE:
            # z="-"（本次無新成交）：用上次 cache 的真實成交價
            result[sid] = _STOCK_PRICE_CACHE[sid]
        elif y is not None:
            # 從未抓到成交價：顯示昨收，change_pct=None（前端顯示 --）
            result[sid] = {"close": round(y, 2), "change_pct": None}
    print(f"[MIS] parsed={len(result)} 支，即時z={z_ok} 支，cache命中={len(result)-z_ok} 支")
    return result


async def _fetch_all_prices() -> dict:
    """為相容其他呼叫點保留，實際上回傳空 dict（watchlist 端點改用 _fetch_mis_prices）"""
    return _PRICE_ALL


def _is_tw_trading_hours() -> bool:
    """台股交易時間判斷：週一到五 09:00~13:35（台灣時間 UTC+8）"""
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz)
    if now.weekday() >= 5:  # 週六日
        return False
    mins = now.hour * 60 + now.minute
    return 540 <= mins <= 815  # 09:00 ~ 13:35


# ── price_cache warmup 狀態（供前端顯示） ────────────────────────────────────
# phase: "init" | "supabase" | "finmind" | "ready"
_warmup_status: dict = {"phase": "init", "days": 0}


# ════════════════════════════════════════════════════════════════════════════
# App 初始化
# ════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_warrant()
    regime_init_db()
    sector_init_db()
    init_positioning_db()
    init_relationship_db()
    start_warrant_scheduler()
    # 從 Supabase 恢復 watchlist 到本地 SQLite（Render 重啟後 SQLite 為空）
    try:
        _sb_wl = sb.wl_list()
        if _sb_wl:
            _wl_conn = get_conn()
            for _r in _sb_wl:
                _wl_conn.execute(
                    "INSERT OR IGNORE INTO watchlist (stock_id, name, added_at, note) VALUES (?,?,?,?)",
                    (_r["stock_id"], _r.get("name",""), _r.get("added_at",""), _r.get("note",""))
                )
            _wl_conn.commit()
            _wl_conn.close()
            print(f"[startup] 從 Supabase 恢復 {len(_sb_wl)} 筆觀察清單")
    except Exception as _wl_e:
        print(f"[startup] 觀察清單恢復失敗：{_wl_e}")
    # 從 Supabase 載入最新掃描結果（若本地 JSON 為空）
    try:
        from yahoo_price import _scan_status, _load_scan_cache
        if not _scan_status.get("results"):
            import supabase_store as _sb2
            import json as _json2
            _sb_raw = _sb2.kv_get("scan_latest")
            if _sb_raw:
                _sb_data = _json2.loads(_sb_raw)
                _scan_status["results"] = _sb_data.get("results", {})
                _scan_status["finished_at"] = _sb_data.get("scanned_at")
                print(f"[startup] 從 Supabase 載入掃描結果，scanned_at={_sb_data.get('scanned_at')}")
    except Exception as _e:
        print(f"[startup] 載入 Supabase 掃描結果失敗：{_e}")
    # 若 regime.db 無資料，背景啟動初始更新
    import threading
    from regime.db import db as _rdb
    with _rdb() as _c:
        _cnt = _c.execute("SELECT COUNT(*) FROM market_daily").fetchone()[0]
    if _cnt == 0:
        def _regime_init():
            try:
                regime_fetch_all(days=90)
                fetch_twse_margin()
                fetch_twse_foreign_spot()
                fetch_twse_market_breadth(lookback=90)
                fetch_taifex_foreign_futures()
                fetch_mi5mins()
                regime_calc_factors()
                regime_backfill_factors(days=120)
            except Exception as _e:
                import logging; logging.getLogger(__name__).error(f"[regime_init] {_e}")
        threading.Thread(target=_regime_init, daemon=True).start()
    else:
        # 已有資料：補算缺失系列後再補算歷史因子
        def _regime_backfill():
            try:
                import logging as _log
                _lg = _log.getLogger(__name__)
                with _rdb() as _c2:
                    has_breadth  = _c2.execute(
                        "SELECT 1 FROM market_daily WHERE series='BREADTH_50MA' LIMIT 1"
                    ).fetchone()
                    has_futures  = _c2.execute(
                        "SELECT 1 FROM market_daily WHERE series='FOREIGN_FUTURES_NET' LIMIT 1"
                    ).fetchone()
                    has_oh       = _c2.execute(
                        "SELECT 1 FROM market_daily WHERE series='OVERHEATING_INDEX' LIMIT 1"
                    ).fetchone()
                if not has_breadth:
                    _lg.info("[regime_backfill] BREADTH_50MA 缺失，重新抓取廣度資料")
                    fetch_twse_market_breadth(lookback=90)
                if not has_futures:
                    _lg.info("[regime_backfill] FOREIGN_FUTURES_NET 缺失，重新抓取期貨資料")
                    fetch_taifex_foreign_futures()
                if not has_oh:
                    _lg.info("[regime_backfill] OVERHEATING_INDEX 缺失，重新抓取 MI5MINS")
                    fetch_mi5mins()
                regime_backfill_factors(days=120)
            except Exception as _e:
                import logging; logging.getLogger(__name__).error(f"[regime_backfill] {_e}")
        threading.Thread(target=_regime_backfill, daemon=True).start()
    # 若 sector_master 為空，背景初始化產業對照表
    if not sector_is_initialized():
        def _sector_init():
            try:
                sector_build_mapping()
            except Exception as _e:
                import logging; logging.getLogger(__name__).error(f"[sector_init] {_e}")
        threading.Thread(target=_sector_init, daemon=True).start()
    else:
        # sector_master 已有資料，但若 sector_daily 是空的 → 自動觸發計算
        def _sector_auto_calc():
            try:
                from sector.db import db as _sdb
                with _sdb() as _sc:
                    cnt = _sc.execute("SELECT COUNT(*) FROM sector_daily").fetchone()[0]
                if cnt == 0:
                    import logging; logging.getLogger(__name__).info("[sector] sector_daily 空，自動觸發計算...")
                    from sector.prices import backfill
                    from sector.engine import run_sector_engine
                    backfill(days=130)
                    run_sector_engine(days_back=60)
            except Exception as _e:
                import logging; logging.getLogger(__name__).error(f"[sector_auto_calc] {_e}")
        threading.Thread(target=_sector_auto_calc, daemon=True).start()
    # 若 relationship.db 無資料、資料過時、或 events=0，背景啟動初始更新
    try:
        from relationship.db import get_conn as _rel_conn
        _rel_c = _rel_conn()
        _rel_row = _rel_c.execute("SELECT COUNT(*) as cnt, MAX(observation_date) as latest FROM market_daily").fetchone()
        _rel_cnt = _rel_row["cnt"] if _rel_row else 0
        _rel_latest = _rel_row["latest"] if _rel_row else None
        _rel_events = _rel_c.execute("SELECT COUNT(*) FROM market_events").fetchone()[0]
        _rel_c.close()
        from datetime import date as _date_cls, timedelta as _td_cls
        _rel_stale = (_rel_latest is None) or (str(_rel_latest) < str((_date_cls.today() - _td_cls(days=2)).isoformat()))
        if _rel_cnt == 0 or _rel_stale or _rel_events == 0:
            def _relationship_init():
                try:
                    from relationship.router import _run_refresh as _rel_refresh
                    import logging; logging.getLogger(__name__).info(f"[relationship] 觸發更新（rows={_rel_cnt}, stale={_rel_stale}, events={_rel_events}）")
                    _rel_refresh(days=400)
                except Exception as _e:
                    import logging; logging.getLogger(__name__).error(f"[relationship_init] {_e}")
            threading.Thread(target=_relationship_init, daemon=True).start()
    except Exception as _rel_e:
        import logging; logging.getLogger(__name__).warning(f"[relationship_check] {_rel_e}")
    # 啟動 relationship 排程（每個交易日 17:00 自動更新，days=30 確保近期事件都產生）
    try:
        from apscheduler.schedulers.background import BackgroundScheduler as _RelSched
        import pytz as _pytz
        _rel_scheduler = _RelSched(timezone=_pytz.timezone("Asia/Taipei"))
        _rel_scheduler.add_job(
            lambda: __import__('threading').Thread(target=lambda: __import__('relationship.router', fromlist=['_run_refresh'])._run_refresh(days=30), daemon=True).start(),
            "cron", day_of_week="mon-fri", hour=17, minute=0,
            id="relationship_daily", replace_existing=True,
        )
        _rel_scheduler.start()
    except Exception as _rel_sch_e:
        import logging; logging.getLogger(__name__).warning(f"[relationship_scheduler] {_rel_sch_e}")
    # 啟動 positioning 排程（每個交易日 16:45 自動更新）
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        import pytz
        _pos_scheduler = BackgroundScheduler(timezone=pytz.timezone("Asia/Taipei"))
        _pos_scheduler.add_job(
            lambda: positioning_run_refresh(),
            "cron",
            day_of_week="mon-fri",
            hour=16,
            minute=45,
            id="positioning_daily",
            replace_existing=True,
        )
        _pos_scheduler.start()
    except Exception as _e:
        import logging; logging.getLogger(__name__).warning(f"[positioning_scheduler] {_e}")
    # 若 positioning_daily 無資料，背景啟動歷史回填（30個交易日）
    try:
        from positioning.db import get_conn as _pos_conn
        _pos_cnt = _pos_conn().execute("SELECT COUNT(*) FROM positioning_daily").fetchone()[0]
        if _pos_cnt == 0:
            def _positioning_init():
                try:
                    import asyncio
                    from datetime import date, timedelta, datetime, timezone
                    import logging as _log
                    _log.getLogger(__name__).info("[positioning] DB 空，啟動歷史回填（30 交易日）...")
                    from positioning.fetcher import fetch_all
                    from positioning.calculator import compute_positioning
                    tw_now = datetime.now(timezone(timedelta(hours=8)))
                    td = tw_now.date()
                    if tw_now.hour < 16:
                        td -= timedelta(days=1)
                    count = 0
                    for i in range(60):  # iterate extra to skip weekends
                        d = td - timedelta(days=i)
                        if d.weekday() >= 5:
                            continue
                        if count >= 30:
                            break
                        try:
                            raw = asyncio.run(fetch_all(d))
                            compute_positioning(raw, target_date=raw.get("observation_date"))
                            count += 1
                        except Exception as _day_e:
                            _log.getLogger(__name__).warning(f"[positioning_init] {d}: {_day_e}")
                    _log.getLogger(__name__).info(f"[positioning] 回填完成，共 {count} 筆")
                except Exception as _e:
                    import logging; logging.getLogger(__name__).error(f"[positioning_init] {_e}")
            threading.Thread(target=_positioning_init, daemon=True).start()
    except Exception as _pos_e:
        import logging; logging.getLogger(__name__).warning(f"[positioning_init_check] {_pos_e}")
    # 啟動觀察清單籌碼定期自動更新
    # - 盤中每小時更新（09:00~13:00），確保開盤隨時可看到最新價格
    # - 收盤後 15:00 再更新一次（完整資料）
    try:
        from apscheduler.schedulers.background import BackgroundScheduler as _ChipSched
        import pytz as _cpytz
        _chip_scheduler = _ChipSched(timezone=_cpytz.timezone("Asia/Taipei"))
        async def _auto_chip_refresh():
            import logging as _lg
            try:
                _lg.getLogger(__name__).info("[auto_chip] 自動更新觀察清單籌碼...")
                import supabase_store as _sb
                _sids = _sb.wl_get_ids()
                if not _sids:
                    _conn = get_conn()
                    _rows = _conn.execute("SELECT stock_id FROM watchlist").fetchall()
                    _conn.close()
                    _sids = [r["stock_id"] for r in _rows]
                if _sids:
                    await update_stocks(_sids, days=30)
                    settings_set("last_refresh", datetime.now().isoformat())
                    _lg.getLogger(__name__).info(f"[auto_chip] 完成 {len(_sids)} 檔")
            except Exception as _ace:
                _lg.getLogger(__name__).error(f"[auto_chip] {_ace}")
        def _auto_chip_sync():
            import asyncio as _aio
            _aio.run(_auto_chip_refresh())
        # 盤中每小時（09~13點整）
        _chip_scheduler.add_job(
            _auto_chip_sync, "cron",
            day_of_week="mon-fri", hour="9-13", minute=0,
            id="chip_intraday", replace_existing=True,
        )
        # 盤後 15:00 補完整日資料
        _chip_scheduler.add_job(
            _auto_chip_sync, "cron",
            day_of_week="mon-fri", hour=15, minute=0,
            id="chip_daily", replace_existing=True,
        )
        _chip_scheduler.start()
    except Exception as _cp_e:
        import logging; logging.getLogger(__name__).warning(f"[chip_scheduler] {_cp_e}")
    # price_daily TWSE 快取：每日 14:00 抓最新一天（供 Yahoo 限流時 fallback 使用）
    try:
        from apscheduler.schedulers.background import BackgroundScheduler as _PriceSched
        import pytz as _ppytz
        _price_sched = _PriceSched(timezone=_ppytz.timezone("Asia/Taipei"))
        def _price_cache_sync():
            import asyncio as _aio
            async def _inner():
                from price_cache import update_price_cache, init_price_db
                init_price_db()
                await update_price_cache(local_mode=False)
            _aio.run(_inner())
        _price_sched.add_job(
            _price_cache_sync, "cron",
            day_of_week="mon-fri", hour=14, minute=30,
            id="price_cache_daily", replace_existing=True,
        )
        _price_sched.start()
    except Exception as _pce:
        import logging; logging.getLogger(__name__).warning(f"[price_cache_scheduler] {_pce}")
    # 啟動時初始化 price_daily 表，抓今日 TWSE 全市場收盤（輕量，~1MB，無 OOM 風險）
    try:
        from price_cache import init_price_db
        init_price_db()
        def _price_init_today():
            import asyncio as _aio
            async def _inner():
                import logging as _lg
                _lg.getLogger(__name__).info("[price_cache] 抓今日 TWSE 收盤資料...")
                from price_cache import update_price_cache
                result = await update_price_cache(local_mode=False)
                _lg.getLogger(__name__).info(f"[price_cache] 完成：{result}")
            _aio.run(_inner())
        threading.Thread(target=_price_init_today, daemon=True).start()
    except Exception as _pcbe:
        import logging; logging.getLogger(__name__).warning(f"[price_cache_init] {_pcbe}")
    # 冷啟動偵測：若歷史快取 < 60 天，先試 Supabase 恢復（快），不夠再用 FinMind 回填
    # 有了歷史，掃描就能直接讀 cache，不必打 Yahoo，消除 IP 限流問題
    try:
        import os as _os
        def _price_backfill_cold():
            import asyncio as _aio, time as _t, logging as _lg
            _t.sleep(15)   # 等 update_price_cache 先跑完
            async def _inner():
                from price_cache import (get_cached_dates, get_price_cache_status,
                                         get_stocks_with_history, update_price_cache)
                n = len(get_cached_dates())
                st = get_price_cache_status()
                stock_cnt = st.get("stocks", 0)
                # 用「有 100 天歷史的股票數」判斷，避免 TPEX 只有 1 天被誤判為就緒
                warm_stocks = get_stocks_with_history(min_days=100)
                # 熱股票數夠（涵蓋上市+上櫃 2119 支中的多數）才算真的就緒
                if warm_stocks >= 1500:
                    _lg.getLogger(__name__).info(
                        f"[price_cache] 快取已有 {n} 天 / {warm_stocks} 支（100天+），跳過回填")
                    _warmup_status["phase"] = "ready"
                    _warmup_status["days"]  = n
                    return
                _lg.getLogger(__name__).info(
                    f"[price_cache] 冷啟動（{n} 天 / {warm_stocks} 支有歷史），開始補全流程...")
                # ── step0：強制抓 TWSE（上市）+TPEX（上櫃）全市場，確保股票清單完整 ──
                # 注意：不能用 update_price_cache，它遇到 dt_str 已快取就提前返回，
                # 導致只有 37 支舊資料的日期被跳過，FinMind 只回填那 37 支。
                # 這裡直接呼叫 openapi 並強制 save，覆蓋不完整的資料。
                _warmup_status["phase"] = "supabase"
                _warmup_status["days"]  = n
                try:
                    import httpx as _httpx, asyncio as _aio2
                    from price_cache import fetch_price_latest_openapi, fetch_price_latest_tpex, save_price_day
                    async with _httpx.AsyncClient() as _hc:
                        (_dt_str, _records), (_tpex_dt, _tpex_rec) = await _aio2.gather(
                            fetch_price_latest_openapi(_hc),
                            fetch_price_latest_tpex(_hc),
                        )
                    # 合併上市 + 上櫃
                    _final_dt = _dt_str or _tpex_dt
                    if _tpex_rec and _tpex_dt == _final_dt:
                        _existing = {r["stock_id"] for r in _records}
                        _records = _records + [r for r in _tpex_rec if r["stock_id"] not in _existing]
                    if _records:
                        save_price_day(_final_dt, _records)
                        _lg.getLogger(__name__).info(
                            f"[price_cache] OpenAPI 強制更新 {_final_dt}：{len(_records)} 支（含上櫃）")
                    else:
                        _lg.getLogger(__name__).warning("[price_cache] OpenAPI 回傳空資料")
                except Exception as _ue:
                    _lg.getLogger(__name__).warning(f"[price_cache] OpenAPI 強制更新失敗：{_ue}")
                # ── step1：Supabase 恢復（若歷史天數不足）────────────────
                if len(get_cached_dates()) < 60:
                    try:
                        from price_cache import restore_from_supabase
                        restored = await restore_from_supabase()
                        _lg.getLogger(__name__).info(f"[price_cache] Supabase 恢復：{restored} 筆")
                    except Exception as _se:
                        _lg.getLogger(__name__).warning(f"[price_cache] Supabase 恢復失敗：{_se}")
                # ── step2：FinMind 回填（若超額則改用 TWSE rwd 備援）───────
                _warmup_status["phase"] = "finmind"
                n2 = len(get_cached_dates())
                _warmup_status["days"] = n2
                fm_ok = False
                if _os.environ.get("FINMIND_TOKEN"):
                    _lg.getLogger(__name__).info(f"[price_cache] FinMind 回填（{n2} 天）...")
                    from price_cache import backfill_from_finmind
                    result = await backfill_from_finmind(days=260)
                    _warmup_status["days"] = len(get_cached_dates())
                    _lg.getLogger(__name__).info(f"[price_cache] FinMind 回填完成：{result}")
                    fm_ok = result.get("new_rows", 0) > 0
                # ── step3：TWSE rwd 備援（FinMind 失敗/超額時）──────────────
                st2 = get_price_cache_status()
                if not fm_ok and st2.get("stocks", 0) < 1000:
                    _warmup_status["phase"] = "twse_rwd"
                    _lg.getLogger(__name__).info("[price_cache] FinMind 無效，改用 TWSE rwd 回填 260 天...")
                    try:
                        from price_cache import update_price_cache
                        rwd_result = await update_price_cache(days=260, local_mode=True)
                        _warmup_status["days"] = len(get_cached_dates())
                        _lg.getLogger(__name__).info(f"[price_cache] TWSE rwd 回填完成：{rwd_result}")
                    except Exception as _re:
                        _lg.getLogger(__name__).warning(f"[price_cache] TWSE rwd 回填失敗：{_re}")
                # 只有真的足夠才算 ready
                final_n   = len(get_cached_dates())
                final_st  = get_price_cache_status()
                final_cnt = final_st.get("stocks", 0)
                _warmup_status["days"]  = final_n
                if final_n >= 60 and final_cnt >= 1000:
                    _warmup_status["phase"] = "ready"
                elif final_n >= 60:
                    _warmup_status["phase"] = "insufficient"
                else:
                    _warmup_status["phase"] = "insufficient"
            _aio.run(_inner())
        threading.Thread(target=_price_backfill_cold, daemon=True).start()
    except Exception as _bfe:
        import logging; logging.getLogger(__name__).warning(f"[price_cache_backfill] {_bfe}")
    yield
    stop_warrant_scheduler()

app = FastAPI(title="籌碼追蹤系統", lifespan=lifespan)

# 掛載 warrant 路由（prefix=/warrant）
app.include_router(warrant_router, prefix="/warrant")

# 掛載 regime 路由
app.include_router(regime_router, prefix="/regime")

# 掛載 sector 路由
app.include_router(sector_router, prefix="/sector")

# 掛載 warrant 前端靜態檔
WARRANT_FRONTEND = BASE_DIR / "warrant-frontend"
app.mount("/warrant/static", StaticFiles(directory=str(WARRANT_FRONTEND)), name="warrant_static")

# 掛載 regime 前端靜態檔
REGIME_FRONTEND = BASE_DIR / "regime-frontend"
app.mount("/regime/static", StaticFiles(directory=str(REGIME_FRONTEND)), name="regime_static")


@app.get("/regime/", include_in_schema=False)
def regime_index():
    from fastapi.responses import FileResponse
    return FileResponse(str(REGIME_FRONTEND / "index.html"))


# 掛載 sector 前端靜態檔
SECTOR_FRONTEND = BASE_DIR / "sector-frontend"
app.mount("/sector/static", StaticFiles(directory=str(SECTOR_FRONTEND)), name="sector_static")


@app.get("/sector/", include_in_schema=False)
def sector_index():
    return FileResponse(str(SECTOR_FRONTEND / "index.html"))

# 掛載 positioning 路由與前端靜態檔
app.include_router(positioning_router)
POSITIONING_FRONTEND = BASE_DIR / "positioning-frontend"
app.mount("/positioning/static", StaticFiles(directory=str(POSITIONING_FRONTEND)), name="positioning_static")

@app.get("/positioning/", include_in_schema=False)
def positioning_index():
    return FileResponse(str(POSITIONING_FRONTEND / "index.html"))

# 掛載 relationship 路由與前端靜態檔
app.include_router(relationship_router)
RELATIONSHIP_FRONTEND = BASE_DIR / "relationship-frontend"
app.mount("/relationship/static", StaticFiles(directory=str(RELATIONSHIP_FRONTEND)), name="relationship_static")

@app.get("/relationship/", include_in_schema=False)
def relationship_index():
    return FileResponse(str(BASE_DIR / "relationship-frontend" / "index.html"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ════════════════════════════════════════════════════════════════════════════
# Pydantic 模型
# ════════════════════════════════════════════════════════════════════════════

class WatchlistItem(BaseModel):
    stock_id: str
    name: Optional[str] = ""
    note: Optional[str] = ""   # 來源策略標注，例如 "S10 漲停"

class RefreshBody(BaseModel):
    date: Optional[str] = None
    backfill: Optional[int] = 30
    extra_stocks: Optional[list[str]] = []

class TelegramSettings(BaseModel):
    token: str
    chat_id: str

class CustomMessage(BaseModel):
    text: str

class ParamsBody(BaseModel):
    weights: dict
    thresholds: dict


# ════════════════════════════════════════════════════════════════════════════
# 設定 helpers
# ════════════════════════════════════════════════════════════════════════════

def settings_get(key: str) -> Optional[str]:
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None

def settings_set(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# Telegram helpers
# ════════════════════════════════════════════════════════════════════════════

async def tg_send(text: str) -> bool:
    token   = settings_get("telegram_token")
    chat_id = settings_get("telegram_chat_id")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
            return r.status_code == 200
    except Exception:
        return False

def log_push(stock_id: str, emoji: str, title: str, ok: bool):
    conn = get_conn()
    conn.execute(
        "INSERT INTO push_log (stock_id, signal_emoji, signal_title, pushed_at, ok) VALUES (?,?,?,?,?)",
        (stock_id, emoji, title, datetime.now().isoformat(), 1 if ok else 0)
    )
    conn.commit()
    conn.close()

def format_stock_message(stock_id: str, records: list[dict]) -> str:
    if not records:
        return f"<b>{stock_id}</b>\n無資料"
    latest = records[-1]
    recent = records[-7:] if len(records) >= 7 else records
    cum7 = sum(r.get("whale_flow_lots", 0) for r in recent)
    sig_emoji = latest.get("signal_emoji", "⚪")
    sig_title = latest.get("signal_title", "盤整")
    lines = [
        f"<b>{sig_emoji} {stock_id} — {sig_title}</b>",
        f"日期：{latest.get('date', '?')}",
        f"大戶流向：{latest.get('whale_flow_lots', 0):+,} 張",
        f"散戶流向：{latest.get('retail_flow_lots', 0):+,} 張",
        f"集中度：{latest.get('concentration_index', 0):.3f}",
        f"7日累計：{cum7:+,} 張",
    ]
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# Watchlist API
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/watchlist")
def api_get_watchlist():
    rows = sb.wl_list()
    if rows is not None:
        return rows
    conn = get_conn()
    rows = conn.execute("SELECT stock_id, name, added_at FROM watchlist ORDER BY added_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/watchlist")
def api_add_watchlist(item: WatchlistItem):
    sid  = item.stock_id.strip()
    name = (item.name or "").strip()
    note = (item.note or "").strip()
    now  = datetime.now().isoformat()
    sb.wl_add(sid, name, now, note)
    conn = get_conn()
    existing = conn.execute("SELECT note FROM watchlist WHERE stock_id=?", (sid,)).fetchone()
    if existing is None:
        # 新股票：直接插入
        conn.execute(
            "INSERT INTO watchlist (stock_id, name, added_at, note) VALUES (?,?,?,?)",
            (sid, name, now, note)
        )
    elif note:
        # 已存在 + 帶有策略來源：更新 note（Supabase 也同步）
        conn.execute("UPDATE watchlist SET note=? WHERE stock_id=?", (note, sid))
        sb.wl_update_note(sid, note)
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/api/watchlist/{stock_id}")
def api_del_watchlist(stock_id: str):
    sb.wl_delete(stock_id)
    sb.cd_delete_stock(stock_id)
    conn = get_conn()
    conn.execute("DELETE FROM watchlist WHERE stock_id=?", (stock_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.put("/api/watchlist/{stock_id}")
def api_update_watchlist(stock_id: str, item: WatchlistItem):
    name = (item.name or "").strip()
    sb.wl_update_name(stock_id, name)
    conn = get_conn()
    conn.execute("UPDATE watchlist SET name=? WHERE stock_id=?", (name, stock_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/watchlist/{stock_id}/memo")
async def api_update_memo(stock_id: str, request: Request):
    """更新個人備註（不影響策略 note 欄位）"""
    body = await request.json()
    memo = str(body.get("memo", "")).strip()
    conn = get_conn()
    conn.execute("UPDATE watchlist SET memo=? WHERE stock_id=?", (memo, stock_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/watchlist/{stock_id}/note")
async def api_update_note(stock_id: str, request: Request):
    """更新來源標籤"""
    body = await request.json()
    note = str(body.get("note", "")).strip()
    sb.wl_update_note(stock_id, note)
    conn = get_conn()
    conn.execute("UPDATE watchlist SET note=? WHERE stock_id=?", (note, stock_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/watchlist/sync_to_supabase")
def api_sync_watchlist_to_supabase():
    """將本地 SQLite watchlist 全部補推到 Supabase（修復清單遺失用）"""
    if not sb._enabled():
        return {"ok": False, "msg": "Supabase 未設定"}
    sb_rows = sb.wl_list() or []
    sb_ids = {r["stock_id"] for r in sb_rows}
    conn = get_conn()
    all_local = conn.execute("SELECT stock_id, name, added_at, note FROM watchlist").fetchall()
    conn.close()
    pushed = []
    for r in all_local:
        if r["stock_id"] not in sb_ids:
            ok = sb.wl_add(r["stock_id"], r["name"] or "", r["added_at"] or "", r["note"] or "")
            if ok:
                pushed.append(r["stock_id"])
    return {"ok": True, "pushed": pushed, "total_local": len(all_local), "already_in_sb": len(sb_ids)}

@app.get("/api/watchlist/debug")
def api_watchlist_debug():
    """診斷：列出本地 SQLite 全部觀察清單 + Supabase 清單 + price_daily 有快取的股票"""
    conn = get_conn()
    local_rows = conn.execute("SELECT stock_id, name, added_at, note FROM watchlist ORDER BY added_at").fetchall()
    # price_daily 裡有快取的股票（可能曾被觀察）
    cached_stocks = conn.execute(
        "SELECT stock_id, COUNT(*) as days, MAX(date) as last_date FROM price_daily GROUP BY stock_id ORDER BY last_date DESC"
    ).fetchall()
    conn.close()
    sb_rows = sb.wl_list() or []
    return {
        "local_sqlite": [dict(r) for r in local_rows],
        "supabase": sb_rows,
        "price_daily_cached": [dict(r) for r in cached_stocks[:50]],
    }

@app.get("/api/server/time")
def api_server_time():
    """回傳伺服器當前時間（UTC 與台灣時間）"""
    from datetime import datetime, timezone, timedelta
    tw_tz = timezone(timedelta(hours=8))
    now_utc = datetime.now(timezone.utc)
    now_tw = datetime.now(tw_tz)
    return {
        "utc": now_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "taiwan": now_tw.strftime("%Y-%m-%d %H:%M:%S"),
        "is_trading_hours": _is_tw_trading_hours(),
    }

@app.get("/api/indices")
async def api_indices():
    """市場指數列：加權指數、上櫃指數、台指近、金融近、電子近"""
    result = {
        "taiex": {"name": "加權指數", "price": None, "change_pct": None},
        "otc":   {"name": "上櫃指數",  "price": None, "change_pct": None},
        "tx":    {"name": "台指近",    "price": None, "change_pct": None},
        "tf":    {"name": "金融近",    "price": None, "change_pct": None},
        "te":    {"name": "電子近",    "price": None, "change_pct": None},
    }
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    # ── 1. TWSE MIS 加權 + 上櫃 ──
    MIS_BASE = "https://mis.twse.com.tw"
    try:
        async with httpx.AsyncClient(
            timeout=12, follow_redirects=True, verify=False,
            headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9"},
        ) as client:
            try:
                await client.get(f"{MIS_BASE}/stock/index.jsp", timeout=8)
            except Exception:
                pass
            r = await client.get(
                f"{MIS_BASE}/stock/api/getStockInfo.jsp",
                headers={
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Referer": f"{MIS_BASE}/stock/index.jsp",
                    "X-Requested-With": "XMLHttpRequest",
                },
                params={
                    "ex_ch": "tse_t00.tw|otc_o00.tw",
                    "json": "1", "delay": "0",
                    "_": str(int(_time.time() * 1000)),
                },
            )
            for item in r.json().get("msgArray", []):
                code = item.get("c", "")
                z = _sf_price(item.get("z"))
                y = _sf_price(item.get("y"))
                if y and y > 0:
                    price = z if z else y
                    pct = round((z - y) / y * 100, 2) if z else None
                    key = "taiex" if code == "t00" else ("otc" if code == "o00" else None)
                    if key:
                        result[key].update({"price": round(price, 2), "change_pct": pct})
    except Exception as e:
        print(f"[indices] TWSE MIS 失敗: {e}")

    # ── 2. TAIFEX MIS 台指近 / 金融近 / 電子近 ──
    try:
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=True,
            headers={
                "User-Agent": UA,
                "Referer": "https://mis.taifex.com.tw/",
                "Accept": "application/json, */*",
            },
        ) as client:
            quotes = []
            for market_type in ["0", "1"]:   # 0=日盤, 1=夜盤
                try:
                    r = await client.get(
                        "https://mis.taifex.com.tw/futures/api/getQuoteList",
                        params={"MarketType": market_type},
                    )
                    if r.status_code == 200:
                        ql = r.json().get("RtData", {}).get("QuoteList", [])
                        if ql:
                            quotes = ql
                            break
                except Exception:
                    pass

            # 找各商品的近月合約（最早到期 = CID 字典序最小）
            _near: dict[str, dict] = {}
            for q in quotes:
                cid = q.get("CID", "")
                for prod, key in [("TX", "tx"), ("TF", "tf"), ("TE", "te")]:
                    if cid.startswith(prod) and len(cid) > len(prod):
                        rest = cid[len(prod):]
                        # skip 選擇權 (O...) and 永續 (AM...)
                        if rest.startswith("O") or rest.startswith("AM"):
                            continue
                        if key not in _near or cid < _near[key].get("CID", "zzzz"):
                            _near[key] = q
                        break
            for key, q in _near.items():
                try:
                    # 優先取成交價, 依序 fallback 到 SettlementPrice / ReferencePrice (昨結)
                    price_s = (q.get("LastPrice") or q.get("MatchPrice") or
                               q.get("ClosingPrice") or q.get("SettlementPrice") or "")
                    price_s = price_s.strip() if isinstance(price_s, str) else ""
                    ref_s   = (q.get("ReferencePrice") or "").strip()
                    price = float(price_s.replace(",", "")) if price_s and price_s != "-" else None
                    ref   = float(ref_s.replace(",", ""))   if ref_s   and ref_s   != "-" else None
                    if price and ref and ref > 0:
                        pct = round((price - ref) / ref * 100, 2)
                        result[key].update({"price": price, "change_pct": pct})
                    elif price:
                        result[key].update({"price": price, "change_pct": None})
                except Exception:
                    pass
    except Exception as e:
        print(f"[indices] TAIFEX MIS 失敗: {e}")

    # 若 TAIFEX MIS 失敗，TX 用 ^TWII 近似值補充
    try:
        if result["tx"]["price"] is None:
            async with httpx.AsyncClient(timeout=8, verify=False, follow_redirects=True,
                headers={"User-Agent": UA, "Accept": "application/json"}) as yc:
                yr = await yc.get(
                    "https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII",
                    params={"interval": "1d", "range": "5d"},
                )
                if yr.status_code == 200:
                    res = (yr.json().get("chart", {}).get("result") or [])
                    if res:
                        closes = res[0]["indicators"]["quote"][0].get("close", [])
                        closes = [c for c in closes if c]
                        if len(closes) >= 2:
                            price = round(float(closes[-1]), 2)
                            prev  = round(float(closes[-2]), 2)
                            pct   = round((price - prev) / prev * 100, 2) if prev else None
                            result["tx"].update({"price": price, "change_pct": pct, "name": "台指近(近似)"})
    except Exception:
        pass

    # ── 3. FinMind 備援：TF/TE 最近日收盤 ──
    import datetime as _dt_idx
    _FM_TOKEN_IDX = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiYnVidXN0IiwiZW1haWwiOiJidWJ1c3RAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.LcLL157_bH6YbABE7JOlg0cAEwwzOV6GfJA6uK2cvIA"
    missing_fut = [k for k in ("tf", "te") if result[k]["price"] is None]
    if missing_fut:
        start_fm = (_dt_idx.datetime.now(_dt_idx.timezone(_dt_idx.timedelta(hours=8))).date() - _dt_idx.timedelta(days=10)).strftime("%Y-%m-%d")
        prod_map = {"tf": "TF", "te": "TE"}
        try:
            async with httpx.AsyncClient(timeout=12, verify=False, follow_redirects=True) as fm_c:
                for key in missing_fut:
                    try:
                        fm_r = await fm_c.get(
                            "https://api.finmindtrade.com/api/v4/data",
                            params={"dataset": "TaiwanFuturesDaily",
                                    "data_id": prod_map[key],
                                    "start_date": start_fm,
                                    "token": _FM_TOKEN_IDX},
                        )
                        if fm_r.status_code == 429:
                            print(f"[indices] FinMind rate-limit for {key}")
                            continue
                        rows = fm_r.json().get("data", [])
                        if not rows:
                            continue
                        # 取最新日期的近月合約 (contract_date 最小即近月)
                        latest_date = max(r.get("date", "") for r in rows)
                        today_rows = [r for r in rows if r.get("date") == latest_date]
                        today_rows.sort(key=lambda r: r.get("contract_date", ""))
                        near = today_rows[0] if today_rows else rows[-1]
                        # 優先 close，備援 settlement_price
                        raw_price = near.get("close") or near.get("settlement_price")
                        try:
                            price = float(str(raw_price).replace(",", "")) if raw_price else None
                        except (ValueError, TypeError):
                            price = None
                        if not price:
                            continue
                        # 昨收：同合約前一日
                        cdate = near.get("contract_date")
                        prev_rows = [r for r in rows
                                     if r.get("contract_date") == cdate
                                     and r.get("date", "") < latest_date]
                        raw_prev = None
                        if prev_rows:
                            raw_prev = prev_rows[-1].get("close") or prev_rows[-1].get("settlement_price")
                        try:
                            prev_c = float(str(raw_prev).replace(",", "")) if raw_prev else None
                        except (ValueError, TypeError):
                            prev_c = None
                        pct = round((price - prev_c) / prev_c * 100, 2) if prev_c and prev_c > 0 else None
                        result[key].update({"price": price, "change_pct": pct})
                    except Exception as _fe:
                        print(f"[indices] FinMind {key} 備援失敗: {_fe}")
        except Exception as _e:
            print(f"[indices] FinMind 備援區塊失敗: {_e}")

    # ── 4. Yahoo Finance 備援：OTC 上櫃指數（多 ticker 輪試）──
    _OTC_TICKERS = ["%5ETWOII", "%5ETWOTC"]  # ^TWOII = 上柜 TPEx；^TWOTC 備援
    try:
        if result["otc"]["price"] is None:
            async with httpx.AsyncClient(timeout=10, verify=False, follow_redirects=True,
                headers={"User-Agent": UA, "Accept": "application/json"}) as yc_otc:
                for _ticker in _OTC_TICKERS:
                    try:
                        yr_otc = await yc_otc.get(
                            f"https://query1.finance.yahoo.com/v8/finance/chart/{_ticker}",
                            params={"interval": "1d", "range": "5d"},
                        )
                        if yr_otc.status_code != 200:
                            continue
                        res_otc = (yr_otc.json().get("chart", {}).get("result") or [])
                        if not res_otc:
                            continue
                        closes_otc = res_otc[0]["indicators"]["quote"][0].get("close", [])
                        closes_otc = [c for c in closes_otc if c]
                        if len(closes_otc) >= 2:
                            price_otc = round(float(closes_otc[-1]), 2)
                            prev_otc  = round(float(closes_otc[-2]), 2)
                            pct_otc   = round((price_otc - prev_otc) / prev_otc * 100, 2) if prev_otc else None
                            result["otc"].update({"price": price_otc, "change_pct": pct_otc, "name": "上櫃指數(延遲)"})
                            break  # 成功拿到，停止輪試
                    except Exception:
                        continue
    except Exception:
        pass

    return result


@app.get("/api/watchlist/prices")
async def api_watchlist_prices():
    """
    輕量端點，供自動刷新用。
    盤中（09:00~13:35）→ TWSE MIS 即時報價
    盤後 / 假日       → Yahoo Finance 收盤價
    """
    from yahoo_price import get_stock_list, fetch_prices_for_stocks
    conn = get_conn()
    rows = conn.execute("SELECT stock_id FROM watchlist").fetchall()
    conn.close()
    if not rows:
        return {}
    stocks_df = get_stock_list()
    mkt_map = dict(zip(stocks_df["stock_id"], stocks_df["type"]))
    stock_ids = [r["stock_id"] for r in rows]

    if _is_tw_trading_hours():
        mis_result = await _fetch_mis_prices(stock_ids, mkt_map)
        # MIS 抓不到 z（低量股 / 上櫃不穩定）→ Yahoo 補最後成交價（15分鐘延遲但是今天的價）
        missing = [sid for sid in stock_ids if mis_result.get(sid, {}).get("change_pct") is None]
        if missing:
            stock_list = [(sid, mkt_map.get(sid, "twse")) for sid in missing]
            yahoo_result = await fetch_prices_for_stocks(stock_list)
            mis_result.update(yahoo_result)
        return mis_result
    else:
        # 盤後：Yahoo → MIS 昨收 → FinMind 三層兜底
        stock_list = [(sid, mkt_map.get(sid, "twse")) for sid in stock_ids]
        yahoo_result = await fetch_prices_for_stocks(stock_list)
        missing_after = [sid for sid in stock_ids if sid not in yahoo_result]
        if missing_after:
            mis_fallback = await _fetch_mis_prices(missing_after, mkt_map)
            for sid, info in mis_fallback.items():
                if sid not in yahoo_result:
                    yahoo_result[sid] = info
        still_missing = [sid for sid in stock_ids if sid not in yahoo_result]
        if still_missing:
            fm_fallback = await _fetch_finmind_prices(still_missing)
            yahoo_result.update(fm_fallback)
        return yahoo_result

async def _deep_chip(stock_id: str) -> dict | None:
    """籌碼：FinMind TaiwanStockInstitutionalInvestorsBuySell 近10日三大法人買賣超"""
    from datetime import date, timedelta
    start = (date.today() - timedelta(days=20)).strftime("%Y-%m-%d")
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "data_id": stock_id,
        "start_date": start,
        "token": _FINMIND_TOKEN,
    }
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(url, params=params)
            data = r.json().get("data", [])
        if not data:
            return None
        # 每日每機構一筆：name in [外資及陸資, 投信, 自營商]
        from collections import defaultdict
        buckets: dict[str, list] = defaultdict(list)
        for row in data[-60:]:  # 最多取近 60 筆（約 20 天 × 3 機構）
            net = int(str(row.get("buy", 0)).replace(",", "") or 0) - \
                  int(str(row.get("sell", 0)).replace(",", "") or 0)
            name = row.get("name", "")
            if "外資" in name:
                buckets["foreign"].append(net)
            elif "投信" in name:
                buckets["trust"].append(net)
            elif "自營" in name:
                buckets["dealer"].append(net)

        def _agg(lst: list) -> dict:
            net10 = sum(lst[-10:]) if lst else 0
            days_buy = sum(1 for x in lst[-10:] if x > 0)
            days_sell = sum(1 for x in lst[-10:] if x < 0)
            return {"net_10d": net10, "days_buy": days_buy, "days_sell": days_sell}

        foreign = _agg(buckets["foreign"])
        trust   = _agg(buckets["trust"])
        dealer  = _agg(buckets["dealer"])
        total   = foreign["net_10d"] + trust["net_10d"] + dealer["net_10d"]

        if total > 3000:
            sig = "三大法人強力買超"
        elif foreign["net_10d"] > 2000:
            sig = "外資連買"
        elif total < -3000:
            sig = "三大法人賣超"
        else:
            sig = "中性"

        return {"foreign": foreign, "trust": trust, "dealer": dealer,
                "total_net_10d": total, "signal": sig}
    except Exception as e:
        log.warning(f"[deep_chip] {stock_id}: {e}")
        return None


async def _deep_fundamental(stock_id: str) -> dict | None:
    """基本面：FinMind TaiwanStockPER — PE/PB/殖利率"""
    from datetime import date, timedelta
    start = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockPER",
        "data_id": stock_id,
        "start_date": start,
        "token": _FINMIND_TOKEN,
    }
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(url, params=params)
            data = r.json().get("data", [])
        if not data:
            return None
        row = data[-1]
        per = row.get("PER") or row.get("per")
        pbr = row.get("PBR") or row.get("pbr")
        dy  = row.get("DividendYield") or row.get("dividend_yield")
        try:
            per = float(per) if per not in (None, "", "—") else None
            pbr = float(pbr) if pbr not in (None, "", "—") else None
            dy  = float(dy)  if dy  not in (None, "", "—") else None
        except Exception:
            per = pbr = dy = None

        if per is None:
            sig = "無資料"
        elif per < 10:
            sig = "低估"
        elif per < 20:
            sig = "合理"
        elif per < 30:
            sig = "偏高"
        else:
            sig = "高估"

        return {
            "date": row.get("date", ""),
            "per": round(per, 2) if per is not None else None,
            "pbr": round(pbr, 2) if pbr is not None else None,
            "dividend_yield": round(dy, 2) if dy is not None else None,
            "signal": sig,
        }
    except Exception as e:
        log.warning(f"[deep_fund] {stock_id}: {e}")
        return None


async def _deep_financial(stock_id: str) -> dict | None:
    """財務：FinMind TaiwanFinancialStatements — EPS/營收/毛利率"""
    from datetime import date, timedelta
    start = (date.today() - timedelta(days=500)).strftime("%Y-%m-%d")
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanFinancialStatements",
        "data_id": stock_id,
        "start_date": start,
        "token": _FINMIND_TOKEN,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url, params=params)
            data = r.json().get("data", [])
        if not data:
            return None

        # 按 (date, type) 樞紐：取 EPS, Revenue, GrossProfit
        from collections import defaultdict
        pivot: dict[str, dict] = defaultdict(dict)
        for row in data:
            dt = row.get("date", "")[:7]  # YYYY-MM
            tp = row.get("type", "")
            try:
                val = float(str(row.get("value", 0)).replace(",", "") or 0)
            except Exception:
                val = 0.0
            if "EPS" in tp:
                pivot[dt]["eps"] = val
            elif "Revenue" in tp or "營業收入" in tp:
                pivot[dt]["revenue"] = val
            elif "GrossProfit" in tp or "毛利" in tp:
                pivot[dt]["gross_profit"] = val

        quarters = sorted(pivot.keys())
        if not quarters:
            return None

        latest_q = quarters[-1]
        latest   = pivot[latest_q]
        eps_latest = latest.get("eps")
        rev_latest = latest.get("revenue")
        gp_latest  = latest.get("gross_profit")

        # YoY：比 4 季前
        yoy_q = quarters[-5] if len(quarters) >= 5 else None
        eps_yoy = rev_yoy = None
        if yoy_q:
            eps_prev = pivot[yoy_q].get("eps")
            rev_prev = pivot[yoy_q].get("revenue")
            if eps_prev and eps_prev != 0:
                eps_yoy = round((eps_latest - eps_prev) / abs(eps_prev) * 100, 1)
            if rev_prev and rev_prev != 0:
                rev_yoy = round((rev_latest - rev_prev) / abs(rev_prev) * 100, 1) if rev_latest else None

        gross_margin = None
        if gp_latest and rev_latest and rev_latest != 0:
            gross_margin = round(gp_latest / rev_latest * 100, 1)

        if eps_yoy is None:
            sig = "無資料"
        elif eps_yoy > 20:
            sig = "高成長"
        elif eps_yoy > 0:
            sig = "成長"
        else:
            sig = "衰退"

        return {
            "latest": {
                "date": latest_q,
                "eps": eps_latest,
                "revenue": int(rev_latest) if rev_latest else None,
                "gross_margin": gross_margin,
            },
            "eps_growth_yoy": eps_yoy,
            "revenue_growth_yoy": rev_yoy,
            "signal": sig,
        }
    except Exception as e:
        log.warning(f"[deep_fin] {stock_id}: {e}")
        return None


async def _deep_news(stock_id: str) -> dict:
    """新聞：Yahoo Finance search API"""
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/search"
        params = {"q": f"{stock_id}.TW", "newsCount": "5", "enableFuzzyQuery": "false"}
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "Mozilla/5.0"}) as c:
            r = await c.get(url, params=params)
            items_raw = r.json().get("news", [])
        items = []
        for n in items_raw[:5]:
            ts = n.get("providerPublishTime")
            from datetime import datetime, timezone
            dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts else ""
            items.append({
                "title": n.get("title", ""),
                "publisher": n.get("publisher", ""),
                "link": n.get("link", ""),
                "date": dt_str,
            })
        return {"items": items}
    except Exception as e:
        log.warning(f"[deep_news] {stock_id}: {e}")
        return {"items": []}


@app.get("/api/stock/{stock_id}/deep-analysis")
async def api_stock_deep_analysis(stock_id: str):
    """
    股票深度分析：技術 + 籌碼 + 基本面 + 財務 + 新聞 + 產業
    資料來源：price_daily / FinMind / Yahoo Finance
    """
    try:
        data = await _api_stock_deep_analysis_impl(stock_id)
        # JSONResponse 明確序列化，先 sanitize 確保無 NaN/Inf（FastAPI 序列化失敗不在 try 範圍內）
        return JSONResponse(content=_sanitize_for_json(data))
    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"[deep-analysis] {stock_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _api_stock_deep_analysis_impl(stock_id: str):
    import math
    import pandas as pd
    from scanner import (
        calc_macd, calc_ma, calc_bb_score, classify_stage, _change_pct
    )
    from chip_tracker_v2 import DB_PATH
    from yahoo_price import get_stock_list

    # ── 1. 取股票名稱 ──
    try:
        stocks_df = get_stock_list()
        name_map = dict(zip(stocks_df["stock_id"], stocks_df["stock_name"]))
        mkt_map  = dict(zip(stocks_df["stock_id"], stocks_df["type"]))
    except Exception:
        name_map = {}
        mkt_map  = {}

    stock_name = name_map.get(stock_id, stock_id)

    # ── 2. 讀取 price_daily（至少 150 天供 50MA + 大MACD 計算）──
    df = None
    try:
        cache_conn = sqlite3.connect(str(DB_PATH))
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM price_daily WHERE stock_id=? ORDER BY date",
            cache_conn, params=(stock_id,)
        )
        cache_conn.close()
    except Exception:
        pass

    # 不足 100 天 → 補抓 Yahoo
    if df is None or len(df) < 100:
        try:
            from yahoo_price import _fetch_yahoo_async
            import asyncio
            mkt = mkt_map.get(stock_id, "twse")
            new_df = await _fetch_yahoo_async(stock_id, mkt)
            if new_df is not None and len(new_df) > (len(df) if df is not None else 0):
                df = new_df
        except Exception:
            pass

    if df is None or len(df) < 20:
        raise HTTPException(status_code=404, detail=f"找不到 {stock_id} 的足夠價格資料")

    # 確保欄位名稱一致（小寫）
    df.columns = [c.lower() for c in df.columns]
    df = df.reset_index(drop=True)

    closes  = df['close'].astype(float)
    volumes = df['volume'].astype(float)
    today   = df.iloc[-1]

    # ── 3. 技術指標 ──
    # MACD
    dif1, dea1, osc1 = calc_macd(closes, 12, 26, 9)
    dif_v, dea_v, osc_v = float(dif1.iloc[-1]), float(dea1.iloc[-1]), float(osc1.iloc[-1])
    dif2, dea2, osc2 = (None, None, None)
    macd_big = None
    if len(df) >= 235:
        dif2, dea2, osc2 = calc_macd(closes, 108, 216, 18)
        macd_big = {
            "dif": round(float(dif2.iloc[-1]), 4),
            "dea": round(float(dea2.iloc[-1]), 4),
            "osc": round(float(osc2.iloc[-1]), 4),
        }

    # MACD 訊號判讀
    macd_signal = "多" if dif_v > 0 and dea_v > 0 and osc_v > 0 else \
                  "偏多" if dif_v > 0 and dea_v > 0 else \
                  "空" if dif_v < 0 and dea_v < 0 and osc_v < 0 else \
                  "偏空" if dif_v < 0 and dea_v < 0 else "震盪"

    # MA
    ma10 = float(closes.rolling(10, min_periods=10).mean().iloc[-1]) if len(df) >= 10 else None
    ma20 = float(closes.rolling(20, min_periods=20).mean().iloc[-1]) if len(df) >= 20 else None
    ma60 = float(closes.rolling(60, min_periods=60).mean().iloc[-1]) if len(df) >= 60 else None
    tc   = float(today['close'])

    # 均線黃金交叉（MA10 近10天由下穿 MA60）
    golden_cross_days = None
    if ma10 and ma60 and len(df) >= 70:
        ma10_s = closes.rolling(10, min_periods=10).mean()
        ma60_s = closes.rolling(60, min_periods=60).mean()
        for lag in range(1, 11):
            i = -(lag + 1)
            if abs(i) <= len(df) and not pd.isna(ma10_s.iloc[i]) and not pd.isna(ma60_s.iloc[i]):
                if float(ma10_s.iloc[i]) < float(ma60_s.iloc[i]):
                    golden_cross_days = lag
                    break

    # BB 位置
    bb_score = calc_bb_score(df)

    # 量能
    try:
        vol_today = float(volumes.iloc[-1]) if len(volumes) > 0 else 0.0
    except (TypeError, ValueError):
        vol_today = 0.0
    vol_prev   = float(volumes.iloc[-2]) if len(volumes) > 1 else 0
    vol_5d_avg = float(volumes.iloc[-5:].mean()) if len(volumes) >= 5 else vol_today
    vol_ratio  = round(vol_today / vol_prev, 2) if vol_prev > 0 else None
    vol_vs_avg = round(vol_today / vol_5d_avg, 2) if vol_5d_avg > 0 else None

    # 漲跌幅
    change_pct = _change_pct(df)

    # ── 4. 操作階段 ──
    stage = classify_stage(df)

    # ── 5. 族群資訊（sector DB）──
    sector_info = None
    try:
        from sector.db import db as sector_db
        with sector_db() as sconn:
            map_row = sconn.execute(
                "SELECT sector_id FROM stock_sector_map WHERE stock_id=? LIMIT 1",
                (stock_id,)
            ).fetchone()
            if map_row:
                sid = map_row["sector_id"]
                s_row = sconn.execute(
                    "SELECT sector_name FROM sector_master WHERE sector_id=?", (sid,)
                ).fetchone()
                latest_date = sconn.execute(
                    "SELECT MAX(observation_date) AS d FROM sector_daily"
                ).fetchone()
                ld = latest_date["d"] if latest_date else None
                rank_row = sconn.execute(
                    "SELECT relative_rank_5d, relative_rank_20d FROM sector_daily WHERE sector_id=? AND observation_date=?",
                    (sid, ld)
                ).fetchone() if ld else None
                total_sectors = sconn.execute("SELECT COUNT(*) AS n FROM sector_master").fetchone()["n"]
                sector_info = {
                    "sector_id":   sid,
                    "sector_name": s_row["sector_name"] if s_row else sid,
                    "rank5d":      rank_row["relative_rank_5d"]  if rank_row else None,
                    "rank20d":     rank_row["relative_rank_20d"] if rank_row else None,
                    "total":       total_sectors,
                }
    except Exception:
        pass

    # ── 6. 綜合評分（0~100）──
    signals = []
    tech_score = 50  # 基礎分

    # MACD 加減分
    if dif_v > 0 and dea_v > 0:
        tech_score += 10; signals.append("MACD 多頭")
    elif dif_v < 0 and dea_v < 0:
        tech_score -= 10; signals.append("MACD 空頭")

    if osc_v > 0:
        tech_score += 5; signals.append("OSC 翻正")
    elif osc_v < 0 and osc_v > float(osc1.iloc[-2]) if len(osc1) > 1 else False:
        tech_score += 3; signals.append("OSC 縮短")

    # 均線加減分
    if ma10 and tc > ma10:
        tech_score += 5; signals.append(f"站上MA10({ma10:.0f})")
    if ma60 and tc > ma60:
        tech_score += 10; signals.append(f"站上MA60({ma60:.0f})")
    elif ma60 and tc < ma60:
        tech_score -= 10; signals.append(f"跌破MA60({ma60:.0f})")

    if golden_cross_days is not None:
        tech_score += 8; signals.append(f"{golden_cross_days}天前黃金交叉")

    # BB 加減分
    if bb_score is not None:
        if bb_score >= 5:
            tech_score += 5; signals.append("BB 上軌區")
        elif bb_score <= -5:
            tech_score -= 5; signals.append("BB 下軌區")

    # 量能加分
    if vol_ratio is not None and vol_ratio >= 2:
        tech_score += 5; signals.append(f"量能翻倍 ×{vol_ratio}")

    # Stage 加減分
    stage_bonus = {"pullback": 8, "fbd": 10, "golden": 5, "consol": 0, "attack": -5, "bull": 3, "bearish": -15}
    tech_score += stage_bonus.get(stage.get("code", ""), 0)

    overall = max(0, min(100, tech_score))

    # ── 7. 並發抓取：籌碼 / 基本面 / 財務 / 新聞 ──
    _gather_results = await asyncio.gather(
        _deep_chip(stock_id),
        _deep_fundamental(stock_id),
        _deep_financial(stock_id),
        _deep_news(stock_id),
        return_exceptions=True,
    )
    chip_data  = None if isinstance(_gather_results[0], Exception) else _gather_results[0]
    fund_data  = None if isinstance(_gather_results[1], Exception) else _gather_results[1]
    fin_data   = None if isinstance(_gather_results[2], Exception) else _gather_results[2]
    news_data  = {"items": []} if isinstance(_gather_results[3], Exception) else _gather_results[3]

    # ── 8. 產業信號補充 ──
    if sector_info:
        r5 = sector_info.get("rank5d")
        if r5 is not None:
            if r5 <= 5:
                sector_info["signal"] = "族群強勢（前5）"
            elif r5 <= 15:
                sector_info["signal"] = "中等偏強"
            else:
                sector_info["signal"] = "偏弱"

    # macd_big: sanitize NaN/Inf
    if macd_big:
        macd_big = {k: _safe_num(v) for k, v in macd_big.items()}

    return {
        "stock_id": stock_id,
        "name":     stock_name,
        "technical": {
            "close":      _safe_num(tc),
            "change_pct": _safe_num(change_pct),
            "volume":     int(vol_today) if math.isfinite(vol_today) else 0,
            "vol_ratio":  _safe_num(vol_ratio),
            "vol_vs_5d":  _safe_num(vol_vs_avg),
            "bb_score":   _safe_num(bb_score),
            "stage":      stage,
            "macd": {
                "dif": _safe_num(dif_v), "dea": _safe_num(dea_v), "osc": _safe_num(osc_v),
                "signal": macd_signal,
            },
            "macd_big": macd_big,
            "ma": {
                "ma10": _safe_num(ma10),
                "ma20": _safe_num(ma20),
                "ma60": _safe_num(ma60),
                "above_ma10":        ma10 is not None and math.isfinite(ma10) and tc > ma10,
                "above_ma60":        ma60 is not None and math.isfinite(ma60) and tc > ma60,
                "golden_cross_days": golden_cross_days,
            },
            "score": {"overall": overall, "signals": signals},
            "data_days": len(df),
        },
        "chip":        chip_data,
        "fundamental": fund_data,
        "financial":   fin_data,
        "news":        news_data,
        "sector":      sector_info,
    }


@app.get("/api/watchlist/summary")
async def api_watchlist_summary():
    from yahoo_price import get_stock_list

    # 雙向同步：Supabase ↔ 本地 SQLite（持久磁碟）
    # 方向一：Supabase → 本地（已有才同步；Supabase 有但本地沒有 → INSERT）
    sb_rows = sb.wl_list()
    sb_ids = set()
    if sb_rows is not None:
        sb_ids = {r["stock_id"] for r in sb_rows}
        if sb_rows:
            conn = get_conn()
            local_ids = {r["stock_id"] for r in conn.execute("SELECT stock_id FROM watchlist").fetchall()}
            for r in sb_rows:
                if r["stock_id"] not in local_ids:
                    conn.execute(
                        "INSERT OR IGNORE INTO watchlist (stock_id, name, added_at, note) VALUES (?,?,?,?)",
                        (r["stock_id"], r.get("name", ""), r.get("added_at", ""), r.get("note", ""))
                    )
            conn.commit()
            conn.close()
    # 方向二：本地 → Supabase（持久磁碟有但 Supabase 沒有 → 補上去）
    if sb._enabled():
        try:
            conn = get_conn()
            all_local = conn.execute("SELECT stock_id, name, added_at, note FROM watchlist").fetchall()
            conn.close()
            for r in all_local:
                if r["stock_id"] not in sb_ids:
                    sb.wl_add(r["stock_id"], r["name"] or "", r["added_at"] or "", r["note"] or "")
        except Exception:
            pass

    # stocks.csv → 備用股名 + 市場類型（OTC 補查 MIS 用）
    stocks_df  = get_stock_list()
    csv_names  = dict(zip(stocks_df["stock_id"], stocks_df["stock_name"]))
    mkt_map    = dict(zip(stocks_df["stock_id"], stocks_df["type"]))

    conn = get_conn()
    rows = conn.execute("SELECT stock_id, name, note, memo FROM watchlist ORDER BY added_at").fetchall()
    conn.close()

    stock_ids = [r["stock_id"] for r in rows]

    # 補空白名稱：DB 有就用 DB，否則從 stocks.csv 補
    names: dict[str, str] = {}
    to_update: list[tuple[str, str]] = []
    for r in rows:
        sid   = r["stock_id"]
        db_n  = (r["name"] or "").strip()
        csv_n = csv_names.get(sid, "")
        resolved = db_n or csv_n
        names[sid] = resolved
        if not db_n and csv_n:
            to_update.append((csv_n, sid))

    # 把補到的名稱同步回 DB
    if to_update:
        conn = get_conn()
        conn.executemany("UPDATE watchlist SET name=? WHERE stock_id=?", to_update)
        conn.commit()
        conn.close()

    # 現價：Yahoo → MIS 昨收 → FinMind 三層兜底
    from yahoo_price import fetch_prices_for_stocks
    stock_list = [(sid, mkt_map.get(sid, "twse")) for sid in stock_ids]
    latest_prices = await fetch_prices_for_stocks(stock_list)
    missing_price = [sid for sid in stock_ids if sid not in latest_prices]
    if missing_price:
        mis_fb = await _fetch_mis_prices(missing_price, mkt_map)
        for sid, info in mis_fb.items():
            if sid not in latest_prices:
                latest_prices[sid] = info
    still_miss = [sid for sid in stock_ids if sid not in latest_prices]
    if still_miss:
        fm_fb = await _fetch_finmind_prices(still_miss)
        latest_prices.update(fm_fb)

    result = []
    for r in rows:
        sid  = r["stock_id"]
        name = names.get(sid, "")
        records = load_stock_history(sid)
        price_info = latest_prices.get(sid, {})
        item: dict = {
            "stock_id":   sid,
            "name":       name,
            "note":       (r["note"] or "").strip() if "note" in r.keys() else "",
            "memo":       (r["memo"] or "").strip() if "memo" in r.keys() else "",
            "close":      price_info.get("close"),
            "change_pct": price_info.get("change_pct"),
            "bb_score":   price_info.get("bb_score"),  # None → 前端顯示 "—"（MIS/FinMind fallback 無OHLCV無法計算BB）
            "stage":      price_info.get("stage", {"code": "unknown", "label": "—", "color": "muted", "desc": "無法取得價格資料"}),
        }
        if records:
            latest = records[-1]
            last7  = records[-7:]
            cum7   = sum(r2.get("whale_flow_lots", 0) for r2 in last7)
            # 連續買超天數（從 CSV/Supabase 讀，若無則從 records 計算）
            consec_buy = int(latest.get("consecutive_buy", 0) or 0)
            # 連續賣超天數（whale < 0 的連續天數，即時計算）
            consec_sell = 0
            for r2 in reversed(records):
                if (r2.get("whale_flow_lots", 0) or 0) < 0:
                    consec_sell += 1
                else:
                    break
            item.update({
                "has_data":            True,
                "date":                latest.get("date", ""),
                "whale_flow_lots":     latest.get("whale_flow_lots", 0),
                "retail_flow_lots":    latest.get("retail_flow_lots", 0),
                "concentration_index": latest.get("concentration_index", 0),
                "cum7_whale":          cum7,
                "signal_emoji":        latest.get("signal_emoji", "⚪"),
                "signal_title":        latest.get("signal_title", "—"),
                "signal_level":        latest.get("signal_level", 0),
                "consecutive_buy":     consec_buy,
                "consecutive_sell":    consec_sell,
            })
        else:
            item["has_data"] = False
        result.append(item)

    # 注入 TDCC 千張大戶週資料（從 SQLite 快取讀取，不會發起網路請求）
    from tdcc_chip import get_tdcc_data
    tdcc_map = get_tdcc_data()
    for item in result:
        t = tdcc_map.get(item["stock_id"])
        if t:
            item["kpct"]        = t["current_pct"]
            item["kpct_prev"]   = t["prev_pct"]
            item["kpct_change"] = t["change"]
            item["kpct_date"]   = t["date"]
        else:
            item["kpct"]        = None
            item["kpct_prev"]   = None
            item["kpct_change"] = None
            item["kpct_date"]   = None
    # ── 注入策略掃描訊號：優先補充 has_data=False 及 signal_title="—" 的股票 ──
    try:
        from yahoo_price import get_scan_results
        _scan_res = get_scan_results()
        _SIG_PRIORITY = {
            "S10":          (10, "🚀", "漲停",    3),
            "CHIP":         (9,  "💎", "主力籌碼", 3),
            "S1":           (8,  "📈", "雙MACD多", 2),
            "S2":           (7,  "📈", "W底確認",  2),
            "S5":           (6,  "📈", "站上均線", 2),
            "S1_SHORT":     (5,  "📉", "雙MACD空", 2),
            "S17A":         (4,  "🔍", "底部翻試", 1),
            "S17B":         (3,  "🔍", "撈底加碼", 1),
            "S_VOLX":       (2,  "💥", "量爆拉升", 1),
            "S_VOLX_SHORT": (2,  "💥", "量爆下殺", 1),
            "S_PB":         (1,  "📊", "均線拉回", 1),
            "S_FBD":        (3,  "🔻", "假跌破",  1),
            "S_RES":        (2,  "📐", "壓力區",  1),
            "S_KD":         (2,  "📊", "KD交叉",  1),
        }
        _all_scan: dict = {}  # sid -> {strategy_key: (priority, emoji, label, level)}
        for _sk, _sresults in _scan_res.items():
            if _sk not in _SIG_PRIORITY:
                continue
            _entry = _SIG_PRIORITY[_sk]
            for _sr in (_sresults or []):
                _sid = _sr.get("stock_id", "")
                if not _sid:
                    continue
                if _sid not in _all_scan:
                    _all_scan[_sid] = {}
                _all_scan[_sid][_sk] = _entry
        for _item in result:
            _sig_map = _all_scan.get(_item["stock_id"])
            if _sig_map:
                _sigs = sorted(_sig_map.values(), key=lambda x: x[0], reverse=True)
                _existing_title = _item.get("signal_title", "—")
                if not _item.get("has_data") or _existing_title == "—":
                    _item["signal_emoji"] = _sigs[0][1]
                    _item["signal_title"] = "·".join(s[2] for s in _sigs)
                    _item["signal_level"] = _sigs[0][3]
    except Exception:
        pass

    last_refresh = settings_get("last_refresh")

    # ── 問題三：若有無籌碼資料的股票，且距上次更新超過 6 小時，自動背景更新 ──
    no_data_ids = [item["stock_id"] for item in result if not item.get("has_data")]
    if no_data_ids:
        _should_auto = False
        try:
            _last_auto = settings_get("last_auto_chip_trigger")
            if _last_auto is None:
                _should_auto = True
            else:
                _last_auto_dt = datetime.fromisoformat(_last_auto)
                _should_auto = (datetime.now() - _last_auto_dt).total_seconds() > 6 * 3600
        except Exception:
            _should_auto = True
        if _should_auto:
            import asyncio as _auto_asyncio
            import threading as _auto_threading
            settings_set("last_auto_chip_trigger", datetime.now().isoformat())
            def _auto_bg_refresh():
                try:
                    _auto_asyncio.run(update_stocks(no_data_ids, days=30))
                except Exception as _ae:
                    import logging; logging.getLogger(__name__).warning(f"[auto_chip_trigger] {_ae}")
            _auto_threading.Thread(target=_auto_bg_refresh, daemon=True).start()

    return {"items": result, "last_refresh": last_refresh}


# ════════════════════════════════════════════════════════════════════════════
# Refresh API（觀察清單個股籌碼更新）
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/refresh")
async def api_refresh(body: RefreshBody):
    sb_ids = sb.wl_get_ids()
    if sb_ids:  # 非空才採用 Supabase，空或 None 都 fallback 到 SQLite
        stock_ids = sb_ids
    else:
        conn = get_conn()
        rows = conn.execute("SELECT stock_id FROM watchlist").fetchall()
        conn.close()
        stock_ids = [r["stock_id"] for r in rows]
    if body.extra_stocks:
        for s in body.extra_stocks:
            s = s.strip()
            if s and s not in stock_ids:
                stock_ids.append(s)
    if not stock_ids:
        raise HTTPException(status_code=400, detail="觀察清單為空，請先新增股票")
    end_dt = None
    if body.date:
        try:
            end_dt = datetime.strptime(body.date, "%Y%m%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date 格式錯誤，應為 YYYYMMDD")
    days = body.backfill or 30
    results = await update_stocks(stock_ids, days=days, end_date=end_dt)
    settings_set("last_refresh", datetime.now().isoformat())
    return {"ok": True, "updated": list(results.keys()), "days": days}


# ════════════════════════════════════════════════════════════════════════════
# 全系統更新 API（一鍵更新所有引擎）
# ════════════════════════════════════════════════════════════════════════════

_refresh_all_status: dict = {
    "running": False,
    "started_at": None,
    "steps": {
        "watchlist":   {"label": "觀察清單股票",    "status": "pending"},
        "regime":      {"label": "總經 Regime 引擎", "status": "pending"},
        "tdcc":        {"label": "千張大戶 TDCC",    "status": "pending"},
        "positioning": {"label": "籌碼定位引擎",     "status": "pending"},
        "sector":      {"label": "產業輪動引擎",     "status": "pending"},
        "warrant":     {"label": "權證合約更新",     "status": "pending"},
    },
}

def _set_step(step: str, status: str):
    _refresh_all_status["steps"][step]["status"] = status

@app.get("/api/refresh_all/status")
def api_refresh_all_status():
    return _refresh_all_status

@app.post("/api/refresh_all")
async def api_refresh_all():
    """一鍵觸發所有引擎更新（背景執行），包含千張大戶、Regime、Positioning、Sector、權證"""
    import threading, asyncio as _asyncio
    from datetime import datetime as _dt

    if _refresh_all_status["running"]:
        return {"ok": False, "message": "更新已在執行中，請稍候"}

    # 重置狀態
    _refresh_all_status["running"] = True
    _refresh_all_status["started_at"] = _dt.now().isoformat()
    for k in _refresh_all_status["steps"]:
        _refresh_all_status["steps"][k]["status"] = "pending"

    def _run_all():
        import logging as _log
        lg = _log.getLogger(__name__)

        # 0. 觀察清單股票（優先更新，供後續引擎使用）
        try:
            _set_step("watchlist", "running")
            sb_ids = sb.wl_get_ids()
            if sb_ids:
                stock_ids = sb_ids
            else:
                conn = get_conn()
                rows = conn.execute("SELECT stock_id FROM watchlist").fetchall()
                conn.close()
                stock_ids = [r["stock_id"] for r in rows]
            if stock_ids:
                try:
                    _asyncio.run(update_stocks(stock_ids, days=30))
                except Exception as _we:
                    lg.warning(f"[refresh_all] watchlist update_stocks: {_we}（保留舊資料）")
            _set_step("watchlist", "done")
        except Exception as e:
            lg.error(f"[refresh_all] watchlist: {e}")
            _set_step("watchlist", "error")

        # 1. Regime（增加 breadth lookback 確保歷史夠長）
        try:
            _set_step("regime", "running")
            regime_fetch_all(days=5)
            fetch_twse_margin()
            fetch_twse_foreign_spot()
            fetch_twse_market_breadth(lookback=90)
            fetch_taifex_foreign_futures()
            fetch_mi5mins()
            regime_calc_factors()
            regime_backfill_factors(days=90)
            _set_step("regime", "done")
        except Exception as e:
            lg.error(f"[refresh_all] regime: {e}")
            _set_step("regime", "error")

        # 2. 千張大戶 TDCC
        try:
            _set_step("tdcc", "running")
            from tdcc_chip import refresh_for_stocks
            _asyncio.run(refresh_for_stocks())   # async 函數必須用 asyncio.run()
            _set_step("tdcc", "done")
        except Exception as e:
            lg.error(f"[refresh_all] tdcc: {e}")
            _set_step("tdcc", "error")

        # 3. Positioning（positioning_run_refresh 是同步函數，內部自行處理 asyncio）
        try:
            _set_step("positioning", "running")
            positioning_run_refresh()
            _set_step("positioning", "done")
        except Exception as e:
            lg.error(f"[refresh_all] positioning: {e}")
            _set_step("positioning", "error")

        # 4. Sector（先抓今日全市場價格存入DB，再執行引擎計算）
        try:
            _set_step("sector", "running")
            from sector.prices import fetch_and_store_today, backfill
            from sector.engine import run_sector_engine
            # 先確保 DB 有足夠歷史（首次補抓 120 天，之後只抓今日）
            from sector.db import db as _sdb, init_db as _sector_init_db
            _sector_init_db()
            with _sdb() as _sc:
                _cnt = _sc.execute("SELECT COUNT(DISTINCT date) FROM sector_stock_daily").fetchone()[0]
            if _cnt < 60:
                lg.info(f"[sector] sector_stock_daily 只有 {_cnt} 天，開始補抓歷史...")
                backfill(days=130)
            else:
                fetch_and_store_today()
            run_sector_engine(days_back=5)
            _set_step("sector", "done")
        except Exception as e:
            lg.error(f"[refresh_all] sector: {e}")
            _set_step("sector", "error")

        # 5. 權證合約更新
        try:
            _set_step("warrant", "running")
            from warrant.ingester import ingest_contracts
            ingest_contracts()
            _set_step("warrant", "done")
        except Exception as e:
            lg.error(f"[refresh_all] warrant: {e}")
            _set_step("warrant", "error")

        _refresh_all_status["running"] = False

    threading.Thread(target=_run_all, daemon=True).start()
    return {"ok": True, "message": "全系統更新已啟動（背景執行）"}


# ════════════════════════════════════════════════════════════════════════════
# 全市場大戶排行 API（TWSE T86 + STOCK_DAY_ALL，單日一次拿全部）
# ════════════════════════════════════════════════════════════════════════════

_UA_TWSE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

@app.get("/api/market/scan")
async def api_market_scan(top: int = 50):
    """全市場今日法人買賣超排行（TWSE 上市，T86 三大法人 + STOCK_DAY_ALL 股價）"""
    from datetime import date, timedelta
    from chip_tracker_v2 import is_trading_day

    timeout_cfg = httpx.Timeout(20.0, connect=8.0)

    # 股價清單（只抓一次）
    price_map: dict = {}
    chip_map: dict = {}
    used_date_str: str = ""

    async with httpx.AsyncClient(
        headers={"User-Agent": _UA_TWSE, "Referer": "https://www.twse.com.tw/"},
        timeout=timeout_cfg,
        verify=False,
        follow_redirects=True,
    ) as client:
        # 先抓股價（與日期無關，單次即可）
        try:
            price_r = await client.get(
                "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
            )
            if price_r.status_code == 200:
                for item in price_r.json():
                    sid = str(item.get("Code", "")).strip()
                    if not sid:
                        continue
                    try:
                        close_s = str(item.get("ClosingPrice", "0")).replace(",", "")
                        price_map[sid] = {
                            "name":  item.get("Name", ""),
                            "close": float(close_s) if close_s not in ("", "--", "-") else None,
                        }
                    except Exception:
                        pass
        except Exception:
            pass

        # T86 嘗試最近 5 個交易日（今日優先，若未公布則往前找）
        attempt_dt = datetime.now(timezone(timedelta(hours=8))).date()
        for _ in range(5):
            if not is_trading_day(attempt_dt):
                attempt_dt -= timedelta(days=1)
                continue
            dt_str = attempt_dt.strftime("%Y%m%d")
            try:
                t86_r = await client.get(
                    "https://www.twse.com.tw/rwd/zh/fund/T86",
                    params={"date": dt_str, "selectType": "ALL", "response": "json"},
                )
                if t86_r.status_code == 200:
                    t86 = t86_r.json()
                    if t86.get("stat") == "OK" and t86.get("data"):
                        used_date_str = dt_str
                        for row in t86.get("data", []):
                            try:
                                sid = str(row[0]).strip()

                                def _f(v):
                                    return float(str(v).replace(",", "")) / 1000  # 股 → 張

                                foreign = _f(row[4])
                                trust   = _f(row[10])
                                dealer  = _f(row[14])
                                whale   = foreign * 1.0 + trust * 0.95 + dealer * 0.70
                                chip_map[sid] = {
                                    "foreign_lots":    round(foreign),
                                    "trust_lots":      round(trust),
                                    "dealer_lots":     round(dealer),
                                    "whale_flow_lots": round(whale),
                                }
                            except Exception:
                                pass
                        break  # 成功取得資料，停止重試
            except Exception:
                pass
            attempt_dt -= timedelta(days=1)

    if not chip_map:
        raise HTTPException(status_code=503, detail="無法取得 T86 法人資料（TWSE 尚未公布或 IP 封鎖），請稍後再試")

    # 合併結果
    from yahoo_price import get_stock_list
    stocks_df = get_stock_list()
    csv_names = dict(zip(stocks_df["stock_id"], stocks_df["stock_name"]))

    merged = []
    for sid, chip in chip_map.items():
        price_info = price_map.get(sid, {})
        name = price_info.get("name") or csv_names.get(sid, "")
        merged.append({
            "stock_id":        sid,
            "name":            name,
            "close":           price_info.get("close"),
            "foreign_lots":    chip["foreign_lots"],
            "trust_lots":      chip["trust_lots"],
            "dealer_lots":     chip["dealer_lots"],
            "whale_flow_lots": chip["whale_flow_lots"],
            "retail_flow_lots": 0,
            "signal_emoji":    "⚪",
            "signal_title":    "—",
            "signal_level":    0,
        })

    merged.sort(key=lambda x: x["whale_flow_lots"], reverse=True)

    # 從策略掃描快取補充 signal 資訊（顯示所有命中策略）
    all_sig: dict = {}  # sid -> {strategy_key: (priority, emoji, label, level)}
    try:
        from yahoo_price import get_scan_results
        scan_res = get_scan_results()
        _SIG_MAP = {
            "S10":          (10, "🚀", "漲停",    3),
            "CHIP":         (9,  "💎", "主力籌碼", 3),
            "S1":           (8,  "📈", "雙MACD多", 2),
            "S2":           (7,  "📈", "W底確認",  2),
            "S5":           (6,  "📈", "站上均線", 2),
            "S1_SHORT":     (5,  "📉", "雙MACD空", 2),
            "S17A":         (4,  "🔍", "底部翻試", 1),
            "S17B":         (3,  "🔍", "撈底加碼", 1),
            "S_VOLX":       (2,  "💥", "量爆拉升", 1),
            "S_VOLX_SHORT": (2,  "💥", "量爆下殺", 1),
            "S_PB":         (1,  "📊", "均線拉回", 1),
        }
        for strategy_key, results in scan_res.items():
            if strategy_key not in _SIG_MAP:
                continue
            entry = _SIG_MAP[strategy_key]
            for r in results:
                sid = r.get("stock_id", "")
                if not sid:
                    continue
                if sid not in all_sig:
                    all_sig[sid] = {}
                all_sig[sid][strategy_key] = entry
        for item in merged:
            sig_map = all_sig.get(item["stock_id"])
            if sig_map:
                sigs = sorted(sig_map.values(), key=lambda x: x[0], reverse=True)
                item["signal_emoji"] = sigs[0][1]
                item["signal_title"] = "·".join(s[2] for s in sigs)
                item["signal_level"] = sigs[0][3]
    except Exception:
        pass

    # 若無策略掃描訊號，以法人買賣超流向產生基礎訊號
    for item in merged:
        if item["signal_title"] != "—":
            continue
        wf = item.get("whale_flow_lots", 0) or 0
        fgn = item.get("foreign_lots", 0) or 0
        if wf >= 2000 or fgn >= 1500:
            item["signal_emoji"] = "📈"
            item["signal_title"] = "強力買超"
            item["signal_level"] = 1
        elif wf >= 500:
            item["signal_emoji"] = "📈"
            item["signal_title"] = "法人買超"
            item["signal_level"] = 1
        elif wf <= -2000 or fgn <= -1500:
            item["signal_emoji"] = "📉"
            item["signal_title"] = "強力賣超"
            item["signal_level"] = 1
        elif wf <= -500:
            item["signal_emoji"] = "📉"
            item["signal_title"] = "法人賣超"
            item["signal_level"] = 1

    return {
        "date":        used_date_str,
        "total":       len(merged),
        "top_buyers":  merged[:top],
        "top_sellers": list(reversed(merged))[:top],
    }


# ════════════════════════════════════════════════════════════════════════════
# Stock Query API
# ════════════════════════════════════════════════════════════════════════════

_INDEX_YAHOO_MAP = {
    "taiex": "^TWII",
    "otc":   "^TWOTC",
    "tx":    "TXF=F",
    "tf":    "TFF=F",
    "te":    "TEF=F",
}
_INDEX_NAMES = {
    "taiex": "加權指數",
    "otc":   "上櫃指數",
    "tx":    "台指近",
    "tf":    "金融近",
    "te":    "電子近",
}

@app.get("/api/index/{key}/ohlcv")
def api_index_ohlcv(key: str, interval: str = "1d"):
    """回傳指數/期貨近月 OHLCV 資料（供 K 線圖使用），支援多週期"""
    from yahoo_price import _parse_yahoo_json
    sym = _INDEX_YAHOO_MAP.get(key)
    if not sym:
        raise HTTPException(status_code=404, detail=f"Unknown index key: {key}")
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    now = int(_time.time())
    _ICFG = {
        "3m": ("3m", 5), "5m": ("5m", 59), "30m": ("30m", 59),
        "60m": ("60m", 59), "1d": ("1d", 730), "3d": ("1d", 730),
        "1wk": ("1wk", 1825), "1mo": ("1mo", 3650),
    }
    yf_iv, days_back = _ICFG.get(interval, ("1d", 730))
    params = {"interval": yf_iv, "period1": now - days_back * 86400, "period2": now}
    for host in ["query1", "query2"]:
        try:
            r = httpx.get(
                f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}",
                params=params,
                headers={"User-Agent": UA, "Accept": "application/json"},
                timeout=10.0, verify=False, follow_redirects=True,
            )
            r.raise_for_status()
            df = _parse_yahoo_json(r.json())
            if not df.empty and len(df) >= 5:
                return df.tail(500).fillna(0).to_dict(orient="records")
        except Exception:
            pass
    # Fallback for futures: use underlying index
    FALLBACKS = {"tx": "^TWII", "tf": "^TWII", "te": "^SOX"}
    fb_sym = FALLBACKS.get(key)
    if fb_sym:
        for host in ["query1", "query2"]:
            try:
                r = httpx.get(
                    f"https://{host}.finance.yahoo.com/v8/finance/chart/{fb_sym}",
                    params=params,
                    headers={"User-Agent": UA, "Accept": "application/json"},
                    timeout=10.0, verify=False, follow_redirects=True,
                )
                r.raise_for_status()
                df = _parse_yahoo_json(r.json())
                if not df.empty and len(df) >= 5:
                    # Mark as fallback index
                    return df.tail(500).fillna(0).to_dict(orient="records")
            except Exception:
                pass
    raise HTTPException(status_code=404, detail=f"{key} ({sym}) 無法取得 K 線資料")


@app.get("/api/backtest/fbd")
def api_backtest_fbd(stock_id: str, holding_days: int = 0,
                     trailing_low_days: int = 0,
                     exit_ma: int = 10,
                     stop_loss: float = 0.0, take_profit: float = 0.0,
                     taiex_bull: int = 0, big_macd: int = 0):
    """
    假跌破/假突破回測：
    - 進場：訊號當日收盤（尾盤進場）
    - 出場：跌破前 trailing_low_days 天低點，或觸及停損/停利
    - holding_days: 出場天數上限，0 = 不限（持到跌破低點）
    - trailing_low_days: 跌破幾天低點出場，0 = 不啟用
    - stop_loss: 停損百分比（如 5 = 5%），0 = 不啟用
    - take_profit: 停利百分比（如 10 = 10%），0 = 不啟用
    - 訊號定義：
        假跌破（FBD）: 當日 close < MA10，隔日 close > MA10
        假突破（FBR）: 當日 close > MA10，隔日 close < MA10
    """
    import pandas as pd
    from yahoo_price import _parse_yahoo_json, get_stock_list
    stocks = get_stock_list()
    row = stocks[stocks["stock_id"] == stock_id]
    market = str(row.iloc[0]["type"]) if not row.empty else "twse"
    suffixes = [".TW"] if market == "twse" else [".TWO", ".TW"]
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    now = int(_time.time())
    p1 = now - 730 * 86400
    params = {"interval": "1d", "period1": p1, "period2": now}

    df = None
    for host in ["query1", "query2"]:
        for suffix in suffixes:
            try:
                r = httpx.get(
                    f"https://{host}.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}",
                    params=params,
                    headers={"User-Agent": UA, "Accept": "application/json"},
                    timeout=12.0, verify=False, follow_redirects=True,
                )
                r.raise_for_status()
                df = _parse_yahoo_json(r.json())
                if df is not None and not df.empty and len(df) >= 30:
                    break
            except Exception:
                pass
        if df is not None and not df.empty and len(df) >= 30:
            break

    if df is None or df.empty or len(df) < 30:
        raise HTTPException(status_code=404, detail=f"{stock_id} 無法取得歷史資料")

    closes = df["close"].values
    lows   = df["low"].values
    highs  = df["high"].values
    dates  = df["date"].values
    n = len(closes)

    # 計算 MA10
    ma10 = pd.Series(closes).rolling(10, min_periods=10).mean().values

    sl_frac = stop_loss / 100.0   # e.g. 5% → 0.05
    tp_frac = take_profit / 100.0

    # ── 加權指數多頭排列篩選 (MA5 > MA10 > MA20 > MA60) ──────────────────────
    taiex_bull_dates: set = set()
    if taiex_bull > 0:
        try:
            from relationship.db import get_conn as _rel_conn
            rc = _rel_conn()
            trows = rc.execute(
                "SELECT observation_date, taiex_close FROM market_daily "
                "WHERE taiex_close IS NOT NULL ORDER BY observation_date ASC"
            ).fetchall()
            rc.close()
            if trows:
                t_closes = pd.Series([r[1] for r in trows],
                                     index=[r[0] for r in trows])
                _ma5  = t_closes.rolling(5).mean()
                _ma10 = t_closes.rolling(10).mean()
                _ma20 = t_closes.rolling(20).mean()
                _ma60 = t_closes.rolling(60).mean()
                for dt_dash, m5, m10, m20, m60 in zip(
                    t_closes.index, _ma5, _ma10, _ma20, _ma60
                ):
                    if not any(pd.isna(x) for x in [m5, m10, m20, m60]):
                        if m5 > m10 > m20 > m60:
                            taiex_bull_dates.add(dt_dash.replace("-", ""))
        except Exception:
            pass  # 若 relationship DB 不存在，跳過此篩選

    # ── 大 MACD（週線 DIF>0 & DEA>0 & 柱狀紅柱）篩選 ───────────────────────
    big_macd_arr: list = [True] * n   # default: all pass
    if big_macd > 0:
        try:
            date_idx = pd.to_datetime(pd.Series(dates), format="%Y%m%d")
            close_s = pd.Series(closes, index=date_idx)
            # 以週五收盤代表週K（台股週一至週五）
            weekly = close_s.resample("W-FRI").last().dropna()
            ema12w = weekly.ewm(span=12, adjust=False).mean()
            ema26w = weekly.ewm(span=26, adjust=False).mean()
            dif_w  = ema12w - ema26w
            dea_w  = dif_w.ewm(span=9, adjust=False).mean()
            hist_w = dif_w - dea_w
            # 前填補：每個交易日繼承上個週五的週線 MACD 值
            dif_d  = dif_w.reindex(date_idx, method="ffill")
            dea_d  = dea_w.reindex(date_idx, method="ffill")
            hist_d = hist_w.reindex(date_idx, method="ffill")
            big_macd_arr = (
                (dif_d > 0) & (dea_d > 0) & (hist_d > 0)
            ).fillna(False).tolist()
        except Exception:
            big_macd_arr = [True] * n

    # ── 出場均線陣列 ──────────────────────────────────────────────────────────
    exit_ma_arr = None
    if exit_ma > 0:
        exit_ma_arr = pd.Series(closes).rolling(exit_ma, min_periods=exit_ma).mean().values

    def run_backtest(signal_type: str):
        """signal_type: 'fbd' (看多/long) or 'fbr' (看空/short)"""
        is_short = (signal_type == "fbr")
        trades = []
        for i in range(10, n - 1):
            if pd.isna(ma10[i]) or pd.isna(ma10[i+1]):
                continue
            # ── 市場環境篩選 ──
            if taiex_bull > 0 and dates[i] not in taiex_bull_dates:
                continue
            if big_macd > 0 and not big_macd_arr[i]:
                continue
            # ── 訊號觸發 ──
            if signal_type == "fbd":
                triggered = (closes[i-1] < ma10[i-1]) and (closes[i] > ma10[i])
            else:
                triggered = (closes[i-1] > ma10[i-1]) and (closes[i] < ma10[i])
            if not triggered:
                continue

            entry_price = closes[i]
            # 停損/停利方向：做空時反轉
            if is_short:
                sl_price = round(entry_price * (1 + sl_frac), 2) if sl_frac > 0 else None
                tp_price = round(entry_price * (1 - tp_frac), 2) if tp_frac > 0 else None
            else:
                sl_price = round(entry_price * (1 - sl_frac), 2) if sl_frac > 0 else None
                tp_price = round(entry_price * (1 + tp_frac), 2) if tp_frac > 0 else None

            # 出場模擬
            exit_reason = ""
            max_j = (i + holding_days) if holding_days > 0 else (n - 1)
            exit_idx = min(max_j, n - 1)

            for j in range(i + 1, min(max_j + 1, n)):
                c = closes[j]
                if is_short:
                    # 做空停損：股價上漲超過 sl%
                    if sl_price is not None and c >= sl_price:
                        exit_idx = j; exit_reason = "停損"; break
                    # 做空停利：股價下跌超過 tp%
                    if tp_price is not None and c <= tp_price:
                        exit_idx = j; exit_reason = "停利"; break
                    # 做空均線出場：股價站回均線以上
                    if exit_ma_arr is not None:
                        ma_v = exit_ma_arr[j]
                        if not pd.isna(ma_v) and c > ma_v:
                            exit_idx = j; exit_reason = f"站上MA{exit_ma}"; break
                    # 做空追蹤高點出場：股價突破前N天高點
                    if trailing_low_days > 0:
                        lb_start = max(i, j - trailing_low_days)
                        if lb_start < j:
                            trail_high = float(max(highs[lb_start:j]))
                            if c > trail_high:
                                exit_idx = j; exit_reason = "突破高點"; break
                else:
                    # 做多停損：股價下跌超過 sl%
                    if sl_price is not None and c <= sl_price:
                        exit_idx = j; exit_reason = "停損"; break
                    # 做多停利：股價上漲超過 tp%
                    if tp_price is not None and c >= tp_price:
                        exit_idx = j; exit_reason = "停利"; break
                    # 做多均線出場：股價跌破均線
                    if exit_ma_arr is not None:
                        ma_v = exit_ma_arr[j]
                        if not pd.isna(ma_v) and c < ma_v:
                            exit_idx = j; exit_reason = f"破MA{exit_ma}"; break
                    # 做多追蹤低點出場
                    if trailing_low_days > 0:
                        lb_start = max(i, j - trailing_low_days)
                        if lb_start < j:
                            trail_low = float(min(lows[lb_start:j]))
                            if c < trail_low:
                                exit_idx = j; exit_reason = "跌破低點"; break

            if not exit_reason:
                exit_reason = "天數到期" if holding_days > 0 else "持至末端"

            # 追蹤參考價（出場時點的追蹤低/高點）
            trail_ref = None
            if trailing_low_days > 0 and exit_idx > i:
                lb_s = max(i, exit_idx - trailing_low_days)
                if lb_s < exit_idx:
                    trail_ref = round(float(
                        max(highs[lb_s:exit_idx]) if is_short else min(lows[lb_s:exit_idx])
                    ), 2)

            exit_price = closes[exit_idx]
            # 回報計算：做空時股價下跌才獲利
            if is_short:
                ret = (entry_price - exit_price) / entry_price
            else:
                ret = (exit_price - entry_price) / entry_price

            trades.append({
                "entry_date":  dates[i],
                "entry_price": float(entry_price),
                "exit_date":   dates[exit_idx],
                "exit_price":  float(exit_price),
                "return":      round(float(ret), 4),
                "exit_reason": exit_reason,
                "sl_price":    sl_price,
                "tp_price":    tp_price,
                "trail_ref":   trail_ref,
            })

        if not trades:
            return {"count": 0}
        rets = [t["return"] for t in trades]
        wins = [r for r in rets if r > 0]
        return {
            "count":         len(trades),
            "win_rate":      round(len(wins) / len(rets), 3),
            "avg_return":    round(sum(rets) / len(rets), 4),
            "median_return": round(sorted(rets)[len(rets)//2], 4),
            "max_win":       round(max(rets), 4),
            "max_loss":      round(min(rets), 4),
            "trades":        trades[-30:],
        }

    return {
        "stock_id":    stock_id,
        "holding_days": holding_days,
        "trailing_low_days": trailing_low_days,
        "exit_ma":     exit_ma,
        "stop_loss":   stop_loss,
        "take_profit": take_profit,
        "taiex_bull":  taiex_bull,
        "big_macd":    big_macd,
        "total_bars":  n,
        "fbd": run_backtest("fbd"),
        "fbr": run_backtest("fbr"),
    }


@app.get("/api/backtest/index")
def api_backtest_index(key: str, holding_days: int = 0,
                       trailing_low_days: int = 0,
                       exit_ma: int = 10,
                       stop_loss: float = 0.0, take_profit: float = 0.0,
                       taiex_bull: int = 0,
                       big_macd: int = 0):
    """指數 MA10 假跌破/假突破回測（同個股邏輯，但使用指數 OHLCV 資料）"""
    import pandas as pd
    from yahoo_price import _parse_yahoo_json
    sym = _INDEX_YAHOO_MAP.get(key)
    name = _INDEX_NAMES.get(key, key)
    if not sym:
        raise HTTPException(status_code=404, detail=f"Unknown index key: {key}")
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    now = int(_time.time())
    params = {"interval": "1d", "period1": now - 730 * 86400, "period2": now}

    df = None
    for host in ["query1", "query2"]:
        try:
            r = httpx.get(
                f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}",
                params=params,
                headers={"User-Agent": UA, "Accept": "application/json"},
                timeout=12.0, verify=False, follow_redirects=True,
            )
            r.raise_for_status()
            df = _parse_yahoo_json(r.json())
            if df is not None and not df.empty and len(df) >= 30:
                break
        except Exception:
            pass
    if df is None or df.empty or len(df) < 30:
        raise HTTPException(status_code=404, detail=f"{name} ({sym}) 無法取得歷史資料")

    closes = df["close"].values
    lows   = df["low"].values
    highs  = df["high"].values
    dates  = df["date"].values
    n = len(closes)
    ma10 = pd.Series(closes).rolling(10, min_periods=10).mean().values
    sl_frac = stop_loss / 100.0
    tp_frac = take_profit / 100.0

    # ── 大 MACD 週線篩選（指數本身）────────────────────────────────────────────
    big_macd_arr_idx: list = [True] * n
    if big_macd > 0:
        try:
            date_idx = pd.to_datetime(pd.Series(dates), format="%Y%m%d")
            close_s = pd.Series(closes, index=date_idx)
            weekly = close_s.resample("W-FRI").last().dropna()
            ema12w = weekly.ewm(span=12, adjust=False).mean()
            ema26w = weekly.ewm(span=26, adjust=False).mean()
            dif_w  = ema12w - ema26w
            dea_w  = dif_w.ewm(span=9, adjust=False).mean()
            hist_w = dif_w - dea_w
            dif_d  = dif_w.reindex(date_idx, method="ffill")
            dea_d  = dea_w.reindex(date_idx, method="ffill")
            hist_d = hist_w.reindex(date_idx, method="ffill")
            big_macd_arr_idx = (
                (dif_d > 0) & (dea_d > 0) & (hist_d > 0)
            ).fillna(False).tolist()
        except Exception:
            big_macd_arr_idx = [True] * n

    # ── 加權多頭排列篩選（指數模式：直接用本 df 的 MA） ──────────────────────
    taiex_bull_dates_idx: set = set()
    if taiex_bull > 0:
        try:
            _ma5  = pd.Series(closes).rolling(5).mean().values
            _ma10c = pd.Series(closes).rolling(10).mean().values
            _ma20c = pd.Series(closes).rolling(20).mean().values
            _ma60c = pd.Series(closes).rolling(60).mean().values
            for i_t, dt_t in enumerate(dates):
                m5, m10c, m20c, m60c = _ma5[i_t], _ma10c[i_t], _ma20c[i_t], _ma60c[i_t]
                if not any(pd.isna(x) for x in [m5, m10c, m20c, m60c]):
                    if m5 > m10c > m20c > m60c:
                        taiex_bull_dates_idx.add(dt_t)
        except Exception:
            pass

    # ── 出場均線陣列 ──────────────────────────────────────────────────────────
    exit_ma_arr = None
    if exit_ma > 0:
        exit_ma_arr = pd.Series(closes).rolling(exit_ma, min_periods=exit_ma).mean().values

    def run_backtest(signal_type: str):
        """signal_type: 'fbd' (看多/long) or 'fbr' (看空/short)"""
        is_short = (signal_type == "fbr")
        trades = []
        for i in range(10, n - 1):
            if pd.isna(ma10[i]) or pd.isna(ma10[i+1]):
                continue
            # ── 市場環境篩選 ──
            if taiex_bull > 0 and dates[i] not in taiex_bull_dates_idx:
                continue
            if big_macd > 0 and not big_macd_arr_idx[i]:
                continue
            # ── 訊號觸發 ──
            if signal_type == "fbd":
                triggered = (closes[i-1] < ma10[i-1]) and (closes[i] > ma10[i])
            else:
                triggered = (closes[i-1] > ma10[i-1]) and (closes[i] < ma10[i])
            if not triggered:
                continue

            entry_price = closes[i]
            # 停損/停利方向：做空時反轉
            if is_short:
                sl_price = round(entry_price * (1 + sl_frac), 2) if sl_frac > 0 else None
                tp_price = round(entry_price * (1 - tp_frac), 2) if tp_frac > 0 else None
            else:
                sl_price = round(entry_price * (1 - sl_frac), 2) if sl_frac > 0 else None
                tp_price = round(entry_price * (1 + tp_frac), 2) if tp_frac > 0 else None

            # 出場模擬
            exit_reason = ""
            max_j = (i + holding_days) if holding_days > 0 else (n - 1)
            exit_idx = min(max_j, n - 1)

            for j in range(i + 1, min(max_j + 1, n)):
                c = closes[j]
                if is_short:
                    # 做空停損：股價上漲超過 sl%
                    if sl_price is not None and c >= sl_price:
                        exit_idx = j; exit_reason = "停損"; break
                    # 做空停利：股價下跌超過 tp%
                    if tp_price is not None and c <= tp_price:
                        exit_idx = j; exit_reason = "停利"; break
                    # 做空均線出場：股價站回均線以上
                    if exit_ma_arr is not None:
                        ma_v = exit_ma_arr[j]
                        if not pd.isna(ma_v) and c > ma_v:
                            exit_idx = j; exit_reason = f"站上MA{exit_ma}"; break
                    # 做空追蹤高點出場：股價突破前N天高點
                    if trailing_low_days > 0:
                        lb_start = max(i, j - trailing_low_days)
                        if lb_start < j:
                            trail_high = float(max(highs[lb_start:j]))
                            if c > trail_high:
                                exit_idx = j; exit_reason = "突破高點"; break
                else:
                    # 做多停損：股價下跌超過 sl%
                    if sl_price is not None and c <= sl_price:
                        exit_idx = j; exit_reason = "停損"; break
                    # 做多停利：股價上漲超過 tp%
                    if tp_price is not None and c >= tp_price:
                        exit_idx = j; exit_reason = "停利"; break
                    # 做多均線出場：股價跌破均線
                    if exit_ma_arr is not None:
                        ma_v = exit_ma_arr[j]
                        if not pd.isna(ma_v) and c < ma_v:
                            exit_idx = j; exit_reason = f"破MA{exit_ma}"; break
                    # 做多追蹤低點出場
                    if trailing_low_days > 0:
                        lb_start = max(i, j - trailing_low_days)
                        if lb_start < j:
                            trail_low = float(min(lows[lb_start:j]))
                            if c < trail_low:
                                exit_idx = j; exit_reason = "跌破低點"; break

            if not exit_reason:
                exit_reason = "天數到期" if holding_days > 0 else "持至末端"

            # 追蹤參考價（出場時點的追蹤低/高點）
            trail_ref = None
            if trailing_low_days > 0 and exit_idx > i:
                lb_s = max(i, exit_idx - trailing_low_days)
                if lb_s < exit_idx:
                    trail_ref = round(float(
                        max(highs[lb_s:exit_idx]) if is_short else min(lows[lb_s:exit_idx])
                    ), 2)

            exit_price = closes[exit_idx]
            # 回報計算：做空時股價下跌才獲利
            if is_short:
                ret = (entry_price - exit_price) / entry_price
            else:
                ret = (exit_price - entry_price) / entry_price

            trades.append({
                "entry_date":  dates[i],
                "entry_price": float(entry_price),
                "exit_date":   dates[exit_idx],
                "exit_price":  float(exit_price),
                "return":      round(float(ret), 4),
                "exit_reason": exit_reason,
                "sl_price":    sl_price,
                "tp_price":    tp_price,
                "trail_ref":   trail_ref,
            })

        if not trades:
            return {"count": 0}
        rets = [t["return"] for t in trades]
        wins = [r for r in rets if r > 0]
        return {
            "count":         len(trades),
            "win_rate":      round(len(wins) / len(rets), 3),
            "avg_return":    round(sum(rets) / len(rets), 4),
            "median_return": round(sorted(rets)[len(rets)//2], 4),
            "max_win":       round(max(rets), 4),
            "max_loss":      round(min(rets), 4),
            "trades":        trades[-30:],
        }

    return {
        "key": key, "name": name, "holding_days": holding_days,
        "trailing_low_days": trailing_low_days,
        "exit_ma": exit_ma,
        "stop_loss": stop_loss, "take_profit": take_profit, "total_bars": n,
        "fbd": run_backtest("fbd"),
        "fbr": run_backtest("fbr"),
    }


@app.get("/api/backtest/strategy-batch")
def api_backtest_strategy_batch(
    strategy: str,
    trailing_low_days: int = 2,
    holding_days: int = 0,
    stop_loss: float = 0.0,
    take_profit: float = 0.0,
    signal: str = "fbd",
    max_stocks: int = 40,
):
    """批量回測：對策略篩選出的股票跑 MA10 假跌破/假突破回測，彙總統計"""
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from yahoo_price import get_scan_results, _parse_yahoo_json, get_stock_list

    scan_res = get_scan_results()
    raw_list = scan_res.get(strategy, [])
    if not raw_list:
        raise HTTPException(status_code=404, detail=f"策略 {strategy} 尚無掃描結果，請先執行全市場掃描")

    stocks = get_stock_list()
    stock_ids = [s["stock_id"] for s in raw_list[:max_stocks]]
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    now_ts = int(_time.time())
    p1 = now_ts - 730 * 86400
    params_yf = {"interval": "1d", "period1": p1, "period2": now_ts}
    sl_frac = stop_loss / 100.0
    tp_frac = take_profit / 100.0

    def _one_stock(stock_id):
        row = stocks[stocks["stock_id"] == stock_id]
        market = str(row.iloc[0]["type"]) if not row.empty else "twse"
        suffixes = [".TW"] if market == "twse" else [".TWO", ".TW"]
        df = None
        for host in ["query1", "query2"]:
            for suffix in suffixes:
                try:
                    r = httpx.get(
                        f"https://{host}.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}",
                        params=params_yf,
                        headers={"User-Agent": UA, "Accept": "application/json"},
                        timeout=12.0, verify=False, follow_redirects=True,
                    )
                    r.raise_for_status()
                    df = _parse_yahoo_json(r.json())
                    if df is not None and not df.empty and len(df) >= 30:
                        break
                except Exception:
                    pass
            if df is not None and not df.empty and len(df) >= 30:
                break
        if df is None or df.empty or len(df) < 30:
            return None

        closes = df["close"].values
        lows_arr = df["low"].values
        dates_arr = df["date"].values
        n = len(closes)
        ma10 = pd.Series(closes).rolling(10, min_periods=10).mean().values
        trades = []
        for i in range(10, n - 1):
            if pd.isna(ma10[i]) or pd.isna(ma10[i + 1]):
                continue
            if signal == "fbd":
                triggered = (closes[i - 1] < ma10[i - 1]) and (closes[i] > ma10[i])
            else:
                triggered = (closes[i - 1] > ma10[i - 1]) and (closes[i] < ma10[i])
            if not triggered:
                continue
            entry_price = closes[i]
            sl_price = round(entry_price * (1 - sl_frac), 2) if sl_frac > 0 else None
            tp_price = round(entry_price * (1 + tp_frac), 2) if tp_frac > 0 else None
            exit_reason = "時間"
            max_j = (i + holding_days) if holding_days > 0 else (n - 1)
            exit_idx = min(max_j, n - 1)
            for j in range(i + 1, min(max_j + 1, n)):
                c = closes[j]
                if sl_price is not None and c <= sl_price:
                    exit_idx = j; exit_reason = "停損"; break
                if tp_price is not None and c >= tp_price:
                    exit_idx = j; exit_reason = "停利"; break
                if trailing_low_days > 0:
                    lb_start = max(i, j - trailing_low_days)
                    if lb_start < j:
                        trail_low = float(min(lows_arr[lb_start:j]))
                        if c < trail_low:
                            exit_idx = j; exit_reason = "跌破低點"; break
            exit_price = closes[exit_idx]
            ret = (exit_price - entry_price) / entry_price
            trades.append({"return": round(float(ret), 4), "exit_reason": exit_reason,
                           "entry_date": dates_arr[i], "exit_date": dates_arr[exit_idx]})
        if not trades:
            return None
        rets = [t["return"] for t in trades]
        wins = [r for r in rets if r > 0]
        return {
            "stock_id": stock_id,
            "name": next((s.get("name", "") for s in raw_list if s.get("stock_id") == stock_id), ""),
            "count": len(trades),
            "win_rate": round(len(wins) / len(rets), 3),
            "avg_return": round(sum(rets) / len(rets), 4),
            "max_win": round(max(rets), 4),
            "max_loss": round(min(rets), 4),
            "last_entry": trades[-1]["entry_date"] if trades else None,
        }

    by_stock = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_one_stock, sid): sid for sid in stock_ids}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                by_stock.append(res)

    if not by_stock:
        return {"strategy": strategy, "total_scanned": len(stock_ids), "computed": 0,
                "aggregate": {"count": 0}, "by_stock": []}

    all_rets = []
    for sr in by_stock:
        # weight each stock's avg equally
        all_rets.append(sr["avg_return"])

    by_stock.sort(key=lambda x: x["avg_return"], reverse=True)
    wins_agg = [r for r in all_rets if r > 0]
    return {
        "strategy": strategy,
        "signal": signal,
        "total_scanned": len(stock_ids),
        "computed": len(by_stock),
        "trailing_low_days": trailing_low_days,
        "holding_days": holding_days,
        "aggregate": {
            "stocks_with_trades": len(by_stock),
            "avg_win_rate": round(sum(s["win_rate"] for s in by_stock) / len(by_stock), 3),
            "avg_return": round(sum(all_rets) / len(all_rets), 4),
            "positive_stocks": len(wins_agg),
        },
        "by_stock": by_stock,
    }


@app.get("/api/stock/{stock_id}/ohlcv")
def api_stock_ohlcv(stock_id: str, interval: str = "1d"):
    """回傳個股 OHLCV 日線/週線/分線資料（供 K 線圖使用）"""
    import pandas as pd
    from yahoo_price import _parse_yahoo_json, get_stock_list
    stocks = get_stock_list()
    row = stocks[stocks["stock_id"] == stock_id]
    market = str(row.iloc[0]["type"]) if not row.empty else "twse"
    suffixes = [".TW"] if market == "twse" else [".TWO", ".TW"]

    # 映射 interval → (yf_interval, days_back, is_intraday)
    _ICFG = {
        "3m":  ("3m",  5,    True),
        "5m":  ("5m",  59,   True),
        "30m": ("30m", 59,   True),
        "60m": ("60m", 59,   True),
        "1d":  ("1d",  730,  False),
        "3d":  ("1d",  730,  False),
        "1wk": ("1wk", 1825, False),
        "1mo": ("1mo", 3650, False),
    }
    yf_iv, days, is_intraday = _ICFG.get(interval, ("1d", 730, False))
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    now = int(_time.time())
    p1 = now - days * 86400
    params = {"interval": yf_iv, "period1": p1, "period2": now}

    for host in ["query1", "query2"]:
        for suffix in suffixes:
            try:
                r = httpx.get(
                    f"https://{host}.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}",
                    params=params,
                    headers={"User-Agent": UA, "Accept": "application/json"},
                    timeout=12.0, verify=False, follow_redirects=True,
                )
                r.raise_for_status()
                raw = (r.json().get("chart", {}).get("result") or [])
                if not raw:
                    continue
                res = raw[0]
                timestamps = res.get("timestamp", [])
                quote = res.get("indicators", {}).get("quote", [{}])[0]
                opens  = quote.get("open",   [])
                highs  = quote.get("high",   [])
                lows   = quote.get("low",    [])
                closes = quote.get("close",  [])
                vols   = quote.get("volume", [])
                if not timestamps or not closes:
                    continue

                if is_intraday:
                    # 回傳含 Unix timestamp 的 records
                    # ts 加 8 小時偏移 (28800)，讓 LightweightCharts 顯示台灣時間
                    _TW_OFFSET = 8 * 3600
                    records = []
                    for i, ts in enumerate(timestamps):
                        c = closes[i] if i < len(closes) else None
                        if c is None:
                            continue
                        records.append({
                            "ts":     int(ts) + _TW_OFFSET,
                            "date":   datetime.utcfromtimestamp(ts + _TW_OFFSET).strftime("%Y%m%d"),
                            "open":   opens[i] if i < len(opens) else c,
                            "high":   highs[i] if i < len(highs) else c,
                            "low":    lows[i]  if i < len(lows)  else c,
                            "close":  c,
                            "volume": int(vols[i] or 0) if i < len(vols) else 0,
                        })
                    if records:
                        return records[-2000:]
                else:
                    df = _parse_yahoo_json(r.json())
                    if df is None or df.empty or len(df) < 5:
                        continue
                    if interval == "3d":
                        df["_dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
                        df3 = df.set_index("_dt").resample("3D").agg(
                            open=("open","first"), high=("high","max"),
                            low=("low","min"),   close=("close","last"),
                            volume=("volume","sum")
                        ).dropna(subset=["close"]).reset_index()
                        df3["date"] = df3["_dt"].dt.strftime("%Y%m%d")
                        df = df3.drop(columns=["_dt"])
                    return df.tail(500).fillna(0).to_dict(orient="records")
            except Exception:
                pass
    # Yahoo Finance 全部失敗 → FinMind 備援（日線 / 週線 / 月線）
    if not is_intraday:
        try:
            _FM_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiYnVidXN0IiwiZW1haWwiOiJidWJ1c3RAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.LcLL157_bH6YbABE7JOlg0cAEwwzOV6GfJA6uK2cvIA"
            import datetime as _dt2
            start_date = (_dt2.datetime.now(_dt2.timezone(_dt2.timedelta(hours=8))).date() - _dt2.timedelta(days=days)).strftime("%Y-%m-%d")
            fm_r = httpx.get(
                "https://api.finmindtrade.com/api/v4/data",
                params={"dataset": "TaiwanStockPrice", "data_id": stock_id,
                        "start_date": start_date, "token": _FM_TOKEN},
                timeout=20.0, verify=False, follow_redirects=True,
            )
            fm_r.raise_for_status()
            fm_rows = fm_r.json().get("data", [])
            if fm_rows:
                df_fm = pd.DataFrame(fm_rows)
                df_fm = df_fm.rename(columns={"max": "high", "min": "low",
                                               "Trading_Volume": "volume"})
                df_fm["date"] = df_fm["date"].str.replace("-", "")
                df_fm = df_fm[["date", "open", "high", "low", "close", "volume"]]
                df_fm = df_fm.dropna(subset=["close"]).astype(
                    {"open": float, "high": float, "low": float,
                     "close": float, "volume": int})
                if interval == "1wk":
                    df_fm["_dt"] = pd.to_datetime(df_fm["date"], format="%Y%m%d")
                    df_fm = df_fm.set_index("_dt").resample("W").agg(
                        open=("open","first"), high=("high","max"),
                        low=("low","min"),   close=("close","last"),
                        volume=("volume","sum")).dropna(subset=["close"]).reset_index()
                    df_fm["date"] = df_fm["_dt"].dt.strftime("%Y%m%d")
                    df_fm = df_fm.drop(columns=["_dt"])
                elif interval == "3d":
                    df_fm["_dt"] = pd.to_datetime(df_fm["date"], format="%Y%m%d")
                    df_fm = df_fm.set_index("_dt").resample("3D").agg(
                        open=("open","first"), high=("high","max"),
                        low=("low","min"),   close=("close","last"),
                        volume=("volume","sum")).dropna(subset=["close"]).reset_index()
                    df_fm["date"] = df_fm["_dt"].dt.strftime("%Y%m%d")
                    df_fm = df_fm.drop(columns=["_dt"])
                return df_fm.tail(500).fillna(0).to_dict(orient="records")
        except Exception:
            pass
    raise HTTPException(status_code=404, detail=f"{stock_id} 無法取得 {interval} 資料")

@app.get("/api/stock/{stock_id}")
async def api_stock(stock_id: str, days: int = 30):
    records = load_stock_history(stock_id)
    if not records:
        await update_stocks([stock_id], days=days)
        records = load_stock_history(stock_id)
    if not records:
        raise HTTPException(status_code=404, detail=f"{stock_id} 尚無資料")
    return {"stock_id": stock_id, "data": records[-days:]}

@app.post("/api/stock/{stock_id}/refresh")
async def api_refresh_stock(stock_id: str, days: int = 30):
    await update_stocks([stock_id], days=days)
    records = load_stock_history(stock_id)
    return {"ok": True, "stock_id": stock_id, "records": len(records)}


# ════════════════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════════════════
# TDCC 千張大戶週資料
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/tdcc/refresh")
async def api_tdcc_refresh(background_tasks: BackgroundTasks):
    """觸發 TDCC 官方 OpenAPI 更新（全市場，無 IP 限制）"""
    from tdcc_chip import refresh_for_stocks
    background_tasks.add_task(refresh_for_stocks)
    return {"ok": True, "message": "已開始從 TDCC 官方 OpenAPI 下載全市場資料（~9.7MB）"}

@app.post("/api/chip/import")
async def api_chip_import(request: Request):
    """
    接收本機上傳的 TDCC 千張大戶週資料。
    Body: {"date": "20260904", "data": {"2330": 78.5, "2317": 45.2, ...}}
    """
    from tdcc_chip import _save
    body = await request.json()
    date_str = str(body.get("date", "")).strip()
    data     = body.get("data", {})
    if not date_str or not data:
        raise HTTPException(status_code=400, detail="缺少 date 或 data")
    if len(date_str) != 8 or not date_str.isdigit():
        raise HTTPException(status_code=400, detail="date 格式應為 YYYYMMDD")
    clean = {str(k): float(v) for k, v in data.items() if v is not None}
    _save(date_str, clean)
    return {"ok": True, "date": date_str, "count": len(clean)}

@app.get("/api/stock/{stock_id}/tdcc")
def api_stock_tdcc(stock_id: str):
    """回傳單支股票的千張大戶歷史（最近 12 週）"""
    from tdcc_chip import get_stock_tdcc_history
    history = get_stock_tdcc_history(stock_id, weeks=12)
    return {"stock_id": stock_id, "history": history}

@app.get("/api/stock/{stock_id}/norway")
async def api_stock_norway(stock_id: str):
    """回傳 norway.twsthr.info 千張大戶細分週資料（最近 20 週）"""
    from norway_holders import get_history
    history = await get_history(stock_id)
    return {"stock_id": stock_id, "history": history}

@app.post("/api/chip/refresh-watchlist")
async def api_chip_refresh_watchlist(background_tasks: BackgroundTasks):
    """用 FinMind 更新觀察清單股票的千張大戶資料（Plan C 手動觸發）"""
    from tdcc_chip import refresh_for_stocks
    sb_ids = sb.wl_get_ids()
    if sb_ids:  # 非空才採用 Supabase，空或 None 都 fallback 到 SQLite
        stock_ids = sb_ids
    else:
        conn = get_conn()
        rows = conn.execute("SELECT stock_id FROM watchlist").fetchall()
        conn.close()
        stock_ids = [r["stock_id"] for r in rows]
    if not stock_ids:
        return {"ok": False, "message": "觀察清單為空"}
    background_tasks.add_task(refresh_for_stocks, stock_ids)
    return {"ok": True, "count": len(stock_ids), "message": f"已開始更新 {len(stock_ids)} 支股票"}

@app.get("/api/tdcc/status")
def api_tdcc_status():
    """回傳 TDCC 快取狀態"""
    from tdcc_chip import get_tdcc_data, DB_PATH
    import sqlite3
    data = get_tdcc_data()
    # 取各日期的快取筆數
    date_counts = {}
    try:
        c = sqlite3.connect(DB_PATH)
        rows = c.execute("SELECT date, COUNT(*) FROM tdcc_holding GROUP BY date ORDER BY date DESC LIMIT 5").fetchall()
        date_counts = {r[0]: r[1] for r in rows}
        c.close()
    except Exception:
        pass
    if not data:
        return {"loaded": False, "count": 0, "date": None, "cache_by_date": date_counts}
    sample = next(iter(data.values()))
    return {"loaded": True, "count": len(data), "date": sample.get("date"), "cache_by_date": date_counts}

@app.get("/api/tdcc/test/{stock_id}")
async def api_tdcc_test(stock_id: str):
    """測試 TDCC 官方 OpenAPI（debug 用，無 IP 限制）"""
    from tdcc_chip import TDCC_OPENAPI, _parse_openapi_rows
    try:
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(TDCC_OPENAPI)
            r.raise_for_status()
            rows = r.json()
        date_str, data = _parse_openapi_rows(rows)
        kpct = data.get(stock_id, 0.0)
        available_dates = []
        try:
            import sqlite3
            from tdcc_chip import DB_PATH
            c = sqlite3.connect(DB_PATH)
            available_dates = [r[0] for r in c.execute(
                "SELECT DISTINCT date FROM tdcc_holding ORDER BY date DESC LIMIT 3"
            ).fetchall()]
            c.close()
        except Exception:
            pass
        return {"ok": True, "stock_id": stock_id, "date": date_str, "kpct": kpct, "available_dates": available_dates}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# 全市場策略掃描 API（Yahoo Finance）
# ════════════════════════════════════════════════════════════════════════════

def _load_strategy_params() -> dict:
    """從 DB 讀取所有策略參數設定，回傳 {strategy_key: {param_key: value}}"""
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE 'sp_%'").fetchall()
    conn.close()
    result = {}
    for r in rows:
        sk = r['key'][3:]   # 去掉 'sp_' prefix
        try:
            result[sk] = json.loads(r['value'])
        except Exception:
            pass
    return result

@app.post("/api/price-cache/backfill")
async def api_price_cache_backfill(background_tasks: BackgroundTasks, days: int = 260):
    """手動觸發 FinMind 歷史回填（掃描前如快取是冷的，先跑這個）"""
    import os
    if not os.environ.get("FINMIND_TOKEN"):
        return {"ok": False, "message": "未設定 FINMIND_TOKEN 環境變數"}
    from price_cache import backfill_from_finmind
    background_tasks.add_task(backfill_from_finmind, days=days)
    return {"ok": True, "message": f"FinMind 回填已啟動（{days} 天），請稍候 5~10 分鐘後再掃描"}

@app.get("/api/price-cache/status")
def api_price_cache_status():
    """查看 price_cache 狀態（含 warmup 階段）"""
    from price_cache import get_price_cache_status
    s = get_price_cache_status()
    s["warmup_phase"] = _warmup_status["phase"]
    s["warmup_days"]  = _warmup_status["days"]
    # 日數夠 AND 最新日股票數 >= 1000，才算真的可掃描
    # （避免 Supabase 只有 2 支時 days_cached=243 就被誤判 ready）
    s["ready"] = s["days_cached"] >= 60 and s["stocks"] >= 1000
    return s

@app.post("/api/screen/run")
async def api_screen_run(background_tasks: BackgroundTasks):
    from yahoo_price import get_scan_status, run_market_scan
    status = get_scan_status()
    if status["running"]:
        return {"ok": False, "message": "掃描中，請稍候"}
    strategy_params = _load_strategy_params()
    background_tasks.add_task(run_market_scan, strategy_params=strategy_params)
    return {"ok": True, "message": "全市場掃描已啟動（所有策略）..."}

@app.get("/api/screen/status")
def api_screen_status():
    from yahoo_price import get_scan_status
    return get_scan_status()

@app.get("/api/screen/results")
def api_screen_results():
    from yahoo_price import get_scan_results
    from scanner import STRATEGIES
    raw = get_scan_results()   # {strategy_key: [result_dict, ...]}
    return {
        "finished_at": _scan_status_ts(),
        "strategies":  STRATEGIES,
        "results":     raw,
    }

def _scan_status_ts():
    from yahoo_price import get_scan_status
    return get_scan_status()["finished_at"]

@app.post("/api/trigger-scan")
async def api_trigger_scan():
    """觸發 GitHub Actions 掃描 workflow"""
    import os, httpx
    token = os.getenv("GITHUB_PAT", "")
    if not token:
        raise HTTPException(status_code=500, detail="GITHUB_PAT 未設定")
    repo = os.getenv("GITHUB_REPO", "bubust/chip-tracke")
    workflow = "scan.yml"
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    try:
        r = httpx.post(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }, json={"ref": "main"}, timeout=15)
        if r.status_code == 204:
            return {"ok": True, "message": "GitHub Actions 掃描已觸發，約 5~10 分鐘後完成"}
        return {"ok": False, "message": f"GitHub API 回應 {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/scan-progress")
async def api_scan_progress():
    """讀取 GitHub Actions 掃描進度（從 GitHub repo scan_data/scan_progress.json）"""
    import supabase_store as sb
    raw = sb.kv_get("scan_progress")
    if not raw:
        return {"running": False, "progress": 0, "total": 0, "found": 0}
    try:
        import json
        return json.loads(raw)
    except Exception:
        return {"running": False, "progress": 0, "total": 0, "found": 0}


# ════════════════════════════════════════════════════════════════════════════
# 股票搜尋（從 stocks.csv）
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/stock-market/{stock_id}")
def api_stock_market(stock_id: str):
    """回傳單支股票的市場類型 twse/tpex"""
    try:
        from yahoo_price import get_stock_list
        stocks = get_stock_list()
        row = stocks[stocks["stock_id"] == stock_id]
        if row.empty:
            return {"market": "twse"}   # 預設上市
        return {"market": str(row.iloc[0]["type"])}
    except Exception:
        return {"market": "twse"}

@app.get("/api/search")
def api_search_stocks(q: str = ""):
    q = q.strip()
    if not q:
        return []
    try:
        from yahoo_price import get_stock_list
        stocks = get_stock_list()
        mask = (stocks["stock_id"].str.startswith(q) |
                stocks["stock_name"].str.contains(q, na=False))
        return stocks[mask].head(10)[["stock_id","stock_name","type"]].rename(
            columns={"stock_name": "name"}
        ).to_dict(orient="records")
    except Exception:
        return []


# ════════════════════════════════════════════════════════════════════════════
# Settings / Params API
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/params")
def api_get_params():
    return {
        "weights":    get_weights(),
        "thresholds": get_thresholds(),
        "defaults": {
            "weights":    DEFAULT_WEIGHTS,
            "thresholds": DEFAULT_THRESHOLDS,
        }
    }

@app.post("/api/params")
def api_save_params(body: ParamsBody):
    w = {k: float(v) for k, v in body.weights.items()    if k in DEFAULT_WEIGHTS}
    t = {k: float(v) for k, v in body.thresholds.items() if k in DEFAULT_THRESHOLDS}
    save_params(w, t)
    return {"ok": True, "saved_weights": len(w), "saved_thresholds": len(t)}

@app.post("/api/params/reset")
def api_reset_params():
    conn = get_conn()
    conn.execute("DELETE FROM settings WHERE key LIKE 'w_%' OR key LIKE 't_%'")
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/params/strategies")
def get_strategy_params():
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE 'sp_%'").fetchall()
    conn.close()
    saved = {}
    for r in rows:
        sk = r['key'][3:]   # 去掉 'sp_' prefix
        try:
            saved[sk] = json.loads(r['value'])
        except Exception:
            pass
    result = {}
    for skey, schema in STRATEGY_PARAMS_SCHEMA.items():
        saved_vals = saved.get(skey, {})
        params = {}
        for field in schema:
            params[field['key']] = saved_vals.get(field['key'], field['default'])
        result[skey] = {"schema": schema, "values": params}
    return result

@app.put("/api/params/strategies/{strategy_key}")
async def put_strategy_params(strategy_key: str, request: Request):
    body = await request.json()
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (f"sp_{strategy_key}", json.dumps(body))
    )
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/settings")
def api_get_settings():
    token   = settings_get("telegram_token") or ""
    chat_id = settings_get("telegram_chat_id") or ""
    masked  = (token[:10] + "...") if len(token) > 10 else token
    return {
        "telegram_token_masked": masked,
        "telegram_chat_id": chat_id,
        "has_token": bool(token),
    }

@app.post("/api/settings/telegram")
def api_save_telegram(body: TelegramSettings):
    settings_set("telegram_token",   body.token.strip())
    settings_set("telegram_chat_id", body.chat_id.strip())
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# Telegram Push API
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/telegram/test")
async def api_tg_test():
    ok = await tg_send("✅ 籌碼追蹤系統測試訊息\n連線正常！")
    if not ok:
        raise HTTPException(status_code=400, detail="推播失敗，請確認 token 與 chat_id")
    return {"ok": True}

@app.post("/api/telegram/push/{stock_id}")
async def api_tg_push_stock(stock_id: str):
    records = load_stock_history(stock_id)
    if not records:
        raise HTTPException(status_code=404, detail=f"{stock_id} 尚無資料")
    msg = format_stock_message(stock_id, records)
    ok  = await tg_send(msg)
    latest = records[-1]
    log_push(stock_id, latest.get("signal_emoji","⚪"), latest.get("signal_title","?"), ok)
    if not ok:
        raise HTTPException(status_code=400, detail="Telegram 推播失敗")
    return {"ok": True}

@app.post("/api/telegram/push-custom")
async def api_tg_push_custom(body: CustomMessage):
    ok = await tg_send(body.text)
    if not ok:
        raise HTTPException(status_code=400, detail="Telegram 推播失敗")
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# Status / Push Log
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/status")
def api_status():
    conn = get_conn()
    cache_count    = conn.execute("SELECT COUNT(*) FROM market_raw").fetchone()[0]
    watchlist_count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    conn.close()
    last_refresh = settings_get("last_refresh")
    return {
        "cache_count":      cache_count,
        "watchlist_count":  watchlist_count,
        "last_refresh":     last_refresh,
        "db_path":          str(DB_PATH),
    }

@app.get("/api/push-log")
def api_push_log(limit: int = 20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM push_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.delete("/api/cache")
def api_clear_cache():
    from chip_tracker_v2 import clear_bad_cache
    deleted = clear_bad_cache()
    return {"ok": True, "deleted": deleted}


# ════════════════════════════════════════════════════════════════════════════
# 首頁
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/debug/yahoo/{stock_id}")
async def debug_yahoo(stock_id: str):
    """Debug: 查看 Yahoo 原始 meta + 解析後 DataFrame 的最後幾行，確認補丁是否正確觸發"""
    import asyncio, time as _time
    from yahoo_price import get_stock_list
    import httpx, datetime as _dt

    stocks = get_stock_list()
    row = stocks[stocks["stock_id"] == stock_id]
    market = "twse" if row.empty else str(row.iloc[0]["type"])
    suffixes = [".TW"] if market == "twse" else [".TWO", ".TW"]

    now = int(_time.time())
    p1  = now - 730 * 86400  # 2y
    params = {"interval": "1d", "period1": p1, "period2": now}

    async with httpx.AsyncClient(verify=False, timeout=15,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}) as client:
        for suffix in suffixes:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}"
            try:
                r = await client.get(url, params=params)
                raw = r.json()
                result = (raw.get("chart", {}).get("result") or [{}])[0]
                meta   = result.get("meta", {})
                from yahoo_price import _parse_yahoo_json
                df = _parse_yahoo_json(raw)
                if df.empty:
                    continue

                rmt = meta.get("regularMarketTime", 0)
                rmp = meta.get("regularMarketPrice")
                rmo = meta.get("regularMarketOpen")
                rmh = meta.get("regularMarketDayHigh")
                rml = meta.get("regularMarketDayLow")
                rmv = meta.get("regularMarketVolume")
                # regularMarketTime 轉台灣時間
                rmt_tw = (_dt.datetime.utcfromtimestamp(int(rmt)) + _dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M") if rmt else None

                last5 = df.tail(5)[["date","open","high","low","close","volume"]].to_dict("records")
                return {
                    "stock_id":   stock_id,
                    "suffix":     suffix,
                    "total_rows": len(df),
                    "last_date":  df.iloc[-1]["date"],
                    "meta": {
                        "regularMarketTime_tw": rmt_tw,
                        "regularMarketOpen":    rmo,
                        "regularMarketDayHigh": rmh,
                        "regularMarketDayLow":  rml,
                        "regularMarketPrice":   rmp,
                        "regularMarketVolume":  rmv,
                    },
                    "last5_rows": last5,
                    "last_is_red_k": bool(float(df.iloc[-1]["close"]) > float(df.iloc[-1]["open"])) if df.iloc[-1]["open"] else None,
                }
            except Exception as e:
                return {"error": str(e), "suffix": suffix}
    return {"error": "no data"}


@app.get("/api/debug/bb/{stock_id}")
async def debug_bb(stock_id: str):
    """Debug: 查看 Yahoo 抓到的原始資料及 BB 計算過程"""
    import asyncio, time
    from yahoo_price import _fetch_yahoo_async, get_stock_list
    from scanner import calc_bb_score
    import httpx

    stocks = get_stock_list()
    row = stocks[stocks["stock_id"] == stock_id]
    market = "twse" if row.empty else str(row.iloc[0]["type"])
    suffixes = [".TW"] if market == "twse" else [".TWO", ".TW"]

    sem = asyncio.Semaphore(5)
    now = int(time.time())
    p1 = now - 365 * 86400
    params = {"interval": "1d", "period1": p1, "period2": now}
    async with httpx.AsyncClient(verify=False, timeout=15) as client:
        for suffix in suffixes:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}"
            try:
                r = await client.get(url, params=params)
                from yahoo_price import _parse_yahoo_json
                df = _parse_yahoo_json(r.json())
                if df.empty: continue
                closes = df["close"]
                ma20 = float(closes.rolling(20).mean().iloc[-1])
                std20 = float(closes.rolling(20).std(ddof=0).iloc[-1])
                last_close = float(df.iloc[-1]["close"])
                last_date = df.iloc[-1]["date"]
                raw_score = (last_close - ma20) / (2 * std20) * 10 if std20 > 0 else 0
                return {
                    "stock_id": stock_id, "suffix": suffix,
                    "total_rows": len(df),
                    "last_date": last_date,
                    "last_close": round(last_close, 2),
                    "ma20": round(ma20, 2),
                    "std20": round(std20, 4),
                    "upper_band": round(ma20 + 2*std20, 2),
                    "lower_band": round(ma20 - 2*std20, 2),
                    "raw_score": round(raw_score, 2),
                    "bb_score": calc_bb_score(df),
                    "last_10_closes": [round(float(x), 2) for x in closes.tail(10).tolist()],
                }
            except Exception as e:
                return {"error": str(e)}
    return {"error": "no data"}

@app.get("/api/debug/prices")
async def debug_prices():
    """Debug: 直接呼叫各現價來源，回傳原始結構與解析結果，方便確認 Render 上可連到哪些 API"""
    out = {}
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.twse.com.tw/",
    }
    async with httpx.AsyncClient(headers=hdrs, timeout=20, follow_redirects=True, verify=False) as client:
        def _inspect(label, r_status, jdata):
            """解析回傳的 JSON，找出所有可能藏資料的位置"""
            info = {"status": r_status, "top_keys": list(jdata.keys()),
                    "stat": jdata.get("stat"), "date": jdata.get("date")}
            # 檢查 tables 陣列
            tables = jdata.get("tables") or []
            info["tables_count"] = len(tables)
            info["tables_summary"] = []
            all_rows = []
            for i, tbl in enumerate(tables):
                if not isinstance(tbl, dict):
                    info["tables_summary"].append({"i": i, "type": str(type(tbl))})
                    continue
                tbl_data = tbl.get("data") or tbl.get("rows") or []
                info["tables_summary"].append({
                    "i": i,
                    "title": tbl.get("title", ""),
                    "keys": list(tbl.keys()),
                    "data_rows": len(tbl_data),
                    "fields": tbl.get("fields", [])[:5],
                    "sample": tbl_data[0] if tbl_data else None,
                })
                all_rows.extend(tbl_data)
            # 也檢查根層的 data/data8/aaData
            for k in ["data", "data8", "data9", "aaData"]:
                v = jdata.get(k) or []
                if v:
                    info[f"root_{k}_count"] = len(v)
                    info[f"root_{k}_sample"] = v[0] if v else None
            info["total_rows_found"] = len(all_rows)
            return info

        # MI_INDEX
        try:
            r = await client.get(
                "https://www.twse.com.tw/exchangeReport/MI_INDEX",
                params={"response": "json", "type": "ALLBUT0999"},
            )
            jdata = r.json() if r.status_code == 200 else {}
            out["mi_index"] = _inspect("mi_index", r.status_code, jdata)
        except Exception as e:
            out["mi_index"] = {"error": str(e)}

        # MIS — 嘗試多個 session 入口，看哪個能取得 cookie
        MIS_BASE = "https://mis.twse.com.tw"
        UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        mis_entries = [
            f"{MIS_BASE}/",
            f"{MIS_BASE}/stock/",
            f"{MIS_BASE}/stock/fibest.jsp",
            f"{MIS_BASE}/stock/fibest.jsp?lang=zh_TW",
        ]
        out["mis_session"] = {}
        for entry_url in mis_entries:
            try:
                async with httpx.AsyncClient(timeout=12, follow_redirects=True, verify=False,
                                             headers={"User-Agent": UA}) as mis_client:
                    sess_r = await mis_client.get(entry_url,
                        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
                    cookies_got = dict(mis_client.cookies)
                    price_r = await mis_client.get(
                        f"{MIS_BASE}/stock/api/getStockInfo.jsp",
                        headers={"Accept": "application/json, text/javascript, */*; q=0.01",
                                 "Referer": entry_url,
                                 "X-Requested-With": "XMLHttpRequest"},
                        params={"ex_ch": "tse_2303.tw|tse_3481.tw|otc_5314.tw", "json": "1", "delay": "0",
                                "_": str(int(_time.time() * 1000))},
                    )
                    items = price_r.json().get("msgArray", []) if price_r.status_code == 200 else []
                    out["mis_session"][entry_url] = {
                        "session_status": sess_r.status_code,
                        "cookies": list(cookies_got.keys()),
                        "price_status": price_r.status_code,
                        "z_values": {i.get("c"): i.get("z") for i in items},
                    }
            except Exception as e:
                out["mis_session"][entry_url] = {"error": str(e)}

        # FinMind — 測試今日收盤 + 分鐘資料
        import datetime as _dt
        today_str = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).date().strftime("%Y-%m-%d")
        FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiYnVidXN0IiwiZW1haWwiOiJidWJ1c3RAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.LcLL157_bH6YbABE7JOlg0cAEwwzOV6GfJA6uK2cvIA"
        for fm_dataset in ["TaiwanStockPrice", "TaiwanStockPriceMinute"]:
            try:
                fm_r = await client.get(
                    "https://api.finmindtrade.com/api/v4/data",
                    params={"dataset": fm_dataset, "stock_id": "2303",
                            "start_date": today_str, "token": FINMIND_TOKEN},
                )
                fm_data = fm_r.json() if fm_r.status_code == 200 else {}
                fm_rows = fm_data.get("data", [])
                out[f"finmind_{fm_dataset}"] = {
                    "status": fm_r.status_code,
                    "rows": len(fm_rows),
                    "latest": fm_rows[-1] if fm_rows else None,
                    "msg": fm_data.get("msg", ""),
                }
            except Exception as e:
                out[f"finmind_{fm_dataset}"] = {"error": str(e)}

        # Fugle — 台灣券商即時 API（demo key 有限制但免費）
        for fugle_url in [
            "https://api.fugle.tw/realtime/v0.3/intraday/quote?symbolId=2303&apiToken=demo",
            "https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/2303",
        ]:
            try:
                fg_r = await client.get(fugle_url, headers={"X-API-KEY": "demo"})
                fg_data = fg_r.json() if fg_r.status_code == 200 else {}
                out[f"fugle_{fugle_url.split('/')[-1].split('?')[0]}"] = {
                    "status": fg_r.status_code,
                    "keys": list(fg_data.keys())[:10],
                    "sample": str(fg_data)[:300],
                }
            except Exception as e:
                out[f"fugle_{fugle_url.split('/')[-1].split('?')[0]}"] = {"error": str(e)}

    # 也順帶重置快取，強制下次重新抓
    global _PRICE_ALL_TS
    _PRICE_ALL_TS = 0.0
    out["cache_reset"] = True
    return out


@app.get("/")
def root():
    html_path = BASE_DIR / "dashboard.html"
    if html_path.exists():
        return FileResponse(html_path)
    return JSONResponse({"error": "dashboard.html not found"}, status_code=404)

@app.get("/warrant/")
def warrant_index():
    return FileResponse(str(WARRANT_FRONTEND / "index.html"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
