"""B80 價位梯＋如果…就…＋三條路（PLAN-B80 §6.1、§6.2；學 @fanny55520 9/22～10/8 的寫法）：純函式
- 每個週期一份：把撐壓、轉折點、多層浪名的關卡與換數法價位、波浪目標與失效、日線母尺、成交密集區放在同一條價位梯，
  0.15% 內併成一列，每一列寫「站上／跌破代表什麼」（優先：換數法 > 關卡 > 轉折點 > 失效 > 目標 > 母尺 > 成交密集區 > 一般撐壓）
- 目標 T1～T3：現在這段方向上、窗口 1.5 倍內的目標，由近到遠；目標之間的撐壓＝過渡壓力（容易先震盪換手）
- 反方向照距離排第一／第二／第三落點
- 如果…就…：有「換數法／關卡」意義的價位，上方由近到遠、下方「跌破 D1、守住 D2」「跌破 D2」
- 三條路：轉強（站上 U1 → 回測不破 → 再站上 U2）／震盪（D1～U1）／轉弱（跌破 D1 → 反彈收不回 → 再跌破 D2）
這些是「怎麼顯示」的規則，不宣稱有預測力（跟 B74 撐壓一樣 △）"""
from __future__ import annotations

from typing import Optional

MERGE = 0.0015
CONFL = 0.002
PER_SIDE = 4
PRIO = {"rule": 1, "gate": 2, "key": 3, "inv": 4, "target": 5, "mother": 6, "zone": 7, "level": 8}
STRUCT = ("rule", "gate", "key", "inv", "mother")
VNAME = ("版本一", "版本二", "版本三")
RETEST = 0.001


def _f(p) -> str:
    return f"{float(p):,.0f}"


def _src_text(z: dict) -> str:
    seen, parts = set(), []
    for s in z.get("sources") or []:
        t = str(s.get("label") or "")
        for pre in ("小級", "中級", "大級"):
            if t.startswith(pre):
                t = t[len(pre):]
        t = t.replace("整數關卡", "整數")
        if t and t not in seen:
            seen.add(t)
            parts.append(t)
        if len(parts) >= 3:
            break
    more = len(z.get("sources") or []) - len(parts)
    return "＋".join(parts) + (f" 等 {len(z['sources'])} 個" if more > 0 else "")


def _verb(side: str) -> str:
    return "跌破" if side == "below" else "漲過"


