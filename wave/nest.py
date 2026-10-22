"""B79 多層浪名（PLAN-B79，學 Threads @fanny55520 的數法）：純函式，不碰網路與資料庫。

同一個級數的轉折點裡，一段走勢可以再拆成 5 段（推動浪 1-2-3-4-5／楔形）或 3 段（鋸齒 5-3-5／平台 3-3-5），
從「這一大段的起點」（日 K 這一浪的起點）開始，把之後的轉折點拆成一棵浪的樹：
  例：50265 → 48413 → 49479 → 48240 → 48705 → 46456 → 47634 → 46107 → 47033 → 46136 → 現在
  數法①「A-4-c」：A 段是五段下跌（第 3 段再拆 3-1～3-5），現在是第 4 段反彈（a-b-c）的 c
  數法②「B-c」：A 段是 5-3-5 鋸齒、在 46107 結束，現在是 B 段反彈的 c
每個數法都有自己的淘汰價位（例：第 4 段碰到第 1 段低點＝不是五段推動），主要＋備選照「規則貼近度＋已經走出來的證據」排序。

規則（x＝方向 × 價格，每一段都看成往上）：
- 推動浪：2 不破 1 的起點、3 要過 1 的終點、4 不能進 1 的價格區、3 不是最短；五段裡的 1、3、5 是推動、2、4 是修正
- 楔形：五段都是修正型（3 段）；4 要進 1 的價格區但不過 2 的終點；收斂 3<1、4<2、5<3／擴散相反
- 鋸齒 a-b-c（5-3-5）：b 不破 a 的起點、c 要過 a 的終點
- 平台 a-b-c（3-3-5）：b ≥ 0.9 倍 a（≤ 1.38 倍）、c 要走到 a 終點附近
- 走完的推動段：起點是整段最低、終點是整段最高
分數＝每個拆開的節點 (比例懲罰和＋0.35)÷(項數＋1)＋0.05（多拆一層的成本）；進行中的修正段回檔已經超過常見上限的，加懲罰（盤面證據）
"""
from __future__ import annotations

import math
from typing import Optional

from . import engine as E

MAX_DEPTH = 3            # 起點那一段（第 0 層）往下最多拆 3 層
MAX_PIV = 18             # 起點之後最多用幾個轉折點（計算量）
NODE_COST = 0.05         # 每多一個拆開的節點的成本（先用簡單的拆法）
DIAG_COST = E.KIND_PRIOR["diagonal"]    # 楔形少見（沿用 B78 校準）
ROLE_MISMATCH = 0.02     # 跟日 K 這一浪的性質（推動／修正）不一致時多加一點
C_SHORT = E.C_SHORT
G = {
    "r2": E.GUIDE["r2"], "r3": E.GUIDE["r3"], "r4": E.GUIDE["r4"], "r5": E.GUIDE["r5"],
    "zb": E.GUIDE["rB_zig"], "zc": (0.618, 1.0, 1.618), "fb": (1.0, 1.236), "fc": (1.0, 1.272, 1.618),
    "dia": E.GUIDE["rDia"],
}
# 進行中的修正段「已經」回檔超過這個比例 → 加懲罰（ln(實際/上限)），讓證據改變排序（她說的：證據衝突就打開替代結構）
SOFT_MAX = {"imp2": 0.786, "imp4": 0.5, "zb": 0.786, "fb": 1.236, "dia": 0.81}
ROLES = {"imp": "MCMCM", "diag": "CCCCC", "zz": "MCM", "flat": "CCM"}
KINDS_OF = {"M": ("imp", "diag"), "C": ("zz", "flat")}
KIND_NAME = {"imp": "五段推動", "diag": "楔形", "zz": "鋸齒（5-3-5）", "flat": "平台（3-3-5）", "atom": "一段"}


def _pen(r: float, guides) -> float:
    return E._pen(r, guides)


def _soft(r: float, cap: float) -> float:
    return max(0.0, math.log(r / cap)) if r > 0 and cap > 0 else 0.0


def _odd_splits(total: int, parts: int):
    """total 拆成 parts 個正奇數（依序）"""
    if parts == 1:
        if total >= 1 and total % 2 == 1:
            yield (total,)
        return
    for a in range(1, total - parts + 2, 2):
        for rest in _odd_splits(total - a, parts - 1):
            yield (a,) + rest


