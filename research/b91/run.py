"""PLAN-B91 研究：尾盤追蹤（13:15 假跌破）＋日線多頭結構＋13:15 大盤盤面 → 什麼盤勢進場比較好

資料：research/b82/data/best（官方日行情 5 年，補到 20261103）、data/tx1315（證交所每 5 秒指數 → 每天加權 1 分 K）、
      wave.db idx_daily（加權日 K、費半；本機缺的最近幾天：加權用分 K 彙總、費半用 Yahoo ^SOX）
訊號：S_FBD 向量化（正式站參數＝預設），先跟 B82 sig_all.csv.gz 比對；股票池＝盤中版（fbd_live.candidates）：
      昨收 > 10、前 20 日均量（不含今天）≥ 300 張、至少 65 根
進場＝訊號日收盤（代替 13:15 價）；出場＝停損 8%（隔天起盤中觸價，跳空用開盤）、停利 25%、上限 250 天；成本、除權息同 engine；
同一檔持有中不重複進場。樣本內 20211001～20240630、樣本外 20240701～20261103。
Q1 結構有沒有幫助；Q2 盤勢 9 族（tail_market.FAMILIES）每族樣本內挑最好／最差各一格 → 樣本外驗一次，18 個一起 BH（q＜0.10）；
Q3 最近 10/20～11/03 跟正式站 98 筆對照；敏感度（進場價往不利方向調整）。
用法：python run.py [--quick]   產出：research/b91/results.json、REPORT.md、repo 根目錄 tail_research.json"""
import gzip, json, os, sqlite3, sys, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, os.path.join(ROOT, 'research', 'best'), os.path.join(ROOT, 'research', 'b73')):
    if p not in sys.path:
        sys.path.insert(0, p)
import numpy as np
import pandas as pd
import engine
from run_quality import month_boot_p, bh
import tail_market as TM

B82 = os.environ.get('B82_DATA', os.path.join(os.path.dirname(ROOT), 'chip-tracker-b81', 'research', 'b82', 'data'))
DATA = os.path.join(B82, 'best')
SIG = os.path.join(B82, 'sig_all.csv.gz')
TXD = os.path.join(HERE, 'data', 'tx1315')
WAVE_DB = os.environ.get('WAVE_DB', os.path.join(os.path.dirname(ROOT), 'chip-tracker', 'chip_data', 'wave.db'))
TAIL_JSON = os.path.join(HERE, 'data', 'tail_list_prod.json')       # 正式站 /api/tail/list（11/03 存的）
IS = ('20211001', '20240630')
OOS = ('20240701', '20261103')
SEED = 20261103
BOOT = 2000
STP, TGT, CAP = 0.08, 0.25, 250
P_FBD = {'min_price': 10, 'min_vol_lots': 300, 'break_vol_ratio': 2.5, 'vol_ref_days': 20, 'macd_ref_days': 3}
RULE = {'is_n': 100, 'oos_n': 50, 'gap': 0.05, 'q': 0.10}
YEARS = ('2021', '2022', '2023', '2024', '2025', '2026')


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


# ── 訊號 ────────────────────────────────────────────────────────────────────
def sfbd_one(o, h, l, c, v, p=P_FBD):
    """scanner.screen_sfbd 向量化（同一檔、只含有交易的日子）→ (訊號, 盤中版股票池)"""
    s = pd.Series(c)
    ma10, ma60 = s.rolling(10).mean().to_numpy(), s.rolling(60).mean().to_numpy()
    e12, e26 = s.ewm(span=12, adjust=False).mean(), s.ewm(span=26, adjust=False).mean()
    dif = e12 - e26
    osc = (dif - dif.ewm(span=9, adjust=False).mean()).to_numpy()
    k = int(p['macd_ref_days'])
    osc_ref = np.r_[np.full(k, np.nan), osc[:-k]]
    vs = pd.Series(v)
    vol20 = vs.rolling(int(p['vol_ref_days'])).mean().to_numpy()                 # 含今天（同 screen_sfbd）
    avg20p = vs.rolling(20).mean().shift(1).to_numpy()                           # 前 20 日（盤中版候選）
    pc = np.r_[np.nan, c[:-1]]
    pv = np.r_[np.nan, v[:-1]]
    pma10 = np.r_[np.nan, ma10[:-1]]
    n = len(c)
    with np.errstate(invalid='ignore'):
        sig = ((np.arange(n) >= 64) & (c > p['min_price']) & (v >= p['min_vol_lots']) & (ma10 > ma60)
               & (osc < 0) & (osc > osc_ref) & (c > o) & (c > ma10) & (pc < pma10)
               & ~((vol20 > 0) & (pv > vol20 * p['break_vol_ratio'])) & (c > pc))
        pool = (np.arange(n) >= 64) & (pc > p['min_price']) & (avg20p >= p['min_vol_lots'])
    return np.nan_to_num(sig, nan=0).astype(bool), pool


