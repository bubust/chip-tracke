"""
disposal.py — ⛓ 處置股（PLAN-LINK 第 5 節；講義：權證小哥「雙刀處置」）

每天抓證交所（announcement/punish、notice）＋櫃買（bulletin/disposal、attention），快取 30 分鐘：
- 處置中：起迄、第幾次（初犯／再次）、分盤頻率；今天／明天出關
- 快被處置：最近 30 個營業日的注意次數、連續注意天數、10 日內次數
  （證交所處置條件：連續 3 個營業日、或連續 5 個營業日、或 10 日內 6 日、或 30 日內 12 日達注意標準；櫃買類似）
- 每檔附雙刀候選：同產業、60 日相關 ≥ 0.6 的連動股（linkage.peers_of），偏差率＝處置股 ÷ 配對股 比值 vs 60 日平均
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta

import httpx

log = logging.getLogger(__name__)
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_CACHE: dict = {"t": 0.0, "data": None}
TTL = 1800


def _roc(s) -> str:
    m = re.match(r"(\d+)\D+(\d+)\D+(\d+)", str(s).strip())
    if not m:
        return ""
    y, mo, d = map(int, m.groups())
    return f"{y + 1911 if y < 1911 else y:04d}{mo:02d}{d:02d}"


def _get(url, params):
    try:
        return httpx.get(url, params=params, headers=H, timeout=30, follow_redirects=True).json()
    except Exception as e:
        log.warning(f"[disposal] {url}: {e}")
        return {}


def fetch_disposals(days: int = 45) -> list:
    """最近 days 天公布的處置（上市＋上櫃）"""
    end = date.today()
    start = end - timedelta(days=days)
    out = []
    j = _get("https://www.twse.com.tw/rwd/zh/announcement/punish",
             {"startDate": start.strftime("%Y%m%d"), "endDate": end.strftime("%Y%m%d"), "response": "json"})
    for r in j.get("data") or []:
        se = re.split(r"[～~]", str(r[6]))
        out.append({"stock_id": str(r[2]).strip(), "name": str(r[3]).strip(), "pub": _roc(r[1]),
                    "start": _roc(se[0]) if se else "", "end": _roc(se[1]) if len(se) > 1 else "",
                    "times": str(r[7]).strip(), "cond": str(r[5]).strip(), "market": "上市",
                    "freq": "20 分鐘" if "二十分鐘" in str(r[8]) else "5 分鐘" if "五分鐘" in str(r[8]) else ""})
    time.sleep(1)
    j = _get("https://www.tpex.org.tw/www/zh-tw/bulletin/disposal",
             {"startDate": start.strftime("%Y/%m/%d"), "endDate": end.strftime("%Y/%m/%d"), "response": "json"})
    for t in j.get("tables") or []:
        for r in t.get("data") or []:
            if not str(r[2]).strip():
                continue
            se = re.split(r"[～~]", str(r[5]))
            txt = str(r[8])
            out.append({"stock_id": str(r[2]).strip(), "name": re.sub(r"\(.*", "", str(r[3])).strip(), "pub": _roc(r[1]),
                        "start": _roc(se[0]) if se else "", "end": _roc(se[1]) if len(se) > 1 else "",
                        "times": str(r[7]).strip(), "cond": str(r[6]).strip(), "market": "上櫃",
                        "freq": "20 分鐘" if "20分鐘" in txt else "5 分鐘" if "5分鐘" in txt else ""})
    return [x for x in out if re.fullmatch(r"\d{4}", x["stock_id"])]


def fetch_attention(days: int = 45) -> list:
    end = date.today()
    start = end - timedelta(days=days)
    out = []
    j = _get("https://www.twse.com.tw/rwd/zh/announcement/notice",
             {"startDate": start.strftime("%Y%m%d"), "endDate": end.strftime("%Y%m%d"), "response": "json"})
    for r in j.get("data") or []:
        out.append({"stock_id": str(r[1]).strip(), "name": str(r[2]).strip(), "date": _roc(r[5]),
                    "reason": re.sub(r"<[^>]+>", "", str(r[4]))[:80], "market": "上市"})
    time.sleep(1)
    j = _get("https://www.tpex.org.tw/www/zh-tw/bulletin/attention",
             {"startDate": start.strftime("%Y/%m/%d"), "endDate": end.strftime("%Y/%m/%d"), "response": "json"})
    for t in j.get("tables") or []:
        for r in t.get("data") or []:
            out.append({"stock_id": str(r[1]).strip(), "name": str(r[2]).strip(), "date": _roc(r[5]),
                        "reason": str(r[4])[:80], "market": "上櫃"})
    return [x for x in out if re.fullmatch(r"\d{4}", x["stock_id"])]


def _trading_days(n: int = 40) -> list:
    """最近 n 個交易日（price_daily 有的日子）"""
    try:
        from linkage import _conn
        c = _conn()
        ds = [r[0] for r in c.execute("SELECT DISTINCT date FROM price_daily ORDER BY date DESC LIMIT ?", (n,)).fetchall()]
        c.close()
        return sorted(str(d).replace("-", "") for d in ds)
    except Exception:
        return []


def _pairs(sid: str, min_corr: float = 0.6) -> list:
    try:
        from linkage import peers_of
        p = peers_of(sid)
    except Exception:
        p = None
    if not p:
        return []
    ps = [x for x in p["peers"] if x["same_sector"] and x["corr"] >= min_corr]
    ps.sort(key=lambda x: -x["corr"])
    return ps[:3]


def today(force: bool = False) -> dict:
    if not force and _CACHE["data"] and time.time() - _CACHE["t"] < TTL:
        return _CACHE["data"]
    tdays = _trading_days(40)
    today_s = tdays[-1] if tdays else date.today().strftime("%Y%m%d")
    disp = fetch_disposals()
    att = fetch_attention()
    active, releasing = [], []
    for d in disp:
        if not d["start"] or not d["end"]:
            continue
        if d["start"] <= today_s <= d["end"] or d["start"] > today_s:
            d["status"] = "今天出關" if d["end"] == today_s else ("明天開始" if d["start"] > today_s else "處置中")
            d["first"] = ("第一次" in d["times"] or "初" in d["times"]) and not re.search("第二次|再次", d["times"])
            d["pairs"] = _pairs(d["stock_id"])
            (releasing if d["end"] == today_s else active).append(d)
    active.sort(key=lambda x: x["end"])
    # 快被處置：注意次數
    by = {}
    for a in att:
        by.setdefault(a["stock_id"], {"name": a["name"], "market": a["market"], "dates": set(), "reasons": []})
        by[a["stock_id"]]["dates"].add(a["date"])
        by[a["stock_id"]]["reasons"].append(a["reason"])
    disposed = {d["stock_id"] for d in active + releasing}
    near = []
    last30 = tdays[-30:]
    for sid, v in by.items():
        if sid in disposed:
            continue
        ds = v["dates"]
        consec = 0
        for d in reversed(tdays):
            if d in ds:
                consec += 1
            else:
                break
        n10 = sum(1 for d in tdays[-10:] if d in ds)
        n30 = sum(1 for d in last30 if d in ds)
        risk = consec >= 2 or n10 >= 5 or n30 >= 11
        if not ds or max(ds) < (tdays[-5] if len(tdays) >= 5 else ""):
            continue
        near.append({"stock_id": sid, "name": v["name"], "market": v["market"], "consec": consec, "n10": n10, "n30": n30,
                     "last": max(ds), "risk": risk, "reason": v["reasons"][-1] if v["reasons"] else "",
                     "hint": (f"已連續 {consec} 天注意，隨時可能被處置" if consec >= 3 else
                              "再 1 天注意就可能被處置（連續 3 天）" if consec == 2 else
                              "10 日內再 1 次就可能被處置（6 次）" if n10 == 5 else
                              "30 日內再 1 次就可能被處置（12 次）" if n30 == 11 else ""),
                     "pairs": _pairs(sid) if risk else []})
    near.sort(key=lambda x: (not x["risk"], -x["consec"], -x["n10"]))
    data = {"date": today_s, "updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "active": active, "releasing": releasing,
            "near": near[:60]}
    _CACHE.update(t=time.time(), data=data)
    return data
