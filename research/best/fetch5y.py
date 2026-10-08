"""5 年官方日行情（研究用，存本機，不碰正式站）：證交所 MI_INDEX（個股＋加權指數）、櫃買 otc。
每天一個檔 data/YYYYMMDD.csv.gz（休市日寫 data/YYYYMMDD.closed），可中斷續抓。
欄位：date,stock_id,name,open,high,low,close,volume(張),chg（漲跌，對除權息參考價；不能比較＝空）
加權指數另存 data/taiex.csv（date,close）"""
import datetime, gzip, csv, os, sys, time
import httpx

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(OUT, exist_ok=True)
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'}
START = datetime.date(*map(int, (sys.argv[1] if len(sys.argv) > 1 else '2021-10-01').split('-')))
END = datetime.date(*map(int, (sys.argv[2] if len(sys.argv) > 2 else '2026-10-08').split('-')))


def num(v):
    try:
        x = float(str(v).replace(',', '').strip())
        return x
    except Exception:
        return None


def twse(d8):
    j = httpx.get('https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX',
                  params={'date': d8, 'type': 'ALLBUT0999', 'response': 'json'}, headers=H, timeout=60).json()
    if '沒有符合條件' in str(j.get('stat', '')):
        return 'closed', [], None
    rows, taiex = [], None
    for t in j.get('tables') or []:
        f = [str(x).strip() for x in (t.get('fields') or [])]
        title = str(t.get('title') or '')
        if '價格指數' in title and '臺灣證券交易所' in title:
            for r in t.get('data') or []:
                if str(r[0]).strip() == '發行量加權股價指數':
                    taiex = num(r[1])
        if '證券代號' in f and '收盤價' in f:
            ix = {k: f.index(k) for k in ('證券代號', '證券名稱', '成交股數', '開盤價', '最高價', '最低價', '收盤價', '漲跌(+/-)', '漲跌價差')}
            for r in t.get('data') or []:
                c = num(r[ix['收盤價']])
                if not c:
                    continue
                sign = str(r[ix['漲跌(+/-)']])
                diff = num(r[ix['漲跌價差']])
                chg = None if ('X' in sign or diff is None) else (-diff if '-' in sign else diff)
                rows.append([d8, str(r[ix['證券代號']]).strip(), str(r[ix['證券名稱']]).strip(),
                             num(r[ix['開盤價']]) or c, num(r[ix['最高價']]) or c, num(r[ix['最低價']]) or c, c,
                             round((num(r[ix['成交股數']]) or 0) / 1000), chg])
    if not rows:
        raise RuntimeError('twse 沒有個股表')
    return 'ok', rows, taiex


def tpex(d8):
    j = httpx.get('https://www.tpex.org.tw/www/zh-tw/afterTrading/otc',
                  params={'date': f'{d8[:4]}/{d8[4:6]}/{d8[6:]}', 'type': 'EW', 'response': 'json'}, headers=H, timeout=60).json()
    rows = []
    for t in j.get('tables') or []:
        f = [str(x).strip() for x in (t.get('fields') or [])]
        if '代號' in f and '收盤' in f:
            ix = {k: f.index(k) for k in ('代號', '名稱', '收盤', '漲跌', '開盤', '最高', '最低', '成交股數')}
            for r in t.get('data') or []:
                c = num(r[ix['收盤']])
                if not c:
                    continue
                rows.append([d8, str(r[ix['代號']]).strip(), str(r[ix['名稱']]).strip(),
                             num(r[ix['開盤']]) or c, num(r[ix['最高']]) or c, num(r[ix['最低']]) or c, c,
                             round((num(r[ix['成交股數']]) or 0) / 1000), num(r[ix['漲跌']])])
    return rows


d = START
taiex_path = os.path.join(OUT, 'taiex.csv')
while d <= END:
    d8 = d.strftime('%Y%m%d')
    out, closed = os.path.join(OUT, d8 + '.csv.gz'), os.path.join(OUT, d8 + '.closed')
    if d.weekday() < 5 and not os.path.exists(out) and not os.path.exists(closed):
        for attempt in range(4):
            try:
                st, rows, tx = twse(d8)
                time.sleep(3)
                if st == 'closed':
                    open(closed, 'w').close()
                    print(d8, '休市', flush=True)
                    break
                rows += tpex(d8)
                time.sleep(2)
                with gzip.open(out + '.tmp', 'wt', newline='', encoding='utf-8') as fh:
                    w = csv.writer(fh)
                    w.writerow(['date', 'stock_id', 'name', 'open', 'high', 'low', 'close', 'volume', 'chg'])
                    w.writerows(rows)
                os.replace(out + '.tmp', out)
                if tx:
                    with open(taiex_path, 'a', encoding='utf-8') as fh:
                        fh.write(f'{d8},{tx}\n')
                print(d8, len(rows), '檔', '加權', tx, flush=True)
                break
            except Exception as e:
                print(d8, '失敗', attempt, type(e).__name__, str(e)[:80], flush=True)
                time.sleep(20 * (attempt + 1))
    d += datetime.timedelta(days=1)
print('DONE', flush=True)
