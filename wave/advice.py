"""B76 條件式操作建議（PLAN-B76 §4）：純函式，輸入快照（含多週期一覽），輸出持股範圍＋四句白話＋條件。
這是規則推出來的部位紀律參考，不是預測：回測只有夜盤、費半對隔天有效，波浪／撐壓／籌碼都沒有預測力。"""
from __future__ import annotations

import logging
from typing import Optional

from .plain import plain

log = logging.getLogger(__name__)
# 跟總經面板 regime-frontend SUGGESTIONS 同一張表（持股比例）
BASE = (("健康多頭", 70, 100), ("多頭過熱", 40, 60), ("恐慌竭盡", 20, 40), ("極端風險", 0, 20), ("空頭", 0, 20))
DEFAULT = (30, 50)
ALIGN_TF = ("60m", "1d", "1wk")
TF_NAME = {"15m": "15 分", "30m": "30 分", "60m": "60 分", "1d": "日 K", "1wk": "週 K"}
MERGE_PCT = 0.002          # 兩個條件價位差 < 0.2% 合併（審查 Gemini 低優先）
MAX_RISKS = 3


def r5(x: float) -> int:
    return int(round(x / 5.0) * 5)


def base_range(regime: Optional[str]) -> tuple:
    for k, lo, hi in BASE:
        if regime and k in regime:
            return lo, hi
    return DEFAULT


def exposure(regime: Optional[str], dirs: dict, overheat: Optional[float]) -> dict:
    """持股範圍：基準＝總經；60 分、日 K、週 K 都上漲段 → 上半段；都下跌段 → 下半段；不一致 → 整段；過熱 ≥50% 且都上漲 → 上限壓到中點"""
    blo, bhi = base_range(regime)
    mid = r5((blo + bhi) / 2)
    lo, hi, why = blo, bhi, []
    if not regime:
        why.append("總經資料暫缺，用 30～50% 當基準")
    ds = [dirs.get(k) for k in ALIGN_TF if dirs.get(k) in (1, -1)]
    if len(ds) >= 2 and all(d == 1 for d in ds):
        lo, hi = mid, bhi
        why.append("60 分、日 K、週 K 都在上漲段 → 用上半段")
        if overheat is not None and overheat >= 0.5:
            lo, hi = blo, mid
            why.append(f"但過熱指數 {overheat * 100:.0f}% ≥ 50% → 不追高，上限壓到 {mid}%")
    elif len(ds) >= 2 and all(d == -1 for d in ds):
        lo, hi = blo, mid
        why.append("60 分、日 K、週 K 都在下跌段 → 用下半段")
    else:
        why.append("各週期方向不一致 → 用整段，等方向一致再調")
    return {"lo": lo, "hi": hi, "base_lo": blo, "base_hi": bhi, "mid": r5((lo + hi) / 2), "why": why}


def _dir_word(d) -> str:
    return "上漲段" if d == 1 else "下跌段" if d == -1 else "方向不明"


def headline(dirs: dict) -> str:
    big, mid_, small = dirs.get("1wk"), dirs.get("1d"), dirs.get("60m")
    if big == 1 and small == 1:
        return "大小週期都往上" if mid_ != -1 else "大方向往上、日 K 回檔中、60 分已轉上"
    if big == -1 and small == -1:
        return "大小週期都往下" if mid_ != 1 else "大方向往下、日 K 反彈中、60 分已轉下"
    if big == -1 and small == 1:
        return "大方向還在修正、短線反彈"
    if big == 1 and small == -1:
        return "大方向往上、短線回檔"
    return "方向還不清楚"


def ladder_summary(rows: list) -> str:
    """小週期 → 大週期一句話"""
    parts = [f"{TF_NAME[r['tf']]}{'↑' if r.get('dir') == 1 else '↓' if r.get('dir') == -1 else '－'}" for r in rows]
    d = {r["tf"]: r.get("dir") for r in rows}
    return "、".join(parts) + " → " + headline(d)