def candidates(ctx: dict) -> list:
    """ctx：price、levels、key、nest、wave（primary／alternate）、positioning、zones、win → [{price, kind, name, act, src, ...}]"""
    px = float(ctx["price"])
    win = float(ctx.get("win") or 0.03)
    out = []
    lv = ctx.get("levels") or {}
    for side, nm in (("support", "支撐"), ("resistance", "壓力")):
        for z in lv.get(side) or []:
            if z.get("price") is None:
                continue
            out.append({"price": float(z["price"]), "kind": "level", "name": nm, "src": _src_text(z),
                        "strong": len(z.get("sources") or []) >= 2})
    k = ctx.get("key")
    if k and k.get("price") is not None:
        below = k.get("side") == "below"
        act = ("跌破 → 這段上漲可能結束（停損參考）" if below else "站上 → 這段下跌可能結束（停損參考）")
        if k.get("broken"):
            act = ("已經跌破 → " if below else "已經站上 → ") + act.split("→ ")[1]
        out.append({"price": float(k["price"]), "kind": "key", "name": k.get("kind") or "轉折點", "act": act,
                    "src": "這段走勢裡最近一個反向的小轉折"})
    nz = ctx.get("nest") or {}
    if nz.get("ok"):
        vers = [(nm, nz.get(key)) for nm, key in zip(VNAME, ("primary", "alternate", "third")) if nz.get(key)]
        for nm, c in vers:
            for r in c.get("rules") or []:
                if r.get("price") is None:
                    continue
                out.append({"price": float(r["price"]), "kind": "rule", "name": "換數法", "ver": nm, "path": c.get("path"),
                            "verb": _verb(r.get("side")), "why": r.get("why") or "", "src": f"{nm}：{r.get('why') or ''}"})
            if nm == "版本一":
                for tg in c.get("targets") or []:
                    if tg.get("kind", "end") == "end" and tg.get("price") is not None:
                        out.append({"price": float(tg["price"]), "kind": "target", "name": "目標", "src": tg.get("label") or ""})
        for g in nz.get("gates") or []:
            if g.get("price") is None or g.get("k") == "目標":
                continue
            t = str(g.get("t") or "")
            if "）→" in t:                                  # 「站穩 X（a→b 整段的 0.382）→ 確認轉浪」：括號裡的箭頭不算
                act = t.split("）→", 1)[1].strip()
            elif "→" in t:
                act = t.split("→", 1)[1].strip()
            else:
                act = t
            name = "趨勢線" if g["k"] == "前提" else g["k"]
            out.append({"price": float(g["price"]), "kind": "gate", "name": name, "gate_act": act[:60], "src": "",
                        "ok": bool(g.get("ok"))})
    w = ctx.get("wave") or {}
    prim, alt = w.get("primary"), w.get("alternate")
    if prim and not nz.get("ok"):
        for tg in prim.get("targets") or []:
            if tg.get("kind") == "end" and tg.get("price") is not None:
                out.append({"price": float(tg["price"]), "kind": "target", "name": "目標", "src": tg.get("label") or "波浪目標"})
        inv = prim.get("invalid")
        if inv is not None and abs(float(inv) / px - 1) <= 2 * win:
            surv = f"，替代劇本（{alt.get('text')}）升為主要" if alt and alt.get("text") else ""
            out.append({"price": float(inv), "kind": "inv", "name": "劇本失效",
                        "act": f"{_verb(prim.get('invalid_side'))} → 主要劇本作廢{surv}", "src": prim.get("text") or ""})
    pos = ctx.get("positioning") or {}
    MOTHER = {"0.382": ("母尺 0.382", "{w}超過 0.382，還在正常範圍，下一個看第一防守區 0.5"),
              "0.5": ("第一防守區 0.5", "第一防守區失守，下一個看第二極限防守區 0.618"),
              "0.618": ("第二極限防守區 0.618", "第二極限防守區失守，下一個看鐵律底線")}
    for r, v in (pos.get("levels") or {}).items():
        nm, mean = MOTHER.get(r, (f"母尺 {r}", "回到母尺的 " + r))
        below = float(v) < px
        out.append({"price": float(v), "kind": "mother", "name": nm, "src": "前一段當母尺（她的日線定位）",
                    "act": f"{'跌破' if below else '站上'} → " + mean.format(w="回檔" if below else "反彈")})
    if pos.get("iron") is not None:
        out.append({"price": float(pos["iron"]), "kind": "mother", "name": "鐵律底線", "src": "前一段的起點",
                    "act": f"{'跌破' if float(pos['iron']) < px else '漲過'} → 不是正常的回檔／反彈，母級結構作廢"})
    for z in ctx.get("zones") or []:
        out.append({"price": float(z["mid"]), "kind": "zone", "name": "成交密集區",
                    "src": f"{_f(z['lo'])}～{_f(z['hi'])}（{'這段時間 ' + str(round(z['share'] * 100)) + '% 的量' if z.get('by') == 'vol' else '停留最久'}）"})
    return [x for x in out if x["price"] > 0]


def _merge(cands: list, px: float) -> list:
    cands = sorted(cands, key=lambda x: x["price"])
    groups: list = []
    for x in cands:
        if groups and abs(x["price"] - groups[-1][-1]["price"]) <= MERGE * px:
            groups[-1].append(x)
        else:
            groups.append([x])
    items = []
    for g in groups:
        g = sorted(g, key=lambda x: PRIO[x["kind"]])
        main = g[0]
        items.append({"price": round(main["price"], 2), "kind": main["kind"], "parts": g,
                      "struct": any(x["kind"] in STRUCT for x in g),
                      "side": "up" if main["price"] > px else "down", "dist_pct": round((main["price"] / px - 1) * 100, 2)})
    return items


