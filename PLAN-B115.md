# PLAN-B115：加上證交所公布的「整戶擔保維持率、低於 130% 戶數、補繳、處分（斷頭）」

用戶（11/17）：B114 核對完別的網站的融資表，說「你查」——找整戶維持率、追繳／處分資料的來源，加進網站。

## 資料來源
證交所「台股儀表板」信用交易頁（https://www.twse.com.tw/dashboard/zh/credit/margin.html，2026/9/23 上線），背後的官方 JSON：
- `/rwd/zh/marginTrading/BFIJ3U?response=json[&date=YYYYMMDD]`：單日
- `/rwd/zh/marginTrading/BFIJ3U_TREND?response=json&days=N`：近 N 個交易日（實測 60 天可以；7/1 之前沒有資料）
欄位：keepRate 全市場整戶擔保維持率（上市＋上櫃、融資＋融券合併）、belowAccNum 整戶維持率低於 130% 的戶數、callAccNum／callAmt 當天通知補繳的戶數／金額、
exeAccNum／exeAmt 次一營業日要處分（斷頭）的戶數／金額、marginAccNum／marginAccRate 當天信用交易戶數／占開戶數。

核對：11/16 165.98%、733 戶、3.97 億、247 戶 5.67 億——跟用戶貼的網站一模一樣（他們的「追繳戶數」＝belowAccNum）。
他們的「倍數」（11/16 6.1 倍）大約是 733 ÷ 120，基準不明；網站改用「前 20 天平均的幾倍」。

## 做法
- `wave/data.py`：表 `credit_keep`、`parse_credit_keep`、`update_credit_keep(days=120)`、`load_credit_keep`；跟著 16:30、21:40 的籌碼／融資排程抓
  （`refresh_all(chips=True)`），剛上線資料表空的時候先抓一次。
- `wave/service.credit_out`：最新一天、跟前一天差、近 60 天最低、低於 130% 戶數是前 20 天平均的幾倍、近 60 天明細 → 快照 `margin.credit`。
- 前端 `creditBox`（大盤解析 → 💰 融資餘額）：整戶維持率、低於 130% 戶數、補繳、處分，近 12 天表格（戶數 ≥1,000 或處分 ≥150 戶標橘）；
  融資那一行標題加「整戶 166.0%、斷頭 247 戶」。AI 圓桌多一行資料。
- 只當描述，沒有回測 △。

## 測試
`tests/test_b115_credit.py`：解析（多天、單日、沒資料）、11/16 的數字、倍數。本機截圖確認。
