import requests, json, re, time, datetime as dt
H={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/html,*/*"}
s=requests.Session(); s.headers.update(H)
API="https://mops.twse.com.tw/mops/api"
hdr={"Content-Type":"application/json","Origin":"https://mops.twse.com.tw","Referer":"https://mops.twse.com.tw/mops/"}
found=0
for d in [dt.date(2026,9,i) for i in (1,2,3,4,8,9,10,15,16,22,23,30)]+[dt.date(2026,8,i) for i in (5,12,19)]:
    r=s.post(f"{API}/t05st02",headers=hdr,json={"year":str(d.year-1911),"month":f"{d.month:02d}","day":f"{d.day:02d}"},timeout=30)
    rows=(r.json().get("result") or {}).get("data") or []
    hits=[x for x in rows if re.search(r"轉換(公司債)?.*價格|轉換價格",str(x[4]))]
    print(d,len(rows),"hits",len(hits))
    for x in hits[:4]: print("   ",x[2],x[3],x[4][:120])
    for x in hits[:2]:
        if found>=5: break
        p=x[5]["parameters"] if isinstance(x[5],dict) else None
        if p:
            rr=s.post(f"{API}/t05st02_detail",headers=hdr,json=p,timeout=30)
            print("DETAIL",json.dumps(rr.json(),ensure_ascii=False)[:1800]); found+=1; time.sleep(1)
    time.sleep(1)
for u,data in [("https://www.tpex.org.tw/www/zh-tw/margin/balance",{"date":"2026/09/30","response":"json"}),
               ("https://www.tpex.org.tw/www/zh-tw/margin/balance",{"date":"115/09/30","response":"json"})]:
    r=s.post(u,data=data,timeout=30); print("TPEXMARGIN",r.status_code,r.text[:1200])
r=s.get("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=20260930&selectType=ALL&response=json",timeout=30)
try:
    j=r.json(); print("TWSEM",j.get("stat"),[ (t.get("title"),t.get("fields"),(t.get("data") or [])[:2]) for t in j.get("tables",[])])
except Exception as e: print("TWSEM ERR",r.status_code,r.text[:300])
r=s.get("https://www.tpex.org.tw/storage/bond_zone/tradeinfo/cb/2026/202610/RSta0113.20261002-C.csv",timeout=30)
t=r.content.decode("big5","replace"); print("CSVTAIL", t[-1500:])
