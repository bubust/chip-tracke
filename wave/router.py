"""B74 大盤解析 API（PLAN-B74 §7）"""
from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException

from . import data as D, panel as P, service as S

log = logging.getLogger(__name__)
router = APIRouter()
_refresh = {"running": False, "error": None, "finished": None}


def startup():
    """伺服器啟動：建表、沒有歷史就背景回補（Yahoo／證交所／FinMind）"""
    try:
        D.init_db()
        D.ensure_history(background=True)
        D.ensure_chips_history(background=True)
    except Exception as e:     # noqa: BLE001
        log.warning(f"[wave] 啟動初始化失敗：{e}")


@router.get("/api/wave/snapshot")
def api_snapshot(force: int = 0):
    return S.snapshot(force=bool(force))


@router.get("/api/wave/status")
def api_status():
    return {"sources": D.status(), "refresh": _refresh, "counts": {s: D.count_idx(s) for s in D.SYMS}}


def refresh_job(chips: bool = True):
    if _refresh["running"]:
        return False
    _refresh.update(running=True, error=None)
    try:
        S.refresh_all(chips=chips)
    except Exception as e:     # noqa: BLE001
        log.exception("[wave] 更新失敗")
        _refresh["error"] = str(e)[:200]
    finally:
        _refresh.update(running=False, finished=D.tw_now().strftime("%Y-%m-%d %H:%M:%S"))
    return True


@router.post("/api/wave/refresh")
def api_refresh():
    if _refresh["running"]:
        return {"ok": True, "running": True}
    threading.Thread(target=refresh_job, daemon=True).start()
    return {"ok": True, "started": True}


@router.get("/api/wave/report")
def api_report():
    """研究報告（research/wave/REPORT.md，純文字）"""
    import os
    from fastapi.responses import PlainTextResponse
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research", "wave", "REPORT.md")
    try:
        with open(p, encoding="utf-8") as fh:
            return PlainTextResponse(fh.read(), media_type="text/plain; charset=utf-8")
    except OSError:
        raise HTTPException(status_code=404, detail="研究報告不存在")


@router.get("/api/wave/panel")
def api_panel():
    return P.latest()


@router.post("/api/wave/panel/run")
def api_panel_run():
    if not P.providers():
        raise HTTPException(status_code=400, detail="還沒設定任何 AI 金鑰（GEMINI_API_KEY／GROQ_API_KEY）")
    try:
        jid = P.start(lambda: S.snapshot(), "manual")
    except OverflowError as e:
        raise HTTPException(status_code=429, detail=str(e))
    return {"job": jid}


@router.get("/api/wave/panel/job/{jid}")
def api_panel_job(jid: str):
    return P.job(jid)


# ── 排程與推播用 ──────────────────────────────────────────────────────────────
def scheduled(kind: str):
    """08:20 國外指數＋重算；13:45 加權收盤；16:30 籌碼＋重算＋AI 圓桌；21:40 融資"""
    try:
        if D.tw_now().weekday() >= 5:
            return
        if kind == "premarket":
            refresh_job(chips=False)
        elif kind == "close":
            refresh_job(chips=False)
        elif kind == "chips":
            refresh_job(chips=True)
            if P.providers():
                P.start(lambda: S.snapshot(), "auto")
        elif kind == "margin":
            refresh_job(chips=True)
    except Exception as e:     # noqa: BLE001
        log.warning(f"[wave] 排程 {kind} 失敗：{e}")


def push_lines(snap: dict | None = None) -> list:
    """08:30 盤前推播的大盤段（HTML，Telegram）；算不出來回 []"""
    import html as _h
    snap = snap or S.snapshot()
    if not snap or not snap.get("ok"):
        return []
    md = lambda d: f"{int(d[5:7])}/{int(d[8:10])}" if d and len(d) >= 10 else d
    L = [f"🌊 <b>加權 {snap['price']:,.0f}</b>（{md(snap['asof']['date'])} 收，{snap.get('chg_pct'):+.2f}%）"]
    mid = (snap.get("waves") or {}).get("mid") or {}
    p, a = mid.get("primary"), mid.get("alternate")
    if p:
        s = f"劇本：{_h.escape(p['text'])}"
        if a:
            s += f"（替代：{_h.escape(a['text'])}）"
        if p.get("invalid") is not None:
            s += f"；{'跌破' if p['invalid_side'] == 'below' else '漲過'} {p['invalid']:,.0f} 主要劇本失效"
        L.append(s)

    def zz(lst):
        if not lst:
            return "—"
        z = lst[0]
        h = z.get("hold") or {}
        tag = f"，守 {h['rate'] * 100:.0f}%" if h.get("rate") is not None else ""
        return f"{z['price']:,.0f}（{_h.escape(z['type_name'])}{tag}）"
    for k, nm in (("short", "短線"), ("swing", "波段")):
        lv = snap["levels"][k]
        L.append(f"{nm}　撐 {zz(lv['support'])}／壓 {zz(lv['resistance'])}")
    so = (snap.get("global") or {}).get("sox_overnight")
    if so and so.get("tw_expect") is not None:
        L.append(f"費半 {md(so['date'])} {so['sox_ret']:+.2f}% → 加權今天歷史平均 {so['tw_expect']:+.2f}%（±{so['sd']:.1f}%）")
    h20 = (snap.get("forecast") or {}).get("h20")
    if h20:
        L.append(f"歷史 20 天：上漲 {h20['p_up'] * 100:.0f}%，八成在 {h20['lo_px']:,.0f}～{h20['hi_px']:,.0f}")
    try:
        lt = P.latest().get("result") or {}
        mo = lt.get("moderator") or {}
        if mo.get("summary") and lt.get("day"):
            if lt.get("mode") == "single":
                who = ((lt.get("participants") or [{}])[0] or {}).get("name", "AI")
                head = f"🤖 只有 {_h.escape(str(who))} 的看法"
                tail = ""
            else:
                head = "🤖 AI 圓桌"
                tail = f"（{_h.escape(str(mo.get('agree_count', '')))}）"
            L.append(f"{head}（{md(lt['day'])}）：{_h.escape(str(mo.get('stance', '')))}・{_h.escape(str(mo['summary']))}{tail}")
    except Exception:     # noqa: BLE001
        pass
    L.append("（規則數浪＋歷史條件推估，不是投資建議）")
    return L
