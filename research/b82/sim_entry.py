"""PLAN-B82 R3 進場時機：在 run825 的 8%／25% 回測上換「怎麼買」，停損／停利以實際買價計算。
成交規則（保守）：掛單買要當天最低 ≤ 掛價 − 1 檔（穿過才算），價格＝min(開盤, 掛價)；突破買要最高 ≥ 訊號高 + 1 檔，價格＝max(開盤, 訊號高 + 1 檔)；
一價漲停買不到；盤中買進那天碰到停損就算停損（不管先後）、停利不算；開盤買進（含開盤就穿過掛價）跟原本一樣。"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, os.path.join(ROOT, 'research', 'b72'), os.path.join(ROOT, 'research', 'best'), os.path.join(ROOT, 'research', 'best2'), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)
import numpy as np
import pandas as pd
import engine
from run825 import Sim825, STP, TGT, CAP
from b82common import tick

LIMIT_UP = 1.095


class SimE(Sim825):
    def entries_v(self, sig, v):
        """訊號 → (t, s, e, 買價, 是否盤中買進)；買不到的不列"""
        if v == 'E0':
            t, s, e = self.entries(sig)
            return t, s, e, self.o[e, s].astype(float), np.zeros(len(t), bool)
        t, s = np.nonzero(sig[:-1])
        T = self.T
        if v == 'E1':
            e = t + 1
            H = self.h[t, s]
            trig = H + tick(H)
            oe, he, le = self.o[e, s], self.h[e, s], self.l[e, s]
            with np.errstate(invalid='ignore'):
                onep = (oe == he) & (oe == le) & (oe >= self.c[t, s] * LIMIT_UP)
                ok = np.isfinite(oe) & np.isfinite(he) & np.isfinite(H) & (he >= trig) & ~onep
            px = np.maximum(oe, trig)
            intra = oe < trig
            return t[ok], s[ok], e[ok], px[ok], intra[ok]
        if v in ('E2', 'E3'):
            c0 = self.c[t, s]
            L = c0 * 0.98 if v == 'E2' else np.minimum((self.h[t, s] + self.l[t, s]) / 2, c0 * 0.99)
            need = L - tick(L)
            e = np.full(len(t), -1, np.int64)
            px = np.full(len(t), np.nan)
            intra = np.zeros(len(t), bool)
            done = np.zeros(len(t), bool)
            for k in (1, 2, 3):
                j = t + k
                jj = np.minimum(j, T - 1)
                oj, lj = self.o[jj, s], self.l[jj, s]
                with np.errstate(invalid='ignore'):
                    hit = ~done & (j < T) & np.isfinite(oj) & np.isfinite(lj) & np.isfinite(L) & (lj <= need)
                e[hit] = jj[hit]
                px[hit] = np.minimum(oj, L)[hit]
                intra[hit] = (oj > L)[hit]
                done |= hit
            return t[done], s[done], e[done], px[done], intra[done]
        if v == 'E4':
            e1 = t + 1
            e = t + 2
            ok = e < T
            t, s, e1, e = t[ok], s[ok], e1[ok], e[ok]
            o1, c1 = self.o[e1, s], self.c[e1, s]
            oe, he, le = self.o[e, s], self.h[e, s], self.l[e, s]
            with np.errstate(invalid='ignore'):
                conf = np.isfinite(c1) & np.isfinite(o1) & (c1 > o1) & (c1 > self.c[t, s])
                onep = (oe == he) & (oe == le) & (oe >= c1 * LIMIT_UP)
                ok = conf & np.isfinite(oe) & (oe > 0) & ~onep
            return t[ok], s[ok], e[ok], oe[ok].astype(float), np.zeros(int(ok.sum()), bool)
        raise ValueError(v)

    def exits_px(self, s, e, ent, intra, stp=STP, tgt=TGT, M=CAP):
        """exits825 一樣，但停損／停利用實際買價；盤中買進那天：最低 ≤ 停損就停損、停利不算"""
        n = len(e)
        stop, tp = ent * (1 - stp), ent * (1 + tgt)
        x = np.full(n, -1, np.int64)
        px = np.full(n, np.nan)
        why = np.zeros(n, np.int8)
        done = np.zeros(n, bool)
        last_valid = np.full(n, -1, np.int64)
        for k in range(M):
            j = e + k
            alive = ~done & (j < self.T)
            if not alive.any():
                break
            jj = np.minimum(j, self.T - 1)
            oj, hj, lj, cj = self.o[jj, s], self.h[jj, s], self.l[jj, s], self.c[jj, s]
            fin = alive & np.isfinite(cj) & np.isfinite(lj) & np.isfinite(hj) & np.isfinite(oj)
            last_valid = np.where(fin, jj, last_valid)
            with np.errstate(invalid='ignore'):
                gap_sl = fin & (k > 0) & (oj <= stop)
                touch_sl = fin & ~gap_sl & (lj <= stop)
                sl = gap_sl | touch_sl
                no_tp = (k == 0) & intra
                gap_tp = fin & ~sl & (k > 0) & (oj >= tp)
                touch_tp = fin & ~sl & ~gap_tp & (hj >= tp) & ~no_tp
                tq = gap_tp | touch_tp
            px = np.where(gap_sl, oj, np.where(touch_sl, stop, np.where(gap_tp, oj, np.where(touch_tp, tp, px))))
            hit = sl | tq
            x = np.where(hit, jj, x)
            why = np.where(sl, 2, np.where(tq, 1, why))
            done |= hit
        lv = np.where(last_valid >= 0, last_valid, e)
        nothit = ~done
        cap = e + M
        capped = nothit & (cap < self.T)
        for i in np.nonzero(capped)[0]:
            j = cap[i]
            while j < self.T and not np.isfinite(self.o[j, s[i]]):
                j += 1
            if j < self.T:
                x[i], px[i], why[i] = j, self.o[j, s[i]], 3
            else:
                capped[i] = False
        rest = nothit & ~capped
        gone = rest & (lv < self.last_idx_all - 0)
        x = np.where(rest, lv, x)
        px = np.where(rest, self.c[lv, s], px)
        why = np.where(rest & gone, 5, np.where(rest, 4, why))
        return x, px, why

    def trades_v(self, sig, v, slip=0.0, stp=STP, tgt=TGT, M=CAP):
        """trades825 一樣的欄位；v＝E0～E4；slip＝盤中買進再多扣的滑價（只當敏感度）"""
        t, s, e, ent, intra = self.entries_v(sig, v)
        cols = ['t', 's', 'e', 'x', 'ret', 'days', 'date', 'px_out', 'why', 'gone', 'intra']
        if len(t) == 0:
            return pd.DataFrame(columns=cols)
        x, pxo, why = self.exits_px(s, e, ent, intra, stp, tgt, M)
        ok = x >= e
        t, s, e, x, pxo, why, ent, intra = t[ok], s[ok], e[ok], x[ok], pxo[ok], why[ok], ent[ok], intra[ok]
        order = np.lexsort((e, s))
        t, s, e, x, pxo, why, ent, intra = t[order], s[order], e[order], x[order], pxo[order], why[order], ent[order], intra[order]
        keep = engine._non_overlap(s, e, x, self.T)
        t, s, e, x, pxo, why, ent, intra = t[keep], s[keep], e[keep], x[keep], pxo[keep], why[keep], ent[keep], intra[keep]
        div = self.cumfac[x, s] / self.cumfac[e, s]
        ent_eff = ent * (1 + slip * intra)
        net = pxo / ent_eff * div * (1 - engine.SELL_COST) / (1 + engine.BUY_COST) - 1
        return pd.DataFrame({'t': t, 's': s, 'e': e, 'x': x, 'ret': net, 'days': x - e, 'date': self.dates[t],
                             'px_out': pxo, 'why': why, 'gone': why >= 4, 'intra': intra})

    def fill_rate(self, sig, v):
        n = int(np.count_nonzero(sig[:-1]))
        return len(self.entries_v(sig, v)[0]) / n if n else None
