import requests, json, re
H={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/html,*/*"}
s=requests.Session(); s.headers.update(H)
r=s.get("https://www.tpex.org.tw/openapi/v1/bond_ISSBD5_data",timeout=40); d=r.json()
print("ISSBD5",len(d)); print("KEYS",list(d[0].keys()))
for x in d:
    if "台泥" in x.get("ShortName","") or x.get("BondCode")=="11011" or "遠東新" in x.get("ShortName",""):
        print(json.dumps(x,ensure_ascii=False)); 
from collections import Counter
print(Counter(x.get("ListingStatus") for x in d), Counter(x.get("BondType") for x in d))
for u in ["https://www.tpex.org.tw/zh-tw/bond/info/statistics/cb.html","https://www.tpex.org.tw/zh-tw/mainboard/trading/info/pricing.html",
          "https://www.tpex.org.tw/zh-tw/index.html","https://www.tpex.org.tw/zh-tw/bond/index.html"]:
    try:
        r=s.get(u,timeout=30); hs=sorted(set(re.findall(r'href="([^"]*bond[^"]*)"',r.text)))
        print("PAGE",u,r.status_code,len(hs)); [print("  ",h) for h in hs[:200]]
    except Exception as e: print("ERR",u,e)
for meth,u,data in [("POST","https://www.tpex.org.tw/www/zh-tw/bond/cbDaily",{"date":"2026/10/02","response":"json"}),
                    ("GET","https://www.tpex.org.tw/www/zh-tw/bond/cbDaily?date=2026/10/02&response=json",None),
                    ("POST","https://www.tpex.org.tw/www/zh-tw/bond/cbIssue",{"response":"json"}),
                    ("POST","https://www.tpex.org.tw/www/zh-tw/bond/cbInfo",{"response":"json"}),
                    ("POST","https://www.tpex.org.tw/www/zh-tw/bond/cbConvPrice",{"response":"json"}),
                    ("POST","https://www.tpex.org.tw/www/zh-tw/bond/issueCb",{"response":"json"}),
                    ("POST","https://www.tpex.org.tw/www/zh-tw/bond/cbBasic",{"response":"json"})]:
    try:
        r=s.post(u,data=data,timeout=30) if meth=="POST" else s.get(u,timeout=30)
        print("API",meth,u,r.status_code,r.text[:1500].replace("\n"," "))
    except Exception as e: print("ERR",u,e)
