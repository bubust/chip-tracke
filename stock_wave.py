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
import re
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
                    lows=sorted({q["p"] for q in seq if q["t"] != after[0]["t"]}
                                | {q["p"] for q in after[:jt + 1] if q["t"] != after[0]["t"]}), fine=fine)   # B113：初推裡沒併掉以前的低點也要（39,977）
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
    # B110：5-1 終點＝第一個「之後的壓回跌破 (1) 高點區」的高點；後來再創高也還是它（那是 5-3 啟動，不是 5-1 延伸）
    run = None
    for k in range(k3, len(rest)):
        q = rest[k]
        if q["t"] == top_t:
            if run is None or (q["p"] - rest[run]["p"]) * u > 0:
                run = k
        elif (run is not None and (q["p"] - lim[0]) * u < 0
              and abs(rest[run]["p"] - q["p"]) >= 0.15 * abs(rest[run]["p"] - launch)):
            return _done52(rest, top_t, u, p0, p5, sp, pull, price, launch, plat_hi, rest[run]["p"], lim, q["p"], lows, fine, big_hi)
    if in4 and (pb - lim[0]) * u < 0:
        return _done52(rest, top_t, u, p0, p5, sp, pull, price, launch, plat_hi, top3, lim, pb, lows, fine, big_hi)
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
            plat_hi: float, top: float, lim: list, pb: float, lows: Optional[list], fine: Optional[list],
            big_hi: Optional[float] = None) -> dict:
    """B107 她 11/12：5-1 結束、日線 5-2 修正（見 _sub5）。
    B110 她 11/15：B 高點之後回檔夠深但還沒破 A 低點 → fork（C 段第幾腳／較大 B 的 b，見 _fork52）；
    之後又站上 5-1 高點 → stage「3」（5-2 走完、5-3 啟動）"""
    big = abs(top - p0)
    k_top = next((k for k, q in enumerate(rest) if q["t"] == top_t and q["p"] == top), len(rest))
    fn = list(fine or [])
    f_top = max((k for k, q in enumerate(fn) if q.get("t") == top_t and abs(q["p"] - top) < 1e-6), default=0)   # B119：5-1 高點已經不在更細一級的轉折裡＝不用它找前低（不然會把 5-2 自己的低點算進去）
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
    # B113 她 11/16：第二層（破四萬深層洗盤底座 39,238～39,977）＝0.786＋上面 2% 內的前波平台低點
    f786 = top - u * 0.786 * big
    pl = [v for v in cand if 0 < (v - f786) * u <= 0.02 * abs(f786)]
    n786 = max(pl, key=lambda v: u * v) if pl else None
    z786 = {"r": 0.786, "v": round(f786, 2), "near": n786, "lo": round(min(f786, n786 if n786 is not None else f786), 2),
            "hi": round(max(f786, n786 if n786 is not None else f786), 2)}
    # 5-2 走 A-B-C：A 低點＝最高點之後第一個「彈回 ≥ 0.236 倍 A」的低點；B＝之後的反彈；再跌破 A 低點＝C
    pts = [q["p"] for q in rest[k_top + 1:]] + [float(price)]
    k_over = next((i for i, v in enumerate(pts) if (v - top) * u > 0), None)   # B110：又站上 5-1 高點
    hi53 = max(pts[k_over:], key=lambda v: u * v) if k_over is not None else None
    if k_over is not None:
        pts = pts[:k_over] or [pb]
    a_low = b_hi = c_low = lo = None
    tail = []                                                         # B 高點之後的點（5-3 啟動時：5-2 的終點＝這裡面最低的）
    for v in pts:
        if a_low is None:
            if lo is None or (v - lo) * u < 0:
                lo = v
            elif (v - lo) * u >= 0.236 * abs(top - lo):
                a_low, b_hi = lo, v
        elif c_low is None:
            if (v - b_hi) * u > 0:
                b_hi, tail = v, []
            elif (v - a_low) * u < 0:
                c_low = v
            else:
                tail.append(v)
        elif (v - c_low) * u < 0:
            c_low = v
    stage = "A" if a_low is None else "B" if c_low is None else "C"
    if a_low is None:
        a_low = lo if lo is not None else pb
    if stage == "B" and k_over is None:                               # B 高點：更細一級（30 分）在 A 低點之後的高點也算
        fa = next((k for k, q in enumerate(fn) if q.get("t") != top_t and abs(q["p"] - a_low) < 1e-6), None)
        if fa is not None:
            b_hi = max([b_hi * u] + [q["p"] * u for q in fn[fa + 1:] if q.get("t") == top_t]) * u
    fork = (_fork52(rest[k_top + 1:], fn, top_t, u, top, p0, a_low, b_hi, float(price), z52[0]["v"], big_hi)
            if stage == "B" and k_over is None else None)
    a_len = abs(top - a_low)
    in_b = stage != "A"
    b52 = [(round(a_low + u * r * a_len, 2), f"5-2-B 反彈 {r:g}" + ("（極限）" if r == 0.786 else "")) for r in (0.382, 0.5, 0.618, 0.786)]
    c52 = ([(round(b_hi - u * r * a_len, 2), f"5-2-C＝{nm}") for r, nm in ((0.618, "0.618 倍 A"), (1.0, "A 等幅"), (1.618, "1.618 倍 A"))]
           if stage == "C" else [])                                  # B112：跌很深的時候看 1.618 倍（11/16 低點 40,714 剛好是它）
    low_all = min([a_low] + ([float(price)] if k_over is None else []) + ([c_low] if c_low is not None else []), key=lambda v: u * v)
    for z in z52 + [z786]:
        z["hit"] = bool((low_all - z["hi"]) * u <= 0)                 # 已經跌到這一區
    cleg = (_c5(rest[k_top + 1:], top_t, u, b_hi, float(price), top=top, a_low=a_low, z382=z52[0]["v"])
            if stage == "C" and k_over is None else None)
    # B121 她 11/17 晚上：5-1 總漲幅的 0.8＝極限防線（39,137）；三種發展——守住＝5-2 極限洗盤直接 5-3；
    # 跌破 0.8＝日線第二隻大腳（W 底，回測 37,694）；37,694 收盤長黑跌破＝A 版 4-C 真 C-5 主跌段
    z80 = round(top - u * 0.8 * big, 2)
    depth = round(abs(top - low_all) / big, 3) if big else None
    dev = 1 if (low_all - z80) * u > 0 else 2 if (float(price) - p0) * u > 0 else 3
    zt = lambda z: f"{z['r']:g} {_fmt(z['v'])}" + (f"～{_fmt(z['near'])}（前低）" if z["near"] is not None else "")   # noqa: E731
    t53 = []
    if k_over is not None:                                            # B110：5-2 走完、5-3 啟動（她：帶量突破且首次回測踩穩）
        stage = "3"
        end52 = c_low if c_low is not None else min(tail, key=lambda v: u * v) if tail else a_low
        t53 = [(round(end52 + u * r * big, 2), f"5-3＝{nm}") for r, nm in ((1.0, "5-1 等幅"), (1.618, "1.618 倍 5-1"))]
        now_t = (f"又站上 5-1 高點 {_fmt(top)}（最高 {_fmt(hi53)}）＝5-2 在 {_fmt(end52)} 走完"
                 + (f"（最低 {_fmt(low_all)}，" if end52 != low_all else "（") + f"只回 {abs(top - low_all) / big:.2f} 倍）、5-3 啟動；"
                 f"要帶量突破、第一次回測 {_fmt(top)} 踩穩才算數")
        obs = (f"5-2 只回到 {_fmt(low_all)}（0.382 是 {_fmt(z52[0]['v'])}）就結束；5-3 的量度（僅參考）"
               + "、".join(f"{t.split('＝')[-1]} {_fmt(v)}" for v, t in t53) + f"；跌回 {_fmt(top)} 下面站不回去＝假突破、5-2 還沒完")
    elif fork:
        now_t = f"5-2-A {_fmt(top)}→{_fmt(a_low)}、5-2-B 彈到 {_fmt(b_hi)}（候選終點）；{fork['now']}"
        obs = fork["main"] + "；" + fork["alt"]
    elif stage == "A":
        now_t = f"5-2-A 進行中（到 {_fmt(a_low)}）"
        obs = f"A 還在走（到 {_fmt(a_low)}），先看 0.382 {_fmt(z52[0]['v'])}；A 走完才有 5-2-B 反彈"
    elif stage == "B":
        now_t = f"5-2-A {_fmt(top)}→{_fmt(a_low)}、5-2-B 反彈中（到 {_fmt(b_hi)}）"
        obs = (f"A {_fmt(top)}→{_fmt(a_low)}（{_fmt(a_len)} 點）；B 反彈 " + "、".join(f"{t.split()[-1]} {_fmt(v)}" for v, t in b52)
               + f"，最高多半壓在 0.618 附近、不會過 {_fmt(top)}；B 走完再看 5-2-C 往上面三區")
    else:
        now_t = (f"5-2-A {_fmt(top)}→{_fmt(a_low)}、5-2-B 彈到 {_fmt(b_hi)}、5-2-C 進行中（到 {_fmt(c_low)}"
                 + (f"；{cleg['now']}" if cleg else "") + "）")
        obs = (f"A {_fmt(top)}→{_fmt(a_low)}、B 彈到 {_fmt(b_hi)}；C 的量度 " + "、".join(f"{t.split('＝')[-1]} {_fmt(v)}" for v, t in c52)
               + "，C 走完才是 5-3 起漲")
    st = (f"5-1 在 {_fmt(top)} 結束（壓回到 {_fmt(low_all)}，跌破 (1) 高點 {_fmt(lim[0])}：4 不能碰 1，所以不是 (4)）；"
          + ("" if stage == "3" else "日線 5-2 修正中：") + now_t)
    lines = [f"大中小（她 11/11）：(1) {_fmt(p0)}→{_fmt(p5)}（{_fmt(sp)} 點）、(2) 橫台 {_fmt(pull)}～{_fmt(plat_hi)}、(3) {_fmt(launch)} 起；"
             f"她 11/12：{_fmt(top)} 是 5-1 終點（(3)(4)(5) 時間壓縮走完，或失敗第 5 波），{_fmt(p0)}→{_fmt(top)} 漲了 {_fmt(big)} 點",
             f"現在：{st}",
             f"5-2 三個大買點（{_fmt(p0)}→{_fmt(top)} 的回檔；個股、0050 分批介入，到了也要等止跌）：" + "、".join(zt(z) for z in z52),
             ("5-3 啟動（她 11/15）：" if stage == "3" else "她 11/15 的分歧：" if fork else "5-2-A／B 拿來觀察：") + obs]
    if fork:
        lines += fork["lines"][2:]                                    # 主追蹤、強替代上面那一行已經講了
    if cleg:
        lines += cleg["lines"]
    if stage == "C" and depth is not None:
        lines.append(f"5-2 回撤深度（她 11/17 晚上）：最低 {_fmt(low_all)}＝5-1 漲幅的 {depth:.1%}；0.786 {_fmt(z786['v'])}、極限 0.8 {_fmt(z80)}。"
                     f"三種發展：① 日線收盤守住 {_fmt(z80)}＝5-2 極限壓回洗盤，整理完直接 5-3"
                     f"② 跌破 {_fmt(z80)}＝日線級第二隻大腳（W 底），回測 {_fmt(p0)}，第二隻腳的低點才重算 5-1"
                     f"③ {_fmt(p0)} 被日線帶量長黑收盤跌破＝4-C 走真 C-5 主跌段（{_fmt(top)} 只是 4-C-4 反彈）。現在：第 {dev} 種")
    if stage == "C":
        lines.append(f"第二層（她 11/16：破四萬深層洗盤底座）{_fmt(z786['lo'])}" + (f"～{_fmt(z786['hi'])}" if z786["hi"] != z786["lo"] else "")
                     + f"：{_fmt(p0)}→{_fmt(top)} 的 0.786" + ("＋前波平台低點" if z786["near"] is not None else "")
                     + "；跌破大買點 0.618 才看這裡，要伴隨底背離、迅速收復才是洗盤底")
    return {"done": True, "stage": stage, "launch": launch, "plat": [pull, plat_hi], "top3": top, "top": top, "limit": lim, "pb": low_all,
            "p0": p0, "a_low": a_low, "b_hi": round(b_hi, 2) if in_b else None, "c_low": c_low, "b52": b52 if in_b else [], "c52": c52,
            "z52": z52, "z786": z786, "cleg": cleg, "z80": z80 if stage == "C" else None, "depth": depth if stage == "C" else None,
            "dev": dev if stage == "C" else None, "z4": {}, "t5": [], "d52": [(z["r"], z["lo"], z["hi"]) for z in z52], "fork": fork,
            "hi53": hi53, "t53": t53, "end52": end52 if stage == "3" else None, "state": st, "lines": lines}


def _legs_down(seq: list, low_t: str, top_t: str, u: int, price: float, cap: bool = True) -> list:
    """一段回檔切成腳：C-1（低）、C-2（高）、C-3（更低）…——沒破前低的低點算在反彈裡；現價已經跌破前一個低點＝下一腳開始；最多五腳"""
    legs = []
    for q in seq:
        if not legs:
            if q["t"] == low_t:
                legs.append(q)
        elif q["t"] == low_t:
            if legs[-1]["t"] == low_t:
                if (q["p"] - legs[-1]["p"]) * u < 0:
                    legs[-1] = q
            elif (q["p"] - legs[-2]["p"]) * u < 0:
                legs.append(q)
        elif legs[-1]["t"] == low_t:
            legs.append(q)
        elif (q["p"] - legs[-1]["p"]) * u > 0:
            legs[-1] = q
    if legs and legs[-1]["t"] == top_t and (price - legs[-2]["p"]) * u < 0:
        legs.append({"p": price, "t": low_t})
    if cap and len(legs) > 5:                                         # 超過五腳：後面的低點都併進第 5 腳
        legs = legs[:4] + [min((q for q in legs[4:] if q["t"] == low_t), key=lambda q: u * q["p"])]
    return legs