def _cands(snap: dict, price: float) -> tuple:
    """上方／下方條件價位：60 分／日 K／週 K 的轉折點（還沒過的）＋日 K 撐壓"""
    key, lv = snap.get("key") or {}, snap.get("levels") or {}
    up, dn = [], []
    for k, nm in (("ultra", "60 分"), ("short", "日 K"), ("swing", "週 K")):
        x = key.get(k)
        if not x or x.get("broken") or x.get("price") is None:
            continue
        item = {"price": float(x["price"]), "label": f"{nm}{x['kind']}", "rank": {"ultra": 1, "short": 2, "swing": 3}[k]}
        (up if x["side"] == "above" else dn).append(item)
    sh = lv.get("short") or {}
    r1 = (sh.get("resistance") or [None])[0]
    s1 = (sh.get("support") or [None])[0]
    if r1:
        up.append({"price": float(r1["price"]), "label": "日 K 壓力", "rank": 2})
    if s1:
        dn.append({"price": float(s1["price"]), "label": "日 K 支撐", "rank": 2})
    up = [x for x in up if x["price"] > price]
    dn = [x for x in dn if x["price"] < price]

    def merge(lst, rev):
        lst = sorted(lst, key=lambda x: -x["price"] if rev else x["price"])
        out = []
        for x in lst:
            if out and abs(x["price"] / out[-1]["price"] - 1) < MERGE_PCT:
                if x["label"] not in out[-1]["label"]:
                    out[-1]["label"] += "＋" + x["label"]
                out[-1]["rank"] = max(out[-1]["rank"], x["rank"])
                continue
            out.append(dict(x))
        return out
    return merge(up, False), merge(dn, True)


def _risks(snap: dict, oh: Optional[dict]) -> list:
    out = []
    ch = snap.get("chips") or {}
    fs = ch.get("f_streak") or 0
    if abs(fs) >= 3:
        out.append(f"外資連{'買' if fs > 0 else '賣'} {abs(fs)} 天（5 天 {ch.get('f5') or 0:+,.0f} 億）")
    if ch.get("fut_pct") is not None and ch["fut_pct"] < 0.2 and (ch.get("fut_f_oi") or 0) < 0:
        out.append(f"外資期貨淨空 {abs(ch['fut_f_oi']):,.0f} 口，在近一年最空的兩成內")
    mg = snap.get("margin") or {}
    if mg.get("ok") and abs(mg.get("streak") or 0) >= 3:
        st_ = mg["streak"]
        out.append(f"融資連{'增' if st_ > 0 else '減'} {abs(st_)} 天（{'散戶加碼' if st_ > 0 else '籌碼變乾淨'}）")
    if oh:
        if (oh.get("overheating") or 0) >= 0.5:
            out.append(f"過熱指數 {oh['overheating'] * 100:.0f}%（≥50%，追高風險）")
        if (oh.get("panic") or 0) >= 0.75:
            out.append(f"恐慌指數 {oh['panic'] * 100:.0f}%（≥75%，賣單幾乎全成交）")
    return out


