"""
backtest_service.py - 回測的資料 / 快取 / 背景批量（PLAN-BACKTEST §3.4、§3.5）

- fetch_adjusted_ohlcv：Yahoo 日 K（含 adjclose），當日記憶體快取
- MaskStore：策略訊號 mask 快取（SQLite WAL + busy_timeout；只有背景 worker 寫入，HTTP 只讀 + 記憶體 LRU）
- run_single：單股回測
- batch_request：批量回測（背景單一 worker + 進度輪詢；結果依策略/參數/出場/成本/日期快取）
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import httpx
import numpy as np
import pandas as pd

from backtest_engine import (ExitConfig, CostConfig, adjust_ohlcv, simulate,
                             compute_stats, summary_sentence)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_TW = timezone(timedelta(hours=8))


def tw_today() -> str:
    return datetime.now(_TW).strftime("%Y%m%d")


def _h(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
                        .encode("utf-8")).hexdigest()


# ── 價格資料 ──────────────────────────────────────────────────────────────────

_frames: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()
_frames_lock = threading.Lock()
_FRAMES_MAX = 350


def fetch_adjusted_ohlcv(stock_id: str, market: str = "twse", years: int = 5) -> Optional[pd.DataFrame]:
    """回傳已還原的 OHLCV（adjust_ohlcv 輸出），抓不到回 None。同一天同一支只抓一次。"""
    key = (stock_id, years, tw_today())
    with _frames_lock:
        if key in _frames:
            _frames.move_to_end(key)
            return _frames[key]
    from yahoo_price import _parse_yahoo_json
    suffixes = [".TW"] if market == "twse" else [".TWO", ".TW"]
    now = int(time.time())
    params = {"interval": "1d", "period1": now - int(years * 365.25 * 86400), "period2": now,
              "events": "div,splits"}
    df = None
    for host in ("query1", "query2"):
        for suffix in suffixes:
            try:
                r = httpx.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}",
                              params=params, headers={"User-Agent": _UA, "Accept": "application/json"},
                              timeout=12.0, verify=False, follow_redirects=True)
                r.raise_for_status()
                df = _parse_yahoo_json(r.json(), adjusted=True)
                if df is not None and len(df) >= 30:
                    break
            except Exception:
                df = None
        if df is not None and len(df) >= 30:
            break
    if df is None or len(df) < 30:
        return None
    adj = adjust_ohlcv(df)
    with _frames_lock:
        _frames[key] = adj
        while len(_frames) > _FRAMES_MAX:
            _frames.popitem(last=False)
    return adj


def data_hash(df: pd.DataFrame) -> str:
    """還原 OHLCV 的 hash：Yahoo 回溯修正或除權息讓還原價改變 → hash 不同 → mask 快取自動失效"""
    cols = df[["open", "high", "low", "close", "volume"]].astype(float).round(4).values
    m = hashlib.sha1(cols.tobytes())
    m.update("|".join(df["date"].astype(str)).encode())
    return m.hexdigest()


# ── 快取 ──────────────────────────────────────────────────────────────────────

def _default_db_path() -> Path:
    from chip_tracker_v2 import DATA_DIR
    return Path(DATA_DIR) / "backtest_cache.db"


class MaskStore:
    """訊號 mask / 批量結果快取。writer 只給背景 worker 用；HTTP 請求只讀。"""

    def __init__(self, db_path=None):
        self.db_path = str(db_path or _default_db_path())
        self._mem: "OrderedDict[str, list]" = OrderedDict()
        self._mem_lock = threading.Lock()
        c = self._conn()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS bt_mask (
                key TEXT PRIMARY KEY, mask TEXT NOT NULL, created TEXT);
            CREATE TABLE IF NOT EXISTS bt_batch (
                key TEXT PRIMARY KEY, result TEXT NOT NULL, created TEXT);
        """)
        c.commit()
        c.close()

    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=5.0)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        return c

    def _mem_put(self, key, mask):
        with self._mem_lock:
            self._mem[key] = mask
            self._mem.move_to_end(key)
            while len(self._mem) > 400:
                self._mem.popitem(last=False)

    def get_mask(self, key: str) -> Optional[list]:
        with self._mem_lock:
            if key in self._mem:
                return self._mem[key]
        try:
            c = self._conn()
            row = c.execute("SELECT mask FROM bt_mask WHERE key=?", (key,)).fetchone()
            c.close()
        except Exception:
            row = None
        if not row:
            return None
        mask = [ch == "1" for ch in row[0]]
        self._mem_put(key, mask)
        return mask

    def put_mask(self, key: str, mask: list, persist: bool):
        self._mem_put(key, mask)
        if persist:
            c = self._conn()
            c.execute("INSERT OR REPLACE INTO bt_mask(key, mask, created) VALUES (?,?,?)",
                      (key, "".join("1" if m else "0" for m in mask), tw_today()))
            c.commit()
            c.close()

    def get_batch(self, key: str) -> Optional[dict]:
        try:
            c = self._conn()
            row = c.execute("SELECT result FROM bt_batch WHERE key=?", (key,)).fetchone()
            c.close()
            return json.loads(row[0]) if row else None
        except Exception:
            return None

    def put_batch(self, key: str, result: dict):
        c = self._conn()
        c.execute("INSERT OR REPLACE INTO bt_batch(key, result, created) VALUES (?,?,?)",
                  (key, json.dumps(result, ensure_ascii=False), tw_today()))
        # 舊結果只留 7 天
        cutoff = (datetime.now(_TW) - timedelta(days=7)).strftime("%Y%m%d")
        c.execute("DELETE FROM bt_batch WHERE created < ?", (cutoff,))
        c.commit()
        c.close()


