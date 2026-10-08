"""PLAN-BEST 研究引擎：官方日行情 → 寬表（日期 × 股票）→ 指標 → 訊號 → 交易模擬 → 統計。
交易模型（PLAN-BEST 第 3 節）：第 t 天收盤出訊號 → t+1 開盤買（開盤一價漲停買不到不算）；
出場條件用收盤判斷 → 隔天開盤賣（用實際開盤價，跳空算在裡面）；成本 買 0.1425%＋賣 0.1425%＋稅 0.3%＋滑價每邊 0.1%；
報酬含除權息（官方「漲跌」是對參考價：參考價＝收盤−漲跌，跟前收差 >0.3% 的日子＝除權息，持有跨過就乘 前收÷參考價）；
同一檔持有中不再進新訊號。
指標都用「這檔有交易的日子」算（停牌日不算一根，跟正式站 price_daily 一樣），再對回日期。"""
import glob, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from scanner_course import rsi as _rsi          # noqa: E402  網站用的 Wilder RSI

BUY_COST = 0.001425 + 0.001       # 手續費＋滑價
SELL_COST = 0.001425 + 0.003 + 0.001
TRADE_FROM = '20211001'           # 之前的資料只當指標暖身


# ── 資料 ────────────────────────────────────────────────────────────────────
def load_panel(data_dir: str) -> dict:
    files = sorted(glob.glob(os.path.join(data_dir, '20*.csv.gz')))
    df = pd.concat((pd.read_csv(f, dtype={'stock_id': str, 'date': str}) for f in files), ignore_index=True)
    df = df[df.stock_id.str.fullmatch(r'[1-9]\d{3}')]
    df = df.drop_duplicates(['date', 'stock_id'], keep='last')
    P = {}
    for col in ('open', 'high', 'low', 'close', 'volume', 'chg'):
        P[col] = df.pivot(index='date', columns='stock_id', values=col).sort_index().astype(float)
    names = df.drop_duplicates('stock_id', keep='last').set_index('stock_id')['name']
    P['name'] = names.reindex(P['close'].columns)
    tx = pd.read_csv(os.path.join(data_dir, 'taiex.csv'), header=None, names=['date', 'taiex'], dtype={'date': str})
    P['taiex'] = tx.drop_duplicates('date', keep='last').set_index('date')['taiex'].reindex(P['close'].index).ffill()
    return P


def event_factor(P: dict, data_dir: str) -> pd.DataFrame:
    """除權息／減資／面額變更日的報酬調整比例＝除權息前收盤 ÷ 參考價（官方事件表 data/events.csv：
    證交所 TWT49U、TWTAUU、TWTB8U，櫃買 exDailyQ），其他日子 1。
    官方日行情在這些日子的漲跌欄是「X／除權息」（沒有數字），所以不能從漲跌反推。
    事件表沒有、但當天收盤比前一天差超過 10.5%（超過漲跌停，一定是減資之類，櫃買減資沒有表）的少數幾天：用 前收 ÷ 開盤 估。"""
    c = P['close']
    ev = pd.read_csv(os.path.join(data_dir, 'events.csv'), dtype={'date': str, 'stock_id': str})
    ev = ev[ev.date.isin(c.index) & ev.stock_id.isin(c.columns) & (ev.ref > 0)]
    ev = ev.drop_duplicates(['date', 'stock_id'], keep='last')
    di = {d: i for i, d in enumerate(c.index)}; si = {s: i for i, s in enumerate(c.columns)}
    arr = np.ones(c.shape)
    arr[ev.date.map(di).to_numpy(), ev.stock_id.map(si).to_numpy()] = (ev.prev_close / ev.ref).to_numpy()
    prev = c.ffill().shift(1)
    jump = (P['chg'].isna() & c.notna() & prev.notna() & ((c / prev - 1).abs() > 0.105)).to_numpy() & (arr == 1.0)
    est = (prev / P['open']).to_numpy()
    arr[jump] = est[jump]
    f = pd.DataFrame(arr, index=c.index, columns=c.columns)
    return f.where(np.isfinite(f), 1.0).clip(0.1, 10.0)


def per_stock(df: pd.DataFrame, fn) -> pd.DataFrame:
    """每一欄去掉停牌日（NaN）算完再對回日期"""
    return df.apply(lambda s: fn(s.dropna())).reindex(index=df.index, columns=df.columns)


# ── 指標 ────────────────────────────────────────────────────────────────────
def atr_df(P):
    """price_levels.atr_series 同一套：TR＝max(高−低, |高−昨收|, |低−昨收|)，14 日簡單平均（昨收＝上一個交易日）"""
    c = P['close']
    pc = per_stock(c, lambda s: s.shift(1))
    h, l = P['high'], P['low']
    tr = np.maximum(h - l, np.maximum((h - pc).abs(), (l - pc).abs()))
    tr = tr.where(pc.notna(), h - l).where(c.notna())
    return per_stock(tr, lambda s: s.rolling(14).mean())


