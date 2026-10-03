import requests, json, re, datetime as dt
H={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/html,*/*"}
def get(u,**k):
    try:
        r=requests.get(u,headers=H,timeout=30,**k); return r
    except Exception as e:
        print("ERR",u,e); return None
for name,url,base in [("TPEX","https://www.tpex.org.tw/openapi/swagger.json","https://www.tpex.org.tw/openapi/v1"),
                      ("TWSE","https://openapi.twse.com.tw/v1/swagger.json","https://openapi.twse.com.tw/v1")]:
    r=get(url)
    if not r: continue
    print("==",name,r.status_code,len(r.text))
    try: sw=r.json()
    except Exception: print(r.text[:300]); continue
    for p,v in sw.get("paths",{}).items():
        summ=" ".join((m.get("summary") or "") for m in v.values() if isinstance(m,dict))
        print(" PATH",p,summ)
        if re.search(r"cb|bond|convert|轉換|債|margin|融資|融券|ap05|營收|股東",p+summ,re.I):
            rr=get(base+p)
            if rr is None: continue
            try:
                d=rr.json(); print("   ->",rr.status_code,len(d), json.dumps(d[:2],ensure_ascii=False)[:900])
            except Exception: print("   ->",rr.status_code,rr.text[:200])
today=dt.date.today()
for i in range(0,6):
    d=today-dt.timedelta(days=i)
    for u in [f"https://www.tpex.org.tw/storage/bond_zone/tradeinfo/cb/{d:%Y}/{d:%Y%m}/RSta0113.{d:%Y%m%d}-C.csv",
              f"https://www.tpex.org.tw/storage/bond_zone/tradeinfo/cb/{d:%Y}/{d:%Y%m}/RSta0113.{d:%Y%m%d}-C.CSV"]:
        r=get(u)
        if r is not None:
            print("CSV",u,r.status_code,len(r.content)); 
            if r.status_code==200: print(r.content[:1500].decode("big5","replace"))
for u in ["https://www.tpex.org.tw/web/bond/publish/convertible_bond_search/memo.php?l=zh-tw",
          "https://www.tpex.org.tw/www/zh-tw/bond/cbIssue",
          "https://www.tpex.org.tw/www/zh-tw/bond/cbDaily",
          "https://www.tpex.org.tw/web/bond/tradeinfo/cb/cb_daily.php?l=zh-tw"]:
    r=get(u)
    if r is not None: print("PAGE",u,r.status_code,r.text[:300].replace("\n"," "))