class _Parser:
    def __init__(self, pts: list):
        self.p = [float(q["p"]) for q in pts]
        self.t = [q["t"] for q in pts]
        self.n = len(pts)
        self.last = self.n - 1
        self.mc: dict = {}
        self.mp: dict = {}

    # ── 基本 ──
    def d(self, i: int) -> int:
        return 1 if self.t[i] == "L" else -1

    def x(self, i: int, d: int) -> float:
        return d * self.p[i]

    def lo(self, i: int, j: int, d: int) -> float:
        return min(d * self.p[k] for k in range(i, j + 1))

    def hi(self, i: int, j: int, d: int) -> float:
        return max(d * self.p[k] for k in range(i, j + 1))

    @staticmethod
    def _node(kind, i, j, d, subs, pens, extra=0.0, partial=False) -> dict:
        own = 0.0 if kind == "atom" else ((sum(pens.values()) + E.PRIOR_PEN) / (len(pens) + E.PRIOR_N) + NODE_COST
                                          + (DIAG_COST if kind == "diag" else 0.0))
        return {"k": kind, "i": i, "j": j, "d": d, "subs": subs, "pens": {k: round(v, 3) for k, v in pens.items()},
                "own": round(own + extra, 4), "cost": own + extra + sum(s["cost"] for s in subs), "partial": partial}

    # ── 結構規則（b：邊界索引，最後一個可能是進行中的終點 last；k＝走完的子段數）──
    def _rules(self, kind: str, b: list, d: int, k: int, partial: bool) -> Optional[tuple]:
        """回傳 (pens, extra) 或 None（違反硬規則）。b 長度＝k+1（走完的段）或 k+2（含進行中那段，終點＝last）"""
        X = [self.x(q, d) for q in b]
        L = [None] + [abs(X[m] - X[m - 1]) for m in range(1, len(X))]
        pens, extra = {}, 0.0
        nb = len(b) - 1                                   # 有幾段（含進行中）
        seg_lo = lambda m: self.lo(b[m - 1], b[m], d)     # 第 m 段範圍內的最低（x）  # noqa: E731
        if kind in ("imp", "diag"):
            if nb >= 2 and not seg_lo(2) > X[0]:
                return None                               # 2 跌破 1 的起點
            if k >= 3 and not X[3] > X[1]:
                return None                               # 3 沒過 1 的終點
            if kind == "imp":
                if nb >= 4 and not seg_lo(4) > X[1]:
                    return None                           # 4 進入 1 的價格區
                if k >= 5 and L[3] < L[1] and L[3] < L[5]:
                    return None                           # 3 最短
            else:
                if k >= 4 and not (X[4] < X[1]):
                    return None                           # 楔形：4 要進 1 的價格區
                if nb >= 4 and not seg_lo(4) > X[2]:
                    return None                           # 楔形：4 不過 2 的終點
                if k >= 3:
                    con = L[3] < L[1]
                    if k >= 4 and (L[4] < L[2]) != con:
                        return None
                    if k >= 5 and (L[5] < L[3]) != con:
                        return None
            if k >= 2:
                pens["r2"] = _pen(L[2] / L[1], G["dia"] if kind == "diag" else G["r2"])
            elif nb == 2 and partial:                     # 2 進行中：已經回檔多少
                extra += _soft((X[1] - seg_lo(2)) / L[1], SOFT_MAX["dia" if kind == "diag" else "imp2"])
            if k >= 3:
                pens["r3"] = _pen(L[3] / L[1], G["r3"] if kind == "imp" else (0.618, 1.0, 1.618))
            if k >= 4:
                pens["r4"] = _pen(L[4] / L[3], G["dia"] if kind == "diag" else G["r4"])
            elif nb == 4 and partial:
                extra += _soft((X[3] - seg_lo(4)) / L[3], SOFT_MAX["dia" if kind == "diag" else "imp4"])
            if k >= 5:
                pens["r5"] = _pen(L[5] / L[1], G["r5"])
        else:                                             # zz／flat
            if nb >= 2:
                rb_now = (X[1] - seg_lo(2)) / L[1]        # b（含進行中）最深回到哪
                if kind == "zz" and not seg_lo(2) > X[0]:
                    return None                           # 鋸齒 b 不破 a 的起點
                if kind == "flat" and rb_now > E.FLAT_MAX:
                    return None
            if k >= 2:
                rb = L[2] / L[1]
                if kind == "flat" and rb < E.FLAT_MIN:
                    return None
                pens["rB"] = _pen(rb, G["zb"] if kind == "zz" else G["fb"])
            elif nb == 2 and partial:
                extra += _soft(rb_now, SOFT_MAX["zb" if kind == "zz" else "fb"])
            if k >= 3:
                if kind == "zz" and not X[3] > X[1]:
                    return None                           # 鋸齒 c 要過 a 的終點
                if kind == "flat" and X[3] < X[1] - C_SHORT * L[1]:
                    return None                           # 平台 c 要到 a 終點附近
                pens["rC"] = _pen(L[3] / L[1], G["zc"] if kind == "zz" else G["fc"])
        return pens, extra

    # ── 走完的一段 [i, j] ──
    def complete(self, i: int, j: int, role: str, depth: int) -> Optional[dict]:
        key = (i, j, role, depth)
        if key in self.mc:
            return self.mc[key]
        best = None
        span = j - i
        d = self.d(i)
        if span % 2 == 1 and j < self.last:
            if span == 1:
                best = self._node("atom", i, j, d, [], {})
            elif depth < MAX_DEPTH:
                for kind in KINDS_OF[role]:
                    roles = ROLES[kind]
                    if span < len(roles):
                        continue
                    if role == "M" and (self.lo(i, j, d) < self.x(i, d) or self.hi(i, j, d) > self.x(j, d)):
                        break                             # 推動段：起點最低、終點最高
                    for parts in _odd_splits(span, len(roles)):
                        b = [i]
                        for a in parts:
                            b.append(b[-1] + a)
                        r = self._rules(kind, b, d, len(roles), False)
                        if r is None:
                            continue
                        subs = []
                        for m, rl in enumerate(roles):
                            s = self.complete(b[m], b[m + 1], rl, depth + 1)
                            if s is None:
                                break
                            subs.append(s)
                        else:
                            nd = self._node(kind, i, j, d, subs, r[0], r[1])
                            if best is None or nd["cost"] < best["cost"]:
                                best = nd
        self.mc[key] = best
        return best

    # ── 從 i 開始、還在進行中（終點＝最後一個轉折）──
    def partial(self, i: int, role: str, depth: int) -> Optional[dict]:
        key = (i, role, depth)
        if key in self.mp:
            return self.mp[key]
        best = None
        d = self.d(i)
        if self.last - i == 1:
            best = self._node("atom", i, None, d, [], {}, partial=True)
        elif depth < MAX_DEPTH:
            for kind in KINDS_OF[role]:
                for nd in self._partials(kind, i, d, depth, kmin=1):
                    if best is None or nd["cost"] < best["cost"]:
                        best = nd
        self.mp[key] = best
        return best

    @staticmethod
    def _prefix_splits(k: int, cap: int):
        """k 個正奇數、總和 ≤ cap 的所有組合（k＝0 → 一個空組合）"""
        if k == 0:
            yield ()
            return
        for total in range(k, cap + 1, 2):
            yield from _odd_splits(total, k)

    def _partials(self, kind: str, i: int, d: int, depth: int, kmin: int = 1):
        """kind 結構從 i 開始、走完 k 段（kmin ≤ k < 段數）＋第 k+1 段進行中；每個 k 回傳最好的一個"""
        roles = ROLES[kind]
        if kind in ("imp", "diag") and self.lo(i, self.last, d) < self.x(i, d):
            return                                        # 推動段進行中：不能低於起點
        rest = self.last - i
        for k in range(kmin, len(roles)):
            best = None
            for parts in self._prefix_splits(k, rest - 1):
                # k 段走完的邊界；剩下的（≥1 段）給進行中那段
                b = [i]
                for a in parts:
                    b.append(b[-1] + a)
                r = self._rules(kind, b + [self.last], d, k, True)
                if r is None:
                    continue
                subs = []
                for m in range(k):
                    s = self.complete(b[m], b[m + 1], roles[m], depth + 1)
                    if s is None:
                        break
                    subs.append(s)
                else:
                    ps = self.partial(b[k], roles[k], depth + 1)
                    if ps is None:
                        continue
                    nd = self._node(kind, i, None, d, subs + [ps], r[0], r[1], partial=True)
                    if best is None or nd["cost"] < best["cost"]:
                        best = nd
            if best is not None:
                yield best


