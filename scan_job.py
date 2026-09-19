"""
scan_job.py — GitHub Actions 全市場掃描腳本
- 使用 Yahoo Finance 直接抓（GitHub Actions IP 不受限流）
- 結果存到 Supabase scan_cache
- 每天盤後自動跑，或手動 trigger
"""
import asyncio
import json
import os
import sys
import tempfile
import datetime
import threading

# 設定 DB 路徑到 /tmp（GitHub Actions 用 ephemeral storage）
os.environ.setdefault("DB_PATH", os.path.join(tempfile.gettempdir(), "chip_tracker_scan.db"))

# 設定 PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def main():
    print(f"[SCAN_JOB] 開始 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 初始化 price_daily 表
    from price_cache import init_price_db
    init_price_db()

    # 跑全市場掃描（Yahoo 在 GitHub Actions 不限流）
    from yahoo_price import run_market_scan, get_scan_results, get_scan_status
    import supabase_store as sb

    # 背景執行緒：每 30 秒把進度寫到 GitHub
    stop_event = threading.Event()

    def _write_progress():
        while not stop_event.wait(30):
            try:
                s = get_scan_status()
                sb.kv_set("scan_progress", json.dumps({
                    "running": True,
                    "progress": s["progress"],
                    "total": s["total"],
                    "yahoo_ok": s["yahoo_ok"],
                    "yahoo_fail": s["yahoo_fail"],
                    "updated_at": datetime.datetime.now().isoformat(),
                }, ensure_ascii=False))
            except Exception as e:
                print(f"[SCAN_JOB] 進度寫入失敗: {e}")

    prog_thread = threading.Thread(target=_write_progress, daemon=True)
    prog_thread.start()

    await run_market_scan()

    stop_event.set()

    status = get_scan_status()
    results = get_scan_results()
    total = sum(len(v) for v in results.values())
    print(f"[SCAN_JOB] 完成：{total} 支符合，Yahoo ok={status['yahoo_ok']} fail={status['yahoo_fail']}")

    if not results:
        print("[SCAN_JOB] 無結果，不儲存")
        sb.kv_set("scan_progress", json.dumps({
            "running": False,
            "progress": status["progress"],
            "total": status["total"],
            "yahoo_ok": status["yahoo_ok"],
            "yahoo_fail": status["yahoo_fail"],
            "finished_at": datetime.datetime.now().isoformat(),
            "found": 0,
        }, ensure_ascii=False))
        return

    # 存到 GitHub repo (scan_data/latest.json)
    payload = json.dumps({
        "results": results,
        "scanned_at": datetime.datetime.now().isoformat(),
        "yahoo_ok": status["yahoo_ok"],
        "yahoo_fail": status["yahoo_fail"],
    }, ensure_ascii=False)
    ok = sb.kv_set("scan_latest", payload)
    print(f"[SCAN_JOB] 結果儲存{'成功' if ok else '失敗'}")

    # 寫入最終進度（供前端偵測完成）
    sb.kv_set("scan_progress", json.dumps({
        "running": False,
        "progress": status["progress"],
        "total": status["total"],
        "yahoo_ok": status["yahoo_ok"],
        "yahoo_fail": status["yahoo_fail"],
        "finished_at": datetime.datetime.now().isoformat(),
        "found": total,
    }, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
