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
FLAT_HARD = 1.45         # B86 平台 b 最多到 a 的幾倍（她 11/1 的「破底穿頭」46107→47555→45523：b＝1.40 倍 a）；超過 E.FLAT_MAX（1.38）的加 FLAT_OVER
FLAT_OVER = 0.40
ABC3_COST = 0.10         # B86 她的「三段式」：A 走三波（50265→48413→49594→46107）、B 不到 A 的 0.9（不是平台）、C 走五波；不是標準型態，只在源頭切組用
G = {
    "r2": E.GUIDE["r2"], "r3": E.GUIDE["r3"], "r4": E.GUIDE["r4"], "r5": E.GUIDE["r5"],
    "zb": E.GUIDE["rB_zig"], "zc": (0.618, 1.0, 1.618), "fb": (1.0, 1.236), "fc": (1.0, 1.272, 1.618),
    "dia": E.GUIDE["rDia"],
    "t24": (0.618, 1.0, 1.618),    # 第 4 段時間 ÷ 第 2 段時間（她：時間要走足同級波段應有的長度）
}
# 進行中的修正段「已經」回檔超過這個比例 → 加懲罰（ln(實際/上限)），讓證據改變排序（她說的：證據衝突就打開替代結構）
SOFT_MAX = {"imp2": 0.786, "imp4": 0.5, "zb": 0.786, "fb": 1.236, "dia": 0.81}
ROLES = {"imp": "MCICM", "diag": "CCCCC", "zz": "MCM", "flat": "CCM", "abc3": "CCM"}    # B83 I＝第 3 段：只能是五段推動（楔形只出現在 1、5、A、C）
KINDS_OF = {"M": ("imp", "diag"), "I": ("imp",), "C": ("zz", "flat")}
KIND_NAME = {"imp": "五段推動", "diag": "楔形", "zz": "鋸齒（5-3-5）", "flat": "平台（3-3-5）", "abc3": "三段式（A 三波、C 五波）", "atom": "一段"}


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
        self.keep_first = False                           # B86 源頭切組：第一層的「第一段終點」不同就分開留（不然只留最便宜的拆法）

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
        if kind == "abc3":
            own += ABC3_COST
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
        else:                                             # zz／flat／abc3（B86 三段式：規則同鋸齒，但 A 是三波、B 不到 A 的 0.9）
            zl = kind in ("zz", "abc3")
            if nb >= 2:
                rb_now = (X[1] - seg_lo(2)) / L[1]        # b（含進行中）最深回到哪
                if zl and not seg_lo(2) > X[0]:
                    return None                           # 鋸齒 b 不破 a 的起點
                if kind == "flat" and rb_now > FLAT_HARD:
                    return None
                if kind == "flat" and rb_now > E.FLAT_MAX:
                    extra += FLAT_OVER + _soft(rb_now, E.FLAT_MAX)   # B86 破底穿頭：b 超過 a 的 1.38 倍（她 11/1：46107→47555→45523）
            if k >= 2:
                rb = L[2] / L[1]
                if kind == "flat" and rb < E.FLAT_MIN:
                    return None
                if kind == "abc3" and rb >= E.FLAT_MIN:
                    return None                           # B 走到 A 的 0.9 以上＝平台，不重複算
                pens["rB"] = _pen(rb, G["zb"] if zl else G["fb"])
            elif nb == 2 and partial:
                extra += _soft(rb_now, SOFT_MAX["zb" if zl else "fb"])
            if k >= 3:
                if zl and not X[3] > X[1]:
                    return None                           # 鋸齒 c 要過 a 的終點
                if kind == "flat" and L[3] < RUN_FLAT_MIN * L[1]:
                    return None                           # 平台 c 太短（不到 a 的 0.618）
                pens["rC"] = _pen(L[3] / L[1], G["zc"] if zl else G["fc"])
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
                        sg = _sig(nd) + ((subs[0]["j"],) if self.keep_first and depth == 0 and subs else ())
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


def parse(pts: list, anchor: int = 0, parent_role: Optional[str] = None, top_k: int = 4, only_role: Optional[str] = None,
          extra_top: tuple = (), keep_first: bool = False) -> list:
    """pts：轉折點（確認＋最後一個進行中的極值）；anchor：起點索引。回傳數法清單（分數低＝好），每個含：
    path（如 ['A','4','c']）、path_str、top_kind、chain、labels（{pts 索引: 浪名}）、cost、tree"""
    seq = pts[anchor:]
    if len(seq) > MAX_PIV + 1:
        return []
    P = _Parser(seq)
    if P.n < 3:
        return []
    P.keep_first = keep_first
    d0 = P.d(0)
    cands = []
    for role in (only_role,) if only_role else ("M", "C"):          # B83 only_role：日 K 定好第一層是 1-5 還是 A-B-C → 先篩再取前 top_k
        for kind in KINDS_OF[role] + (tuple(extra_top) if role == "C" else ()):   # B86 extra_top：第一層多試的型態（源頭切組的三段式）
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
        if node["k"] in ("zz", "abc3") and k == 1:
            out.append({"price": P(0), "side": side, "why": f"{'鋸齒' if node['k'] == 'zz' else '三段式'} b 段不能破 a 的起點"})
        if node["k"] == "flat" and k == 1:
            a = abs(P(1) - P(0))
            out.append({"price": P(1) - d * FLAT_HARD * a, "side": side, "why": f"平台 b 段不能超過 a 的 {FLAT_HARD:g} 倍（破底穿頭的極限）"})
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
        elif kind in ("zz", "abc3"):
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
               ("zz", 1): SOFT_MAX["zb"], ("abc3", 1): SOFT_MAX["zb"], ("flat", 1): 1.0}.get(key)
        if cap is None:
            return None
        if key == ("imp", 3):
            hard = P(parent["subs"][0]["j"])                         # 第 4 段不能碰第 1 段終點
        elif key == ("diag", 3):
            hard = P(parent["subs"][1]["j"])                         # 楔形第 4 段不能過第 2 段終點
        elif key == ("flat", 1):
            hard = P(s) + dirc * FLAT_HARD * lp
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


YOUNG = 0.618            # B85 日 K 剛換成新的推動浪、還沒走出前一段修正的 0.618：先從前一段修正的起點數（她 10/29：45523 起的反彈先當 C-2）


def daily_seg(daily_cnt: Optional[dict]) -> Optional[tuple]:
    """日 K 主要劇本 → (起點 label, 下一點 label, 第一層性質 M／C, young)。
    B85：現在這一浪是推動（1、3、5、C）、前一浪是修正，而且現在這一浪還沒走出前一段的 YOUNG 倍 →
    新的一浪還沒證明自己，先從前一段修正的起點拆（反彈可能只是那段修正的 B／2；她 10/29 把 45523→47606 當 C-2-a）"""
    L = (daily_cnt or {}).get("labels") or []
    if len(L) < 2:
        return None
    role = daily_role(daily_cnt)
    if len(L) >= 3:
        p0, s0, s1 = L[-3], L[-2], L[-1]
        prev_role = daily_role({**daily_cnt, "current": str(s0.get("label") or "")})
        prev_len, cur_len = abs(s0["p"] - p0["p"]), abs(s1["p"] - s0["p"])
        if role == "M" and prev_role == "C" and prev_len > 0 and cur_len < YOUNG * prev_len:
            return p0, s0, "C", True
    return L[-2], L[-1], role, False