# ── 浪名 ─────────────────────────────────────────────────────────────────────
def _sub_labels(kind: str, depth: int) -> list:
    if kind in ("imp", "diag"):
        return ["1", "2", "3", "4", "5"]
    return ["A", "B", "C"] if depth <= 1 else ["a", "b", "c"]


def _walk(node: dict, depth: int, prefix: list, out_lab: dict, chain: list):
    """把每個轉折點標上浪名（終點那一點）；chain：進行中那一串（由上而下）"""
    if node["k"] == "atom":
        return
    labs = _sub_labels(node["k"], depth + 1)
    for m, s in enumerate(node["subs"]):
        path = prefix + [labs[m]]
        if s.get("partial"):
            chain.append({"label": labs[m], "kind": s["k"], "d": s["d"], "i": s["i"], "parent": node["k"]})
        else:
            out_lab[s["j"]] = "-".join(path)
        _walk(s, depth + 1, path, out_lab, chain)


def _text(chain: list, top_kind: str) -> str:
    """進行中那一串 → 白話：例「A 段（五段下跌）的第 4 段反彈・c 段（往上）進行中」"""
    parts = []
    for lv, c in enumerate(chain):
        mv = "上漲" if c["d"] > 0 else "下跌"
        lab = c["label"]
        if c["parent"] in ("imp", "diag"):
            s = f"第 {lab} 段{'推進' if lab in '135' and c['parent'] == 'imp' else ''}"
            s += f"（{'反彈' if c['d'] > 0 else '回檔'}）" if lab in "24" else f"（{mv}）"
        else:
            s = f"{lab} 段（{'反彈' if c['d'] > 0 and lab.upper() == 'B' else '回落' if lab.upper() == 'B' else mv}）"
        if c["kind"] not in ("atom",):
            s += f"＝{KIND_NAME[c['kind']]}"
        parts.append(s)
    return " → ".join(parts) + " 進行中" if parts else ""