def features(P: dict) -> dict:
    c, v = P['close'], P['volume']
    F = {}
    for n in (5, 10, 20, 60, 120, 200):
        F[f'ma{n}'] = per_stock(c, lambda s, n=n: s.rolling(n).mean())
    F['atr'] = atr_df(P)
    F['rsi2'] = per_stock(c, lambda s: _rsi(s, 2))
    F['vol20'] = per_stock(v, lambda s: s.rolling(20).mean())               # 含今天（股票池用）
    F['vol20p'] = per_stock(v, lambda s: s.rolling(20).mean().shift(1))     # 前 20 天（量增用）
    F['bars'] = c.notna().cumsum()
    F['liquid'] = (c >= 10) & (F['vol20'] >= 500) & (F['bars'] >= 120) & c.notna()
    # 除權息／減資的價格缺口：台股單日漲跌幅上限 10%，收盤或開盤比前一天收盤差超過 10.5% 一定是公司事件（配股、大額配息、減資、面額變更）。
    # 不還原價格的均線、乖離、ATR 在之後 60 根都會被扭曲（例：6669 緯穎 2026-09-02 配股 7800→2615，被當成暴跌出抄底訊號）→ 這段期間不出訊號
    pc = per_stock(c, lambda s: s.shift(1))
    jump = (((c / pc - 1).abs() > 0.105) | ((P['open'] / pc - 1).abs() > 0.105)).where(c.notna())
    F['gap60'] = per_stock(jump.astype(float), lambda s: s.rolling(60, min_periods=1).max()).fillna(0) > 0
    tx = P['taiex']
    F['tx_ma60'] = tx.rolling(60).mean()
    F['tx_ma200'] = tx.rolling(200).mean()
    return F


# ── 交易模擬 ────────────────────────────────────────────────────────────────
def _next_true(hit: np.ndarray) -> np.ndarray:
    """nt[i, s]＝第 i 天（含）之後第一個 hit 的日子，沒有＝T（往回掃一次，全部股票一起）"""
    T, S = hit.shape
    nt = np.full((T + 1, S), T, dtype=np.int32)
    for i in range(T - 1, -1, -1):
        nt[i] = np.where(hit[i], i, nt[i + 1])
    return nt[:T]