def build(P):
    c = P['close']
    T, S = c.shape
    A = lambda x: x.to_numpy(dtype=float)
    o, h, l, cc, v = A(P['open']), A(P['high']), A(P['low']), A(c), A(P['volume'])
    sig = np.zeros((T, S), bool)                                   # S_FBD 本身（不含盤中版股票池）
    pool = np.zeros((T, S), bool)
    st = {k: np.zeros((T, S), np.int8) for k in (3, 5, 8)}          # 0 合格、1～3 不合格、4 點不夠
    for j in range(S):
        idx = np.nonzero(np.isfinite(cc[:, j]))[0]
        if len(idx) < 70:
            st[3][:, j] = st[5][:, j] = st[8][:, j] = 4
            continue
        s_, p_ = sfbd_one(o[idx, j], h[idx, j], l[idx, j], cc[idx, j], v[idx, j])
        sig[idx, j], pool[idx, j] = s_, p_
        for k in (3, 5, 8):
            col = np.full(T, 4, np.int8)
            col[idx] = TM.struct_series(h[idx, j], l[idx, j], k)[2]
            st[k][:, j] = col
    return sig, pool, st


def verify_sig(P, sig):
    """跟 B82 sig_all（逐日呼叫 scanner.screen_sfbd、只算 engine 股票池的日子）比對"""
    sa = pd.read_csv(SIG, dtype={'date': str, 'stock_id': str})
    sa = sa[sa.strategy == 'S_FBD']
    dates, sids = list(P['close'].index), list(P['close'].columns)
    di, si = {d: i for i, d in enumerate(dates)}, {s: i for i, s in enumerate(sids)}
    F = engine.features(P)
    liquid = F['liquid'].to_numpy()                                # B82 signals_a：股票池＝engine liquid（含除權息缺口那 60 天）
    ref = set((d, s) for d, s in zip(sa.date, sa.stock_id) if d in di and s in si)
    last = sa.date.max()
    mine = set()
    for t, s in zip(*np.nonzero(sig & liquid)):
        d = dates[t]
        if engine.TRADE_FROM <= d <= last:
            mine.add((d, sids[s]))
    ref = {x for x in ref if engine.TRADE_FROM <= x[0] <= last}
    both = len(ref & mine)
    return {'ref': len(ref), 'mine': len(mine), 'both': both, 'only_ref': len(ref - mine), 'only_mine': len(mine - ref),
            'agree': both / max(1, len(ref | mine)), 'sample_only_ref': sorted(ref - mine)[:10], 'sample_only_mine': sorted(mine - ref)[:10]}


# ── 大盤 ────────────────────────────────────────────────────────────────────
def load_tx_day(d8):
    f = os.path.join(TXD, d8 + '.csv.gz')
    if not os.path.exists(f):
        return None
    df = pd.read_csv(f)
    y = df.loc[df.hm == 859, 'c']
    m = df[df.hm >= 900]
    if m.empty:
        return None
    o = float(m.iloc[0]['o'])
    upto = m[m.hm < 1315]
    at = m[m.hm == 1315]
    if at.empty or upto.empty:
        return None
    x = float(at.iloc[0]['o'])                                         # 13:15:00
    return {'y': float(y.iloc[0]) if len(y) else None, 'o': o, 'h': max(float(upto.h.max()), x), 'l': min(float(upto.l.min()), x), 'x': x,
            'day': {'o': o, 'h': float(m.h.max()), 'l': float(m.l.min()), 'c': float(m.iloc[-1]['c'])}}


def load_index(sym):
    with sqlite3.connect(WAVE_DB) as c:
        df = pd.read_sql_query("SELECT date, o, h, l, c FROM idx_daily WHERE sym=? AND c IS NOT NULL ORDER BY date", c, params=(sym,))
    for k in ('o', 'h', 'l'):
        df[k] = df[k].fillna(df['c'])
    return df