def parse(pts: list, anchor: int = 0, parent_role: Optional[str] = None, top_k: int = 4) -> list:
    """pts：轉折點（確認＋最後一個進行中的極值）；anchor：起點索引。回傳數法清單（分數低＝好），每個含：
    path（如 ['A','4','c']）、path_str、top_kind、chain、labels（{pts 索引: 浪名}）、cost、tree"""
    seq = pts[anchor:]
    if len(seq) > MAX_PIV + 1:
        return []
    P = _Parser(seq)
    if P.n < 3:
        return []
    d0 = P.d(0)
    cands = []
    for role in ("M", "C"):
        for kind in KINDS_OF[role]:
            for nd in P._partials(kind, 0, d0, 0, kmin=0):
                extra = ROLE_MISMATCH if parent_role and parent_role != role else 0.0
                nd = dict(nd, cost=nd["cost"] + extra)
                lab, lab1, chain = {}, {}, []
                top_labs = _sub_labels(kind, 1)
                # 第 0 層（起點那一大段）的子段
                for m, s in enumerate(nd["subs"]):
                    if s.get("partial"):
                        chain.append({"label": top_labs[m], "kind": s["k"], "d": s["d"], "i": s["i"], "parent": kind})
                    else:
                        lab[s["j"]] = top_labs[m]
                        lab1[anchor + s["j"]] = top_labs[m]
                    _walk(s, 1, [top_labs[m]], lab, chain)
                path = [c["label"] for c in chain]
                cands.append({"top_kind": kind, "role": role, "path": path, "path_str": "-".join(path),
                              "chain": chain, "labels": {anchor + k: v for k, v in lab.items()}, "lab1": lab1,
                              "cost": round(nd["cost"], 4), "tree": nd, "text": _text(chain, kind)})
    cands.sort(key=lambda c: c["cost"])
    out, seen = [], set()
    for c in cands:
        key = (c["role"], c["path_str"], tuple(sorted(c["labels"].items())))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out[:top_k]


def primary_alternate(cands: list) -> tuple:
    """主要＝分數最好；備選＝現在位置（浪名第一、二層）不同的下一個"""
    if not cands:
        return None, None
    p = cands[0]
    for c in cands[1:]:
        if c["path"][:2] != p["path"][:2] or c["role"] != p["role"]:
            return p, c
    return p, None


# ── 她的「關卡」與操作紀律 ─────────────────────────────────────────────────────
DAILY_ROLE = {  # 日 K 這一浪的性質：M＝推動（裡面拆 1-5）、C＝修正（裡面拆 A-B-C）；None＝不確定（兩種都試）
    ("impulse", "1"): "M", ("impulse", "3"): "M", ("impulse", "5"): "M", ("impulse", "2"): "C", ("impulse", "4"): "C",
}


def daily_role(cnt: Optional[dict]) -> Optional[str]:
    """日 K 主要劇本現在這一浪 → 推動／修正"""
    if not cnt:
        return None
    k, cur, ck = cnt.get("kind"), str(cnt.get("current") or ""), cnt.get("corr_kind")
    if (k, cur) in DAILY_ROLE:
        return DAILY_ROLE[(k, cur)]
    if k in ("impulse", "correction") and cur in ("A", "B", "C"):
        if cur == "B":
            return "C"
        if cur == "C":
            return "M"
        return "M" if ck == "zigzag" else None          # A：鋸齒的 A 是五段、平台的 A 是三段
    if k in ("combo", "triangle", "diagonal"):
        return "C" if cur not in ("Wa", "Ya", "Za") else None
    return None


def _fmt(p: float) -> str:
    return f"{p:,.0f}"


