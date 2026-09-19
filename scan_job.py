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
    await run_market_scan()

    status = get_scan_status()
    results = get_scan_results()
    total = sum(len(v) for v in results.values())
    print(f"[SCAN_JOB] 完成：{total} 支符合，Yahoo ok={status['yahoo_ok']} fail={status['yahoo_fail']}")

    if not results:
        print("[SCAN_JOB] 無結果，不儲存")
        return

    # 存到 GitHub repo (scan_data/latest.json)
    import supabase_store as sb
    payload = json.dumps({
        "results": results,
        "scanned_at": datetime.datetime.now().isoformat(),
        "yahoo_ok": status["yahoo_ok"],
        "yahoo_fail": status["yahoo_fail"],
    }, ensure_ascii=False)
    ok = sb.kv_set("scan_latest", payload)
    print(f"[SCAN_JOB] 結果儲存{'成功' if ok else '失敗'}")

if __name__ == "__main__":
    asyncio.run(main())