def _anchor(pts: list, daily_cnt: Optional[dict], daily_dates, tdate) -> tuple:
    """起點：日 K 主要劇本「現在這一浪」的起點（B85：新的一浪還太小 → 前一段的起點，見 daily_seg），對到分 K 同方向轉折：
    日期在「前一根日 K 那天～這根日 K 後 2 天」內最極端的（B85：以前只看前後 2 天，颱風休市 10/23 的 45523 併在 10/27 那根，對不到）；
    對不到 → 視窗內較早的極值。回傳 (索引, how, 第一層性質, young)"""
    n = len(pts)
    lo_i = max(0, n - 1 - MAX_PIV)
    lo_d = max(0, n - 1 - ANCHOR_LOOK)                   # B83 日 K 起點可以比較遠（轉折太多由 NEST_SEG 併段處理）
    seg = daily_seg(daily_cnt) if daily_dates is not None else None
    if seg:
        s0, s1, role, young = seg
        typ = "L" if s1["p"] > s0["p"] else "H"
        try:
            import datetime as _dt
            day = lambda k: _dt.date.fromisoformat(str(daily_dates[k])[:10])   # noqa: E731
            d_s = day(s0["i"])
            d_lo = min(d_s - _dt.timedelta(days=2), day(s0["i"] - 1) if s0["i"] >= 1 else d_s)
            d_hi = d_s + _dt.timedelta(days=2)
            cand = [k for k in range(lo_d, n - 2) if pts[k]["t"] == typ and d_lo <= tdate(pts[k]["i"]) <= d_hi]
        except Exception:  # noqa: BLE001
            cand = []
        if cand:
            k = (max if typ == "H" else min)(cand, key=lambda q: pts[q]["p"])
            return k, "daily", role, young
    win = range(lo_i, n - 2)
    if not win:
        return None, None, None, False
    kmax = max(win, key=lambda q: pts[q]["p"] if pts[q]["t"] == "H" else -1e18)
    kmin = min(win, key=lambda q: pts[q]["p"] if pts[q]["t"] == "L" else 1e18)
    return min(kmax, kmin), "window", None, False


def anchor_at(pts: list, t0: int, t1: int, typ: str, times) -> Optional[int]:
    """B80 15 分 K：起點對到上一層（60 分）那段的起點——時間在 [t0, t1) 內、同方向的轉折取最極端的；對不到 → None（B83：轉折多由 NEST_SEG 併段）"""
    n = len(pts)
    cand = [k for k in range(max(0, n - 1 - ANCHOR_LOOK), n - 2) if pts[k]["t"] == typ and t0 <= int(times[pts[k]["i"]]) < t1]
    if not cand:
        return None
    return (max if typ == "H" else min)(cand, key=lambda q: pts[q]["p"])


LIFE_R = 0.7             # B85 她 10/29 的生死臨界線上緣＝C-2-a 的 0.7（46,148）；下緣＝C-2-a 最後一段起漲點（46,006）
NEXT_OF = {"B": "C", "b": "c", "2": "3", "4": "5"}


def life_line(c: dict, seq: list, pts: list, d0: int, price: float, t_now: int, closes=None) -> Optional[dict]:
    """B85 她 10/29「生死臨界線」：主要數法是逆著大段的那段（B／2／4，她的 C-2）、而且它的第一段（a）已經走完 →
    a 的 0.7～a 最後一段的起漲點＝生死臨界線（60 分收盤要守住）；a 的 0.618＝跌破後反抽的關卡；
    a 高點之後走了幾根 K（她：橫台磨 8～12 根）、MACD 綠柱修到哪（她：指標修完、價格還在地板＝時間額度用完）"""
    X = (c["tree"].get("subs") or [None])[-1]
    if not X or not X.get("partial") or X["k"] == "atom" or len(X["subs"]) < 2:
        return None
    a = X["subs"][0]
    A0, A1 = seq[a["i"]], seq[a["j"]]
    La = abs(A1["p"] - A0["p"])
    if La <= 0:
        return None
    up = -d0                                             # X（逆勢那段）的方向
    lv = lambda r: A1["p"] - up * r * La                 # noqa: E731
    k0 = next((k for k, q in enumerate(pts) if q["i"] == A0["i"]), None)
    k1 = next((k for k, q in enumerate(pts) if q["i"] == A1["i"]), None)
    origin = None
    if k0 is not None and k1 is not None:
        origin = next((pts[k]["p"] for k in range(k1 - 1, k0, -1) if pts[k]["t"] == A0["t"]), None)
    edge = origin if origin is not None and (origin - lv(LIFE_R)) * up < 0 else lv(0.786)
    zone = sorted([lv(LIFE_R), edge])
    far = zone[0] if up > 0 else zone[1]                 # 往大段方向那一邊：越過＝生死線失守
    near = zone[1] if up > 0 else zone[0]
    if (price - A1["p"]) * up > 0:
        return None                                      # 已經過 a 的高點：X 段還在往上走，生死線用不到
    if k1 is not None and any((q["p"] - far) * up < 0 for q in pts[k1 + 1:-1]):
        return None                                      # 之前已經穿過臨界區又拉回來（例 10/21 的 B-b 46136）：這條線她不用
    name = c["path"][0] if c["path"] else "B"
    nxt = NEXT_OF.get(name, "下一")
    bars = t_now - A1["i"]
    dn, brk = ("跌破", "破") if up > 0 else ("漲過", "過")
    macd = ""
    if closes is not None and len(closes) > A1["i"] + 1:
        import numpy as _np
        cl = _np.asarray(closes, float)
        ema = lambda x, n: _np.array(list(__import__("itertools").accumulate(x, lambda e, v: v * (2 / (n + 1)) + e * (1 - 2 / (n + 1)))))   # noqa: E731
        dif = ema(cl, 12) - ema(cl, 26)
        osc = dif - ema(dif, 9)
        seg = osc[A1["i"]:]
        worst = float(seg.min() if up > 0 else seg.max())
        now = float(osc[-1])
        if worst * up < 0:
            fixed = abs(now) <= 0.25 * abs(worst) or now * up > 0
            macd = (f"；MACD {'綠' if up > 0 else '紅'}柱從 {worst:+.0f} {'翻正' if now * up > 0 else '縮到'} {now:+.0f}"
                    f"（{'指標修得差不多了' if fixed else '指標還在修'}）")
    ext_p = A0["p"]
    span = abs(seq[0]["p"] - ext_p)
    rs = (1.0, 1.618) if name == "2" else (0.618, 1.0)
    tg = "、".join(f"{r:g} 倍＝{_fmt(A1['p'] + d0 * r * span)}" for r in rs)
    t = (f"生死臨界線 {_fmt(zone[1] if up > 0 else zone[0])}～{_fmt(far)}（{name}-a {_fmt(A0['p'])}→{_fmt(A1['p'])} 的 {LIFE_R:g}＝{_fmt(lv(LIFE_R))}"
         + (f"、{name}-a 最後一段起漲點 {_fmt(origin)}" if origin is not None and edge == origin else f"、0.786＝{_fmt(lv(0.786))}")
         + f"）：60 分 K 收盤守住＝{name}（她的 C-2）還沒走完；帶量實體{dn}（或{dn}後反抽不過 0.618＝{_fmt(lv(0.618))}）"
         + f"＝{name} 結束、{nxt} 段{'主跌' if d0 < 0 else '主升'}開始，直接看{brk} {_fmt(ext_p)}。"
         + f"{name}-a 高點之後已經 {bars} 根 K（她：橫台磨 8～12 根才判）{macd}")
    plan = [f"版本 1（{name} 還在走＝她的 C-2）：60 分收盤守住 {_fmt(near)}～{_fmt(far)} → {name} 段後面還有一段{'反彈' if up > 0 else '回檔'}，或繼續橫盤磨時間",
            f"版本 2（{name} 結束、{nxt} 段{'主跌' if d0 < 0 else '主升'}＝她的 C-3）：60 分帶量實體{dn} {_fmt(far)}（或反抽不過 {_fmt(lv(0.618))}）"
            f" → 看{brk} {_fmt(ext_p)}；{nxt}＝前一段（{_fmt(seq[0]['p'])}→{_fmt(ext_p)}）的 {tg}（以 {_fmt(A1['p'])} 當 {name} 結束估）"]
    return {"name": name, "zone": [round(zone[0], 2), round(zone[1], 2)], "far": round(far, 2), "near": round(near, 2),
            "origin": origin, "r618": round(lv(0.618), 2), "r70": round(lv(LIFE_R), 2), "bars": bars,
            "broken": bool((price - far) * up < 0), "a": [A0["p"], A1["p"]], "t": t, "plan": plan}


