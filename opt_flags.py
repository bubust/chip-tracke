"""⭐ 優化研究通過的條件（PLAN-B82 §4；research/b82/opt_research.json 裡 passed:true 的才用）
掃描最後幫「有通過條件的策略」每一列加 o＝{date, flags, meets: {族: True/False}}，網站把符合的排前面、標 ⭐（不藏股票）。
條件定義、資料時間點跟研究同一套（research/b82/b82common.py；verify_flags.py 逐日比對 0 不一致）：
- 籌碼 C1～C8：三大法人用訊號當天（INST_LAG＝0）、融資用前一天（MARGIN_LAG＝1）；連買／5 日都是「交易日」往回數，哪天沒資料＝不符合
- 月營收 M1～M5：M 月營收從 M+1 月 15 日起才用（1 月營收＝2 月 20 日）"""
import json
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)
BASE = Path(__file__).parent
RESEARCH_PATH = BASE / "research" / "b82" / "opt_research.json"
COURSE_DB = BASE / "chip_data" / "course.db"
REV_AVAIL_DAY, REV_AVAIL_DAY_JAN = 15, 20
_R = {"mtime": None, "data": {}}


def research() -> dict:
    try:
        mt = RESEARCH_PATH.stat().st_mtime
        if _R["mtime"] != mt:
            _R.update(mtime=mt, data=json.loads(RESEARCH_PATH.read_text(encoding="utf-8")))
        return _R["data"]
    except Exception:      # noqa: BLE001
        return {}


def passed_rules(R: dict | None = None) -> dict:
    """{策略: [{fam, combo, desc}]}，只有 passed:true、而且網站算得出來的族（籌碼、月營收）"""
    R = research() if R is None else R
    out = {}
    for k, x in (R.get("strategies") or {}).items():
        for fam in ("chip", "rev"):
            y = x.get(fam)
            if y and y.get("passed") and y.get("combo"):
                out.setdefault(k, []).append({"fam": fam, "combo": list(y["combo"]), "desc": y.get("desc", "")})
    return out


# ── 純函式（研究對照用）────────────────────────────────────────────────────────
def chip_flags_pure(cal: list, inst: dict, margin: dict, vol: dict, sids) -> dict:
    """cal：到訊號日為止的交易日（YYYYMMDD，由舊到新，最後一個＝訊號日）
    inst：{日: {sid: (外資, 投信, 自營)}}（股）；margin：{日: {sid: 融資餘額}}（張）；vol：{sid: 訊號日成交量（張）}
    → {sid: set(C1..C8)}"""
    out = {}
    if not cal:
        return out
    d0 = cal[-1]
    back = lambda k: cal[-1 - k] if len(cal) > k else None      # noqa: E731

    def iv(d, sid, j):
        r = (inst.get(d) or {}).get(sid) if d else None
        return None if r is None or r[j] is None else float(r[j])

    def gt0(x):
        return x is not None and x > 0
    for sid in sids:
        f = [iv(back(k), sid, 0) for k in range(3)]
        t = [iv(back(k), sid, 1) for k in range(2)]
        tot = []
        for k in range(5):
            r = (inst.get(back(k)) or {}).get(sid) if back(k) else None
            tot.append(None if r is None or any(v is None for v in r) else float(sum(r)))
        s = set()
        if gt0(f[0]):
            s.add("C1")
        if gt0(t[0]):
            s.add("C2")
        if all(gt0(x) for x in f):
            s.add("C3")
        if all(gt0(x) for x in t):
            s.add("C4")
        if all(x is not None for x in tot) and sum(tot) > 0:
            s.add("C5")
        v = vol.get(sid)
        if gt0(tot[0]) and v is not None and tot[0] / 1000.0 >= 0.10 * float(v):
            s.add("C6")
        m1 = (margin.get(back(1)) or {}).get(sid) if back(1) else None
        m6 = (margin.get(back(6)) or {}).get(sid) if back(6) else None
        if m1 is not None and m6 is not None and m6 > 0 and m1 < m6:
            s.add("C7")
        if "C1" in s and "C2" in s:
            s.add("C8")
        out[sid] = s
    return out


def rev_avail_date(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[4:6])
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{ny:04d}{nm:02d}{REV_AVAIL_DAY_JAN if m == 1 else REV_AVAIL_DAY:02d}"


def _prev_ym(ym: str, k: int = 1) -> str:
    y, m = int(ym[:4]), int(ym[4:6]) - k
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}{m:02d}"


