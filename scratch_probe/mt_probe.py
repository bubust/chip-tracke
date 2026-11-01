"""暫時檢查 v3：用官方融資金額總數驗算個股估計（逐日買進金額、餘額金額）、上櫃融資成數、大盤融資維持率"""
import json, os, sys, time, sqlite3
sys.path.insert(0, os.getcwd())
from pathlib import Path
import httpx
import chip_course as cc, margin_maint as MM, price_cache
T = Path('/tmp/mt'); T.mkdir(exist_ok=True)
cc.DB_PATH = T / 'course.db'
price_cache.DB_PATH = T / 'cache.db'
price_cache.init_price_db()
t0 = time.time()
print('backfill', MM.backfill(), round(time.time() - t0), flush=True)
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'}
cl = httpx.Client(headers=H, timeout=60, follow_redirects=True)
def num(v):
    try: return float(str(v).replace(',', '').strip())
    except Exception: return None
c = cc.get_conn()
dates = [r[0] for r in c.execute("SELECT DISTINCT date FROM margin_flow ORDER BY date")]
c.close()
pc = sqlite3.connect(str(price_cache.DB_PATH))
vw = {}
for k, ds in enumerate(dates):
    d8 = ds.replace('-', '')
    rows = []
    for mk, url, kw in (('tw', 'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX', {'date': d8, 'type': 'ALLBUT0999', 'response': 'json'}),
                        ('tp', 'https://www.tpex.org.tw/www/zh-tw/afterTrading/otc', {'date': f'{d8[:4]}/{d8[4:6]}/{d8[6:]}', 'type': 'EW', 'response': 'json'})):
        for attempt in range(3):
            try:
                j = cl.get(url, params=kw).json()
                for t in j.get('tables') or []:
                    f = [str(x).strip() for x in (t.get('fields') or [])]
                    names = (('證券代號', '證券名稱', '收盤價', '開盤價', '最高價', '最低價', '成交股數') if mk == 'tw' else ('代號', '名稱', '收盤', '開盤', '最高', '最低', '成交股數'))
                    if all(q in f for q in names):
                        ix = [f.index(q) for q in names]
                        ia = next((i for i, q in enumerate(f) if q.startswith('成交金額')), None)
                        for r in t.get('data') or []:
                            cc_ = num(r[ix[2]])
                            if not cc_: continue
                            sid = str(r[ix[0]]).strip()
                            vol = num(r[ix[6]]) or 0
                            rows.append((d8, sid, num(r[ix[3]]) or cc_, num(r[ix[4]]) or cc_, num(r[ix[5]]) or cc_, cc_, vol, str(r[ix[1]]).strip()))
                            amt = num(r[ia]) if ia is not None else None
                            if amt and vol: vw[(ds, sid)] = amt / vol
                break
            except Exception as e:
                print('px fail', mk, d8, e); time.sleep(10)
        time.sleep(1.1)
    pc.executemany("INSERT OR REPLACE INTO price_daily (date,stock_id,open,high,low,close,volume,name) VALUES (?,?,?,?,?,?,?,?)", rows)
    pc.commit()
    if k % 25 == 0: print('px', ds, len(rows), round(time.time() - t0), flush=True)
pc.close()
c = cc.get_conn()
tot = {(d, m): (bl, amt, bl_, ba) for d, m, bl, amt, bl_, ba in c.execute("SELECT date, mkt, bal_lots, amt_k, buy_lots, buy_amt_k FROM margin_total")}
flow = {}
for d, sid, mk, b, bal in c.execute("SELECT date, sid, mkt, buy, bal FROM margin_flow"):
    flow.setdefault((d, mk), []).append((sid, b, bal))