def _c5(after: list, top_t: str, u: int, b_hi: float, price: float, top: Optional[float] = None, a_low: Optional[float] = None,
        z382: Optional[float] = None) -> Optional[dict]:
    """B113 她 11/16：5-2-C 走「標準五波」（目前在 C-3 末端）→ C-3 踩煞車、C-4 橫盤箱體、C-5 最後一腳（動能衰竭只針尖刺穿，或等幅下殺摜破再收復）。
    用小級（60 分）轉折切（她：60 分決定切組）：C-1 44,824→42,956（1,868 點）、C-2 43,770、C-3 →40,714、C-4 41,465、C-5…；4 不能碰 1。
    C-5 的量度從 C-4 高點往下：0.618 倍 C-1（40,311；她的針尖區 40,313～40,451 下緣）、C-1 等幅（39,597；落在她的第二層 39,238～39,977）。
    after：5-1 高點之後的小級轉折。不到三腳回 None"""
    low_t = "L" if u > 0 else "H"
    kb = max((k for k, q in enumerate(after or []) if q.get("t") == top_t and abs(q["p"] - b_hi) < 1e-6), default=None)
    if kb is None:
        return None
    seq = [{"p": float(q["p"]), "t": q["t"]} for q in after[kb + 1:]]
    if not seq:
        return None
    if (price - seq[-1]["p"]) * (u if seq[-1]["t"] == top_t else -u) > 0:
        seq[-1]["p"] = price
    legs = _legs_down(seq, low_t, top_t, u, price)
    n = len(legs)
    if n < 3:
        return None
    lo_w, hi_w, dn_w = ("低", "高", "跌") if u > 0 else ("高", "低", "漲")
    c1 = abs(b_hi - legs[0]["p"])
    c3 = abs(legs[1]["p"] - legs[2]["p"])
    overlap = bool(n >= 4 and (legs[3]["p"] - legs[0]["p"]) * u > 0)
    names = "、".join(f"C-{k + 1} {_fmt(q['p'])}" for k, q in enumerate(legs))
    c4z, t5 = [], []
    if n == 3:                                                        # C-3 之後的 C-4 反彈：C-3 的 0.236～0.382，不能回到 C-1 低點上面
        c4z = [(round(legs[2]["p"] + u * r * c3, 2), f"C-3 的 {r:g}") for r in (0.236, 0.382)]
        now = f"C-3 {dn_w}到 {_fmt(legs[2]['p'])}（{c3 / c1:.2f} 倍 C-1）"
        nxt = (f"C-3 踩煞車以後是 C-4 橫盤箱體（反彈 " + "、".join(f"{t.split()[-1]} {_fmt(v)}" for v, t in c4z)
               + f"，不能回到 C-1 {lo_w}點 {_fmt(legs[0]['p'])} 上面），再走最後一腳 C-5")
    else:
        c4 = legs[3]["p"]
        t5 = [(round(c4 - u * r * c1, 2), f"C-5＝{nm}") for r, nm in ((0.618, "0.618 倍 C-1"), (1.0, "C-1 等幅"))]
        tt = "、".join(f"{t.split('＝')[-1]} {_fmt(v)}" for v, t in t5)
        if n == 4:
            now = f"C-4 反彈到 {_fmt(c4)}"
            nxt = f"C-4 是橫盤箱體，後面還有最後一腳 C-5（從 {_fmt(c4)} 往下量：{tt}）"
        else:
            ext = abs(legs[4]["p"] - legs[2]["p"])
            now = f"C-5 到 {_fmt(legs[4]['p'])}（比 C-3 {lo_w}點多{dn_w} {_fmt(ext)} 點）"
            nxt = (f"五腳走齊：站回 C-4 {hi_w}點 {_fmt(c4)} 才算 C 段走完；也可能 C-4 箱體還沒走完（{_fmt(c4)}～{_fmt(legs[4]['p'])} 只是箱體上下緣）、"
                   f"真正的 C-5 還在後面（{tt}）")
    # B119 她 11/17：C-5 之後站上 C-4 高點＝C 段走完（情境 A，看 5-3）；之後又跌破 C-5 低點＝C-5 延伸（情境 B「再踹最後一腳」）
    phase, c5a, reb, gates = "box", None, None, []
    raw = _legs_down(seq, low_t, top_t, u, price, cap=False)
    if n == 5 and len(raw) > 5:
        c5a, c4 = raw[4]["p"], raw[3]["p"]
        post = raw[5:]
        reb = max((q["p"] for q in post if q["t"] == top_t), key=lambda v: u * v, default=None)
        lows_post = [q["p"] for q in post if q["t"] == low_t]
        if reb is not None and (reb - c4) * u > 0:
            phase = "ext" if lows_post and (min(lows_post, key=lambda v: u * v) - c5a) * u < 0 else "done"
    cl = legs[4]["p"] if n == 5 else None
    if phase in ("done", "ext") and top is not None:
        k5 = max((k for k, q in enumerate(seq) if q["t"] == low_t and q["p"] == c5a), default=0)
        first_reb = next((q["p"] for q in seq[k5 + 1:] if q["t"] == top_t), reb)    # C-5 之後第一個反彈高點（她：41,627 仙人指路）
        g1 = sorted([legs[3]["p"], first_reb])
        gates.append({"k": 1, "name": "C-4 高點～C-5 之後第一個反彈高點", "lo": g1[0], "hi": g1[1],
                      "t": f"保留站穩＝5-3 起跳前漸入佳境（她：41,500～41,700）"})
        f382 = cl + u * 0.382 * abs(top - cl)
        if reb is not None and (reb - first_reb) * u > 0:            # 後來又彈得更高（11/17 早上 41,828）
            gates.append({"k": 2, "name": "C-5 之後最高的反彈高點", "lo": reb, "hi": reb, "t": "第二目標（她：41,650～41,745）"})
        elif z382 is None or (z382 - f382) * u > 0:
            gates.append({"k": 2, "name": f"{_fmt(top)}→{_fmt(cl)} 的 0.382", "lo": round(f382, 2), "hi": round(f382, 2),
                          "t": "第二目標（她：41,650～41,745）"})
        if z382 is not None and a_low is not None:
            g3 = sorted([z382, a_low])
            gates.append({"k": len(gates) + 1, "name": "大買點 0.382～5-2-A 低點（撐壓互換）", "lo": round(g3[0], 2), "hi": round(g3[1], 2),
                          "t": "站穩第二目標以後才看；三關都過才開啟 5-3（她：42,134～42,349）"})
    if phase == "done":
        now = f"C-5 在 {_fmt(c5a)} 走完，反彈到 {_fmt(reb)} 已站上 C-4 {hi_w}點 {_fmt(legs[3]['p'])}"
        nxt = (f"C 段走完（她 11/17 情境 A：C-5 打底吃貨）；5-3 要依序過關：" + "；".join(
            f"{'①②③'[g['k'] - 1]} {_fmt(g['lo'])}" + (f"～{_fmt(g['hi'])}" if g["hi"] != g["lo"] else "") + f"（{g['name']}）" for g in gates)
            + f"；跌破 {_fmt(c5a)}＝C-5 還沒走完")
    elif phase == "ext":
        now = f"C-5 先到 {_fmt(c5a)}、反彈 {_fmt(reb)} 站上 C-4 {hi_w}點後又跌破，{dn_w}到 {_fmt(cl)}"
        nxt = (f"站上 C-4 {hi_w}點以後又跌破 C-5 {lo_w}點 {_fmt(c5a)}＝C-5 還在延伸（她 11/17 情境 B：結算前再踹最後一腳黃金坑）；"
               f"跌深以後站回 {_fmt(c5a)} 才是買點（她：站回收上 40,616 就是很漂亮的買點），站不回去就看第二層")
    kind = "重疊型（4 碰到 1）" if overlap else "標準五波"
    lines = [f"5-2-C 的腳（她 11/16：{kind} 5-2-C；照小級轉折切）：{names}；C-1 {_fmt(c1)} 點、C-3 是它的 {c3 / c1:.2f} 倍",
             nxt]
    return {"legs": [{"k": k + 1, "p": q["p"], "t": q["t"]} for k, q in enumerate(legs)], "n": n, "overlap": overlap, "c1": round(c1, 2),
            "c4": legs[3]["p"] if n >= 4 else None, "c4z": c4z, "t5": t5, "now": now, "next": nxt, "kind": kind, "lines": lines,
            "phase": phase, "c5a": c5a, "reb": reb, "gates53": gates}


