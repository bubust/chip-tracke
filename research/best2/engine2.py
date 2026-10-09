"""PLAN-BEST2 研究引擎：在 research/best/engine.Sim 上加
- E0＝網站 K 線回測預設（直接呼叫 backtest_engine.simulate，跟網站批量回測同一份程式）
- E6 固定 % 停損＋停利／天數（收盤判斷、隔天開盤出場）
- E7 固定 % 停損、沒跌破一直抱（最多 250 天）：E7c 收盤判斷／E7i 盤中觸價（開盤跳空越過→開盤價，否則停損價）
停損價＝買進價 ×（1 − %），進場後不重算。資料結束還沒出場的用最後收盤算、標 open。"""
import os, sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'research', 'best')); sys.path.insert(0, HERE)
import numpy as np
import pandas as pd
import engine
from engine import _non_overlap

E7_CAP = 250


def new_exit_rules():
    R = {}
    for sp in (3, 5, 7, 10):
        for tg in (None, 10, 20):
            for m in (20, 60):
                R[f'E6_s{sp}_t{tg or 0}_{m}d'] = {'kind': 'pct', 'stp': sp / 100, 'tgt': tg / 100 if tg else None, 'max': m}
    for sp in (5, 7, 10, 15, 20):
        R[f'E7c_s{sp}'] = {'kind': 'hold', 'stp': sp / 100, 'mode': 'close', 'max': E7_CAP}
        R[f'E7i_s{sp}'] = {'kind': 'hold', 'stp': sp / 100, 'mode': 'intraday', 'max': E7_CAP}
    return R


class Sim2(engine.Sim):
    """exits2 回傳 (x, px, is_open)：px＝出場價（NaN＝用 x 那天開盤）；is_open＝資料結束還抱著（用最後收盤）"""

    def exits2(self, t, s, e, rule):
        kind, M = rule['kind'], rule.get('max', rule.get('n'))
        n = len(e)
        if kind not in ('pct', 'hold'):
            x = self.exits(t, s, e, rule)
            at_close = x <= -2
            x = np.where(at_close, -2 - x, x)
            px = np.where(at_close, self.c[np.maximum(x, 0), s], np.nan)
            return x, px, np.zeros(n, bool)
        ent = self.o[e, s]
        stop = ent * (1 - rule['stp'])
        tgt = ent * (1 + rule['tgt']) if rule.get('tgt') else np.full(n, np.inf)
        intraday = rule.get('mode') == 'intraday'
        x = np.full(n, -1, np.int64)
        px = np.full(n, np.nan)
        done = np.zeros(n, bool)
        last_valid = np.full(n, -1, np.int64)
        for k in range(M):
            j = e + k
            alive = ~done & (j < self.T)
            if not alive.any():
                break
            jj = np.minimum(j, self.T - 1)
            cj, oj, lj = self.c[jj, s], self.o[jj, s], self.l[jj, s]
            fin = alive & np.isfinite(cj)
            last_valid = np.where(fin, jj, last_valid)
            with np.errstate(invalid='ignore'):
                if intraday:
                    gap = fin & (k > 0) & (oj <= stop)            # 開盤就跳空越過停損 → 開盤價（進場那天開盤＝買價，不算）
                    touch = fin & ~gap & (lj <= stop)
                    hit = gap | touch
                    px = np.where(gap, oj, np.where(touch, stop, px))
                    x = np.where(hit, jj, x)
                else:
                    hit = fin & ((cj < stop) | (cj >= tgt))       # 收盤跌破／到停利 → 隔天開盤
                    x = np.where(hit, jj + 1, x)
            done |= hit
        # 沒觸發：到天數 → 第 e+M 天開盤賣；資料不夠 → 還抱著（最後收盤）
        cap = e + M
        nothit = ~done
        x = np.where(nothit & (cap < self.T), cap, x)
        is_open = nothit & (cap >= self.T)
        # 收盤判斷版：觸發在最後一天 → 隔天沒資料也算還抱著
        if not intraday:
            is_open |= done & (x >= self.T)
        lv = np.where(last_valid >= 0, last_valid, e)
        x = np.where(is_open, lv, x)
        px = np.where(is_open, self.c[lv, s], px)
        # 出場日沒開盤（停牌）→ 往後第一個有開盤的日子
        need_open = ~is_open & np.isnan(px)
        bad = np.nonzero(need_open & ~np.isfinite(self.o[np.minimum(x, self.T - 1), s]))[0]
        for i in bad:
            j = x[i]
            while j < self.T and not np.isfinite(self.o[j, s[i]]):
                j += 1
            if j < self.T:
                x[i] = j
            else:
                x[i] = lv[i]; px[i] = self.c[lv[i], s[i]]; is_open[i] = True
        return x, px, is_open

    def trades2(self, sig, rule, cut_tail=True):
        """跟 Sim.trades 一樣（不重疊、成本、除權息），多了出場價、還抱著的；E7（mtm）不砍尾端訊號"""
        sig = sig.copy()
        M = rule.get('max', rule.get('n'))
        if cut_tail and rule['kind'] != 'hold':
            sig[max(0, self.trade_to - M - 1):] = False
        t, s, e = self.entries(sig)
        if len(t) == 0:
            return _empty2()
        x, px, op = self.exits2(t, s, e, rule)
        ok = (x >= 0) & (x >= e) & ((x > e) | ~np.isnan(px))   # 盤中停損可以當天出場；開盤出場要隔天以後
        t, s, e, x, px, op = t[ok], s[ok], e[ok], x[ok], px[ok], op[ok]
        order = np.lexsort((e, s))
        t, s, e, x, px, op = t[order], s[order], e[order], x[order], px[order], op[order]
        keep = _non_overlap(s, e, x, self.T)
        t, s, e, x, px, op = t[keep], s[keep], e[keep], x[keep], px[keep], op[keep]
        return self._finish(t, s, e, x, px, op)

    def _finish(self, t, s, e, x, px, op, reason=None):
        px_in = self.o[e, s]
        px_out = np.where(np.isnan(px), self.o[x, s], px)
        div = self.cumfac[x, s] / self.cumfac[e, s]
        net = px_out / px_in * div * (1 - engine.SELL_COST) / (1 + engine.BUY_COST) - 1
        d = pd.DataFrame({'t': t, 's': s, 'e': e, 'x': x, 'ret': net, 'days': x - e, 'date': self.dates[t],
                          'open': op, 'gone': np.zeros(len(t), bool), 'px_out': px_out})
        if reason is not None:
            d['reason'] = reason
        return d


