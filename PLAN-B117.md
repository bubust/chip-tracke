# B117：FinMind 金鑰不再寫死在程式裡

## 為什麼
6 個檔案（server.py、chip_tracker_v2.py、positioning／regime／relationship 的 fetcher.py、sector/universe.py）在「沒設環境變數 FINMIND_TOKEN」時，
會改用一組寫死在程式裡的 FinMind 金鑰。金鑰是祕密，應該只放在 GitHub secret／Fly secret。

## 改了什麼
- 6 個檔案的預設值都改成空字串，只從環境變數 `FINMIND_TOKEN` 讀。
- 沒設金鑰時：
  - 單次的小請求（台指期 TX 日 K、產業分類、市場廣度、期貨籌碼…）照樣打 FinMind，用免費額度（FinMind 官方範例也是 token 留空）。
  - 以前「沒金鑰就直接放棄」的兩處（relationship 抓 TX、sector 抓產業清單）改成用免費額度試試。
  - 全市場歷史回填（2,000 多支股票）免費額度不夠，維持原本做法：回「未設定 FINMIND_TOKEN 環境變數」。
- 正式站有設 secret，行為不變。

## 後續（用戶要做）
舊金鑰已經在 git 歷史裡，要到 FinMind 網站換一組新的，再更新 GitHub secret `FINMIND_TOKEN`（部署時會同步到 Fly）。