def _fork52(after: list, fn: list, top_t: str, u: int, top: float, p0: float, a_low: float, b_hi: float, price: float,
            z382: float, big_hi: Optional[float]) -> Optional[dict]:
    """B110 她 11/15：5-2-B 高點（44,824）之後的回檔夠深（≥ 0.382 倍 B）、但還沒跌破 A 低點（42,371）——是 C 段、還是 B 還沒走完：
    主追蹤＝重疊型（終結）5-2-C：C-1 43,692、C-2 44,423、C-3 42,956、C-4 反彈到 43,770（越過 C-1 低點＝4 碰到 1，標準推動 C 不成立，
    只能是允許重疊的終結 C）、後面還欠 C-5 破底；
    強替代＝44,824→42,956 只是較大 5-2-B 裡的 B-b，接著 B-c 往上補時間；再突破並守穩 44,824／44,911＝5-2 已在 42,956 走完、直接 5-3。
    往上三關：控制區（她 43,834～43,890：43,890＝44,824→42,956 的 0.5；下緣網站用 44,423→42,956 的 0.618＝43,863）、
    C-2 高點 44,423、B 高點／5-1 高點 44,824／44,911。
    往下三道：這段反彈的 0.382（43,459＋旁邊的前低 43,492；她 43,454～43,500）、0.618（43,267；她 43,272）、C-3 低點 42,956；
    再下面 A 低點 42,371、母級共振 42,154～42,496（5-1 的 0.382、50,265→37,694 的 0.382 回升）。
    after：5-1 高點之後的小級（60 分）轉折；fn：更細一級（30 分）轉折，B 高點之後的腳先用它數。回 None＝回檔還不夠深"""
    low_t = "L" if u > 0 else "H"
    b_len = abs(b_hi - a_low)
    seq = None
    for src in (fn, after):                                           # B 高點之後的轉折：先用更細一級，沒有才用小級
        kb = max((k for k, q in enumerate(src or []) if q.get("t") == top_t and abs(q["p"] - b_hi) < 1e-6), default=None)
        if kb is not None:
            seq = [{"p": float(q["p"]), "t": q["t"]} for q in src[kb + 1:]]
            break
    seq = seq or [{"p": price, "t": low_t}]
    if (price - seq[-1]["p"]) * (u if seq[-1]["t"] == top_t else -u) > 0:
        seq[-1]["p"] = price                                          # 最後一腳還在走：用現價延長
    legs = _legs_down(seq, low_t, top_t, u, price)
    if not legs:
        return None
    n = len(legs)
    k_lo = max(k for k in range(n) if legs[k]["t"] == low_t)
    c_lo = legs[k_lo]["p"]                                            # 這段回檔的最低點（C-3 低點 42,956）
    if (b_hi - c_lo) * u < 0.382 * b_len or (c_lo - a_low) * u <= 0:
        return None
    g2 = legs[k_lo - 1]["p"] if k_lo >= 1 else None                   # 最低點前面那個反彈高點（C-2 高點 44,423）
    prev_lo = legs[k_lo - 2]["p"] if k_lo >= 2 else None              # 再前面的低點（跌破它才有現在這一腳）
    rb_hi = legs[-1]["p"] if legs[-1]["t"] == top_t else max(price, c_lo, key=lambda v: u * v)   # 從最低點彈到哪
    rb = abs(rb_hi - c_lo)
    fall = abs(b_hi - c_lo)
    falling = legs[-1]["t"] == low_t and rb < 0.146 * (abs(g2 - c_lo) if g2 is not None else fall)   # 這一腳還在跌、沒有像樣的反彈
    overlap = bool(n >= 4 and (legs[3]["p"] - legs[0]["p"]) * u > 0)   # 第 4 腳越過第 1 腳的低點
    dn_w, up_w = ("跌", "反彈") if u > 0 else ("漲", "拉回")
    lo_w, hi_w = ("低", "高") if u > 0 else ("高", "低")
    brk = "破底" if u > 0 else "破頂"
    v_dn, v_up = ("跌破", "站穩") if u > 0 else ("漲過", "跌破")
    nxt_dn = min(k_lo + 3, 5)                                         # 再破底的話是第幾腳
    g2_nm = f"C-{k_lo} {hi_w}點"
    up, down = [], []
    if falling:
        if prev_lo is not None:
            up.append({"kind": "prev", "name": f"C-{k_lo - 1} {lo_w}點（剛{v_dn}）", "lo": prev_lo, "hi": prev_lo, "lv": [(prev_lo, f"C-{k_lo - 1} {lo_w}點")],
                       "t": f"站回去＝假{v_dn}，這一腳可能已經走完"})
    else:
        zc_lv = (([(c_lo + u * 0.618 * abs(g2 - c_lo), f"{_fmt(g2)}→{_fmt(c_lo)} 的 0.618")] if g2 is not None else [])
                 + [(c_lo + u * 0.5 * fall, f"{_fmt(b_hi)}→{_fmt(c_lo)} 的 0.5")])
        zc = sorted(v for v, _ in zc_lv)
        up.append({"kind": "ctrl", "name": "控制區", "lo": round(zc[0], 2), "hi": round(zc[-1], 2), "lv": [(round(v, 2), t) for v, t in zc_lv],
                   "t": f"只判斷修復有沒有傳到小級；站不穩＝只是 C-{k_lo + 2} {up_w}、還保留一腳{brk}"})
    if g2 is not None:
        up.append({"kind": "g2", "name": g2_nm, "lo": g2, "hi": g2, "lv": [(g2, g2_nm)],
                   "t": f"K 棒實體{v_up}＝排除再{brk}的 C-{nxt_dn}，B-b 落底轉上取得優勢"})
    g3 = sorted([b_hi, top])
    up.append({"kind": "g3", "name": f"B {hi_w}點／5-1 {hi_w}點", "lo": round(g3[0], 2), "hi": round(g3[1], 2),
               "lv": [(round(b_hi, 2), f"5-2-B {hi_w}點"), (round(top, 2), f"5-1 {hi_w}點")],
               "t": f"遇壓折返＝B-c 高檔折返補時間；帶量突破、第一次回測踩穩＝5-2 已在 {_fmt(c_lo)} 走完、啟動 5-3"})
    if not falling:
        if rb >= 0.236 * fall:                                        # 有像樣的反彈才有「墊高結構」的兩道防線
            d1 = rb_hi - u * 0.382 * rb
            nr = [q["p"] for q in (fn or []) if q.get("t") == low_t and 0 < (q["p"] - d1) * u <= 0.0015 * abs(d1)]
            nv = max(nr, key=lambda v: u * v) if nr else None
            z1 = sorted([d1] + ([nv] if nv is not None else []))
            down.append({"kind": "r382", "name": f"{up_w} 0.382", "lo": round(z1[0], 2), "hi": round(z1[-1], 2),
                         "lv": [(round(d1, 2), f"{_fmt(c_lo)}→{_fmt(rb_hi)} 的 0.382")] + ([(nv, f"前{lo_w}")] if nv is not None else []),
                         "t": f"{v_dn}＝短線修復轉弱"})
            d2 = rb_hi - u * 0.618 * rb
            down.append({"kind": "r618", "name": f"{up_w} 0.618", "lo": round(d2, 2), "hi": round(d2, 2),
                         "lv": [(round(d2, 2), f"{_fmt(c_lo)}→{_fmt(rb_hi)} 的 0.618")],
                         "t": f"再{v_dn}＝{_fmt(c_lo)} 起的墊高結構破壞，這段{up_w}有結束的疑慮"})
        down.append({"kind": "lo", "name": f"C-{k_lo + 1} {lo_w}點", "lo": c_lo, "hi": c_lo, "lv": [(c_lo, f"C-{k_lo + 1} {lo_w}點")],
                     "t": f"{v_dn}而且收在{'下' if u > 0 else '上'}面＝" + (f"C-{nxt_dn} 取得主導" if k_lo + 1 < 5 else "第 5 腳還在延伸")})
    for k, g in enumerate(up):
        g["k"] = k + 1
    for k, g in enumerate(down):
        g["k"] = k + 1
    big382 = p0 + u * 0.382 * abs(big_hi - p0) if big_hi is not None and (big_hi - p0) * u > 0 else None
    dz = sorted([z382] + ([big382] if big382 is not None and abs(big382 / z382 - 1) < 0.015 else []))
    deep = {"a_low": a_low, "lo": round(dz[0], 2), "hi": round(dz[-1], 2),
            "lv": [(round(z382, 2), f"{_fmt(p0)}→{_fmt(top)} 的 0.382")]
                  + ([(round(big382, 2), f"{_fmt(big_hi)}→{_fmt(p0)} 的 0.382 回升")] if len(dz) > 1 else [])}
    zt = lambda g: _fmt(g["lo"]) + (f"～{_fmt(g['hi'])}" if g["hi"] != g["lo"] else "")   # noqa: E731
    deep_t = zt(deep)
    g2_t = _fmt(g2) if g2 is not None else _fmt(b_hi)
    names = "、".join(f"C-{k + 1} {_fmt(q['p'])}" for k, q in enumerate(legs[:-1]))
    cur = f"C-{n} {up_w if n % 2 == 0 else dn_w}到 {_fmt(legs[-1]['p'])}"
    if falling:
        where = "fall"
        now = (f"C-{n} {'下跌' if u > 0 else '上漲'}中（到 {_fmt(c_lo)}）" + (f"、已{v_dn} C-{k_lo - 1} {lo_w}點 {_fmt(prev_lo)}" if prev_lo is not None else "")
               + ("：C 段最後一腳，" if n >= 5 else "，") + f"往 {_fmt(a_low)}、{deep_t}")
    elif g2 is not None and (price - g2) * u > 0:
        where, now = "bc", f"站上 {_fmt(g2)}：排除再{brk}，B-b 在 {_fmt(c_lo)} 落底、往 {_fmt(b_hi)} 走 B-c（要 K 棒實體站穩）"
    elif (price - (up[0]["hi"] if u > 0 else up[0]["lo"])) * u > 0:
        where, now = "above", f"{_fmt(c_lo)} 起{up_w}到 {_fmt(rb_hi)}，過了控制區 {zt(up[0])}、還沒到 {g2_t}"
    elif (price - (up[0]["lo"] if u > 0 else up[0]["hi"])) * u >= 0:
        where, now = "ctrl", f"{_fmt(c_lo)} 起{up_w}到 {_fmt(rb_hi)}，正在控制區 {zt(up[0])}：站不站得穩決定{up_w}有沒有傳到小級"
    else:
        where, now = "mid", f"{_fmt(c_lo)} 起{up_w}到 {_fmt(rb_hi)}，還在控制區 {zt(up[0])} 下面"
    if n >= 4:
        ov = (f"已越過 C-1 {lo_w}點 {_fmt(legs[0]['p'])}（4 碰到 1）→ 標準推動 C 不成立，只能是允許重疊的終結 C" if overlap
              else f"沒碰到 C-1 {lo_w}點 {_fmt(legs[0]['p'])}")
        main = (f"主追蹤＝{'重疊型 ' if overlap else ''}5-2-C：{names}、{cur}（C-4 {ov}）"
                + (f"，後面還欠 C-5 {brk}" if n == 4 else "，五腳走齊就進入落底觀察"))
    else:
        main = "主追蹤＝5-2-C 已經開始：" + (names + "、" if names else "") + cur
    alt = (f"強替代＝{_fmt(b_hi)}→{_fmt(c_lo)} 只是較大 5-2-B 裡的 B-b 壓回，接著 B-c 往上補時間；"
           f"再突破並守穩 {_fmt(b_hi)}／{_fmt(top)}＝5-2 已在 {_fmt(c_lo)} 走完、直接 5-3")
    evo = [f"補空間：{up_w}受阻轉弱、再補一腳破 {_fmt(prev_lo if falling and prev_lo is not None else c_lo)} → {_fmt(a_low)}、{deep_t}（母級共振區，到了等止穩才出手）",
           f"補時間或轉推：站穩 {g2_t}＝B-b 落底、走 B-c；突破 {_fmt(b_hi)}／{_fmt(top)} 且回測踩穩＝直攻 5-3",
           f"中性收斂：上不過 {g2_t}、下守 {_fmt(c_lo)}，區間壓縮，先不急著加浪名"]
    lines = [main, alt,
             "往上三關：" + "；".join(f"{'①②③'[g['k'] - 1]} {zt(g)}（{g['name']}）{g['t']}" for g in up),
             ("往下三道防線：" + "；".join(f"{'①②③'[g['k'] - 1]} {zt(g)}（{g['name']}）{g['t']}" for g in down) + "；再下面 " if down else "往下：")
             + f"{_fmt(a_low)}（A {lo_w}點）、{deep_t}（" + "、".join(t for _, t in deep["lv"]) + "）",
             "三種演化：" + "；".join(f"{'①②③'[k]} {t}" for k, t in enumerate(evo)),
             f"現在：{now}"]
    return {"legs": [{"k": k + 1, "p": q["p"], "t": q["t"]} for k, q in enumerate(legs)], "n": n, "overlap": overlap,
            "c_lo": c_lo, "g2": g2, "prev_lo": prev_lo, "rb_hi": round(rb_hi, 2), "b_hi": round(b_hi, 2), "up": up, "down": down, "deep": deep,
            "where": where, "now": now, "main": main, "alt": alt, "evo": evo, "lines": lines}


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
        fk = sub.get("fork")
        status = sub["state"] if sub["stage"] == "3" else f"{sub['state']}；5-2 大買點 {zs}（分批、等止{s_dn}）"
        tag = "52"
        lines[2] = status
        if sub["stage"] == "3":                                       # B110 她 11/15：突破要帶量、第一次回測踩穩
            et = (f"進場：{_fmt(sub['top'])} 突破以後不追——等第一次回測 {_fmt(sub['top'])} 踩穩再進（她 11/15）；"
                  f"跌回 {_fmt(sub['top'])} 下面站不回去＝假突破")
        elif fk:
            g2t = _fmt(fk["g2"]) if fk["g2"] is not None else _fmt(fk["b_hi"])
            et = (f"進場：{_fmt(fk['c_lo'])}～{g2t} 中間兩種看法還沒分出來，先不出手；跌破 {_fmt(fk['c_lo'])} 往 {_fmt(sub['a_low'])}、"
                  f"{_fmt(fk['deep']['lo'])}～{_fmt(fk['deep']['hi'])} 等止{s_dn}才分批（5-2 大買點 {zs}）；站穩 {g2t} 才考慮順著做")
        else:
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
    return {"dir": d, "case": case, "tag": tag, "labels": lb, "ma5": ma5, "full": full,
            "big": {"T": T["p"], "L1": L1["p"], "H2": H2["p"], "ext": ext},
            "small": small_out, "fib": {str(r): round(v, 2) for r, v in fib.items()}, "rebound": round(R, 2),
            "gate1": gate1, "gate2": gate2, "fork": fork, "ext3": ext3, "entry": entry, "status": status, "lines": lines}


def merge_pause(big: list) -> list:
    """B123 她 11/22：50,265→37,694 中間雖有 45,523→47,607 的小停頓，但日線 5T／12T 下壓斜率沒被切開＝同一筆日線下跌。
    最後一段又創新極值（33,719 破 37,694）時，往前看 a(50,265) b(45,523) c(47,607) d(37,694)：c 沒過 a、d 破 b，
    而且停頓 b→c 不到 a→b 的一半 → 拿掉 b、c，日線變成 a→d→H2→現在。沒有創新極值（例：42,371 沒破 37,694）就不動"""
    if len(big) < 6:
        return big
    a, b, c, d, h2, x = big[-6:]
    if not (a["t"] == c["t"] == h2["t"] != b["t"] == d["t"] == x["t"]):
        return big
    s = 1 if a["t"] == "H" else -1                                    # 1＝a 是高點（一路往下）
    if (d["p"] - x["p"]) * s <= 0 or (a["p"] - c["p"]) * s <= 0 or (b["p"] - d["p"]) * s <= 0:
        return big
    if abs(c["p"] - b["p"]) >= 0.5 * abs(a["p"] - b["p"]):
        return big
    return big[:-5] + big[-3:]


