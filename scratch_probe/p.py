import requests
j=requests.get("https://openapi.tdcc.com.tw/v1/opendata/1-5",timeout=120,headers={"User-Agent":"Mozilla/5.0"}).json()
ks=list(j[0].keys()); print(ks)
sk=[k for k in ks if "代號" in k][0]
for sid in ("2330","6214"):
    rows=[x for x in j if x[sk].strip()==sid]
    for r in rows: print(sid, {k.strip('﻿'):v for k,v in r.items()})