def sox_yahoo_tail(after: str):
    import httpx
    try:
        j = httpx.get('https://query1.finance.yahoo.com/v8/finance/chart/%5ESOX', params={'range': '3mo', 'interval': '1d'},
                      headers={'User-Agent': 'Mozilla/5.0'}, timeout=30).json()
        r = j['chart']['result'][0]
        ts, cl = r['timestamp'], r['indicators']['quote'][0]['close']
        off = r['meta'].get('gmtoffset', -14400)
        rows = [(datetime.fromtimestamp(t + off, timezone.utc).strftime('%Y-%m-%d'), c) for t, c in zip(ts, cl) if c]
        return [x for x in rows if x[0] > after]
    except Exception as e:      # noqa: BLE001
        log('Yahoo SOX 失敗', e)
        return []


def market_table(dates):
    """每個交易日（YYYYMMDD）→ 13:15 大盤特徵（tail_market.market_features，跟網站同一份）"""
    tw = load_index('TWII')
    snaps = {d: load_tx_day(d) for d in dates}
    # 本機 idx_daily 缺的最近幾天：用分 K 彙總補（重疊日期先比對收盤）
    have = set(tw.date)
    chk = []
    add = []
    for d, sn in snaps.items():
        if not sn:
            continue
        iso = f'{d[:4]}-{d[4:6]}-{d[6:]}'
        if iso in have:
            cl = float(tw.loc[tw.date == iso, 'c'].iloc[0])
            chk.append(abs(sn['day']['c'] / cl - 1))
        else:
            add.append({'date': iso, **sn['day']})
    if add:
        tw = pd.concat([tw, pd.DataFrame(add)], ignore_index=True).sort_values('date').reset_index(drop=True)
    sox = load_index('SOX')
    extra = sox_yahoo_tail(sox.date.max())
    if extra:
        sox = pd.concat([sox, pd.DataFrame([{'date': d, 'o': c, 'h': c, 'l': c, 'c': c} for d, c in extra])], ignore_index=True)
    td, th, tl, tc = tw.date.to_numpy(), tw.h.to_numpy(float), tw.l.to_numpy(float), tw.c.to_numpy(float)
    sd, sc = sox.date.to_list(), sox.c.to_list()
    out = {}
    for d, sn in snaps.items():
        if not sn:
            continue
        iso = f'{d[:4]}-{d[4:6]}-{d[6:]}'
        k = int(np.searchsorted(td, iso))                              # 昨天以前
        f = TM.market_features(th[:k], tl[:k], tc[:k], sn, TM.sox_change(sd, sc, iso))
        if f:
            out[d] = f
    meta = {'tx_days': sum(1 for s in snaps.values() if s), 'close_check_max': max(chk) if chk else None,
            'close_check_n': len(chk), 'filled_from_minutes': len(add), 'sox_yahoo_days': len(extra)}
    return out, meta


# ── 交易 ────────────────────────────────────────────────────────────────────
class Book:
    def __init__(self, P, fac):
        A = lambda x: x.to_numpy(dtype=float)
        self.dates = np.array(P['close'].index)
        self.sids = np.array(P['close'].columns)
        self.o, self.h, self.l, self.c = A(P['open']), A(P['high']), A(P['low']), A(P['close'])
        self.T = len(self.dates)
        self.cum = np.cumprod(A(fac), axis=0)

    def trades(self, mask, bump=0.0, fwd=(5, 10, 20)):
        """mask (T×S) 訊號日收盤進場（bump＝進場價 ×(1+bump)，敏感度用）→ DataFrame"""
        t, s = np.nonzero(mask)
        order = np.lexsort((t, s))
        t, s = t[order], s[order]
        c0 = self.c[t, s] * (1 + bump)
        n = len(t)
        x = np.full(n, -1, np.int64)
        px = np.full(n, np.nan)
        why = np.zeros(n, np.int8)
        done = np.zeros(n, bool)
        last = t.copy()
        stop, tp = c0 * (1 - STP), c0 * (1 + TGT)
        for k in range(1, CAP + 1):
            j = t + k
            alive = ~done & (j < self.T)
            if not alive.any():
                break
            jj = np.minimum(j, self.T - 1)
            oj, hj, lj, cj = self.o[jj, s], self.h[jj, s], self.l[jj, s], self.c[jj, s]
            fin = alive & np.isfinite(oj) & np.isfinite(hj) & np.isfinite(lj) & np.isfinite(cj)
            last = np.where(fin, jj, last)
            with np.errstate(invalid='ignore'):
                gsl = fin & (oj <= stop)
                tsl = fin & ~gsl & (lj <= stop)
                sl = gsl | tsl
                gtp = fin & ~sl & (oj >= tp)
                ttp = fin & ~sl & ~gtp & (hj >= tp)
                tq = gtp | ttp
            px = np.where(gsl, oj, np.where(tsl, stop, np.where(gtp, oj, np.where(ttp, tp, px))))
            hit = sl | tq
            x = np.where(hit, jj, x)
            why = np.where(sl, 2, np.where(tq, 1, why))
            done |= hit
        rest = ~done
        x = np.where(rest, last, x)
        px = np.where(rest, self.c[last, s], px)
        why = np.where(rest, np.where(last >= self.T - 1, 4, 3), why)          # 3 到期／下市、4 資料結束還抱著
        keep = engine._non_overlap(s, t, x, self.T)
        t, s, x, px, why, c0 = t[keep], s[keep], x[keep], px[keep], why[keep], c0[keep]
        div = self.cum[x, s] / self.cum[t, s]
        ret = px / c0 * div * (1 - engine.SELL_COST) / (1 + engine.BUY_COST) - 1
        out = pd.DataFrame({'t': t, 's': s, 'x': x, 'ret': ret, 'days': x - t, 'date': self.dates[t], 'why': why})
        for f in fwd:
            j = np.minimum(t + f, self.T - 1)
            r = self.c[j, s] / c0 * self.cum[j, s] / self.cum[t, s] - 1
            out[f'f{f}'] = np.where((t + f < self.T) & np.isfinite(r), r, np.nan)
        return out