def _rule_act(parts: list, versions: list) -> Optional[str]:
    rules = [p for p in parts if p["kind"] == "rule"]
    if not rules:
        return None
    killed = []
    for r in rules:
        if r["ver"] not in killed:
            killed.append(r["ver"])
    surv = [v for v in versions if v[0] not in killed]
    verb = rules[0]["verb"]
    names = dict.fromkeys(f"{r['ver']}（{r['path']}）" for r in rules if r["ver"] in killed[:2])   # 同一版本兩條規則併在一列 → 只寫一次（審查 Gemini F2）
    s = f"{verb} → " + "、".join(names) + " 作廢"
    if surv and killed:
        s += f"，{surv[0][0]}（{surv[0][1]}）升為主要"
    return s


def build(ctx: dict) -> dict:
    """→ {items（上到下）, up, down, targets, top3, decision, steps}"""
    px = float(ctx["price"])
    win = float(ctx.get("win") or 0.03)
    leg = ctx.get("leg_dir") or 0
    nz = ctx.get("nest") or {}
    versions = [(nm, (nz.get(k) or {}).get("path")) for nm, k in zip(VNAME, ("primary", "alternate", "third")) if nz.get(k)]
    items = _merge(candidates(ctx), px)
    # 目標 T1～T3（現在這段方向、窗口 1.5 倍內）
    tdir = "up" if leg > 0 else "down" if leg < 0 else None
    tg_items = sorted([it for it in items if tdir and it["side"] == tdir and any(p["kind"] == "target" for p in it["parts"])
                       and abs(it["dist_pct"]) <= 150 * win], key=lambda it: abs(it["dist_pct"]))[:3]
    for n, it in enumerate(tg_items):
        it["t"] = f"T{n + 1}"
        it["tlabel"] = next(p["src"] for p in it["parts"] if p["kind"] == "target")
        others = [p["name"] for p in it["parts"] if p["kind"] != "target"]
        it["confl"] = "、".join(dict.fromkeys(others))
    far = abs(tg_items[-1]["dist_pct"]) if tg_items else 0
    for it in items:
        if tdir and it["side"] == tdir and not it.get("t") and it["kind"] in ("level", "zone") and abs(it["dist_pct"]) < far:
            it["transit"] = True
    # 反方向落點
    odir = "down" if tdir == "up" else "up" if tdir == "down" else None
    if odir:
        opp = sorted([it for it in items if it["side"] == odir and it["kind"] in ("level", "zone", "mother", "target")],
                     key=lambda it: abs(it["dist_pct"]))
        for n, it in enumerate(opp[:3]):
            it["land"] = ("回檔" if odir == "down" else "反彈") + ("第一", "第二", "第三")[n] + ("落點" if odir == "down" else "壓力")
    # 每邊挑 4 個：一定包含最近的、轉折點、T1；其他照意義優先、再照距離
    sel = []
    for side in ("up", "down"):
        xs = sorted([it for it in items if it["side"] == side], key=lambda it: abs(it["dist_pct"]))
        must = [xs[0]] if xs else []
        must += [it for it in xs if it["kind"] == "key" or it.get("t") == "T1"]
        rest = sorted([it for it in xs if it not in must], key=lambda it: (0 if it["struct"] else 1, abs(it["dist_pct"]), PRIO[it["kind"]]))
        pick = []
        for it in must + rest:
            if it not in pick:
                pick.append(it)
            if len(pick) >= PER_SIDE:
                break
        sel += pick
    sel.sort(key=lambda it: -it["price"])
    up = sorted([it for it in sel if it["side"] == "up"], key=lambda it: it["price"])
    dn = sorted([it for it in sel if it["side"] == "down"], key=lambda it: -it["price"])
    vol_ok = bool(ctx.get("vol_ok"))
    vol_hint_done = {"up": False, "down": False}
    for side, xs in (("up", up), ("down", dn)):
        for n, it in enumerate(xs):
            nxt = xs[n + 1]["price"] if n + 1 < len(xs) else None
            it.update(_describe(it, side, nxt, versions))
            if not vol_hint_done[side] and it["struct"] and it["kind"] != "mother":
                verb = "站上" if side == "up" else "跌破"
                it["vol"] = f"要帶量（≥1.3 倍）{verb}才算" if vol_ok else f"帶量{verb}更可信（回測 △）"
                vol_hint_done[side] = True
    out_items = [{k: v for k, v in it.items() if k != "parts"} for it in sel]
    pick = lambda xs: next((it for it in xs if it["struct"]), xs[0] if xs else None)   # noqa: E731
    key_it = next((it for it in sel if it["kind"] == "key" or any(p["kind"] == "key" for p in it["parts"])), None)
    pu, pd_ = pick(up), pick(dn)
    top = {"up": _slim(pu), "down": _slim(pd_), "stop": _slim(key_it)}
    for side, it, xs in (("down", pd_, dn), ("up", pu, up)):
        if key_it is not None and it is key_it:
            k = xs.index(it)
            nxt = next((x for x in xs[k + 1:] if x["struct"]), xs[k + 1] if k + 1 < len(xs) else None)
            if nxt is not None:
                top.update(stop=_slim(nxt), stop_same=side)
            elif k > 0:                               # 轉折點是那邊最遠的 → 第三格改放途中先遇到的價位（不再兩格同價）
                top.update(stop=_slim(xs[0]), stop_same=side, stop_pos="before")
            # 那邊只有轉折點一個價位 → 停損那格照舊顯示轉折點（審查 Gemini F1）
            break
    up_all = sorted([it for it in items if it["side"] == "up"], key=lambda it: it["price"])
    dn_all = sorted([it for it in items if it["side"] == "down"], key=lambda it: -it["price"])
    for side, xs in (("up", up_all), ("down", dn_all)):
        for n, it in enumerate(xs):
            if "act" not in it:
                it.update(_describe(it, side, xs[n + 1]["price"] if n + 1 < len(xs) else None, versions))
    return {"price": px, "items": out_items, "targets": [_slim(it) for it in tg_items], "top3": top,
            "decision": decision(up_all, dn_all, versions, vol_ok), "steps": steps(up, dn, px, ctx.get("hlc"))}