def big_frame(t: dict, price: float, full: Optional[float] = None, lows: Optional[list] = None,
              cyc: Optional[list] = None, leg: Optional[tuple] = None, clock: Optional[dict] = None,
              supply: Optional[list] = None) -> Optional[dict]:
    """B123 她 11/22～11/23（T3 MONTHLY／DAILY MOTHER MAP 四張）：日線 T→L1→H2→ext 三筆跌完（ext 破 L1）之後的反彈怎麼看。
    - 第一道牆＝L1（37,694，1、4 重疊魔咒）；第二道牆＝T→ext 的 0.382／0.5／0.618（40,040／41,992／43,944）；再上去前高 H2（44,911）
    - 尋底帶＝full→T 的 0.5（33,640）～H2 往下等幅 T−L1（32,340）；破了看延伸區＝前一個日線大低點（31,740）～full→T 的 0.618（29,717）
    - 三種發展：① 五波下跌（反彈壓在 L1 下面＝第 4 浪，再殺第 5 浪）② 過第一道、卡第二道＝大 B 波（之後大 C 破底）③ 兩道都站穩、攻回 H2＝月線大四浪完成
    t＝structure()；full＝全波段起點（17,015）；lows＝T 之前的日線低點（最後一個＝T 的起漲點 39,442，現在這段要跌破它才算升級；也拿來找 31,740）；cyc＝月線級的低點（8,268、12,652）；
    leg＝最近一段 15 分上漲 (lo, hi)（短線鎖利的 0.236，她 11/23：36,280→40,324 的 0.236＝39,370）。不是這種結構回 None"""
    if not t or t.get("dir") != -1 or t.get("case") != "3":
        return None
    T, L1, H2, ext = (float(t["big"][k]) for k in ("T", "L1", "H2", "ext"))
    price = float(price)
    if not (T > H2 > L1 > ext) or price <= ext:
        return None
    if not lows or ext >= float(lows[-1]):                            # 她：幾乎把起漲那段吐回（33,719 破 50,265 的起漲點 39,442）＝修正跨級數升級
        return None
    span = T - ext
    w2 = [(r, ext + r * span) for r in (0.382, 0.5, 0.618)]
    w382, w5, w618 = (v for _, v in w2)
    band = ext_band = None
    if full and full < ext:
        b5, ca = full + 0.5 * (T - full), H2 - (T - L1)
        e618 = T - 0.618 * (T - full)
        band = sorted([b5, ca], reverse=True)
        pl = [float(v) for v in (lows or []) if e618 < float(v) < band[-1]]
        ext_band = [pl[-1] if pl else band[-1], e618]
    rb = max(price, float(t.get("rebound") or price))                 # 反彈最高到哪
    stage = ("top" if price >= H2 else "w2p" if price >= w618 else "w0" if price < L1 else
             "w2" if price >= w382 or rb >= w382 else "w1")                      # 碰過第二道牆又跌回第一道牆下面＝w0
    dev = 3 if stage == "top" else 1 if stage == "w0" else 2
    d236 = None
    if leg and leg[1] > leg[0] and leg[1] > price - 1e-9 * price:
        d236 = {"lo": float(leg[0]), "hi": float(leg[1]), "v": round(leg[1] - 0.236 * (leg[1] - leg[0]), 2)}
    mo = None
    if cyc and len(cyc) >= 2:
        mo = {"a": float(cyc[0]), "b": float(cyc[1])}
    f = _fmt
    w2t = f"{f(w382)}～{f(w618)}"
    st = {"w0": f"反彈還在第一道牆 {f(L1)} 下面：五波下跌的第 4 浪（頂過不了 {f(L1)}、之後再殺第 5 浪），還是三波末端已經跌完（要帶量實體站穩 {f(L1)} 才算），還分不出來",
          "w1": f"站上第一道牆 {f(L1)}（要帶量實體收盤站穩才算）＝打破 1、4 重疊，五波下跌的看法淘汰；{f(T)}→{f(ext)} 這一段結束，下一關第二道牆 {w2t}",
          "w2": f"{f(T)}→{f(ext)} 這一段正式結束；站上第一道牆 {f(L1)}、碰到第二道牆 {w2t}（最高 {f(rb)}）——先當反彈大 B 波，"
                f"之後在 {w2t} 的發展才是分辨大 B 波還是重新啟動的關鍵",
          "w2p": f"過了第二道牆 0.618 {f(w618)}，剩前高 {f(H2)}：站穩就是月線大四浪完成",
          "top": f"連過兩道牆並站上前高 {f(H2)}＝月線大四浪完成，轉看第五大浪創高（要守穩 {f(H2)}）"}[stage]
    lines = [f"日線：{f(T)}→{f(L1)} 是同一筆下跌（中間的小停頓不算，5T、12T 下壓斜率沒切開），{f(L1)}→{f(H2)} 是第一個有效反彈"
             f"（+{f(H2 - L1)} 點），{f(H2)}→{f(ext)} 再跌 {f(H2 - ext)} 點",
             f"現在 {f(price)}：{st}"]
    if mo:
        lines.insert(0, f"月線：{f(T)} 是從 {f(mo['a'])} 起算走完五浪的六年大頂，還是從 {f(mo['b'])} 起算、大三浪之後的大四浪洗盤？"
                        + (f"大四浪的底線 {f(band[0])}～{f(band[1])}（極限 {f(ext_band[1])}）" if band else ""))
    if band:
        lines.append(f"尋底帶 {f(band[0])}～{f(band[1])}（{f(full)}→{f(T)} 的 0.5、{f(H2)} 往下等幅）；跌破看延伸區 {f(ext_band[0])}～{f(ext_band[1])}"
                     f"（{f(full)}→{f(T)} 的 0.618）；連 {f(ext_band[1])} 都灌破、反彈又壓在 {f(L1)} 下＝六年大頂")
    lines.append(f"兩道牆：第一道 {f(L1)}（帶量實體站穩＝止跌確認）；第二道 " + "→".join(f"{f(v)}（{r:g}）" for r, v in w2)
                 + f"，過第一道卻在第二道量縮折返＝大頂之後的大 B 波（彈完再殺大 C）；連過兩道並站穩 {f(H2)}＝月線大四浪完成")
    fr = {"L1": L1, "ext": ext, "band": band, "stage": stage, "clock": clock}
    cl = _clock_lines(fr) if clock else []
    sl = _supply_line(supply, H2, ext, price)
    if sl:
        cl.append(sl)
    if cl:
        lines[-1:-1] = cl
        if clock and clock.get("up_days"):
            lines[1 if mo else 0] = lines[1 if mo else 0].replace("第一個有效反彈（", f"第一個有效反彈（{clock['up_days']} 天 ")
    return {"T": T, "L1": L1, "H2": H2, "ext": ext, "rb": rb, "w2": [(r, round(v, 2)) for r, v in w2], "clock": clock, "supply": supply or [],
            "band": [round(v, 2) for v in band] if band else None, "ext_band": [round(v, 2) for v in ext_band] if ext_band else None,
            "full": full, "mo": mo, "stage": stage, "dev": dev, "d236": d236, "status": st, "lines": lines}


def frame_clock(bars: list, weekly: list, d_l1: str, d_h2: str, d_ext: str, today: str) -> dict:
    """B124 用戶 11/24「你注意一下時間」：她的判斷都帶時間——
    ① 37,694→44,911「只花 4 天」；② 五波版的第 4 浪「止跌後只彈 5～10 天」；③「下週同時收週線與 11 月月線」（11/27 週線、11/30 月 K 長下影、守住月 20T）；
    ④ 換手量要比 11/06（231,828 口）、3 月（302,178 口）那種日線天量。
    bars＝日 K [{time 'YYYY-MM-DD', open, high, low, close, volume}]（最後一根可能是今天還沒收完）；weekly＝週 K（time＝那週第一天）；日期都是 'YYYY-MM-DD'"""
    import datetime as _dt
    days = [str(b["time"])[:10] for b in bars]
    td = _dt.date.fromisoformat(today)
    wk = td + _dt.timedelta(days=(4 - td.weekday()) % 7)              # 這週五
    nm = (td.replace(day=28) + _dt.timedelta(days=4)).replace(day=1)
    me = nm - _dt.timedelta(days=1)
    while me.weekday() >= 5:
        me -= _dt.timedelta(days=1)
    out = {"today": today, "wk_close": wk.isoformat(), "mo_close": me.isoformat(),
           "up_days": sum(1 for d in days if d_l1 < d <= d_h2) if d_l1 and d_h2 else None,
           "reb_days": sum(1 for d in days if d_ext < d <= today) if d_ext else None}
    vol = {d: float(b.get("volume") or 0) for d, b in zip(days, bars)}
    if d_ext and vol:
        prev = [(v, d) for d, v in vol.items() if d < d_ext and d >= (_dt.date.fromisoformat(d_ext) - _dt.timedelta(days=365)).isoformat()]
        mx = max(prev) if prev else (0, None)
        reb = [(v, d) for d, v in vol.items() if d >= d_ext]
        rb = max(reb) if reb else (0, None)
        out["vol"] = {"l1": vol.get(d_l1), "l1_date": d_l1, "max": mx[0], "max_date": mx[1], "reb": rb[0], "reb_date": rb[1],
                      "big": bool(vol.get(d_l1) and rb[0] >= vol[d_l1])}
    mon = today[:7]
    mb = [b for d, b in zip(days, bars) if d.startswith(mon)]
    if mb:
        o, lo, c = float(mb[0]["open"]), min(float(b["low"]) for b in mb), float(mb[-1]["close"])
        out["month"] = {"open": o, "low": lo, "close": c, "shadow": round(min(o, c) - lo, 2)}
    mc = {}                                                            # 月收盤：週 K 用那週週五落在哪個月；本月用日 K 現價
    for w in weekly or []:
        d = _dt.date.fromisoformat(str(w["time"])[:10]) + _dt.timedelta(days=4)
        mc[d.isoformat()[:7]] = float(w["close"])
    if mb:
        mc[mon] = float(mb[-1]["close"])
    ks = sorted(mc)
    if len(ks) >= 20:
        out["m20"] = round(sum(mc[k] for k in ks[-20:]) / 20, 2)
    return out


def _clock_lines(fr: dict) -> list:
    """B124：時間、量能兩句（給 big_frame 的文字和結論卡）"""
    ck = fr.get("clock") or {}
    if not ck:
        return []
    f = _fmt
    md = lambda d: f"{int(d[5:7])}/{int(d[8:10])}"                    # noqa: E731
    wd = lambda d: "一二三四五六日"[__import__("datetime").date.fromisoformat(d).weekday()]   # noqa: E731
    L1, ext, band = fr["L1"], fr["ext"], fr.get("band")
    out = []
    t = []
    if ck.get("reb_days") is not None:
        t.append(f"{f(ext)} 之後第 {ck['reb_days']} 個交易日" + ("（五波版的第 4 浪只彈 5～10 天、頂過不了 " + f(L1) + "）" if fr["stage"] in ("w0", "w1") or ck["reb_days"] <= 10 else ""))
    mo = ck.get("month")
    m20 = ck.get("m20")
    t.append(f"{md(ck['wk_close'])}（{wd(ck['wk_close'])}）收週線、{md(ck['mo_close'])}（{wd(ck['mo_close'])}）收月線："
             + (f"月 K 要在尋底帶 {f(band[0])}～{f(band[1])} 之上止跌" if band else "月 K 要止跌")
             + "、留長下影線" + (f"、守住月 20T（約 {f(m20)}）" if m20 else "")
             + (f"；這個月開 {f(mo['open'])}、最低 {f(mo['low'])}、現在 {f(mo['close'])}，下影線 {f(mo['shadow'])} 點" if mo else "")
             + (("（月 20T 現在" + ("守住" if mo and mo["close"] >= m20 else "還沒站回") + "）") if m20 and mo else ""))
    out.append("時間：" + "；".join(t))
    v = ck.get("vol")
    if v and v.get("l1"):
        out.append(f"量：反彈以來最大 {f(v['reb'])} 口（{md(v['reb_date'])}）" + ("，已超過" if v["big"] else "，還沒超過")
                   + f" {md(v['l1_date'])} 的 {f(v['l1'])} 口" + (f"、一年最大 {f(v['max'])} 口（{md(v['max_date'])}）" if v.get("max") else "")
                   + ("——有換手量" if v["big"] else "——還不算日線級換手天量，「帶量站穩」要再看"))
    return out


def _supply_line(supply: Optional[list], H2: float, ext: float, price: float) -> Optional[str]:
    """B125 用戶 11/24「把量能分析加進來」：她 11/23 的 39,500～41,500 套牢賣壓＝44,911→33,719 這段下跌的成交分布最密的地方"""
    if not supply:
        return None
    f = _fmt
    sd = {"up": "在現價上面＝反彈到這裡會湧出解套賣壓", "at": "現價就在裡面＝正在消化解套賣壓", "down": "已經站上＝這段的換手成本，回測要守"}
    parts = []
    for z in supply[:2]:
        when = f"，{z['first']}～{z['last']} 在這裡換手" if z.get("first") and z.get("last") and z["first"] != z["last"] else ""
        parts.append(f"{f(z['lo'])}～{f(z['hi'])} 占 {z['share']:.0%}（平均成本 {f(z['vwap'])}{when}）{sd[z['side']]}")
    return f"套牢區（{f(H2)}→{f(ext)} 這段下跌的成交分布，60 分 K 的量攤到每個價位）：" + "；".join(parts)


def _squeeze(pts: list, n: int) -> list:
    """轉折太多時，把最小的一段（相鄰兩點）併掉，直到 ≤n 點；第一點、最後一點不動"""
    q = [dict(x) for x in pts]
    while len(q) > n and len(q) >= 4:
        k = min(range(1, len(q) - 2), key=lambda j: abs(q[j]["p"] - q[j + 1]["p"]))
        del q[k:k + 2]
    return q


