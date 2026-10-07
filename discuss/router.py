"""
💬 戰略討論區 API（把跟老大哥的對話貼進來：AI 找股票、題材、產業鏈、大哥／小弟、同族群，接上戰術中心的資料）

POST   /api/discuss/analyze              {text, images:[{mime,data(base64)}], chat_date} → {job_id}（背景跑，約 30～60 秒）
GET    /api/discuss/job/{job_id}         進度／結果（session_id）
GET    /api/discuss/status               有沒有金鑰、今天用了幾次
GET    /api/discuss/sessions             歷史（含提到的股票、記錄價）
GET    /api/discuss/session/{id}         單筆完整結果
DELETE /api/discuss/session/{id}
PUT    /api/discuss/session/{id}/note    {note}
POST   /api/discuss/session/{id}/resolve {text, stock_id}：「新棒」＝哪一檔（記住暱稱，下次自動對上）
GET    /api/discuss/aliases；DELETE /api/discuss/alias?alias=
GET    /api/discuss/quotes?ids=          每檔：現價、漲跌、均線、今天中的策略、千張大戶、產業輪動
GET    /api/discuss/tracker              老大哥提過的股票：提到時價格 → 現在漲跌
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from . import ai, db

router = APIRouter()
_TW = timezone(timedelta(hours=8))
_jobs: dict = {}
_lock = threading.Lock()
_daily = {"date": None, "n": 0}
DAILY_LIMIT = int(os.environ.get("DISCUSS_DAILY_LIMIT", "60"))     # 網址沒有密碼：保護 Gemini 免費額度
MAX_IMAGES, MAX_IMAGE_B64 = 8, 8_000_000
_SID = re.compile(r"^\d{4}$")

db.init_db()


def tw_today() -> date:
    return datetime.now(_TW).date()


# ── 股票清單：代號 ↔ 名稱 ───────────────────────────────────────────────────────

def _stock_maps():
    from yahoo_price import get_stock_list
    df = get_stock_list()
    by_id = {str(r.stock_id): str(r.stock_name) for r in df.itertuples()}
    mkt = {str(r.stock_id): str(r.type) for r in df.itertuples()}
    by_name = {}
    for sid, nm in by_id.items():
        if _SID.match(sid):
            by_name.setdefault(_norm(nm), sid)
    return by_id, by_name, mkt


def _norm(name: str) -> str:
    s = re.sub(r"[\s\*＊]|股份有限公司|有限公司|-KY|－KY|KY$", "", str(name or ""))
    return s.replace("臺", "台")


def _name_match(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a and b) and (a == b or a in b or b in a)


def _lookup_name(name: str, by_name: dict):
    n = _norm(name)
    if not n:
        return None
    if n in by_name:
        return by_name[n]
    hits = [sid for nm, sid in by_name.items() if len(nm) >= 2 and (n.startswith(nm) or nm.startswith(n))]
    return hits[0] if len(hits) == 1 else None


def _valid(sid, name, by_id, by_name):
    """AI 給的代號＋名稱 → (代號, 正式名稱, 狀況)
    狀況：ok／fixed（代號錯、用名稱找到）／mismatch（代號存在但名稱完全對不上）／none（找不到）"""
    sid = re.sub(r"\D", "", str(sid or ""))
    if sid in by_id and _SID.match(sid):
        if not name or _name_match(name, by_id[sid]):
            return sid, by_id[sid], "ok"
        other = _lookup_name(name, by_name)
        if other and other != sid:
            return other, by_id[other], "fixed"          # 代號跟名稱對不上：相信名稱
        return sid, by_id[sid], "mismatch"
    other = _lookup_name(name, by_name)
    if other:
        return other, by_id[other], "fixed"
    return None, None, "none"


def resolve(result: dict, aliases: dict) -> dict:
    """AI 結果的股票全部拿 stocks.csv 對過：不存在的代號不亂給；使用者確認過的暱稱優先"""
    by_id, by_name, _ = _stock_maps()
    dropped = []
    for m in result.get("mentions") or []:
        text = str(m.get("text") or "").strip()
        cands = []
        for c in m.get("candidates") or []:
            cs, cn, how = _valid(c.get("stock_id"), c.get("name"), by_id, by_name)
            if cs and how != "mismatch" and cs not in [x["stock_id"] for x in cands]:
                cands.append({"stock_id": cs, "name": cn})
        if text in aliases:
            a = aliases[text]
            m.update(stock_id=a["stock_id"], name=by_id.get(a["stock_id"], a["name"]), confidence="confirmed")
        else:
            sid, nm, how = _valid(m.get("stock_id"), m.get("name"), by_id, by_name)
            if not sid and _SID.match(text) and text in by_id:
                sid, nm, how = text, by_id[text], "ok"
            conf = m.get("confidence") or "low"
            if how == "fixed" and conf == "high":
                conf = "medium"
            if not sid or how == "mismatch":           # 名稱跟代號完全對不上：讓使用者確認
                conf = "low"
            m.update(stock_id=sid or "", name=nm or m.get("name") or "", confidence=conf)
        m["candidates"] = [c for c in cands if c["stock_id"] != m["stock_id"]][:3]
        m["status"] = "unknown" if not m["stock_id"] else ("unsure" if m["confidence"] == "low" else "ok")

    def fix_list(items, key="stock_id"):
        out = []
        for s in items or []:
            sid, nm, how = _valid(s.get(key), s.get("name"), by_id, by_name)
            if sid and how != "mismatch":
                s.update(stock_id=sid, name=nm)
                out.append(s)
            else:
                dropped.append(f"{s.get('name') or ''} {s.get(key) or ''}".strip())
        return out

    for th in result.get("themes") or []:
        for seg in th.get("chain") or []:
            seg["stocks"] = fix_list(seg.get("stocks"))
    result["related"] = fix_list(result.get("related"))
    for lf in result.get("leader_follower") or []:
        for k in ("leaders", "followers"):
            lf[k] = [x for x in (re.sub(r"\D", "", str(v)) for v in lf.get(k) or []) if x in by_id]
    result["dropped"] = [d for d in dropped if d]
    return result


# ── 價格 ─────────────────────────────────────────────────────────────────────

def _price_conn():
    from chip_tracker_v2 import DB_PATH
    return sqlite3.connect(str(DB_PATH), timeout=5.0)


def _price_on(sids, chat_date: str) -> dict:
    """{sid: (收盤, 日期)}：對話日期當天（或之前最近一天）"""
    d = chat_date.replace("-", "")
    out = {}
    try:
        c = _price_conn()
        for sid in sids:
            r = c.execute("SELECT close, date FROM price_daily WHERE stock_id=? AND close>0 AND date<=? ORDER BY date DESC LIMIT 1",
                          (sid, d)).fetchone()
            if r:
                out[sid] = (float(r[0]), str(r[1]))
        c.close()
    except Exception:
        pass
    return out


def _latest(sids) -> dict:
    out = {}
    try:
        c = _price_conn()
        for sid in sids:
            r = c.execute("SELECT close, date FROM price_daily WHERE stock_id=? AND close>0 ORDER BY date DESC LIMIT 1",
                          (sid,)).fetchone()
            if r:
                out[sid] = (float(r[0]), str(r[1]))
        c.close()
    except Exception:
        pass
    return out


def session_stocks(result: dict, chat_date: str) -> list:
    """要存的股票：對話提到的（含大哥／小弟角色）＋同族群／產業鏈上的"""
    roles = {}
    for lf in result.get("leader_follower") or []:
        for s in lf.get("leaders") or []:
            roles[s] = "leader"
        for s in lf.get("followers") or []:
            roles.setdefault(s, "follower")
    rows = {}
    for m in result.get("mentions") or []:
        if m.get("stock_id") and m["stock_id"] not in rows:
            rows[m["stock_id"]] = {"stock_id": m["stock_id"], "name": m.get("name"), "kind": "mentioned",
                                   "role": roles.get(m["stock_id"], ""), "mention_text": m.get("text")}
    for th in result.get("themes") or []:
        for seg in th.get("chain") or []:
            for s in seg.get("stocks") or []:
                rows.setdefault(s["stock_id"], {"stock_id": s["stock_id"], "name": s.get("name"), "kind": "related",
                                                "role": roles.get(s["stock_id"], "")})
    for s in result.get("related") or []:
        rows.setdefault(s["stock_id"], {"stock_id": s["stock_id"], "name": s.get("name"), "kind": "related",
                                        "role": roles.get(s["stock_id"], "")})
    px = _price_on(list(rows), chat_date)
    for sid, r in rows.items():
        if sid in px:
            r["price_at"], r["price_date"] = px[sid]
    return list(rows.values())


def _title(result: dict) -> str:
    names = [t.get("name") for t in result.get("themes") or [] if t.get("name")]
    if names:
        return "、".join(names[:2])
    ms = [m.get("name") for m in result.get("mentions") or [] if m.get("name")]
    return "、".join(ms[:3]) or "（沒有找到股票）"


# ── 分析（背景工作）───────────────────────────────────────────────────────────

class AnalyzeIn(BaseModel):
    text: str = ""
    images: list = []
    chat_date: str = ""


def _job_set(jid, **kw):
    with _lock:
        _jobs[jid].update(kw)


def _run(jid: str, text: str, images: list, chat_date: str):
    try:
        transcript = text.strip()
        if images:
            _job_set(jid, step=f"讀截圖（{len(images)} 張）…")
            ocr_text, _ = ai.ocr(images)
            transcript = (ocr_text + ("\n" + transcript if transcript else "")).strip()
        _job_set(jid, step="AI 分析中（查最新產業消息）…", transcript=transcript)
        aliases = db.get_aliases()
        out = ai.analyze(transcript, chat_date, aliases)
        result = resolve(out["result"], aliases)
        result["transcript"] = transcript
        result["searched"] = out["searched"]
        result["queries"] = out["queries"]
        _job_set(jid, step="整理股票資料…")
        sid = db.save_session({"chat_date": chat_date, "title": _title(result), "source_text": text,
                               "image_count": len(images), "transcript": transcript, "result": result,
                               "sources": out["sources"], "model": out["model"]},
                              session_stocks(result, chat_date))
        _job_set(jid, status="done", step="完成", session_id=sid)
    except Exception as e:
        _job_set(jid, status="error", step="失敗", error=str(e)[:600])


@router.post("/api/discuss/analyze")
def analyze(body: AnalyzeIn):
    if not ai.api_key():
        raise HTTPException(400, "還沒設定 Gemini 金鑰（Fly secret GEMINI_API_KEY）")
    text = (body.text or "").strip()
    images = [im for im in (body.images or []) if isinstance(im, dict) and im.get("data")]
    if not text and not images:
        raise HTTPException(400, "請貼上對話文字或截圖")
    if len(images) > MAX_IMAGES:
        raise HTTPException(400, f"截圖最多 {MAX_IMAGES} 張")
    if any(len(im["data"]) > MAX_IMAGE_B64 for im in images):
        raise HTTPException(400, "截圖太大")
    if len(text) > 20000:
        raise HTTPException(400, "文字太長（最多 2 萬字）")
    chat_date = body.chat_date or tw_today().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", chat_date):
        raise HTTPException(400, "對話日期格式要 YYYY-MM-DD")
    today = tw_today().isoformat()
    with _lock:
        if _daily["date"] != today:
            _daily.update(date=today, n=0)
        if _daily["n"] >= DAILY_LIMIT:
            raise HTTPException(429, f"今天已經分析 {DAILY_LIMIT} 次，明天再來（保護免費額度）")
        _daily["n"] += 1
        for k in [k for k, v in _jobs.items() if time.time() - v["t"] > 3600]:
            _jobs.pop(k, None)
        jid = uuid.uuid4().hex[:12]
        _jobs[jid] = {"status": "running", "step": "開始…", "t": time.time()}
    threading.Thread(target=_run, args=(jid, text, images, chat_date), daemon=True, name="discuss-ai").start()
    return {"job_id": jid}


@router.get("/api/discuss/job/{jid}")
def job(jid: str):
    with _lock:
        j = _jobs.get(jid)
        if not j:
            raise HTTPException(404, "找不到這個分析（伺服器可能重開了，請重新分析）")
        return {k: v for k, v in j.items() if k != "t"} | {"elapsed": round(time.time() - j["t"])}


@router.get("/api/discuss/status")
def status():
    with _lock:
        n = _daily["n"] if _daily["date"] == tw_today().isoformat() else 0
    return {"has_key": bool(ai.api_key()), "today": n, "limit": DAILY_LIMIT}


# ── 歷史 ─────────────────────────────────────────────────────────────────────

def _fill_price_at(sessions: list):
    """盤中分析時當天還沒收盤，記錄價先用前一天；當天收盤進資料庫後換成對話日期當天的收盤"""
    upd = []
    for r in sessions:
        d = (r.get("chat_date") or "").replace("-", "")
        stale = [s for s in r["stocks"] if not s.get("price_date") or s["price_date"] < d]
        if not stale or d > tw_today().strftime("%Y%m%d"):
            continue
        px = _price_on([s["stock_id"] for s in stale], r["chat_date"])
        for s in stale:
            p = px.get(s["stock_id"])
            if p and p[1] != s.get("price_date"):
                s["price_at"], s["price_date"] = p
                upd.append((r["id"], s["stock_id"], p[0], p[1]))
    db.update_price_at(upd)


def _with_now(stocks: list) -> list:
    now = _latest({s["stock_id"] for s in stocks})
    for s in stocks:
        p = now.get(s["stock_id"])
        s["price_now"], s["now_date"] = (p if p else (None, None))
        s["chg_since"] = round((p[0] / s["price_at"] - 1) * 100, 2) if p and s.get("price_at") else None
    return stocks


@router.get("/api/discuss/sessions")
def sessions():
    rows = db.list_sessions()
    _fill_price_at(rows)
    _with_now([s for r in rows for s in r["stocks"]])
    return {"rows": rows}


@router.get("/api/discuss/session/{session_id}")
def session(session_id: int):
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(404, "找不到")
    _fill_price_at([s])
    _with_now(s["stocks"])
    return s


@router.delete("/api/discuss/session/{session_id}")
def delete(session_id: int):
    db.delete_session(session_id)
    return {"ok": True}


class NoteIn(BaseModel):
    note: str = ""


@router.put("/api/discuss/session/{session_id}/note")
def note(session_id: int, body: NoteIn):
    db.update_note(session_id, body.note[:2000])
    return {"ok": True}


class ResolveIn(BaseModel):
    text: str
    stock_id: str = ""          # 空字串＝「不是股票」：從這次結果拿掉


@router.post("/api/discuss/session/{session_id}/resolve")
def resolve_mention(session_id: int, body: ResolveIn):
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(404, "找不到")
    by_id, _, _ = _stock_maps()
    text = body.text.strip()
    sid = body.stock_id.strip()
    if sid and sid not in by_id:
        raise HTTPException(400, f"沒有 {sid} 這檔")
    result = s["result"]
    hit = False
    for m in result.get("mentions") or []:
        if str(m.get("text") or "").strip() == text:
            hit = True
            if sid:
                m.update(stock_id=sid, name=by_id[sid], confidence="confirmed", status="ok", candidates=[])
            else:
                m.update(stock_id="", confidence="low", status="ignored", candidates=[])
    if not hit:
        raise HTTPException(404, f"這次結果沒有「{text}」")
    if sid:
        db.set_alias(text, sid, by_id[sid])
    db.update_session(session_id, result, session_stocks(result, s["chat_date"]), _title(result))
    return session(session_id)


@router.get("/api/discuss/aliases")
def aliases():
    return {"rows": [{"alias": k, **v} for k, v in db.get_aliases().items()]}


@router.delete("/api/discuss/alias")
def delete_alias(alias: str = Query(...)):
    db.delete_alias(alias)
    return {"ok": True}


@router.get("/api/discuss/tracker")
def tracker():
    """對話提到的股票：第一次提到的日期／價格 → 現在，提到幾次"""
    rows = db.list_sessions(limit=1000)
    _fill_price_at(rows)
    agg = {}
    for r in sorted(rows, key=lambda x: (x["chat_date"] or "", x["id"])):
        for s in r["stocks"]:
            if s["kind"] != "mentioned":
                continue
            a = agg.setdefault(s["stock_id"], {"stock_id": s["stock_id"], "name": s["name"], "times": 0,
                                               "first_date": r["chat_date"], "first_price": s.get("price_at"),
                                               "last_date": r["chat_date"], "sessions": [], "roles": set()})
            a["times"] += 1
            a["last_date"] = r["chat_date"]
            a["sessions"].append(r["id"])
            if s.get("role"):
                a["roles"].add(s["role"])
            if a["first_price"] is None and s.get("price_at"):
                a["first_price"] = s["price_at"]
    now = _latest(list(agg))
    out = []
    for sid, a in agg.items():
        p = now.get(sid)
        a["price_now"], a["now_date"] = (p if p else (None, None))
        a["chg"] = round((p[0] / a["first_price"] - 1) * 100, 2) if p and a["first_price"] else None
        a["roles"] = sorted(a["roles"])
        out.append(a)
    out.sort(key=lambda x: (x["first_date"] or ""), reverse=True)
    return {"rows": out}


# ── 每檔股票的戰術中心資料 ─────────────────────────────────────────────────────

def _sector_info(sids) -> dict:
    try:
        from sector.db import SECTOR_DB_PATH
        c = sqlite3.connect(str(SECTOR_DB_PATH), timeout=5.0)
        c.row_factory = sqlite3.Row
        last = c.execute("SELECT MAX(observation_date) FROM sector_daily").fetchone()[0]
        total = c.execute("SELECT COUNT(*) FROM sector_daily WHERE observation_date=?", (last,)).fetchone()[0]
        out = {}
        for sid in sids:
            r = c.execute("""SELECT s.sector_name, d.relative_rank_20d, d.rank_trend, d.trend_state, d.sector_regime,
                                    d.transition_state, d.return_ew_20d
                             FROM stock_sector_map m JOIN sector_master s USING(sector_id)
                             LEFT JOIN sector_daily d ON d.sector_id=m.sector_id AND d.observation_date=?
                             WHERE m.stock_id=? ORDER BY m.effective_date DESC LIMIT 1""", (last, sid)).fetchone()
            if r:
                out[sid] = {**dict(r), "total": total, "date": last}
        c.close()
        return out
    except Exception:
        return {}


def _tech(df: pd.DataFrame) -> dict:
    c = df["close"].astype(float).values
    v = df["volume"].astype(float).values
    n = len(c)
    ma = {k: (float(c[-k:].mean()) if n >= k else None) for k in (5, 10, 20, 60)}
    ret = lambda k: round((c[-1] / c[-1 - k] - 1) * 100, 2) if n > k and c[-1 - k] > 0 else None
    state = "整理"
    if all(ma.values()):
        if ma[5] > ma[10] > ma[20] > ma[60]:
            state = "多頭排列"
        elif ma[5] < ma[10] < ma[20] < ma[60]:
            state = "空頭排列"
    hi = float(df["high"].astype(float).values[-250:].max())
    return {"close": round(float(c[-1]), 2), "date": str(df.iloc[-1]["date"]), "change_pct": ret(1),
            "ret5": ret(5), "ret20": ret(20), "ret60": ret(60), "ma_state": state,
            "above_ma20": bool(ma[20] and c[-1] > ma[20]), "above_ma60": bool(ma[60] and c[-1] > ma[60]),
            "vol_ratio": round(float(v[-1] / v[-21:-1].mean()), 1) if n > 21 and v[-21:-1].mean() > 0 else None,
            "from_high_pct": round((c[-1] / hi - 1) * 100, 1) if hi > 0 else None}


@router.get("/api/discuss/quotes")
def quotes(ids: str = ""):
    sids = list(dict.fromkeys(x for x in (i.strip() for i in ids.split(",")) if _SID.match(x)))[:60]
    by_id, _, mkt = _stock_maps()
    from price_cache import get_stock_ohlcv
    try:
        from yahoo_price import get_scan_results
        scan = get_scan_results()
    except Exception:
        scan = {}
    hits = {}
    for key, res in (scan or {}).items():
        for r in res or []:
            hits.setdefault(str(r.get("stock_id")), []).append(key)
    try:
        from tdcc_chip import get_tdcc_data
        tdcc = get_tdcc_data()
    except Exception:
        tdcc = {}
    sector = _sector_info(sids)
    out = {}
    for sid in sids:
        row = {"stock_id": sid, "name": by_id.get(sid, ""), "market": mkt.get(sid, "")}
        df = get_stock_ohlcv(sid, days=260)
        if df.empty or len(df) < 25:
            try:
                from yahoo_price import _fetch_for_scan
                df = _fetch_for_scan(sid, mkt.get(sid, "twse"))
            except Exception:
                df = None
        if df is not None and not df.empty and len(df) >= 2:
            row.update(_tech(df.dropna(subset=["close"]).reset_index(drop=True)))
        row["strategies"] = hits.get(sid, [])
        t = tdcc.get(sid)
        row["kpct"] = t.get("current_pct") if t else None
        row["kpct_change"] = t.get("change") if t else None
        row["sector"] = sector.get(sid)
        out[sid] = row
    return out