_store: Optional[MaskStore] = None
_store_lock = threading.Lock()


def get_store() -> MaskStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = MaskStore()
        return _store


# ── 訊號 ──────────────────────────────────────────────────────────────────────

def ma10_cross_mask(df: pd.DataFrame, signal: str = "fbd") -> list:
    """MA10 假跌破（fbd，昨收<MA10 今收>MA10）/ 假突破（fbr）— K 線圖黃色標記"""
    c = df["close"].values.astype(float)
    ma = pd.Series(c).rolling(10, min_periods=10).mean().values
    out = [False] * len(c)
    for i in range(10, len(c)):
        if np.isnan(ma[i - 1]) or np.isnan(ma[i]):
            continue
        out[i] = (c[i - 1] < ma[i - 1] and c[i] > ma[i]) if signal == "fbd" else \
                 (c[i - 1] > ma[i - 1] and c[i] < ma[i])
    return out


def strategy_mask(df: pd.DataFrame, stock_id: str, strategy: str, params: Optional[dict],
                  min_vol_ratio: float, store: Optional[MaskStore] = None, persist: bool = False,
                  compute_fn: Optional[Callable] = None) -> list:
    """策略 mask（最貴的部分），依 股票+策略+策略參數+還原資料 hash 快取"""
    if compute_fn is None:
        from scanner import strategy_signal_mask as compute_fn
    store = store or get_store()
    key = _h(["mask", stock_id, strategy, params or {}, float(min_vol_ratio or 0), data_hash(df)])
    mask = store.get_mask(key)
    if mask is not None and len(mask) == len(df):
        return mask
    mask = compute_fn(df, strategy, params=params, min_vol_ratio=min_vol_ratio)
    store.put_mask(key, mask, persist=persist)
    return mask