# ── B86 她 11/1 的「源頭」兩種切組：日 K 是 A-B-C 的 C（或 1-2-3 的 3）時，60 分從修正的起點（50,265）整段拆 ─────────
SRC_TOP = 400            # 候選留前幾名再篩（她的版本分數不一定最好，要留得夠多才挑得到；只是切片，不多算）


def _src_view(c: dict, seq: list, times, kinds_of) -> dict:
    """一個源頭數法 → {path, text, marks:[{p, time, text}], segs:[(浪名, 起點, 終點, 型態)], cost}"""
    tree = c["tree"]
    labs = _sub_labels(c["top_kind"], 1)
    segs = []
    for m, sub in enumerate(tree["subs"]):
        a_, b_ = seq[sub["i"]]["p"], (seq[sub["j"]]["p"] if sub.get("j") is not None else seq[-1]["p"])
        segs.append({"lab": labs[m], "from": a_, "to": b_, "kind": KIND_NAME.get(sub["k"], ""), "k": sub["k"], "done": sub.get("j") is not None})
    marks = []
    for k, lab in sorted(c["labels"].items()):
        parts = lab.split("-")
        n = len(parts)
        while n > 1 and parts[n - 1] in ("5", "c"):          # 「B-a-c」＝B-a 這段的終點、「A-c」＝A 的終點
            n -= 1
        if n <= 2:                                           # 第一、二層就好（她的圖：大段＋子浪）
            q = seq[k]
            marks.append({"p": q["p"], "time": int(times[q["i"]]), "text": "-".join(parts[:n])})
    return {"path": c["path_str"], "top_kind": c["top_kind"], "kind": KIND_NAME.get(c["top_kind"], ""), "text": c["text"],
            "cost": round(c["cost"], 4), "segs": segs, "marks": marks}


def source_cut(pts: list, daily_cnt: Optional[dict], daily_dates, tdate, times, price: float) -> Optional[dict]:
    """她 11/1「回到最源頭的思路」：日 K 這段修正的起點（50,265）到現在，60 分怎麼切組——
    第一種（三段式）：A 走三波（50,265→48,413→49,594→46,107）、B 破底穿頭平台（→47,555→45,523→47,607）、C 走五波（47,607 起）
    第二種（五段式，威脅）：第 1 段五波（50,265→45,523）、第 2 段（→47,607）、第 3 段（47,607 起，主跌才剛開始）
    兩種的第二段都要結束在日 K 的 B（47,607）。三段式優先挑「B 破底穿頭」那種（她點名的型態），沒有才用分數最好的"""
    L = (daily_cnt or {}).get("labels") or []
    kind, cur = (daily_cnt or {}).get("kind"), str((daily_cnt or {}).get("current") or "")
    if len(L) < 4 or not ((kind == "correction" and cur == "C") or (kind == "impulse" and cur == "3")):
        return None
    k0 = _anchor(pts, {**daily_cnt, "labels": [L[-4], L[-3]], "current": "A"}, daily_dates, tdate)
    kB = _anchor(pts, {**daily_cnt, "labels": [L[-2], L[-1]], "current": "C"}, daily_dates, tdate)
    if k0[0] is None or kB[0] is None or k0[1] != "daily" or kB[1] != "daily" or kB[0] <= k0[0]:
        return None
    seq = pts[k0[0]:]
    pB = pts[kB[0]]
    while len(seq) - 1 > NEST_SEG:
        nxt = drop_smallest(seq)
        if nxt is None:
            return None
        seq = nxt
    jB = next((k for k, q in enumerate(seq) if q["i"] == pB["i"]), None)
    if jB is None:
        return None
    d0 = 1 if seq[0]["t"] == "L" else -1
    # 三段式：A 是三波（鋸齒／平台）、C 進行中；五段式：第 1 段是五波、第 3 段進行中（日 K 這一浪還在走）
    c3 = [c for c in parse(seq, 0, top_k=SRC_TOP, only_role="C", extra_top=("abc3",), keep_first=True)
          if len(c["tree"]["subs"]) == 3 and c["tree"]["subs"][1].get("j") == jB and c["tree"]["subs"][0]["k"] in ("zz", "flat")]
    c5 = [c for c in parse(seq, 0, top_k=SRC_TOP, only_role="M", keep_first=True)
          if c["top_kind"] == "imp" and len(c["tree"]["subs"]) == 3 and c["tree"]["subs"][1].get("j") == jB
          and c["tree"]["subs"][0]["k"] == "imp"]

    def breaks(c):                                           # B 是平台、而且 b 段刺穿 A 的終點（破底穿頭）
        B = c["tree"]["subs"][1]
        if B["k"] != "flat" or len(B["subs"]) < 2:
            return False
        a_end = seq[c["tree"]["subs"][0]["j"]]["p"]
        return (seq[B["subs"][1]["j"]]["p"] - a_end) * d0 > 0     # 下跌（d0＝−1）：b 比 A 的低點更低
    pick3 = min([c for c in c3 if breaks(c)] or c3, key=lambda c: c["cost"], default=None)
    pick5 = min(c5, key=lambda c: c["cost"], default=None)
    if not pick3 and not pick5:
        return None
    out = {"from": {"p": seq[0]["p"], "time": int(times[seq[0]["i"]])}, "b_end": pB["p"]}
    wd = "跌" if d0 < 0 else "漲"
    if pick3:
        v = _src_view(pick3, seq, times, None)
        A, B = v["segs"][0], v["segs"][1]
        la = abs(A["to"] - A["from"])
        v["targets"] = [{"label": f"C＝A 等幅（{_fmt(A['from'])}→{_fmt(A['to'])} 共 {la:,.0f} 點）", "price": round(B["to"] + d0 * la, 2)},
                        {"label": "C＝1.618 倍 A", "price": round(B["to"] + d0 * 1.618 * la, 2)}]
        v["bpn"] = breaks(pick3)
        v["desc"] = (f"A＝{_fmt(A['from'])}→{_fmt(A['to'])}（{A['kind']}）、B＝{_fmt(B['from'])}→{_fmt(B['to'])}（{B['kind']}"
                     + ("，破底穿頭" if v["bpn"] else "") + f"）、C＝{_fmt(B['to'])} 起{wd}（要走五波）")
        out["three"] = v
    if pick5:
        v = _src_view(pick5, seq, times, None)
        S1, S2 = v["segs"][0], v["segs"][1]
        l1 = abs(S1["to"] - S1["from"])
        v["targets"] = [{"label": f"第 3 段＝1 倍第 1 段（{l1:,.0f} 點）", "price": round(S2["to"] + d0 * l1, 2)},
                        {"label": "第 3 段＝1.618 倍第 1 段", "price": round(S2["to"] + d0 * 1.618 * l1, 2)}]
        v["desc"] = (f"第 1 段＝{_fmt(S1['from'])}→{_fmt(S1['to'])}（五波）、第 2 段＝→{_fmt(S2['to'])}、"
                     f"第 3 段＝{_fmt(S2['to'])} 起主{wd}（才剛開始，裡面也要走五小段）")
        lows = [m["p"] for m in v["marks"] if m["text"] == "3-1"]
        if lows:                                             # 3-1 走完 → 3-2 是弱勢反彈：常見回 0.5～0.618，過了 3-1 的起點這個版本就作廢
            l31 = abs(lows[0] - S2["to"])
            v["rebound"] = {"p50": round(lows[0] - d0 * 0.5 * l31, 2), "p618": round(lows[0] - d0 * 0.618 * l31, 2), "kill": S2["to"],
                            "low": lows[0]}
        out["five"] = v
    return out