class Sim:
    """一次準備好陣列，對任一個訊號矩陣、出場規則算交易"""
    def __init__(self, P, F, fac):
        self.dates = np.array(P['close'].index)
        self.sids = np.array(P['close'].columns)
        A = lambda x: x.to_numpy(dtype=float)
        self.o, self.h, self.l, self.c = A(P['open']), A(P['high']), A(P['low']), A(P['close'])
        self.atr, self.ma5 = A(F['atr']), A(F['ma5'])
        self.T, self.S = self.c.shape
        fin = np.isfinite(self.c)
        self.last_idx = np.where(fin.any(axis=0), self.T - 1 - np.argmax(fin[::-1], axis=0), -1)   # 每檔最後交易日
        self.cumfac = np.cumprod(A(fac), axis=0)        # 持有 e→x 的除權息調整＝cumfac[x]/cumfac[e]
        with np.errstate(invalid='ignore'):
            rsi2 = A(F['rsi2'])
            self.nt = {
                'ma5': _next_true(np.nan_to_num((self.c > self.ma5) | (rsi2 > 70), nan=0).astype(bool)),
                'ma10': _next_true(self.c < A(F['ma10'])),
                'ma20': _next_true(self.c < A(F['ma20'])),
            }
        self.e5 = None            # {(s, t): 第一個收盤跌破滾動停損的日子}，run.py 算好放進來
        self.e5_stop = None       # {(s, t): 進場時的停損價}
        self.trade_to = len(self.dates) - 1
        self.oos_end = None

    def entries(self, sig: np.ndarray):
        """訊號 (T×S bool) → (t, s, e)：e＝t+1 進場日；排除隔天沒開盤（停牌）、一價漲停"""
        t, s = np.nonzero(sig[:-1])
        e = t + 1
        o_e = self.o[e, s]
        ok = np.isfinite(o_e) & (o_e > 0)
        lim = (o_e >= self.c[t, s] * 1.095) & (o_e == self.h[e, s]) & (o_e == self.l[e, s])
        ok &= ~lim
        return t[ok], s[ok], e[ok]

    def exits(self, t, s, e, rule: dict):
        """回傳出場日 x（在 x 開盤賣）。rule：
        {'kind':'time','n':N} | {'kind':'ma5','max':M}（收盤>MA5 或 RSI2>70）|
        {'kind':'atr','tgt':k1,'stp':k2,'max':M} | {'kind':'ma10'/'ma20','max':M}（收盤跌破）| {'kind':'roll','max':M}"""
        kind = rule['kind']
        M = rule.get('max', rule.get('n'))
        cap = e + M                                      # 最長持有：第 e+M 天開盤賣
        if kind == 'time':
            hitday = np.full(len(e), self.T)
        elif kind in self.nt:
            hitday = self.nt[kind][e, s]
        elif kind == 'roll':
            hitday = np.array([self.e5.get((int(a), int(b)), self.T) for a, b in zip(s, t)], dtype=np.int64)
        elif kind == 'atr':
            hitday = np.full(len(e), self.T)
            ent = self.o[e, s]
            a = self.atr[t, s]
            tg, sp = ent + rule['tgt'] * a, ent - rule['stp'] * a
            for k in range(M):
                j = e + k
                ok = j < self.T
                jj = np.minimum(j, self.T - 1)
                cj = self.c[jj, s]
                with np.errstate(invalid='ignore'):
                    h = ok & ((cj >= tg) | (cj < sp)) & (hitday == self.T)
                hitday = np.where(h, j, hitday)
        else:
            raise ValueError(kind)
        x = np.where(hitday < cap, hitday + 1, cap).astype(np.int64)
        # 出場日沒開盤（停牌）→ 往後找第一個有開盤的日子
        x = np.minimum(x, self.T)
        bad = np.nonzero((x < self.T) & ~np.isfinite(self.o[np.minimum(x, self.T - 1), s]))[0]
        for i in bad:
            j = x[i]
            while j < self.T and not np.isfinite(self.o[j, s[i]]):
                j += 1
            x[i] = j
        # 之後都沒開盤：資料最後一天前就沒了（下市、長期停牌到期末）→ 用最後一天收盤出場（標 -2-x，trades 換成收盤價）
        gone = (x >= self.T) & (self.last_idx[s] < self.T - 1) & (self.last_idx[s] > e)
        x = np.where(gone, -2 - self.last_idx[s], x)
        x[x >= self.T] = -1
        return x

    def trades(self, sig, rule):
        """不重疊（同一檔出場之後的訊號才能再進）的交易表；只收「最長持有期滿也在資料內」的訊號（避免尾端偏差）"""
        M = rule.get('max', rule.get('n'))
        sig = sig.copy()
        sig[max(0, self.trade_to - M - 1):] = False
        t, s, e = self.entries(sig)
        if len(t) == 0:
            return _empty()
        x = self.exits(t, s, e, rule)
        at_close = x <= -2
        x = np.where(at_close, -2 - x, x)
        ok = x > e
        t, s, e, x, at_close = t[ok], s[ok], e[ok], x[ok], at_close[ok]
        order = np.lexsort((e, s))
        t, s, e, x, at_close = t[order], s[order], e[order], x[order], at_close[order]
        keep = _non_overlap(s, e, x, self.T)
        t, s, e, x, at_close = t[keep], s[keep], e[keep], x[keep], at_close[keep]
        px_in, px_out = self.o[e, s], np.where(at_close, self.c[x, s], self.o[x, s])
        div = self.cumfac[x, s] / self.cumfac[e, s]      # e 當天開盤已經是除權息後的價，所以從 e 算
        gross = px_out / px_in * div
        net = gross * (1 - SELL_COST) / (1 + BUY_COST) - 1
        return pd.DataFrame({'t': t, 's': s, 'e': e, 'x': x, 'ret': net, 'days': x - e, 'date': self.dates[t],
                             'gone': at_close})


def _empty():
    return pd.DataFrame({k: pd.Series(dtype=float) for k in ('t', 's', 'e', 'x', 'ret', 'days')}).assign(date=pd.Series(dtype=str))


def _non_overlap(s, e, x, T):
    """已依 (s, e) 排序：每檔從第一筆開始，下一筆＝進場日 > 上一筆出場日的第一筆（向量化指標追蹤，全部股票一起走）"""
    n = len(s)
    keep = np.zeros(n, bool)
    if n == 0:
        return keep
    key = s.astype(np.int64) * (T + 2) + e
    nxt = np.searchsorted(key, s.astype(np.int64) * (T + 2) + x, side='right')
    nxt_ok = nxt < n
    same = np.zeros(n, bool)
    same[nxt_ok] = s[nxt[nxt_ok]] == s[nxt_ok]
    nxt = np.where(same, nxt, -1)
    first = np.r_[True, s[1:] != s[:-1]]
    cur = np.nonzero(first)[0]
    while len(cur):
        keep[cur] = True
        cur = nxt[cur]
        cur = cur[cur >= 0]
    return keep


# ── 統計 ────────────────────────────────────────────────────────────────────
def stats(r: np.ndarray, days=None) -> dict:
    r = np.asarray(r, float)
    if len(r) == 0:
        return {'n': 0}
    w, ls = r[r > 0], r[r <= 0]
    return {'n': int(len(r)), 'win': float((r > 0).mean()), 'mean': float(r.mean()), 'median': float(np.median(r)),
            'pf': float(w.sum() / -ls.sum()) if ls.sum() < 0 else 99.0,
            'avg_win': float(w.mean()) if len(w) else 0.0, 'avg_loss': float(ls.mean()) if len(ls) else 0.0,
            'p5': float(np.percentile(r, 5)), 'days': float(np.mean(days)) if days is not None and len(days) else None}
