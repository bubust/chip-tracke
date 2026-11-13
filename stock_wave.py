"""B93 她 11/4 的方法（@fanny55520 台指期）：多週期逐層驗證——小級的「大、中、小」五段＋兩道關卡；台指期跟個股共用。

她 11/4：47,607 起跌到 42,050 是 60 分「大、中、小」三段動能逐漸收斂（大 47,607→44,052、中 45,487→42,925、小 44,069→42,050）
- 第一道關（安全門）＝小級第 (1) 段終點 44,052（1、4 不重疊）＋整段 47,607→42,050 的 0.382（44,173）＋日線 5 均（44,154）：
  彈過並站穩＝這組跌勢在 42,050 走完五段、轉入修正反彈，短線連續破底的危機才化解；在這裡遇壓折返＝小級還沒跌完、還有破底段
- 第二道關＝大級第 (1) 段終點 45,523：大級第 (4) 段反彈在 0.5（44,829）～日線 10 均（45,357）～45,523 受阻 → 大級再殺第 (5) 段
  （或至少回測底部）；就算越過 45,523，也先當「大 B 波反彈震盪」，要站穩、回測、看籌碼換手才分辨
- 進場：短線看 0.382 有沒有真過，壓回的第二隻腳落在這段反彈的 0.382～0.5 才做多（還要技術面確認止跌），目標整段 0.5；追高沒有肉

級數：台指期＝日 K（大級）＋60 分（小級）；個股只有日 K → 大級＝日 K 中級轉折（平均一段約 38 天）、小級＝日 K 小級轉折（約 10 天）。
方向對稱：跌勢看反彈的關卡；漲勢（大級第 3 段創高）看拉回的關卡。只描述結構與價位，不是買賣建議。"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np


def _fmt(p) -> str:
    """千以上取整（四捨五入，44,828.5 → 44,829，跟她寫的一樣）；以下留兩位"""
    import math
    x = float(p)
    if abs(x) >= 1000:
        return f"{int(math.floor(x + 0.5)):,}"
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def _drop_smallest(seq: list) -> Optional[list]:
    """把最小的一段（相鄰兩個轉折）併掉；起點、極值、最後一點不動（同 wave.nest.drop_smallest）"""
    from wave.nest import drop_smallest
    return drop_smallest(seq)


def tentative(piv: list, h, l) -> Optional[dict]:
    """最後一個確認轉折之後、反方向走到現在的極值（還沒確認的轉折）"""
    if not piv:
        return None
    last = piv[-1]
    i0 = last["i"] + 1
    if i0 >= len(h):
        return None
    if last["t"] == "H":
        k = i0 + int(np.argmin(l[i0:]))
        return {"i": k, "p": float(l[k]), "t": "L"}
    k = i0 + int(np.argmax(h[i0:]))
    return {"i": k, "p": float(h[k]), "t": "H"}


def _fork(first_leg: Optional[list], T: dict, L1: dict, H2: dict, ext: float, d: int, lb: dict,
          contract: Optional[bool]) -> Optional[dict]:
    """B95 她 11/5：「46,107、45,523 不同的判斷落點，影響推敲日線定位」。
    first_leg＝小級轉折從 T 到 L1（大級第一段）。併到五段以後：
    ① 落在第 3 個轉折（46,107）＝小級 A-B-C（5-3-5）走完＝大級的 a，H2 是破底穿頭的 b，現在是 c（走完整段修正就結束）
    ② 落在 L1（45,523）＝小級五段 (1)～(5)＝大級第 (1) 段（或 A），現在是第 (3) 段（主跌）或 C（5-3-5 收尾）"""
    if not first_leg:
        return None
    F = [{"p": float(q["p"]), "t": q["t"]} for q in first_leg if q.get("p") is not None]
    if len(F) < 6 or F[0]["t"] != T["t"] or abs(F[0]["p"] / T["p"] - 1) > 0.002 or abs(F[-1]["p"] / L1["p"] - 1) > 0.002:
        return None
    while len(F) > 6:
        nxt = _drop_smallest(F)
        if nxt is None:
            break
        F = nxt
    a3 = F[3]["p"] if len(F) == 6 else None
    if a3 is None or (a3 - L1["p"]) * d >= 0:                          # L1 要比第 3 個轉折更遠（第 5 段破了 a 的終點）
        return None
    s_dn = "跌" if d < 0 else "漲"
    len3, len5 = abs(T["p"] - a3), abs(T["p"] - L1["p"])
    hit = lambda v: (ext - v) * d >= 0                                 # noqa: E731  這段已經走到

    def tg(label, v):
        return {"label": label, "price": round(v, 2), "hit": hit(v)}
    v3 = {"end": a3, "seq": [q["p"] for q in F[:4]],
          "targets": [tg("c＝a 等幅", H2["p"] + d * len3), tg("c＝1.618 倍 a", H2["p"] + d * 1.618 * len3)]}
    v5 = {"end": L1["p"], "seq": [q["p"] for q in F],
          "targets": [tg("C＝A 等幅", H2["p"] + d * len5), tg("第 (3) 段＝1.618 倍第 (1) 段", H2["p"] + d * 1.618 * len5)]}
    tt = lambda v: "、".join(f"{x['label']} {_fmt(x['price'])}" + ("（已到）" if x["hit"] else "") for x in v["targets"])  # noqa: E731
    b_word = f"破底穿頭的 b（中間{s_dn}到 {_fmt(L1['p'])}）" if d < 0 else f"穿頭破底的 b（中間{s_dn}到 {_fmt(L1['p'])}）"
    lines = [f"第一段落點兩種看法（她 11/5：{_fmt(a3)}、{_fmt(L1['p'])} 不同的判斷落點，會影響{lb['big']}定位）",
             f"① 落在 {_fmt(a3)}：{_fmt(T['p'])}→{_fmt(F[1]['p'])}→{_fmt(F[2]['p'])}→{_fmt(a3)} 是{lb['small']} A-B-C（5-3-5）＝{lb['big']}的 a，"
             f"{_fmt(a3)}→{_fmt(H2['p'])} 是{b_word}，{_fmt(H2['p'])} 起{s_dn}＝c：c 走完整段修正就結束（三段式）；{tt(v3)}",
             f"② 落在 {_fmt(L1['p'])}：{_fmt(T['p'])}→{_fmt(L1['p'])} 是{lb['small']}五段 (1)～(5)＝{lb['big']}第 (1) 段（或 A），"
             f"{_fmt(H2['p'])}＝(2)／B，{_fmt(H2['p'])} 起{s_dn}＝第 (3) 段（主{s_dn}，會很深）或 C（5-3-5 收尾）；{tt(v5)}"]
    if contract is True:
        lines.append(f"怎麼分：第 (3) 段通常比第 (1) 段更猛；現在{lb['small']}走成「大、中、小」動能遞減 → 比較像 C 浪五段收尾"
                     f"（網友的見底劇本，她回「推敲正確」），但還是要過兩道關卡才算數")
    elif contract is False:
        lines.append(f"怎麼分：第 (3) 段通常比第 (1) 段更猛；現在{lb['small']}沒有一段比一段小 → 第 (3) 段主{s_dn}還不能排除")
    else:
        lines.append(f"怎麼分：等{lb['small']}這組走完五段，看動能有沒有一段比一段小（遞減＝像 C 浪收尾，越來越猛＝第 (3) 段）")
    return {"a3": a3, "l1": L1["p"], "v3": v3, "v5": v5, "lines": lines}


def _push(after: list, d: int, ext: float, price: float, fib382: Optional[float], f382_lab: str,
          big_hi: Optional[float] = None, c1_low: Optional[float] = None, neck: Optional[float] = None,
          fine: Optional[list] = None) -> Optional[dict]:
    """B103 她 11/10 傍晚：極值之後這一腳如果是清楚的「小 5 段」（2 不破起點、3 不是最短、4 不碰 1）＝初推（第五大波的 (1) 浪或大 B／C-4 的小 a），
    接下來的壓回（(2) 或小 b）是三波整理、不會回到起點，整理完還有一段（(3) 或小 c）。壓回落在哪三種區：
    ① 時間換空間（強勢橫盤）：初推 0.236＋大級 0.382（41,830／41,481，她：守住日盤低點 41,873）
    ② 標準對稱：初推 0.382＋小 4 低點＋小 1 高點（41,040、40,715、40,690）
    ③ 深層 1 轉 2：初推 0.5～0.618（40,401～39,762）；實體跌破小 1 高點才往這裡，不破起點 37,694 結構都還在"""
    u = -d                                                            # 這一腳的方向（d＝-1 時往上）
    hs = [j for j, q in enumerate(after) if q["t"] == (after[0]["t"] if after else None)]
    if len(after) < 5 or not hs:
        return None
    def five(j):                                                      # 起點到 after[j] 併成五段、符合推動規則 → 那五段；不然 None
        sq = [{"p": ext, "t": "L" if u > 0 else "H"}] + [dict(q) for q in after[:j + 1]]
        while len(sq) > 6:
            nx = _drop_smallest(sq)
            if nx is None or len(nx) >= len(sq):
                break
            sq = nx
        if len(sq) != 6:
            return None
        yv = [u * q["p"] for q in sq]
        l1, l3, l5 = yv[1] - yv[0], yv[3] - yv[2], yv[5] - yv[4]
        ok = yv[2] > yv[0] and yv[3] > yv[1] and yv[4] > yv[1] and yv[5] > yv[3] and l3 > min(l1, l5)
        return sq if ok else None                                     # 不是五段推動（只有三段＝弱勢反彈）
    # B104：初推終點＝第一個「五段成立、之後壓回 ≥ 0.2 倍」的高點（她 11/10：43,108 走完、41,873 是 (2)）；
    # 之後再創高（43,147）算第 (3) 浪／小 c 啟動，不再把 (2) 併進第 5 段
    jt = None
    for j in hs:
        sq = five(j)
        if not sq:
            continue
        sp_j = abs(after[j]["p"] - ext)
        lo_after = []
        for q in after[j + 1:]:
            if q["t"] == after[0]["t"] and (q["p"] - after[j]["p"]) * u > 0:
                break
            if q["t"] != after[0]["t"]:
                lo_after.append(q["p"])
        if lo_after and abs(after[j]["p"] - min(lo_after, key=lambda v: u * v)) >= 0.2 * sp_j:
            jt = j
            break
    if jt is None:
        jt = max(hs, key=lambda j: u * after[j]["p"])                 # 還沒有像樣的壓回：這一腳最遠的點
    seq = five(jt)
    if not seq:
        return None
    p0, p5 = seq[0]["p"], seq[5]["p"]
    sp = abs(p5 - p0)
    fb = {r: p5 - u * r * sp for r in (0.236, 0.382, 0.5, 0.618)}
    rest = [q["p"] for q in after[jt + 1:] if q["t"] != after[0]["t"]]     # 初推終點之後出現的壓回低點（轉折）
    pull = min(rest + [float(price)], key=lambda v: u * v) if rest else None   # 還沒有壓回轉折＝初推可能還在走
    new_hi = max([q["p"] * u for q in after[jt + 1:] if q["t"] == after[0]["t"]] + [float(price) * u]) * u
    third = pull is not None and (new_hi - p5) * u > 0                # 壓回之後又過初推高點＝第 (3) 浪／小 c 啟動
    z1 = [(fb[0.236], "初推 0.236")] + ([(fib382, f382_lab)]
                                        if fib382 is not None and (fb[0.236] - fib382) * u > 0 and (fib382 - fb[0.382]) * u > 0 else [])
    if pull is not None and (pull - fb[0.236]) * u > 0 and abs(p5 - pull) >= 0.146 * sp:
        z1.append((pull, "目前壓回低點"))                              # 她：守住日盤低點 41,873（初推 0.236 為 41,830）至 41,481
    z2 = [(fb[0.382], "初推 0.382"), (seq[4]["p"], "小 4 低點" if u > 0 else "小 4 高點"), (seq[1]["p"], "小 1 高點" if u > 0 else "小 1 低點")]
    z3 = [(fb[0.5], "初推 0.5"), (fb[0.618], "初推 0.618")]
    zones = []
    for k, (nm, lv) in enumerate((("強勢橫盤換手（以時間換空間）", z1), ("標準對稱回測（健康 2 浪／b 浪共振）", z2), ("深層 1 轉 2 洗盤", z3)), 1):
        lv = sorted(lv, key=lambda q: -u * q[0])                      # 近的（高的）在前
        zones.append({"k": k, "name": nm, "hi": round(lv[0][0], 2), "lo": round(lv[-1][0], 2), "lv": [(round(v, 2), t) for v, t in lv]})
    where = None
    if pull is not None:
        where = next((z["k"] for z in zones if (pull - z["lo"]) * u >= 0), 4)
        if (pull - zones[0]["hi"]) * u > 0:
            where = 0                                                 # 還沒回到第一區
    up_w, dn_w = ("漲", "跌") if u > 0 else ("跌", "漲")
    tg = [(pull + u * r * sp, nm) for r, nm in ((0.618, "c＝0.618 倍 a"), (1.0, "c＝a／(3)＝(1)"), (1.618, "(3)＝1.618 倍 (1)"))] if pull is not None else []
    st = (f"第 (3) 浪（或小 c）已啟動：{_fmt(pull)} 起{up_w}、過了初推高點 {_fmt(p5)}（最高 {_fmt(new_hi)}），守住 {_fmt(pull)} 推升結構就還在"
          + (f"；現在拉回到 {_fmt(price)}" if abs(new_hi - price) >= 0.1 * sp else "")
          if third else
          "初推還在走" if pull is None else
          f"壓回到 {_fmt(pull)}：" + ({0: "還沒回到第一區（很強）", 4: f"跌破 0.618，看起點 {_fmt(p0)} 守不守"}.get(where)
                                     or f"在第 {where} 區（{zones[where - 1]['name'].split('（')[0]}）"))
    sub = None
    if third:
        sub = _sub5(after[jt + 1:], after[0]["t"], u, p0, p5, sp, pull, price, big_hi, c1_low, neck,
                    lows=[q["p"] for q in seq if q["t"] != after[0]["t"]], fine=fine)
        if sub and sub.get("done"):
            st = sub["state"]                                         # B107：5-1 已結束、日線 5-2
    lines = [f"初推小 5 段（她 11/10）：{'→'.join(_fmt(q['p']) for q in seq)}（2 不破起點、3 不是最短、4 不碰 1）＝第五大波 (1) 浪或大 B／C-4 的小 a；"
             f"接下來的壓回是三波整理、不會回測 {_fmt(p0)}，整理完還有一段向上（(3) 浪或小 c）",
             "壓回三種：" + "；".join(f"{'①②③'[z['k'] - 1]} {z['name'].split('（')[0]} {_fmt(z['hi'])}～{_fmt(z['lo'])}（" + "、".join(t for _, t in z["lv"]) + "）"
                                      for z in zones) + f"；實體{'跌破' if u > 0 else '漲過'}小 1 {_fmt(seq[1]['p'])} 才往第 3 區，{'跌破' if u > 0 else '漲過'}起點 {_fmt(p0)} 才算失敗",
             f"現在：{st}"]
    if third:
        if not (sub and sub.get("done")):
            lines.append("(3) 浪／小 c 的量度：" + "、".join(f"{t} {_fmt(v)}" for v, t in tg)
                         + "；C-4 版本的小 c 不能重疊 C-1 低點，越過 C-1 低點、頸線＝真推升")
        if sub:
            lines += sub["lines"]
    return {"seq": [q["p"] for q in seq], "fib": {str(r): round(v, 2) for r, v in fb.items()}, "zones": zones, "pull": pull,
            "where": where, "state": st, "third": third, "new_hi": new_hi if third else None,
            "targets": [(round(v, 2), t) for v, t in tg] if third else [], "sub": sub, "lines": lines}


def _sub5(rest: list, top_t: str, u: int, p0: float, p5: float, sp: float, pull: float, price: float,
          big_hi: Optional[float], c1_low: Optional[float], neck: Optional[float],
          lows: Optional[list] = None, fine: Optional[list] = None) -> Optional[dict]:
    """B105 她 11/11：第四大波完成、啟動 5-1，60 分「大中小」——(1)＝初推 37,694→43,108（5,414 點）、(2)＝很短的橫台
    （41,873～43,147，最後一個低點 42,165 起漲），(3)＝42,165→44,680（中結構，候選結束點）；
    (4) 淺回 0.236（44,086）、標準 0.382（43,719），不能碰 (1) 高點區 43,108～43,147；(5) 最後一推完成 5-1：
    (4)-C 的 0.618 回升 45,463、從淺回位再走 0.618 倍 (3)＝45,640（她：共振 45,460～45,650）；
    日線 5-2 推敲＝5-1 停在 C-1 低點 45,523～頸線 46,107 時的 0.382／0.5／0.618（她：42,520～42,884、41,604～41,893、40,680～40,902）
    B107 她 11/12：壓回跌破 (1) 高點（4 不能碰 1）→ 不是 (4)，5-1 在最高點 44,911 結束（時間壓縮或失敗第 5 波）、進日線 5-2：
    三個大買點＝37,694→44,911 的 0.382／0.5／0.618，有前低在上面 0.7% 內就併成一區（她：42,165、41,303、40,451～40,715）；
    5-2-A／B 拿來觀察：A＝最高點到之後的低點，B 反彈 0.382／0.5／0.618，最高多半壓在 0.618 附近。
    lows：初推小 5 段的低點；fine：更細一級（30 分）的轉折（找 42,165 這種前低）"""
    margin = 0.1 * sp                                                 # 過初推高點不到 0.1 倍＝還在 (2) 橫台裡（例：43,147 只多 39 點）
    k3 = next((k for k, q in enumerate(rest) if q["t"] == top_t and (q["p"] - p5) * u > margin), None)
    if k3 is None:
        return None
    lows_before = [q["p"] for q in rest[:k3] if q["t"] != top_t]
    if not lows_before:
        return None
    launch = lows_before[-1]                                          # (3) 的起點＝橫台最後一個低點
    plat_hi = max([q["p"] * u for q in rest[:k3] if q["t"] == top_t] + [p5 * u]) * u
    highs = [q["p"] for q in rest[k3:] if q["t"] == top_t] + [float(price)]
    top3 = max(highs, key=lambda v: u * v)
    l3 = abs(top3 - launch)
    z4 = {r: top3 - u * r * l3 for r in (0.236, 0.382)}
    lim = sorted([p5, plat_hi], key=lambda v: u * v)                  # (4) 不能碰 (1) 高點區
    k_t3 = max((k for k in range(k3, len(rest)) if rest[k]["t"] == top_t and rest[k]["p"] == top3), default=len(rest))
    lows_after = [q["p"] for q in rest[k_t3 + 1:] if q["t"] != top_t]   # 最高點之後的低點（現價創新高＝沒有）
    pb = min(lows_after + [float(price)], key=lambda v: u * v)
    in4 = abs(top3 - pb) >= 0.15 * l3
    t5 = [(z4[0.236] + u * 0.618 * l3, "(5)＝0.618 倍 (3)（從淺回位）")]
    if big_hi is not None and (big_hi - p0) * u > 0:
        t5.insert(0, (p0 + u * 0.618 * abs(big_hi - p0), f"{_fmt(big_hi)}→{_fmt(p0)} 的 0.618 回升"))
    if in4 and (pb - lim[0]) * u < 0:
        return _done52(rest, top_t, u, p0, p5, sp, pull, price, launch, plat_hi, top3, lim, pb, lows, fine)
    d52 = []
    ends = [v for v in (c1_low, neck) if v is not None and (v - p0) * u > 0]
    if ends:
        for r in (0.382, 0.5, 0.618):
            vs = [e - u * r * abs(e - p0) for e in ends]
            d52.append((r, round(min(vs), 2), round(max(vs), 2)))
    up_w = "漲" if u > 0 else "跌"
    st = (f"(3) 走到 {_fmt(top3)}（候選結束點）" + (f"，(4) 壓回中（到 {_fmt(pb)}）" if in4 else "，還在 (3)"))
    lines = [f"大中小（她 11/11）：(1) {_fmt(p0)}→{_fmt(p5)}（{_fmt(sp)} 點）、(2) 橫台 {_fmt(pull)}～{_fmt(plat_hi)}、"
             f"(3) {_fmt(launch)}→{_fmt(top3)}；{st}",
             f"(4) 淺回 {_fmt(z4[0.236])}（0.236）、標準 {_fmt(z4[0.382])}（0.382），不能碰 (1) 高點區 {_fmt(lim[0])}～{_fmt(lim[1])}；"
             f"(4) 走完最後一推 (5)：" + "、".join(f"{t} {_fmt(v)}" for v, t in t5)]
    if d52:
        lines.append("日線 5-2 推敲（5-1 停在 " + "～".join(_fmt(v) for v in ends) + " 的回檔，僅參考）："
                     + "、".join(f"{r:g} {_fmt(a)}～{_fmt(b)}" for r, a, b in d52))
    return {"launch": launch, "plat": [pull, plat_hi], "top3": top3, "z4": {str(r): round(v, 2) for r, v in z4.items()},
            "limit": lim, "pb": pb if in4 else None, "t5": [(round(v, 2), t) for v, t in t5], "d52": d52, "state": st, "lines": lines}


def _done52(rest: list, top_t: str, u: int, p0: float, p5: float, sp: float, pull: float, price: float, launch: float,
            plat_hi: float, top: float, lim: list, pb: float, lows: Optional[list], fine: Optional[list]) -> dict:
    """B107 她 11/12：5-1 結束、日線 5-2 修正（見 _sub5）"""
    big = abs(top - p0)
    k_top = next((k for k, q in enumerate(rest) if q["t"] == top_t and q["p"] == top), len(rest))
    fn = list(fine or [])
    f_top = max((k for k, q in enumerate(fn) if q.get("t") == top_t and abs(q["p"] - top) < 1e-6), default=len(fn))
    f_st = max((k for k, q in enumerate(fn[:f_top]) if q.get("t") != top_t and (q["p"] - p0) * u <= 0), default=-1) + 1
    cand = [v for v in [pull, launch] + list(lows or []) + [q["p"] for q in rest[:k_top] if q["t"] != top_t]   # 只用 5-1 裡面的前低
            + [q["p"] for q in fn[f_st:f_top] if q.get("t") != top_t] if v is not None and (v - p0) * u > 0 and (top - v) * u > 0]
    z52 = []
    for r in (0.382, 0.5, 0.618):
        f = top - u * r * big
        near = [v for v in cand if 0 < (v - f) * u <= 0.007 * abs(f)]          # 上面 0.7% 內的前低一起算（她 40,451～40,715）
        nv = max(near, key=lambda v: u * v) if near else None
        z52.append({"r": r, "v": round(f, 2), "near": nv, "lo": round(min(f, nv if nv is not None else f), 2),
                    "hi": round(max(f, nv if nv is not None else f), 2)})
    # 5-2 走 A-B-C：A 低點＝最高點之後第一個「彈回 ≥ 0.236 倍 A」的低點；B＝之後的反彈；再跌破 A 低點＝C
    pts = [q["p"] for q in rest[k_top + 1:]] + [float(price)]
    a_low = b_hi = c_low = lo = None
    for v in pts:
        if a_low is None:
            if lo is None or (v - lo) * u < 0:
                lo = v
            elif (v - lo) * u >= 0.236 * abs(top - lo):
                a_low, b_hi = lo, v
        elif c_low is None:
            if (v - b_hi) * u > 0:
                b_hi = v
            elif (v - a_low) * u < 0:
                c_low = v
        elif (v - c_low) * u < 0:
            c_low = v
    stage = "A" if a_low is None else "B" if c_low is None else "C"
    if a_low is None:
        a_low = lo if lo is not None else pb
    if stage == "B":                                                  # B 高點：更細一級（30 分）在 A 低點之後的高點也算
        fa = next((k for k, q in enumerate(fn) if q.get("t") != top_t and abs(q["p"] - a_low) < 1e-6), None)
        if fa is not None:
            b_hi = max([b_hi * u] + [q["p"] * u for q in fn[fa + 1:] if q.get("t") == top_t]) * u
    a_len = abs(top - a_low)
    in_b = stage != "A"
    b52 = [(round(a_low + u * r * a_len, 2), f"5-2-B 反彈 {r:g}" + ("（極限）" if r == 0.786 else "")) for r in (0.382, 0.5, 0.618, 0.786)]
    c52 = [(round(b_hi - u * r * a_len, 2), f"5-2-C＝{nm}") for r, nm in ((0.618, "0.618 倍 A"), (1.0, "A 等幅"))] if stage == "C" else []
    low_all = min([a_low, float(price)] + ([c_low] if c_low is not None else []), key=lambda v: u * v)
    for z in z52:
        z["hit"] = bool((low_all - z["hi"]) * u <= 0)                 # 已經跌到這一區
    zt = lambda z: f"{z['r']:g} {_fmt(z['v'])}" + (f"～{_fmt(z['near'])}（前低）" if z["near"] is not None else "")   # noqa: E731
    if stage == "A":
        now_t = f"5-2-A 進行中（到 {_fmt(a_low)}）"
        obs = f"A 還在走（到 {_fmt(a_low)}），先看 0.382 {_fmt(z52[0]['v'])}；A 走完才有 5-2-B 反彈"
    elif stage == "B":
        now_t = f"5-2-A {_fmt(top)}→{_fmt(a_low)}、5-2-B 反彈中（到 {_fmt(b_hi)}）"
        obs = (f"A {_fmt(top)}→{_fmt(a_low)}（{_fmt(a_len)} 點）；B 反彈 " + "、".join(f"{t.split()[-1]} {_fmt(v)}" for v, t in b52)
               + f"，最高多半壓在 0.618 附近、不會過 {_fmt(top)}；B 走完再看 5-2-C 往上面三區")
    else:
        now_t = f"5-2-A {_fmt(top)}→{_fmt(a_low)}、5-2-B 彈到 {_fmt(b_hi)}、5-2-C 進行中（到 {_fmt(c_low)}）"
        obs = (f"A {_fmt(top)}→{_fmt(a_low)}、B 彈到 {_fmt(b_hi)}；C 的量度 " + "、".join(f"{t.split('＝')[-1]} {_fmt(v)}" for v, t in c52)
               + "，C 走完才是 5-3 起漲")
    st = (f"5-1 在 {_fmt(top)} 結束（壓回到 {_fmt(low_all)}，跌破 (1) 高點 {_fmt(lim[0])}：4 不能碰 1，所以不是 (4)）；日線 5-2 修正中：" + now_t)
    lines = [f"大中小（她 11/11）：(1) {_fmt(p0)}→{_fmt(p5)}（{_fmt(sp)} 點）、(2) 橫台 {_fmt(pull)}～{_fmt(plat_hi)}、(3) {_fmt(launch)} 起；"
             f"她 11/12：{_fmt(top)} 是 5-1 終點（(3)(4)(5) 時間壓縮走完，或失敗第 5 波），{_fmt(p0)}→{_fmt(top)} 漲了 {_fmt(big)} 點",
             f"現在：{st}",
             f"5-2 三個大買點（{_fmt(p0)}→{_fmt(top)} 的回檔；個股、0050 分批介入，到了也要等止跌）：" + "、".join(zt(z) for z in z52),
             "5-2-A／B 拿來觀察：" + obs]
    return {"done": True, "stage": stage, "launch": launch, "plat": [pull, plat_hi], "top3": top, "top": top, "limit": lim, "pb": low_all,
            "p0": p0, "a_low": a_low, "b_hi": round(b_hi, 2) if in_b else None, "c_low": c_low, "b52": b52 if in_b else [], "c52": c52,
            "z52": z52, "z4": {}, "t5": [], "d52": [(z["r"], z["lo"], z["hi"]) for z in z52], "state": st, "lines": lines}


def _paths(after: list, d: int, ext: float, price: float, y: float, x: float, T: dict, L1: dict, H2: dict,
           ffib: dict, fib382: float, ma5: Optional[float], lb: dict, case: str, neck: Optional[list] = None,
           neck_p: Optional[float] = None, fine: Optional[list] = None) -> Optional[dict]:
    """B100 她 11/8：37,694 的級數身分＝三條路徑（A 日線三段式已完成、B 60 分 3-4-c、C 日線五段式 C-4）＋三層驗證。
    after：極值之後的小級轉折（a 終點、b、c-1、c-2…）。她的數字：a 37,694→40,690、b 39,129 →
    第一層 守住壓回低點（39,977；她 39,944～40,000）且實體站回 40,690→39,977 的 0.5～0.618（40,334～40,418；她 40,335～40,419）；
    第二層 前高 40,690～40,745 與 40,981（c＝0.618 倍 a，也是 3-3 的 0.5）；她再往 41,335～41,557（沒說怎麼算）；
    第三層 41,481（47,607→37,694 的 0.382）收盤接受 → 挑戰 41,677～42,125（日線 5T、c＝a）；站穩 42,050（3-1 低點）＝升級日線級反彈"""
    if len(after) < 2:
        return None
    a_end, b = after[0]["p"], after[1]["p"]
    if (a_end - ext) * -d <= 0 or (b - ext) * d >= 0 or (a_end - b) * -d <= 0:
        return None                                                   # b 破了起點＝不是 a-b-c
    la = abs(a_end - ext)
    ilo = max(j for j in range(1, len(after)) if after[j]["t"] != after[0]["t"])          # 最後一次壓回的低點
    last_lo = after[ilo]["p"]
    top = max([q["p"] * -d for q in after[:ilo] if q["t"] == after[0]["t"]]) * -d       # 壓回之前反彈最遠的轉折（c-1）
    prev_hi = after[ilo - 1]["p"]                                                       # 緊接在壓回前的高點
    c = {r: b - d * r * la for r in (0.618, 1.0, 1.618)}
    sp3 = abs(y - ext)
    f5 = ext - d * 0.5 * sp3
    ref = a_end if (a_end - last_lo) * -d > 0 else prev_hi        # B101：壓回沒回到 a 的高點以下 → 改用緊接的前高
    rc = sorted([last_lo - d * 0.5 * abs(ref - last_lo), last_lo - d * 0.618 * abs(ref - last_lo)], key=lambda v: -d * v)
    beyond = lambda v: (price - v) * -d > 0                            # noqa: E731
    up, dn = ("上", "下") if d < 0 else ("下", "上")
    s_up = "反彈" if d < 0 else "拉回"
    L1v = {"defend": last_lo, "zone": [round(v, 2) for v in rc], "ok": beyond(rc[-1]) and beyond(last_lo), "part": beyond(last_lo)}
    hi2 = sorted([a_end, top], key=lambda v: -d * v)
    g2 = max([hi2[-1], c[0.618], f5], key=lambda v: -d * v)
    L2v = {"prev": [round(v, 2) for v in hi2], "c618": round(c[0.618], 2), "f5": round(f5, 2), "ok": beyond(g2), "part": beyond(hi2[0])}
    l3 = [(fib382, f"{_fmt(H2['p'])}→{_fmt(ext)} 的 0.382")]
    chal = [(c[1.0], "c＝a 等幅")] + ([(ma5, f"{lb['big']} 5 均")] if ma5 and (ma5 - fib382) * -d > 0 else [])
    L3v = {"gate": round(fib382, 2), "chal": [(round(v, 2), t) for v, t in sorted(chal, key=lambda q: -d * q[0])], "hard": x,
           "ok": beyond(x), "part": beyond(fib382)}
    gap = round(abs(ext - ffib[0.382]), 0) if 0.382 in ffib else None
    st = lambda v: "✅" if v["ok"] else "◐" if v["part"] else "⬜"                    # noqa: E731
    paths = [
        {"k": "A", "name": f"{lb['big']}三段式修正已完成",
         "t": (f"{_fmt(ext)} 離全波段 0.382 {_fmt(ffib[0.382])} 只差 {_fmt(gap)} 點；" if gap is not None else "")
              + f"若 {_fmt(H2['p'])}→{_fmt(ext)} 的五段已經把{lb['big']} C 浪走完，{_fmt(ext)} 起{'漲' if d < 0 else '跌'}＝{lb['big']}大 B 浪{s_up}（B-a）"},
        {"k": "B", "name": f"{lb['small']}原切組：3-4-c 運行中",
         "t": f"a {_fmt(ext)}→{_fmt(a_end)}、b {_fmt(b)}、c 從 {_fmt(b)} 起；仍只是 3-4 的 c，走完還有 3-5 破{'底' if d < 0 else '頂'}或雙{'底' if d < 0 else '頂'}測試"},
        {"k": "C", "name": f"{lb['big']}五段式：{_fmt(ext)}＝{lb['big']} C-3 終點、現在走 C-4",
         "t": f"只要不重疊 C-1 {'低' if d < 0 else '高'}點 {_fmt(L1['p'])}，後面還有{lb['big']} C-5 破{'底' if d < 0 else '頂'}"},
    ]
    if L3v["ok"]:                                                     # B101：站穩 3-1 低點＝路徑 B（單純的 3-4）淘汰
        paths[1]["out"] = True
        paths[1]["name"] += f"（已淘汰：{'站穩' if d < 0 else '跌破'} {_fmt(x)}）"
    if case != "3":
        paths = paths[1:2]
    lines = [f"{_fmt(ext)} 的級數身分（她 11/8）：" + "；".join(f"路徑 {p['k']}（{p['name']}）{p['t']}" for p in paths),
             f"三條路徑共用的短線考驗——{st(L1v)} 第一層：回測守住 {_fmt(last_lo)}（這次壓回的{'低' if d < 0 else '高'}點）、實體站回 "
             f"{_fmt(rc[0])}～{_fmt(rc[1])}（{_fmt(ref)}→{_fmt(last_lo)} 的 0.5～0.618）＝壓回換手結束、多方拿回短線推進權" if d < 0 else
             f"三條路徑共用的短線考驗——{st(L1v)} 第一層：回測守住 {_fmt(last_lo)}、實體跌回 {_fmt(rc[0])}～{_fmt(rc[1])}",
             f"{st(L2v)} 第二層：突破站穩前高 {_fmt(hi2[0])}～{_fmt(hi2[1])} 和 {_fmt(c[0.618])}（c＝0.618 倍 a；3-3 的 0.5 {_fmt(f5)}）；"
             f"只是路徑 B 的話，會在這裡失速、反抽失敗、跌破控制線 → 結束{s_up}轉入 3-5",
             f"{st(L3v)} 第三層（級數升權分水嶺）：{_fmt(fib382)}（{_fmt(H2['p'])}→{_fmt(ext)} 的 0.382）收盤接受、回測不破、放量推升，才有資格挑戰 "
             + "～".join(_fmt(v) for v, _ in L3v["chal"]) + "（" + "、".join(t for _, t in L3v["chal"]) + "）；"
             f"{'站穩' if d < 0 else '跌破'} {_fmt(x)}（重疊 3-1）＝淘汰單純的{lb['small']} 3-4，升級{lb['big']}級{s_up}（路徑 A 或 C）"]
    push = _push(after, d, ext, price, fib382, f"{_fmt(H2['p'])}→{_fmt(ext)} 的 0.382",       # B103 她 11/10 傍晚
                 big_hi=T["p"], c1_low=L1["p"], neck=neck_p, fine=fine)
    if L3v["ok"]:
        L1v["ok"] = L2v["ok"] = True                                  # B103：升級（站穩 3-1 低點）以後，第一、二層已經走過
    nxt = None
    if L3v["ok"]:
        # B101 她 11/10：升級以後＝新脈動（最後一次壓回低點起）跟舊脈動做撐壓交換。
        # 新脈動小 (3) 目標＝壓回段（42,317→40,715）的 1.618 倍外部投射 43,307；上方撐壓互換頸線＝舊等幅目標 43,397～43,449＋60 分前波平台低點 42,925
        proj = last_lo - d * 1.618 * abs(prev_hi - last_lo)
        nk = sorted(neck or [], key=lambda q: -d * q[0])
        if nk:
            lo_, hi_ = nk[0][0], nk[-1][0]
            nst = ("站上頸線：新脈動贏，頸線轉成支撐（回測要守住）" if beyond(hi_) else
                   "在頸線區裡：新舊脈動撐壓交換中，回測守不守得住是關鍵" if beyond(lo_) else
                   "還在頸線下：舊脈動的壓力還在，先看能不能站上")
        nxt = {"from": last_lo, "prev_hi": prev_hi, "proj": round(proj, 2), "neck": [(round(v, 2), t) for v, t in nk],
               "neck_state": nst if nk else None}
        if push and push["pull"] is not None:                         # B103：初推走完、壓回還在走 → 新脈動目標要等壓回結束才算
            nxt["proj"] = None
            nxt["from"] = None
        lines.append(f"升級以後（她 11/10）：新脈動跟舊脈動（{_fmt(H2['p'])}→{_fmt(ext)}）做撐壓交換"
                     + (f"；新脈動小 (3) 目標 {_fmt(proj)}（{_fmt(prev_hi)}→{_fmt(last_lo)} 壓回段的 1.618 倍外部投射），到了容易短線調節、小 (4) 換氣"
                        if nxt["proj"] is not None else "")
                     + (f"；上方撐壓互換頸線 {_fmt(nk[0][0])}～{_fmt(nk[-1][0])}（" + "、".join(t for _, t in nk) + f"）：{nst}" if nk else ""))
    if push:
        lines += push["lines"]
    return {"a": [ext, a_end], "b": b, "c1": top, "c2": last_lo, "c": {str(r): round(v, 2) for r, v in c.items()},
            "paths": paths, "layers": [L1v, L2v, L3v], "next": nxt, "push": push, "lines": lines}


def _ext3(S: list, k: int, d: int, ext: float, R: float, price: float, T: dict, L1: dict, H2: dict,
          full: Optional[float], lb: dict, case: str, after: Optional[list] = None, fib382: Optional[float] = None,
          ma5: Optional[float] = None, neck: Optional[list] = None, neck_p: Optional[float] = None,
          fine: Optional[list] = None) -> Optional[dict]:
    """B98 她 11/6：小級五段、但第 (4) 段碰到第 (1) 段的領地 → 4 不重疊 1，所以它不是第 4 段：
    S[3] 只是 3-1、S[4] 是 3-2，S[4] 起是 3-3（延伸的主跌段）。算 3-3 兩個煞車區、3-4 反抽還是轉浪、第 5 段走完的下修。
    她的數字：煞車區 38,713～38,522＝44,274 往下 1.618 倍 3-1（3,437）、1.618 倍第 (1) 段（3,555）；
    37,564～37,400＝全波段（17,015→50,265）的 0.382、2 倍 3-1；深 5 到 33,641＝全波段 0.5；35,192＝日線第 (3) 段 2.618 倍第 (1) 段。
    淺 5 的 36,603 她沒說怎麼算，試算最接近的是 44,274 往下 1.618 倍日線第 (1) 段（36,601）。full＝全波段起點（大級更大一級的低點）"""
    if k < 5 or (S[4]["p"] - S[1]["p"]) * -d <= 0:
        return None
    y, x = S[4]["p"], S[3]["p"]
    l1, l31 = abs(S[0]["p"] - S[1]["p"]), abs(S[2]["p"] - S[3]["p"])
    if l1 <= 0 or l31 <= 0:
        return None
    pj = lambda base, r, ln: base + d * r * ln                        # noqa: E731  順著這段的方向量 r 倍
    dn = "下" if d < 0 else "上"
    lo_hi = "低" if d < 0 else "高"
    s_dn, s_up = ("跌", "反彈") if d < 0 else ("漲", "拉回")
    span_full = abs(T["p"] - full) if full is not None and (T["p"] - full) * -d > 0 else None
    ffib = {r: T["p"] + d * r * span_full for r in (0.382, 0.5, 0.618)} if span_full else {}
    f_name = f"全波段 {_fmt(full)}→{_fmt(T['p'])} 的" if span_full else ""
    z1 = [(pj(y, 1.618, l31), f"{_fmt(y)} 往{dn} 1.618 倍 3-1"), (pj(y, 1.618, l1), f"{_fmt(y)} 往{dn} 1.618 倍第 (1) 段")]
    a2 = pj(y, 2, l31)
    near = sorted(((abs(v / a2 - 1), r, v) for r, v in ffib.items() if abs(v / a2 - 1) < 0.015))
    z2 = [(a2, f"{_fmt(y)} 往{dn} 2 倍 3-1")] + ([(near[0][2], f"{f_name} {near[0][1]}")] if near
                                                 else [(pj(y, 2, l1), f"{_fmt(y)} 往{dn} 2 倍第 (1) 段")])
    gone = lambda v: (ext - v) * d >= 0                               # noqa: E731  極值已經走到（過）v

    def zone(name, lv):
        lv = sorted(lv, key=lambda q: d * q[0])                       # 近的（離 3-2 近）在前
        a, b = lv[0][0], lv[-1][0]
        st = "through" if gone(b) else "in" if gone(a) else "ahead"
        return {"name": name, "lo": round(min(a, b), 2), "hi": round(max(a, b), 2), "state": st,
                "gap": None if st != "ahead" else round(abs(ext - a), 0 if abs(ext) >= 1000 else 2), "lv": [(round(v, 2), t) for v, t in lv]}
    brakes = [zone("第一煞車區", z1), zone("第二煞車區", z2)]
    sp = abs(y - ext)
    f382, f5 = ext - d * 0.382 * sp, ext - d * 0.5 * sp
    back = lambda v: (R - v) * -d > 0                                 # noqa: E731  反彈（拉回）越過 v
    if (price - x) * -d > 0:
        now = f"已經收復 3-1 {lo_hi}點 {_fmt(x)} → 轉浪（至少 B 波{s_up}），這個數法先放一邊"
    elif back(x):
        now = f"{s_up}曾經到 {_fmt(R)}、越過 {_fmt(x)} 但沒站穩，看能不能收復"
    elif back(f5):
        now = f"{s_up}到 {_fmt(R)}，過了 0.5、還沒收復 {_fmt(x)}"
    elif back(f382):
        now = f"{s_up}到 {_fmt(R)}，在 0.382～0.5 之間（典型 3-4 反抽的位置）"
    else:
        now = f"{s_up}到 {_fmt(R)}，還沒到 0.382"
    reb = {"from": ext, "R": round(R, 2), "f382": round(f382, 2), "f5": round(f5, 2), "hard": x, "now": now}
    five = None
    if case == "3":
        bl1 = abs(T["p"] - L1["p"])
        w3 = pj(H2["p"], 2.618, bl1)
        sh = [(pj(y, 1.618, bl1), f"{_fmt(y)} 往{dn} 1.618 倍{lb['big']}第 (1) 段"), (w3, f"{lb['big']}第 (3) 段＝2.618 倍第 (1) 段")]
        dp = [(w3, f"{lb['big']}第 (3) 段＝2.618 倍第 (1) 段")]
        if 0.5 in ffib and (ffib[0.5] - w3) * d > 0:
            dp.append((ffib[0.5], f"{f_name} 0.5"))
        if (sh[0][0] - w3) * d < 0 and len(dp) == 2:
            five = {"shallow": {"lv": [(round(v, 2), t) for v, t in sh]}, "deep": {"lv": [(round(v, 2), t) for v, t in dp]}}
            for z in five.values():
                vs = [v for v, _ in z["lv"]]
                z["lo"], z["hi"] = min(vs), max(vs)
    st_t = {"in": "現在已經進入", "through": "已經穿過"}
    zt = lambda z: (f"{z['name']} {_fmt(z['lv'][0][0])}～{_fmt(z['lv'][-1][0])}（" + "、".join(t for _, t in z["lv"]) + "）"  # noqa: E731
                    + (f"{st_t[z['state']]}（{lo_hi}點 {_fmt(ext)}）" if z["state"] != "ahead" else f"還差 {_fmt(z['gap'])} 點"))
    lines = [f"另一種數法（她 11/6）：{_fmt(y)} 碰到{lb['small']}第 (1) 段{lo_hi}點 {_fmt(S[1]['p'])}（4 不重疊 1）→ 它不是第 4 段："
             f"{_fmt(x)} 只是 3-1、{_fmt(y)} 是 3-2，{_fmt(y)} 起{s_dn}是 3-3（延伸的主{s_dn}段）",
             "3-3 兩個煞車區（只是空間到達）：" + "；".join(zt(z) for z in brakes),
             f"{s_up}是 3-4 還是轉浪：{s_up}受阻在 {_fmt(f382)}～{_fmt(f5)}（3-3 的 0.382～0.5）以{dn}、或收不回 3-1 {lo_hi}點 {_fmt(x)}，"
             f"壓回又{'跌破' if d < 0 else '漲過'}{s_up}起點 {_fmt(ext)} → 只是 3-4 反抽，後面還有 3-5 和第 5 段；"
             f"{'站穩' if d < 0 else '跌破'} {_fmt(x)} → 轉浪。現在：{now}"]
    if five:
        lines.append(f"第 5 段全部走完的{'下修' if d < 0 else '上攻'}：淺 5 {_fmt(five['shallow']['lv'][0][0])}～{_fmt(five['shallow']['lv'][-1][0])}、"
                     f"深 5 {_fmt(five['deep']['lv'][0][0])}～{_fmt(five['deep']['lv'][-1][0])}（"
                     + "、".join(t for _, t in five["shallow"]["lv"][:1] + five["deep"]["lv"]) + "）")
    lines.append(f"以上點位只是空間到達：沒有止{s_dn}訊號（第一根壓{dn}來收盤不破前{lo_hi}、站回 5 均、帶量實體{'紅' if d < 0 else '黑'} K 站穩，"
                 f"或跨級數雙重{'底' if d < 0 else '頂'}背離）就衝進去＝{'接刀' if d < 0 else '摸頂'}；止{s_dn}訊號＋分批試水溫")
    pz = _paths(after or [], d, ext, price, y, x, T, L1, H2, ffib, fib382, ma5, lb, case, neck, neck_p, fine=fine) if fib382 is not None else None
    return {"y": y, "x": x, "legs": [round(l1, 2), round(l31, 2)], "full": full, "ffib": {str(r): round(v, 2) for r, v in ffib.items()},
            "brakes": brakes, "reb": reb, "five": five, "paths": pz, "lines": lines}


def structure(big: list, small: list, price: float, ma5: Optional[float] = None, ma10: Optional[float] = None,
              labels: Optional[dict] = None, first_leg: Optional[list] = None, full: Optional[float] = None,
              fine: Optional[list] = None) -> Optional[dict]:
    """big：大級轉折（舊→新，含最後還沒確認的那個），至少 [T, L1, H2, X]；small：小級轉折，從 H2 開始、到現在（含暫定）。
    price：現價；ma5／ma10：大級的 5、10 均（台指期＝日線）。labels：{"big": "日線", "small": "60 分"}（顯示用）。
    first_leg：小級轉折從 T 到 L1（有給才算 B95 的第一段落點分歧）。full：全波段起點（B98，T 之前更大一級的轉折）。
    fine：更細一級的轉折（台指期＝30 分；B107 找 5-2 大買點旁邊的前低）。
    回 {dir, case, big:{...}, small:{...}, gate1, gate2, fork, ext3, entry, status, lines}；結構不夠回 None"""
    lb = {"big": "大級", "small": "小級", **(labels or {})}
    if len(big) < 4 or len(small) < 2:
        return None
    T, L1, H2, X = big[-4], big[-3], big[-2], big[-1]
    d = -1 if H2["t"] == "H" else 1                                   # 現在這段大級的方向（-1＝從 H2 往下跌）
    if X["t"] == H2["t"] or T["t"] != H2["t"]:
        return None
    if abs(H2["p"] - L1["p"]) > 1.382 * abs(T["p"] - L1["p"]):
        return None                                                   # B101：第 (2) 段回到第 (1) 段的 1.382 倍以上（擴張型 B 也到不了）＝不是這種結構
    s_dn, s_up = ("跌", "反彈") if d < 0 else ("漲", "拉回")
    v_cross, v_fail = ("站穩", "跌破") if d < 0 else ("跌破", "站穩")
    lo_hi = "低" if d < 0 else "高"
    # 現在這段大級的極值（第 3 段到現在最遠的點）＝小級序列裡順方向最遠的
    seq = [q for q in small if q.get("p") is not None]
    if not seq or seq[0]["t"] != H2["t"]:
        seq = [{"i": H2.get("i"), "p": H2["p"], "t": H2["t"]}] + [q for q in seq if q["t"] != H2["t"] or q["p"] != H2["p"]]
    ek = max(range(len(seq)), key=lambda k: d * seq[k]["p"])
    ext = seq[ek]["p"]
    after = seq[ek + 1:]
    R = (max if d < 0 else min)([float(price)] + [q["p"] for q in after])   # 極值之後反向走到哪（現價或之後的轉折）
    S = seq[:ek + 1]
    while len(S) > 6:                                                # 併到最多五段（大、(2)、中、(4)、小）
        nxt = _drop_smallest(S + [{"p": R, "t": "H" if d < 0 else "L"}])
        if nxt is None:
            break
        S = nxt[:-1]
    k = len(S) - 1
    span = abs(H2["p"] - ext)
    fib = {r: ext - d * r * span for r in (0.382, 0.5, 0.618)}
    legs = [abs(S[j]["p"] - S[j + 1]["p"]) for j in range(0, k, 2)]  # 順方向的段：大、中、小
    names = ["大", "中", "小"]
    small_out = {"seq": [{"p": q["p"], "t": q["t"], "i": q.get("i")} for q in S], "legs": [round(x, 2) for x in legs], "n_seg": k,
                 "contract": k >= 5 and all(legs[j] > legs[j + 1] for j in range(len(legs) - 1)),
                 "overlap": k >= 5 and (S[4]["p"] - S[1]["p"]) * -d > 0}
    case = "3" if (ext - L1["p"]) * d > 0 else "2"                   # 3＝已經破了大級第 1 段終點（她的日線第 (3) 段）
    # 第一道關：小級第 (1) 段終點（1、4 不重疊）＋整段 0.382；5 均靠近就一起列
    g1_lv = [(S[1]["p"], f"{lb['small']}第 (1) 段{lo_hi}點（1、4 不重疊）")] if k >= 3 else []
    g1_lv.append((fib[0.382], f"{_fmt(H2['p'])}→{_fmt(ext)} 的 0.382"))
    if ma5 and abs(ma5 / fib[0.382] - 1) < 0.015:
        g1_lv.append((ma5, f"{lb['big']} 5 均"))
    g1_lo, g1_hi = sorted(v for v, _ in g1_lv)[0], sorted(v for v, _ in g1_lv)[-1]
    far1 = g1_hi if d < 0 else g1_lo                                  # 要越過的那一邊
    beyond = lambda v: (price - v) * -d > 0                           # noqa: E731  反向越過 v
    gate1 = {"lo": round(g1_lo, 2), "hi": round(g1_hi, 2), "far": round(far1, 2), "lv": [(round(v, 2), t) for v, t in g1_lv],
             "passed": beyond(far1), "touched": any(beyond(v) for v, _ in g1_lv)}
    # 第二道關：大級第 1 段終點（大級第 4 段不能碰到它）；前面先過 0.5、10 均
    gate2 = None
    if case == "3":
        g2_lv = [(fib[0.5], f"{_fmt(H2['p'])}→{_fmt(ext)} 的 0.5")]
        if ma10 and (ma10 - fib[0.5]) * -d > 0 and (L1["p"] - ma10) * -d > 0:
            g2_lv.append((ma10, f"{lb['big']} 10 均"))
        g2_lv.append((L1["p"], f"{lb['big']}第 (1) 段{lo_hi}點（4 不重疊 1）"))
        gate2 = {"price": L1["p"], "zone": [round(v, 2) for v, _ in g2_lv], "lv": [(round(v, 2), t) for v, t in g2_lv],
                 "passed": beyond(L1["p"])}
        # B95 網友推敲（她回「推敲正確」）：0.618＋小級第 (2) 段＋大級第 (1) 段匯聚成一區（45,484～45,523），站上就很有機會轉強
        bd = [(fib[0.618], f"{_fmt(H2['p'])}→{_fmt(ext)} 的 0.618")]
        if k >= 3:
            bd.append((S[2]["p"], f"{lb['small']}第 (2) 段{'高' if d < 0 else '低'}點"))
        bd = [(v, t) for v, t in bd if abs(v / L1["p"] - 1) < 0.012]
        if bd:
            bd.append((L1["p"], f"{lb['big']}第 (1) 段{lo_hi}點"))
            vs = sorted(v for v, _ in bd)
            gate2["band"] = {"lo": round(vs[0], 2), "hi": round(vs[-1], 2), "lv": [(round(v, 2), t) for v, t in sorted(bd)],
                             "passed": beyond(vs[-1] if d < 0 else vs[0])}
    # 進場（她：0.382 真過以後，壓回第二隻腳落在這段反彈的 0.382～0.5）
    reb = abs(R - ext)
    entry = None
    if (gate1["passed"] or beyond(fib[0.382])) and reb > 0:          # B102：0.382 已經過了（還沒過第一道關）也一樣等第二隻腳
        z = sorted([R + d * 0.382 * reb, R + d * 0.5 * reb])
        # B102：目標＝還沒到的下一個價位（0.5 → 0.618 → 大級第 1 段終點），不要給已經過了的
        tg = next(((v, nm) for v, nm in ((fib[0.5], "0.5"), (fib[0.618], "0.618"), (L1["p"], f"{lb['big']}第 (1) 段{lo_hi}點"))
                   if (v - R) * -d > 0), (fib[0.5], "0.5"))
        entry = {"zone": [round(z[0], 2), round(z[1], 2)], "from": [ext, round(R, 2)], "target": round(tg[0], 2),
                 "t": f"等{s_up}的第二隻腳：壓回到這段{s_up}（{_fmt(ext)}→{_fmt(R)}）的 0.382～0.5＝{_fmt(z[0])}～{_fmt(z[1])}，"
                      f"技術面確認止{s_dn}才進場，目標 {tg[1]} {_fmt(tg[0])}；追{'高' if d < 0 else '低'}沒有肉"}
    # 結構文字
    leg_t = "、".join(f"{names[j]} {_fmt(legs[j])}" for j in range(min(3, len(legs))))
    if k >= 5:
        shape = (f"{lb['small']}「大、中、小」五段（{leg_t}）" + ("，動能逐漸收斂" if small_out["contract"] else "，但沒有一段比一段小")
                 + ("；第 (4) 段碰到第 (1) 段的領地＝收斂楔形（結束型）" if small_out["overlap"] else "") + "：具備走完的條件"
                 + ("（另一種看法＝她 11/6：4 不重疊 1，那不是第 4 段、是延伸第 3 段的 3-2，見「另一種數法」）" if small_out["overlap"] else ""))
    elif k == 3:
        shape = f"{lb['small']}只走了「大、中」兩段（{leg_t}）：第 (3) 段還在走，後面通常還有一段"
    else:
        shape = f"{lb['small']}一路{s_dn}、還沒有像樣的{s_up}（{_fmt(H2['p'])}→{_fmt(ext)}）"
    if case == "3":
        head = (f"{lb['big']}：{_fmt(T['p'])}→{_fmt(L1['p'])}＝(1)、→{_fmt(H2['p'])}＝(2)、{_fmt(H2['p'])} 起{s_dn}＝(3)"
                f"（也可能是 A-B-C 的 C），{s_dn}到 {_fmt(ext)}")
    else:
        head = (f"{lb['big']}：{_fmt(T['p'])}→{_fmt(L1['p'])}→{_fmt(H2['p'])}，現在這段{s_dn}到 {_fmt(ext)} 還沒{'跌破' if d < 0 else '漲過'} "
                f"{_fmt(L1['p'])}（還在 (2)／B 的範圍）")
    if gate2 and gate2["passed"]:
        status = (f"已經{v_cross}第二道關 {_fmt(L1['p'])}：三段式告一段落，但先當「大 B 波{s_up}震盪」，"
                  f"要{v_cross}之後回測守住、看籌碼換手，才分辨是不是新的一波")
        tag = "B"
    elif gate1["passed"]:
        status = (f"已經{v_cross}第一道關 {_fmt(gate1['lo'])}～{_fmt(gate1['hi'])}：{lb['small']}這組{s_dn}勢先當走完、轉入修正{s_up}"
                  + (f"（{lb['big']}第 (4) 段）；下一道關 {_fmt(L1['p'])}" if gate2 else ""))
        tag = "4"
    elif gate1["touched"]:
        status = (f"正在第一道關 {_fmt(gate1['lo'])}～{_fmt(gate1['hi'])}：過了一部分、還沒站穩；在這裡被壓回＝{lb['small']}還沒{s_dn}完，"
                  f"隨時再{s_dn}出一段破{lo_hi}")
        tag = "at1"
    else:
        status = (f"還在第一道關 {_fmt(gate1['lo'])}～{_fmt(gate1['hi'])} 前面：{s_up}只是止{s_dn}反應（單根長{'下' if d < 0 else '上'}影線不等於落底），"
                  f"過不去轉弱＝還有一段破{lo_hi}")
        tag = "below1"
    lines = [head, shape, status]
    lines.append(f"第一道關（安全門）{_fmt(gate1['lo'])}～{_fmt(gate1['hi'])}：" + "、".join(f"{t} {_fmt(v)}" for v, t in gate1["lv"])
                 + f" → {v_cross}＝{lb['small']}{s_dn}勢在 {_fmt(ext)} " + ("走完五段" if k >= 5 else "先告一段落")
                 + f"、轉入修正；遇壓折返＝還沒{s_dn}完")
    if gate2:
        bd = gate2.get("band")
        lines.append(f"第二道關 {_fmt(L1['p'])}：{lb['big']}第 (4) 段在 " + "～".join(_fmt(v) for v in gate2["zone"])
                     + f" 受阻（4 不重疊 1）→ {lb['big']}再{s_dn}第 (5) 段破 {_fmt(ext)}（或至少回測）；"
                     + (f"{_fmt(bd['lo'])}～{_fmt(bd['hi'])} 是" + "、".join(t for _, t in bd["lv"]) + f"匯聚，{v_cross}就很有機會轉強，但"
                        if bd else f"就算{v_cross} {_fmt(L1['p'])}，也")
                     + f"先當大 B 波{s_up}震盪")
    fork = _fork(first_leg, T, L1, H2, ext, d, lb, small_out["contract"] if k >= 5 else None) if case == "3" else None
    if fork:
        lines += fork["lines"]
    neck = []
    if fork:                                                          # B101 舊的等幅目標（c＝a，從 H2 和 60 分 (4) 高點往下量）
        A = abs(T["p"] - fork["a3"])
        bases = [H2["p"]] + [b_ for b_ in fork["v5"]["seq"][4:5] if abs(b_ / H2["p"] - 1) < 0.005 and b_ != H2["p"]]
        neck = [(b_ + d * A, f"{_fmt(b_)} 往{'下' if d < 0 else '上'}等幅（c＝a）") for b_ in bases]
        edge = min(v for v, _ in neck) if d < 0 else max(v for v, _ in neck)
        plat = [q["p"] for q in seq[1:ek] if q["t"] != H2["t"] and (edge - q["p"]) * -d > 0 and abs(q["p"] / edge - 1) < 0.02]
        if plat:
            neck.append((min(plat, key=lambda v: abs(v - edge)), f"{lb['small']}前波平台{lo_hi}點"))
    ext3 = _ext3(S, k, d, ext, R, float(price), T, L1, H2, full, lb, case, after=after, fib382=fib[0.382], ma5=ma5, neck=neck,
                 neck_p=(fork or {}).get("a3"), fine=fine)
    pz = (ext3 or {}).get("paths")
    sub = ((pz or {}).get("push") or {}).get("sub")
    if pz and pz["layers"][2]["ok"] and tag == "4" and sub and not sub.get("done"):
        # B105 她 11/11：站穩第一道關以後＝第四大波三段式完成、啟動 5-1；狀態講 60 分大中小走到哪、下一關 C-1 低點／頸線
        a3 = (fork or {}).get("a3")
        status = (f"已{v_cross}第一道關 {_fmt(gate1['lo'])}～{_fmt(gate1['hi'])}，升級{lb['big']}級{s_up}；{sub['state']}；"
                  f"下一關 C-1 {lo_hi}點 {_fmt(L1['p'])}" + (f"、頸線 {_fmt(a3)}" if a3 else "")
                  + f"（越過＝路徑 A：第四大波完成、走第 5 大波，她 11/11 看這個）")
        tag = "up5"
        lines[2] = status
        if entry:                                                     # 進場講她的 (4) 回測，大的上車點是日線 5-2（不跟整段反彈的第二隻腳混在一起）
            z4 = sub["z4"]
            entry["t"] = (f"進場：等 (4) 回測——淺 {_fmt(z4['0.236'])}、標準 {_fmt(z4['0.382'])} 止{s_dn}再進（不能碰 {_fmt(sub['limit'][0])}～{_fmt(sub['limit'][1])}）；"
                          + ("大的上車點等日線 5-2：" + "、".join(f"{r:g} {_fmt(a)}～{_fmt(b)}" for r, a, b in sub["d52"]) if sub["d52"] else "追高沒有肉"))
    if pz and pz["layers"][2]["ok"] and tag in ("below1", "at1"):
        # B102：站穩 3-1 低點以後，「還沒跌完、隨時再破低」跟三層驗證矛盾 → 狀態改成升級後的說法（下一關＝頸線、第一道關上緣）
        nx = pz.get("next") or {}
        nk = nx.get("neck") or []
        pu = pz.get("push")
        status = (f"已{v_cross} 3-1 {lo_hi}點 {_fmt(ext3['x'])}：單純的{lb['small']} 3-4 淘汰，升級{lb['big']}級{s_up}（路徑 A 或 C）；"
                  + (f"初推小 5 段走完，{pu['state']}；" if pu and pu["pull"] is not None else "")
                  + (f"撐壓互換頸線 {_fmt(nk[0][0])}～{_fmt(nk[-1][0])} {nx['neck_state'].split('：')[0]}，" if nk else "")
                  + f"再上去是第一道關上緣 {_fmt(gate1['far'])}")
        tag = "up3"
        lines[2] = status
    if sub and sub.get("done"):
        # B107 她 11/12：壓回跌破 (1) 高點 → 5-1 在最高點結束、日線 5-2 修正；5-2-A／B 拿來觀察，三個大買點分批
        zs = "、".join(f"{z['r']:g} {_fmt(z['v'])}" + (f"～{_fmt(z['near'])}" if z["near"] is not None else "") for z in sub["z52"])
        status = f"{sub['state']}；5-2 大買點 {zs}（分批、等止{s_dn}）"
        tag = "52"
        lines[2] = status
        et = (f"進場：5-2 是個股、0050 上車的位置——分批 {zs}，到了也要等止{s_dn}訊號；"
              + (f"5-2-B 反彈（{'、'.join(_fmt(v) for v, _ in sub['b52'])}）只拿來觀察、不追" if sub["b52"] else "5-2-A 還在走，先不急"))
        if entry:
            entry["t"] = et
        else:
            z0 = sub["z52"][0]
            entry = {"zone": [z0["lo"], z0["hi"]], "from": [sub["top"], sub["pb"]], "target": sub["top"], "t": et}
    if entry:
        lines.append(entry["t"])
    else:
        lines.append(f"進場：先看 0.382 {_fmt(fib[0.382])} 有沒有真的{'過' if d < 0 else '破'}，之後壓回的第二隻腳（{s_up}的 0.382～0.5）才考慮；"
                     "現在追沒有肉")
    return {"dir": d, "case": case, "tag": tag, "labels": lb,
            "big": {"T": T["p"], "L1": L1["p"], "H2": H2["p"], "ext": ext},
            "small": small_out, "fib": {str(r): round(v, 2) for r, v in fib.items()}, "rebound": round(R, 2),
            "gate1": gate1, "gate2": gate2, "fork": fork, "ext3": ext3, "entry": entry, "status": status, "lines": lines}


def pierce_reclaim(bars: list, lines: list, side: int, atr15: Optional[float], atr60: Optional[float],
                   win: int = 8, recent: int = 4) -> Optional[dict]:
    """B108 她的進場訊號（規則跟 B106 回測同一套）：最近 recent 根收完的 15 分 K 裡，有沒有「刺穿某條事先畫好的線、又收回」。
    side＝1 做多（往下刺、收回線上）、-1 做空（往上刺、收回線下）。bars：收完的 15 分 K（舊→新）；lines：[(價位, 名稱)]。
    刺穿深度 ≥ 0.15 ATR15、≤ 1 ATR60；8 根內收回；收回之後已經碰到停損（尖端外 0.1 ATR15）的不算。回最新的一個或 None"""
    n = len(bars)
    if n < 3 or not atr15 or not atr60:
        return None
    c = [side * b["close"] for b in bars]
    lo = [side * (b["low"] if side > 0 else b["high"]) for b in bars]
    best = None
    for line, name in lines:
        S = side * line
        for j in range(max(1, n - recent - win), n):
            if not (c[j - 1] > S and lo[j] < S):
                continue
            X = float("inf")
            for k in range(j, min(j + win, n)):
                X = min(X, lo[k])
                if S - X > atr60:
                    break                                             # 真的破了
                if c[k] > S:
                    stop = X - 0.1 * atr15
                    if (S - X >= 0.15 * atr15 and k >= n - recent and all(lo[m] > stop for m in range(k + 1, n))
                            and (best is None or k > best["_k"] or (k == best["_k"] and abs(c[k] - S) < best["_gap"]))):
                        e = bars[k]["close"]
                        risk = abs(e - side * stop)
                        best = {"_k": k, "_gap": abs(c[k] - S), "side": side, "line": line, "name": name, "tip": side * X,
                                "time": bars[k].get("time"), "ago": n - 1 - k, "close": e, "stop": round(side * stop, 2),
                                "risk": round(risk, 2), "t1": round(e + side * risk, 2)}
                    break
    if best:
        best = {k: v for k, v in best.items() if not k.startswith("_")}
    return best


METHOD = ("她的進出場（從 11/2～11/11 的對帳單推敲）：價位事先畫好 → 等價格刺穿又收回才進 → 停損放刺出去的尖端外 → "
          "一口一口出、先把停損拉到成本。回測：照這套機械化地做跟隨機差不多 △（B106），她的優勢在挑哪條線、挑哪一次")
EXIT = "出場：賺到跟停損一樣多的點數先出一口，剩下的停損拉到成本，之後一口一口出（她 11/11 的三口：+622、+805、+1,068 點）"


def plan_card(t: dict, price: float, bars15: Optional[list] = None, atr15: Optional[float] = None,
              atr60: Optional[float] = None) -> Optional[dict]:
    """B108 結論卡（用戶：簡單說現在的位階、在哪個波形裡，然後怎麼試單、怎麼進出場）。
    t＝structure() 的結果。回 {pos: [兩句位階], shape: 波形, plays: [{k, tag, t}], exit, flip, method, tiles, signal, watch}"""
    if not t:
        return None
    lb, u = t["labels"], -t["dir"]
    pu = ((t.get("ext3") or {}).get("paths") or {}).get("push") or {}
    sb = pu.get("sub") or {}
    price = float(price)
    pct = lambda v: round((v / price - 1) * 100, 2)                   # noqa: E731
    tile = lambda v, name, act: {"price": round(v, 2), "dist_pct": pct(v), "name": name, "act": act}   # noqa: E731
    rng = lambda a, b: _fmt(a) + (f"～{_fmt(b)}" if b != a else "")   # noqa: E731
    how_long = "跌破又收回（15 分 K 收回線上）才進，停損放最低點下面"
    longs, shorts, tiles, shape, flip = [], [], None, None, None
    plays = []
    if t["tag"] == "52" and sb.get("done") and u > 0:
        top, p0, a_low, b_hi, c_low, stage, zs = sb["top"], sb["p0"], sb["a_low"], sb.get("b_hi"), sb.get("c_low"), sb["stage"], sb["z52"]
        ztxt = "、".join(rng(z["lo"], z["hi"]) + ("（已到）" if z.get("hit") else "") for z in zs)
        nz = next((z for z in zs if not z.get("hit")), None)
        longs = [(z["v"], f"大買點 {z['r']:g}") for z in zs] + [(z["near"], f"大買點 {z['r']:g} 旁邊的前低") for z in zs if z["near"] is not None]
        pos = [f"{lb['big']}：第 5 大波裡的 5-2 回檔——5-1（{_fmt(p0)}→{_fmt(top)}，漲 {_fmt(top - p0)} 點）已經走完"]
        buy = {"k": "long", "tag": "做多等大買點",
               "t": f"{ztxt}——她說這三區才是 5-2 的最大買點（0050、個股也在這裡分批）；{how_long}"}
        down = tile(nz["hi"], "5-2 大買點", "跌破又收回才做多") if nz else tile(p0, "5-1 起點", "跌破＝看法作廢")
        if stage == "A":
            pos.append(f"{lb['small']}：5-2 走 A-B-C 三段——現在是 A 段下跌（到 {_fmt(a_low)}），還沒有像樣的反彈")
            shape = "三段式修正（A-B-C）的 A 段：第一段下跌"
            plays = [{"k": "wait", "tag": "不接刀、不追空", "t": "A 段還在跌，等它止跌、彈出 B 段再說；A 段直接跌進大買點也可以開始分批"}, buy]
            tiles = {"up": tile(top, "5-1 高點", "站上＝5-2 結束"), "down": down, "stop": None}
        elif stage == "B":
            lv = {r: v for (v, _), r in zip(sb["b52"], (0.382, 0.5, 0.618, 0.786))}
            rel = (f"還沒到 0.382 {_fmt(lv[0.382])}" if b_hi < lv[0.382] else
                   f"在 0.382～0.5（{_fmt(lv[0.382])}～{_fmt(lv[0.5])}）" if b_hi < lv[0.5] else
                   f"在 0.5～0.618（{_fmt(lv[0.5])}～{_fmt(lv[0.618])}）" if b_hi < lv[0.618] else
                   f"已過 0.618 的 {_fmt(lv[0.618])}、比她估的強一點" if b_hi < lv[0.786] else
                   f"已過 0.786 的 {_fmt(lv[0.786])}、反彈太強，要提防 5-2 已經在 {_fmt(a_low)} 結束")
            pos.append(f"{lb['small']}：5-2 走 A-B-C 三段——A 跌到 {_fmt(a_low)} 走完，現在是 B 段反彈（最高 {_fmt(b_hi)}，{rel}），C 段還沒走")
            shape = "三段式修正（A-B-C）的 B 段：逆著 5-2 的反彈，走完還有一段 C 往下"
            near = 0.5 * atr60 if atr60 else 0.004 * price
            hi_ok = b_hi - price >= 0.15 * (atr15 or 0.001 * price)   # B 高點就是現價（還在創高）時不算一條線
            res = sorted({round(v, 2) for v in [lv[0.5], lv[0.618], lv[0.786], top] + ([b_hi] if hi_ok else []) if v >= price - near})[:3]
            nm = {round(lv[0.5], 2): "B 反彈 0.5", round(lv[0.618], 2): "B 反彈 0.618", round(lv[0.786], 2): "B 反彈 0.786", round(top, 2): "5-1 高點",
                  round(b_hi, 2): "B 段高點"}
            shorts = [(v, nm.get(v, "反彈壓力")) for v in res]
            below = [v for v in (lv[0.618], lv[0.5], lv[0.382]) if v < price - (atr15 or 0)]
            t1 = max(below) if below else a_low
            plays = [{"k": "wait", "tag": "不追多", "t": "B 段只是反彈，她說 5-2-A、B「拿來觀察」；現在買，後面還有 C 段下跌"}]
            if res:
                plays.append({"k": "short", "tag": "小量試空",
                              "t": f"反彈壓力 {'、'.join(_fmt(v) for v in res)}：價格刺過其中一條、15 分 K 又收回線下才空（她 11/6、11/9 的空單都是這樣進的）；"
                                   f"停損放那根的最高點上面；目標先看 {_fmt(t1)}，再看 A 低點 {_fmt(a_low)}"})
            plays.append(buy)
            up_v = next((v for v in res if v > price), None)
            tiles = {"up": tile(up_v, nm.get(up_v, "反彈壓力"), "刺過又收回＝試空") if up_v else tile(top, "5-1 高點", "站上＝5-2 結束"),
                     "down": down, "stop": tile(top, "5-1 高點", "站上＝5-2 結束") if up_v and up_v != round(top, 2) else None}
        else:
            pos.append(f"{lb['small']}：5-2 走 A-B-C 三段——A 跌到 {_fmt(a_low)}、B 彈到 {_fmt(b_hi)} 都走完，現在是 C 段下跌（到 {_fmt(c_low)}），往大買點走")
            shape = "三段式修正（A-B-C）的 C 段：最後一段下跌，走完才是 5-3 起漲"
            ct = "、".join(f"{nm_.split('＝')[-1]} {_fmt(v)}" for v, nm_ in sb.get("c52") or [])
            plays = [{"k": "wait", "tag": "不追空", "t": f"C 段的目標就是大買點（量度：{ct}），追空沒有肉；手上有空單就照目標分批回補"}, buy]
            tiles = {"up": tile(b_hi, "B 段高點", "站上＝C 段沒了"), "down": down, "stop": tile(top, "5-1 高點", "站上＝5-1 還在走")}
        flip = (f"改判：站上 {_fmt(b_hi)}（B 段高點）＝C 段沒了、5-2 可能已經結束；" if stage == "C" else
                f"改判：站上 {_fmt(top)}＝5-2 提早結束、5-1 還在延伸；") + f"跌破 {_fmt(p0)}＝第 5 大波的看法作廢"
    elif t["tag"] == "up5" and sb and not sb.get("done") and u > 0:
        z4, lim, t5, in4 = sb["z4"], sb["limit"], sb["t5"], sb.get("pb") is not None
        seq = pu["seq"]
        pos = [f"{lb['big']}：第四大波修正走完，第 5 大波的第 1 段（5-1）推升中",
               f"{lb['small']}：5-1 走五小段——(1) {_fmt(seq[0])}→{_fmt(seq[5])}、(2) 橫台、(3) {_fmt(sb['launch'])}→{_fmt(sb['top3'])}，"
               + (f"現在是 (4) 回檔（到 {_fmt(sb['pb'])}）" if in4 else "(3) 還在走")]
        shape = "五段推動的第 (4) 段回檔：回完還有最後一推 (5)" if in4 else "五段推動的第 (3) 段：最會跑的一段"
        longs = [(float(z4["0.236"]), "(4) 淺回 0.236"), (float(z4["0.382"]), "(4) 標準 0.382")]
        if not in4:
            plays.append({"k": "wait", "tag": "不追高", "t": f"(3) 走到 {_fmt(sb['top3'])}，等 (4) 回檔出來再進"})
        plays.append({"k": "long", "tag": "做多等 (4) 回測",
                      "t": f"(4) 回到 {_fmt(z4['0.236'])}（淺）～{_fmt(z4['0.382'])}（標準）：{how_long}；目標最後一推 (5)：" + "、".join(_fmt(v) for v, _ in t5)})
        flip = f"改判：跌破 (1) 高點 {_fmt(lim[0])}（4 不能碰 1）＝5-1 已經結束、進 5-2 回檔"
        tiles = {"up": tile(t5[0][0], "(5) 目標", "最後一推") if t5 else None, "down": tile(float(z4["0.236"]), "(4) 回測", "止跌才做多"),
                 "stop": tile(lim[0], "(1) 高點", "跌破＝進 5-2")}
    elif pu and u > 0 and t["tag"] in ("up3", "4"):
        seq, zones, where = pu["seq"], pu["zones"], pu.get("where")
        pos = [f"{lb['big']}：{_fmt(seq[0])} 落底後的{lb['big']}級反彈（第 5 大波的 (1)，或大 B／C-4 的反彈，還分不出來）", f"{lb['small']}：{pu['state']}"]
        if pu.get("third"):
            shape = "初推五小段走完、壓回守住之後的第 (3) 浪（或小 c）推升"
            plays = [{"k": "long", "tag": "順勢做多", "t": f"守住 {_fmt(pu['pull'])} 推升結構就還在；回檔不破前低、{how_long}；量度 " + "、".join(_fmt(v) for v, _ in pu["targets"])}]
            tiles = {"up": tile(pu["targets"][0][0], "(3)／小 c 量度", "第一個目標") if pu["targets"] else None,
                     "down": tile(pu["pull"], "(2) 低點", "要守住"), "stop": tile(seq[0], "初推起點", "跌破＝作廢")}
        elif pu.get("pull") is not None:
            shape = "初推五小段走完後的壓回（(2) 浪或小 b）：三波整理、不會破起點，整理完還有一段上攻"
            zt = "、".join(f"{'①②③'[z['k'] - 1]} {rng(z['hi'], z['lo'])}" for z in zones)
            longs = [(v, f"壓回第 {z['k']} 區") for z in zones for v, _ in z["lv"]]
            plays = [{"k": "long", "tag": "做多等壓回", "t": f"壓回三區 {zt}：到了、{how_long}（最遠不能破 {_fmt(seq[0])}）；目標先看初推高點 {_fmt(seq[5])}"}]
            zk = zones[min(max(where or 1, 1), 3) - 1]
            tiles = {"up": tile(seq[5], "初推高點", "再過高＝(3) 啟動"), "down": tile(zk["hi"], f"壓回第 {zk['k']} 區", "止跌才做多"),
                     "stop": tile(seq[0], "初推起點", "跌破＝作廢")}
        else:
            shape = "初推五小段還在走"
            plays = [{"k": "wait", "tag": "不追高", "t": "初推還沒出現像樣的壓回，等壓回三區出來再進"}]
        flip = f"改判：跌破 {_fmt(seq[0])}＝初推失敗"
    else:
        pos = [t["lines"][0], t["status"]]
        plays = [{"k": "wait", "tag": "進場", "t": (t.get("entry") or {}).get("t") or t["lines"][-1]}]
    sig = None
    if bars15:
        cands = [x for x in (pierce_reclaim(bars15, longs, 1, atr15, atr60) if longs else None,
                             pierce_reclaim(bars15, shorts, -1, atr15, atr60) if shorts else None) if x]
        sig = min(cands, key=lambda x: x["ago"]) if cands else None
    return {"pos": pos, "shape": shape, "plays": plays, "exit": EXIT, "flip": flip, "method": METHOD, "tiles": tiles, "signal": sig,
            "watch": {"long": [(round(v, 2), nm_) for v, nm_ in longs], "short": [(round(v, 2), nm_) for v, nm_ in shorts]}}


def analyze_daily(df, price: Optional[float] = None) -> Optional[dict]:
    """個股日 K → structure()：大級＝日 K 中級轉折、小級＝日 K 小級轉折；5、10 均＝日線"""
    from wave import engine as E
    if df is None or len(df) < 120:
        return None
    h = df["high"].astype(float).to_numpy()
    l = df["low"].astype(float).to_numpy()
    c = df["close"].astype(float).to_numpy()
    if np.isnan(h[-120:]).any() or np.isnan(l[-120:]).any():
        return None
    px = float(price if price is not None else c[-1])
    bp = E.zigzag(h, l, E.thresholds(h, l, c, "mid"))
    tb = tentative(bp, h, l)
    big = bp + ([tb] if tb else [])
    if len(big) < 4:
        return None
    H2 = big[-2]
    sp = E.zigzag(h, l, E.thresholds(h, l, c, "small"))
    ts = tentative(sp, h, l)
    small = [q for q in sp if q["i"] > H2["i"]] + ([ts] if ts and ts["i"] > H2["i"] else [])
    small = [{"i": H2["i"], "p": H2["p"], "t": H2["t"]}] + small
    ma5 = float(np.mean(c[-5:])) if len(c) >= 5 else None
    ma10 = float(np.mean(c[-10:])) if len(c) >= 10 else None
    T, L1 = big[-4], big[-3]
    first = [q for q in sp if T["i"] <= q["i"] <= L1["i"]]
    gp = E.zigzag(h, l, E.thresholds(h, l, c, "big"))                # B98 全波段起點＝T 之前大波段的反向轉折
    full = next((q["p"] for q in reversed(gp) if q["i"] < T["i"] and q["t"] != T["t"]), None)
    out = structure(big, small, px, ma5, ma10, {"big": "中級（日 K 波段）", "small": "小級（日 K 短線）"}, first_leg=first, full=full)
    if out:
        dates = [str(x) for x in df["date"].tolist()] if "date" in df.columns else None
        if dates:
            for q in out["small"]["seq"]:
                if q.get("i") is not None and 0 <= q["i"] < len(dates):
                    q["date"] = dates[q["i"]]
            out["big"]["dates"] = {k: dates[q["i"]] for k, q in zip(("T", "L1", "H2", "X"), big[-4:]) if 0 <= q["i"] < len(dates)}
    return out


# ── B96 個股支撐補波浪價位：前低跌破、下一個前低太遠（群創 38 元、前低 22.95 −39.6%）時看波浪理論 ──
SUP_FIB = (0.382, 0.5, 0.618, 0.786)    # 0.236 太淺、不當支撐
SUP_WIN = 0.30                          # 只挑現價下面 30% 內的波浪價位
DEG_NAME = {"mid": "中波段", "big": "大波段"}


def _turns(h, l, c, deg: str) -> list:
    """日 K 這個級數到今天收盤看得到的轉折（確認過的＋進行中的極值），舊→新"""
    from wave import engine as E
    piv = E.zigzag(h, l, E.thresholds(h, l, c, deg))
    conf, tent = E.state_at(piv, h, l, len(c) - 1)
    return conf + ([tent] if tent else [])


def _up_leg(pts: list):
    """最近一段漲勢（低→高）：最後一點是高點＝正在漲的這段；最後一點是低點＝前一段漲勢"""
    if len(pts) >= 2 and pts[-1]["t"] == "H" and pts[-2]["t"] == "L":
        return pts[-2], pts[-1]
    if len(pts) >= 3 and pts[-1]["t"] == "L" and pts[-2]["t"] == "H" and pts[-3]["t"] == "L":
        return pts[-3], pts[-2]
    return None


def support_candidates(h, l, c) -> list:
    """波浪理論的支撐候選（不分在現價上下）：[{price, label}]
    - 中波段、大波段最近一段漲勢的 0.382／0.5／0.618／0.786 回檔
    - 中波段正在跌、前面是「高→低→較低的高」：這段跌勢＝前一段跌幅等幅（第 (3) 段＝第 (1) 段、或 C＝A）"""
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    c = np.asarray(c, dtype=float)
    if len(c) < 60 or np.isnan(h[-60:]).any() or np.isnan(l[-60:]).any():
        return []
    out, seen = [], set()

    def fib(deg, A, B):
        if (round(A, 2), round(B, 2)) in seen:
            return
        seen.add((round(A, 2), round(B, 2)))
        for r in SUP_FIB:
            out.append({"price": round(B - r * (B - A), 2), "label": f"{DEG_NAME[deg]} {_fmt(A)}→{_fmt(B)} 回檔 {r:g}"})
    for deg in ("mid", "big"):
        pts = _turns(h, l, c, deg)
        leg = _up_leg(pts)
        if leg:
            fib(deg, leg[0]["p"], leg[1]["p"])
        if deg == "big" and pts:
            # 整段大漲（資料裡最高點、跟它之前的最低點）：大級門檻在波動小的股票會把一段大漲切成好幾段，這段要另外列
            k = max(range(len(pts)), key=lambda j: pts[j]["p"] if pts[j]["t"] == "H" else -1e18)
            lows = [q for q in pts[:k] if q["t"] == "L"]
            if pts[k]["t"] == "H" and lows:
                fib(deg, min(q["p"] for q in lows), pts[k]["p"])
        if deg == "mid" and len(pts) >= 4 and [q["t"] for q in pts[-4:]] == ["H", "L", "H", "L"] and pts[-2]["p"] < pts[-4]["p"]:
            T, L1, H2 = pts[-4]["p"], pts[-3]["p"], pts[-2]["p"]
            v = H2 - (T - L1)
            if v > 0:
                out.append({"price": round(v, 2), "label": f"中波段 {_fmt(H2)} 起跌＝前一段跌幅（{_fmt(T)}→{_fmt(L1)}）等幅"})
    return [x for x in out if x["price"] > 0]


def support_zones(h, l, c, price: float, atr_v: float) -> list:
    """support_candidates 在 0.5 ATR 內合併成一區（整區不超過 1 ATR，同 wave.levels.make_zones），只留整區都在現價下面的；
    近的在前。回 [{price（區中間）, lo, hi, sources:[{price, label}]}]"""
    if not atr_v or not math.isfinite(atr_v) or not price:
        return []
    cs = sorted((x for x in support_candidates(h, l, c) if x["price"] < price), key=lambda x: x["price"])
    if not cs:
        return []
    tol = 0.5 * atr_v
    groups, cur = [], [cs[0]]
    for x in cs[1:]:
        if x["price"] - cur[-1]["price"] <= tol and x["price"] - cur[0]["price"] <= 2 * tol:
            cur.append(x)
        else:
            groups.append(cur)
            cur = [x]
    groups.append(cur)
    zones = [{"price": round(float(np.mean([x["price"] for x in g])), 2), "lo": g[0]["price"], "hi": g[-1]["price"],
              "sources": g[::-1]} for g in groups]
    return sorted(zones, key=lambda z: -z["hi"])