def market_filter_mask(df: pd.DataFrame, taiex_bull: int = 0, big_macd: int = 0) -> list:
    """回測面板的「市場篩選」：加權多頭排列（MA5>10>20>60）、週線大 MACD 多頭"""
    n = len(df)
    ok = [True] * n
    dates = [str(d) for d in df["date"].values]
    if taiex_bull:
        bull = set()
        try:
            from relationship.db import get_conn as _rel_conn
            rc = _rel_conn()
            rows = rc.execute("SELECT observation_date, taiex_close FROM market_daily "
                              "WHERE taiex_close IS NOT NULL ORDER BY observation_date ASC").fetchall()
            rc.close()
            if rows:
                s = pd.Series([r[1] for r in rows], index=[r[0] for r in rows])
                m5, m10, m20, m60 = (s.rolling(k).mean() for k in (5, 10, 20, 60))
                for d, a, b, c_, e in zip(s.index, m5, m10, m20, m60):
                    if not any(pd.isna(x) for x in (a, b, c_, e)) and a > b > c_ > e:
                        bull.add(str(d).replace("-", ""))
        except Exception:
            bull = None   # relationship DB 不存在 → 跳過此篩選
        if bull is not None:
            ok = [o and d in bull for o, d in zip(ok, dates)]
    if big_macd:
        try:
            idx = pd.to_datetime(pd.Series(dates), format="%Y%m%d")
            cs = pd.Series(df["close"].values.astype(float), index=idx)
            wk = cs.resample("W-FRI").last().dropna()
            dif = wk.ewm(span=12, adjust=False).mean() - wk.ewm(span=26, adjust=False).mean()
            dea = dif.ewm(span=9, adjust=False).mean()
            hist = dif - dea
            good = ((dif.reindex(idx, method="ffill") > 0) & (dea.reindex(idx, method="ffill") > 0)
                    & (hist.reindex(idx, method="ffill") > 0)).fillna(False).tolist()
            ok = [o and bool(g) for o, g in zip(ok, good)]
        except Exception:
            pass
    return ok


# ── 單股 ──────────────────────────────────────────────────────────────────────

def _market_of(stock_id: str) -> str:
    from yahoo_price import get_stock_list
    stocks = get_stock_list()
    row = stocks[stocks["stock_id"] == stock_id]
    return str(row.iloc[0]["type"]) if not row.empty else "twse"


def run_single(stock_id: str, strategy: str, signal: str, exit_cfg: ExitConfig,
               cost_cfg: CostConfig, all_params: dict, taiex_bull: int = 0, big_macd: int = 0,
               years: int = 5) -> Optional[dict]:
    from scanner import SHORT_STRATEGIES, STRATEGIES
    df = fetch_adjusted_ohlcv(stock_id, _market_of(stock_id), years)
    if df is None:
        return None
    if strategy:
        mask = strategy_mask(df, stock_id, strategy, all_params.get(strategy),
                             (all_params.get("_global") or {}).get("min_vol_ratio", 0.0))
        direction = "short" if strategy in SHORT_STRATEGIES else "long"
        name = STRATEGIES.get(strategy, strategy)
    else:
        mask = ma10_cross_mask(df, signal)
        direction = "short" if signal == "fbr" else "long"
        name = "MA10 假突破（看空）" if signal == "fbr" else "MA10 假跌破（看多）"
    if taiex_bull or big_macd:
        f = market_filter_mask(df, taiex_bull, big_macd)
        mask = [a and b for a, b in zip(mask, f)]
    trades, open_trade, info = simulate(df, mask, direction, exit_cfg, cost_cfg)
    stats = compute_stats(trades)
    stats["trades"] = trades
    return {
        "stock_id":      stock_id,
        "strategy":      strategy,
        "strategy_name": name,
        "direction":     direction,
        "exit_cfg":      exit_cfg.key(),
        "cost":          cost_cfg.roundtrip,
        "first_date":    info["first_date"],
        "last_date":     info["last_date"],
        "total_bars":    info["bars"],
        "buy_hold_return": info["buy_hold_return"],
        "pending_signal": info["pending_signal"],
        "blocked_entries": info["blocked_entries"],
        "open_trade":    open_trade,
        "summary":       summary_sentence(stats, info, cost_cfg.roundtrip),
        "result":        stats,
    }


