"""暫時檢查：真實資料回補半年融資流量＋日行情 → 算融資維持率清單（結果 commit 回分支）"""
import json, os, sys, time, datetime as dt
sys.path.insert(0, os.getcwd())
from pathlib import Path
import httpx
import chip_course as cc, margin_maint as MM, price_cache
T = Path('/tmp/mt'); T.mkdir(exist_ok=True)
cc.DB_PATH = T / 'course.db'
price_cache.DB_PATH = T / 'cache.db'
price_cache.init_price_db()
t0 = time.time()
print('margin backfill', MM.backfill(progress=lambda m, k, n: print(m, k, n, flush=True) if k % 20 == 0 else None), round(time.time() - t0))
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'}
cl = httpx.Client(headers=H, timeout=60, follow_redirects=True)
def num(v):
    try: return float(str(v).replace(',', '').strip())
    except Exception: return None
c = cc.get_conn()
dates = [r[0] for r in c.execute("SELECT DISTINCT date FROM margin_flow ORDER BY date")]
c.close()
import sqlite3
pc = sqlite3.connect(str(price_cache.DB_PATH))
for k, ds in enumerate(dates):
    d8 = ds.replace('-', '')
    rows = []
    for attempt in range(3):
        try:
            j = cl.get('https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX', params={'date': d8, 'type': 'ALLBUT0999', 'response': 'json'}).json()
            for t in j.get('tables') or []:
                f = [str(x).strip() for x in (t.get('fields') or [])]
                if '證券代號' in f and '收盤價' in f:
                    ix = {q: f.index(q) for q in ('證券代號', '證券名稱', '成交股數', '開盤價', '最高價', '最低價', '收盤價')}
                    for r in t.get('data') or []:
                        cc_ = num(r[ix['收盤價']])
                        if cc_:
                            rows.append((d8, str(r[ix['證券代號']]).strip(), num(r[ix['開盤價']]) or cc_, num(r[ix['最高價']]) or cc_,
                                         num(r[ix['最低價']]) or cc_, cc_, num(r[ix['成交股數']]) or 0, str(r[ix['證券名稱']]).strip()))
            break
        except Exception as e:
            print('tw px fail', d8, e); time.sleep(10)
    time.sleep(1.2)
    for attempt in range(3):
        try:
            j = cl.get('https://www.tpex.org.tw/www/zh-tw/afterTrading/otc', params={'date': f'{d8[:4]}/{d8[4:6]}/{d8[6:]}', 'type': 'EW', 'response': 'json'}).json()
            for t in j.get('tables') or []:
                f = [str(x).strip() for x in (t.get('fields') or [])]
                if '代號' in f and '收盤' in f:
                    ix = {q: f.index(q) for q in ('代號', '名稱', '收盤', '開盤', '最高', '最低', '成交股數')}
                    for r in t.get('data') or []:
                        cc_ = num(r[ix['收盤']])
                        if cc_:
                            rows.append((d8, str(r[ix['代號']]).strip(), num(r[ix['開盤']]) or cc_, num(r[ix['最高']]) or cc_,
                                         num(r[ix['最低']]) or cc_, cc_, num(r[ix['成交股數']]) or 0, str(r[ix['名稱']]).strip()))
            break
        except Exception as e:
            print('tp px fail', d8, e); time.sleep(10)
    time.sleep(1.0)
    pc.executemany("INSERT OR REPLACE INTO price_daily (date,stock_id,open,high,low,close,volume,name) VALUES (?,?,?,?,?,?,?,?)", rows)
    pc.commit()
    if k % 20 == 0: print('px', ds, len(rows), round(time.time() - t0), flush=True)
pc.close()
def get_df(sid):
    df = price_cache.get_stock_ohlcv(sid, days=120)
    return df if not df.empty else None
p = {x['key']: x['default'] for x in cc.CHIP_PARAMS['S_MAINT_LOW']}
asof, est = MM.compute(min_lots=0)
out = {'asof': asof, 'days': len(dates), 'first': dates[0], 'n_est': len(est)}
out['rows140'] = MM.screen(get_df, None, p)
out['rows150_all'] = MM.screen(get_df, None, {**p, 'max_maint': 150, 'min_lots': 0, 'min_conf': 0, 'min_price': 0})
big = {s: e for s, e in est.items() if e['bal'] >= 300}
ms = sorted(MM.maint_of(e['close'], e['avg'], e['mkt']) for e in big.values())
out['dist'] = {'n': len(ms), 'p10': ms[len(ms)//10], 'p50': ms[len(ms)//2], 'p90': ms[9*len(ms)//10],
               'lt130': sum(m < 130 for m in ms), 'lt140': sum(m < 140 for m in ms), 'lt150': sum(m < 150 for m in ms),
               'conf_p10': sorted(e['conf'] for e in big.values())[len(big)//10]}
out['check'] = {s: {k: (round(v, 3) if isinstance(v, float) else v) for k, v in est[s].items()} | {'maint': round(MM.maint_of(est[s]['close'], est[s]['avg'], est[s]['mkt']), 1)}
                for s in ('2330', '2409', '3481', '2603', '3105', '1101', '2317', '8299') if s in est}
for r in out['rows140'] + out['rows150_all']:
    r.pop('bb_score', None)
json.dump(out, open('scratch_probe/mt_out.json', 'w'), ensure_ascii=False, indent=1, default=str)
print(json.dumps(out['dist'], ensure_ascii=False), len(out['rows140']), round(time.time() - t0))
for r in out['rows140'][:60]:
    print(r['stock_id'], r['name'], r['maint'], r['margin_lots'], r['margin_cost'], r['close'], r['conf'], r['market'])
