"""B74 大盤解析 API（PLAN-B74 §7）；B75 加 sym＝TWII／TX、分 K 排程（PLAN-B75 §3.4、§9）"""
from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException

from . import data as D, futdata as FD, panel as P, service as S

log = logging.getLogger(__name__)
router = APIRouter()
_refresh = {"running": False, "error": None, "finished": None}


def startup():
    """伺服器啟動：建表、沒有歷史就背景回補（Yahoo／證交所／FinMind）"""
    try:
        D.init_db()
        D.ensure_history(background=True)
        D.ensure_chips_history(background=True)
        FD.ensure_history(background=True)
    except Exception as e:     # noqa: BLE001
        log.warning(f"[wave] 啟動初始化失敗：{e}")


@router.get("/api/wave/snapshot")
def api_snapshot(force: int = 0, sym: str = "TWII"):
    if sym not in S.SYMS:
        raise HTTPException(status_code=400, detail="sym 只能是 TWII 或 TX")
    return S.snapshot(force=bool(force), sym=sym)


@router.get("/api/wave/status")
def api_status():
    with D.db() as c:
        b5 = {r["sym"]: {"n": r["n"], "last": FD.tw_dt(r["mx"]).strftime("%Y-%m-%d %H:%M")}
              for r in c.execute("SELECT sym, COUNT(*) n, MAX(ts) mx FROM bars5 GROUP BY sym").fetchall()}
        fd = c.execute("SELECT COUNT(*) n, MAX(date) mx FROM fut_daily").fetchone()
        fc = c.execute("SELECT COUNT(*) n, MAX(date) mx FROM fut_chips").fetchone()
    return {"sources": D.status(), "refresh": _refresh, "counts": {s: D.count_idx(s) for s in D.SYMS},
            "bars5": b5, "fut_daily": {"n": fd["n"], "last": fd["mx"]}, "fut_chips": {"n": fc["n"], "last": fc["mx"]}}


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
def api_report(part: str = "wave"):
    """研究報告（純文字）：part＝wave（B74 research/wave/REPORT.md）／futures（B75 research/futures/REPORT.md）"""
    import os
    from fastapi.responses import PlainTextResponse
    if part not in ("wave", "futures"):
        raise HTTPException(status_code=400, detail="part 只能是 wave 或 futures")
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research", part, "REPORT.md")
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
        jid = P.start(S.panel_snapshot, "manual")
    except OverflowError as e:
        raise HTTPException(status_code=429, detail=str(e))
    return {"job": jid}


@router.get("/api/wave/panel/job/{jid}")
def api_panel_job(jid: str):
    return P.job(jid)


# ── 排程與推播用 ──────────────────────────────────────────────────────────────
def scheduled(kind: str):
    """08:20 國外指數＋台指期夜盤＋重算；13:45 加權收盤；13:50 分 K 存檔；16:30 籌碼＋逐筆檔補分 K＋重算＋AI 圓桌；
    21:40 融資；05:10（二～六）夜盤分 K 存檔"""
    try:
        wd = D.tw_now().weekday()
        if kind == "night_close":
            if 1 <= wd <= 5:
                FD.live_bars("TX")
                S.snapshot(force=True, sym="TX")
            return
        if kind == "intraday_close":
            if wd < 5:
                FD.live_bars("TX")
                FD.live_bars("TWII")
                S.fill_twii_today()
                S.snapshot(force=True, sym="TX")
                S.snapshot(force=True)
            return
        if wd >= 5:
            return
        if kind == "premarket":
            refresh_job(chips=False)
        elif kind == "close":
            refresh_job(chips=False)
        elif kind == "chips":
            refresh_job(chips=True)
            if P.providers():
                P.start(S.panel_snapshot, "auto")
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
    ks = (snap.get("key") or {}).get("short")
    if ks:
        L.append(f"短線{ks['kind']} {ks['price']:,.0f}（{'跌破' if ks['side'] == 'below' else '站上'}＝這一段可能結束）")
    ad = snap.get("advice") or {}
    if ad.get("ok"):
        cs = "；".join(f"{'站上' if c['side'] == 'up' else '跌破'} {c['price']:,.0f} {_h.escape(c['act'].split('→')[-1].strip())}"
                      for c in [next((x for x in ad.get("conds") or [] if x["side"] == sd), None) for sd in ("up", "down")] if c)
        L.append(f"💡 操作：建議持股 {ad['range']['lo']}～{ad['range']['hi']}%" + (f"（{cs}）" if cs else ""))
    orf = snap.get("open_ref")
    if orf and orf.get("night_ret") is not None:
        L.append(f"台指期夜盤 {orf['night_ret']:+.2f}% → 加權今天開盤參考 {orf['gap']:+.2f}%（±{orf['gap_sd']:.1f}%）")
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
