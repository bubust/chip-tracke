"""暫時檢查 v2：①官方融資金額總數 vs 每檔估計加總 ②櫃買總額來源、上櫃融資成數 ③不同估法比較"""
import json, os, sys, time, re
sys.path.insert(0, os.getcwd())
from pathlib import Path
import httpx
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'}
cl = httpx.Client(headers=H, timeout=60, follow_redirects=True)
def num(v):
    try: return float(str(v).replace(',', '').strip())
    except Exception: return None
# ① TWSE 信用交易統計
j = cl.get('https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN', params={'date': '20261030', 'selectType': 'ALL', 'response': 'json'}).json()
print('TWSE T1', j['tables'][0].get('fields'), j['tables'][0].get('data'))
print('TWSE notes', j.get('notes') or j['tables'][1].get('notes'))
from collections import Counter
print('註記', Counter(str(r[15]).strip() for r in j['tables'][1]['data']).most_common(10))
time.sleep(2)
# ② TPEx：balance 回應的其他欄位；openapi 清單裡跟融資有關的
r = cl.post('https://www.tpex.org.tw/www/zh-tw/margin/balance', data={'date': '2026/10/30', 'response': 'json'}).json()
print('TPEX keys', list(r.keys()), [(k, (v if not isinstance(v, (list, dict)) else type(v).__name__)) for k, v in r.items() if k != 'tables'])
for t in r.get('tables') or []:
    print(' table', t.get('title'), {k: (v if k != 'data' else len(v)) for k, v in t.items() if k not in ('fields',)})
    if t.get('summary'): print('  summary', t.get('summary'))
    print('  last rows', (t.get('data') or [])[-2:])
time.sleep(2)
try:
    sw = cl.get('https://www.tpex.org.tw/openapi/swagger.json').json()
    for pth, v in sw.get('paths', {}).items():
        s = json.dumps(v, ensure_ascii=False)
        if 'margin' in pth.lower() or '融資' in s:
            print('OPENAPI', pth, re.findall(r'"summary": "([^"]+)"', s)[:1])
except Exception as e:
    print('swagger fail', e)
for u, kw in (('https://www.tpex.org.tw/www/zh-tw/margin/sum', {}), ('https://www.tpex.org.tw/www/zh-tw/margin/mark', {}),
              ('https://www.tpex.org.tw/www/zh-tw/margin/total', {})):
    try:
        x = cl.post(u, data={'date': '2026/10/30', 'response': 'json'})
        print('TRY', u, x.status_code, x.text[:600].replace('\n', ' '))
    except Exception as e:
        print('TRY', u, e)
    time.sleep(1.5)
