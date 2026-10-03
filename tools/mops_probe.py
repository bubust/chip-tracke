"""臨時診斷：用實際的 mna.fetcher 抓近 8 個交易日（需要 stocks.csv 對應代號）"""
import json, sys
sys.path.insert(0, ".")
import mna.fetcher as f
import csv
f._names = [(r["stock_id"], r["stock_name"]) for r in csv.DictReader(open("stocks.csv", encoding="utf-8"))]
res = f.fetch_range(days=8)
print("errors:", res["errors"]); print("找到", len(res["records"]), "筆")
keys = ("target_id", "target_name", "acquirer", "deal_type", "announce_date", "offer_price", "stock_company", "stock_ref", "stock_ratio",
        "min_shares", "max_shares", "offer_pct", "scope", "period_start", "period_end", "consideration", "target_company")
for r in res["records"]:
    print(json.dumps({k: r.get(k) for k in keys if r.get(k) is not None}, ensure_ascii=False))
