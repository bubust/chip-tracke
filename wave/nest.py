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
- 平台 a-b-c（3-3-5）：b ≥ 0.9 倍 a（≤ 1.38 倍）、c 至少走 a 的 0.618 倍
- 走完的推動段：起點是整段最低、終點是整段最高
分數＝每個拆開的節點 (比例懲罰和＋0.35)÷(項數＋1)＋0.05（多拆一層的成本）；進行中的修正段回檔已經超過常見上限的，加懲罰（盤面證據）
"""
from __future__ import annotations

import math
from typing import Optional

from . import engine as E

MAX_DEPTH = 4            # 起點那一段（第 0 層）往下最多拆 4 層（B83：3→4，她 10/28 的 C-3-2 反彈裡還有 a-b-c：C-3-2-c）
MAX_PIV = 18             # 起點之後最多用幾個轉折點（計算量）
PARTIAL_K = 6            # 每個「從這點開始、還在進行中」最多留幾種拆法
UNVERIFIED = 0.15        # 進行中、還沒有比例可驗證的節點（例：只走完 a）的成本（完整的先驗 0.35 會讓「剛開始的新結構」永遠輸）
ALT_PEN = 0.15           # 交替原則：第 2、4 浪同樣急或同樣橫
THIRD_GAP = 0.15         # 第三個候選跟主要分數差這麼多以內才列（她：候選結構可以不只一套）
NODE_COST = 0.05         # 每多一個拆開的節點的成本（先用簡單的拆法）
DIAG_COST = E.KIND_PRIOR["diagonal"]    # 楔形少見（沿用 B78 校準）
ROLE_MISMATCH = 0.02     # 跟日 K 這一浪的性質（推動／修正）不一致時多加一點
RUN_FLAT_MIN = 0.618     # 平台 c 最少走 a 的 0.618 倍（c 沒回到 a 終點＝「穿底平台」／running flat，她的 A-1-(2) 就是這種）
NEST_SEG = 14            # B83 起點之後最多拆幾段：轉折更多就先把最小的那一段併掉（她的 60 分圖只標大段＋子浪；60 分 θ 小時 50265 起有 26 段，一段都拆不出來）
ANCHOR_LOOK = 80         # B83 找「日 K 這一浪的起點」最多往回看幾個轉折（以前只看 MAX_PIV 個，起點太遠就對不到）
ALT_GAP = 0.35           # B83 另一邊（大段還在走／已走完）的數法跟主要差這麼多以內就一定列出來
T5_MAX = 2.618           # B83 第 5 段時間最多是第 1、3 段較長那段的幾倍（她：同級數的段落時間要相近；超過加 ln(倍數/上限)）
EV_PRE = 0.20            # B83 還沒越過趨勢線：「大段已走完」的數法先加這麼多（她：前提是先越過下降趨勢線完成切組，不然大段還有下一段）
G = {
    "r2": E.GUIDE["r2"], "r3": E.GUIDE["r3"], "r4": E.GUIDE["r4"], "r5": E.GUIDE["r5"],
    "zb": E.GUIDE["rB_zig"], "zc": (0.618, 1.0, 1.618), "fb": (1.0, 1.236), "fc": (1.0, 1.272, 1.618),
    "dia": E.GUIDE["rDia"],
    "t24": (0.618, 1.0, 1.618),    # 第 4 段時間 ÷ 第 2 段時間（她：時間要走足同級波段應有的長度）
}
# 進行中的修正段「已經」回檔超過這個比例 → 加懲罰（ln(實際/上限)），讓證據改變排序（她說的：證據衝突就打開替代結構）
SOFT_MAX = {"imp2": 0.786, "imp4": 0.5, "zb": 0.786, "fb": 1.236, "dia": 0.81}
ROLES = {"imp": "MCICM", "diag": "CCCCC", "zz": "MCM", "flat": "CCM"}    # B83 I＝第 3 段：只能是五段推動（楔形只出現在 1、5、A、C）
KINDS_OF = {"M": ("imp", "diag"), "I": ("imp",), "C": ("zz", "flat")}
KIND_NAME = {"imp": "五段推動", "diag": "楔形", "zz": "鋸齒（5-3-5）", "flat": "平台（3-3-5）", "atom": "一段"}


def _pen(r: float, guides) -> float:
    return E._pen(r, guides)


def _soft(r: float, cap: float) -> float:
    return max(0.0, math.log(r / cap)) if r > 0 and cap > 0 else 0.0


def _form(nd: dict) -> str:
    """修正段的樣子：一段或鋸齒＝急（sharp）、平台＝橫（sideways）"""
    return "side" if nd["k"] == "flat" else "sharp"


def _alternation(w2: dict, w4: dict) -> float:
    """交替原則：第 2、4 浪通常一急一橫（她：第 2 浪簡單，第 4 浪原則上走 a-b-c）；一樣的加一點"""
    return ALT_PEN if _form(w2) == _form(w4) else 0.0


def _sig(nd: dict) -> tuple:
    """進行中那一串的結構（種類、走完幾段）一路往下"""
    if nd["k"] == "atom":
        return ()
    return (nd["k"], len(nd["subs"]) - 1) + _sig(nd["subs"][-1])


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
        self.ix = [int(q.get("i", k)) for k, q in enumerate(pts)]     # 第幾根 K 棒（算時間比例）
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
        if kind == "atom":
            own = 0.0
        elif partial and not pens:                       # 剛開始、還沒有任何比例可以驗證（例：只走完 a）
            own = UNVERIFIED + NODE_COST
        else:
            own = (sum(pens.values()) + E.PRIOR_PEN) / (len(pens) + E.PRIOR_N) + NODE_COST
        if kind == "diag":
            own += DIAG_COST
        if kind in ("imp", "diag") and len(subs) >= 4 and not subs[3].get("partial"):
            own += _alternation(subs[1], subs[3])
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
            if k >= 4:                                    # 第 4 段走完：時間跟第 2 段比（同級數的段落時間相近；B83 楔形也算）
                t2 = self.ix[b[2]] - self.ix[b[1]]
                t4 = self.ix[b[4]] - self.ix[b[3]]
                if t2 > 0 and t4 > 0:
                    pens["t24"] = _pen(t4 / t2, G["t24"])
            if nb == 5:                                   # B83 第 5 段（含進行中）的時間已經超過第 1、3 段較長那段的 T5_MAX 倍 → 加懲罰
                t5 = self.ix[b[5]] - self.ix[b[4]]        # 進行中的 b[5]＝最後一點：已經走的時間是下限
                ref = max(self.ix[b[1]] - self.ix[b[0]], self.ix[b[3]] - self.ix[b[2]])
                if ref > 0 and t5 > 0:
                    extra += _soft(t5 / ref, T5_MAX)
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
                if kind == "flat" and L[3] < RUN_FLAT_MIN * L[1]:
                    return None                           # 平台 c 太短（不到 a 的 0.618）
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
                    if role != "C" and (self.lo(i, j, d) < self.x(i, d) or self.hi(i, j, d) > self.x(j, d)):
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
    def partials(self, i: int, role: str, depth: int) -> list:
        """從 i 開始、還在進行中的各種拆法（每種「進行中那一串的結構」留最好的一個，最多 PARTIAL_K 個）。
        只留最好一個的話，內層比較省的拆法會把外層別的數法擠掉（例：她 10/20 的 A-4-b 被 A-5 擠掉）"""
        key = (i, role, depth)
        if key in self.mp:
            return self.mp[key]
        out = []
        d = self.d(i)
        if self.last - i == 1:
            out = [self._node("atom", i, None, d, [], {}, partial=True)]
        elif depth < MAX_DEPTH:
            for kind in KINDS_OF[role]:
                out += list(self._partials(kind, i, d, depth, kmin=1))
            out.sort(key=lambda nd: nd["cost"])
            out = out[:PARTIAL_K]
        self.mp[key] = out
        return out

    def partial(self, i: int, role: str, depth: int) -> Optional[dict]:
        ps = self.partials(i, role, depth)
        return ps[0] if ps else None

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
            best: dict = {}                                 # 進行中那一串的結構 → 最好的節點
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
                    for ps in self.partials(b[k], roles[k], depth + 1):
                        nd = self._node(kind, i, None, d, subs + [ps], r[0], r[1], partial=True)
                        sg = _sig(nd)
                        if sg not in best or nd["cost"] < best[sg]["cost"]:
                            best[sg] = nd
            yield from best.values()


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


def _pt(seq: list, k: int, times, tlabel) -> dict:
    q = seq[k]
    return {"p": round(float(q["p"]), 2), "t": tlabel(q["i"]), "time": int(times[q["i"]]) if times is not None else None}


def tree_out(node: dict, seq: list, times, tlabel, prefix: Optional[list] = None, depth: int = 0) -> list:
    """B80 版本樹（她 10/7 的畫法）：數法的節點 → [{lab, path, kind, split, from, to, now, subs}]（最多 MAX_DEPTH 層）"""
    if not node or node.get("k") == "atom":
        return []
    prefix = prefix or []
    labs = _sub_labels(node["k"], depth + 1)
    out = []
    for m, s in enumerate(node.get("subs") or []):
        path = prefix + [labs[m]]
        out.append({"lab": labs[m], "path": "-".join(path), "kind": KIND_NAME.get(s["k"], ""), "split": s["k"] != "atom",
                    "dir": s["d"], "from": _pt(seq, s["i"], times, tlabel),
                    "to": _pt(seq, s["j"] if s["j"] is not None else len(seq) - 1, times, tlabel),   # 進行中（j＝None）→ 目前的極值
                    "now": bool(s.get("partial")), "subs": tree_out(s, seq, times, tlabel, path, depth + 1)})
    return out


def parse(pts: list, anchor: int = 0, parent_role: Optional[str] = None, top_k: int = 4, only_role: Optional[str] = None) -> list:
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
    for role in (only_role,) if only_role else ("M", "C"):          # B83 only_role：日 K 定好第一層是 1-5 還是 A-B-C → 先篩再取前 top_k
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


def drop_smallest(seq: list) -> Optional[list]:
    """B83 併段：把最小的一段（相鄰兩個轉折）拿掉，前後兩段接成一段（像她的圖只標 (1)～(4) 這種大段）。
    起點、順方向的極值、最後一點（現價）不動；拿掉以後兩邊不能有更高的高點／更低的低點不見。沒有可併的 → None"""
    n = len(seq)
    if n < 5:
        return None
    d0 = 1 if seq[0]["t"] == "L" else -1
    ext = max(range(n), key=lambda k: d0 * seq[k]["p"])
    best = None
    for k in range(1, n - 2):
        if ext in (k, k + 1):
            continue
        a, b = seq[k], seq[k + 1]
        s = 1 if a["t"] == "H" else -1
        if s * (a["p"] - seq[k + 2]["p"]) > 0 or s * (seq[k - 1]["p"] - b["p"]) > 0:
            continue
        size = abs(a["p"] - b["p"])
        if best is None or size < best[0]:
            best = (size, k)
    if best is None:
        return None
    k = best[1]
    return seq[:k] + seq[k + 2:]


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


TL_TOL = 0.003           # B83 趨勢線「碰到」的容許誤差（0.3%）：她的線 50265→49594→47555 中間 49200 高出 0.28% 也算碰到


def _trendline(pts: list, anchor: int, ext: int, d0: int, t_now: int) -> Optional[dict]:
    """起點畫到「起點之後、極值之前」的同方向轉折。B83：取碰到最多轉折的那條（誤差 TL_TOL 內算碰到、沒有轉折超出線外 TL_TOL），
    一樣多取連到比較近的轉折那條（她畫的是現在正在測試的線）；都不行 → 最平的一條（舊做法）。回傳現在的值"""
    a = pts[anchor]
    ks = [k for k in range(anchor + 1, ext) if pts[k]["t"] == a["t"] and pts[k]["i"] != a["i"]]
    if not ks:
        return None
    best, flat = None, None
    for k in ks:
        s = (pts[k]["p"] - a["p"]) / (pts[k]["i"] - a["i"])
        if flat is None or -d0 * s > -d0 * flat[0]:      # 下跌取最平（斜率最大）的壓力線、上漲取最平的支撐線
            flat = (s, k)
        line = lambda q: a["p"] + s * (q["i"] - a["i"])   # noqa: E731
        if any((pts[j]["p"] - line(pts[j])) * -d0 > TL_TOL * line(pts[j]) for j in ks):
            continue                                      # 有轉折明顯穿過這條線
        touch = [j for j in ks if abs(pts[j]["p"] - line(pts[j])) <= TL_TOL * line(pts[j])]
        score = (len(touch), k)
        if best is None or score > best[0]:
            best = (score, s, k)
    s, k = (best[1], best[2]) if best else flat
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


def limit_zone(c: dict, seq: list, d0: int) -> Optional[dict]:
    """B83 她的「極限區」：『大段還在走』的數法裡，逆著大段的那一段（第 2／4 段、b 段、平台）最多走到哪還算這個數法。
    - 第 2 段 0.786、第 4 段 0.5、鋸齒 b 0.786、楔形 0.81（前一段的常見上限）～硬規則（第 2 段不破起點、第 4 段不碰第 1 段…）
      例 10/28：C-3-2＝C-3-1（47555→45523）的 0.786＝47,120，硬規則 47,555
    - 平台 c 段進行中、b 段已超過 a 的起點（穿頭破底）→ c＝a 等長 ～ b 段的 0.786
    回傳 {lo, hi, far, why, brk:[(價, 說明)]}；far＝越過就換數法的那一邊；brk＝已經越過的回檔價位（壓回跌破＝脈動斷裂）"""
    parent, node, depth = None, c["tree"], 0
    while node and node.get("partial") and node["k"] != "atom" and node["subs"]:
        parent, node, depth = node, node["subs"][-1], depth + 1
        if node["d"] == -d0:                                         # 第一個逆著大段、還在走的那段
            break
    else:
        return None
    P = lambda k: seq[k]["p"]                                        # noqa: E731
    m = len(parent["subs"]) - 1                                      # 這段是上一層的第幾段（0 起算）
    name = "-".join(c["path"][:depth])                              # 這段的浪名（例 C-3-2）
    s = node["i"]                                                    # 這段的起點
    prev_s = parent["subs"][m - 1]["i"] if m >= 1 else parent["i"]
    lp = abs(P(s) - P(prev_s))                                       # 前一段（順大段那段）的長度
    dirc = -d0                                                       # 這段的方向
    out = None
    subs = node["subs"]
    if node["k"] == "flat" and len(subs) >= 3:
        a0, a1, b1 = subs[0]["i"], subs[0]["j"], subs[1]["j"]
        la, lb = abs(P(a1) - P(a0)), abs(P(b1) - P(a1))
        if lb > la:                                                  # b 段超過 a 的起點＝穿頭破底
            lv = [(P(b1) + dirc * la, "c＝a 等長"), (P(b1) + dirc * 0.786 * lb, "b 段的 0.786")]
            out = {"why": f"{name} 是穿頭破底的平台（b 段 {_fmt(P(b1))} {'跌破' if d0 < 0 else '漲過'} a 段起點 {_fmt(P(a0))}），c 段的極限",
                   "lv": lv, "leg": (P(a1), P(b1))}
    if out is None and m >= 1:
        key = (parent["k"], m)
        cap = {("imp", 1): SOFT_MAX["imp2"], ("imp", 3): SOFT_MAX["imp4"], ("diag", 1): SOFT_MAX["dia"], ("diag", 3): SOFT_MAX["dia"],
               ("zz", 1): SOFT_MAX["zb"], ("flat", 1): 1.0}.get(key)
        if cap is None:
            return None
        if key == ("imp", 3):
            hard = P(parent["subs"][0]["j"])                         # 第 4 段不能碰第 1 段終點
        elif key == ("diag", 3):
            hard = P(parent["subs"][1]["j"])                         # 楔形第 4 段不能過第 2 段終點
        elif key == ("flat", 1):
            hard = P(s) + dirc * E.FLAT_MAX * lp
        else:
            hard = P(prev_s)                                         # 第 2 段／b 段不能破前一段起點
        lv = [(P(s) + dirc * cap * lp, f"前一段的 {cap:g}"), (hard, "硬規則")]
        out = {"why": f"{name} 是逆著大段的{'反彈' if d0 < 0 else '回檔'}，常見最多回到前一段的 {cap:g}", "lv": lv, "leg": (P(prev_s), P(s))}
    if out is None:
        return None
    ps = sorted(v for v, _ in out["lv"])
    far = ps[-1] if dirc > 0 else ps[0]
    a_, b_ = out["leg"]
    L = abs(a_ - b_)
    brk = [(b_ + dirc * r * L, f"{r:g}") for r in (0.618, 0.5)]
    return {"lo": round(ps[0], 2), "hi": round(ps[-1], 2), "far": round(far, 2), "why": out["why"],
            "lv": [(round(v, 2), t) for v, t in out["lv"]], "brk": [(round(v, 2), t) for v, t in brk]}


def _anchor(pts: list, daily_cnt: Optional[dict], daily_dates, tdate) -> tuple:
    """起點：日 K 主要劇本「現在這一浪」的起點，對到分 K 同方向轉折（前後 2 天內最極端的）；對不到 → 視窗內較早的極值"""
    n = len(pts)
    lo_i = max(0, n - 1 - MAX_PIV)
    lo_d = max(0, n - 1 - ANCHOR_LOOK)                   # B83 日 K 起點可以比較遠（轉折太多由 NEST_SEG 併段處理）
    if daily_cnt and daily_dates is not None and len(daily_cnt.get("labels") or []) >= 2:
        L = daily_cnt["labels"]
        s0, s1 = L[-2], L[-1]
        typ = "L" if s1["p"] > s0["p"] else "H"
        try:
            import datetime as _dt
            d_s = _dt.date.fromisoformat(str(daily_dates[s0["i"]])[:10])
            cand = [k for k in range(lo_d, n - 2) if pts[k]["t"] == typ and abs((tdate(pts[k]["i"]) - d_s).days) <= 2]
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


def anchor_at(pts: list, t0: int, t1: int, typ: str, times) -> Optional[int]:
    """B80 15 分 K：起點對到上一層（60 分）那段的起點——時間在 [t0, t1) 內、同方向的轉折取最極端的；對不到 → None（B83：轉折多由 NEST_SEG 併段）"""
    n = len(pts)
    cand = [k for k in range(max(0, n - 1 - ANCHOR_LOOK), n - 2) if pts[k]["t"] == typ and t0 <= int(times[pts[k]["i"]]) < t1]
    if not cand:
        return None
    return (max if typ == "H" else min)(cand, key=lambda q: pts[q]["p"])


def build(an: dict, times: list, price: float, tfn: str = "60 分", daily_cnt: Optional[dict] = None,
          daily_dates=None, tdate=None, tlabel=None, parent_seg: Optional[dict] = None) -> dict:
    """分 K 的 analyze 結果 → 多層浪名＋關卡＋操作紀律。
    an：engine.analyze（pivots、tentative）；times：K 棒時間；tdate(i)→date、tlabel(i)→字串（分 K 第 i 根）
    parent_seg（B80 15 分 K）：{time, t0, t1, typ, name}＝上一層（60 分）主要數法第一層進行中那段的起點，對得到就從那裡拆"""
    piv = list(an.get("pivots") or [])
    tent = an.get("tentative")
    pts = piv + ([tent] if tent else [])
    if len(pts) < 4:
        return {"ok": False, "note": f"{tfn} K 轉折還不夠"}
    tdate = tdate or (lambda i: None)
    tlabel = tlabel or (lambda i: str(i))
    anchor, how = None, None
    if parent_seg:
        anchor = anchor_at(pts, parent_seg["t0"], parent_seg["t1"], parent_seg["typ"], times)
        how = "parent" if anchor is not None else None
    if anchor is None:
        anchor, how = _anchor(pts, daily_cnt, daily_dates, tdate)
    if anchor is None:
        return {"ok": False, "note": f"{tfn} K 找不到起點"}
    role = daily_role(daily_cnt) if how == "daily" else (parent_seg.get("role") if how == "parent" and parent_seg else None)
    # B83 起點之後的轉折：太多（> NEST_SEG 段）或拆不出合規則的數法 → 一次併掉最小的一段再試（她的圖只標大段＋子浪）
    seq = pts[anchor:]
    n_raw = len(seq) - 1
    cands: list = []
    while True:
        if len(seq) - 1 <= NEST_SEG:
            cands = (parse(seq, 0, top_k=12, only_role=role) if role else []) or parse(seq, 0, top_k=12)
            if cands:
                break
        nxt = drop_smallest(seq)
        if nxt is None:
            break
        seq = nxt
    if not cands:
        return {"ok": False, "note": f"{tfn} K 從起點開始的轉折拆不出合規則的數法"}
    d0 = 1 if seq[0]["t"] == "L" else -1
    ext_k = max(range(len(seq)), key=lambda k: d0 * seq[k]["p"])     # 起點之後順方向的極值
    a_p, e_p = seq[0]["p"], seq[ext_k]["p"]
    span = abs(e_p - a_p)
    fib = {r: e_p - d0 * r * span for r in (0.382, 0.5, 0.618)}
    t_now = len(times) - 1
    ext_f = max(range(anchor, len(pts)), key=lambda k: d0 * pts[k]["p"])   # 趨勢線用沒併段的轉折（每個高點都要在線下）
    tl = _trendline(pts, anchor, ext_f, d0, t_now)
    # 證據（她：證據一致升權、衝突就打開替代結構）：越過趨勢線、站上 0.382 → 「起點那一大段還在順方向走」的數法降權；
    # B83 還沒越過趨勢線 → 「大段已走完」的數法先加 EV_PRE（她 10/28：越過下降趨勢線並站穩才「級數轉浪」，不然維持原架構）
    beyond = lambda v: (price - v) * -d0 > 0                          # noqa: E731  反方向越過 v
    ev = {"trend": bool(tl) and beyond(tl["now"]), "f382": beyond(fib[0.382])}
    for c in cands:
        c["adj"] = c["cost"] + (0.03 * (ev["trend"] + ev["f382"]) if _with_trend(c, d0) else (0.0 if ev["trend"] else EV_PRE))
    cands.sort(key=lambda c: (round(c["adj"], 4), 0 if _with_trend(c, d0) else 1))
    prim, alt = primary_alternate(cands)
    third = next((c for c in cands if c is not prim and c is not alt and prim and c["path"][:2] != prim["path"][:2]
                  and (not alt or c["path"][:2] != alt["path"][:2]) and c["adj"] - prim["adj"] <= THIRD_GAP), None)
    # B83 逆著大段走的時候（反彈／回檔中），她一定拿兩邊比：「維持原架構」vs「級數轉浪」（10/21、10/28）→ 備選換成另一邊最好的
    #     （差 ALT_GAP 以內），原本的備選往後挪成第三個；順著大段走的時候（10/20）照原本的規則
    cur_dir = 1 if seq[-1]["p"] > seq[-2]["p"] else -1
    if prim and cur_dir != d0 and alt is not None and _with_trend(alt, d0) == _with_trend(prim, d0):
        opp = next((c for c in cands if _with_trend(c, d0) != _with_trend(prim, d0) and c["adj"] - prim["adj"] <= ALT_GAP), None)
        if opp is not None:
            alt, third = opp, alt

    def out_c(c):
        if not c:
            return None
        marks = []
        cur1 = c["path"][0] if c["path"] else None
        for k, lab in sorted(c["labels"].items()):
            q = seq[k]
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
        tops = sorted(c["lab1"])                         # 第一層走完的那幾段終點（seq 索引）
        k1 = tops[-1] if tops else 0                      # 第一層進行中那段的起點（seq 索引）
        q1 = seq[k1]
        lab0 = c["path"][0] if c["path"] else None
        labs1 = _sub_labels(c["top_kind"], 1)
        seg1 = {"time": int(times[q1["i"]]), "p": q1["p"], "t": q1["t"], "lab": lab0,
                "role": ROLES[c["top_kind"]][labs1.index(lab0)].replace("I", "M") if lab0 in labs1 else None}   # 這段本身是推動（M）還是修正（C）
        return {"path": c["path_str"], "role": c["role"], "top_kind": c["top_kind"], "text": c["text"],
                "cost": round(c["adj"], 4), "with_trend": _with_trend(c, d0), "marks": marks,
                "tree": {"kind": KIND_NAME.get(c["top_kind"], ""), "from": _pt(seq, 0, times, tlabel),
                         "to": _pt(seq, len(seq) - 1, times, tlabel), "subs": tree_out(c["tree"], seq, times, tlabel)},
                "seg1": seg1,
                "rules": [{**r, "price": round(r["price"], 2)} for r in _rule_levels(c, seq, d0)],
                "targets": _targets(c, seq)}
    P, A, T3 = out_c(prim), out_c(alt), out_c(third)
    # 關卡（她的寫法）：反向（逆著起點那一大段）走時 → 分水嶺（B83）、前提趨勢線、0.382、前高頸線＋0.5、0.618＋第 1 段低點區、失敗
    up_word, dn_word = ("反彈", "下跌") if d0 < 0 else ("回檔", "上漲")
    gates = []
    watershed = None
    if cur_dir != d0:
        # B83 分水嶺（她 10/28「關鍵分水嶺 46,969～47,120：C-3-2 極限區 vs 下降趨勢線轉浪口」）：
        # 「大段還在走」的數法裡，這段逆勢走最多到哪（還沒被價格淘汰的、排最前面的那個）＋趨勢線
        for c, x in ((prim, P), (alt, A), (third, T3)):
            if not (c and x and x["with_trend"]):
                continue
            z = limit_zone(c, seq, d0)
            if z and (z["far"] - price) * -d0 > 0:
                watershed = dict(z, path=x["path"])
                break
        if watershed:
            soft = next((v for v, t in watershed["lv"] if t != "硬規則"), watershed["far"])
            hard = next((v for v, t in watershed["lv"] if t == "硬規則"), None)
            ends = sorted([soft] + ([tl["now"]] if tl and (tl["now"] - price) * -d0 > 0 else []))
            lo_, hi_ = ends[0], ends[-1]
            far_ = hi_ if d0 < 0 else lo_
            ct = next((x for x in (P, A, T3) if x and not x["with_trend"]), None)
            lv_t = "、".join(f"{t} {_fmt(v)}" for v, t in watershed["lv"])
            watershed.update(lo=round(lo_, 2), hi=round(hi_, 2), far=round(far_, 2))
            gates.append({"k": "分水嶺", "price": round(far_, 2), "ok": beyond(far_) and ev["trend"],
                          "t": f"關鍵分水嶺 {_fmt(lo_) + '～' + _fmt(hi_) if round(lo_) != round(hi_) else _fmt(hi_)}："
                               f"{watershed['path']}（大段還在走）裡 {watershed['why']}（{lv_t}）"
                               + (f" vs {'下降' if d0 < 0 else '上升'}趨勢線轉浪口（現在約 {_fmt(tl['now'])}）" if tl else "")
                               + f" → 在這裡被壓回＝維持原架構、接著{dn_word}；越過趨勢線並站穩 {_fmt(far_)}＝級數轉浪"
                               + (f"（{ct['path']}）" if ct else "")
                               + (f"；{'漲過' if d0 < 0 else '跌破'} {_fmt(hard)} 這個數法就不成立" if hard is not None else "")})
        if tl:
            gates.append({"k": "前提", "price": round(tl["now"], 2), "ok": ev["trend"],
                          "t": f"{tfn}先越過{'下降' if d0 < 0 else '上升'}趨勢線（{tlabel(tl['from']['i'])} {_fmt(tl['from']['p'])} 連 "
                               f"{tlabel(tl['to']['i'])} {_fmt(tl['to']['p'])}，現在約 {_fmt(tl['now'])}）"})
        hi_word = "反彈高點" if d0 < 0 else "回檔低點"
        near = lambda a, b: abs(a / b - 1) < 0.003                       # noqa: E731  幾乎同一價 → 併成一關
        # 前高頸線（她 10/28 第二目標「前高頸線與 0.5」）＝走到極值的最後一段的起點
        neck = seq[ext_k - 1]["p"] if ext_k >= 2 and seq[ext_k - 1]["t"] == seq[0]["t"] else None
        # 這段逆勢走裡 a-b 都走完：c＝a 等長（她：45,523→46,846→46,006 的 c＝a 47,329）
        cea = None
        if len(seq) - 1 - ext_k == 3:
            q1, q2 = seq[ext_k + 1]["p"], seq[ext_k + 2]["p"]
            cea = q2 + (q1 - e_p)
        alt_trend = next((x for x in (P, A) if x and x["with_trend"]), None)
        fifth = [t for t in (alt_trend or {}).get("targets", []) if "第 5 段" in t["label"]]
        miss = f"；{'站' if d0 < 0 else '跌'}不{'上' if d0 < 0 else '破'}→ 這一大段還有第 5 段{dn_word}" + (f"（看 {'、'.join(_fmt(t['price']) for t in fifth)}）" if fifth else "")
        ladder = []                                                      # (價, 關卡文字, 已經越過)
        f382, f5, f618 = fib[0.382], fib[0.5], fib[0.618]
        between = lambda v, a, b: (v - a) * -d0 > 0 and (b - v) * -d0 > 0   # noqa: E731  v 在 a、b 之間（逆勢方向）
        if neck is not None and not near(neck, f382) and (f382 - neck) * -d0 > 0 and (neck - price) * -d0 > 0:
            ladder.append((neck, f"{'站上' if d0 < 0 else '跌破'} {_fmt(neck)}（前一個{hi_word}）→ 初步{'止跌' if d0 < 0 else '止漲'}", False))
        extra = []
        if neck is not None and near(neck, f382):
            extra.append(f"前一個{hi_word} {_fmt(neck)}")
        if cea is not None and near(cea, f382):
            extra.append(f"{_fmt(e_p)}→{_fmt(seq[ext_k + 1]['p'])}→{_fmt(seq[ext_k + 2]['p'])} 的 c＝a 等長 {_fmt(cea)}")
        ladder.append((f382, f"{'站穩' if d0 < 0 else '跌破'} {_fmt(f382)}（{_fmt(a_p)}→{_fmt(e_p)} 整段的 0.382"
                             + (f"；同時也是 {'、'.join(extra)}" if extra else "") + f"）→ 確認轉浪、換數法{miss}", ev["f382"]))
        first = [seq[k]["p"] for k in (1, 3) if k < len(seq) - 1 and seq[k]["t"] != seq[0]["t"]]
        z1 = f"＋第 1 段{'低點' if d0 < 0 else '高點'}領地 {_fmt(min(first))}～{_fmt(max(first))}" if first else ""
        if neck is not None and not near(neck, f382) and between(neck, f382, f5):
            ladder.append((f5, f"{_fmt(neck)} → {_fmt(f5)}（前高頸線＋0.5）", beyond(f5)))
            ladder.append((f618, f"{_fmt(f618)}（0.618）{z1} → {up_word}極限（逃命波），原則上在這裡開始下一段{dn_word}", beyond(f618)))
        else:
            zone = sorted([f5, f618])
            ladder.append((f5, f"{_fmt(zone[0])}～{_fmt(zone[1])}（0.5～0.618）{z1} → {up_word}目標區（逃命波），原則上在這裡開始下一段{dn_word}", beyond(f5)))
        names = ["第一關", "第二關", "第三關", "第四關"]
        for n_, (v, t, ok) in enumerate(ladder):
            gates.append({"k": names[n_], "price": round(v, 2), "ok": ok, "t": t})
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
        plan.append(f"這段是逆著{'下跌' if d0 < 0 else '上漲'}大段的{up_word}＝逃命波：到 0.5～0.618 分批{'出多單' if d0 < 0 else '回補空單'}，不要過度歡樂")
        if watershed:                                    # B83 她 10/28 的兩個版本＋盤中怎麼確認
            brk = [(v, t) for v, t in watershed["brk"] if (price - v) * -d0 > 0]
            s1 = (f"版本 1（維持原架構 {watershed['path']}）：{_fmt(watershed['far'])} {'開高衝不過' if d0 < 0 else '開低跌不破'}、在分水嶺前被"
                  f"{'壓回' if d0 < 0 else '拉回'}" + "".join(f" → {'跌破' if d0 < 0 else '漲過'} {_fmt(v)}（{t}）"
                                                       + ("先造成脈動斷裂" if n_ == 0 else f"確認重啟{dn_word}") for n_, (v, t) in enumerate(brk)))
            plan.insert(1, s1)
            ct = next((x for x in (P, A, T3) if x and not x["with_trend"]), None)
            tg = "、".join(_fmt(v) for v, _, _ in ladder[-3:])
            plan.insert(2, f"版本 2（級數轉浪{(' ' + ct['path']) if ct else ''}）：越過{'下降' if d0 < 0 else '上升'}趨勢線並站穩 {_fmt(watershed['far'])}"
                           f" → 目標 {tg}")
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
            "evidence": ev, "primary": P, "alternate": A, "third": T3, "gates": gates, "plan": plan,
            "watershed": watershed, "n_seg": len(seq) - 1, "merged": n_raw - (len(seq) - 1)}


def timeline(piv: list, h, l, c, times: list, ends: list, tfn: str, daily_at, daily_dates, tdate, tlabel) -> list:
    """浪名演變：每個 ends（K 棒索引，例如每天最後一根）當時「只用那時候以前的資料」重算一次主要／備選數法。
    daily_at(i) → 那根 K 棒當時（前一個交易日收盤）的日 K 主要劇本。回傳由舊到新，標出換數法的那一天"""
    out, prev = [], None
    for t in ends:
        conf, tent = E.state_at(piv, h, l, t)
        try:
            r = build({"pivots": conf, "tentative": tent}, list(times[:t + 1]), float(c[t]), tfn, daily_cnt=daily_at(t),
                      daily_dates=daily_dates, tdate=tdate, tlabel=tlabel)
        except Exception:  # noqa: BLE001
            continue
        if not r.get("ok"):
            continue
        p, a = r.get("primary") or {}, r.get("alternate") or {}
        row = {"t": int(times[t]), "label": tlabel(t), "price": round(float(c[t]), 2), "anchor": r["anchor"]["p"],
               "primary": p.get("path"), "ptext": p.get("text"), "alternate": a.get("path"),
               "evidence": r.get("evidence"), "changed": False, "step": False}
        if prev is not None and p.get("path") != prev:
            if prev_r["anchor"]["p"] == r["anchor"]["p"] and _progress(prev or "", p.get("path") or ""):
                row["step"] = True                          # 照原本的數法走到下一段（不是換數法）
            else:
                row["changed"] = True
                row["why"] = _why_change(prev_r, r)
        out.append(row)
        prev, prev_r = p.get("path"), r
    return out


_SEQS = ("12345", "ABC", "abc")


def _progress(old: str, new: str) -> bool:
    """new 是不是 old 照同一個數法往下走：同一層的下一段（C-3→C-4）、或這一段開始拆小段（A-4→A-4-a）、或小段走完回到上一層的下一段（A-4-c→A-5）"""
    o, n = old.split("-") if old else [], new.split("-") if new else []
    if not o or not n:
        return False
    if n[:len(o)] == o:                                 # 往下拆一層
        return True
    for k in range(min(len(o), len(n)) - 1, -1, -1):
        if o[:k] == n[:k] and len(n) == k + 1:
            a, b = o[k], n[k]
            return any(a in s_ and b in s_ and s_.index(b) == s_.index(a) + 1 for s_ in _SEQS)
    return False


def _why_change(old: dict, new: dict) -> str:
    """換數法的原因（白話）：起點換了、證據成立、或新的轉折讓原本的數法違反規則"""
    if old["anchor"]["p"] != new["anchor"]["p"]:
        return f"起點換成 {new['anchor']['p']:,.0f}（日 K 這一浪換了）"
    eo, en = old.get("evidence") or {}, new.get("evidence") or {}
    got = [k for k in ("trend", "f382") if en.get(k) and not eo.get(k)]
    if got:
        return "盤面證據成立：" + "、".join({"trend": "越過趨勢線", "f382": "站上 0.382"}[k] for k in got)
    for r in (old.get("primary") or {}).get("rules") or []:
        px = new["primary"]["marks"][-1]["p"] if new.get("primary") and new["primary"].get("marks") else None
        if px is not None and ((r["side"] == "below" and px < r["price"]) or (r["side"] == "above" and px > r["price"])):
            return f"{'跌破' if r['side'] == 'below' else '漲過'} {r['price']:,.0f}：{r['why']}"
    op, np_ = (old.get("primary") or {}), (new.get("primary") or {})
    last = (np_.get("marks") or [{}])[-1].get("p")
    s = f"原本 {op.get('path')}（{op.get('text', '')}）"
    s += f"；{'價格走到 ' + format(last, ',.0f') + '、' if last else ''}多了新的轉折後改數成 {np_.get('path')}（規則都沒違反，但分數變成比較好）"
    return s


# ── 她的「日線定位」寫法：母尺、防守區、鐵律底線、威脅版本的確認順序 ─────────────────────────
def positioning(prim: Optional[dict], alt: Optional[dict], price: float, tfn: str = "日 K") -> Optional[dict]:
    """日 K／週 K 主要劇本：現在這一段跟前一段反向時（回檔或反彈），用前一段當母尺：
    0.382、0.5（第一防守區）、0.618（第二極限防守區）、前一段起點（鐵律底線）；替代劇本＝威脅版本，列出它要成立得先過哪些價位"""
    if not prim or len(prim.get("labels") or []) < 3:
        return None
    L = prim["labels"]
    s0, s1, cur = L[-3], L[-2], L[-1]
    pd_ = 1 if s1["p"] > s0["p"] else -1
    if (cur["p"] - s1["p"]) * pd_ >= 0:
        return None                                          # 現在這段跟前一段同方向：不是回檔／反彈
    span = abs(s1["p"] - s0["p"])
    lv = {r: s1["p"] - pd_ * r * span for r in (0.382, 0.5, 0.618)}
    depth = abs(price - s1["p"]) / span if span else 0
    word = "回檔" if pd_ > 0 else "反彈"
    brk = "跌破" if pd_ > 0 else "漲過"
    d = lambda x: str(x.get("date") or "")[5:]               # noqa: E731
    lines = [
        f"定位 A（主要）：{_fmt(s0['p'])}（{d(s0)}）→ {_fmt(s1['p'])}（{d(s1)}）這一段當母尺，現在 {_fmt(s1['p'])} → {_fmt(price)} 是它的{word}，"
        f"已經{word} {depth:.0%}",
        f"母尺 0.382＝{_fmt(lv[0.382])}；第一防守區 0.5＝{_fmt(lv[0.5])}；第二極限防守區 0.618＝{_fmt(lv[0.618])}；"
        f"鐵律底線＝{_fmt(s0['p'])}（這一段的起點，{brk}就不是正常{word}）",
    ]
    ladder = [(lv[0.5], "0.5"), (lv[0.618], "0.618"), (s0["p"], "起點")]
    if alt:
        # 替代劇本也是「原方向還在走」（同方向的推動浪／楔形）→ 不是威脅，只列作廢價位；否則＝前一段可能已經結束的威脅版本
        threat = not (alt.get("kind") in ("impulse", "diagonal") and alt.get("dir") == pd_)
        need = "、".join(f"{_fmt(v)}（{k}）" for v, k in ladder if (v - price) * pd_ < 0)
        s = f"定位 B（{'威脅' if threat else '另一種數法'}）：{alt.get('text')}"
        if threat and need:
            s += f"；要正式成立，得依序{brk} {need}"
        if alt.get("invalid") is not None:
            s += f"；{'跌破' if alt.get('invalid_side') == 'below' else '漲過'} {_fmt(alt['invalid'])} 這個版本就作廢"
        lines.append(s)
    return {"tf": tfn, "lines": lines, "ruler": [s0["p"], s1["p"]], "levels": {str(k): round(v, 2) for k, v in lv.items()},
            "iron": s0["p"], "depth": round(depth, 4), "passed": [k for v, k in ladder if (v - price) * pd_ >= 0 and k != "起點"]}
