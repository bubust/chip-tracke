"""暫時檢查：MI_MARGN／櫃買融資餘額的欄位、餘額等式、半年前的日期抓不抓得到"""
import json, time, httpx
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'}
cl = httpx.Client(headers=H, timeout=60, follow_redirects=True)
def num(v):
    try: return float(str(v).replace(',', '').strip())
    except Exception: return None
for d8 in ('20261030', '20260504'):
    j = cl.get('https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN', params={'date': d8, 'selectType': 'ALL', 'response': 'json'}).json()
    print('TWSE', d8, j.get('stat'), [ (t.get('title'), t.get('fields'), t.get('groups')) for t in j.get('tables') or []][:3])
    for t in j.get('tables') or []:
        f = t.get('fields') or []
        if len(f) > 13 and '代號' in str(f[0]):
            rows = t.get('data') or []
            print(' n', len(rows))
            bad = 0
            for r in rows:
                if r[0] in ('2330', '2409', '3481', '2603', '1101'):
                    print('  ', r)
                b, s, rp, pv, bl = (num(r[k]) for k in (2, 3, 4, 5, 6))
                off = num(r[14]) if len(r) > 14 else 0
                if None not in (b, s, rp, pv, bl) and abs(pv + b - s - rp - bl) > 0.5:
                    bad += 1
                    if bad < 4: print('  mismatch', r)
            print(' mismatch count (pv+b-s-rp vs bal)', bad)
    time.sleep(2)
    r = cl.post('https://www.tpex.org.tw/www/zh-tw/margin/balance', data={'date': f'{d8[:4]}/{d8[4:6]}/{d8[6:]}', 'response': 'json'}).json()
    for t in r.get('tables') or []:
        f = t.get('fields') or []
        print('TPEX', d8, t.get('title'), t.get('date'), f, len(t.get('data') or []))
        bad = 0
        for x in t.get('data') or []:
            if x[0] in ('3141', '6488', '8299', '3105', '5347'):
                print('  ', x)
            if '資餘額' in f:
                g = lambda k: num(x[f.index(k)]) if k in f else None
                pv, b, s, rp, bl = g('前資餘額(張)'), g('資買'), g('資賣'), g('現償'), g('資餘額')
                if None not in (pv, b, s, rp, bl) and abs(pv + b - s - rp - bl) > 0.5:
                    bad += 1
                    if bad < 4: print('  mismatch', x)
        print(' mismatch', bad)
    time.sleep(2)
