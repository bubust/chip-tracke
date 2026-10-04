"""
收購併購 API

GET    /api/mna/list            清單（狀態、現價、溢價、剩餘天數、年化報酬）
GET    /api/mna/status          資料狀態＋更新進度
POST   /api/mna/refresh         背景從 MOPS 重大訊息更新（days=回溯交易日數）
POST   /api/mna/deal            手動新增；PUT /api/mna/deal/{id} 修改；DELETE 刪除
POST   /api/mna/import          匯入 CSV（第一列表頭：標的代號、收購方、類型、公告日、收購價、最低數量、最高數量、比例、範圍、期間起、期間迄、對價、備註）
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from . import db
from .fetcher import fetch_range
from treasury.parser import roc_to_iso, to_num

router = APIRouter()
_TW = timezone(timedelta(hours=8))
_refresh = {"running": False, "progress": 0, "total": 0}
_lock = threading.Lock()


def tw_today() -> date:
    return datetime.now(_TW).date()


def run_refresh(days: int = 14) -> dict:
    with _lock:
        if _refresh["running"]:
            return {"ok": False, "message": "已在更新中"}
        _refresh.update(running=True, progress=0, total=0)
    try:
        def prog(d, t):
            with _lock:
                _refresh.update(progress=d, total=t)
        res = fetch_range(days, progress=prog)
        st = db.upsert_auto(res["records"])
        now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M")
        msg = f"找到 {len(res['records'])} 則收購併購訊息（新增 {st['inserted']}、補資料 {st['updated']}）"
        if res["errors"]:
            msg += f"；{len(res['errors'])} 天失敗"
        db.set_status(last_refresh=now, last_message=msg, last_errors="\n".join(res["errors"][:6]) or None,
                      last_snippet=res["snippet"] or None)
        return {"ok": True, "message": msg}
    except Exception as e:
        db.set_status(last_refresh=datetime.now(_TW).strftime("%Y-%m-%d %H:%M"), last_message=f"更新失敗：{e}")
        return {"ok": False, "message": str(e)}
    finally:
        with _lock:
            _refresh["running"] = False


@router.post("/api/mna/refresh")
def refresh(days: int = Query(14, ge=1, le=120)):
    with _lock:
        if _refresh["running"]:
            return {"ok": False, "message": "已在更新中"}
    threading.Thread(target=run_refresh, args=(days,), daemon=True, name="mna-refresh").start()
    return {"ok": True, "message": f"開始從公開資訊觀測站重大訊息更新近 {days} 個交易日"}


@router.get("/api/mna/status")
def status():
    s = db.get_status()
    with _lock:
        s["refresh"] = dict(_refresh)
    return s


def _latest_prices(ids) -> dict:
    out = {}
    try:
        from chip_tracker_v2 import DB_PATH
        c = sqlite3.connect(str(DB_PATH), timeout=5.0)
        for sid in ids:
            r = c.execute("SELECT close, date FROM price_daily WHERE stock_id=? AND close>0 ORDER BY date DESC LIMIT 1",
                          (sid,)).fetchone()
            if r:
                out[sid] = (r[0], r[1])
        c.close()
    except Exception:
        pass
    return out


def _pre_prices(pairs) -> dict:
    """{(sid, iso_date): 公告前一個交易日收盤}：算「公告溢價」（老王：溢價要 15% 以上才進）"""
    out = {}
    try:
        from chip_tracker_v2 import DB_PATH
        c = sqlite3.connect(str(DB_PATH), timeout=5.0)
        for sid, d in pairs:
            if not d:
                continue
            r = c.execute("SELECT close FROM price_daily WHERE stock_id=? AND close>0 AND date<? ORDER BY date DESC LIMIT 1",
                          (sid, d.replace("-", ""))).fetchone()
            if r:
                out[(sid, d)] = r[0]
        c.close()
    except Exception:
        pass
    return out


def _day23(sid: str, resume: str) -> Optional[dict]:
    """減資恢復交易後的第 2 天（第 2 天是一字線就用第 3 天）K 棒"""
    try:
        from chip_tracker_v2 import DB_PATH
        c = sqlite3.connect(str(DB_PATH), timeout=5.0)
        rows = c.execute("SELECT date, open, high, low, close FROM price_daily WHERE stock_id=? AND date>=? ORDER BY date LIMIT 3",
                         (sid, resume.replace("-", ""))).fetchall()
        c.close()
    except Exception:
        return None
    if len(rows) < 2:
        return None
    n = 2
    if rows[1][2] == rows[1][3] and len(rows) >= 3:      # 第 2 天一字線
        n = 3
    d = rows[n - 1]
    return {"n": n, "date": f"{d[0][:4]}-{d[0][4:6]}-{d[0][6:]}", "high": d[2], "low": d[3]}


MNA_TYPES = ("公開收購", "合併", "股份轉換", "收購股權")
_TIP_LOTS = "分批掛單：一張一張掛，不要一次掛大單"
# 上課筆記（2026-10-04）為主：減資用恢復交易 Day 2／Day 3 畫線法；現增看用途、繳款前 1~2 週拉抬
_DAY23 = "恢復交易後看第 2 天或第 3 天的高低點：有效突破該日高點＝買訊，跌破該日低點＝出場"
_CAPITAL_TIPS = {
    "虧損減資": ["彌補虧損大舉減資，之後營收與獲利由負轉正成長 → 容易變翻倍大標股", _DAY23],
    "減資再增資": ["減資再增資：看增資是不是「好資」（引進策略股東、資金用途明確），是的話後勢可期", _DAY23],
    "現金減資": ["大漲後減資（退還現金）依然後勢可期", _DAY23],
    "減資": [_DAY23, "長線看營收：由負轉正、成長的才留"],
    "現金增資": ["宣布現增短線必然利空（股本稀釋、賣老股換新股）",
               "用途是償還債務、營收又不好 → 避開；體質好、用途是擴充產能，或股價在低點現增 → 長線仍看好",
               "認購繳款日前 1~2 週，公司／大戶有動機拉抬（特別是先前修正／盤整過、有成交量的股票）",
               "融券增加、拉回是買點；融券開始減少就是高點"],
    "私募": ["私募看對象：引進策略投資人是好資，後勢可期；私募股有閉鎖期，短線影響小"],
}


def deal_signal(r: dict, today: date) -> Optional[dict]:
    """依老王筆記給訊號：level = buy / watch / avoid / info"""
    t = r.get("deal_type")
    if t in MNA_TYPES:
        if r["status"] == "已結束":
            return None
        pre, cur = r.get("premium_pre_pct"), r.get("premium_pct")
        base = pre if pre is not None else cur
        full = r.get("scope") == "完全收購"
        fresh = bool(r.get("first_announce")) and (today - date.fromisoformat(r["first_announce"])).days <= 3
        if base is None:
            if r.get("offer_value"):
                return {"level": "info", "label": "等股價資料算溢價", "tips": ["溢價 15% 以上才考慮", _TIP_LOTS]}
            return {"level": "info", "label": "待補收購價", "tips": ["補上收購價才能算溢價；溢價 15% 以上才考慮"]}
        if base >= 15 and (cur is None or cur > 3):
            if full:
                lab = ("🔥 新公告：溢價≥15%＋買全部股份 → 隔天掛漲停買" if fresh
                       else "🔥 溢價≥15%＋完全收購：可進場")
                return {"level": "buy", "label": lab,
                        "tips": ["100% 收購＋溢價 15%~30% 以上 → 隔日開盤掛漲停搶購", "大單拆成多筆單張掛單（一張一張掛）"]}
            return {"level": "buy", "label": "✅ 溢價≥15%（部分收購）",
                    "tips": ["溢價 15%~30% 以上可以進", "非 100% 收購：收購期結束後股價容易回落，要在期間內處理",
                             "應賣超過上限會按比例收購，沒收走的股票會退回", _TIP_LOTS]}
        if base >= 15:
            return {"level": "watch", "label": "價差已收斂", "tips": [f"公告溢價 {base:.1f}%，但現價離收購價只剩 {cur:.1f}%，已經沒什麼空間"]}
        if cur is not None and cur <= 0:
            return {"level": "avoid", "label": "現價已高於收購價", "tips": ["市場可能在賭加價或競購，風險自負"]}
        return {"level": "watch", "label": f"溢價 {base:.1f}% 未達 15%", "tips": ["老王：溢價要 15% 以上才進"]}
    if t in ("減資", "現金增資"):
        k = r.get("deal_kind") or t
        tips = list(_CAPITAL_TIPS.get(k, _CAPITAL_TIPS.get(t, [])))
        ps, pe = r.get("period_start"), r.get("period_end")
        tday = today.isoformat()
        if t == "減資":
            d23 = r.get("day23")
            if d23:
                tips.insert(0, f"第 {d23['n']} 天（{d23['date']}）高 {d23['high']}、低 {d23['low']}；現價 {r.get('price')}")
                if r.get("price") is not None and r["price"] > d23["high"]:
                    return {"level": "buy", "label": f"{k}：突破恢復交易第{d23['n']}天高點（買訊）", "tips": tips}
                if r.get("price") is not None and r["price"] < d23["low"]:
                    return {"level": "avoid", "label": f"{k}：跌破第{d23['n']}天低點（出場）", "tips": tips}
                return {"level": "watch", "label": f"{k}：在第{d23['n']}天高低點之間，等突破", "tips": tips}
            if ps and ps >= tday:
                return {"level": "watch", "label": f"{k}：{ps[5:].replace('-', '/')} 恢復交易，看 Day2/3 高低點", "tips": tips}
            return {"level": "info", "label": k, "tips": tips}
        if k == "私募":
            return {"level": "info", "label": "私募：看對象", "tips": tips}
        use = r.get("consideration")
        if ps and ps >= tday and (date.fromisoformat(ps) - today).days <= 14:
            return {"level": "watch", "label": "繳款前 1~2 週：容易拉抬", "tips": tips}
        if use == "償還債務":
            return {"level": "avoid", "label": "現增還債：避開（營收不佳更要避）", "tips": tips}
        if use == "擴充產能":
            return {"level": "info", "label": "現增擴產：短空長多", "tips": tips}
        if pe and pe >= tday:
            return {"level": "watch", "label": "繳款期間：短線別追", "tips": tips}
        return {"level": "avoid", "label": "現增：短線利空", "tips": tips}
    return None


def classify_status(r: dict, today: date) -> str:
    if r.get("status_override"):
        return r["status_override"]
    ps, pe = r.get("period_start"), r.get("period_end")
    t = today.isoformat()
    if ps and t < ps:
        return "未開始"
    if pe:
        return "進行中" if t <= pe else "已結束"
    if r.get("deal_type") == "公開收購":
        return "待補期間"
    return "已公告"


def enrich(rows: list, today: date = None) -> list:
    today = today or tw_today()
    prices = _latest_prices({r["target_id"] for r in rows} | {r["stock_ref"] for r in rows if r.get("stock_ref")})
    pre = _pre_prices({(r["target_id"], r.get("first_announce") or r.get("announce_date")) for r in rows})
    out = []
    for r in rows:
        r = dict(r)
        r["status"] = classify_status(r, today)
        px, pdate = prices.get(r["target_id"], (None, None))
        r["price"], r["price_date"] = px, pdate
        op = r.get("offer_price")
        # 現金＋換股：每股價值＝現金＋換股比例 × 換發股票現價
        if r.get("stock_ratio") and r.get("stock_ref") and prices.get(r["stock_ref"]):
            op = round((op or 0) + r["stock_ratio"] * prices[r["stock_ref"]][0], 2)
            r["offer_value_note"] = f"現金 {r.get('offer_price') or 0} ＋ {r.get('stock_company') or r['stock_ref']} {r['stock_ratio']} 股"
        r["offer_value"] = op
        r["premium_pct"] = round((op / px - 1) * 100, 2) if op and px else None
        pp = pre.get((r["target_id"], r.get("first_announce") or r.get("announce_date")))
        r["pre_price"] = pp
        r["premium_pre_pct"] = round((op / pp - 1) * 100, 2) if op and pp else None
        if r.get("deal_type") in ("減資", "現金增資"):     # 增資的價格是認購價，不是收購價
            r["premium_pct"] = r["premium_pre_pct"] = None
        pe = r.get("period_end")
        r["days_left"] = (date.fromisoformat(pe) - today).days if pe and r["status"] in ("進行中", "未開始") else None
        r["annualized_pct"] = None if r.get("deal_type") in ("減資", "現金增資") else (round(r["premium_pct"] * 365 / max(r["days_left"], 1), 1)
                               if r["premium_pct"] is not None and r["premium_pct"] > 0 and r["days_left"] else None)
        r["min_lots"] = round(r["min_shares"] / 1000) if r.get("min_shares") else None
        r["max_lots"] = round(r["max_shares"] / 1000) if r.get("max_shares") else None
        r["amount_yi"] = round(op * r["max_shares"] / 1e8, 2) if op and r.get("max_shares") else None
        if r.get("deal_type") == "減資" and r.get("period_start") and r["period_start"] <= today.isoformat():
            r["day23"] = _day23(r["target_id"], r["period_start"])
        r["signal"] = deal_signal(r, today)
        r["listed_target"] = r.get("target_id") != r.get("announcer_id") or not r.get("target_company")
        out.append(r)
    return out


_MERGE_KEYS = ("acquirer", "offer_price", "min_shares", "max_shares", "offer_pct", "scope", "period_start",
               "period_end", "consideration", "target_company", "stock_company", "stock_ref", "stock_ratio", "deal_kind")


def group_deals(rows: list) -> list:
    """同一案常有好幾則公告（收購方、被收購方、延長期間…）：同標的＋同類型、公告日相差 120 天內合成一列，
    欄位以「資料最完整、最新」的那則為主，缺的從其他則補；related 記下所有公告"""
    rows = sorted(rows, key=lambda r: (r.get("announce_date") or ""), reverse=True)
    groups: list = []
    for r in rows:
        g = next((g for g in groups if g["target_id"] == r["target_id"] and g["deal_type"] == r["deal_type"]
                  and abs((date.fromisoformat(g["_first"]) - date.fromisoformat(r.get("announce_date") or g["_first"])).days) <= 120), None)
        if g is None:
            g = {**r, "_first": r.get("announce_date") or tw_today().isoformat(), "related": []}
            groups.append(g)
        else:
            for k in _MERGE_KEYS:
                if g.get(k) in (None, "") and r.get(k) not in (None, ""):
                    g[k] = r[k]
            if r.get("status_override") and not g.get("status_override"):
                g["status_override"] = r["status_override"]
            g["_first"] = min(g["_first"], r.get("announce_date") or g["_first"])
        g["related"].append({"id": r["id"], "date": r.get("announce_date"), "subject": r.get("subject") or r.get("notes") or "",
                             "source": r.get("source")})
    for g in groups:
        g["first_announce"] = g.pop("_first")
    return groups


@router.get("/api/mna/list")
def list_deals(days: int = Query(365, ge=7, le=3650)):
    since = (tw_today() - timedelta(days=days)).isoformat()
    rows = enrich(group_deals(db.all_rows(since)))
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"rows": rows, "counts": counts, "status": status()}


class Deal(BaseModel):
    target_id: str
    target_name: Optional[str] = ""
    acquirer: Optional[str] = ""
    deal_type: Optional[str] = "公開收購"
    announce_date: Optional[str] = None
    offer_price: Optional[float] = None
    min_shares: Optional[float] = None
    max_shares: Optional[float] = None
    offer_pct: Optional[float] = None
    scope: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    consideration: Optional[str] = None
    status_override: Optional[str] = None
    notes: Optional[str] = ""


def _clean(d: Deal) -> dict:
    if not re.fullmatch(r"[0-9A-Za-z]{2,10}", (d.target_id or "").strip()):
        raise HTTPException(400, "標的代號格式不正確")
    data = d.model_dump()
    data["target_id"] = data["target_id"].strip()
    for k in ("announce_date", "period_start", "period_end"):
        data[k] = roc_to_iso(data[k]) if data.get(k) else None
    for k in ("target_name", "acquirer", "deal_type", "scope", "consideration", "status_override", "notes"):
        v = "".join(ch for ch in str(data.get(k) or "") if ch >= " ").strip()
        data[k] = v[:300] or None
    return data


@router.post("/api/mna/deal")
def create_deal(d: Deal):
    return {"ok": True, "id": db.save_manual(_clean(d))}


@router.put("/api/mna/deal/{deal_id}")
def update_deal(deal_id: int, d: Deal):
    db.save_manual(_clean(d), deal_id)
    return {"ok": True, "id": deal_id}


@router.delete("/api/mna/deal/{deal_id}")
def delete_deal(deal_id: int):
    db.delete(deal_id)
    return {"ok": True}


_CSV_MAP = {"標的代號": "target_id", "代號": "target_id", "標的名稱": "target_name", "名稱": "target_name",
            "收購方": "acquirer", "類型": "deal_type", "公告日": "announce_date", "收購價": "offer_price",
            "最低數量": "min_shares", "最高數量": "max_shares", "比例": "offer_pct", "範圍": "scope",
            "期間起": "period_start", "期間迄": "period_end", "對價": "consideration", "備註": "notes"}


@router.post("/api/mna/import")
async def import_csv(request: Request):
    raw = await request.body()
    if not raw or len(raw) > 4 * 1024 * 1024:
        raise HTTPException(400, "檔案是空的或太大（上限 4MB）")
    text = None
    for enc in ("utf-8-sig", "cp950"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    rows = list(csv.reader(io.StringIO(text or "")))
    if len(rows) < 2:
        raise HTTPException(400, "CSV 至少要有表頭和一列資料")
    hdr = [_CSV_MAP.get(h.strip()) for h in rows[0]]
    if "target_id" not in hdr:
        raise HTTPException(400, "表頭要有「標的代號」")
    n = 0
    for r in rows[1:]:
        rec = {k: (r[i].strip() if i < len(r) else "") for i, k in enumerate(hdr) if k}
        if not rec.get("target_id"):
            continue
        for k in ("offer_price", "min_shares", "max_shares", "offer_pct"):
            rec[k] = to_num(rec.get(k))
        rec = {k: v for k, v in rec.items() if v not in ("", None)}
        try:
            data = _clean(Deal(**rec))
        except Exception:
            continue
        data["source"] = "匯入"
        db.save_manual(data)
        n += 1
    return {"ok": True, "imported": n}