def _slim(it: Optional[dict]) -> Optional[dict]:
    if not it:
        return None
    return {k: it.get(k) for k in ("price", "dist_pct", "name", "act", "side", "kind", "t", "vol") if it.get(k) is not None}


def _describe(it: dict, side: str, nxt: Optional[float], versions: list) -> dict:
    parts = it["parts"]
    names = []
    for p in parts:
        if p["kind"] == "rule":
            nm = "換數法"
        elif p["kind"] == "target":
            continue
        else:
            nm = p["name"]
        if nm not in names:
            names.append(nm)
    if it.get("t"):
        names.insert(0, it["t"])
    if it.get("transit"):
        names.append("過渡壓力" if side == "up" else "過渡支撐")
    if it.get("land"):
        names.append(it["land"])
    act = _rule_act(parts, versions)
    if act is None:
        g = next((p for p in parts if p["kind"] == "gate"), None)
        if g:
            act = f"{'站上' if side == 'up' else '跌破'} → {g['gate_act']}" if g.get("gate_act") else None
    if act is None:
        x = next((p for p in parts if p["kind"] in ("key", "inv", "mother") and p.get("act")), None)
        act = x["act"] if x else None
    if act is None and it.get("t"):
        act = f"{it['t']}：{it['tlabel']}" + ("；到了先出一半（走一口留一口）" if it["t"] == "T1" else "")
        if it.get("confl"):
            act += f"（跟{it['confl']}重疊）"
    if act is None and it.get("transit"):
        act = "目標之間的關卡，容易先震盪換手"
    if act is None:
        verb = "站上" if side == "up" else "跌破"
        act = f"{verb} → 下一個看 {_f(nxt)}" if nxt else f"{verb} → 附近沒有下一個系統價位"
    src = "；".join(dict.fromkeys(p["src"] for p in parts if p.get("src")))
    if len(src) > 90:
        src = src[:89] + "…"
    return {"name": "／".join(names[:3]) or ("壓力" if side == "up" else "支撐"), "act": act, "src": src,
            "strong": any(p.get("strong") for p in parts) or len(parts) >= 2}