def st(tr, a, b):
    d = tr['date'].astype(str)
    m = (d >= a) & (d <= b)
    r = tr.loc[m, 'ret'].to_numpy(float)
    s = engine.stats(r, tr.loc[m, 'days'].to_numpy(float))
    if s.get('n'):
        s['f10'] = float(np.nanmean(tr.loc[m, 'f10'])) if 'f10' in tr else None
        s['stop_rate'] = float((tr.loc[m, 'why'] == 2).mean())
    return s


def brief(s):
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items() if k in ('n', 'win', 'mean', 'median', 'pf', 'f10', 'stop_rate')}


def random_same_days(book, pool, tr, reps=10, seed=SEED, need=None):
    """跟 tr 同一天（同樣多筆）隨機挑股票池裡的股票（need：另外要成立的條件，例如結構合格），同出場 → 交易表"""
    rng = np.random.default_rng(seed)
    cnt = tr.groupby('t').size()
    outs = []
    for r in range(reps):
        m = np.zeros(pool.shape, bool)
        for t, k in cnt.items():
            ok = pool[t] & (need[t] if need is not None else True)
            cand = np.nonzero(ok)[0]
            if len(cand):
                m[t, rng.choice(cand, size=min(k, len(cand)), replace=False)] = True
        outs.append(book.trades(m))
    return pd.concat(outs, ignore_index=True)