def two_ways(c1: dict, c2: Optional[dict], seq: list, d0: int, price: float, fib: dict, src: Optional[dict] = None) -> Optional[dict]:
    """B87／B88 她 11/2 的「兩種」（@fanny55520 台指期 60 分，47,607→44,052 之後）：
    第一種＝第 1 段還沒走完（44,052 只是第 3 小段的終點，她的 3-1-4／3-1-5）；第二種＝第 1 段已走完（她的 3-2／3-3）。
    分三個階段（極值之後走了幾段）：
    - up1（反彈第一段進行中，B87 她 11/2 中午）：第一種標準 45,332～45,410、天花板 45,597，第 5 小段最可能 43,974～43,851、
      標準 43,704～43,449、失敗型 44,417～；第二種走法 A（b 守 45,039、極限 44,804～44,881，c → 45,830～46,126）、走法 B（44,700↔45,350）
    - pull（反彈高點之後回落中，B88 她 11/2 晚上 23:00：45,487→44,832）：第一種甲＝4-b 落底還有小 c（c 目標階梯 T1 45,364～45,410、
      T2 45,487～45,583／45,597＝4-c 極限區、T3 45,830～45,891＝升格 3-2-c）；第一種乙＝啟動 1-5，5-2 反抽測 45,146～45,173（死貓跳）；
      決戰關卡＝45,146～45,173（b 的 0.5 附近），帶量實體紅 K 站穩才是真 c，移動停利 45,080（0.382）→ 45,145～45,160
    - up2（回落之後再反彈＝小 c 或 5-2）：同 pull 的價位，標出已經走到哪
    c1＝parser 的第一種候選（lab1 標出第 1、2、3 小段終點）、c2＝第二種候選（極值＝第 1 段終點）。價位都用 seq 的轉折即時算。"""
    ends = {v: k for k, v in c1["lab1"].items()}
    if not {"1", "2", "3"} <= set(ends):
        return None
    k1, k2, k3 = ends["1"], ends["2"], ends["3"]
    n_after = len(seq) - 1 - k3
    if n_after not in (1, 2, 3):
        return None
    phase = {1: "up1", 2: "pull", 3: "up2"}[n_after]
    a_p, e_p = seq[0]["p"], seq[k3]["p"]
    tent = seq[-1]["p"]
    dir_now = d0 if phase == "pull" else -d0
    cur = tent if (tent - price) * dir_now >= 0 else price             # 進行中那段到現在的極值
    H = cur if phase == "up1" else seq[k3 + 1]["p"]                    # 極值之後第一段反彈的終點
    a_len = abs(H - e_p)
    if a_len <= 0:
        return None
    w1 = abs(seq[k1]["p"] - a_p)                                       # 第 1 小段長度
    w3 = abs(seq[k2]["p"] - e_p)                                       # 第 3 小段長度
    L1 = abs(a_p - e_p)                                                # 第 1 段（起點→極值）長度
    beyond = lambda v, ref: (v - ref) * -d0 > 0                        # noqa: E731  v 在 ref 的反彈方向那一邊
    srt = lambda xs: sorted(xs, key=lambda v: -d0 * v)                 # noqa: E731  反彈方向由近到遠
    inner = [seq[k]["p"] for k in range(k2 + 1, k3) if seq[k]["t"] == seq[0]["t"]]
    ceil_ = inner[-1] if inner else e_p - d0 * 0.618 * w3              # 第 3 小段裡前一個小反彈高點（小 4）；沒有就用 0.618
    std = sorted([e_p - d0 * 0.5 * w3, fib[0.382]])
    hard = seq[k1]["p"]                                                # 第 4 段不碰第 1 段終點（楔形放寬到第 2 段終點）
    wd, up, dn = ("跌", "反彈", "回落") if d0 < 0 else ("漲", "回檔", "反彈")
    v_up, v_dn = ("漲過", "跌破") if d0 < 0 else ("跌破", "漲過")
    hl = "高" if d0 < 0 else "低"
    # 第一種的第 5 小段：從第 4 小段的終點（up1＝反彈到現在的極值；之後＝H）往下量
    tg = [("5＝0→3 的 0.382", H + d0 * 0.382 * L1, "main"), ("5＝1 倍第 1 小段", H + d0 * w1, "main"),
          ("5＝0.618 倍第 1 小段", H + d0 * 0.618 * w1, "main"), ("第 4 小段的 1.272 倍外延", H + d0 * 1.272 * a_len, "std")]
    t3 = (src or {}).get("three") or {}
    if t3.get("targets"):
        tg.append((t3["targets"][0]["label"].split("（")[0] + "（源頭三段式）", float(t3["targets"][0]["price"]), "std"))
    targets = []
    for lab, v, g in tg:
        g = g if (e_p - v) * -d0 > 0 or abs(v - e_p) < 1 else "fail"    # 沒有破 e_p＝失敗型（雙底／雙頂）
        targets.append({"label": lab, "price": round(v, 2), "grp": g})
    targets.sort(key=lambda t: -d0 * t["price"], reverse=True)          # 離現價近的先列
    grp = lambda g: "～".join(_fmt(t["price"]) for t in targets if t["grp"] == g)   # noqa: E731
    five_txt = "；".join(x for x in (f"最可能 {grp('main')}" if grp("main") else "", f"標準 {grp('std')}" if grp("std") else "",
                                     f"失敗型（不破 {_fmt(e_p)}、雙{'底' if d0 < 0 else '頂'}）{grp('fail')}" if grp("fail") else "") if x)
    # 她的浪名（源頭第二種切組把 47,607 起算成第 3 段時才對得上：第一種＝3-1-x、第二種＝3-x）
    pre = "3-" if str(((src or {}).get("five") or {}).get("path", "")).startswith("3") and (src or {}).get("b_end") == a_p else None
    p1, p2 = c1["path_str"], (c2 or {}).get("path_str") or "2"
    her1, her2 = (pre + "1-" + p1, pre + p2) if pre else (None, None)
    hs = lambda h: f"＝她的 {h}" if h else ""                          # noqa: E731
    ws = {"lo": round(ceil_, 2), "hi": round(ceil_, 2), "far": round(ceil_, 2),
          "why": f"第一種（第 4 小段）最多到第 3 小段裡前一個小{up}高點", "lv": [(round(ceil_, 2), "前一個小 4"), (round(hard, 2), "硬規則")],
          "brk": [], "path": p1}
    out = {"phase": phase, "R": round(H, 2), "low": e_p, "watershed": ws, "ceil_hit": not beyond(ceil_, cur if phase != "pull" else H)}
    one = {"path": p1, "her": her1, "std": [round(std[0], 2), round(std[1], 2)], "ceil": round(ceil_, 2), "hard": round(hard, 2),
           "targets": targets}
    two = {"path": p2, "her": her2}
    if phase == "up1":
        A = {"a": [e_p, round(H, 2)], "b_strict": round(H + d0 * 0.236 * a_len, 2), "b_ext": round(H + d0 * 0.382 * a_len, 2),
             "c": [{"price": v, "label": t, "hit": not beyond(v, H)} for v, t in
                   sorted({round(v, 2): t for v, t in [(fib[0.382], "整段 0.382"), (ceil_, "第一種的天花板"), (fib[0.5], "0.5"),
                                                       (hard, "第 1 小段終點"), (fib[0.618], "0.618 極限")]}.items(), key=lambda x: -d0 * x[0])]}
        B = {"lo": round(H + d0 * 0.5 * a_len, 2), "hi": round(H, 2)}
        one["text"] = (f"第一種（第 1 段還沒走完）：{_fmt(e_p)} 只是第 3 小段的終點，這段{up}＝第 4 小段{('（她的 ' + her1 + '）') if her1 else ''}——標準 "
                       f"{_fmt(std[0])}～{_fmt(std[1])}（第 3 小段 0.5～整段 0.382）、最多到 {_fmt(ceil_)}（第 3 小段裡前一個小{up}高點），"
                       f"之後第 5 小段再{wd}破 {_fmt(e_p)}；{v_up} {_fmt(hard)}（第 1 小段終點）這個數法就不成立")
        two.update(A=A, B=B, text=f"第二種（第 1 段已走完）：{_fmt(a_p)}→{_fmt(e_p)} 五小段走完，這段{up}＝第 2 段{('（她的 ' + her2 + '）') if her2 else ''}，"
                                  f"之後還有第 3 段主{wd}")
        out["judge"] = [f"{'站穩' if d0 < 0 else '跌破'} {_fmt(ceil_)}＝第一種不成立 → 第二種走法 A（c 段往 {_fmt(fib[0.5])}～{_fmt(hard)}）",
                        f"{v_dn} {_fmt(A['b_ext'])}（a 的 0.382）＝走法 A 的 b 太深 → 走法 B（時間型）或第一種",
                        f"{v_dn} {_fmt(e_p)}＝第一種的第 5 小段（或第二種失敗）"]
        c_next = [c for c in A["c"] if not c["hit"]]
        out["plan"] = [f"版本 1（第一種 {p1}{hs(her1)}）：{_fmt(std[0])}～{_fmt(std[1])}、最多 {_fmt(ceil_)} 被{'壓回' if d0 < 0 else '拉回'} → "
                       f"第 5 小段破 {_fmt(e_p)}：{five_txt}",
                       f"版本 2（第二種 {p2}{hs(her2)}）：走法 A（標準 a-b-c）a＝{_fmt(e_p)}→{_fmt(H)}（到現在的{hl}點），"
                       f"b 守 {_fmt(A['b_strict'])}（a 的 0.236）、極限 {_fmt(A['b_ext'])}（0.382），c 依序{'站上' if d0 < 0 else '跌破'} "
                       + " → ".join(f"{_fmt(c['price'])}（{c['label']}）" for c in c_next)
                       + f"；走法 B（時間型、偏弱）在 {_fmt(min(B['lo'], B['hi']))}～{_fmt(max(B['lo'], B['hi']))} 來回磨 2～3 天，之後照樣第 3 段主{wd}"]
        out.update(one=one, two=two)
        return out
    # ── pull／up2：H 之後回落（L）、可能再反彈（小 c 或 5-2） ──
    L = cur if phase == "pull" else seq[k3 + 2]["p"]
    R2 = cur if phase == "up2" else None
    bl = abs(H - L)
    if bl <= 0:
        return None
    at = lambda r: L - d0 * r * bl                                     # noqa: E731  從 L 往反彈方向走 b 的 r 倍
    band = srt([at(0.48), at(0.52)])                                   # 決戰關卡：b 的 0.5 附近（她 45,146～45,173）
    reach = lambda v: R2 is not None and not beyond(v, R2)             # noqa: E731  小 c／5-2 已經走到
    ladder = [("T1", srt([at(0.81), fib[0.382]]), "b 的 0.81～整段 0.382"),
              ("T2", srt([H, ceil_]), "前高～第一種的天花板（4-c 極限區）"),
              ("T3", srt([fib[0.5], at(1.618)]), f"整段 0.5～b 的 1.618 倍（升格第二種 2-c{hs(pre + '2-c' if pre else None)}）")]
    c_lad = [{"t": t, "lo": round(xs[0], 2), "hi": round(xs[-1], 2), "label": lab, "hit": reach(xs[0])} for t, xs, lab in ladder]
    down3 = [round(H + d0 * L1, 2), round(H + d0 * 1.618 * L1, 2)]    # 第二種：2 在 H 結束 → 第 3 段＝1、1.618 倍第 1 段
    flat = [round(H + d0 * 0.9 * a_len, 2), e_p]                       # 第二種：2 還沒走完（平台 b 回 0.9～1 倍 a）
    gate = {"lo": round(band[0], 2), "hi": round(band[1], 2), "mid": round(at(0.5), 2), "hit": reach(band[1]),
            "stop": [round(at(0.382), 2), round(at(0.5), 2)]}
    fb = lambda: f"{_fmt(band[0])}～{_fmt(band[1])}"                   # noqa: E731
    one.update(b=[round(H, 2), round(L, 2)], c=c_lad, gate=gate,
               text=f"第一種（第 1 段還沒走完）：{_fmt(e_p)} 只是第 3 小段的終點、{_fmt(e_p)}→{_fmt(H)}＝第 4 小段（的 a）——還在第 4 小段的話，"
                    f"{_fmt(H)}→{_fmt(L)}＝4-b，落底後還有小 c（最多到 {_fmt(ceil_)}）；第 4 小段已經在 {_fmt(H)} 結束的話，第 5 小段啟動、"
                    f"再{wd}破 {_fmt(e_p)}")
    two.update(down=down3, flat=flat,
               text=f"第二種（第 1 段已走完）：{_fmt(e_p)}→{_fmt(H)}＝第 2 段{up}；2 在 {_fmt(H)} 結束（反彈偏弱＝走法 B 的預告）→ 第 3 段主{wd}；"
                    f"2 還沒走完（平台 b）先回 {_fmt(flat[0])}～{_fmt(flat[1])} 再 c")
    k_sol = "紅" if d0 < 0 else "黑"
    out["judge"] = [f"帶量實體{k_sol} K {'站穩' if d0 < 0 else '跌破'} {_fmt(band[1])}（決戰關卡 {fb()}：b 的 0.5 附近）→ 第一種甲：4-b 落底、小 c 往 T1 "
                    f"{_fmt(c_lad[0]['lo'])}～{_fmt(c_lad[0]['hi'])}；卡在 {fb()} → 第一種乙：第 5 小段的 5-2 死貓跳",
                    f"小 c {v_up} {_fmt(ceil_)}（4-c 極限）、站上 T3 {_fmt(c_lad[2]['lo'])}＝升格第二種（2-c{hs(pre + '2-c' if pre else None)}）",
                    f"{v_dn} {_fmt(e_p)}＝第一種乙的第 5 小段（看 {grp('main') or grp('std')}）或第二種第 3 段主{wd}（看 {_fmt(down3[0])}、{_fmt(down3[1])}）"]
    if phase == "pull":
        out["judge"].append(f"{v_up} {_fmt(H)}＝{up}還沒走完（回到第 4 小段／第 2 段進行中）")
    tl_c = " → ".join(f"{c['t']} {_fmt(c['lo'])}～{_fmt(c['hi'])}{'✅' if c['hit'] else ''}" for c in c_lad) + "（T2＝4-c 極限區、T3＝升格第二種）"
    stop_t = (f"移動停利推上 {_fmt(gate['stop'][0])}（b 的 0.382）、再推到 {_fmt(band[0])}～{_fmt(gate['stop'][1])}")
    down_t = f"第 3 段主{wd} 1 倍第 1 段 {_fmt(down3[0])}、1.618 倍 {_fmt(down3[1])}"
    if phase == "pull":
        out["plan"] = [f"版本 1（第一種甲：{p1}{hs(her1)}，4-b 落底還有小 c）：防守放 {_fmt(L)} {'下方' if d0 < 0 else '上方'}；帶量站穩 {_fmt(band[1])} 後"
                       f"{stop_t}；小 c 目標 {tl_c}",
                       f"版本 2（第一種乙：{_fmt(H)} 已是第 4 小段終點、第 5 小段啟動{hs(pre + '1-5' if pre else None)}）：5-2 反抽到 {fb()} 就卡住（死貓跳）"
                       f" → 第 5 小段破 {_fmt(e_p)}：{five_txt}",
                       f"版本 3（第二種：{p2}{hs(her2)}）：2 在 {_fmt(H)} 結束 → {down_t}；2 還沒走完（平台 b）先回 {_fmt(flat[0])}～{_fmt(flat[1])} 再 c"]
    else:
        out["plan"] = [f"版本 1（第一種甲：{p1}{hs(her1)}，4-b 已在 {_fmt(L)} 落底、小 c 進行中）：防守 {_fmt(L)} {'下方' if d0 < 0 else '上方'}；"
                       f"{'已站上' if gate['hit'] else '帶量站穩'} {_fmt(band[1])}{'，' if gate['hit'] else ' 後'}{stop_t}；小 c 目標 {tl_c}",
                       f"版本 2（第一種乙：{_fmt(H)} 已是第 4 小段終點、這段＝5-2 反抽{hs(pre + '1-5-2' if pre else None)}）：到 {fb()} 就卡住（死貓跳）"
                       f" → 第 5 小段破 {_fmt(e_p)}：{five_txt}",
                       f"版本 3（第二種：{p2}{hs(her2)}）：2 還沒走完、這段＝2-c（走法 A 的 c）→ 站上 T3 {_fmt(c_lad[2]['lo'])} 確認；"
                       f"2 已在 {_fmt(H)} 結束的話這段只是反抽 → {down_t}"]
    out["gates"] = [{"k": "決戰關卡", "price": round(band[1], 2), "ok": gate["hit"],
                     "t": f"決戰關卡 {fb()}（{_fmt(H)}→{_fmt(L)} 的 0.5 附近）→ 帶量實體{k_sol} K {'站穩' if d0 < 0 else '跌破'}＝第一種甲（4-b 落底、小 c 往 "
                          f"{_fmt(c_lad[0]['lo'])}）；卡住＝第一種乙（第 5 小段的 5-2 死貓跳）"},
                    {"k": "破底" if d0 < 0 else "破頂", "price": e_p, "ok": False,
                     "t": f"{v_dn} {_fmt(e_p)}（前{'低' if d0 < 0 else '高'}）→ 第一種乙的第 5 小段（{grp('main') or grp('std')}）或第二種第 3 段主{wd}"
                          f"（{_fmt(down3[0])}）"}]
    out.update(one=one, two=two)
    return out


