"""B80 加權成交量資料（PLAN-B80 §5.1）：Yahoo ^TWII 5 分 K 沒有量、鉅亨 TSE01 開收盤那幾根不準 → 用證交所
- vol5：MI_5MINS（每 5 秒累計成交金額，百萬元）→ 每根 5 分 K 的成交金額（元，跟鉅亨同單位）
  累計(T)＝時間 ≤T 的最後一列；當天起點累計＝0（開盤撮合在 09:00:05 那列 → 第一根含開盤撮合）；
  每根（開始 s）＝累計(s+5 分)−累計(s)；13:30:00 收盤撮合算進 13:25 那根（跟 futdata.agg_bars 一致）；相減 <0 不存
- turnover：FMTQIK 每日市場成交資訊（成交金額元、成交股數），2000 年起都有
- 回補只有一個工作執行緒（模組鎖＋running 旗標）；使用者開頁面不會觸發，只有開機與排程；請求間隔 3.2 秒，
  失敗 30 秒後重試一次、再失敗這次就停（等下一個排程）
純函式（parse_*、bars_from_cum、*_fracs）不碰網路"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from . import data as D
from . import futdata as FD

log = logging.getLogger(__name__)
MI5_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_5MINS"
FMTQIK_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
GAP = 3.2
KEEP_DAYS = 45
DAY_BARS = 54                    # 09:00～13:25 開始的 5 分 K
TURNOVER_START = (2020, 1)       # 正式站回補起點（週 K 260 週夠用）
MI5_TTL = 100                    # 盤中今天 MI_5MINS 快取秒數
_lock = threading.Lock()
_state = {"running": False, "last": None, "remain": None}
_today = {"t": 0.0, "day": None, "data": None}


def _get(url: str, params: dict, get=None, timeout: float = 25):
    if get is not None:
        return get(url, params)
    r = httpx.get(url, params=params, headers={**D.UA, "Referer": "https://www.twse.com.tw/"}, timeout=timeout)
    return r.json()


def _num(s) -> Optional[float]:
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ── MI_5MINS → 5 分 K 成交金額 ───────────────────────────────────────────────
def parse_mi5(j: dict) -> list:
    """→ [(當天秒數, 累計成交金額 元)]（時間升冪）；stat≠OK 或沒有資料 → []"""
    if not isinstance(j, dict) or j.get("stat") != "OK":
        return []
    out = []
    for row in j.get("data") or []:
        try:
            hh, mm, ss = (int(x) for x in str(row[0]).strip().split(":"))
            amt = _num(row[7])
        except Exception:     # noqa: BLE001
            continue
        if amt is not None:
            out.append((hh * 3600 + mm * 60 + ss, amt * 1e6))
    out.sort()
    return out


def bars_from_cum(day: date, cum: list, upto_s: Optional[int] = None) -> tuple:
    """累計 → ([(5 分 K 開始 epoch, 金額)] 收完的, (開始 epoch, 金額, 最後一列秒數) 進行中或 None)。
    upto_s：資料到當天第幾秒（盤中）；None＝整天（收盤後）"""
    if not cum:
        return [], None
    last_s = cum[-1][0] if upto_s is None else min(upto_s, cum[-1][0])
    j = 0
    done, part = [], None
    base = datetime(day.year, day.month, day.day, tzinfo=FD.TW).timestamp()

    def cum_at(T):
        nonlocal j
        while j + 1 < len(cum) and cum[j + 1][0] <= T:
            j += 1
        return cum[j][1] if cum[j][0] <= T else 0.0
    prev = 0.0                                   # 當天起點累計＝0
    for k in range(DAY_BARS):
        s = 9 * 3600 + k * 300
        e = s + 300 if k < DAY_BARS - 1 else 13 * 3600 + 30 * 60      # 最後一根含 13:30:00 收盤撮合
        if e <= last_s or (k == DAY_BARS - 1 and last_s >= e):
            cur = cum_at(e)
            v = cur - prev
            if v >= 0:
                done.append((int(base + s), v))
            prev = cur
        else:
            if last_s > s:
                cur = cum_at(last_s)
                v = cur - prev
                if v >= 0:
                    part = (int(base + s), v, last_s)
            break
    return done, part


def save_vol5(sym: str, rows: list, src: str) -> int:
    if not rows:
        return 0
    with D.db() as c:
        c.executemany("INSERT INTO vol5(sym,ts,v,src) VALUES(?,?,?,?) ON CONFLICT(sym,ts) DO UPDATE SET v=excluded.v,src=excluded.src",
                      [(sym, int(ts), float(v), src) for ts, v in rows])
    return len(rows)


def load_vol5(sym: str, since_ts: int = 0) -> dict:
    with D.db() as c:
        rs = c.execute("SELECT ts, v FROM vol5 WHERE sym=? AND ts>=? ORDER BY ts", (sym, int(since_ts))).fetchall()
    return {int(r[0]): float(r[1]) for r in rs}


def count_vol5_day(sym: str, day: date) -> int:
    s = datetime(day.year, day.month, day.day, 9, 0, tzinfo=FD.TW).timestamp()
    with D.db() as c:
        return c.execute("SELECT COUNT(*) FROM vol5 WHERE sym=? AND ts>=? AND ts<?", (sym, int(s), int(s + 5 * 3600))).fetchone()[0]


def update_day(day: date, get=None) -> int:
    """抓某一天（收盤後）的 MI_5MINS 存 vol5；回傳存了幾根"""
    j = _get(MI5_URL, {"date": day.strftime("%Y%m%d"), "response": "json"}, get)
    done, _ = bars_from_cum(day, parse_mi5(j))
    n = save_vol5("TWII", done, "TWSE_MI5")
    D.mark("twse_mi5", True)
    return n


def _twii_days(days: int) -> list:
    since = int(time.time() - days * 86400)
    return sorted({FD.tw_dt(r[0]).date() for r in FD.load_bars5("TWII", since)})


def backfill_twii_vol(days: int = KEEP_DAYS, max_days: Optional[int] = None, get=None, sleep=True) -> int:
    """近 days 天、bars5 有加權 K 棒、vol5 不到 50 根的日子 → 抓 MI_5MINS（新的先抓）；一次最多 max_days 天"""
    if not _lock.acquire(blocking=False):
        return 0
    _state["running"] = True
    n = 0
    try:
        now = D.tw_now()
        today = now.date()
        todo = [d for d in _twii_days(days) if (d < today or (now.hour, now.minute) >= (13, 31)) and count_vol5_day("TWII", d) < 50]
        todo.sort(reverse=True)
        cap = len(todo) if max_days is None else max_days
        for k, d in enumerate(todo[:cap]):
            ok = False
            for attempt in range(2):
                try:
                    n += update_day(d, get)
                    ok = True
                    break
                except Exception as e:     # noqa: BLE001
                    D.mark("twse_mi5", False, repr(e))
                    if attempt == 0 and sleep:
                        time.sleep(30)
            if not ok:
                log.warning(f"[vol] MI_5MINS {d} 連續失敗，這次先停")
                break
            if sleep and k < cap - 1:
                time.sleep(GAP)
        remain = max(0, len(todo) - cap)
        _state["remain"] = remain
        if remain:
            log.info(f"[vol] 加權盤中量還差 {remain} 天，下次排程接著補")
        return n
    finally:
        _state.update(running=False, last=D.tw_now().strftime("%Y-%m-%d %H:%M:%S"))
        _lock.release()


def mi5_today(get=None, now_ts: Optional[float] = None) -> Optional[dict]:
    """盤中今天：{done: {ts: 金額}, part: (ts, 金額, 秒數) 或 None, cum: 今天累計, s: 資料到第幾秒}；快取 100 秒；收完的順便存 vol5"""
    now_ts = time.time() if now_ts is None else now_ts
    day = FD.tw_dt(now_ts).date()
    if _today["data"] is not None and _today["day"] == day and now_ts - _today["t"] < MI5_TTL:
        return _today["data"]
    try:
        j = _get(MI5_URL, {"response": "json"}, get, timeout=8)      # 盤中在快照鎖裡面跑，不要卡太久
        cum = parse_mi5(j)
        if not cum:
            return None
        done, part = bars_from_cum(day, cum)
        save_vol5("TWII", done, "TWSE_MI5")
        out = {"done": dict(done), "part": part, "cum": cum[-1][1], "s": cum[-1][0]}
        _today.update(t=now_ts, day=day, data=out)
        D.mark("twse_mi5_live", True)
        return out
    except Exception as e:     # noqa: BLE001
        D.mark("twse_mi5_live", False, repr(e))
        return None


# ── 日 K 盤中預估：過去各天「同一時間累計占全天」 ─────────────────────────────
def day_fracs(per_day: dict, elapsed_s: float) -> list:
    """per_day：{交易日: [(這根開始距離開盤幾秒, 量)]}（完整的天）→ 每天開盤後 elapsed_s 秒時累計占全天的比例"""
    out = []
    for _, rows in per_day.items():
        tot = sum(v for _, v in rows)
        if tot <= 0:
            continue
        acc = sum(v for s, v in rows if s + 300 <= elapsed_s)
        part = [(s, v) for s, v in rows if s < elapsed_s < s + 300]
        if part:                                 # 走到一半的那根照比例
            s, v = part[0]
            acc += v * (elapsed_s - s) / 300.0
        out.append(acc / tot)
    return out


# ── FMTQIK 每日成交金額 ──────────────────────────────────────────────────────
def parse_fmtqik(j: dict) -> list:
    """→ [(YYYY-MM-DD, 成交金額 元, 成交股數)]；日期是民國 115/10/22"""
    out = []
    if not isinstance(j, dict) or j.get("stat") != "OK":
        return out
    for row in j.get("data") or []:
        try:
            y, m, d = str(row[0]).strip().split("/")
            amt, sh = _num(row[2]), _num(row[1])
            if amt is None:
                continue
            yy = int(y) + 1911 if int(y) < 1900 else int(y)      # 民國年；萬一改成西元年也不會錯（審查 Gemini F3）
            out.append((f"{yy:04d}-{int(m):02d}-{int(d):02d}", amt, sh))
        except Exception:     # noqa: BLE001
            continue
    return out


def save_turnover(rows: list, src: str = "TWSE_FMTQIK") -> int:
    if not rows:
        return 0
    with D.db() as c:
        c.executemany("INSERT INTO turnover(date,amt,shares,src) VALUES(?,?,?,?) ON CONFLICT(date) DO UPDATE SET "
                      "amt=excluded.amt,shares=excluded.shares,src=excluded.src", [(d, a, s, src) for d, a, s in rows])
    return len(rows)


def load_turnover() -> dict:
    with D.db() as c:
        return {r[0]: float(r[1]) for r in c.execute("SELECT date, amt FROM turnover ORDER BY date").fetchall()}


def fetch_month(y: int, m: int, get=None) -> list:
    return parse_fmtqik(_get(FMTQIK_URL, {"date": f"{y:04d}{m:02d}01", "response": "json"}, get))


def update_turnover(months: int = 1, get=None, sleep=True) -> int:
    """最近 months 個月（含本月）重抓"""
    today = D.tw_now().date()
    n = 0
    for k in range(months):
        y, m = today.year, today.month - k
        while m <= 0:
            y, m = y - 1, m + 12
        try:
            n += save_turnover(fetch_month(y, m, get))
            D.mark("twse_fmtqik", True)
        except Exception as e:     # noqa: BLE001
            D.mark("twse_fmtqik", False, repr(e))
        if sleep and k < months - 1:
            time.sleep(GAP)
    return n


def backfill_turnover(start: tuple = TURNOVER_START, get=None, sleep=True) -> int:
    """start 起每個月，資料庫裡那個月不到 15 天的才抓（本月、上個月一律重抓）"""
    have: dict = {}
    for d in load_turnover():
        have[d[:7]] = have.get(d[:7], 0) + 1
    today = D.tw_now().date()
    y, m = start
    todo = []
    while (y, m) <= (today.year, today.month):
        ym = f"{y:04d}-{m:02d}"
        recent = (today.year * 12 + today.month) - (y * 12 + m) <= 1
        if recent or have.get(ym, 0) < 15:
            todo.append((y, m))
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    n = 0
    for k, (y, m) in enumerate(todo):
        ok = False
        for attempt in range(2):
            try:
                n += save_turnover(fetch_month(y, m, get))
                ok = True
                break
            except Exception as e:     # noqa: BLE001
                D.mark("twse_fmtqik", False, repr(e))
                if attempt == 0 and sleep:
                    time.sleep(30)
        if not ok:
            log.warning(f"[vol] FMTQIK {y}-{m:02d} 連續失敗，這次先停")
            break
        if sleep and k < len(todo) - 1:
            time.sleep(GAP)
    if n:
        D.mark("twse_fmtqik", True)
    return n


def ensure(background: bool = True) -> bool:
    """開機：加權盤中量（近 45 天）＋每日成交金額（2020 起）缺的才補；一個執行緒依序跑"""
    if _state["running"]:
        return False

    def _run():
        try:
            backfill_twii_vol()
            backfill_turnover()
        except Exception as e:     # noqa: BLE001
            log.warning(f"[vol] 回補失敗：{e}")
    if background:
        threading.Thread(target=_run, daemon=True, name="vol-backfill").start()
    else:
        _run()
    return True


def status() -> dict:
    with D.db() as c:
        v = c.execute("SELECT COUNT(*) n, MAX(ts) mx FROM vol5 WHERE sym='TWII'").fetchone()
        t = c.execute("SELECT COUNT(*) n, MAX(date) mx FROM turnover").fetchone()
    return {"vol5": {"n": v[0], "last": FD.tw_dt(v[1]).strftime("%Y-%m-%d %H:%M") if v[1] else None},
            "turnover": {"n": t[0], "last": t[1]}, "backfill": dict(_state)}