def _trendline(pts: list, anchor: int, ext: int, d0: int, t_now: int) -> Optional[dict]:
    """起點畫到「起點之後、極值之前」的同方向轉折，取最平的一條（所有轉折都在線的一側）；回傳現在的值"""
    a = pts[anchor]
    best = None
    for k in range(anchor + 1, ext):
        q = pts[k]
        if q["t"] != a["t"] or q["i"] == a["i"]:
            continue
        s = (q["p"] - a["p"]) / (q["i"] - a["i"])
        if best is None or -d0 * s > -d0 * best[0]:  # 下跌取最平（斜率最大）的壓力線、上漲取最平的支撐線
            best = (s, k)
    if best is None:
        return None
    s, k = best
    return {"from": {"i": a["i"], "p": a["p"]}, "to": {"i": pts[k]["i"], "p": pts[k]["p"]}, "slope": s,
            "now": a["p"] + s * (t_now - a["i"]), "t_now": t_now}


def _rule_levels(c: dict, seq: list, d0: int) -> list:
    """這個數法現在進行中那一串的「淘汰價位」（違反硬規則＝換數法）"""
    out = []
    node = c["tree"]
    depth = 0
    while node and node.get("partial") and node["k"] != "atom":
        subs = node["subs"]
        k = len(subs) - 1                                   # 走完幾段
        b = [node["i"]] + [s["j"] for s in subs[:-1]]
        d = node["d"]
        P = lambda m: seq[b[m]]["p"]                        # noqa: E731
        labs = _sub_labels(node["k"], depth + 1)
        cur = labs[k]
        side = "below" if d > 0 else "above"
        if node["k"] in ("imp", "diag") and k == 1:
            out.append({"price": P(0), "side": side, "why": f"第 2 段不能破第 1 段起點（{cur} 段）"})
        if node["k"] == "imp" and k == 3:
            out.append({"price": P(1), "side": side, "why": "第 4 段碰到第 1 段終點＝1、4 浪重疊，不是五段推動（化解成三段 abc）"})
        if node["k"] == "diag" and k == 3:
            out.append({"price": P(2), "side": side, "why": "楔形第 4 段不能過第 2 段終點"})
        if node["k"] == "zz" and k == 1:
            out.append({"price": P(0), "side": side, "why": "鋸齒 b 段不能破 a 的起點"})
        if node["k"] == "flat" and k == 1:
            a = abs(P(1) - P(0))
            out.append({"price": P(1) - d * E.FLAT_MAX * a, "side": side, "why": "平台 b 段不能超過 a 的 1.38 倍"})
        node = subs[-1]
        depth += 1
    # 最深那一段的起點：反向超過＝這一段其實還沒開始（前一段在延伸）
    last_i = len(seq) - 2
    dd = 1 if seq[-1]["p"] > seq[-2]["p"] else -1
    out.append({"price": seq[last_i]["p"], "side": "below" if dd > 0 else "above", "why": "這一小段的起點（反向超過＝前一段還在延伸）"})
    return out


def _targets(c: dict, seq: list) -> list:
    """進行中那一串每一層「這一段可能走到」（費波那契比例，跟 engine 同一套）"""
    out = []
    node = c["tree"]
    depth = 0
    while node and node.get("partial") and node["k"] != "atom":
        subs = node["subs"]
        k = len(subs) - 1
        b = [node["i"]] + [s["j"] for s in subs[:-1]]
        d = node["d"]
        P = lambda m: seq[b[m]]["p"]                        # noqa: E731
        L = lambda m: abs(P(m) - P(m - 1))                  # noqa: E731
        lab = _sub_labels(node["k"], depth + 1)[k]
        kind = node["k"]
        tg, nx = [], []
        now = seq[-1]["p"]
        if kind == "imp":
            if k == 1:
                tg = [(f"第 2 段回 {r:g}", P(1) - d * r * L(1)) for r in (0.5, 0.618)]
            elif k == 2:
                tg = [(f"第 3 段 {r:g} 倍第 1 段", P(2) + d * r * L(1)) for r in (1.618, 2.618)]
            elif k == 3:
                tg = [(f"第 4 段回 {r:g}", P(3) - d * r * L(3)) for r in (0.236, 0.382)]
                nx = [(f"第 5 段 {r:g} 倍第 1 段（第 4 段在現價結束的話）", now + d * r * L(1)) for r in (0.618, 1.0)]
            elif k == 4:
                tg = [(f"第 5 段 {r:g} 倍第 1 段", P(4) + d * r * L(1)) for r in (0.618, 1.0)]
        elif kind == "diag":
            if k in (1, 3):
                tg = [(f"楔形第 {k + 1} 段回 {r:g}", P(k) - d * r * L(k)) for r in (0.66, 0.81)]
        elif kind == "zz":
            if k == 1:
                tg = [(f"b 段回 {r:g}", P(1) - d * r * L(1)) for r in (0.5, 0.618)]
                nx = [(f"c＝{r:g} 倍 a（b 在現價結束的話）", now + d * r * L(1)) for r in (1.0, 1.618)]
            elif k == 2:
                tg = [(f"c＝{r:g} 倍 a", P(2) + d * r * L(1)) for r in (1.0, 1.618)]
        elif kind == "flat":
            if k == 1:
                tg = [(f"b 段回 {r:g}", P(1) - d * r * L(1)) for r in (0.9, 1.0)]
            elif k == 2:
                tg = [(f"c＝{r:g} 倍 a", P(2) + d * r * L(1)) for r in (1.0, 1.272)]
        for t_, v in nx:
            out.append({"level": depth, "wave": lab, "label": t_, "price": round(v, 2), "kind": "next"})
        for t_, v in tg:
            # 這一層進行中那段的方向：第 k 段（0 起算）偶數跟 node 同向、奇數反向；已經走過的目標不列
            dirk = d if k % 2 == 0 else -d
            if (v - now) * dirk > 0:
                out.append({"level": depth, "wave": lab, "label": t_, "price": round(v, 2), "kind": "end"})
        node = subs[-1]
        depth += 1
    return out