def build(an: dict, times: list, price: float, tfn: str = "60 分", daily_cnt: Optional[dict] = None,
          daily_dates=None, tdate=None, tlabel=None, parent_seg: Optional[dict] = None, closes=None) -> dict:
    """分 K 的 analyze 結果 → 多層浪名＋關卡＋操作紀律。closes（B85，可省）：分 K 收盤價，算 MACD 綠柱修復
    an：engine.analyze（pivots、tentative）；times：K 棒時間；tdate(i)→date、tlabel(i)→字串（分 K 第 i 根）
    parent_seg（B80 15 分 K）：{time, t0, t1, typ, name}＝上一層（60 分）主要數法第一層進行中那段的起點，對得到就從那裡拆"""
    piv = list(an.get("pivots") or [])
    tent = an.get("tentative")
    pts = piv + ([tent] if tent else [])
    if len(pts) < 4:
        return {"ok": False, "note": f"{tfn} K 轉折還不夠"}
    tdate = tdate or (lambda i: None)
    tlabel = tlabel or (lambda i: str(i))
    anchor, how, role, young = None, None, None, False
    if parent_seg:
        anchor = anchor_at(pts, parent_seg["t0"], parent_seg["t1"], parent_seg["typ"], times)
        how = "parent" if anchor is not None else None
        role = parent_seg.get("role") if anchor is not None else None
    if anchor is None:
        anchor, how, role, young = _anchor(pts, daily_cnt, daily_dates, tdate)
    if anchor is None:
        return {"ok": False, "note": f"{tfn} K 找不到起點"}
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
    # B87 她 11/2 的「兩種」：極值之後（反彈中、反彈完回落、再反彈）主要是第二種（極值＝第 1 段終點：2、2-b、3…＝她的 3-2、3-3）
    #     或第一種（極值＝第 3 小段終點：4、4-b、4-c…＝她的 3-1-4）時，另一個一定拿對面那種比——B83 換進來的「1-2」跟「2」
    #     反彈的是同一段（只差級數名稱），不是真的另一種走法 → 往後挪成第三個（B88：反彈完回落時也一樣，她 11/2 晚上的 1-4-b／1-5）
    pair = None
    kind_ = lambda c: {"1": 2, "3": 1}.get(c["lab1"].get(ext_k)) if c["top_kind"] in ("imp", "diag") else None   # noqa: E731
    if prim and 1 <= len(seq) - 1 - ext_k <= 3 and kind_(prim):
        k_p = kind_(prim)
        other = next((c for c in cands if kind_(c) and kind_(c) != k_p and abs(c["adj"] - prim["adj"]) <= ALT_GAP), None)
        if other is not None:
            if alt is not other:
                alt, third = other, (alt if alt is not None else third)
            pair = (prim, other) if k_p == 1 else (other, prim)        # (第一種, 第二種)
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
    life = life_line(prim, seq, pts, d0, price, len(times) - 1, closes) if prim and not _with_trend(prim, d0) else None
    try:                                                     # B86 源頭兩種切組（她 11/1）：只在 60 分算（15／30 分從上一層接）
        src = source_cut(pts, daily_cnt, daily_dates, tdate, times, price) if tfn == "60 分" and not parent_seg else None
    except Exception:       # noqa: BLE001
        src = None
    two = two_ways(pair[0], pair[1], seq, d0, price, fib, src) if pair is not None else None
    # 關卡（她的寫法）：反向（逆著起點那一大段）走時 → 分水嶺（B83）、前提趨勢線、0.382、前高頸線＋0.5、0.618＋第 1 段低點區、失敗
    up_word, dn_word = ("反彈", "下跌") if d0 < 0 else ("回檔", "上漲")
    gates = []
    watershed = None
    if cur_dir != d0:
        # B83 分水嶺（她 10/28「關鍵分水嶺 46,969～47,120：C-3-2 極限區 vs 下降趨勢線轉浪口」）：
        # 「大段還在走」的數法裡，這段逆勢走最多到哪（還沒被價格淘汰的、排最前面的那個）＋趨勢線
        for c, x in ((prim, P), (alt, A), (third, T3)):
            if two or not (c and x and x["with_trend"]):
                continue
            z = limit_zone(c, seq, d0)
            if z and (z["far"] - price) * -d0 > 0:
                watershed = dict(z, path=x["path"])
                break
        if two:                                              # B87 她 11/2：兩種的分界＝第一種（第 4 小段）的天花板
            o_ = two["one"]
            watershed = dict(two["watershed"])
            gates.append({"k": "分水嶺", "price": o_["ceil"], "ok": beyond(o_["ceil"]) and ev["trend"],
                          "t": f"關鍵分水嶺 {_fmt(o_['ceil'])}（{'她 11/2 ' if o_['her'] else ''}兩種的分界）：第一種＝{o_['path']}（第 1 段還沒走完）這段{up_word}只是第 4 小段，"
                               f"標準 {_fmt(o_['std'][0])}～{_fmt(o_['std'][1])}、最多到第 3 小段裡前一個小{up_word}高點 {_fmt(o_['ceil'])} → "
                               f"在這裡被壓回＝還有第 5 小段{dn_word}破 {_fmt(e_p)}；{'站穩' if d0 < 0 else '跌破'} {_fmt(o_['ceil'])}＝第二種"
                               f"（{two['two']['path']}：第 1 段已走完、第 2 段{up_word}確認）；{'漲過' if d0 < 0 else '跌破'} {_fmt(o_['hard'])}（第 1 小段終點）第一種就不成立"})
            if two.get("gates"):                             # B88 小 c／5-2 進行中：決戰關卡走到哪
                gates.extend(g for g in two["gates"] if g["k"] == "決戰關卡")
        elif watershed:
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
        if two:                                                          # B87 第一種的第 5 小段（她 11/2：最可能那組）
            fifth = [t for t in two["one"]["targets"] if t["grp"] == "main"][:2]
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
                      "t": fail + f"{'跌破' if d0 < 0 else '漲過'} {_fmt(e_p)}（{'新低' if d0 < 0 else '新高'}）→ "
                           + (f"C 段主{dn_word[-1]}（她的 C-3）" if life else f"第 5 段{dn_word}")})
    else:
        if two and two.get("gates"):                         # B88 她 11/2 晚上：反彈完回落時的決戰關卡、破底
            gates.extend(two["gates"])
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
        if watershed and not life and not two:           # B83 她 10/28 的兩個版本＋盤中怎麼確認
            brk = [(v, t) for v, t in watershed["brk"] if (price - v) * -d0 > 0]
            s1 = (f"版本 1（維持原架構 {watershed['path']}）：{_fmt(watershed['far'])} {'開高衝不過' if d0 < 0 else '開低跌不破'}、在分水嶺前被"
                  f"{'壓回' if d0 < 0 else '拉回'}" + "".join(f" → {'跌破' if d0 < 0 else '漲過'} {_fmt(v)}（{t}）"
                                                       + ("先造成脈動斷裂" if n_ == 0 else f"確認重啟{dn_word}") for n_, (v, t) in enumerate(brk)))
            plan.insert(1, s1)
            ct = next((x for x in (P, A, T3) if x and not x["with_trend"]), None)
            # 目標只列分水嶺「外面」的關卡（B87：分水嶺 46,846 在 0.382～0.618 外面時，以前會寫成「站穩 46,846 → 目標 45,410…」）
            far_tg = [v for v, _, _ in ladder if (v - watershed["far"]) * -d0 > 0][-3:]
            hard_ = next((v for v, t in watershed["lv"] if t == "硬規則"), None)
            tg = ("目標 " + "、".join(_fmt(v) for v in far_tg)) if far_tg else \
                (f"下一個看 {_fmt(hard_)}（硬規則，{'漲過' if d0 < 0 else '跌破'}＝更大一級換數法）" if hard_ is not None else "")
            plan.insert(2, f"版本 2（級數轉浪{(' ' + ct['path']) if ct else ''}）：越過{'下降' if d0 < 0 else '上升'}趨勢線並站穩 {_fmt(watershed['far'])}"
                           + (f" → {tg}" if tg else ""))
        elif two:                                        # B87／B88 她 11/2 的兩種（版本 1／2〔／3〕）
            plan[1:1] = two["plan"]
    else:
        plan.append(f"順著大段{dn_word}中：{up_word}沒過前一個{'反彈高點' if d0 < 0 else '回檔低點'}就照原方向，別逆勢{'接多' if d0 < 0 else '放空'}")
        if two:                                          # B88 反彈完回落：她 11/2 晚上的三個版本
            plan[1:1] = two["plan"]
    if life:                                             # B85 她 10/29：B（C-2）走完第一段以後的兩個版本
        gates.insert(0, {"k": "生死線", "price": life["far"], "ok": life["broken"], "t": life["t"]})
        if not two:                                      # B88 有「兩種」時版本用她 11/2 的（生死線還是列在關卡）
            plan[1:1] = life["plan"]
    if P and P["path"].endswith(("c", "C", "5")):
        st_ = next((r for r in P["rules"] if "這一小段的起點" in r["why"]), None)
        if st_:
            plan.append(f"最後一段（{P['path'].split('-')[-1]}）進行中：起點 {_fmt(st_['price'])} 是多空線，{'跌破' if cur_dir > 0 else '漲過'}就是數法錯了，先出場")
    plan.append("進場等第一根回測不破前低／前高（她：第一根壓下來上車），防守放在多空線")
    plan.append("走一口留一口：第一個目標到了先出一半，剩下的防守拉到成本或多空線")
    plan.append("壓回失速、加速往反方向走＝盤中立刻換數法（她：一但壓回是失速的就轉浪）")
    return {"ok": True, "tf": tfn, "anchor": {"i": seq[0]["i"], "time": int(times[seq[0]["i"]]), "p": a_p, "how": how,
                                             "label": tlabel(seq[0]["i"]), "young": young},
            "extreme": {"p": e_p, "label": tlabel(seq[ext_k]["i"])}, "dir": d0, "cur_dir": cur_dir,
            "daily_role": role, "fib": {str(k): round(v, 2) for k, v in fib.items()},
            "trendline": None if not tl else {"from": {**tl["from"], "time": int(times[tl["from"]["i"]])},
                                              "now": round(tl["now"], 2), "time_now": int(times[t_now]),
                                              "to": {**tl["to"], "time": int(times[tl["to"]["i"]])}},
            "evidence": ev, "primary": P, "alternate": A, "third": T3, "gates": gates, "plan": plan,
            "watershed": watershed, "life": life, "n_seg": len(seq) - 1, "merged": n_raw - (len(seq) - 1),
            "source": src, "two": two}


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
    if depth >= 1 and len(L) >= 4:
        # B86 已經超過這一段的起點（11/1 日 K：45,523→47,607 回檔 111%）→ 這段當母尺失效：前一段 L[-4]→L[-3] 跟現在同方向，
        #     現在是它的延伸（A-B-C 的 C／1-2-3 的 3），改列「延伸段＝前一段的 0.618／1／1.618 倍」
        p0, a1 = L[-4], L[-3]
        la = abs(a1["p"] - p0["p"])
        ext = {r: s1["p"] - pd_ * r * la for r in (0.618, 1.0, 1.618)}
        lines = [f"定位 A（主要）：已經{brk}鐵律底線 {_fmt(s0['p'])}（{_fmt(s0['p'])}→{_fmt(s1['p'])} 這段{word} {depth:.0%}），"
                 f"這段當母尺已經失效 → 現在是 {_fmt(p0['p'])}→{_fmt(a1['p'])} 那段的延伸（{d(p0)}～{d(a1)}，{la:,.0f} 點）",
                 "延伸段（從 " + _fmt(s1["p"]) + " 起）＝前一段的 " + "、".join(f"{r:g} 倍 {_fmt(v)}" for r, v in ext.items())]
        if alt:
            lines.append(f"定位 B：{alt.get('text')}" + (f"；{'跌破' if alt.get('invalid_side') == 'below' else '漲過'} {_fmt(alt['invalid'])} 這個版本就作廢"
                                                        if alt.get("invalid") is not None else ""))
        return {"tf": tfn, "lines": lines, "ruler": [p0["p"], a1["p"]], "levels": {f"x{r:g}": round(v, 2) for r, v in ext.items()},
                "iron": s1["p"], "depth": round(depth, 4), "passed": [f"x{r:g}" for r, v in ext.items() if (v - price) * -pd_ <= 0],
                "extension": True}
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