def frame_tfs(fr: dict, price: float, piv: dict, ma5: dict) -> dict:
    """B126 用戶 11/24：切 15 分／30 分／60 分／週 K，結論卡（母圖、上方／下方／改判）也要跟著換。日 K＝原本那張。
    piv＝{tf: [{p, t}]}（含暫定轉折，舊→新；'1wk' 用週 K 級轉折）；ma5＝{tf: 該週期 5 均}。回 {tf: {map, tiles, pos}}"""
    f = _fmt
    price = float(price)
    T, L1, H2, ext, rb = fr["T"], fr["L1"], fr["H2"], fr["ext"], fr["rb"]
    w382, w5, w618 = (v for _, v in fr["w2"])
    pct = lambda v: round((v / price - 1) * 100, 2)                   # noqa: E731
    tile = lambda v, name, act: {"price": round(v, 2), "dist_pct": pct(v), "name": name, "act": act}   # noqa: E731
    out = {}

    def path_of(pv, start_p, n, lab, fb=False):
        k = max((j for j, q in enumerate(pv) if abs(q["p"] - start_p) <= 0.0005 * start_p), default=None)
        if k is None and fb and pv:                                   # 分 K 窗口比起點短（60 分只存約 3 週）→ 起點接在最前面
            j0 = next((j for j, q in enumerate(pv) if q["t"] != pv[0]["t"]), 0) if pv[0]["t"] == "H" else 0
            pv = [{"p": start_p, "t": "H"}] + pv[j0:]
            k = 0
        if k is None:
            return None
        pts = _squeeze([{"p": q["p"], "label": lab.get(round(q["p"]), "")} for q in pv[k:]], n)
        if abs(pts[-1]["p"] - price) > 0.0005 * price:
            pts.append({"p": price, "label": "現在"})
        pts[-1]["now"] = True
        pts[-1]["label"] = "現在"
        return pts

    # 週 K：月線格局（她 11/22 的 01 張）
    pw = piv.get("1wk") or []
    mo, band, eb, ck = fr.get("mo") or {}, fr.get("band"), fr.get("ext_band"), fr.get("clock") or {}
    full = fr.get("full")
    if pw and full:
        lab = {round(full): "全波段起點", round(T): "大頂？", round(ext): "現在這段低點"}
        pts = path_of(pw, full, 10, lab)
        if pts:
            lines = []
            if band:
                lines += [{"p": band[0], "label": f"尋底帶 {f(band[0])}～{f(band[1])}", "kind": "down"}]
            if eb:
                lines.append({"p": eb[1], "label": f"極限 {f(eb[1])}", "kind": "down2"})
            if ck.get("m20"):
                lines.append({"p": ck["m20"], "label": f"月 20T {f(ck['m20'])}", "kind": "down"})
            lines.append({"p": L1, "label": f"日線第一道牆 {f(L1)}", "kind": "up"})
            a, b = mo.get("a"), mo.get("b")
            vers = []
            if a and b:
                vers = [{"title": f"從 {f(a)} 起算｜六年大頂", "tag": "延伸第五浪見頂，50,265 起走大 A 浪".replace("50,265", f(T)), "now": False,
                         "pts": [{"p": a, "label": f(a)}, {"p": T, "label": f(T)}, {"p": ext, "label": f(ext)},
                                 {"p": (eb[1] if eb else ext) - 0.04 * (T - a), "label": "再破底"}],
                         "notes": [f"{f(eb[1]) if eb else '極限'} 都灌破", f"日線反彈壓在 {f(L1)} 下又殺新低"]},
                        {"title": f"從 {f(b)} 起算｜大四浪洗盤", "tag": "大三浪見頂後的暴力洗盤", "now": False,
                         "pts": [{"p": b, "label": f(b)}, {"p": T, "label": f(T)}, {"p": ext, "label": f(ext)}, {"p": T + 0.05 * (T - b), "label": "第五大浪"}],
                         "notes": [f"月 K 在 {f(band[0])}～{f(band[1])} 止跌、留長下影" if band else "月 K 止跌、留長下影",
                                   "守住月 20T" + (f"（約 {f(ck['m20'])}）" if ck.get("m20") else "")]}]
            out["1wk"] = {"map": {"title": f"{f(T)} 是六年大頂，還是大四浪洗盤？", "tag": "T3 MONTHLY MOTHER MAP",
                                  "sub": f"月線格局；週 K 轉折從 {f(full)} 起" + (f"；這個月最低 {f(ck['month']['low'])}、下影線 {f(ck['month']['shadow'])} 點" if ck.get("month") else ""),
                                  "path": pts, "lines": lines, "versions": vers,
                                  "common": f"共同事實｜{f(T)} 起修正，最低 {f(ext)}",
                                  "fork": f"真正分歧｜{f(eb[1]) if eb else '底線'} 守不守、月 K 能不能留長下影",
                                  "when": [x.replace("時間：", "⏱ ", 1) for x in _clock_lines(fr) if x.startswith("時間")]},
                          "tiles": {"up": tile(H2, "前高", "站穩＝月線大四浪完成"),
                                    "down": tile(band[0], "尋底帶上緣", "月 K 要在這之上止跌") if band and band[0] < price else tile(ext, "低點", "跌破＝還在找底"),
                                    "stop": tile(eb[1], "大四浪極限", "灌破＝六年大頂") if eb else None}}

    # 60 分：33,719 起的反彈怎麼走（44,911 下來到現在）
    p60 = piv.get("60m") or []
    pts = path_of(p60, H2, 9, {round(H2): "第一個反彈高", round(ext): "低點"}, fb=True)
    if pts:
        r382, r5 = rb - 0.382 * (rb - ext), rb - 0.5 * (rb - ext)
        sup = [z for z in fr.get("supply") or [] if z["side"] in ("at", "up")]
        lines = [{"p": w5, "label": f"第二道牆 0.5 {f(w5)}", "kind": "up2"}, {"p": w382, "label": f"第二道牆 0.382 {f(w382)}", "kind": "up"},
                 {"p": r382, "label": f"反彈 0.382 {f(r382)}", "kind": "down"}, {"p": L1, "label": f"第一道牆 {f(L1)}", "kind": "down2"}]
        m5 = ma5.get("60m")
        ups = [(v, n) for v, n in ((w382, "第二道牆 0.382"), (w5, "第二道牆 0.5"), (w618, "第二道牆 0.618"), (H2, "前高")) if v > price]
        out["60m"] = {"map": {"title": f"{f(ext)} 起的反彈｜60 分怎麼走", "tag": "T3 60M MOTHER MAP",
                              "sub": f"{f(ext)}→{f(rb)}（+{f(rb - ext)} 點）；壓回第二隻腳看反彈的 0.382～0.5＝{f(r382)}～{f(r5)}"
                                     + (f"；60 分 5 均 {f(m5)}" if m5 else ""),
                              "path": pts, "lines": lines,
                              "versions": [{"title": "反彈續攻", "tag": "壓回守住、再攻第二道牆", "now": price >= r382,
                                            "pts": [{"p": ext, "label": ""}, {"p": rb, "label": ""}, {"p": r382, "label": "守住"}, {"p": w5, "label": "再攻"}],
                                            "notes": [f"壓回不破 {f(r382)}～{f(r5)}", f"再攻 {f(w5)}～{f(w618)}" + (f"（先過套牢區 {f(sup[0]['lo'])}～{f(sup[0]['hi'])}）" if sup else "")]},
                                           {"title": "反彈失敗", "tag": "跌回第一道牆下", "now": price < r382,
                                            "pts": [{"p": ext, "label": ""}, {"p": rb, "label": ""}, {"p": L1, "label": ""}, {"p": ext - 0.05 * (rb - ext), "label": "破底"}],
                                            "notes": [f"60 分收在 {f(L1)} 下面", "回到五波下跌（第 4 浪）的看法"]}],
                              "common": f"共同事實｜{f(ext)} 起反彈到 {f(rb)}",
                              "fork": f"真正分歧｜壓回守 {f(r382)}～{f(r5)}（續攻）vs 跌回 {f(L1)} 下（失敗）",
                              "when": [("🧱 " + x.split("：", 1)[1]) for x in [_supply_line(fr.get("supply"), H2, ext, price)] if x]},
                      "tiles": {"up": tile(ups[0][0], ups[0][1], "量縮折返＝大 B 波") if ups else None,
                                "down": tile(r382, "反彈 0.382", "壓回第二隻腳的上緣") if r382 < price else tile(L1, "第一道牆", "收在下面＝反彈失敗"),
                                "stop": tile(L1, "第一道牆", "60 分收在下面＝反彈失敗")}}

    # 30 分／15 分：短線鎖利（她 11/23：15 分 K 跌破 5T 或 0.236 39,370）
    d236 = fr.get("d236")
    for tf, nm in (("30m", "30 分"), ("15m", "15 分")):
        pv = piv.get(tf) or []
        if not pv:
            continue
        pts = path_of(pv, ext, 9, {round(ext): "低點"} | ({round(d236["lo"]): "起漲點"} if d236 else {}))
        if not pts:
            continue
        m5 = ma5.get(tf)
        lines, dn = [], []
        if d236:
            lo, hi = d236["lo"], d236["hi"]
            l382 = hi - 0.382 * (hi - lo)
            lines = [{"p": d236["v"], "label": f"0.236 {f(d236['v'])}", "kind": "down"}, {"p": l382, "label": f"0.382 {f(l382)}", "kind": "down2"},
                     {"p": lo, "label": f"起漲點 {f(lo)}", "kind": "down2"}]
            dn = [(d236["v"], "短線 0.236"), (l382, "0.382"), (lo, "起漲點")]
        if m5:
            lines.insert(0, {"p": m5, "label": f"{nm} 5 均 {f(m5)}", "kind": "down"})
        ups = sorted([(v, n_) for v, n_ in ((rb, "反彈高點"), (w382, "第二道牆 0.382"), (w5, "第二道牆 0.5")) if v > price + 1])
        sup = [z for z in fr.get("supply") or [] if z["side"] == "at"]
        below = [x for x in ([(m5, f"{nm} 5 均")] if m5 else []) + dn if x[0] < price]
        below.sort(key=lambda x: -x[0])
        lk = (f"{nm} K 收破 5 均（{f(m5)}）" if m5 else "") + ("、或" if m5 and d236 else "") + (f"跌破 0.236 {f(d236['v'])}" if d236 else "")
        out[tf] = {"map": {"title": (f"{f(d236['lo'])}→{f(d236['hi'])}｜短線鎖利線" if d236 else f"{f(ext)} 起｜{nm}短線"),
                           "tag": f"T3 {tf.upper()} MOTHER MAP",
                           "sub": f"{nm} K 轉折從 {f(ext)} 起；她 11/23：短線鎖利用 15 分 K 跌破 5T 或 0.236",
                           "path": pts, "lines": lines,
                           "versions": [{"title": "守住鎖利線", "tag": "短線多單續抱", "now": bool(below) and below[0][0] < price and (not d236 or price >= d236["v"]),
                                         "pts": [{"p": d236["lo"] if d236 else ext, "label": ""}, {"p": rb, "label": ""},
                                                 {"p": d236["v"] if d236 else rb, "label": "守住"}, {"p": rb + 0.2 * (rb - ext), "label": "續攻"}],
                                         "notes": [f"守住 {lk}" if lk else "守住短線支撐", f"上面先看 {f(ups[0][0])}" if ups else "創高續攻"]},
                                        {"title": "跌破鎖利線", "tag": "先下車、等第二隻腳", "now": bool(d236) and price < d236["v"],
                                         "pts": [{"p": d236["lo"] if d236 else ext, "label": ""}, {"p": rb, "label": ""},
                                                 {"p": (hi - 0.5 * (hi - lo)) if d236 else ext, "label": "壓回"}],
                                         "notes": [lk + "＝先鎖利" if lk else "先鎖利", "壓回 0.382～0.5 止穩再接"]}],
                           "common": f"共同事實｜{f(ext)} 起反彈到 {f(rb)}",
                           "fork": f"真正分歧｜守住鎖利線 vs 跌破先下車",
                           "when": ([f"🧱 現價在套牢區 {f(sup[0]['lo'])}～{f(sup[0]['hi'])} 裡（平均成本 {f(sup[0]['vwap'])}），開高容易湧出解套賣壓"] if sup else [])},
                   "tiles": {"up": tile(ups[0][0], ups[0][1], "過不去＝短線先休息") if ups else None,
                             "down": tile(below[0][0], below[0][1], "跌破先鎖利") if below else None,
                             "stop": tile(L1, "第一道牆", "收在下面＝反彈失敗")}}
    return out


def _frame_card(t: dict, fr: dict, price: float, bars15: Optional[list], atr15: Optional[float], atr60: Optional[float]) -> dict:
    """B123：big_frame 的結論卡（位階、怎麼做、上方／下方／改判、母圖）"""
    f = _fmt
    T, L1, H2, ext, rb, stage, d236 = fr["T"], fr["L1"], fr["H2"], fr["ext"], fr["rb"], fr["stage"], fr["d236"]
    w382, w5, w618 = (v for _, v in fr["w2"])
    pct = lambda v: round((v / price - 1) * 100, 2)                   # noqa: E731
    tile = lambda v, name, act: {"price": round(v, 2), "dist_pct": pct(v), "name": name, "act": act}   # noqa: E731
    ma15 = None
    cl = [float(b["close"]) for b in (bars15 or []) if b.get("close") is not None]
    if len(cl) >= 5:
        ma15 = round(sum(cl[-5:]) / 5, 2)
    pos = [x for x in fr["lines"] if not x.startswith(("尋底帶", "兩道牆"))]
    walls = [(w382, "第二道牆 0.382"), (w5, "第二道牆 0.5"), (w618, "第二道牆 0.618"), (H2, "前高")]
    up_v = next(((v, n) for v, n in walls if v > price), None)
    band, eb = fr["band"], fr["ext_band"]
    longs = [(v, n) for v, n in ([(L1, "第一道牆")] + ([(d236["v"], "短線 0.236")] if d236 else [])) if v < price]
    shorts = [(v, n) for v, n in walls if v > price]
    if stage == "w0":
        shape = "日線第三筆跌完後的反彈：五波下跌的第 4 浪，還是三波末端已經跌完，要看能不能帶量站穩第一道牆"
        plays = [{"k": "wait", "tag": "不追", "t": f"反彈 5～10 天壓在 {f(L1)} 下面＝第 4 浪，之後再殺第 5 浪；追多沒有保障"},
                 {"k": "long", "tag": "做多等確認",
                  "t": f"帶量實體站穩 {f(L1)} 才算止跌確認、展開多週反彈" + (f"；或尋底帶 {f(band[0])}～{f(band[1])} 止跌拉下影線" if band else "")}]
        tiles = {"up": tile(L1, "第一道牆", "帶量實體站穩＝止跌確認"),
                 "down": tile(band[0], "尋底帶上緣", "止跌拉下影線") if band and band[0] < price else tile(ext, "低點", "跌破＝還在跌"),
                 "stop": tile(ext, f"{f(ext)} 低點", "跌破＝第 3 浪還沒完") if ext < price else None}
        flip = f"改判：帶量實體站穩 {f(L1)}＝三波末端已經跌完、五波看法淘汰；跌破 {f(ext)}＝第 3 浪還在走" + (f"，看 {f(band[1])}、{f(eb[0])}～{f(eb[1])}" if band else "")
    else:
        shape = "日線三筆跌完後的多週反彈：先當大 B 波；第二道牆量縮折返＝大 B 波，連過兩道並站穩前高＝大四浪完成"
        lk = []
        if ma15:
            lk.append(f"15 分 K 跌破 5 均（現在 {f(ma15)}）")
        if d236:
            lk.append(f"跌破 0.236 {f(d236['v'])}（{f(d236['lo'])}→{f(d236['hi'])}）")
        plays = [{"k": "long", "tag": "波段多單", "t": f"成本比現價低 3,000 點以上的波段多單照抱、做防守；防守線第一道牆 {f(L1)}（收盤跌回下面＝反彈失敗）"},
                 {"k": "long", "tag": "短線鎖利", "t": ("、或".join(lk) or f"跌回 {f(w382)} 下面") + "，先鎖利"},
                 {"k": "wait", "tag": "第二道牆",
                  "t": (f"可以去拼 {f(w5)}～{f(w618)}；" if stage in ("w1", "w2") else "")
                       + f"在 {f(w382)}～{f(w618)} 量縮折返＝大 B 波，彈完提防大 C 浪再破底；連過兩道並站穩 {f(H2)}＝月線大四浪完成"}]
        sup = [z for z in fr.get("supply") or [] if z["side"] in ("up", "at")]
        if sup:
            z = min(sup, key=lambda z: z["lo"])
            plays.insert(2, {"k": "wait", "tag": "套牢賣壓",
                             "t": f"{f(z['lo'])}～{f(z['hi'])}（{f(H2)} 下來這段 {z['share']:.0%} 的量在這裡成交、平均成本 {f(z['vwap'])}）"
                                  + ("：現價就在裡面，開高容易湧出解套賣壓，不追高" if z["side"] == "at" else "：反彈到這裡容易遇到解套賣壓")
                                  + (f"；再上面 {f(sup[1]['lo'])}～{f(sup[1]['hi'])}" if len(sup) > 1 and sup[1] is not z else "")})
        if stage == "top":
            plays[-1] = {"k": "long", "tag": "大四浪完成", "t": f"站穩 {f(H2)}＝月線大四浪完成、轉看第五大浪創高；跌回 {f(H2)} 下面＝假突破"}
        dn = (tile(d236["v"], "短線 0.236", "跌破先鎖利") if d236 and d236["v"] < price else
              tile(w382, "第二道牆 0.382", "跌回下面＝站不穩") if w382 < price else tile(L1, "第一道牆", "收盤跌回＝反彈失敗"))
        tiles = {"up": tile(up_v[0], up_v[1], "量縮折返＝大 B 波" if up_v[0] < H2 else "站穩＝大四浪完成") if up_v else None,
                 "down": dn, "stop": tile(L1, "第一道牆", "收盤跌回＝回到五波下跌")}
        flip = (f"改判：日線收盤跌回 {f(L1)} 下面＝站穩失敗，回到五波下跌（第 4 浪）的看法，之後看第 5 浪破底"
                + (f"、{f(eb[1])}" if eb else "") + f"；連過兩道牆並站穩 {f(H2)}＝月線大四浪完成")
    sig = None
    if bars15:
        cands = [x for x in (pierce_reclaim(bars15, longs, 1, atr15, atr60) if longs else None,
                             pierce_reclaim(bars15, shorts, -1, atr15, atr60) if shorts else None) if x]
        sig = min(cands, key=lambda x: x["ago"]) if cands else None
    try:
        mp = _mapframe(fr, price)
    except Exception:     # noqa: BLE001
        mp = None
    return {"pos": pos, "shape": shape, "plays": plays, "exit": EXIT, "flip": flip, "method": METHOD, "tiles": tiles, "signal": sig,
            "steps": None, "map": mp, "ma15": ma15,
            "watch": {"long": [(round(v, 2), n) for v, n in longs], "short": [(round(v, 2), n) for v, n in shorts]}}