# ── 批量 ──────────────────────────────────────────────────────────────────────

def select_universe(max_stocks: int = 100) -> tuple:
    """全市場清單中，近 20 日平均成交金額最大的 N 支（price_daily 快取）。回傳 ([(sid, name, market)], 來源說明)"""
    from yahoo_price import get_stock_list
    stocks = get_stock_list()
    meta = {r.stock_id: (r.stock_name, r.type) for r in stocks.itertuples(index=False)}
    picked = []
    try:
        from chip_tracker_v2 import DB_PATH
        c = sqlite3.connect(str(DB_PATH), timeout=5.0)
        dates = [r[0] for r in c.execute(
            "SELECT DISTINCT date FROM price_daily ORDER BY date DESC LIMIT 20").fetchall()]
        if dates:
            rows = c.execute(
                f"SELECT stock_id, AVG(close*volume) AS tv FROM price_daily "
                f"WHERE date IN ({','.join('?' * len(dates))}) AND close > 0 "
                f"GROUP BY stock_id ORDER BY tv DESC", dates).fetchall()
            picked = [r[0] for r in rows if r[0] in meta][:max_stocks]
        c.close()
    except Exception:
        picked = []
    if picked:
        src = f"近 20 日平均成交金額前 {len(picked)} 大"
    else:
        picked = [sid for sid in meta if len(sid) == 4][:max_stocks]
        src = f"成交金額資料不足，改取清單前 {len(picked)} 支"
    return [(sid, meta[sid][0], meta[sid][1]) for sid in picked], src


_batch = {"running": False, "key": None, "strategy": None, "progress": 0, "total": 0,
          "error": None, "started_at": None}
_batch_lock = threading.Lock()


def batch_key(strategy: str, params: Optional[dict], min_vol_ratio: float, exit_cfg: ExitConfig,
              cost_cfg: CostConfig, max_stocks: int) -> str:
    return _h(["batch", strategy, params or {}, float(min_vol_ratio or 0), exit_cfg.key(),
               cost_cfg.roundtrip, int(max_stocks), tw_today()])


def batch_request(strategy: str, exit_cfg: ExitConfig, cost_cfg: CostConfig, all_params: dict,
                  max_stocks: int = 100) -> dict:
    """查詢 / 啟動批量回測。快取命中 → done；同設定跑中 → running；其他 → 啟動背景 worker"""
    params = all_params.get(strategy)
    mvr = (all_params.get("_global") or {}).get("min_vol_ratio", 0.0)
    key = batch_key(strategy, params, mvr, exit_cfg, cost_cfg, max_stocks)
    store = get_store()
    cached = store.get_batch(key)
    if cached:
        return {"status": "done", "result": cached}
    with _batch_lock:
        if _batch["running"]:
            same = _batch["key"] == key
            return {"status": "running" if same else "busy", "strategy": _batch["strategy"],
                    "progress": _batch["progress"], "total": _batch["total"]}
        if _batch["key"] == key and _batch["error"]:
            err = _batch["error"]
            _batch["key"] = None
            return {"status": "error", "error": err}
        _batch.update(running=True, key=key, strategy=strategy, progress=0, total=0,
                      error=None, started_at=time.time())
    t = threading.Thread(target=_batch_worker,
                         args=(key, strategy, params, mvr, exit_cfg, cost_cfg, max_stocks),
                         daemon=True, name="backtest-batch")
    t.start()
    return {"status": "started", "progress": 0, "total": 0}