def decision(up: list, dn: list, versions: list, vol_ok: bool) -> list:
    """如果…就…：有「換數法／關卡／轉折點／失效／母尺」意義的價位，上方 1 條、下方 2 條（跌破 D1 守住 D2、跌破 D2）"""
    U = [it for it in up if it.get("struct")]
    D = [it for it in dn if it.get("struct")]
    isrule = lambda it: any(p["kind"] == "rule" for p in it["parts"]) if "parts" in it else it.get("kind") == "rule"   # noqa: E731
    out = []
    extra = []
    for xs, side in ((U, "up"), (D, "down")):
        r = next((it for it in xs if isrule(it)), None)
        if r is not None and r not in xs[:2]:
            v = "站上" if side == "up" else "跌破"
            extra.append({"side": side, "if": f"{v} {_f(r['price'])}", "then": r["act"].split("→", 1)[-1].strip(), "price": r["price"]})
    if U:
        u = U[0]
        out.append({"side": "up", "if": f"站上 {_f(u['price'])}" + ("（帶量）" if vol_ok else ""), "then": u["act"].split("→", 1)[-1].strip(),
                    "price": u["price"]})
        if len(U) > 1:
            out.append({"side": "up", "if": f"再站上 {_f(U[1]['price'])}", "then": U[1]["act"].split("→", 1)[-1].strip(), "price": U[1]["price"]})
    if len(D) >= 2:
        out.append({"side": "down", "if": f"跌破 {_f(D[0]['price'])}、守住 {_f(D[1]['price'])}", "then": D[0]["act"].split("→", 1)[-1].strip(),
                    "price": D[0]["price"]})
        out.append({"side": "down", "if": f"跌破 {_f(D[1]['price'])}", "then": D[1]["act"].split("→", 1)[-1].strip(), "price": D[1]["price"]})
    elif D:
        out.append({"side": "down", "if": f"跌破 {_f(D[0]['price'])}", "then": D[0]["act"].split("→", 1)[-1].strip(), "price": D[0]["price"]})
    out = out[:4] + extra
    ups = sorted([x for x in out if x["side"] == "up"], key=lambda x: x["price"])
    dns = sorted([x for x in out if x["side"] == "down"], key=lambda x: -x["price"])
    return ups + dns


def _crossed_then(hlc, lv: float, up: bool):
    """最近一次收盤越過 lv 之後：有沒有回測（碰到 0.1% 內又收在同一邊）"""
    if not hlc:
        return None
    h, l, c = hlc
    n = len(c)
    k0 = None
    for k in range(n - 1, 0, -1):
        if (up and c[k] > lv >= c[k - 1]) or (not up and c[k] < lv <= c[k - 1]):
            k0 = k
            break
    if k0 is None:
        return None
    for k in range(k0 + 1, n):
        if up and l[k] <= lv * (1 + RETEST) and c[k] >= lv:
            return True
        if not up and h[k] >= lv * (1 - RETEST) and c[k] <= lv:
            return True
    return False


def steps(up: list, dn: list, px: float, hlc=None) -> dict:
    """三條路步驟清單：每步 {t, ok}；回測那步：越過後有回測守住＝✅；已經直接走到下一個價位＝✅（直接拉開，沒回測；R4 Gemini F2）"""
    def path(xs, is_up):
        if not xs:
            return []
        verb, verb2 = ("站上", "回測") if is_up else ("跌破", "反彈")
        u1 = xs[0]["price"]
        crossed = (px > u1) if is_up else (px < u1)
        out = [{"t": f"先{verb} {_f(u1)}", "ok": crossed}]
        rt = _crossed_then(hlc, u1, is_up) if crossed else None
        nxt = xs[1]["price"] if len(xs) > 1 else None
        ran = crossed and nxt is not None and ((px >= nxt) if is_up else (px <= nxt))
        out.append({"t": f"{verb2} {_f(u1)} {'不破' if is_up else '收不回'}", "ok": bool(rt) or ran,
                    "note": "直接拉開，沒回測" if ran and not rt else None})
        if nxt is not None:
            out.append({"t": f"{'帶量' if is_up else ''}再{verb} {_f(nxt)}", "ok": (px > nxt) if is_up else (px < nxt)})
        return out
    U = [it for it in up]
    D = [it for it in dn]
    rng = None
    if U and D:
        rng = {"t": f"{_f(D[0]['price'])}～{_f(U[0]['price'])} 之間來回", "ok": D[0]["price"] < px < U[0]["price"]}
    return {"up": path(U, True), "range": rng, "down": path(D, False)}