# ── 主程式 ──────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    P = engine.load_panel(DATA)
    fac = engine.event_factor(P, DATA)
    dates = np.array(P['close'].index)
    log('行情', P['close'].shape, dates[0], dates[-1])
    raw, pool, stc = build(P)
    ver = verify_sig(P, raw)                                       # 跟 B82 比：不套盤中版股票池
    sig = raw & pool                                               # 研究用：盤中版股票池（跟 fbd_live 一樣）
    log('訊號＋結構', int(sig.sum()), f'{time.time() - t0:.0f}s')
    log('S_FBD 比對', ver)
    book = Book(P, fac)
    trade_ok = (dates >= IS[0])[:, None]
    A = sig & trade_ok
    Bm = A & (stc[3] == 0)
    mk, mk_meta = market_table([d for d in dates if d >= IS[0]])
    log('大盤特徵', len(mk), mk_meta)
    tA, tB = book.trades(A), book.trades(Bm)
    res = {'generated': datetime.now().strftime('%Y-%m-%d %H:%M'), 'data': {'from': str(dates[0]), 'to': str(dates[-1])},
           'is': IS, 'oos': OOS, 'seed': SEED, 'boot': BOOT, 'verify_sfbd': ver, 'market_meta': mk_meta,
           'struct_unknown_share': float(((stc[3] == 4) & A).sum() / max(1, A.sum())),
           'struct_fail_reasons': {TM._REASONS[k]: int(((stc[3] == k) & A).sum()) for k in (1, 2, 3, 4)}}
    # Q1 結構
    pool_ok = pool & trade_ok
    rA = random_same_days(book, pool_ok, tA)
    rB = random_same_days(book, pool_ok, tB, need=(stc[3] == 0))
    q1 = {'A': {'is': brief(st(tA, *IS)), 'oos': brief(st(tA, *OOS))}, 'B': {'is': brief(st(tB, *IS)), 'oos': brief(st(tB, *OOS))},
          'rand_A': {'oos': brief(st(rA, *OOS))}, 'rand_B': {'oos': brief(st(rB, *OOS))},
          'years_A': {y: brief(st(tA, y + '0101', y + '1231')) for y in YEARS},
          'years_B': {y: brief(st(tB, y + '0101', y + '1231')) for y in YEARS}}
    for k in (5, 8):
        tk = book.trades(A & (stc[k] == 0))
        q1[f'B_k{k}'] = {'is': brief(st(tk, *IS)), 'oos': brief(st(tk, *OOS))}
    res['q1'] = q1
    log('Q1', json.dumps({k: q1[k] for k in ('A', 'B')}, ensure_ascii=False))
    # Q2 盤勢：母體＝B
    feat = {d: mk.get(d) or {} for d in dates}
    tB['d8'] = tB['date'].astype(str)
    base_is, base_oos = st(tB, *IS), st(tB, *OOS)
    rand_all = random_same_days(book, pool_ok, tB, reps=5, seed=SEED + 1)
    rand_all['d8'] = rand_all['date'].astype(str)
    fams, tests = {}, {}
    for fk, (fname, buckets) in TM.FAMILIES.items():
        col = tB['d8'].map(lambda d: feat.get(d, {}).get(fk))
        rcol = rand_all['d8'].map(lambda d: feat.get(d, {}).get(fk))
        rows = {}
        for b in buckets:
            sub = tB[col == b]
            rows[b] = {'is': brief(st(sub, *IS)), 'oos': brief(st(sub, *OOS)), 'rand_oos': brief(st(rand_all[rcol == b], *OOS)),
                       'years': {y: brief(st(sub, y + '0101', y + '1231')) for y in YEARS}}
        nodata = int(col.isna().sum())
        ok = [b for b in buckets if rows[b]['is'].get('n', 0) >= RULE['is_n']]
        good = [b for b in ok if rows[b]['is']['mean'] >= base_is['mean']]
        bad = [b for b in ok if rows[b]['is']['mean'] <= base_is['mean']]
        pick = {}
        if good:
            g = max(good, key=lambda b: (rows[b]['is']['win'], rows[b]['is']['mean']))
            pick['good'] = g
            p, ci = month_boot_p(tB[col == g], tB, OOS, reps=BOOT, seed=SEED)
            tests[(fk, 'good')] = (g, p, ci)
        if bad:
            w = min(bad, key=lambda b: (rows[b]['is']['win'], rows[b]['is']['mean']))
            pick['bad'] = w
            p, ci = month_boot_p(tB, tB[col == w], OOS, reps=BOOT, seed=SEED)
            tests[(fk, 'bad')] = (w, p, ci)
        fams[fk] = {'name': fname, 'buckets': rows, 'pick': pick, 'nodata': nodata}
    padj = bh({k: v[1] for k, v in tests.items()}) if tests else {}
    rules = []
    for (fk, side), (b, p, ci) in tests.items():
        o = fams[fk]['buckets'][b]['oos']
        n_ok = o.get('n', 0) >= RULE['oos_n']
        if side == 'good':
            ok = n_ok and o['win'] >= base_oos['win'] + RULE['gap'] and o['mean'] > base_oos['mean']
        else:
            ok = n_ok and o['win'] <= base_oos['win'] - RULE['gap'] and o['mean'] < base_oos['mean']
        rules.append({'family': fk, 'family_name': fams[fk]['name'], 'bucket': b, 'side': side,
                      'is': fams[fk]['buckets'][b]['is'], 'oos': o, 'rand_oos': fams[fk]['buckets'][b]['rand_oos'],
                      'p': round(p, 4), 'p_adj': round(padj[(fk, side)], 4), 'ci': ci,
                      'pass': bool(ok and padj[(fk, side)] < RULE['q'])})
    res['q2'] = {'base': {'is': brief(base_is), 'oos': brief(base_oos)}, 'families': fams, 'rule': RULE}
    res['rules'] = rules
    log('Q2 通過', [(r['family'], r['bucket'], r['side']) for r in rules if r['pass']])
    # Q3 最近＋正式站對照、敏感度
    res['q3'] = recent_check(P, sig, stc, book, feat)
    bump = res['q3'].get('adverse_bump')
    if bump:
        tS = book.trades(Bm, bump=bump)
        tS['d8'] = tS['date'].astype(str)
        sens = []
        bo = st(tS, *OOS)
        for r in rules:
            col = tS['d8'].map(lambda d: feat.get(d, {}).get(r['family']))
            o = st(tS[col == r['bucket']], *OOS)
            sens.append({'family': r['family'], 'bucket': r['bucket'], 'side': r['side'], 'oos': brief(o), 'base_oos': brief(bo)})
        res['sensitivity'] = {'bump': bump, 'rows': sens}
    res['sec'] = round(time.time() - t0)
    return res