def _mapframe(fr: dict, price: float) -> dict:
    """B123 母圖：T→L1→H2→ext→（反彈高）→現在，兩道牆畫虛線，三種發展並排（她 11/22 的 02～04 張）"""
    f = _fmt
    T, L1, H2, ext, rb, dev, d236 = fr["T"], fr["L1"], fr["H2"], fr["ext"], fr["rb"], fr["dev"], fr["d236"]
    w382, w5, w618 = (v for _, v in fr["w2"])
    eb = fr["ext_band"]
    path = [{"p": T, "label": "大頂？"}, {"p": L1, "label": "第 1 筆低點"}, {"p": H2, "label": "第一個反彈"}, {"p": ext, "label": "第 3 筆"}]
    if rb - price > 0.1 * (rb - ext):
        path.append({"p": rb, "label": "反彈高"})
    path.append({"p": price, "label": "現在", "now": True})
    lines = [{"p": w618, "label": f"第二道牆 0.618 {f(w618)}", "kind": "up2"}, {"p": w382, "label": f"第二道牆 0.382 {f(w382)}", "kind": "up"},
             {"p": L1, "label": f"第一道牆 {f(L1)}", "kind": "down2"}]
    if d236 and dev == 2 and d236["v"] < price:
        lines.insert(2, {"p": d236["v"], "label": f"短線鎖利 0.236 {f(d236['v'])}", "kind": "down"})
    bot = eb[1] if eb else ext - 0.25 * (T - ext)
    versions = [
        {"title": "第一類｜五波下跌", "tag": "第 3 浪主殺 → 第 4 浪 → 第 5 浪破底", "now": dev == 1,
         "pts": [{"p": ext, "label": f(ext)}, {"p": L1 - 0.3 * (L1 - ext), "label": "第 4 浪"}, {"p": bot, "label": f"第 5 浪 {f(bot)}" if eb else "第 5 浪"}],
         "notes": [f"弱彈 5～10 天、頂過不了 {f(L1)}" + (f"（現在第 {(fr.get('clock') or {}).get('reb_days')} 天）" if (fr.get("clock") or {}).get("reb_days") else ""), "再殺第 5 浪破底" + (f"，考驗 {f(bot)}" if eb else ""),
                   f"現價已站上 {f(L1)}：收盤守住就淘汰" if price >= L1 else ""]},
        {"title": "第二類｜過第一道、卡第二道", "tag": "六年大頂之後的大 B 波", "now": dev == 2 and price < w618,
         "pts": [{"p": ext, "label": f(ext)}, {"p": L1, "label": "站上"}, {"p": w5, "label": "量縮遇壓"}, {"p": ext - 0.06 * (T - ext), "label": "大 C 破底"}],
         "notes": [f"{f(w382)}～{f(w618)} 量縮鈍化", "前面三筆＝A-a／A-b／A-c", "彈完提防大 C 浪再破底"]},
        {"title": "第三類｜兩道牆都站穩", "tag": "月線大四浪完成", "now": dev == 3 or price >= w618,
         "pts": [{"p": ext, "label": f(ext)}, {"p": L1, "label": ""}, {"p": w618, "label": "站穩"}, {"p": H2, "label": f(H2)},
                 {"p": H2 + 0.12 * (T - ext), "label": "第五大浪"}],
         "notes": [f"強勢站穩 {f(w5)}～{f(w618)}", f"攻回 {f(H2)}", "Y-a／Y-b／Y-c 完成，轉看創高"]},
    ]
    for v in versions:
        v["notes"] = [x for x in v["notes"] if x]
    return {"title": f"{f(T)}→{f(ext)}｜三筆跌完，反彈要闖兩道牆",
            "sub": f"第一道牆 {f(L1)}；第二道牆 {f(w382)}～{f(w618)}（{f(T)}→{f(ext)} 的 0.382～0.618）；前高 {f(H2)}",
            "path": path, "lines": lines, "versions": versions,
            "common": f"共同事實｜{f(T)}→{f(ext)} 跌 {f(T - ext)} 點，反彈最高 {f(rb)}",
            "fork": f"真正分歧｜第二道牆 {f(w382)}～{f(w618)} 量縮折返（大 B 波）vs 站穩 {f(H2)}（大四浪完成）",
            "when": [x.replace("時間：", "⏱ ", 1).replace("量：", "🔊 ", 1) for x in _clock_lines(fr)]
                    + [("🧱 " + x.split("：", 1)[1]) for x in [_supply_line(fr.get("supply"), H2, ext, price)] if x]}


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


def _map52(t: dict, sb: dict, price: float) -> Optional[dict]:
    """B122 用戶 11/18：結論卡改成她的圖卡樣子——一條折線把每個轉折標價位（母圖）＋幾種發展並排的小圖＋最下面「共同事實｜真正分歧」，文字說明另外放。
    回 {title, sub, path:[{p, label, now?}], lines:[{p, label, kind}], versions:[{title, tag, now, pts:[{p, label}], notes:[...]}], common, fork}"""
    p0, top, a_low, b_hi, stage = sb["p0"], sb["top"], sb["a_low"], sb.get("b_hi"), sb["stage"]
    cg, fk, z7, z80 = sb.get("cleg") or {}, sb.get("fork") or {}, sb.get("z786"), sb.get("z80")
    path = [{"p": p0, "label": "5-1 起點"}, {"p": top, "label": "5-1 高點"}]
    if stage == "3":
        path += [{"p": sb.get("end52") or sb["pb"], "label": "5-2 低點"}, {"p": price, "label": "現在", "now": True}]
        return {"title": f"{_fmt(p0)} 起漲｜日線第 5 大波", "sub": f"5-1 {_fmt(p0)}→{_fmt(top)}；5-2 走完、5-3 啟動", "path": path,
                "lines": [{"p": top, "label": "5-1 高點（回測要踩穩）", "kind": "key"}], "versions": [],
                "common": f"共同事實｜站上 5-1 高點 {_fmt(top)}", "fork": f"真正分歧｜回測踩穩（5-3）vs 跌回 {_fmt(top)} 下面（假突破）"}
    path.append({"p": a_low, "label": "5-2-A"})
    if b_hi is not None:
        path.append({"p": b_hi, "label": "5-2-B"})
    legs = cg.get("legs") or fk.get("legs") or []
    if cg.get("phase") == "ext":                                      # C-5 先到、反彈站上 C-4 又跌破：三個點都畫出來
        for x in legs[:4]:
            path.append({"p": x["p"], "label": f"C-{x['k']}"})
        path += [{"p": cg["c5a"], "label": "C-5?"}, {"p": cg["reb"], "label": "反彈"}, {"p": legs[4]["p"], "label": "C-5 延伸"}]
    else:
        for x in legs:
            path.append({"p": x["p"], "label": f"C-{x['k']}"})
    if abs(path[-1]["p"] - price) > 1:
        path.append({"p": price, "label": "現在", "now": True})
    else:
        path[-1]["now"] = True
    lines, versions, common, fork = [], [], None, None
    depth = sb.get("depth")
    title = f"{_fmt(p0)}→{_fmt(top)}｜日線 5-1 之後的 5-2 修正"
    sub = f"5-1 漲 {_fmt(top - p0)} 點；5-2 " + ("A-B-C 的 C 段" if stage == "C" else f"在 {stage} 段") + (f"，已回撤 {depth:.1%}" if depth else "")
    if stage == "C" and sb.get("dev") and depth is not None and depth >= 0.618 and z80 is not None:
        c5a, reb, cl = cg.get("c5a") or cg.get("legs", [{}])[-1].get("p"), cg.get("reb"), sb["pb"]
        ma5 = t.get("ma5")
        strong = sorted(x for x in (ma5, reb) if x)
        lines = [{"p": z80, "label": f"0.8 極限防線 {_fmt(z80)}", "kind": "down"}, {"p": p0, "label": f"多頭總底線 {_fmt(p0)}", "kind": "down2"}]
        if c5a and c5a > price:
            lines.append({"p": c5a, "label": f"站回＝買點 {_fmt(c5a)}", "kind": "up"})
        if strong:
            lines.append({"p": strong[-1], "label": "轉強 " + "～".join(_fmt(x) for x in strong), "kind": "up2"})
        up1 = strong[0] if strong else (reb or top)
        versions = [
            {"title": "第一種｜守住 0.8", "tag": "5-2 極限洗盤 → 直接 5-3", "now": sb["dev"] == 1,
             "pts": [{"p": cl, "label": _fmt(cl)}] + ([{"p": c5a, "label": f"站回 {_fmt(c5a)}"}] if c5a else [])
                    + [{"p": (c5a or cl) - 0.25 * ((c5a or cl) - cl), "label": ""}, {"p": up1, "label": "轉強"}, {"p": top, "label": "5-3"}],
             "notes": [f"日線收盤守住 {_fmt(z80)}", f"60 分收復 {_fmt(c5a)}" if c5a else "", "帶量站穩 " + "～".join(_fmt(x) for x in strong) if strong else ""]},
            {"title": "第二種｜跌破 0.8", "tag": "日線第二隻大腳（W 底）", "now": sb["dev"] == 2,
             "pts": [{"p": cl, "label": _fmt(cl)}, {"p": cl + 0.35 * (top - cl) * 0.5, "label": ""}, {"p": p0, "label": f"回測 {_fmt(p0)}"},
                     {"p": cl + 0.2 * (top - cl), "label": "重算 5-1"}],
             "notes": [f"跌破 {_fmt(z80)}，修正時間拉長", f"回測 {_fmt(p0)} 不破或假跌破收回＝雙底", "第二隻腳低點才重算 5-1"]},
            {"title": f"第三種｜{_fmt(p0)} 失守", "tag": "4-C 真 C-5 主跌段", "now": sb["dev"] == 3,
             "pts": [{"p": cl, "label": _fmt(cl)}, {"p": cl - 0.25 * (cl - p0), "label": ""}, {"p": cl + 0.08 * (top - cl), "label": "反抽無力"},
                     {"p": p0 - 0.12 * (top - p0), "label": "破底"}],
             "notes": [f"帶量長黑收盤跌破 {_fmt(p0)}", f"反抽收不回 {_fmt(c5a)}、5 均" if c5a else "反抽收不回 5 均", "風險邊界，沒觸發前別自己嚇自己"]},
        ]
        for v in versions:
            v["notes"] = [x for x in v["notes"] if x]
        common = f"共同事實｜{_fmt(top)} 起 5-2 回檔，最低 {_fmt(cl)}（回撤 {depth:.1%}）"
        fork = f"真正分歧｜守住 {_fmt(z80)}（洗盤）vs 跌破（第二隻腳）vs {_fmt(p0)} 失守（主跌）"
    elif fk:                                                          # B110 她 11/15：主追蹤 vs 強替代
        g2 = fk.get("g2") or b_hi
        lines = [{"p": g["lo"], "label": f"往上第 {g['k']} 關 {_fmt(g['lo'])}", "kind": "up"} for g in fk["up"][:2]] + \
                [{"p": fk["c_lo"], "label": f"C-3 低點 {_fmt(fk['c_lo'])}", "kind": "down"}]
        deep = fk["deep"]
        versions = [
            {"title": "主追蹤｜重疊型 5-2-C", "tag": "還欠 C-5 破底", "now": fk["where"] in ("mid", "ctrl", "above", "fall"),
             "pts": [{"p": fk["c_lo"], "label": _fmt(fk["c_lo"])}, {"p": fk["rb_hi"], "label": "C-4"}, {"p": deep["hi"], "label": "C-5"}],
             "notes": [f"上不過 {_fmt(g2)}", f"跌破 {_fmt(fk['c_lo'])} 往 {_fmt(a_low)}、{_fmt(deep['lo'])}～{_fmt(deep['hi'])}"]},
            {"title": "強替代｜較大的 5-2-B", "tag": "B-b 落底、B-c 往上", "now": fk["where"] == "bc",
             "pts": [{"p": fk["c_lo"], "label": _fmt(fk["c_lo"])}, {"p": g2, "label": "站穩"}, {"p": b_hi, "label": "B-c"}, {"p": top, "label": "5-3?"}],
             "notes": [f"60 分實體站穩 {_fmt(g2)}", f"突破 {_fmt(b_hi)}／{_fmt(top)} 回測踩穩＝5-3"]},
        ]
        common = f"共同事實｜5-2-A {_fmt(top)}→{_fmt(a_low)}、B 彈到 {_fmt(b_hi)}"
        fork = f"真正分歧｜重疊型 C 還欠一腳 vs 較大 B 補時間"
    elif stage == "C" and cg.get("phase") == "done":
        lines = [{"p": g["lo"], "label": f"5-3 第 {g['k']} 關 {_fmt(g['lo'])}", "kind": "up"} for g in cg.get("gates53") or []] + \
                [{"p": cg["c5a"], "label": f"C-5 低點 {_fmt(cg['c5a'])}", "kind": "down"}]
        common = f"共同事實｜C 段在 {_fmt(cg['c5a'])} 走完"
        fork = "真正分歧｜三關都過（5-3）vs 跌破 C-5 低點（C-5 還沒走完）"
    else:
        zs = sb.get("z52") or []
        lines = [{"p": z["v"], "label": f"5-2 大買點 {z['r']:g} {_fmt(z['v'])}", "kind": "down"} for z in zs]
    return {"title": title, "sub": sub, "path": path, "lines": lines, "versions": versions, "common": common, "fork": fork}


