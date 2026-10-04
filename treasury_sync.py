"""
在自己電腦（台灣網路）抓公開資訊觀測站的庫藏股資料，推到線上網站。
伺服器（Fly.io 東京）若被公開資訊觀測站擋，用這支補資料。

用法：
  python treasury_sync.py                       # 近 180 天，推到預設網站
  python treasury_sync.py --days 1095           # 回補 3 年
  python treasury_sync.py --server http://127.0.0.1:8080 --dry-run
網站有開寫入保護時會要密碼（或先設環境變數 CHIP_ADMIN_PASSWORD）。
"""
import argparse
import json
from datetime import date, timedelta

import httpx

from server_auth_client import auth_headers
from treasury.fetcher import fetch_range

DEFAULT_SERVER = "https://qiangni-tactics.fly.dev"


def main():
    ap = argparse.ArgumentParser(description="同步庫藏股資料到網站")
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("--dry-run", action="store_true", help="只抓不推")
    a = ap.parse_args()

    end = date.today()
    res = fetch_range(end - timedelta(days=a.days), end,
                      progress=lambda d, t: print(f"\r抓取中 {d}/{t} 段", end="", flush=True))
    print()
    recs = res["records"]
    print(f"抓到 {len(recs)} 筆")
    for e in res["errors"]:
        print("  失敗：", e)
    if res["snippet"]:
        print("  回應開頭：", res["snippet"][:200])
    if not recs or a.dry_run:
        return
    r = httpx.post(a.server.rstrip("/") + "/api/treasury/import",
                   content=json.dumps(recs, ensure_ascii=False).encode("utf-8"),
                   headers={"Content-Type": "application/octet-stream", **auth_headers(a.server)},
                   timeout=60.0)
    print(r.status_code, r.text[:300])


if __name__ == "__main__":
    main()