def _empty2():
    return pd.DataFrame({k: pd.Series(dtype=float) for k in ('t', 's', 'e', 'x', 'ret', 'days', 'px_out')}).assign(
        date=pd.Series(dtype=str), open=pd.Series(dtype=bool), gone=pd.Series(dtype=bool))


# ── E0：網站 K 線回測預設（backtest_engine.simulate）──────────────────────────
_G = {}


def _e0_init():
    import backtest_engine as be
    _G['be'] = be


def _e0_stock(task):
    """一檔股票、多個訊號：回傳 [(name, t_panel, e_panel, x_panel, exit_px_raw, reason)]"""
    col, rows, df, masks = task
    be = _G['be']
    out = []
    ec = be.ExitConfig()                                 # 2ATR 停損、2.5ATR 移動停損、最多 60 天、隔天開盤進場
    adj = be.adjust_ohlcv(df)
    di = {d: k for k, d in enumerate(df['date'])}
    for name, m in masks.items():
        trades, open_tr, _ = be.simulate(adj, m, 'long', ec)
        for tr in trades + ([open_tr] if open_tr else []):
            if not tr:
                continue
            ti, ei, xi = di.get(tr['signal_date']), di.get(tr['entry_date']), di.get(tr['exit_date'])
            if ti is None or ei is None or xi is None:
                continue
            out.append((name, int(rows[ti]), int(rows[ei]), int(rows[xi]), float(tr['exit_price']),
                        tr.get('exit_reason', ''), tr.get('status', 'closed')))
    return col, out


def run_e0(sim, P, sigs_dense: dict, procs=6):
    """sigs_dense：{name: T×S bool}；回傳 {name: trades DataFrame}（我們的成本＋除權息算報酬）"""
    C = P['close'].to_numpy(float)
    tasks = []
    names = list(sigs_dense)
    for col in range(C.shape[1]):
        cols = {k: v[:, col] for k, v in sigs_dense.items() if v[:, col].any()}
        if not cols:
            continue
        ok = np.isfinite(C[:, col])
        rows = np.nonzero(ok)[0]
        sid = P['close'].columns[col]
        df = pd.DataFrame({'date': P['close'].index[ok], **{k: P[k][sid].to_numpy()[ok] for k in ('open', 'high', 'low', 'close', 'volume')}})
        tasks.append((col, rows, df, {k: v[ok].tolist() for k, v in cols.items()}))
    res = {k: [] for k in names}
    with Pool(procs, initializer=_e0_init) as pool:
        for col, out in pool.imap_unordered(_e0_stock, tasks, chunksize=4):
            for name, t, e, x, px, why, st in out:
                res[name].append((t, col, e, x, px, why, st == 'open'))
    outd = {}
    for name, rows in res.items():
        if not rows:
            outd[name] = _empty2()
            continue
        a = np.array([r[:5] for r in rows], dtype=float)
        t, s, e, x = (a[:, k].astype(np.int64) for k in range(4))
        px = a[:, 4]
        op = np.array([r[6] for r in rows], bool)
        d = sim._finish(t, s, e, x, px, op, reason=[r[5] for r in rows])
        outd[name] = d.sort_values(['s', 'e']).reset_index(drop=True)
    return outd