def recent_check(P, sig, stc, book, feat):
    """10/20～11/03：正式站尾盤追蹤（13:10 清單）vs 研究收盤版訊號；13:10 價 vs 收盤價"""
    out = {}
    if not os.path.exists(TAIL_JSON):
        return {'note': '沒有正式站清單檔'}
    rows = json.load(open(TAIL_JSON, encoding='utf-8'))['rows']
    dates, sids = list(P['close'].index), list(P['close'].columns)
    di, si = {d: i for i, d in enumerate(dates)}, {s: i for i, s in enumerate(sids)}
    agree, diffs, sk = [], [], []
    for r in rows:
        if r.get('source') != '13:10 假跌破':
            continue
        d8 = r['entry_date'].replace('-', '')
        t, s = di.get(d8), si.get(r['stock_id'])
        if t is None or s is None:
            continue
        agree.append(bool(sig[t, s]))
        cl = book.c[t, s]
        if np.isfinite(cl) and r.get('entry_price'):
            diffs.append(r['entry_price'] / cl - 1)
        sk.append(int(stc[3][t, s]))
    days = sorted({r['entry_date'].replace('-', '') for r in rows})
    research_cnt = {d: int(sig[di[d]].sum()) for d in days if d in di}
    struct_ok_cnt = {d: int((sig[di[d]] & (stc[3][di[d]] == 0)).sum()) for d in days if d in di}
    diffs = np.array(diffs)
    out = {'prod_n': len(agree), 'close_signal_rate': float(np.mean(agree)) if agree else None,
           'price_diff_mean': float(diffs.mean()) if len(diffs) else None, 'price_diff_abs_mean': float(np.abs(diffs).mean()) if len(diffs) else None,
           'price_diff_p10': float(np.percentile(diffs, 10)) if len(diffs) else None, 'price_diff_p90': float(np.percentile(diffs, 90)) if len(diffs) else None,
           'struct_ok_share_prod': float(np.mean([x == 0 for x in sk])) if sk else None,
           'struct_reason_prod': {TM._REASONS[k]: sum(1 for x in sk if x == k) for k in range(5)},
           'research_signals_by_day': research_cnt, 'research_struct_ok_by_day': struct_ok_cnt,
           'market_by_day': {d: {k: feat.get(d, {}).get(k) for k in ('chg', 'M2', 'M4', 'M5', 'M9')} for d in days}}
    # 敏感度：13:10 價跟收盤的差平均幾乎是 0 → 用「絕對值平均」當不利方向的調整（每筆都買貴這麼多，保守）
    out['adverse_bump'] = round(out['price_diff_abs_mean'], 4) if out['price_diff_abs_mean'] else None
    # 正式站實際成績：日線結構合格 vs 不合格（停損的用停損價、其他用 11/03 現價）
    real = {}
    for r in rows:
        if r.get('source') != '13:10 假跌破':
            continue
        t, s = di.get(r['entry_date'].replace('-', '')), si.get(r['stock_id'])
        if t is None or s is None:
            continue
        v = r['stop_ret_pct'] if r['zone'] == 'stop' else r['ret_pct']
        if v is not None:
            real.setdefault('ok' if stc[3][t, s] == 0 else 'ng', []).append(v / 100)
    out['prod_by_struct'] = {k: {'n': len(v), 'mean': float(np.mean(v)), 'win': float(np.mean(np.array(v) > 0))} for k, v in real.items()}
    return out


if __name__ == '__main__':
    res = main()
    with open(os.path.join(HERE, 'results.json'), 'w', encoding='utf-8') as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    from b91_report import write_outputs
    write_outputs(res)
    log('完成', res['sec'], '秒')