# ── B86 她 11/1「50265 起的下跌三種日線定位」：用週 K 轉折找全波段起點、第 (3) 浪、第 (4) 浪 ──────────────────────
def big_picture(piv: list, price: float, mid_primary: Optional[dict] = None) -> Optional[dict]:
    """piv：週 K 轉折（舊→新，{p, t, date}）。最新高點 H（50,265）之後在回檔時，列她的三種定位：
    1. 全波段（G0→H，17,016→50,265）走完、進行更上層大 A 浪：全波段 0.382（37,564）是總修正目標
    2. 第四大波還沒走完（只修正第 (3) 浪 31,740→49,240）：4-C／Y 浪看第 (3) 浪的 0.382～0.5（42,555～40,490），守住第 (4) 浪低點（39,442）
    3. 49,240 早已結束全波段、H 是 B 波假突破 → 全波段 C 浪：全波段 0.382～0.5（37,564～33,641）
    找法：G0＝H 之前最低的低點；H3＝H 之前最高的高點（49,240）；W4＝H3～H 之間最低（39,442）；
    第 (3) 浪起點＝G0～H3 之間「漲最多的那一段」的起點（31,740→46,994 那段的 31,740）"""
    P = [q for q in (piv or []) if q.get("p")]
    if len(P) < 6:
        return None
    kH = max(range(len(P)), key=lambda k: P[k]["p"] if P[k]["t"] == "H" else -1e18)
    if P[kH]["t"] != "H" or kH < 4 or price >= P[kH]["p"] or any(q["t"] == "H" and q["p"] > P[kH]["p"] for q in P[kH + 1:]):
        return None
    H = P[kH]
    lows = [k for k in range(kH) if P[k]["t"] == "L"]
    if not lows:
        return None
    k0 = min(lows, key=lambda k: P[k]["p"])
    highs = [k for k in range(k0 + 1, kH) if P[k]["t"] == "H"]
    if not highs:
        return None
    k3 = max(highs, key=lambda k: P[k]["p"])
    w4 = [k for k in range(k3 + 1, kH) if P[k]["t"] == "L"]
    ups = [k for k in range(k0, k3) if P[k]["t"] == "L" and P[k + 1]["t"] == "H"]
    if not w4 or not ups:
        return None
    k4 = min(w4, key=lambda k: P[k]["p"])
    ks = max(ups, key=lambda k: P[k + 1]["p"] - P[k]["p"])
    G0, H3, W4, S3 = P[k0], P[k3], P[k4], P[ks]
    full, w3, w4len = H["p"] - G0["p"], H3["p"] - S3["p"], H3["p"] - W4["p"]
    f = lambda r: round(H["p"] - r * full, 2)                       # noqa: E731
    g = lambda r: round(H3["p"] - r * w3, 2)                        # noqa: E731
    d = lambda q: str(q.get("date") or "")[:10]                     # noqa: E731
    sc = [
        {"key": "A", "title": f"全波段 {_fmt(G0['p'])}→{_fmt(H['p'])} 走完，現在是更上層的大 A 浪",
         "levels": [{"label": "全波段 0.236", "price": f(0.236)}, {"label": "全波段 0.382（總修正目標）", "price": f(0.382)}],
         "after": "大 A 浪走完一定有一波日線級大 B 段反彈，之後才走大 C 浪"},
        {"key": "4", "title": f"只修正第 (3) 浪 {_fmt(S3['p'])}→{_fmt(H3['p'])}：第四大波還沒走完（{_fmt(H3['p'])}→{_fmt(W4['p'])}＝W、"
                              f"{_fmt(W4['p'])}→{_fmt(H['p'])}＝X 假突破、現在 Y／4-C）",
         "levels": [{"label": "第 (3) 浪 0.382", "price": g(0.382)}, {"label": "第 (3) 浪 0.5（極限防守）", "price": g(0.5)},
                    {"label": "Y＝0.618 倍 W", "price": round(H["p"] - 0.618 * w4len, 2)}, {"label": "Y＝W 等幅", "price": round(H["p"] - w4len, 2)},
                    {"label": f"第 (4) 浪低點（要守住，跌破這個定位作廢）", "price": W4["p"]}],
         "after": "在這區完成修正＝第四大波結束、直接轉入第 5 大波創高"},
        {"key": "C", "title": f"{_fmt(H3['p'])} 早已結束全波段、{_fmt(H['p'])} 是 B 波假突破，現在全波段 C 浪",
         "levels": [{"label": "C＝A 等幅（A＝" + f"{_fmt(H3['p'])}→{_fmt(W4['p'])}）", "price": round(H["p"] - w4len, 2)},
                    {"label": "全波段 0.382", "price": f(0.382)}, {"label": "全波段 0.5", "price": f(0.5)}],
         "after": "大 C 浪五波主跌，最深往全波段 0.382～0.5"},
    ]
    for x in sc:
        x["levels"] = [dict(v, hit=bool(price <= v["price"])) for v in x["levels"]]
    mk, cur = (mid_primary or {}).get("kind"), str((mid_primary or {}).get("current") or "")
    labs = [round(float(q.get("p") or 0)) for q in (mid_primary or {}).get("labels") or []]
    favored = "C" if (mk == "correction" and cur == "C" and round(H3["p"]) in labs and round(H["p"]) in labs) else None
    return {"pts": {"g0": {"p": G0["p"], "date": d(G0)}, "s3": {"p": S3["p"], "date": d(S3)}, "h3": {"p": H3["p"], "date": d(H3)},
                    "w4": {"p": W4["p"], "date": d(W4)}, "h": {"p": H["p"], "date": d(H)}},
            "scenarios": sc, "favored": favored, "price": price,
            "note": f"週 K 轉折：{_fmt(G0['p'])}（{d(G0)}）→ 第 (3) 浪 {_fmt(S3['p'])}→{_fmt(H3['p'])}、第 (4) 浪 {_fmt(W4['p'])}、"
                    f"{_fmt(H['p'])}（{d(H)}）；三種定位的分界：守不守得住 {_fmt(W4['p'])}、反彈能不能切開日線斜率"}