def rev_flags_pure(day: str, rev: dict, sids) -> dict:
    """rev：{YYYYMM: {sid: (營收, 年增%, 累計年增%)}} → {sid: set(M1..M5)}；只用訊號日已經「可以知道」的最新月份"""
    avail = [ym for ym in rev if rev_avail_date(ym) <= day]
    out = {sid: set() for sid in sids}
    if not avail:
        return out
    M = max(avail)
    cur, prev = rev.get(M) or {}, rev.get(_prev_ym(M)) or {}
    prior = [rev.get(_prev_ym(M, k)) for k in range(1, 12)]
    for sid in sids:
        r = cur.get(sid)
        if not r:
            continue
        rv, yoy, cum = r
        s = out[sid]
        if yoy is not None and yoy > 0:
            s.add("M1")
        if yoy is not None and yoy >= 20:
            s.add("M2")
        if cum is not None and cum > 0:
            s.add("M3")
        if rv is not None and all(p is not None and (p.get(sid) or (None,))[0] is not None for p in prior):
            if rv >= max(p[sid][0] for p in prior):
                s.add("M4")
        py = (prev.get(sid) or (None, None, None))[1]
        if yoy is not None and yoy > 0 and py is not None and py > 0:
            s.add("M5")
    return out


# ── 網站資料（本機 SQLite）────────────────────────────────────────────────────
def _calendar(day: str, n: int = 8) -> list:
    from price_cache import DB_PATH
    c = sqlite3.connect(str(DB_PATH), timeout=30)
    try:
        rows = c.execute("SELECT DISTINCT date FROM price_daily WHERE date<=? ORDER BY date DESC LIMIT ?", (day, n)).fetchall()
    finally:
        c.close()
    return sorted(r[0] for r in rows)


def load_chip(day: str, sids):
    cal = _calendar(day)
    if not cal or cal[-1] != day:
        return [], {}, {}, {}
    iso = {d: f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in cal}
    c = sqlite3.connect(str(COURSE_DB), timeout=30)
    inst, margin = {}, {}
    try:
        for d in cal:
            inst[d] = {s: (f, t, dl) for s, f, t, dl in c.execute("SELECT sid, foreign_net, trust_net, dealer_net FROM inst_daily WHERE date=?", (iso[d],))}
            margin[d] = {s: m for s, m in c.execute("SELECT sid, margin FROM margin_bal WHERE date=?", (iso[d],))}
    finally:
        c.close()
    from price_cache import DB_PATH
    c = sqlite3.connect(str(DB_PATH), timeout=30)
    try:
        vol = {s: v for s, v in c.execute("SELECT stock_id, volume FROM price_daily WHERE date=?", (day,))}
    finally:
        c.close()
    return cal, inst, margin, vol


def load_rev(months: int = 14) -> dict:
    import course_live
    course_live.ensure_revenue_history(months)
    c = course_live._conn()
    try:
        rows = c.execute("SELECT ym, stock_id, rev, yoy, cum_yoy FROM revenue_month ORDER BY ym DESC").fetchall()
    finally:
        c.close()
    out = {}
    for ym, sid, rv, yoy, cum in rows:
        out.setdefault(ym, {})[sid] = (rv, yoy, cum)
    return out


def annotate(all_results: dict, day: str | None = None, lock=None) -> dict:
    """有通過條件的策略：每一列加 o＝{date, flags, meets}；回傳摘要。lock＝寫入時要拿的鎖（掃描結果已經公開時用）"""
    rules = passed_rules()
    rules = {k: v for k, v in rules.items() if all_results.get(k)}
    if not rules:
        return {"rules": 0}
    rows = [r for k in rules for r in all_results[k]]
    day = day or max((str(r.get("last_date") or "") for r in rows), default="")
    if not day:
        return {"rules": len(rules), "day": None}
    sids = sorted({str(r.get("stock_id")) for r in rows})
    fams = {x["fam"] for v in rules.values() for x in v}
    flags = {sid: set() for sid in sids}
    if "chip" in fams:
        cal, inst, margin, vol = load_chip(day, sids)
        for sid, s in chip_flags_pure(cal, inst, margin, vol, sids).items():
            flags[sid] |= s
    if "rev" in fams:
        for sid, s in rev_flags_pure(day, load_rev(), sids).items():
            flags[sid] |= s
    todo = []
    for k, rl in rules.items():
        for r in all_results[k]:
            fl = flags.get(str(r.get("stock_id")), set())
            todo.append((r, {"date": day, "flags": sorted(fl), "meets": {x["fam"]: all(c in fl for c in x["combo"]) for x in rl}}))
    if lock is not None:
        with lock:
            for r, o in todo:
                r["o"] = o
    else:
        for r, o in todo:
            r["o"] = o
    return {"rules": {k: [x["desc"] for x in v] for k, v in rules.items()}, "day": day, "meets": sum(any(o["meets"].values()) for _, o in todo)}


def annotate_current() -> dict:
    """重開機後：記憶體裡的掃描結果補上 o（不重掃）"""
    try:
        from yahoo_price import _scan_status, _results_lock
        if _scan_status.get("running"):
            return {"skip": "掃描中"}
        with _results_lock:
            res = {k: list(v or []) for k, v in (_scan_status.get("results") or {}).items()}
        return annotate(res, lock=_results_lock)      # 列是同一批 dict：先算好，寫入時才上鎖
    except Exception as e:      # noqa: BLE001
        log.warning(f"[opt] annotate_current 失敗：{e}")
        return {"error": str(e)}