def plan_card(t: dict, price: float, bars15: Optional[list] = None, atr15: Optional[float] = None,
              atr60: Optional[float] = None) -> Optional[dict]:
    """B108 結論卡（用戶：簡單說現在的位階、在哪個波形裡，然後怎麼試單、怎麼進出場）。
    t＝structure() 的結果。回 {pos: [兩句位階], shape: 波形, plays: [{k, tag, t}], exit, flip, method, tiles, signal, watch}"""
    if not t:
        return None
    if t.get("frame"):                                                # B123 她 11/22～11/23：三筆跌完、反彈闖兩道牆
        return _frame_card(t, t["frame"], float(price), bars15, atr15, atr60)
    lb, u = t["labels"], -t["dir"]
    pu = ((t.get("ext3") or {}).get("paths") or {}).get("push") or {}
    sb = pu.get("sub") or {}
    price = float(price)
    pct = lambda v: round((v / price - 1) * 100, 2)                   # noqa: E731
    tile = lambda v, name, act: {"price": round(v, 2), "dist_pct": pct(v), "name": name, "act": act}   # noqa: E731
    rng = lambda a, b: _fmt(a) + (f"～{_fmt(b)}" if b != a else "")   # noqa: E731
    how_long = "跌破又收回（15 分 K 收回線上）才進，停損放最低點下面"
    longs, shorts, tiles, shape, flip, steps = [], [], None, None, None, None
    plays = []
    if t["tag"] == "52" and sb.get("done") and u > 0:
        top, p0, a_low, b_hi, c_low, stage, zs = sb["top"], sb["p0"], sb["a_low"], sb.get("b_hi"), sb.get("c_low"), sb["stage"], sb["z52"]
        low52 = sb.get("pb")                                          # 5-2 到現在的最低點
        zhit = lambda z: ("" if not z.get("hit") else "（已到）" if low52 is None or (low52 - z["v"]) * u <= 0   # noqa: E731
                          else f"（碰到上緣，{z['r']:g} 的 {_fmt(z['v'])} 還沒到）")       # B113 她 11/16：「還沒到 0.618 差一點」
        ztxt = "、".join(rng(z["lo"], z["hi"]) + zhit(z) for z in zs)
        nz = next((z for z in zs if not z.get("hit")), None)
        longs = [(z["v"], f"大買點 {z['r']:g}") for z in zs] + [(z["near"], f"大買點 {z['r']:g} 旁邊的前低") for z in zs if z["near"] is not None]
        pos = [f"{lb['big']}：第 5 大波裡的 5-2 回檔——5-1（{_fmt(p0)}→{_fmt(top)}，漲 {_fmt(top - p0)} 點）已經走完"]
        buy = {"k": "long", "tag": "做多等大買點",
               "t": f"{ztxt}——她說這三區才是 5-2 的最大買點（0050、個股也在這裡分批）；{how_long}"}
        down = tile(nz["hi"], "5-2 大買點", "跌破又收回才做多") if nz else tile(p0, "5-1 起點", "跌破＝看法作廢")
        fk = sb.get("fork")
        if stage == "3":                                              # B110：又站上 5-1 高點＝5-2 走完、5-3 啟動
            hi53, t53, e52 = sb.get("hi53") or price, sb.get("t53") or [], sb.get("end52") or sb["pb"]
            pos = [f"{lb['big']}：第 5 大波的 5-3 啟動——5-1（{_fmt(p0)}→{_fmt(top)}）走完、5-2 在 {_fmt(e52)} 結束（最低只到 {_fmt(sb['pb'])}）",
                   f"{lb['small']}：站上 5-1 高點 {_fmt(top)}（最高 {_fmt(hi53)}）；她 11/15：要帶量突破、第一次回測踩穩才算數"]
            shape = "五段推動的第 3 段（5-3）剛啟動：通常是最長的一段"
            longs = [(top, "5-1 高點（回測）")] + ([(b_hi, "5-2-B 高點（回測）")] if b_hi is not None and b_hi != top else [])
            plays = [{"k": "wait", "tag": "不追高", "t": f"剛突破 {_fmt(top)}，追在突破那一根容易被回測洗掉"},
                     {"k": "long", "tag": "做多等回測", "t": f"第一次回測 " + (f"{_fmt(b_hi)}～" if b_hi is not None and b_hi != top else "") + f"{_fmt(top)}"
                      + f"：{how_long}" + ("；量度（僅參考）" + "、".join(f"{nm_.split('＝')[-1]} {_fmt(v)}" for v, nm_ in t53) if t53 else "")}]
            tiles = {"up": tile(t53[0][0], "5-3 量度", "5-1 等幅（僅參考）") if t53 else None,
                     "down": tile(top, "5-1 高點", "回測踩穩才做多"), "stop": tile(e52, "5-2 低點", "跌破＝5-2 還沒完")}
            flip = f"改判：跌回 {_fmt(top)} 下面站不回去＝假突破、5-2 還沒走完；跌破 {_fmt(e52)}＝5-2 往大買點 {ztxt}"
        elif stage == "B" and fk:                                     # B110 她 11/15：C 段第幾腳／較大 B 的 b，還沒分出來
            c_lo, g2, n, rb_hi, deep, where = fk["c_lo"], fk["g2"], fk["n"], fk["rb_hi"], fk["deep"], fk["where"]
            ups, dns = fk["up"], fk["down"]
            steps = {"up": ups, "down": dns, "deep": {**deep, "t": "最後一腳的落底觀察區：到了等止穩才出手"}, "evo": fk["evo"],
                     "now": fk["now"], "src": "她 11/15"}
            g2v = g2 if g2 is not None else b_hi
            g2n = next((g["name"] for g in ups if g["kind"] == "g2"), "5-2-B 高點")
            g3 = next(g for g in ups if g["kind"] == "g3")
            deep_t = rng(deep["lo"], deep["hi"])
            legs_t = "、".join(f"C-{x['k']} {_fmt(x['p'])}" for x in fk["legs"])
            buy_deep = {"k": "long", "tag": "做多等落底",
                        "t": f"{_fmt(a_low)}、{deep_t}（最後一腳的落底觀察區，也是 5-2 第一個大買點；全部 {ztxt}）：到了等止穩、{how_long}"}
            longs = ([(a_low, "5-2-A 低點"), (deep["hi"], "母級共振區")] + [(z["v"], f"大買點 {z['r']:g}") for z in zs]
                     + [(z["near"], f"大買點 {z['r']:g} 旁邊的前低") for z in zs if z["near"] is not None])
            near = 0.5 * atr60 if atr60 else 0.004 * price
            if where == "fall":                                       # 這一腳還在跌
                prev = fk.get("prev_lo")
                pos.append(f"{lb['small']}：5-2 的 A（→{_fmt(a_low)}）、B（→{_fmt(b_hi)}）走完，現在是 C 段的第 {n} 腳下跌（到 {_fmt(c_lo)}）"
                           + (f"——已跌破前一個低點 {_fmt(prev)}" if prev is not None else "") + ("，C 段最後一腳" if n >= 5 else "，後面還有反彈和再一腳"))
                shape = ("重疊型 C（4 碰到 1 的終結型）" if fk["overlap"] else "5-2-C") + f"的第 {n} 腳：{legs_t}" + ("；走完才是 5-3 起漲" if n >= 5 else "")
                plays = [{"k": "wait", "tag": "不追空", "t": f"這一腳的目標就是 {_fmt(a_low)}、{deep_t}，追空沒有肉；手上有空單就照目標分批回補"}, buy_deep]
                if prev is not None:
                    shorts = [(prev, "剛跌破的低點")]
                up_g = ups[0]
                tiles = {"up": tile(up_g["lo"], up_g["name"].split("（")[0], "站回＝假跌破" if up_g["kind"] == "prev" else "站穩＝排除破底"),
                         "down": tile(a_low, "5-2-A 低點", "再下面是母級共振區") if price > a_low else down,
                         "stop": tile(g2v, g2n, "站上＝這一腳破底失敗") if up_g["kind"] == "prev" else None}
                flip = (f"改判：站回 {_fmt(prev)}＝假跌破、這一腳可能已經走完；" if prev is not None else "改判：") + f"站穩 {_fmt(g2v)}＝排除再破底；跌破 {_fmt(a_low)}＝5-2 往更深的大買點"
            elif where == "bc":                                       # 站上 C-2 高點：強替代取得優勢
                pos.append(f"{lb['small']}：站上 {_fmt(g2v)}——「還欠一腳破底」先排除；{_fmt(b_hi)}→{_fmt(c_lo)} 是 B 波裡面的回檔，現在往 {_fmt(b_hi)} 走 B 波最後一段"
                           f"（要 60 分 K 實體站穩 {_fmt(g2v)} 才算數）")
                shape = f"較大的 5-2-B：B-a {_fmt(a_low)}→{_fmt(b_hi)}、B-b →{_fmt(c_lo)}、B-c 往上（到 {_fmt(rb_hi)}）；補時間，還不是 5-3"
                shorts = [(v, nm_) for v, nm_ in ((b_hi, "5-2-B 高點"), (top, "5-1 高點")) if v >= price - near]
                longs = [(g2v, f"{g2n}（回測）")] + longs
                plays = [{"k": "wait", "tag": "不追多", "t": f"B-c 只是 B 波的最後一段，上面 {rng(g3['lo'], g3['hi'])} 遇壓折返＝高檔折返補時間，之後還有 C 段"},
                         {"k": "short", "tag": "小量試空", "t": f"{rng(g3['lo'], g3['hi'])}：刺過又收回線下才空，停損放那根最高點上面；目標先看 {_fmt(g2v)}"},
                         {"k": "long", "tag": "做多等確認", "t": f"帶量突破 {_fmt(top)}、第一次回測踩穩＝5-2 已在 {_fmt(c_lo)} 走完、啟動 5-3，那時才順著做多"}]
                tiles = {"up": tile(g3["lo"], "5-2-B 高點", "遇壓折返＝補時間"), "down": tile(g2v, g2n, "跌回下面＝還是 C 段反彈"),
                         "stop": tile(top, "5-1 高點", "突破踩穩＝5-3")}
                flip = f"改判：跌回 {_fmt(g2v)} 下面站不回去＝還是 C 段的反彈、保留一腳破底；突破並守穩 {_fmt(top)}＝5-3；跌破 {_fmt(c_lo)}＝C 段最後一腳"
            else:                                                     # 反彈中：mid／ctrl／above
                zc = ups[0]
                lo_t = "、後面還欠一腳破底" if n <= 4 else "、五腳走齊"
                pos.append(f"{lb['small']}：5-2 的 A（→{_fmt(a_low)}）、B（→{_fmt(b_hi)}）走完，現在多半是 C 段的"
                           + (f"第 {n} 腳反彈（{_fmt(c_lo)}→{_fmt(rb_hi)}）" if n % 2 == 0 else f"第 {n} 腳跌完（{_fmt(c_lo)}）後的反彈（到 {_fmt(rb_hi)}）")
                           + lo_t + f"；也可能 B 還沒走完（{_fmt(b_hi)}→{_fmt(c_lo)} 只是 B 裡面的回檔）")
                shape = (("重疊型 C（4 碰到 1 的終結型）" if fk["overlap"] else "5-2-C") + "：" + legs_t
                         + ("、C-5 還沒走" if n == 4 else "") + "；強替代＝較大 B 波的 b 落底")
                res = [(v, nm_) for v, nm_ in [(zc["lo"], "控制區"), (zc["hi"], "控制區")] + ([(g2, g2n)] if g2 is not None else [])
                       + [(b_hi, "5-2-B 高點"), (top, "5-1 高點")] if v >= price - near]
                seen = set()
                for v, nm_ in res:
                    if round(v, 2) not in seen:
                        seen.add(round(v, 2))
                        shorts.append((v, nm_))
                longs = [(c_lo, next(g["name"] for g in dns if g["kind"] == "lo"))] + longs   # 反彈的 0.382／0.618 會跟著高點移動，不當訊號線
                below = [g for g in dns if g["hi"] < price - (atr15 or 0)]
                t1 = "、".join(_fmt(g["lo"]) for g in below[:2]) or _fmt(c_lo)
                plays = [{"k": "wait", "tag": "中間不出手",
                          "t": f"{_fmt(c_lo)}～{_fmt(g2v)} 中間兩種看法還沒分出來；上不過 {_fmt(g2v)}、下守 {_fmt(c_lo)} 就只是壓縮（她：不急著加浪名）"},
                         {"k": "short", "tag": "小量試空",
                          "t": f"控制區 {rng(zc['lo'], zc['hi'])}、{_fmt(g2v)}：刺過其中一條、15 分 K 又收回線下才空，停損放那根最高點上面；"
                               f"目標 {t1}" + (f"，再看 {_fmt(c_lo)}" if _fmt(c_lo) not in t1 else "")},
                         {**buy_deep, "t": f"跌破 {_fmt(c_lo)} 以後看 " + buy_deep["t"]}]
                up_v = next((g for g in ups if g["lo"] > price), None)
                dn_v = next((g for g in dns if g["hi"] < price), None)
                act_u = {"ctrl": "站不穩＝還有一腳破底", "g2": "站穩＝排除破底", "g3": "突破踩穩＝5-3"}
                act_d = {"r382": "跌破＝短線轉弱", "r618": "跌破＝反彈結束", "lo": "跌破＝再破底一腳"}
                tiles = {"up": tile(up_v["lo"], up_v["name"], act_u[up_v["kind"]]) if up_v else tile(top, "5-1 高點", "站上＝5-2 結束"),
                         "down": tile(dn_v["hi"], dn_v["name"], act_d[dn_v["kind"]]) if dn_v else down,
                         "stop": tile(g2v, g2n, "60 分站穩＝排除破底") if up_v and up_v["kind"] == "ctrl" else None}
                flip = (f"改判：60 分 K 實體站穩 {_fmt(g2v)}＝排除再破底、B 裡面的回檔在 {_fmt(c_lo)} 落底轉上；突破並守穩 {_fmt(b_hi)}／{_fmt(top)}＝5-2 已在 {_fmt(c_lo)} 走完、啟動 5-3；"
                        f"跌破 {_fmt(c_lo)} 且收在下面＝最後一腳往 {_fmt(a_low)}、{deep_t}")
        elif stage == "A":
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
            # B112：C 段跌很深（11/16 一天跌 2,949 點到 40,714，三個大買點全到）——量度標「已到」、上方下方格子用離現價最近的那一層
            # B113 她 11/16：C 段是標準五波（C-1～C-5，照 60 分轉折切）、第二層 0.786＋平台低點
            c52, cg, z7 = sb.get("c52") or [], sb.get("cleg"), sb.get("z786")
            n_hit = sum(1 for z in zs if z.get("hit"))
            ct = "、".join(f"{nm_.split('＝')[-1]} {_fmt(v)}" + ("（已到）" if (c_low - v) * u <= 1 else "") for v, nm_ in c52)
            gap = (low52 - zs[-1]["v"]) * u if low52 is not None else 0     # 最深一區的黃金切割本身還差幾點
            where_t = (("三個大買點都碰到了" + (f"（最深一區只碰到上緣，{zs[-1]['r']:g} 的 {_fmt(zs[-1]['v'])} 還差 {_fmt(round(gap))} 點）" if gap > 0 else ""))
                       if n_hit == len(zs) else f"已經到第 {n_hit} 個大買點" if n_hit else "往大買點走")
            leg_t = "、".join(f"C-{x['k']} {_fmt(x['p'])}" for x in cg["legs"]) if cg else ""
            pos.append(f"{lb['small']}：5-2 走 A-B-C 三段——A 跌到 {_fmt(a_low)}、B 彈到 {_fmt(b_hi)} 都走完，現在是 C 段下跌（到 {_fmt(c_low)}），{where_t}"
                       + (f"；C 段照 {lb['small']}轉折是{cg['kind']}：{leg_t}" if cg else ""))
            if cg:
                pos.append(f"接下來：{cg['next']}")
            shape = ("三段式修正（A-B-C）的 C 段" + (f"，{cg['kind']}走到第 {cg['n']} 腳" if cg else "") + "：最後一段下跌，走完才是 5-3 起漲")
            lvn = {}
            for v, nm_ in c52:
                lvn[round(v, 2)] = "C＝" + nm_.split("＝")[-1]
            if z7:
                lvn[round(z7["v"], 2)] = "第二層：0.786"
                if z7["near"] is not None:
                    lvn[round(z7["near"], 2)] = "第二層：前波平台低點"
            if cg:
                for v, nm_ in cg["t5"]:
                    lvn[round(v, 2)] = nm_
                for x in cg["legs"][:4 if cg["n"] == 5 else cg["n"] - 1]:    # 還在走的那一腳（最後一個）不當價位
                    lvn[round(x["p"], 2)] = f"C-{x['k']} {'低' if x['t'] == 'L' else '高'}點"
                if cg["n"] == 5:
                    lvn[round(cg["legs"][4]["p"], 2)] = "C-5 低點"
            for z in zs:                                              # 大買點的名字蓋過量度（同一個價位時）
                lvn[round(z["v"], 2)] = f"大買點 {z['r']:g}"
                if z["near"] is not None:
                    lvn[round(z["near"], 2)] = f"大買點 {z['r']:g} 旁邊的前低"
            broke = sorted(v for v in lvn if v > price and (c_low - v) * u <= 1)          # 已經跌破、現在在頭上的
            under = sorted((v for v in lvn if v < price), reverse=True)                   # 現價下面的
            longs = longs + [(v, nm_) for v, nm_ in lvn.items() if v < price and all(abs(v - w) > 1 for w, _ in longs)]
            z7t = f"；再破就看第二層 {rng(z7['lo'], z7['hi'])}（0.786" + ("＋前波平台低點" if z7["near"] is not None else "") + "）" if z7 else ""
            t5t = ("；C-5 的量度 " + "、".join(f"{nm_.split('＝')[-1]} {_fmt(v)}" for v, nm_ in cg["t5"])) if cg and cg["t5"] else ""
            plays = [{"k": "wait", "tag": "不追空", "t": f"C 段的量度 {ct}；{where_t.split('（')[0]}，追空沒有肉，手上有空單就照目標分批回補"},
                     {**buy, "t": buy["t"] + (f"；三區都碰到了，最深這一區 {rng(zs[-1]['lo'], zs[-1]['hi'])} 守不守是關鍵" if n_hit == len(zs) else "") + z7t + t5t}]
            c4 = cg["c4"] if cg and cg["n"] == 5 else None            # 五腳走齊以後：站回 C-4 高點＝C 段走完的第一個證據
            c1_lo = cg["legs"][0]["p"] if cg and cg["n"] < 5 else None  # 還沒走齊：C-4 反彈不能回到 C-1 低點上面（4 不碰 1）
            stop_t = (tile(c4, "C-4 高點", "站上＝C 段五腳走完") if c4 is not None and c4 > price else
                      tile(c1_lo, "C-1 低點", "站上＝4 碰到 1") if c1_lo is not None and c1_lo > price else tile(b_hi, "B 段高點", "站上＝C 段沒了"))
            tiles = {"up": tile(broke[0], lvn[broke[0]], "站回去＝止跌第一步") if broke else tile(b_hi, "B 段高點", "站上＝C 段沒了"),
                     "down": tile(under[0], lvn[under[0]], "跌破又收回才做多") if under else tile(p0, "5-1 起點", "跌破＝看法作廢"),
                     "stop": stop_t if broke else tile(top, "5-1 高點", "站上＝5-1 還在走")}
            if cg:
                flip = ((f"改判：站上 {_fmt(c4)}（C-4 高點）＝C 段五腳走完、5-2 可能已經落底；" if c4 is not None and c4 > price else
                         f"改判：站上 {_fmt(c1_lo)}（C-1 低點）＝4 碰到 1、標準五波不成立（C 段可能已經在 {_fmt(c_low)} 走完）；" if c1_lo is not None and c1_lo > price
                         else "改判：")
                        + f"站上 {_fmt(b_hi)}（B 段高點）＝C 段沒了；跌破 {_fmt(p0)}＝第 5 大波的看法作廢")
            ph = (cg or {}).get("phase")
            g53 = (cg or {}).get("gates53") or []
            gt = lambda g: _fmt(g["lo"]) + (f"～{_fmt(g['hi'])}" if g["hi"] != g["lo"] else "")   # noqa: E731
            if ph == "ext":                                           # B119 她 11/17 情境 B：站上 C-4 高點後又跌破 C-5 低點
                c5a, reb = cg["c5a"], cg["reb"]
                deep_ok = z7 and (z7["hi"] - price) * u < 0
                plays.insert(1, {"k": "long", "tag": "站回才做多",
                                 "t": f"C-5 跌破前低 {_fmt(c5a)} 還在延伸：跌深以後 15 分 K 站回 {_fmt(c5a)} 才進（她：站回收上 40,616 就是很漂亮的買點），"
                                      f"停損放最低點下面；站不回去就看第二層" + (f" {rng(z7['lo'], z7['hi'])}" if z7 else "")
                                      + "（要有底背離、迅速收復才是洗盤底）"})
                tiles = {"up": tile(c5a, "前一個 C-5 低點", "站回＝買點") if (c5a - price) * u > 0 else tiles["up"],
                         "down": tile(z7["hi"], "第二層上緣", "跌進去等止穩") if deep_ok else tiles["down"],
                         "stop": tile(reb, "C-5 後的反彈高點", "站上＝C 段走完")}
                flip = (f"改判：站回 {_fmt(c5a)}＝假跌破、C 段可能已經落底；站上 {_fmt(reb)}＝C 段走完、看 5-3；"
                        f"跌破第二層" + (f" {_fmt(z7['lo'])}" if z7 else "") + "＝5-2 比她估的更深")
            dev, z80, dep = sb.get("dev"), sb.get("z80"), sb.get("depth")
            if dev and z80 is not None and dep is not None and dep >= 0.618:   # B121 她 11/17 晚上：跌過 0.618 以後才講 0.8 極限防線、三種發展
                ma5 = t.get("ma5")
                reb = (cg or {}).get("reb")
                strong = sorted(x for x in (ma5, reb) if x)
                pos.append(f"深度：5-2 已回撤 5-1 漲幅的 {dep:.1%}（最低 {_fmt(sb['pb'])}）；0.786 {_fmt(z7['v']) if z7 else '—'}、極限 0.8 {_fmt(z80)}"
                              + ("——還沒跌破，屬「5-2 極限壓回洗盤」" if dev == 1 else
                                 f"——已跌破 0.8，轉「日線第二隻大腳（W 底）」，看 {_fmt(p0)}" if dev == 2 else
                                 f"——{_fmt(p0)} 也跌破了，要防「4-C 真 C-5 主跌段」"))
                dv = [f"① 日線收盤守住 {_fmt(z80)}、60 分收復 {_fmt((cg or {}).get('c5a') or c_low)}" + (f"、站上日線 5 均 {_fmt(ma5)}" if ma5 else "")
                      + "＝5-2 極限洗盤，整理完直接 5-3",
                      f"② 跌破 {_fmt(z80)}＝打日線第二隻大腳（W 底），回測 {_fmt(p0)}：不破或假跌破迅速收回都算築底，第二隻腳低點才重算 5-1",
                      f"③ {_fmt(p0)} 被帶量長黑收盤跌破、反彈收不回前箱底與 5 均＝真 C-5 主跌段（風險邊界，沒觸發前不要自己嚇自己）"]
                plays.insert(0, {"k": "wait", "tag": f"三種發展（現在第 {dev} 種）", "t": "；".join(dv)})
                if dev == 1:
                    tiles["down"] = tile(z80, "0.8 極限防線", "日線收盤跌破＝轉第二隻腳")
                    if strong and strong[-1] > price:
                        tiles["stop"] = tile(strong[0], "日線 5 均～C-5 後反彈高點" if len(strong) > 1 else "轉強關卡",
                                             f"帶量站穩 {rng(strong[0], strong[-1])}＝重啟波段")
                elif dev == 2:
                    tiles["down"] = tile(p0, "多頭總底線", "長黑收盤跌破＝主跌段")
                flip = (re.sub(r"；跌破第二層[^；]*", "", flip or "") + f"；日線收盤跌破 {_fmt(z80)}＝轉第二隻大腳（W 底）；{_fmt(p0)} 被長黑跌破＝4-C 真 C-5").lstrip("；")
            if ph == "done" and g53:                                # B119 她 11/17 情境 A：C 段走完、5-3 要過三關
                c5a = cg["c5a"]
                nxt_g = next((g for g in g53 if (g["hi"] - price) * u > 0), None)
                plays = [{"k": "wait", "tag": "5-3 還沒開",
                          "t": "三關都過才開啟 5-3：" + "；".join(f"{'①②③'[g['k'] - 1]} {gt(g)}（{g['name']}）" for g in g53)},
                         {"k": "long", "tag": "回測不破才做多",
                          "t": f"回測不破 C-5 低點 {_fmt(c5a)}、{how_long}；跌破 {_fmt(c5a)}＝C-5 還沒走完"}]
                up_p = (nxt_g["lo"] if (nxt_g["lo"] - price) * u > 0 else nxt_g["hi"]) if nxt_g else None   # 已經在這一關裡面＝看上緣
                tiles = {"up": tile(up_p, nxt_g["name"].split("（")[0], "站穩＝下一關") if nxt_g else tiles["up"],
                         "down": tile(c5a, "C-5 低點", "跌破＝C-5 還沒走完"), "stop": None}
                longs = longs + [(c5a, "C-5 低點")]
                flip = f"改判：跌破 {_fmt(c5a)}＝C-5 還在延伸（她的情境 B）；三關都過＝5-3 開啟"
        if flip is None:
            flip = (f"改判：站上 {_fmt(b_hi)}（B 段高點）＝C 段沒了、5-2 可能已經結束；" if stage == "C" else
                    f"改判：站上 {_fmt(top)}＝5-2 走完、5-3 啟動；") + f"跌破 {_fmt(p0)}＝第 5 大波的看法作廢"
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
    mp = None
    try:
        mp = _map52(t, sb, price) if t["tag"] == "52" and sb.get("done") and u > 0 else None
    except Exception:     # noqa: BLE001
        mp = None
    return {"pos": pos, "shape": shape, "plays": plays, "exit": EXIT, "flip": flip, "method": METHOD, "tiles": tiles, "signal": sig, "steps": steps,
            "map": mp,
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
