"""B91 融資維持率正確率驗算（用戶：「融資的部分，再詳細檢查一下正確率」）
交易所沒有公布個股融資金額 → 能對照的真值只有官方每天的「融資買進／賣出／現金償還金額」和「融資金額餘額」（上市、上櫃總數）：
  1. 買進價：Σ 融資買進張數 × 估的買價 × 成數 vs 官方融資買進金額 → 哪一種買價（收盤／(高+低+收)÷3／(高+低)÷2／開盤）每天最穩
  2. 減少：賣出＋現償用「平均成本」扣（現行）vs 官方融資賣出＋現償金額 → 平均成本法偏多少
  3. 餘額：Σ 估計（沒校正）vs 官方融資金額，每天的校正倍數穩不穩
  4. 個股：同一檔用 130 天 vs 260 天估（260 天的期初成本假設影響小很多）→ 估計維持率差多少，依「可信度」分組
資料：margin_maint.backfill（官方 MI_MARGN＋櫃買）存到 data/margin_course.db；股價＝research/b82 官方日行情
用法：python margin_check.py fetch（約 20 分鐘）→ python margin_check.py run"""
import gzip, glob, json, os, sqlite3, sys, time
from contextlib import closing

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
import numpy as np
import pandas as pd
import chip_course as CC
import margin_maint as MM

DB = os.path.join(HERE, 'data', 'margin_course.db')
B82 = os.environ.get('B82_DATA', os.path.join(os.path.dirname(ROOT), 'chip-tracker-b81', 'research', 'b82', 'data'))
CC.DB_PATH = __import__('pathlib').Path(DB)
LONG, SHORT = 260, MM.MAINT_DAYS


def fetch():
    t0 = time.time()
    st = MM.backfill(n_days=LONG, pause=3.0, progress=lambda m, k, n: print(time.strftime('%H:%M:%S'), m, k, n, flush=True) if k % 20 == 0 else None)
    print('done', st, round(time.time() - t0), 's')


def prices():
    """b82 官方日行情 → {sid: {YYYY-MM-DD: (開, 高, 低, 收)}}（最近 300 個交易日）"""
    files = sorted(glob.glob(os.path.join(B82, 'px', '*.t[wp].csv.gz')))
    days = sorted({os.path.basename(f)[:8] for f in files})[-300:]
    out = {}
    for d in days:
        for mk in ('tw', 'tp'):
            f = os.path.join(B82, 'px', f'{d}.{mk}.csv.gz')
            if not os.path.exists(f):
                continue
            df = pd.read_csv(f, dtype={'stock_id': str})
            iso = f'{d[:4]}-{d[4:6]}-{d[6:]}'
            for sid, o, h, l, c in zip(df.stock_id, df.open, df.high, df.low, df.close):
                out.setdefault(sid, {})[iso] = (o, h, l, c)
    return out


def load_flows():
    with closing(sqlite3.connect(DB)) as c:
        dates = [r[0] for r in c.execute("SELECT DISTINCT date FROM margin_flow ORDER BY date")]
        fl = pd.read_sql_query("SELECT date, sid, mkt, buy, sell, repay, prev, bal, off FROM margin_flow", c)
        tot = pd.read_sql_query("SELECT * FROM margin_total", c)
    return dates, fl, tot