c.close()
pc = sqlite3.connect(str(price_cache.DB_PATH))
px = {(d, s): (h, l, cl_) for d, s, h, l, cl_ in pc.execute("SELECT date, stock_id, high, low, close FROM price_daily")}
pc.close()
iso = lambda d8: f"{d8[:4]}-{d8[4:6]}-{d8[6:]}"
px = {(iso(d), s): v for (d, s), v in px.items()}
# ① 逐日買進金額：Σ 買進張數 × 1000 × 價 × 成數 vs 官方
print('n totals', len(tot), 'dates', len(dates))
res = {'buy': {}, 'bal': {}, 'maint': {}}
for mk in ('twse', 'tpex'):
    rs = []
    for d in dates[-60:]:
        if (d, mk) not in tot: continue
        _, _, bl_, ba = tot[(d, mk)]
        s_typ = s_vw = s_cl = 0.0; miss = 0.0
        for sid, b, _ in flow.get((d, mk), []):
            p = px.get((d, sid))
            if not p or not b: miss += b or 0; continue
            typ = (p[0] + p[1] + p[2]) / 3
            s_typ += b * typ; s_cl += b * p[2]; s_vw += b * vw.get((d, sid), typ)
        cov = 1 - miss / max(bl_, 1)
        rs.append((d, ba * 1000 / (s_typ * 1000) if s_typ else None, ba / s_vw if s_vw else None, ba / s_cl if s_cl else None, round(cov, 3)))
    # 官方買進金額 ÷（Σ 張 × 價）＝實際的成數
    vals = [r[2] for r in rs if r[2]]
    vals_t = [r[1] for r in rs if r[1]]
    res['buy'][mk] = {'implied_lev_vwap_median': sorted(vals)[len(vals)//2] if vals else None,
                      'implied_lev_typ_median': sorted(vals_t)[len(vals_t)//2] if vals_t else None,
                      'sample': rs[-5:]}
    print('BUY', mk, json.dumps(res['buy'][mk], ensure_ascii=False), flush=True)
# ② 餘額金額：Σ 估計平均成本 × 成數 × 張 vs 官方（asof、30 天前、60 天前）
c = cc.get_conn()
allrows = {}
for d, sid, mk, nm, b, s, r, pv, bl, off in c.execute("SELECT date, sid, mkt, name, buy, sell, repay, prev, bal, off FROM margin_flow ORDER BY sid, date"):
    allrows.setdefault(sid, (mk, []))[1].append((d, b, s, r, pv, bl, off))
c.close()
byid = {}
for (d, s), v in px.items():
    byid.setdefault(s, {})[d] = v
for back in (60, 30, 0):
    at = dates[-1 - back]
    for mk in ('twse', 'tpex'):
        s_amt = {0.5: 0.0, 0.6: 0.0}; s_mv = 0.0; lots_cov = 0.0
        for sid, (m, rows) in allrows.items():
            if m != mk: continue
            rr = [x for x in rows if x[0] <= at][-MM.MAINT_DAYS:]
            if not rr or rr[-1][0] != at: continue
            e = MM.estimate(rr, byid.get(sid, {}))
            if not e: continue
            for lv in s_amt: s_amt[lv] += e['avg'] * lv * e['bal']
            s_mv += e['close'] * e['bal']; lots_cov += e['bal']
        bl, amt, _, _ = tot.get((at, mk), (None, None, None, None))
        if not amt: continue
        cov = lots_cov / bl
        res['bal'][f'{mk}-{at}'] = {'official_amt_yi': round(amt / 1e5, 1), 'est_amt_yi_0.6': round(s_amt[0.6] / 1e2 / cov, 1),
                                    'est_amt_yi_0.5': round(s_amt[0.5] / 1e2 / cov, 1), 'coverage': round(cov, 3),
                                    'ratio_0.6': round(amt / (s_amt[0.6] / cov), 3), 'ratio_0.5': round(amt / (s_amt[0.5] / cov), 3),
                                    'market_maint_official': round(s_mv / cov / amt * 100, 1)}
        print('BAL', mk, at, json.dumps(res['bal'][f'{mk}-{at}']), flush=True)
# ③ 整體
for at in dates[-5:]:
    mv = amt = 0.0
    for mk in ('twse', 'tpex'):
        bl, a, _, _ = tot.get((at, mk), (None, None, None, None))
        if not a: continue
        m_ = c_ = 0.0
        for sid, b, bal in flow.get((at, mk), []):
            p = px.get((at, sid))
            if p and bal: m_ += bal * p[2]; c_ += bal
        mv += m_ / (c_ / bl); amt += a
    res['maint'][at] = round(mv / amt * 100, 1) if amt else None
print('MAINT all', res['maint'])
print('t', round(time.time() - t0))
