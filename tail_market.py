"""
tail_market.py — 🎯 尾盤追蹤 B91（PLAN-B91 §1、§3.3）：研究（research/b91/run.py）跟網站（fbd_live、tail_track）用同一份函式

1. 日線多頭結構（低不破低、高過高）struct_series／struct_check
   波段點＝course2.swing_seq（講義 a／d 點，前後 k 根，要到第 j+k 根才確認，不偷看未來）。
   到今天為止已確認的點：H1＝最近一個波段高、L1＝H1 前面的波段低、H0＝L1 前面的波段高
   高過高＝H1 > H0；低不破低＝H1 之後（含今天）的最低價 > L1；兩個都成立＝ok。
   空頭（bear）＝高不過高（H1 < H0）而且低破低（最低 < L1）。點不夠＝ok False、reason「波段點不夠」。
   呼叫端決定最後一根是什麼：網站盤中＝今天到現在的開高低收（低點還會再變低），研究＝全天日 K。
   已知限制：波段點要 k 根後才確認 → H1 至少是 k 天前的高點；「現在」的狀態交給 S_FBD 本身（站回 MA10、收紅）＋最低 > L1 把關。

2. 13:15 大盤盤面 market_features：加權昨天以前的日 K＋13:15 快照（開 o、高 h、低 l、現 x、昨收 y）＋前一晚費半
   M1 13:15 漲跌、M2 當天走法、M3 在今天高低區間的位置、M4 大盤日線結構（多頭／盤整／空頭）、M5 均線、M6 近 5 日、M7 前一晚費半、M8 波動、M9＝M4×漲跌

3. 盤勢判斷 verdict：只用 tail_research.json 裡「通過」的規則（研究沒通過＝一律一般）
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

import numpy as np

from course2 import HIGH, LOW, swing_seq

K_STRUCT = 3
RESEARCH_PATH = Path(__file__).parent / "tail_research.json"

# 族與格（研究、網站、前端說明用同一份；順序＝顯示順序）
FAMILIES = {
    "M1": ("13:15 大盤漲跌", ["≤−1%", "−1～0%", "0～+1%", "≥+1%"]),
    "M2": ("大盤當天走法", ["開高走高", "開高走低", "開低走高", "開低走低"]),
    "M3": ("13:15 在今天高低區間", ["下 1/3", "中間", "上 1/3"]),
    "M4": ("大盤日線結構", ["多頭", "盤整", "空頭"]),          # 盤整＝不是多頭也不是空頭（高低點一高一低、轉折中）
    "M5": ("大盤月線／季線", ["兩條都站上", "只站上一條", "都跌破"]),
    "M6": ("大盤近 5 日", ["≤−3%", "−3～0%", "0～+3%", "≥+3%"]),
    "M7": ("前一晚費半", ["≤−2%", "−2～0%", ">0%"]),
    "M8": ("大盤波動", ["一般", "高波動"]),
    "M9": ("大盤日線×今天漲跌", ["多頭·漲", "多頭·跌", "盤整·漲", "盤整·跌", "空頭·漲", "空頭·跌"]),
}


# ── 1. 日線結構 ───────────────────────────────────────────────────────────────
_REASONS = {0: "", 1: "高沒有過前高", 2: "低點跌破前低", 3: "高沒過前高、低點也跌破前低", 4: "波段點不夠"}


def struct_series(h, l, k: int = K_STRUCT):
    """每一天（含當天那根）的結構 → (ok bool[n], bear bool[n], code int8[n], H0, L1, H1, pull_low float[n])
    code：0 合格、1 高沒過高、2 低破低、3 兩個都不行、4 點不夠"""
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    n = len(h)
    ok = np.zeros(n, bool)
    bear = np.zeros(n, bool)
    code = np.full(n, 4, np.int8)
    H0 = np.full(n, np.nan); L1 = np.full(n, np.nan); H1 = np.full(n, np.nan); PL = np.full(n, np.nan)
    if n == 0:
        return ok, bear, code, H0, L1, H1, PL
    typ, val, idx = swing_seq(h, l, k, depth=4)
    run_j, run_t, run_min = -2, -2, math.inf
    for t in range(n):
        tt, vv, ii = typ[t], val[t], idx[t]
        p = 0 if tt[0] == HIGH else 1 if tt[1] == HIGH else -1
        if p < 0 or p + 2 >= 4 or tt[p + 1] != LOW or tt[p + 2] != HIGH:
            continue
        j1 = int(ii[p])
        if j1 != run_j or run_t != t - 1:                 # 換了一個 H1（或中間跳過）→ 從 H1 後一根重新算最低
            seg = l[j1 + 1:t + 1]
            seg = seg[np.isfinite(seg)]
            run_min = float(seg.min()) if len(seg) else math.inf
            run_j = j1
        elif np.isfinite(l[t]):
            run_min = min(run_min, float(l[t]))
        run_t = t
        if not math.isfinite(run_min):
            continue
        hh = vv[p] > vv[p + 2]
        hl = run_min > vv[p + 1]
        H1[t], L1[t], H0[t], PL[t] = vv[p], vv[p + 1], vv[p + 2], run_min
        ok[t] = hh and hl
        bear[t] = (vv[p] < vv[p + 2]) and (run_min < vv[p + 1])
        code[t] = 0 if ok[t] else (1 if hl else (2 if hh else 3))
    return ok, bear, code, H0, L1, H1, PL


def _r(x, nd=2):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def struct_check(h, l, k: int = K_STRUCT) -> dict:
    """最後一根（今天）的結構 → {ok, bear, H0, L1, H1, pull_low, reason}"""
    ok, bear, code, H0, L1, H1, PL = struct_series(h, l, k)
    if not len(ok):
        return {"ok": False, "bear": False, "H0": None, "L1": None, "H1": None, "pull_low": None, "reason": _REASONS[4]}
    return {"ok": bool(ok[-1]), "bear": bool(bear[-1]), "H0": _r(H0[-1]), "L1": _r(L1[-1]), "H1": _r(H1[-1]),
            "pull_low": _r(PL[-1]), "reason": _REASONS[int(code[-1])]}


# ── 2. 13:15 大盤盤面 ─────────────────────────────────────────────────────────
def _b_chg(v):
    return "≤−1%" if v <= -0.01 else "−1～0%" if v <= 0 else "0～+1%" if v < 0.01 else "≥+1%"


def _b_r5(v):
    return "≤−3%" if v <= -0.03 else "−3～0%" if v <= 0 else "0～+3%" if v < 0.03 else "≥+3%"


def _b_sox(v):
    return "≤−2%" if v <= -0.02 else "−2～0%" if v <= 0 else ">0%"


def sox_change(dates, closes, today: str) -> Optional[float]:
    """前一晚費半：美國日期 < 台灣今天（YYYY-MM-DD）的最後一筆 ÷ 再前一筆 − 1（週一＝美國週五；美國休市＝再往前）"""
    ds = [str(d)[:10] for d in dates]
    cs = [float(c) for c in closes]
    keep = [i for i, d in enumerate(ds) if d < today and cs[i] > 0]
    if len(keep) < 2:
        return None
    a, b = cs[keep[-1]], cs[keep[-2]]
    return a / b - 1


def market_features(dh, dl, dc, snap: dict, sox: Optional[float]) -> Optional[dict]:
    """dh/dl/dc＝加權日 K 的高低收（舊→新，到昨天為止）；snap＝{o, h, l, x, y}（13:15）；sox＝前一晚費半漲跌（小數）
    回傳特徵 dict（算不出來的族＝None）；snap 不完整＝None"""
    try:
        o, h, l, x = (float(snap[k]) for k in ("o", "h", "l", "x"))
    except (KeyError, TypeError, ValueError):
        return None
    dh, dl, dc = (np.asarray(a, dtype=float) for a in (dh, dl, dc))
    try:
        y = float(snap.get("y"))
    except (TypeError, ValueError):
        y = None
    if not y or not math.isfinite(y) or y <= 0:
        y = float(dc[-1]) if len(dc) and np.isfinite(dc[-1]) and dc[-1] > 0 else None
    if not y or not all(math.isfinite(v) and v > 0 for v in (o, h, l, x)):
        return None
    h, l = max(h, x, o), min(l, x, o)
    f = {"x": round(x, 2), "y": round(y, 2), "o": round(o, 2), "h": round(h, 2), "l": round(l, 2)}
    chg = x / y - 1
    f["chg"] = round(chg, 5)
    f["M1"] = _b_chg(chg)
    f["M2"] = ("開高" if o > y else "開低") + ("走高" if x > o else "走低")
    pos = (x - l) / (h - l) if h > l else 0.5
    f["pos"] = round(pos, 3)
    f["M3"] = "下 1/3" if pos < 1 / 3 else "上 1/3" if pos > 2 / 3 else "中間"
    # 大盤日線結構：昨天以前日 K＋今天到 13:15 那根
    f["M4"] = None
    if len(dc) >= 30:
        st = struct_check(np.append(dh, h), np.append(dl, l))
        f["M4"] = "多頭" if st["ok"] else "空頭" if st["bear"] else ("盤整" if st["reason"] != _REASONS[4] else None)
    # 均線（收盤到昨天＋13:15 當今天）
    f["M5"] = None
    if len(dc) >= 59:
        cc = np.append(dc[-59:], x)
        ma20, ma60 = cc[-20:].mean(), cc.mean()
        f["ma20"], f["ma60"] = round(float(ma20), 2), round(float(ma60), 2)
        up = int(x > ma20) + int(x > ma60)
        f["M5"] = "兩條都站上" if up == 2 else "只站上一條" if up == 1 else "都跌破"
    f["M6"] = None
    if len(dc) >= 5 and dc[-5] > 0:
        r5 = x / dc[-5] - 1
        f["r5"] = round(float(r5), 5)
        f["M6"] = _b_r5(r5)
    f["sox"] = None if sox is None else round(float(sox), 5)
    f["M7"] = None if sox is None or not math.isfinite(sox) else _b_sox(sox)
    # 波動：前 20 日報酬標準差 vs 過去 250 天（滾動、只用昨天以前）每天這個值的 2/3 分位
    f["M8"] = None
    if len(dc) >= 271 and np.all(np.isfinite(dc[-271:])) and np.all(dc[-271:] > 0):
        r = dc[1:] / dc[:-1] - 1
        sd = np.array([r[i - 20:i].std(ddof=1) for i in range(len(r) - 249, len(r) + 1)])
        f["sd20"] = round(float(sd[-1]), 5)
        f["M8"] = "高波動" if sd[-1] >= np.quantile(sd, 2 / 3) else "一般"
    f["M9"] = None if f["M4"] is None else f"{f['M4']}·{'漲' if chg > 0 else '跌'}"
    return f


def snap_from_5sec(rows) -> Optional[dict]:
    """證交所 MI_5MINS_INDEX 的 data（[[時間, 加權指數, …], …]）→ 13:15 快照 {y, o, h, l, x}
    09:00:00 那筆＝昨收（還沒成交）、開盤＝第一筆 09:00:05 之後的值；高低＝13:15:00 以前（含）"""
    y = o = x = None
    hi, lo = -math.inf, math.inf
    for r in rows or []:
        t = str(r[0]).strip()
        try:
            v = float(str(r[1]).replace(",", ""))
        except (TypeError, ValueError, IndexError):
            continue
        if t.startswith("09:00:00"):
            y = v
            continue
        if t > "13:15:00":
            break
        if o is None:
            o = v
        hi, lo = max(hi, v), min(lo, v)
        if t == "13:15:00":
            x = v
    if o is None or x is None:
        return None
    return {"y": y, "o": o, "h": hi, "l": lo, "x": x}


def describe(f: Optional[dict]) -> str:
    """一行白話：大盤 13:15 43,210（−1.2%）開高走低｜日線空頭｜月線、季線都跌破"""
    if not f:
        return "大盤資料抓不到"
    ma = {"兩條都站上": "站上月線、季線", "只站上一條": "月線季線只站上一條", "都跌破": "月線、季線都跌破"}.get(f.get("M5"), "")
    parts = [f"大盤 13:15 {f['x']:,.0f}（{f['chg'] * 100:+.2f}%）{f['M2']}"]
    if f.get("M4"):
        parts.append(f"日線{f['M4']}")
    if ma:
        parts.append(ma)
    return "｜".join(parts)


# ── 3. 盤勢判斷 ───────────────────────────────────────────────────────────────
_CACHE = {"mtime": None, "data": None}


def load_research(path: Optional[Path] = None) -> dict:
    p = Path(path or RESEARCH_PATH)
    try:
        mt = p.stat().st_mtime
    except OSError:
        return {}
    if _CACHE["mtime"] != (str(p), mt):
        try:
            _CACHE["data"] = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            _CACHE["data"] = {}
        _CACHE["mtime"] = (str(p), mt)
    return _CACHE["data"] or {}


def verdict(f: Optional[dict], research: Optional[dict] = None) -> dict:
    """→ {label: good|bad|neutral|nodata, rules: [碰到的規則]}；只用研究「通過」的規則"""
    if not f:
        return {"label": "nodata", "rules": []}
    rules = (research if research is not None else load_research()).get("rules") or []
    hit = [r for r in rules if r.get("pass") and f.get(r.get("family")) == r.get("bucket")]
    bad = [r for r in hit if r.get("side") == "bad"]
    good = [r for r in hit if r.get("side") == "good"]
    if bad:
        return {"label": "bad", "rules": bad}
    if good:
        return {"label": "good", "rules": good}
    return {"label": "neutral", "rules": []}


LABEL_TEXT = {"good": "✅ 適合", "bad": "⚠ 不適合", "neutral": "— 一般", "nodata": "大盤資料缺"}