def run():
    px = prices()
    dates, fl, tot = load_flows()
    print('融資資料', len(dates), dates[0], dates[-1], '股票', fl.sid.nunique())
    res = {'days': len(dates), 'from': dates[0], 'to': dates[-1]}
    tot = tot.set_index(['date', 'mkt'])
    fl = fl.sort_values(['sid', 'date'])
    # 1. 買進價
    rows = []
    for (d, mk), g in fl.groupby(['date', 'mkt']):
        if (d, mk) not in tot.index:
            continue
        t = tot.loc[(d, mk)]
        if not t['buy_amt_k'] or not t['buy_lots']:
            continue
        s = {'close': 0.0, 'typ': 0.0, 'hl2': 0.0, 'open': 0.0}
        cov = 0.0
        for sid, b in zip(g.sid, g.buy):
            p = px.get(sid, {}).get(d)
            if not p or not b:
                continue
            o, h, l, c = p
            s['close'] += b * c; s['typ'] += b * (h + l + c) / 3; s['hl2'] += b * (h + l) / 2; s['open'] += b * o
            cov += b
        if cov < 0.95 * t['buy_lots']:
            continue
        k = t['buy_lots'] / cov
        rows.append({'date': d, 'mkt': mk, **{f'lev_{n}': t['buy_amt_k'] / (v * k) for n, v in s.items()}})
    bp = pd.DataFrame(rows)
    res['buy_price'] = {mk: {n: {'mean': round(float(g[f'lev_{n}'].mean()), 4), 'cv': round(float(g[f'lev_{n}'].std() / g[f'lev_{n}'].mean()), 4)}
                             for n in ('close', 'typ', 'hl2', 'open')} for mk, g in bp.groupby('mkt')}
    # 2～4：跑兩種長度的估計
    by = {sid: g for sid, g in fl.groupby('sid')}
    meta = fl.drop_duplicates('sid', keep='last').set_index('sid')['mkt'].to_dict()
    asof = dates[-1]
    est = {}
    for win in (SHORT, LONG):
        lo = dates[-min(win, len(dates))]
        e = {}
        for sid, g in by.items():
            g = g[g.date >= lo]
            if g.empty or g.date.iloc[-1] != asof:
                continue
            rows_ = list(zip(g.date, g.buy, g.sell, g.repay, g.prev, g.bal, g.off))
            pp = {d: (v[1], v[2], v[3]) for d, v in px.get(sid, {}).items()}
            x = MM.estimate(rows_, pp, track=True)
            if x:
                x['mkt'] = meta[sid]
                e[sid] = x
        est[win] = e
        print('估計', win, len(e))
    # 3. 餘額：每天 Σ（沒校正）vs 官方（用長版本的 track）
    daily = {}
    for sid, x in est[LONG].items():
        for d, avg, cl, bl in x['series']:
            if avg:
                k = (d, x['mkt'])
                daily[k] = daily.get(k, 0.0) + avg * MM.LEV[x['mkt']] * bl
    cal = []
    for (d, mk), v in sorted(daily.items()):
        if (d, mk) in tot.index and tot.loc[(d, mk)]['amt_k']:
            cal.append({'date': d, 'mkt': mk, 'k': tot.loc[(d, mk)]['amt_k'] / v})
    cal = pd.DataFrame(cal)
    res['calib_series'] = {mk: {'first': round(float(g.k.iloc[0]), 4), 'last': round(float(g.k.iloc[-1]), 4),
                                'last60_mean': round(float(g.k.tail(60).mean()), 4), 'last60_std': round(float(g.k.tail(60).std()), 4),
                                'series': [(d, round(k, 4)) for d, k in zip(g.date.tail(60), g.k.tail(60))]} for mk, g in cal.groupby('mkt')}
    # 2. 減少：平均成本法扣掉的金額 vs 官方賣出＋現償（長版本、最近 60 天）
    red = {}
    for sid, x in est[LONG].items():
        ser = {d: avg for d, avg, cl, bl in x['series'] if avg}
        g = by[sid]
        prev_avg = None
        for d, b, s_, r, off in zip(g.date, g.buy, g.sell, g.repay, g.off):
            if d in ser:
                if prev_avg and d >= dates[-60]:
                    p = px.get(sid, {}).get(d)
                    typ = (p[1] + p[2] + p[3]) / 3 if p else prev_avg
                    k = (d, x['mkt'])
                    red[k] = red.get(k, 0.0) + (max(s_ - off, 0) + r) * prev_avg * MM.LEV[x['mkt']] + off * typ * MM.LEV[x['mkt']]
                prev_avg = ser[d]
    rr = []
    for (d, mk), v in red.items():
        if (d, mk) in tot.index:
            t = tot.loc[(d, mk)]
            off_amt = t['sell_amt_k'] + t['repay_amt_k']
            if v and off_amt:
                rr.append({'date': d, 'mkt': mk, 'ratio': off_amt / v})
    rr = pd.DataFrame(rr)
    res['reduce'] = {mk: {'mean': round(float(g.ratio.mean()), 4), 'std': round(float(g.ratio.std()), 4)} for mk, g in rr.groupby('mkt')}
    # 4. 個股：130 天 vs 260 天
    ks = {mk: float(cal[cal.mkt == mk].k.iloc[-1]) for mk in ('twse', 'tpex') if (cal.mkt == mk).any()}
    cmp = []
    for sid, a in est[SHORT].items():
        b = est[LONG].get(sid)
        if not b or a['bal'] < 300:
            continue
        cl = a['close']
        ma = MM.maint_of(cl, a['avg'], a['mkt'], ks.get(a['mkt'], 1))
        mb = MM.maint_of(cl, b['avg'], b['mkt'], ks.get(b['mkt'], 1))
        cmp.append({'sid': sid, 'conf': a['conf'], 'conf_long': b['conf'], 'm130': ma, 'm260': mb, 'diff': ma - mb})
    cmp = pd.DataFrame(cmp)
    bins = [(0, .5), (.5, .7), (.7, .9), (.9, 1.01)]
    res['stock_window'] = {f'{int(a * 100)}～{min(100, int(b * 100))}%': {
        'n': int(((cmp.conf >= a) & (cmp.conf < b)).sum()),
        'abs_median': round(float(cmp[(cmp.conf >= a) & (cmp.conf < b)]['diff'].abs().median()), 1) if ((cmp.conf >= a) & (cmp.conf < b)).any() else None,
        'abs_p80': round(float(cmp[(cmp.conf >= a) & (cmp.conf < b)]['diff'].abs().quantile(.8)), 1) if ((cmp.conf >= a) & (cmp.conf < b)).any() else None,
        'mean': round(float(cmp[(cmp.conf >= a) & (cmp.conf < b)]['diff'].mean()), 1) if ((cmp.conf >= a) & (cmp.conf < b)).any() else None}
        for a, b in bins}
    res['stock_window_all'] = {'n': len(cmp), 'abs_median': round(float(cmp['diff'].abs().median()), 1),
                               'abs_p80': round(float(cmp['diff'].abs().quantile(.8)), 1),
                               'conf_long_median': round(float(cmp.conf_long.median()), 3)}
    res['calib_now'] = ks
    json.dump(res, open(os.path.join(HERE, 'margin_check.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    print(json.dumps({k: v for k, v in res.items() if k != 'calib_series'}, ensure_ascii=False, indent=1, default=str))
    print({mk: {k: v for k, v in x.items() if k != 'series'} for mk, x in res['calib_series'].items()})


if __name__ == '__main__':
    fetch() if (sys.argv[1:] or ['run'])[0] == 'fetch' else run()