def build(snap: dict) -> dict:
    """snap：service 算好的快照（要有 ladder、key、levels、context、chips、margin、open_ref／global）"""
    try:
        price = float(snap["price"])
        ctx = snap.get("context") or {}
        regime = (ctx.get("regime") or {}).get("label")
        oh = ctx.get("oh")
        rows = snap.get("ladder") or []
        dirs = {r["tf"]: r.get("dir") for r in rows}
        rg = exposure(regime, dirs, (oh or {}).get("overheating"))
        waves, key = snap.get("waves") or {}, snap.get("key") or {}
        name = "台指期" if snap.get("sym") == "TX" else "加權"
        lines = []
        # ① 大方向
        wk = plain((waves.get("mid") or {}).get("primary"))
        s = f"總經「{regime or '資料暫缺'}」（基本建議持股 {rg['base_lo']}～{rg['base_hi']}%）；週 K：{wk['title'] if wk else '結構不清楚'}"
        if ctx.get("box"):
            s += f"；均線格局「{ctx['box']}」"
        if ctx.get("mslope"):
            s += f"、月線{ctx['mslope'].get('tier') or ''}"
        if ctx.get("crash") and ctx["crash"].get("deep"):
            s += "；出現深跌訊號（過去 5 次有 4 次之後 2～6 個月是賺的）"
        lines.append({"k": "大方向", "t": s})
        # ② 短線
        dk = plain((waves.get("small") or {}).get("primary"))
        hk = plain((waves.get("intra") or {}).get("primary"))
        k1, k60 = key.get("short"), key.get("ultra")
        s = f"日 K：{dk['title'] if dk else '結構不清楚'}"
        if k1:
            s += f"，{k1['kind']} {k1['price']:,.0f}（{k1['dist_pct']:+.1f}%）"
        s += f"；60 分 K：{hk['title'] if hk else '資料不足'}"
        if k60:
            s += (f"，已{'跌破' if k60['side'] == 'below' else '站上'}{k60['kind']} {k60['price']:,.0f}" if k60.get("broken")
                  else f"，{k60['kind']} {k60['price']:,.0f}")
        lines.append({"k": "短線", "t": s})
        # ③ 明天／今天
        o = snap.get("open_ref")
        so = (snap.get("global") or {}).get("sox_overnight")
        if o:
            when = "夜盤進行中（即時）" if o.get("live") else "夜盤"
            lines.append({"k": "明天" if o.get("live") else "今天",
                          "t": f"{when} {o['night_ret']:+.2f}% → 加權開盤參考 {o['gap']:+.2f}%（±{o['gap_sd']:.1f}%）、收盤參考 {o['r1']:+.2f}%（回測有效 ✅）"})
        elif so and so.get("tw_expect") is not None:
            lines.append({"k": "今天", "t": f"前一晚費半 {so['sox_ret']:+.2f}% → 加權隔天平均 {so['tw_expect']:+.2f}%（±{so['sd']:.1f}%，回測有效 ✅）"})
        # ④ 風險
        risks = _risks(snap, oh)
        more = max(0, len(risks) - MAX_RISKS)
        lines.append({"k": "風險", "t": "；".join(risks[:MAX_RISKS]) + (f"；等 {more} 項" if more else "") if risks else "沒有特別警訊"})
        # 條件
        up, dn = _cands(snap, price)
        conds = []
        if up:
            conds.append({"side": "up", "price": up[0]["price"], "label": up[0]["label"], "act": f"站上 → 轉強，可往 {rg['hi']}% 靠"})
        if len(up) > 1:
            conds.append({"side": "up", "price": up[1]["price"], "label": up[1]["label"],
                          "act": f"再站上 → 更大的週期也轉強，上限 {rg['base_hi']}%"})
        if dn:
            conds.append({"side": "down", "price": dn[0]["price"], "label": dn[0]["label"], "act": f"跌破 → 轉弱，先減到 {rg['mid']}%"})
        if len(dn) > 1:
            nxt = f"，下一個看 {dn[2]['price']:,.0f}" if len(dn) > 2 else ""
            conds.append({"side": "down", "price": dn[1]["price"], "label": dn[1]["label"], "act": f"再跌破 → 降到 {rg['lo']}%{nxt}"})
        return {"ok": True, "range": rg, "headline": f"建議持股 {rg['lo']}～{rg['hi']}%：{headline(dirs)}", "lines": lines,
                "risks": risks, "conds": conds, "cond_note": "" if conds else "附近沒有系統價位",
                "name": name,
                "note": "規則推出來的部位紀律參考，不是預測：回測只有夜盤、前一晚費半對隔天有效，波浪、支撐壓力、籌碼都沒有預測力"}
    except Exception as e:     # noqa: BLE001
        log.warning(f"[wave] 操作建議失敗：{e}")
        return {"ok": False}
