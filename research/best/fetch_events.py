"""官方除權息／減資／面額變更事件 → data/events.csv（date,stock_id,prev_close,ref,kind,src）。報酬調整＝prev_close ÷ ref"""
import httpx, time, csv, os, re
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'events.csv')
def num(v):
    try:
        return float(str(v).replace(',', '').strip())
    except ValueError:
        return None
def roc(s):
    m = re.match(r'(\d+)\D+(\d+)\D+(\d+)', s.strip()); y, mo, d = map(int, m.groups())
    return f'{y + 1911:04d}{mo:02d}{d:02d}'
rows = []
for y in range(2021, 2027):
    a, b = f'{y}0101', f'{y}1231'
    j = httpx.get('https://www.twse.com.tw/rwd/zh/exRight/TWT49U', params={'startDate': a, 'endDate': b, 'response': 'json'}, headers=H, timeout=60).json()
    for r in j.get('data') or []:
        rows.append([roc(r[0]), r[1].strip(), num(r[3]), num(r[4]), r[6].strip(), 'twse_div'])
    time.sleep(3)
    j = httpx.get('https://www.twse.com.tw/rwd/zh/reducation/TWTAUU', params={'startDate': a, 'endDate': b, 'response': 'json'}, headers=H, timeout=60).json()
    for r in j.get('data') or []:
        rows.append([roc(r[0]), r[1].strip(), num(r[3]), num(r[4]), '減資', 'twse_red'])
    time.sleep(3)
    j = httpx.get('https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php', params={'l': 'zh-tw', 'd': f'{y - 1911}/01/01', 'ed': f'{y - 1911}/12/31'}, headers=H, timeout=60).json()
    for t in j.get('tables') or []:
        for r in t.get('data') or []:
            rows.append([roc(r[0]), r[1].strip(), num(r[3]), num(r[4]), r[8].strip(), 'tpex_div'])
    time.sleep(3)
    print(y, len(rows), flush=True)
j = httpx.get('https://www.twse.com.tw/rwd/zh/change/TWTB8U', params={'startDate': '20210101', 'endDate': '20261231', 'response': 'json'}, headers=H, timeout=60).json()
for r in j.get('data') or []:
    rows.append([roc(r[0]), r[1].strip(), num(r[3]), num(r[4]), '面額變更', 'twse_par'])
rows = [r for r in rows if r[2] and r[3]]
with open(OUT, 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh); w.writerow(['date', 'stock_id', 'prev_close', 'ref', 'kind', 'src']); w.writerows(rows)
print('DONE', len(rows))
