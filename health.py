"""🩺 系統健康（PLAN-B77 D3）：記憶體、最近重開、背景工作紀錄、各資料最新日期

每一項都回白話：ok（✅）／warn（⚠）＋一句說明。
「應有的交易日」＝平日 18:30 以後是今天，否則前一個平日（沒有休市日曆：國定假日當天會顯示 ⚠，說明裡有寫）。
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import jobs

DATA = Path(__file__).parent / "chip_data"


def expected_day(now: datetime) -> date:
    d = now.date()
    if d.weekday() < 5 and (now.hour, now.minute) >= (18, 30):
        return d
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _to_date(v):
    """'20261021'／'2026-10-21'／'2026-10-21 18:40'／'2026-10-21T18:40:00' → date；不認得回 None"""
    if v is None:
        return None
    s = str(v).strip()
    try:
        if len(s) >= 8 and s[:8].isdigit():
            return datetime.strptime(s[:8], "%Y%m%d").date()
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _item(key, label, latest, ok, note, what=""):
    return {"key": key, "label": label, "latest": latest, "ok": bool(ok), "note": note, "what": what}


def _daily(key, label, latest, exp: date, what: str, holiday_hint=True):
    d = _to_date(latest)
    if d is None:
        return _item(key, label, latest, False, "沒有資料或讀不到日期", what)
    if d >= exp:
        return _item(key, label, latest, True, "是最新的", what)
    lag = (exp - d).days
    hint = "（今天如果休市就正常）" if holiday_hint and lag <= 3 else ""
    return _item(key, label, latest, False, f"停在 {d.isoformat()}，應該要有 {exp.isoformat()}{hint}", what)


def _q(db: Path, sql: str):
    try:
        c = sqlite3.connect(str(db), timeout=5)
        try:
            return c.execute(sql).fetchone()[0]
        finally:
            c.close()
    except Exception:
        return None


def freshness(now: datetime, refresh_status: dict | None = None) -> list:
    exp = expected_day(now)
    items = []
    # 股價（官方收盤）
    try:
        from price_cache import get_price_cache_status
        items.append(_daily("price", "股價（每日收盤）", get_price_cache_status().get("to"), exp,
                            "證交所＋櫃買官方收盤，所有 K 線、策略、觀察清單都用它"))
    except Exception as e:      # noqa: BLE001
        items.append(_item("price", "股價（每日收盤）", None, False, f"讀取失敗：{type(e).__name__}"))
    # 全市場掃描（18:00）
    try:
        from yahoo_price import get_scan_status
        fin = get_scan_status().get("finished_at")
        d = _to_date(fin)
        ok = False
        try:
            ok = fin is not None and datetime.fromisoformat(str(fin)).replace(tzinfo=None) >= datetime(exp.year, exp.month, exp.day, 17, 30)
        except ValueError:
            pass
        items.append(_item("scan", "全市場策略掃描", str(fin)[:16].replace("T", " ") if fin else None, ok,
                           "是最新的" if ok else (f"上次掃描 {d}，{exp} 晚上的還沒跑（18:00 自動跑；重開機會自動補）" if d else "還沒有掃描結果"),
                           "策略篩選分頁的名單"))
    except Exception as e:      # noqa: BLE001
        items.append(_item("scan", "全市場策略掃描", None, False, f"讀取失敗：{type(e).__name__}"))
    # 總經
    items.append(_daily("regime", "總經面板", _q(DATA / "regime.db", "SELECT MAX(date) FROM market_daily WHERE series='TAIEX'"),
                        exp, "總經分數、過熱恐慌、大盤解析的國外指數"))
    # 三大法人、集保
    course = DATA / "course.db"
    items.append(_daily("inst", "三大法人買賣超", _q(course, "SELECT MAX(date) FROM inst_daily"), exp,
                        "全市場排行、投信連買、籌碼型策略"))
    td = _to_date(_q(course, "SELECT MAX(date) FROM tdcc_tier"))
    items.append(_item("tdcc", "集保大戶（每週）", td.isoformat() if td else None,
                       bool(td and (now.date() - td).days <= 9),
                       "是最新的（集保每週五公布）" if td and (now.date() - td).days <= 9 else "超過 9 天沒更新", "千張大戶、大戶增散戶減"))
    # 產業輪動
    items.append(_daily("sector", "產業輪動", _q(DATA / "sector.db", "SELECT MAX(observation_date) FROM sector_daily"), exp,
                        "產業強弱、輪動泡泡圖"))
    # 市場關聯
    items.append(_daily("relationship", "市場關聯", _q(DATA / "relationship.db", "SELECT MAX(observation_date) FROM market_daily"),
                        exp, "台指期與現貨背離、市場事件"))
    # 權證合約
    try:
        from warrant.router import _last_ingest_log as wl
        ran = wl.get("finished_at") or wl.get("ran_at")
        d = _to_date(ran)
        ok = bool(d and (now.date() - d).days <= 1 and not wl.get("error"))
        note = ("是最新的" if ok else ("上次更新失敗：" + str(wl.get("error"))[-120:] if wl.get("error")
                                       else (f"上次更新 {d}" if d else "還沒有更新紀錄（每天 08:00 自動更新）")))
        items.append(_item("warrant", "權證合約", str(ran)[:16].replace("T", " ") if ran else None, ok, note, "權證選擇器、認購前十大"))
    except Exception as e:      # noqa: BLE001
        items.append(_item("warrant", "權證合約", None, False, f"讀取失敗：{type(e).__name__}"))
    # 可轉債、收購併購、庫藏股（各自 last_refresh）
    for key, label, mod, fn, what in (("cb", "可轉債", "cb.router", "status", "可轉債分頁"),
                                      ("mna", "收購併購", "mna.router", "status", "收購併購分頁"),
                                      ("treasury", "庫藏股", "treasury.router", "get_status", "庫藏股分頁")):
        try:
            import importlib
            st = getattr(importlib.import_module(mod), fn)()
            items.append(_daily(key, label, st.get("last_refresh"), exp, what))
        except Exception as e:      # noqa: BLE001
            items.append(_item(key, label, None, False, f"讀取失敗：{type(e).__name__}"))
    # 全系統更新
    if refresh_status is not None:
        rs = refresh_status
        fin = rs.get("finished_at")
        bad = [v.get("label") for v in (rs.get("steps") or {}).values() if v.get("status") in ("error", "interrupted", "skipped")]
        if rs.get("running"):
            items.append(_item("refresh_all", "全系統更新", "更新中", True, "正在跑", "按 🔄 全系統更新 或 18:00 自動"))
        else:
            ok = bool(fin) and not rs.get("interrupted") and not bad and (_to_date(fin) or date.min) >= exp
            note = ("是最新的" if ok else
                    ("上次跑到一半伺服器重開" if rs.get("interrupted") else
                     (f"上次有 {len(bad)} 項沒成功：" + "、".join(bad[:4]) if bad else
                      (f"上次跑完是 {str(fin)[:16].replace('T', ' ')}" if fin else "還沒有紀錄"))))
            items.append(_item("refresh_all", "全系統更新", str(fin)[:16].replace("T", " ") if fin else None, ok, note,
                               "按 🔄 全系統更新 或 18:00 自動"))
    return items


def memory() -> dict:
    mi = jobs.meminfo()
    rss = jobs.rss_mb()
    out = {"rss": rss, **mi}
    total = mi.get("total")
    if rss and total:
        pct = rss / total
        out["level"] = "ok" if pct < 0.6 else ("warn" if pct < 0.8 else "bad")
        out["text"] = f"網站用了 {rss}MB／機器 {total}MB（{round(pct * 100)}%）"
    elif rss:
        out["level"] = "ok"
        out["text"] = f"網站用了 {rss}MB"
    if mi.get("swap_total"):
        out["text"] = out.get("text", "") + f"；備用空間（swap）用了 {mi.get('swap_used', 0)}／{mi['swap_total']}MB"
    return out


def report(refresh_status: dict | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    items = freshness(now, refresh_status)
    mem = memory()
    boots = jobs.boots(10)
    cut = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    crashes = [b for b in boots if b.get("t", "") >= cut and b.get("interrupted")]
    warn = [i for i in items if not i["ok"]]
    if mem.get("level") == "bad":
        warn.append({"label": "記憶體", "note": mem.get("text", "")})
    if crashes:
        warn.append({"label": "重開", "note": f"3 天內有 {len(crashes)} 次是工作跑到一半重開"})
    text = "✅ 全部正常" if not warn else f"⚠ {len(warn)} 項要注意：" + "、".join(w["label"] for w in warn[:5])
    jobs_recent = [r for r in jobs.recent(80) if r.get("kind") in ("end", "skip", "catchup", "boot")][-30:]
    return {"now": now.strftime("%Y-%m-%d %H:%M"), "expected_day": expected_day(now).isoformat(), "summary": text,
            "ok": not warn, "items": items, "memory": mem, "boots": boots, "crash_boots_3d": len(crashes),
            "jobs": list(reversed(jobs_recent)), "running": jobs.current()}
