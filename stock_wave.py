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


def _paths(after: list, d: int, ext: float, price: float, y: float, x: float, T: dict, L1: dict, H2: dict,
           ffib: dict, fib382: float, ma5: Optional[float], lb: dict, case: str, neck: Optional[list] = None) -> Optional[dict]:
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
        lines.append(f"升級以後（她 11/10）：新脈動（{_fmt(last_lo)} 起{'漲' if d < 0 else '跌'}）跟舊脈動（{_fmt(H2['p'])}→{_fmt(ext)}）做撐壓交換；"
                     f"新脈動小 (3) 目標 {_fmt(proj)}（{_fmt(prev_hi)}→{_fmt(last_lo)} 壓回段的 1.618 倍外部投射），到了容易短線調節、小 (4) 換氣"
                     + (f"；上方撐壓互換頸線 {_fmt(nk[0][0])}～{_fmt(nk[-1][0])}（" + "、".join(t for _, t in nk) + f"）：{nst}" if nk else ""))
    return {"a": [ext, a_end], "b": b, "c1": top, "c2": last_lo, "c": {str(r): round(v, 2) for r, v in c.items()},
            "paths": paths, "layers": [L1v, L2v, L3v], "next": nxt, "lines": lines}


def _ext3(S: list, k: int, d: int, ext: float, R: float, price: float, T: dict, L1: dict, H2: dict,
          full: Optional[float], lb: dict, case: str, after: Optional[list] = None, fib382: Optional[float] = None,
          ma5: Optional[float] = None, neck: Optional[list] = None) -> Optional[dict]:
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
    pz = _paths(after or [], d, ext, price, y, x, T, L1, H2, ffib, fib382, ma5, lb, case, neck) if fib382 is not None else None
    return {"y": y, "x": x, "legs": [round(l1, 2), round(l31, 2)], "full": full, "ffib": {str(r): round(v, 2) for r, v in ffib.items()},
            "brakes": brakes, "reb": reb, "five": five, "paths": pz, "lines": lines}


def structure(big: list, small: list, price: float, ma5: Optional[float] = None, ma10: Optional[float] = None,
              labels: Optional[dict] = None, first_leg: Optional[list] = None, full: Optional[float] = None) -> Optional[dict]:
    """big：大級轉折（舊→新，含最後還沒確認的那個），至少 [T, L1, H2, X]；small：小級轉折，從 H2 開始、到現在（含暫定）。
    price：現價；ma5／ma10：大級的 5、10 均（台指期＝日線）。labels：{"big": "日線", "small": "60 分"}（顯示用）。
    first_leg：小級轉折從 T 到 L1（有給才算 B95 的第一段落點分歧）。full：全波段起點（B98，T 之前更大一級的轉折）。
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
    if gate1["passed"] and reb > 0:
        z = sorted([R + d * 0.382 * reb, R + d * 0.5 * reb])
        entry = {"zone": [round(z[0], 2), round(z[1], 2)], "from": [ext, round(R, 2)], "target": round(fib[0.5], 2),
                 "t": f"等{s_up}的第二隻腳：壓回到這段{s_up}（{_fmt(ext)}→{_fmt(R)}）的 0.382～0.5＝{_fmt(z[0])}～{_fmt(z[1])}，"
                      f"技術面確認止{s_dn}才進場，目標 0.5 {_fmt(fib[0.5])}；追{'高' if d < 0 else '低'}沒有肉"}
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
    ext3 = _ext3(S, k, d, ext, R, float(price), T, L1, H2, full, lb, case, after=after, fib382=fib[0.382], ma5=ma5, neck=neck)
    if entry:
        lines.append(entry["t"])
    else:
        lines.append(f"進場：先看 0.382 {_fmt(fib[0.382])} 有沒有真的{'過' if d < 0 else '破'}，之後壓回的第二隻腳（{s_up}的 0.382～0.5）才考慮；"
                     "現在追沒有肉")
    return {"dir": d, "case": case, "tag": tag, "labels": lb,
            "big": {"T": T["p"], "L1": L1["p"], "H2": H2["p"], "ext": ext},
            "small": small_out, "fib": {str(r): round(v, 2) for r, v in fib.items()}, "rebound": round(R, 2),
            "gate1": gate1, "gate2": gate2, "fork": fork, "ext3": ext3, "entry": entry, "status": status, "lines": lines}


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
