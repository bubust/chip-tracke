"""
sector/router.py — FastAPI routes for 產業輪動引擎
"""
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from .db import db
from .universe import fetch_and_build_mapping, is_initialized, get_all_sectors

log = logging.getLogger(__name__)
router = APIRouter()

_engine_running = False
_engine_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/sectors  — 所有產業最新狀態列表
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/sectors")
def api_get_sectors(sort_by: str = Query("rank5d", description="rank5d|rank20d|rank60d|rank_change|event")):
    """
    回傳所有產業的最新狀態，按 relative_rank_5d 排序（或依 sort_by 切換）。
    """
    with db() as conn:
        # 找最新日期
        row = conn.execute(
            "SELECT MAX(observation_date) AS d FROM sector_daily"
        ).fetchone()
        if not row or not row["d"]:
            return {"date": None, "sectors": []}
        latest_date = row["d"]

        rows = conn.execute(
            """
            SELECT sd.*, sm.sector_name
            FROM sector_daily sd
            LEFT JOIN sector_master sm ON sd.sector_id = sm.sector_id
            WHERE sd.observation_date = ?
            """,
            (latest_date,),
        ).fetchall()

    sectors = [dict(r) for r in rows]

    # 排序
    if sort_by == "rank5d":
        sectors.sort(key=lambda x: (x.get("relative_rank_5d") or 9999))
    elif sort_by == "rank20d":
        sectors.sort(key=lambda x: (x.get("relative_rank_20d") or 9999))
    elif sort_by == "rank60d":
        sectors.sort(key=lambda x: (x.get("relative_rank_60d") or 9999))
    elif sort_by == "rank_change":
        # 排名改善幅度最大在前（rank_change_5d 越大越好）
        sectors.sort(key=lambda x: -(x.get("rank_change_5d") or 0))
    elif sort_by == "event":
        # 有結構事件的排前面
        def event_key(x):
            ev = x.get("structure_event")
            priority = {"BREAKOUT": 0, "FALSE_BREAKDOWN": 1, "RECLAIM": 2, "BREAKDOWN": 3, "FALSE_BREAKOUT": 4}
            return priority.get(ev, 9)
        sectors.sort(key=event_key)

    return {"date": latest_date, "total": len(sectors), "sectors": sectors}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/sector/{sector_id}  — 單一產業詳細 + 歷史
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/sector/{sector_id}")
def api_get_sector(sector_id: str, days: int = Query(60, ge=1, le=365)):
    """
    回傳單一產業的最新狀態 + 最近 days 天歷史。
    """
    with db() as conn:
        # 最新一筆
        latest = conn.execute(
            """
            SELECT sd.*, sm.sector_name
            FROM sector_daily sd
            LEFT JOIN sector_master sm ON sd.sector_id = sm.sector_id
            WHERE sd.sector_id = ?
            ORDER BY sd.observation_date DESC
            LIMIT 1
            """,
            (sector_id,),
        ).fetchone()

        if not latest:
            raise HTTPException(status_code=404, detail=f"找不到產業：{sector_id}")

        # 歷史資料
        history_rows = conn.execute(
            """
            SELECT observation_date, index_level, return_ew_1d,
                   return_ew_5d, return_ew_20d, return_ew_60d,
                   ma20, ma60, ma120, trend_state,
                   relative_rank_5d, relative_rank_20d,
                   breadth_up_ratio, above_ma20_ratio
            FROM sector_daily
            WHERE sector_id = ?
            ORDER BY observation_date DESC
            LIMIT ?
            """,
            (sector_id, days),
        ).fetchall()

        # 近期結構事件
        events = conn.execute(
            """
            SELECT * FROM sector_events
            WHERE sector_id = ?
            ORDER BY observation_date DESC
            LIMIT 10
            """,
            (sector_id,),
        ).fetchall()

        # 該產業股票清單
        stocks = conn.execute(
            """
            SELECT stock_id FROM stock_sector_map
            WHERE sector_id = ?
            ORDER BY stock_id
            """,
            (sector_id,),
        ).fetchall()

    return {
        "latest": dict(latest),
        "history": [dict(r) for r in reversed(history_rows)],
        "events": [dict(r) for r in events],
        "stocks": [r["stock_id"] for r in stocks],
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/events  — 最近結構事件
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/events")
def api_get_events(limit: int = Query(50, ge=1, le=200)):
    """回傳最近結構事件列表"""
    try:
        with db() as conn:
            rows = conn.execute(
                """
                SELECT se.*, sm.sector_name
                FROM sector_events se
                LEFT JOIN sector_master sm ON se.sector_id = sm.sector_id
                ORDER BY se.observation_date DESC, se.event_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return {"events": [dict(r) for r in rows]}
    except Exception as e:
        log.warning(f"[sector] api_get_events 失敗: {e}")
        return {"events": []}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/status  — 引擎狀態
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/status")
def api_get_status():
    """回傳引擎狀態：幾個產業、最後更新日、是否初始化"""
    try:
        with db() as conn:
            sector_count = conn.execute(
                "SELECT COUNT(*) FROM sector_master"
            ).fetchone()[0]

            stock_count = conn.execute(
                "SELECT COUNT(DISTINCT stock_id) FROM stock_sector_map"
            ).fetchone()[0]

            latest_date_row = conn.execute(
                "SELECT MAX(observation_date) AS d FROM sector_daily"
            ).fetchone()
            latest_date = latest_date_row["d"] if latest_date_row else None

            last_run_row = conn.execute(
                "SELECT value FROM sector_meta WHERE key='last_run'"
            ).fetchone()
            last_run = last_run_row["value"] if last_run_row else None

            event_count = conn.execute(
                "SELECT COUNT(*) FROM sector_events"
            ).fetchone()[0]

        return {
            "initialized": sector_count > 0,
            "sector_count": sector_count,
            "stock_count": stock_count,
            "latest_date": latest_date,
            "last_run": last_run,
            "event_count": event_count,
            "engine_running": _engine_running,
        }
    except Exception as e:
        return {
            "initialized": False,
            "sector_count": 0,
            "stock_count": 0,
            "latest_date": None,
            "last_run": None,
            "event_count": 0,
            "engine_running": _engine_running,
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/refresh  — 觸發重新計算
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/refresh")
def api_refresh(background_tasks: BackgroundTasks, days_back: int = Query(30, ge=1, le=365)):
    """觸發產業引擎重新計算（背景執行）"""
    global _engine_running
    with _engine_lock:
        if _engine_running:
            return {"ok": False, "message": "引擎計算中，請稍候"}
        _engine_running = True

    def _run():
        global _engine_running
        try:
            from .prices import fetch_and_store_today, backfill
            from .db import db as _sdb, init_db as _sector_init_db
            from .engine import run_sector_engine
            _sector_init_db()
            with _sdb() as _sc:
                _cnt = _sc.execute("SELECT COUNT(DISTINCT date) FROM sector_stock_daily").fetchone()[0]
            if _cnt < 60:
                log.info(f"[sector] sector_stock_daily 只有 {_cnt} 天，開始補抓歷史...")
                backfill(days=130)
            else:
                fetch_and_store_today()
            run_sector_engine(days_back=days_back)
        except Exception as e:
            log.error(f"[sector] 引擎錯誤: {e}", exc_info=True)
        finally:
            _engine_running = False

    background_tasks.add_task(_run)
    return {"ok": True, "message": f"已開始計算（days_back={days_back}）"}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/init  — 觸發 sector mapping 初始化
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/init")
def api_init(background_tasks: BackgroundTasks):
    """觸發 FinMind 抓取 + sector mapping 建立（背景執行）"""

    def _init():
        try:
            counts = fetch_and_build_mapping()
            log.info(f"[sector] 初始化完成：{len(counts)} 個產業")
        except Exception as e:
            log.error(f"[sector] 初始化失敗: {e}", exc_info=True)

    background_tasks.add_task(_init)
    return {"ok": True, "message": "已開始從 FinMind 建立產業對照表"}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/sectors/history  — 多產業歷史指數（供 chart 用）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/sectors/history")
def api_sectors_history(
    sector_ids: str = Query("", description="逗號分隔的 sector_id"),
    days: int = Query(60, ge=1, le=365),
):
    """
    回傳多個產業的歷史指數（供前端畫多線圖）。
    """
    if not sector_ids.strip():
        return {"series": {}}

    ids = [s.strip() for s in sector_ids.split(",") if s.strip()]
    result = {}
    with db() as conn:
        for sid in ids:
            rows = conn.execute(
                """
                SELECT observation_date, index_level, return_ew_1d,
                       trend_state, relative_rank_5d
                FROM sector_daily
                WHERE sector_id = ?
                ORDER BY observation_date DESC
                LIMIT ?
                """,
                (sid, days),
            ).fetchall()
            result[sid] = [dict(r) for r in reversed(rows)]

    return {"series": result}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/sector/{sector_id}/stocks  — 產業內個股近況
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/sector/{sector_id}/stocks")
def api_sector_stocks(sector_id: str):
    """回傳產業內各股近況：股號、股名、現價、成交量（張）、近20日漲幅"""
    from chip_tracker_v2 import DB_PATH

    with db() as sconn:
        stock_rows = sconn.execute(
            "SELECT stock_id FROM stock_sector_map WHERE sector_id = ? ORDER BY stock_id",
            (sector_id,),
        ).fetchall()

    stock_ids = [r["stock_id"] for r in stock_rows]
    if not stock_ids:
        return {"stocks": []}

    # 從 stocks.csv 取得正確股名（price_daily.name 在 Yahoo 路徑為 NULL）
    try:
        from yahoo_price import get_stock_list as _gsl
        _stk = _gsl()
        _name_map = dict(zip(_stk["stock_id"], _stk["stock_name"]))
    except Exception:
        _name_map = {}

    try:
        cache_conn = sqlite3.connect(str(DB_PATH))
        cache_conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" * len(stock_ids))
        # 取最近 25 個交易日，足以算 20 日漲幅
        rows = cache_conn.execute(f"""
            SELECT date, stock_id, name, close, volume
            FROM price_daily
            WHERE stock_id IN ({placeholders})
              AND date IN (
                SELECT DISTINCT date FROM price_daily
                ORDER BY date DESC LIMIT 25
              )
            ORDER BY stock_id, date DESC
        """, stock_ids).fetchall()
        cache_conn.close()
    except Exception as e:
        log.error(f"[sector] stocks DB read: {e}")
        return {"stocks": [{"stock_id": sid, "name": sid} for sid in stock_ids]}

    # 按股票整理
    from collections import defaultdict
    price_map: dict = defaultdict(list)
    for r in rows:
        price_map[r["stock_id"]].append(dict(r))

    result = []
    for sid in stock_ids:
        days_data = price_map.get(sid, [])   # 已依 date DESC 排列
        if not days_data:
            result.append({"stock_id": sid, "name": _name_map.get(sid, sid),
                           "close": None, "volume": None, "return_20d": None})
            continue
        latest   = days_data[0]
        close    = latest.get("close")
        volume   = latest.get("volume")
        name     = _name_map.get(sid) or latest.get("name") or sid
        ret_20d  = None
        if len(days_data) >= 20 and close:
            old = days_data[19].get("close")
            if old and old > 0:
                ret_20d = round((close / old - 1) * 100, 2)
        result.append({
            "stock_id":  sid,
            "name":      name,
            "close":     round(float(close), 2) if close else None,
            "volume":    int(volume) if volume else None,
            "return_20d": ret_20d,
        })

    # 依 20 日漲幅由強到弱排序
    result.sort(key=lambda x: (x["return_20d"] is None, -(x["return_20d"] or 0)))
    return {"stocks": result}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/sector/{sector_id}/correlation  — 產業內股票相關係數
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/sector/{sector_id}/correlation")
def api_sector_correlation(
    sector_id: str,
    days: int = Query(60, ge=20, le=120),
    threshold: float = Query(0.5, ge=0.0, le=1.0),
):
    """
    計算產業內股票兩兩 Pearson 相關係數（依日報酬率），
    回傳節點、邊、最強正相關、最強負相關。
    """
    from chip_tracker_v2 import DB_PATH  # cache.db 路徑

    # 1. 取出該產業的股票清單與產業名稱
    with db() as sconn:
        sector_row = sconn.execute(
            "SELECT sector_name FROM sector_master WHERE sector_id = ?",
            (sector_id,),
        ).fetchone()
        if not sector_row:
            raise HTTPException(status_code=404, detail=f"找不到產業：{sector_id}")
        sector_name = sector_row["sector_name"]

        stock_rows = sconn.execute(
            "SELECT stock_id FROM stock_sector_map WHERE sector_id = ?",
            (sector_id,),
        ).fetchall()

    stock_ids = [r["stock_id"] for r in stock_rows]
    if len(stock_ids) < 2:
        return {
            "sector_id": sector_id,
            "sector_name": sector_name,
            "days": days,
            "nodes": [],
            "edges": [],
            "top_positive": [],
            "top_negative": [],
        }

    # 2. 從 cache.db 取 price_daily
    cache_path = str(DB_PATH)
    try:
        cache_conn = sqlite3.connect(cache_path)
        placeholders = ",".join("?" * len(stock_ids))
        query = f"""
            SELECT date, stock_id, close, name
            FROM price_daily
            WHERE stock_id IN ({placeholders})
            ORDER BY date DESC
        """
        df = pd.read_sql_query(query, cache_conn, params=stock_ids)
        cache_conn.close()
    except Exception as e:
        log.error(f"[sector] correlation DB read failed: {e}")
        raise HTTPException(status_code=500, detail=f"無法讀取價格資料：{e}")

    if df.empty:
        return {
            "sector_id": sector_id,
            "sector_name": sector_name,
            "days": days,
            "nodes": [],
            "edges": [],
            "top_positive": [],
            "top_negative": [],
        }

    # 取最近 days 個交易日
    all_dates = sorted(df["date"].unique(), reverse=True)
    use_dates = set(all_dates[:days])
    df = df[df["date"].isin(use_dates)]

    # pivot: index=date, columns=stock_id, values=close
    pivot = df.pivot_table(index="date", columns="stock_id", values="close", aggfunc="last")
    pivot = pivot.sort_index()

    # 取名稱對照
    name_map = df.groupby("stock_id")["name"].last().to_dict()

    # 日報酬率
    returns = pivot.pct_change().dropna(how="all")

    # 計算 60d 累積報酬
    total_return_map: dict = {}
    for sid in pivot.columns:
        if sid in pivot.columns:
            prices = pivot[sid].dropna()
            if len(prices) >= 2:
                total_return_map[sid] = float(prices.iloc[-1] / prices.iloc[0] - 1)

    # 只保留有足夠資料的股票
    valid_stocks = [c for c in returns.columns if returns[c].notna().sum() >= max(10, days // 2)]
    if len(valid_stocks) < 2:
        return {
            "sector_id": sector_id,
            "sector_name": sector_name,
            "days": days,
            "nodes": [{"id": sid, "name": name_map.get(sid, sid), "return_60d": total_return_map.get(sid)}
                      for sid in stock_ids],
            "edges": [],
            "top_positive": [],
            "top_negative": [],
        }

    returns_valid = returns[valid_stocks]
    corr_matrix = returns_valid.corr(method="pearson")

    # 建立節點
    nodes = []
    for sid in valid_stocks:
        nodes.append({
            "id": sid,
            "name": name_map.get(sid, sid),
            "return_60d": round(total_return_map.get(sid, 0), 4),
        })

    # 建立邊（|corr| >= threshold）
    edges = []
    seen = set()
    for i, a in enumerate(valid_stocks):
        for j, b in enumerate(valid_stocks):
            if i >= j:
                continue
            pair = (a, b)
            if pair in seen:
                continue
            seen.add(pair)
            v = corr_matrix.loc[a, b]
            if pd.isna(v):
                continue
            if abs(v) >= threshold:
                edges.append({"source": a, "target": b, "corr": round(float(v), 4)})

    # top_positive / top_negative
    all_pairs = []
    for e in edges:
        all_pairs.append({"a": e["source"], "b": e["target"], "corr": e["corr"]})

    all_pairs.sort(key=lambda x: x["corr"], reverse=True)
    top_positive = all_pairs[:5]
    top_negative = sorted(all_pairs, key=lambda x: x["corr"])[:5]
    top_negative = [p for p in top_negative if p["corr"] < 0]

    return {
        "sector_id": sector_id,
        "sector_name": sector_name,
        "days": days,
        "nodes": nodes,
        "edges": edges,
        "top_positive": top_positive,
        "top_negative": top_negative,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/correlation-scan  — 全產業關聯掃描（每個族群的最強關聯股票對）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/correlation-scan")
def api_correlation_scan(
    days: int = Query(60, ge=20, le=120),
    threshold: float = Query(0.7, ge=0.0, le=1.0),
    top_n: int = Query(5, ge=1, le=20),
):
    """
    掃描所有產業，回傳每個族群內關聯係數最強的股票對清單。
    """
    from chip_tracker_v2 import DB_PATH

    # 1. 取出所有產業
    with db() as sconn:
        sector_rows = sconn.execute(
            "SELECT sector_id, sector_name FROM sector_master ORDER BY sector_name"
        ).fetchall()
        # 取出全部 stock_sector_map
        all_maps = sconn.execute(
            "SELECT sector_id, stock_id FROM stock_sector_map"
        ).fetchall()

    if not sector_rows:
        return {"days": days, "threshold": threshold, "sectors": []}

    # 建立 sector -> [stock_ids] 對照
    from collections import defaultdict
    sector_stocks: dict = defaultdict(list)
    for row in all_maps:
        sector_stocks[row["sector_id"]].append(row["stock_id"])

    all_stock_ids = list({r["stock_id"] for r in all_maps})
    if not all_stock_ids:
        return {"days": days, "threshold": threshold, "sectors": []}

    # 2. 一次性讀取所有股票的價格（避免多次 DB 查詢）
    try:
        cache_conn = sqlite3.connect(str(DB_PATH))
        placeholders = ",".join("?" * len(all_stock_ids))
        df_all = pd.read_sql_query(
            f"SELECT date, stock_id, close, name FROM price_daily WHERE stock_id IN ({placeholders}) ORDER BY date DESC",
            cache_conn,
            params=all_stock_ids,
        )
        cache_conn.close()
    except Exception as e:
        log.error(f"[sector] correlation-scan DB read failed: {e}")
        raise HTTPException(status_code=500, detail=f"無法讀取價格資料：{e}")

    if df_all.empty:
        return {"days": days, "threshold": threshold, "sectors": []}

    # 取最近 days 個交易日
    all_dates = sorted(df_all["date"].unique(), reverse=True)
    use_dates = set(all_dates[:days])
    df_all = df_all[df_all["date"].isin(use_dates)]

    name_map_global = df_all.groupby("stock_id")["name"].last().to_dict()

    # 3. 對每個產業計算相關係數
    results = []
    for sec_row in sector_rows:
        sector_id = sec_row["sector_id"]
        sector_name = sec_row["sector_name"]
        stock_ids = sector_stocks.get(sector_id, [])
        if len(stock_ids) < 2:
            continue

        df_sec = df_all[df_all["stock_id"].isin(stock_ids)]
        if df_sec.empty:
            continue

        pivot = df_sec.pivot_table(index="date", columns="stock_id", values="close", aggfunc="last").sort_index()
        returns = pivot.pct_change().dropna(how="all")
        valid = [c for c in returns.columns if returns[c].notna().sum() >= max(10, days // 2)]
        if len(valid) < 2:
            continue

        corr_matrix = returns[valid].corr(method="pearson")

        # 找出超過 threshold 的股票對
        pairs = []
        for i in range(len(valid)):
            for j in range(i + 1, len(valid)):
                a, b = valid[i], valid[j]
                v = corr_matrix.loc[a, b]
                if pd.isna(v) or abs(v) < threshold:
                    continue
                pairs.append({
                    "stock1_id":   a,
                    "stock1_name": name_map_global.get(a, a),
                    "stock2_id":   b,
                    "stock2_name": name_map_global.get(b, b),
                    "corr":        round(float(v), 3),
                })

        if not pairs:
            continue

        pairs.sort(key=lambda x: x["corr"], reverse=True)
        results.append({
            "sector_id":   sector_id,
            "sector_name": sector_name,
            "stock_count": len(stock_ids),
            "pair_count":  len(pairs),
            "pairs":       pairs[:top_n],
        })

    # 依 pair_count 由多到少排序（關聯最密集的產業優先）
    results.sort(key=lambda x: x["pair_count"], reverse=True)

    return {
        "days":      days,
        "threshold": threshold,
        "sectors":   results,
    }