def _batch_worker(key, strategy, params, mvr, exit_cfg, cost_cfg, max_stocks):
    from concurrent.futures import ThreadPoolExecutor
    from scanner import SHORT_STRATEGIES, STRATEGIES
    store = get_store()
    try:
        universe, src = select_universe(max_stocks)
        with _batch_lock:
            _batch["total"] = len(universe)
        direction = "short" if strategy in SHORT_STRATEGIES else "long"
        all_trades, by_stock, failed = [], [], 0
        # 下載用 4 條 IO thread 預取；訊號計算/模擬在本 worker 單執行緒跑（不搶 CPU）
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = [pool.submit(fetch_adjusted_ohlcv, sid, mkt, 5) for sid, _, mkt in universe]
            for (sid, name, _), fut in zip(universe, futs):
                try:
                    df = fut.result()
                    if df is None:
                        failed += 1
                        continue
                    mask = strategy_mask(df, sid, strategy, params, mvr, store=store, persist=True)
                    trades, open_t, info = simulate(df, mask, direction, exit_cfg, cost_cfg)
                    st = compute_stats(trades)
                    for t in trades:
                        t["stock_id"] = sid
                    all_trades.extend(trades)
                    by_stock.append({
                        "stock_id": sid, "name": name,
                        "count": st.get("count", 0),
                        "win_rate": st.get("win_rate"),
                        "expectancy": st.get("expectancy"),
                        "total_return": st.get("total_return"),
                        "buy_hold_return": info["buy_hold_return"],
                        "max_loss": st.get("max_loss"),
                        "open": bool(open_t),
                        "pending_signal": info["pending_signal"],
                    })
                except Exception as e:
                    failed += 1
                    print(f"[BT-BATCH] {sid} 失敗: {type(e).__name__}: {e}")
                finally:
                    with _batch_lock:
                        _batch["progress"] += 1
        agg = compute_stats(all_trades)
        # 合併交易的權益曲線 / 累計報酬 / 回撤沒有意義（各股同時持有），批量不顯示
        for k in ("equity_curve", "total_return", "max_drawdown"):
            agg.pop(k, None)
        traded = [s for s in by_stock if s["count"]]
        bh = [s["buy_hold_return"] for s in by_stock if s["buy_hold_return"] is not None]
        strat_tot = [s["total_return"] for s in traded if s["total_return"] is not None]
        avg_bh = sum(bh) / len(bh) if bh else None
        avg_tot = sum(strat_tot) / len(strat_tot) if strat_tot else None
        if agg.get("count"):
            summary = (f"{len(traded)} 支股票共 {agg['count']} 筆交易，每筆平均 "
                       f"{agg['expectancy']*100:+.2f}%（已扣成本），勝率 {agg['win_rate']*100:.0f}%")
            if avg_bh is not None and avg_tot is not None:
                summary += ("，" + ("勝過" if avg_tot > avg_bh else "不如")
                            + f"同期買進持有（每股平均累計 {avg_tot*100:+.1f}% vs {avg_bh*100:+.1f}%）")
            if agg.get("low_sample"):
                summary += "；樣本太少，參考性低"
        else:
            summary = "這段期間沒有任何完成的交易"
        by_stock.sort(key=lambda s: (s["expectancy"] is None, -(s["expectancy"] or 0)))
        result = {
            "strategy": strategy, "strategy_name": STRATEGIES.get(strategy, strategy),
            "direction": direction, "universe": src, "total_scanned": len(universe),
            "computed": len(by_stock), "failed": failed, "stocks_with_trades": len(traded),
            "exit_cfg": exit_cfg.key(), "cost": cost_cfg.roundtrip,
            "avg_buy_hold_return": round(avg_bh, 5) if avg_bh is not None else None,
            "avg_strategy_total_return": round(avg_tot, 5) if avg_tot is not None else None,
            "summary": summary, "aggregate": agg, "by_stock": by_stock,
            "computed_at": datetime.now(_TW).strftime("%Y-%m-%d %H:%M"),
        }
        store.put_batch(key, result)
        with _batch_lock:
            _batch["running"] = False
    except Exception as e:
        print(f"[BT-BATCH] 失敗: {type(e).__name__}: {e}")
        with _batch_lock:
            _batch.update(running=False, error=f"{type(e).__name__}: {e}")


def batch_status() -> dict:
    with _batch_lock:
        return {k: _batch[k] for k in ("running", "strategy", "progress", "total", "error")}