def _with_trend(c: dict, d0: int) -> bool:
    """第一層進行中那段跟起點那一大段同方向（還在主跌／主升裡）"""
    return bool(c["chain"]) and c["chain"][0]["d"] == d0


def _anchor(pts: list, daily_cnt: Optional[dict], daily_dates, tdate) -> tuple:
    """起點：日 K 主要劇本「現在這一浪」的起點，對到分 K 同方向轉折（前後 2 天內最極端的）；對不到 → 視窗內較早的極值"""
    n = len(pts)
    lo_i = max(0, n - 1 - MAX_PIV)
    if daily_cnt and daily_dates is not None and len(daily_cnt.get("labels") or []) >= 2:
        L = daily_cnt["labels"]
        s0, s1 = L[-2], L[-1]
        typ = "L" if s1["p"] > s0["p"] else "H"
        try:
            import datetime as _dt
            d_s = _dt.date.fromisoformat(str(daily_dates[s0["i"]])[:10])
            cand = [k for k in range(lo_i, n - 2) if pts[k]["t"] == typ and abs((tdate(pts[k]["i"]) - d_s).days) <= 2]
        except Exception:  # noqa: BLE001
            cand = []
        if cand:
            k = (max if typ == "H" else min)(cand, key=lambda q: pts[q]["p"])
            return k, "daily"
    win = range(lo_i, n - 2)
    if not win:
        return None, None
    kmax = max(win, key=lambda q: pts[q]["p"] if pts[q]["t"] == "H" else -1e18)
    kmin = min(win, key=lambda q: pts[q]["p"] if pts[q]["t"] == "L" else 1e18)
    return min(kmax, kmin), "window"


