"""暫時檢查 v4：最終版程式在真實資料上的結果（校正倍數、清單、大盤融資維持率、個股抽查），結果 commit 回分支"""
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
                        for r in t.get('data') or []:
                            cc_ = num(r[ix[2]])
                            if cc_:
                                rows.append((d8, str(r[ix[0]]).strip(), num(r[ix[3]]) or cc_, num(r[ix[4]]) or cc_, num(r[ix[5]]) or cc_, cc_, num(r[ix[6]]) or 0, str(r[ix[1]]).strip()))
                break
            except Exception as e:
                print('px fail', mk, d8, e); time.sleep(10)
        time.sleep(1.1)
    pc.executemany("INSERT OR REPLACE INTO price_daily (date,stock_id,open,high,low,close,volume,name) VALUES (?,?,?,?,?,?,?,?)", rows)
    pc.commit()
pc.close()
print('px done', round(time.time() - t0), flush=True)
def get_df(sid):
    df = price_cache.get_stock_ohlcv(sid, days=120)
    return df if not df.empty else None
p = {x['key']: x['default'] for x in cc.CHIP_PARAMS['S_MAINT_LOW']}
asof, est = MM.compute()
ks = MM.calib(asof)
big = {s: e for s, e in est.items() if e['bal'] >= 300}
ms = sorted(MM.maint_of(e['close'], e['avg'], e['mkt'], ks.get(e['mkt'], 1)) for e in big.values())
out = {'asof': asof, 'days': len(dates), 'calib': ks, 'n_est': len(est), 'market': {k: v for k, v in MM.market_maint().items() if k != 'series'},
       'market_series': MM.market_maint().get('series', [])[-10:],
       'dist': {'n': len(ms), 'p10': ms[len(ms)//10], 'p50': ms[len(ms)//2], 'p90': ms[9*len(ms)//10], 'lt130': sum(m < 130 for m in ms),
                'lt140': sum(m < 140 for m in ms), 'lt150': sum(m < 150 for m in ms)}}
rows = MM.screen(get_df, None, p)
for r in rows: r.pop('bb_score', None); r.pop('note', None)
out['rows140'] = rows
out['check'] = {s: {k: v for k, v in (MM.estimate_one(s) or {}).items() if k != 'series'} for s in ('2330', '2409', '3481', '2303', '2337', '2603', '3105', '8299', '6994', '2317')}
json.dump(out, open('scratch_probe/mt_out.json', 'w'), ensure_ascii=False, indent=1, default=str)
print(json.dumps({k: out[k] for k in ('asof', 'days', 'calib', 'market', 'dist')}, ensure_ascii=False), len(rows), round(time.time() - t0))
