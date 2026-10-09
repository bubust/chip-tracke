"""正式站產業分類（sector_master／stock_sector_map）→ data/sectors.csv（sector_id,stock_id,name）"""
import csv, os, time
import httpx
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(OUT, exist_ok=True)
BASE = 'https://qiangni-tactics.fly.dev/sector'
secs = httpx.get(BASE + '/api/sectors', timeout=60).json()
secs = secs.get('sectors', secs) if isinstance(secs, dict) else secs
rows = []
for s in secs:
    sid = s['sector_id']
    j = httpx.get(f'{BASE}/api/sector/{sid}/stocks', timeout=60).json()
    st = j.get('stocks', j) if isinstance(j, dict) else j
    for x in st:
        rows.append([sid, x.get('stock_id'), x.get('name')])
    time.sleep(0.3)
with open(os.path.join(OUT, 'sectors.csv'), 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh); w.writerow(['sector_id', 'stock_id', 'name']); w.writerows(rows)
print(len(secs), 'sectors', len(rows), 'rows')