def build(an: dict, times: list, price: float, tfn: str = "60 分", daily_cnt: Optional[dict] = None,
          daily_dates=None, tdate=None, tlabel=None) -> dict:
    """分 K 的 analyze 結果 → 多層浪名＋關卡＋操作紀律。
    an：engine.analyze（pivots、tentative）；times：K 棒時間；tdate(i)→date、tlabel(i)→字串（分 K 第 i 根）"""
    piv = list(an.get("pivots") or [])
    tent = an.get("tentative")
    pts = piv + ([tent] if tent else [])
    if len(pts) < 4:
        return {"ok": False, "note": f"{tfn} K 轉折還不夠"}
    tdate = tdate or (lambda i: None)
    tlabel = tlabel or (lambda i: str(i))
    anchor, how = _anchor(pts, daily_cnt, daily_dates, tdate)
    if anchor is None:
        return {"ok": False, "note": f"{tfn} K 找不到起點"}
    role = daily_role(daily_cnt) if how == "daily" else None
    cands = parse(pts, anchor, parent_role=None, top_k=12)
    if role:
        cands = [c for c in cands if c["role"] == role] or cands
    if not cands:
        return {"ok": False, "note": f"{tfn} K 從起點開始的轉折拆不出合規則的數法"}
    seq = pts[anchor:]
    d0 = 1 if seq[0]["t"] == "L" else -1
    ext_k = max(range(len(seq)), key=lambda k: d0 * seq[k]["p"])     # 起點之後順方向的極值
    a_p, e_p = seq[0]["p"], seq[ext_k]["p"]
    span = abs(e_p - a_p)
    fib = {r: e_p - d0 * r * span for r in (0.382, 0.5, 0.618)}
    t_now = len(times) - 1
    tl = _trendline(pts, anchor, anchor + ext_k, d0, t_now)
    # 證據（她：證據一致升權、衝突就打開替代結構）：越過趨勢線、站上 0.382 → 「起點那一大段還在順方向走」的數法降權
    beyond = lambda v: (price - v) * -d0 > 0                          # noqa: E731  反方向越過 v
    ev = {"trend": bool(tl) and beyond(tl["now"]), "f382": beyond(fib[0.382])}
    for c in cands:
        c["adj"] = c["cost"] + (0.03 * (ev["trend"] + ev["f382"]) if _with_trend(c, d0) else 0.0)
    cands.sort(key=lambda c: (round(c["adj"], 4), 0 if _with_trend(c, d0) else 1))
    prim, alt = primary_alternate(cands)

    def out_c(c):
        if not c:
            return None
        marks = []
        cur1 = c["path"][0] if c["path"] else None
        for k, lab in sorted(c["labels"].items()):
            q = pts[k]
            parts = lab.split("-")
            rest = "-".join(parts[1:])
            if k in c["lab1"]:                              # 第一層某一段的終點：「A／c-5」
                text = c["lab1"][k] + (f"／{rest}" if rest else "")
            else:
                text = rest or parts[0]
            marks.append({"i": q["i"], "time": int(times[q["i"]]), "p": q["p"], "t": q["t"], "text": text,
                          "top": k in c["lab1"], "done": parts[0] != cur1})
        marks.append({"i": seq[-1]["i"], "time": int(times[seq[-1]["i"]]), "p": seq[-1]["p"], "t": seq[-1]["t"],
                      "text": (c["path"][-1] if c["path"] else "") + "?", "top": None})
        return {"path": c["path_str"], "role": c["role"], "top_kind": c["top_kind"], "text": c["text"],
                "cost": round(c["adj"], 4), "with_trend": _with_trend(c, d0), "marks": marks,
                "rules": [{**r, "price": round(r["price"], 2)} for r in _rule_levels(c, seq, d0)],
                "targets": _targets(c, seq)}
    P, A = out_c(prim), out_c(alt)
    # 關卡（她的寫法）：反向（逆著起點那一大段）走時 → 前提趨勢線、第一關前一個反彈高點、第二關 0.382、第三關 0.5～0.618＋第 1 段低點區
    cur_dir = 1 if seq[-1]["p"] > seq[-2]["p"] else -1
    up_word, dn_word = ("反彈", "下跌") if d0 < 0 else ("回檔", "上漲")
    gates = []
    if cur_dir != d0:
        if tl:
            gates.append({"k": "前提", "price": round(tl["now"], 2), "ok": ev["trend"],
                          "t": f"{tfn}先越過{'下降' if d0 < 0 else '上升'}趨勢線（{tlabel(tl['from']['i'])} {_fmt(tl['from']['p'])} 連 "
                               f"{tlabel(tl['to']['i'])} {_fmt(tl['to']['p'])}，現在約 {_fmt(tl['now'])}）"})
        nxt = [q for q in seq[1:-1] if q["t"] == seq[0]["t"] and (q["p"] - price) * -d0 > 0]
        g1 = min(nxt, key=lambda q: abs(q["p"] - price)) if nxt else None
        near = g1 is not None and abs(g1["p"] / fib[0.382] - 1) < 0.003     # 跟 0.382 幾乎同一價 → 併成一關
        if g1 is not None and not near:
            gates.append({"k": "第一關", "price": g1["p"], "ok": False,
                          "t": f"{'站上' if d0 < 0 else '跌破'} {_fmt(g1['p'])}（前一個{'反彈高點' if d0 < 0 else '回檔低點'}）→ 初步{'止跌' if d0 < 0 else '止漲'}"})
        alt_trend = next((x for x in (P, A) if x and x["with_trend"]), None)
        fifth = [t for t in (alt_trend or {}).get("targets", []) if "第 5 段" in t["label"]]
        miss = f"；{'站' if d0 < 0 else '跌'}不{'上' if d0 < 0 else '破'}→ 這一大段還有第 5 段{dn_word}" + (f"（看 {'、'.join(_fmt(t['price']) for t in fifth)}）" if fifth else "")
        both = f"、前一個{'反彈高點' if d0 < 0 else '回檔低點'} {_fmt(g1['p'])} 也在這裡" if near else ""
        gates.append({"k": "第一關" if near else "第二關", "price": round(fib[0.382], 2), "ok": ev["f382"],
                      "t": f"{'站穩' if d0 < 0 else '跌破'} {_fmt(fib[0.382])}（{_fmt(a_p)}→{_fmt(e_p)} 整段的 0.382{both}）→ 確認轉浪、換數法{miss}"})
        zone = sorted([fib[0.5], fib[0.618]])
        first = [seq[k]["p"] for k in (1, 3) if k < len(seq) - 1 and seq[k]["t"] != seq[0]["t"]]
        z1 = f"＋第 1 段{'低點' if d0 < 0 else '高點'}領地 {_fmt(min(first))}～{_fmt(max(first))}" if first else ""
        gates.append({"k": "第二關" if near else "第三關", "price": round(fib[0.5], 2), "ok": beyond(fib[0.5]),
                      "t": f"{_fmt(zone[0])}～{_fmt(zone[1])}（0.5～0.618）{z1} → {up_word}目標區（逃命波），原則上在這裡開始下一段{dn_word}"})
        lows = [q for q in seq[ext_k + 1:-1] if q["t"] != seq[0]["t"]]
        fail = (f"{'跌破' if d0 < 0 else '漲過'} {_fmt(lows[-1]['p'])}（這段{up_word}裡的低點）→ 這段{up_word}的數法不成立；" if lows else "")
        gates.append({"k": "失敗", "price": e_p, "ok": False,
                      "t": fail + f"{'跌破' if d0 < 0 else '漲過'} {_fmt(e_p)}（{'新低' if d0 < 0 else '新高'}）→ 第 5 段{dn_word}"})
    else:
        tg = [t for t in (P or {}).get("targets", [])][-2:]
        if tg:
            gates.append({"k": "目標", "price": tg[0]["price"], "ok": False,
                          "t": "、".join(f"{_fmt(t['price'])}（{t['label']}）" for t in tg)})
        opp = [q for q in seq[1:-1] if q["t"] == seq[0]["t"]]
        if opp:
            g = opp[-1]
            gates.append({"k": "轉強" if d0 < 0 else "轉弱", "price": g["p"], "ok": False,
                          "t": f"{'站上' if d0 < 0 else '跌破'} {_fmt(g['p'])}（前一個{'反彈高點' if d0 < 0 else '回檔低點'}）→ 這段{dn_word}可能結束"})
        if tl:
            gates.append({"k": "趨勢線", "price": round(tl["now"], 2), "ok": ev["trend"],
                          "t": f"{'下降' if d0 < 0 else '上升'}趨勢線現在約 {_fmt(tl['now'])}，越過＝{tfn}轉向的前提"})
    # 操作紀律（她的做法；規則化）
    plan = []
    if cur_dir != d0:
        plan.append(f"這段是逆著{'下跌' if d0 < 0 else '上漲'}大段的{up_word}＝逃命波：到第三關分批{'出多單' if d0 < 0 else '回補空單'}，不要過度歡樂")
    else:
        plan.append(f"順著大段{dn_word}中：{up_word}沒過前一個{'反彈高點' if d0 < 0 else '回檔低點'}就照原方向，別逆勢{'接多' if d0 < 0 else '放空'}")
    if P and P["path"].endswith(("c", "C", "5")):
        st_ = next((r for r in P["rules"] if "這一小段的起點" in r["why"]), None)
        if st_:
            plan.append(f"最後一段（{P['path'].split('-')[-1]}）進行中：起點 {_fmt(st_['price'])} 是多空線，{'跌破' if cur_dir > 0 else '漲過'}就是數法錯了，先出場")
    plan.append("進場等第一根回測不破前低／前高（她：第一根壓下來上車），防守放在多空線")
    plan.append("走一口留一口：第一個目標到了先出一半，剩下的防守拉到成本或多空線")
    plan.append("壓回失速、加速往反方向走＝盤中立刻換數法（她：一但壓回是失速的就轉浪）")
    return {"ok": True, "tf": tfn, "anchor": {"i": seq[0]["i"], "time": int(times[seq[0]["i"]]), "p": a_p, "how": how,
                                             "label": tlabel(seq[0]["i"])},
            "extreme": {"p": e_p, "label": tlabel(seq[ext_k]["i"])}, "dir": d0, "cur_dir": cur_dir,
            "daily_role": role, "fib": {str(k): round(v, 2) for k, v in fib.items()},
            "trendline": None if not tl else {"from": {**tl["from"], "time": int(times[tl["from"]["i"]])},
                                              "now": round(tl["now"], 2), "time_now": int(times[t_now]),
                                              "to": {**tl["to"], "time": int(times[tl["to"]["i"]])}},
            "evidence": ev, "primary": P, "alternate": A, "gates": gates, "plan": plan}
