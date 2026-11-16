"""暫時檢查：用戶 11/16 晚上貼別的網站的「融資餘額（扣除 ETF）、融資維持率、整戶維持率、追繳／處分」→ 正式站現在的融資餘額、大盤融資維持率，跟官方原始數字比"""
import json
import time
import httpx

B = "https://qiangni-tactics.fly.dev"
UA = {"User-Agent": "Mozilla/5.0"}
out = {}
for k in range(30):                                            # 等 B113 部署完（wave.js 有 B113）
    try:
        if "B113" in httpx.get(B + "/regime/static/wave.js", timeout=30).text:
            break
    except Exception:  # noqa: BLE001
        pass
    time.sleep(20)
try:
    j = httpx.get(B + "/api/wave/snapshot", params={"sym": "TWII"}, timeout=300).json()
    m = j.get("margin") or {}
    out["margin"] = {k: m.get(k) for k in ("ok", "date", "amt", "chg1", "pct1", "chg5", "chg20", "pending", "last10")}
    mt = m.get("maint") or {}
    out["maint"] = {k: mt.get(k) for k in ("ok", "date", "twse", "tpex", "all", "amt_yi", "cover", "chg5", "low60")}
    out["maint_series"] = (mt.get("series") or [])[-12:]
    tx = httpx.get(B + "/api/wave/snapshot", params={"sym": "TX"}, timeout=300).json()
    out["tx"] = {k: tx.get(k) for k in ("generated", "price", "prev_close", "chg", "chg_pct", "sess")}
    t = ((tx.get("nest") or {}).get("60m") or {}).get("tiers") or {}
    out["tx_card"] = {"pos": (t.get("card") or {}).get("pos"), "tiles": (t.get("card") or {}).get("tiles")}
except Exception as e:  # noqa: BLE001
    out["err"] = repr(e)
# 官方原始：證交所信用交易統計（融資金額，含 ETF）、櫃買融資餘額彙總
for d in ("20261113", "20261116"):
    try:
        r = httpx.get("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN", params={"date": d, "selectType": "MS", "response": "json"},
                      headers=UA, timeout=40).json()
        out[f"twse_ms_{d}"] = {"stat": r.get("stat"), "tables": [{"title": t.get("title"), "fields": t.get("fields"), "data": t.get("data")}
                                                                for t in (r.get("tables") or [])][:2]}
    except Exception as e:  # noqa: BLE001
        out[f"twse_ms_{d}"] = repr(e)
    time.sleep(3)
try:
    r = httpx.get("https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php",
                  params={"l": "zh-tw", "o": "json", "d": "115/11/16"}, headers=UA, timeout=40).json()
    out["tpex_1116"] = {k: r.get(k) for k in ("reportDate", "iTotalRecords", "tfootData_one", "tfootData_two")}
    if not any(out["tpex_1116"].values()):
        out["tpex_1116_keys"] = list(r.keys())[:30]
        out["tpex_1116_tables"] = [{"title": t.get("title"), "summary": t.get("summary")} for t in (r.get("tables") or [])][:3]
except Exception as e:  # noqa: BLE001
    out["tpex_1116"] = repr(e)
with open("scratch_probe/b114.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(json.dumps({k: out.get(k) for k in ("margin", "maint", "tx")}, ensure_ascii=False)[:3000])
