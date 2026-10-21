"""重工作排隊＋背景工作紀錄（PLAN-B77 A4、D3）

正式站只有 512MB：權證合約、產業同步、全市場掃描、全系統更新同時跑會被系統砍掉（OOM）。
- heavy(name)：同一時間只跑一個重工作，其他排隊；同一個執行緒可以重入（全系統更新裡面呼叫庫藏股更新）
  只包「工作的最外層入口」，不要包在 worker 執行緒裡跑的函式；不能在 asyncio event loop 上等鎖
- 每個重工作記一筆到 chip_data/job_log.jsonl：開始／結束、秒數、成功失敗、尖峰記憶體、排隊秒數
- 開機記一筆 boot；上一次有 start 沒 end＝跑到一半伺服器重開（多半是記憶體不夠）
"""
from __future__ import annotations

import asyncio
import gc
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "chip_data"
LOG_FILE = DATA_DIR / "job_log.jsonl"
TMP_DIR = DATA_DIR / "tmp"
KEEP_LINES = 300
WAIT_LIMIT = 3600            # 排隊最多等 60 分鐘，逾時就不跑（審查 Groq F1）

_lock = threading.RLock()
_log_lock = threading.Lock()
_state = {"current": None, "since": None, "depth": 0}
_last_ok: dict = {}          # name → 最近一次成功結束的 time.time()（排程版判斷「剛做過」用）


class QueueTimeout(Exception):
    pass


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def rss_mb():
    """目前這個程式用的記憶體（MB）；Linux 讀 /proc，其他平台用 psutil（沒有就 None）"""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024)
    except Exception:
        pass
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1e6)
    except Exception:
        return None


def meminfo() -> dict:
    """機器記憶體（MB）：total／available／swap_total／swap_used；非 Linux 回空"""
    out = {}
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            kv = {ln.split(":")[0]: int(ln.split()[1]) for ln in f if ":" in ln}
        out = {"total": round(kv.get("MemTotal", 0) / 1024), "available": round(kv.get("MemAvailable", 0) / 1024),
               "swap_total": round(kv.get("SwapTotal", 0) / 1024),
               "swap_used": round((kv.get("SwapTotal", 0) - kv.get("SwapFree", 0)) / 1024)}
    except Exception:
        pass
    return out


def release_memory():
    """把釋放掉的記憶體還給系統：gc＋glibc malloc_trim（非 Linux／不是 glibc 就只做 gc）"""
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def _append(rec: dict):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with _log_lock, open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def event(kind: str, **kw):
    """記一筆非重工作的事件（boot、catchup、略過…）"""
    _append({"t": _now(), "kind": kind, **kw})


def _in_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


@contextmanager
def heavy(name: str, wait_limit: float = WAIT_LIMIT):
    """重工作排隊。用法：with jobs.heavy("warrant_ingest"): ingest_contracts()"""
    if _in_event_loop():
        # 在 event loop 上等鎖會讓整個網站卡住（審查 Gemini F2）
        raise RuntimeError(f"jobs.heavy({name}) 不能在 asyncio event loop 上呼叫，先開背景執行緒")
    t_wait = time.time()
    if not _lock.acquire(timeout=wait_limit):
        event("skip", name=name, reason=f"排隊超過 {int(wait_limit / 60)} 分鐘（{_state['current']} 還在跑）")
        raise QueueTimeout(name)
    waited = round(time.time() - t_wait, 1)
    nested = _state["depth"] > 0
    _state["depth"] += 1
    if nested:                       # 同一個執行緒重入（例如全系統更新裡的庫藏股）：不另外記、不另外取樣
        try:
            yield
        finally:
            _state["depth"] -= 1
            _lock.release()
        return
    _state.update(current=name, since=_now())
    t0 = time.time()
    r0 = rss_mb()
    peak = [r0 or 0]
    stop = threading.Event()

    def _sample():
        while not stop.wait(0.5):
            r = rss_mb()
            if r and r > peak[0]:
                peak[0] = r
    threading.Thread(target=_sample, daemon=True, name=f"rss-{name}").start()
    _append({"t": _now(), "kind": "start", "name": name, "rss": r0, "waited": waited})
    ok, err = True, None
    try:
        yield
    except Exception as e:      # noqa: BLE001
        ok, err = False, f"{type(e).__name__}: {e}"[:300]
        raise
    finally:
        stop.set()
        release_memory()
        rec = {"t": _now(), "kind": "end", "name": name, "sec": round(time.time() - t0, 1), "ok": ok,
               "rss_before": r0, "rss_peak": peak[0] or None, "rss_after": rss_mb(), "waited": waited}
        if err:
            rec["error"] = err
        _append(rec)
        if ok:
            _last_ok[name] = time.time()
        _state.update(current=None, since=None)
        _state["depth"] -= 1
        _lock.release()


def run_heavy(name: str, fn, *a, **kw):
    """heavy() 的函式版：排隊逾時回 None（排程用，不丟例外）"""
    try:
        with heavy(name):
            return fn(*a, **kw)
    except QueueTimeout:
        log.warning(f"[jobs] {name} 排隊逾時，這次略過")
        return None


def recently_ok(name: str, seconds: float = 5400) -> bool:
    """name 在 seconds 秒內成功做過（排程版：全系統更新剛做過同一項就跳過）"""
    t = _last_ok.get(name)
    return bool(t and time.time() - t < seconds)


def mark_ok(name: str):
    """不在 heavy() 裡跑但算成功的子步驟（例如全系統更新裡的庫藏股）"""
    _last_ok[name] = time.time()


def current() -> dict:
    return {"name": _state["current"], "since": _state["since"]}


def recent(n: int = 30) -> list:
    """最後 n 筆；用 deque 只留 n 行在記憶體（審查 Groq：紀錄檔變大也不會整個讀進來；開機時也會裁到 300 行）"""
    from collections import deque
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            lines = deque(f, maxlen=n)
    except Exception:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def boots(n: int = 10) -> list:
    return [r for r in recent(KEEP_LINES) if r.get("kind") == "boot"][-n:]


def on_boot() -> dict:
    """開機：清暫存檔、裁掉太長的紀錄、找出上次跑到一半的工作、記一筆 boot"""
    try:
        if TMP_DIR.exists():
            for p in TMP_DIR.iterdir():
                try:
                    p.unlink()
                except Exception:
                    pass
    except Exception:
        pass
    rows = recent(2000)
    open_jobs: dict = {}
    for r in rows:
        if r.get("kind") == "start":
            open_jobs[r.get("name")] = r
        elif r.get("kind") == "end":
            open_jobs.pop(r.get("name"), None)
        elif r.get("kind") == "boot":
            open_jobs = {}
    interrupted = sorted(open_jobs)
    rec = {"t": _now(), "kind": "boot", "interrupted": interrupted}
    try:
        keep = rows[-KEEP_LINES:]
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = LOG_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for r in keep:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, LOG_FILE)
    except Exception:
        pass
    _append(rec)
    return rec


def write_json_atomic(path: Path, data) -> None:
    """寫 JSON：先寫暫存再改名，被砍掉也不會留下半個檔（審查 Gemini 第 3 輪 F2）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
