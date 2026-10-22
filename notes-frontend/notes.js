// 📚 上課筆記分頁（dashboard 內嵌）：內容寫在 NOTES 裡，依分類／方向／能不能自動選股呈現；手機單欄、分類列可左右滑
'use strict';

// 分類：t 技術面、c 籌碼面、f 基本面與族群、e 事件（可轉債／收購／增減資）、m 心法、w 波浪（Threads @fanny55520 的數法）
// dir：long 做多、exit 做空／出場、info 觀念
// go：🔍 按鈕跳去的選股策略或分頁（@cb @mna @sector @treasury @regime）；沒有 go＝要自己手動查
// stop：停損／出場規則（一覽表也會用）
const NOTES = [
  // ── 技術面・做多 ──
  { cat: 't', dir: 'long', title: '週 MACD 長線大波段', go: ['S_WMACD'],
    pts: ['週 K 線，MACD 參數改 <b>(10, 20, 50)</b>，搭配 20 週、60 週均線。', '進場：波段大跌後<b>重新站上 20 週線</b>，且週 MACD 柱<b>由綠翻紅</b>。', '持有：無視日 K 波動，沒跌破 20 週線、MACD 沒翻綠就抱牢，目標數倍。'],
    stop: '跌破 20 週線或週 MACD 翻綠 → 全數出場' },
  { cat: 't', dir: 'long', title: '月線斜率（權證小哥）', isNew: true,
    pts: ['月線斜率＝（今天 20 日線 − 昨天 20 日線）÷ 昨天 20 日線。', '<b>>1% 強勢股、>3% 妖股</b>；很陡的月線、股價靠近月線時是不錯的進場點，搭配主力大買更好。', '處置股出關前「浪子回頭」：月線斜率 >1、布林位階 <4。', '看哪裡：觀察清單「月斜率」欄（迷你走勢＋強弱）、深度分析技術分頁。回測：斜率 1～3% 之後 20 天平均比大盤 <b>+2.19%</b>、≥3% <b>+3.46%</b>。'],
    stop: '跌破月線（20MA）或月線轉下彎' },
  { cat: 't', dir: 'long', title: '負乖離（BIAS）極端逆勢抄底', go: ['S_BIAS'],
    pts: ['60BIAS（季線）或 20BIAS（月線）；長多趨勢股用季線負乖離。', '進場：負乖離 <b>−20% 以下</b>（急跌型態勝率最高）。', '確認：「定海神針」（長下影線且不破低）或第一個「向上跳空缺口」。', '分批布局（每跌 3~5% 進一次）。'],
    stop: '10% 硬停損；跌破當日最低或前低' },
  { cat: 't', dir: 'long', title: 'RSI(6) 超賣第一次勾起', go: ['S_RSI_OS'],
    pts: ['RSI(6) 掉到 20 以下後，重新向上勾起突破 20。', '只做<b>第一次</b>勾起，第二次以後無效。', '<b>絕不分批加碼或攤平</b>。'],
    stop: '跌破前波低點立刻出場' },
  { cat: 't', dir: 'long', title: 'RSI(6) 高檔鈍化強勢噴出', go: ['S_RSI_HOT'],
    pts: ['RSI(6) 在 80 以上維持 3 天以上（高檔鈍化）。', '等股價<b>打橫盤整</b>、RSI 仍 ≥ 80、靠近 5 日線時介入。', '只做第一次高檔鈍化。'],
    stop: '跌破 5 日線出場' },
  { cat: 't', dir: 'long', title: '布林(20, 1) 飆股抱牢', go: ['S_BB1'],
    pts: ['布林週期 20，標準差改為 <b>1</b>（預設 2）。', '開布林大漲後股價維持在上軌之外＝極強勢飆股，持續抱牢。'],
    stop: '收盤跌回上軌之內＝立即賣出' },
  { cat: 't', dir: 'long', title: '急跌爆天量＋第一個向上跳空', go: ['S_GAP_BOTTOM'],
    pts: ['急跌後出現數年不見的波段超級大量（換手量）。', '隨後第一個「往上跳空缺口」（收盤不補）。'],
    stop: '缺口當日低點或缺口下緣' },
  { cat: 't', dir: 'long', title: '爆量打開連續跳空漲停', go: ['S_LIMIT_OPEN'],
    pts: ['強大基本面／財報利多（非假消息）、連續跳空漲停買不到的股票。', '漲停板<b>爆大量打開</b>當天可分批掛單介入。'],
    stop: '爆量當日低點' },
  { cat: 't', dir: 'long', title: '破底翻', go: ['S_BREAKBOTTOM'], isNew: true,
    pts: ['一波跌深修正末端，出現一根<b>長黑 K 收在最低點</b>。', '隔天開盤或盤中<b>守住前一天低點、沒再破底</b>＝急跌末端賣壓被吸收，短線反彈進場訊號。', '勝率比不上「短線兩隻腳」。'],
    stop: '長黑 K 的最低點；隔天跌破就失效' },
  { cat: 't', dir: 'long', title: '短線兩隻腳（W 底騙線）', go: ['S2'], isNew: true,
    pts: ['股價創波段低點後短線急彈，再<b>二次回測前低</b>。', '盤中可以跌破前低（洗盤），但<b>收盤一定要收回前低之上</b>：下去不是真的，上去才是真的。', '把散戶洗下車、大戶重新進場，勝率高於單純破底翻。', '回測途中出現<b>大幅向下跳空缺口</b> → 不要盲目抄底。', '⚙️ 系統 S2 已改成你的版本（10/06）：碗公底、10>20>60、第一波攻擊後盤整<b>不破前低</b>、今天突破盤整再攻擊（不再抓「盤中跌破又收回」）。'],
    stop: '第二隻腳的最低點；收盤確認守住前低時進場' },
  { cat: 't', dir: 'long', title: '仙人指路（老大哥）', go: ['S_XIANREN'], isNew: true,
    pts: ['盤整完<b>上攻</b>，當天收一根<b>長上影線</b>（第一次出量）＝主力試盤，往上指路。', '之後<b>繼續盤整</b>幾天：收盤不破那根的低點、還沒衝過上影線頂。', '<b>第二次出量</b>（量 ≥ 均量 1.5 倍、收紅、站上那根的實體）＝要進攻了，這時抓出來。', '漲停鎖住時量反而小，所以出量是跟「仙人指路之前的 20 日均量」比，不跟昨天比。', '例：華新科 2492 10/05 高 396 收 368.5（3.3 倍量）→ 10/06 盤整 → 10/07 漲停 428。', '回測：平均報酬贏大盤，但一半會失敗（贏的抱得大），停損一定要守。'],
    stop: '仙人指路那根的低點（收盤跌破）；上影線頂是第一個壓力' },
  { cat: 't', dir: 'long', title: 'KDJ 低檔轉強（抄底金叉）', go: ['S_KDJ_LOW'], isNew: true,
    pts: ['必須先經過一波<b>大跌修正</b>。', 'K、D 都 <b>&lt; 20</b>（超賣區），且 J <b>&lt; 0</b>（甚至負很多）。', 'J 值<b>往上穿越 K 與 D</b>＝黃金交叉，極端超賣區的轉折買點。', 'J 跟 K、D 黏在一起、沒有明顯開口 → 多觀察一天確認。'],
    stop: '前波最低點，或當天爆大量 K 棒的低點' },
  { cat: 't', dir: 'long', title: '關鍵價突破（N 字型上漲）', go: ['S_NBREAK'], isNew: true,
    pts: ['波段大漲後拉回整理。', '<b>長紅 K 實體帶量突破</b>前波波段高點（頸線壓力）。', '積極：突破當天進場；保守：等回測頸線守住不破再低接。'],
    stop: '跌回頸線下方' },
  { cat: 't', dir: 'long', title: '底部爆量量滾量起漲', go: ['S_VOLROLL'], isNew: true,
    pts: ['股價長期跌深盤整後，<b>重新站上 60MA（季線）</b>。', '成交量出現<b>超越前期 1 倍以上的連續爆量</b>（量滾量）＝主力大戶資金進場。', '量能持續放大是多頭續攻的必要條件；量縮就要小心。'],
    stop: '跌破季線或爆量 K 棒低點' },

  // ── 技術面・做空／出場 ──
  { cat: 't', dir: 'exit', title: '均線趨勢翻空', go: ['S_W60_BREAK', 'S_MA_ALLDOWN'],
    pts: ['週 K 跌破 <b>60 週均線</b>即翻空。', '跌破 5／10／20／60 日所有均線且均線下彎，或大量高點破線轉弱。'],
    stop: '持股出場、不再做多' },
  { cat: 't', dir: 'exit', title: '危險量＋高檔空方缺口', go: ['S_DANGER'],
    pts: ['危險量：近期量再觸及 5~6 年波段高點量水位、高點不過、爆量滯漲 → 預警（系統用可取得的 1~2 年最大量）。', '空方缺口：大漲高檔出現第一個「往下跳空缺口」＝極端反轉賣訊／放空點。'],
    stop: '危險量先減碼；空方缺口出場或放空' },
  { cat: 't', dir: 'exit', title: 'KDJ 高檔轉弱（摸頭賣點）', go: ['S_KDJ_HIGH'], isNew: true,
    pts: ['股價經過大漲波段；K、D <b>&gt; 80</b> 且 J <b>&gt; 100</b>（過熱區）。', 'J 值<b>往下穿越 K 與 D</b>＝死亡交叉。', '<b>高檔鈍化注意</b>：K、D 黏在 80 以上超過 3 天不交叉＝極強趨勢，不可隨意放空、不要太早賣光。'],
    stop: '死叉先賣一半；另一半跌破 5MA／10MA 或月線（20MA）全賣' },
  { cat: 't', dir: 'exit', title: 'KDJ 高檔背離', go: ['S_KDJ_DIV'], isNew: true,
    pts: ['股價<b>創前波新高</b>，但 KDJ 高點<b>低於前波高點</b>，並出現死叉。', '多頭動能衰退，大多頭尾聲容易大回檔。'],
    stop: '逢高減碼或出場避險' },

  // ── 籌碼面 ──
  { cat: 'c', dir: 'long', title: '投信連續買超＋5 日線打橫', go: ['S_TRUST5'],
    pts: ['投信連續買超（中小型電子股勝率最高）。', '強勢股回測 <b>5 日線</b>（不是 10 日線），2~3 天打橫不破 5 日線時介入，停損極短。'],
    stop: '跌破 10 日線或 20 日線出場' },
  { cat: 'c', dir: 'long', title: '強勢股融券大增（拉回買）', go: ['S_SHORT_UP'],
    pts: ['強勢飆股上漲中融券持續大增＝軋空與高檔套利熱絡，股價還有高點，<b>拉回皆為買點</b>。'],
    stop: '近期波段低點' },
  { cat: 'c', dir: 'long', title: '千張大戶增、散戶減', go: ['S_BIGHOLD'],
    pts: ['集保：「千張大戶持股比率」持續上升，「散戶持股比率」創新低＝籌碼高度集中、大戶吃貨。', '系統散戶預設 50 張以下（可在設定改 10／400 張）；集保每週一份，逐週累積。'],
    stop: '大戶比率轉降時減碼' },
  { cat: 'c', dir: 'long', title: '地緣券商選股法', isNew: true,
    pts: ['核心：「凡事有人早知道」。', '查公司<b>總部登記地址</b>，看附近的券商分點（例：高雄公司看高雄當地分點）。', '財報公布前或股價低迷盤整時，地緣分點<b>連續大買、越跌越買</b> → 常預告重大利多或財報佳。', '查法：券商分點進出要到看盤軟體或券商 App 的「分點進出」手動查（系統沒有分點資料）。'],
    stop: '地緣分點在高檔連續大賣時同步離場' },
  { cat: 'c', dir: 'long', title: '跟著基金經理人：投信認養', isNew: true,
    pts: ['到「投信投顧公會」網站找過去 3 個月或 1 年<b>績效前兩名</b>的台股基金。', '比對前後兩個月的前十大持股：某檔<b>新進榜</b>（持股比例 0% → 5~8%）＝投信剛開始大量佈局認養，中長線波段開端。', '查法：投信投顧公會 → 基金資料 → 每月前十大持股（手動）。'],
    stop: '投信持股比例大幅、連續減持時出場' },
  { cat: 'c', dir: 'long', title: '主力投信判讀：跟贏家投信', isNew: true,
    pts: ['不能只看市場總和的「投信買賣超」。', '20 家投信 19 家在賣，但<b>績效第一名的投信逆勢大買</b> → 仍可跟著做中長線布局。', '查法：要看個別投信的買賣明細（券商分點／基金持股），系統只有投信合計（手動）。'],
    stop: '贏家投信轉賣時出場' },
  { cat: 'c', dir: 'exit', title: '融券退潮', go: ['S_SHORT_EBB'],
    pts: ['強勢股在高檔，融券開始連續減少／退潮＝軋空與套利推力消失，拉回不再是買點。'],
    stop: '減碼或出場' },
  { cat: 'c', dir: 'exit', title: '地緣券商／投信高檔連續大賣', go: ['S_TRUST_DUMP'], isNew: true,
    pts: ['股價拉高噴出後，原本進場佈局的<b>地緣分點或主控投信在高檔連續大賣</b>、籌碼出清。', '代表知情人士逢高獲利了結，股價隨後易大幅回檔。', '系統自動抓「投信」這一半；地緣分點要自己查。'],
    stop: '跟著賣出避險' },
  { cat: 'c', dir: 'info', title: '自營商與隔日沖是雜訊',
    pts: ['自營商與隔日沖主力多是 1~2 天短線交易，無連續性，<b>不適合做波段跟隨</b>。'] },

  // ── 基本面與族群 ──
  { cat: 'f', dir: 'long', title: '季報行情三部曲（五大濾網）', go: ['S_VOLROLL'], isNew: true,
    pts: ['① 營收：最新單月或單季營收<b>創新高且 YoY 成長</b>。', '② 獲利：毛利率、營業利益率穩定或向上。', '③ 技術：股價在 <b>60MA（季線）之上</b>。', '④ 成交量：底部出現爆發性大量。', '⑤ 籌碼：投信或外資持續買超護盤。', '系統能自動篩 ③④（🔍＝底部量滾量）；①② 營收、毛利率要自己對財報。'],
    stop: '財報前股價已大跌破季線就不參與' },
  { cat: 'f', dir: 'long', title: '存貨周轉率成長', isNew: true,
    pts: ['存貨周轉率＝銷貨成本 ÷ 平均存貨；越大越好（銷路好、庫存天數短）。', '條件：周轉率<b>季增或 YoY 成長</b>，而且<b>營收同步成長</b>（排除低價清庫存造成的假性上升）。', '做法：同產業、同期（YoY）比較，挑最好的布局（季報手動查）。'],
    stop: '周轉率轉為連續下滑時出場' },
  { cat: 'f', dir: 'long', title: '母以子貴（母子公司連動）', isNew: true,
    pts: ['子公司股價狂飆 → 母公司帳上「未實現投資利益」爆發，滋養母公司財報。', '查子公司的董監持股／大股東名單，確認母公司<b>持股比例高</b>（&gt; 8% 或持有數萬張）。', '子公司買不到或漲多了，改買<b>基期低、持股張數多的母公司</b>布局補漲（手動）。'],
    stop: '子公司轉弱時一起出場' },
  { cat: 'f', dir: 'long', title: '同族群連動（機器位階）', go: ['@sector'], isNew: true,
    pts: ['同產業供應鏈有連動性與資金輪動：指標股大漲 → 資金轉向同族群落後股。', '過濾：歷史 K 線走勢相似度高，且<b>「機器位階」相當</b>（都守住 10MA 或 20MA）。', '指標股創高時，買位階相同但漲幅落後的同族群個股。', '🔍 跳到「產業輪動」看哪個族群在轉強，再自己挑落後股。'],
    stop: '跌破同一條均線（10MA／20MA）出場' },
  { cat: 'f', dir: 'long', title: '財報資本支出（預告 2~3 年後營收）',
    pts: ['看現金流量表「購買不動產、廠房及設備」（資本支出）。', '資本支出較往年<b>成倍翻增</b>（或大規模併購）＝接到大單擴產，營收爆發通常在 2~3 年後。', '市場傳接大單、但資本支出沒增加 → 多半是假消息。'] },
  { cat: 'f', dir: 'exit', title: '存貨周轉率下滑預警', isNew: true,
    pts: ['存貨周轉率<b>連續幾季下滑</b>（例：1.2 → 0.9 → 0.7）＝強烈的營收衰退預告。', '就算眼前月營收還在成長，之後營收與股價都容易大跌，<b>不要逢低承接</b>（手動查季報）。'],
    stop: '出場、不承接' },
  { cat: 'f', dir: 'exit', title: '季報利多出盡／財報前先大跌', isNew: true,
    pts: ['財報公布前股價<b>先大跌一波、跌破月線／季線</b>＝知情人士先走，公布後易利多出盡。', '財報公布後投信轉為連續賣超、成交量萎縮，也是警訊（🔍 投信高檔倒貨可以幫忙抓）。'],
    stop: '不參與／出場' },

  // ── 事件 ──
  { cat: 'e', dir: 'long', title: '可轉債（CB）套利與現股連動', go: ['@cb'],
    pts: ['理論價值＝現股股價 ÷ 轉換價格 × 100。', '市價 &gt; 理論價值（溢價）＝大戶搶購 CB，強烈看好現股（CB 是現股的領先指標）。', '現股高檔且融券大增＝CB 持有者用融券鎖利。', '兩波：定價完成後（開放轉換前有拉抬）、快到期前；發行前公司常壓低股價。', '面額 100 保底：股災時 CB 跌近 100 是極高安全邊際買點。'] },
  { cat: 'e', dir: 'long', title: '企業收購套利：100% 收購＋高溢價', go: ['@mna'],
    pts: ['宣布 100% 股權收購且溢價 15%~30% 以上。', '隔日開盤掛漲停搶購（大單拆成多筆單張掛單）。'],
    stop: '非 100% 收購案在收購期結束後易回落' },
  { cat: 'e', dir: 'long', title: '減資轉機股：Day 2／Day 3 畫線法', go: ['@mna'],
    pts: ['因彌補虧損大舉減資，之後營收與獲利由負轉正 → 容易翻倍。', '恢復交易後看第 2 或第 3 天高低點：突破高點＝買訊。'],
    stop: '跌破第 2／3 天低點出場' },
  { cat: 'e', dir: 'info', title: '現金增資：短空長多與繳款拉抬', go: ['@mna'],
    pts: ['宣布現增短線必然利空（股本稀釋、賣老股換新股）。', '用途「償還債務」且營收不佳 → 避開；體質好、用途「擴充產能」或低點現增 → 長線看好。', '認購繳款日前 1~2 週，公司／大戶有動機拉抬。'] },

  // ── 心法 ──
  { cat: 'm', dir: 'info', title: '停損放哪裡？（各策略整理）',
    pts: ['前低型（兩隻腳、RSI 勾起、KDJ 金叉）：<b>前波最低點</b>。', 'K 棒型（破底翻、漲停打開、爆量）：<b>那根關鍵 K 棒的低點</b>。', '突破型（N 字、平地一聲雷、跳空）：<b>跌回頸線／缺口下緣</b>。', '均線型（週 MACD、量滾量、投信連買）：<b>跌破指定均線</b>（20 週線、季線、10 日線）。', '出場訊號（KDJ 死叉）：<b>先賣一半</b>，另一半等破均線。'] },
  { cat: 'm', dir: 'info', title: '看線不看線（前低防守）',
    pts: ['均線（5 日、10 日、月線）只看方向。', '實際進出以<b>均線附近的近期波段低點</b>當防守價，避免盤中破線的洗盤陷阱。', '觀察清單的「關鍵價位」停損就是用波段低點／前低。'] },
  { cat: 'm', dir: 'info', title: '強勢股別太早下車',
    pts: ['KD 在 80 以上黏住超過 3 天（高檔鈍化）、RSI 高檔鈍化、布林上軌外 → 都是極強趨勢。', '這時只照規則減碼一半，<b>不要逆勢放空、不要一次賣光</b>。'] },
  { cat: 'm', dir: 'info', title: '克服心理錨點（背景價格）',
    pts: ['買進成本是心理錨點：上漲時怕獲利倒吐而<b>太早賣</b>；下跌時幻想彈回成本而<b>不停損</b>。', '拋棄成本觀念，只依客觀規則與當下走勢決策。'] },
  { cat: 'm', dir: 'info', title: '克服錯誤經驗與後見之明',
    pts: ['不要因為「停損後隨即反彈」的經驗就不再停損：<b>一次沒停損可能重創 70% 甚至畢業</b>。', '避免「我早就知道」的後見之明，防範過度自信與頻繁交易。'] },
  { cat: 'm', dir: 'info', title: '資金配置原則',
    pts: ['<b>大壓穩，小壓快</b>：大資金放權值股／穩健標的追求穩定複利；小資金追飆股求速度。', '<b>組合分散</b>：約 3 檔平均分配資金，嚴禁單一標的 100% All-in。'] },

  // ── 波浪實戰（Threads @fanny55520 的台指期數法；系統「總經面板 → 大盤解析 → 🧩 多層浪名」照這套寫成規則）──
  { cat: 'w', dir: 'info', title: '多層浪名：C-1-4-b 怎麼讀', go: ['@regime'], isNew: true,
    pts: ['<b>大的浪裡面再拆小的浪</b>：日線 C 浪 → C 的第 1 段（C-1）→ C-1 的第 4 段（C-1-4）→ 第 4 段裡的 b（C-1-4-b）。', '推動段（1、3、5、A、C）裡面拆成 <b>5 段</b>；修正段（2、4、B）裡面拆成 <b>3 段 a-b-c</b>。', '例：50265 起跌 → 1（48413）→ 2（49479）→ 3 再拆 3-1～3-5（到 46107）→ 4 走 a（47033）、b（46136）、c。', '同一張 60 分圖就可以看到兩、三層，所以每個轉折都要問「它是哪一層的哪一段」。'] },
  { cat: 'w', dir: 'info', title: '主要＋備選：浪名要受盤面證據約束', go: ['@regime'], isNew: true,
    pts: ['波浪不是「怎麼數都可以」：市場揭曉前候選結構可以不只一套，但<b>每一套都要有自己的淘汰價位</b>，不是事後一直改浪名。', '例：主要「C-1-4-c 反彈」、備選「60 分 ABC 走 5-3-5 已在 46107 結束 → C-B 反彈」。', '<b>證據一致就讓原本的數法升權；證據衝突就打開替代結構</b>；盤面已經變質，原本數得再漂亮也要重新命名。', '證據：裸 K（每一步怎麼攻怎麼守、有沒有被拒絕）、量能（推進有沒有資源）、型態（停頓時收斂、換氣、蓄力或派發）、Key level（走到哪個成熟位置）、時間（走足同級波段的長度沒）、籌碼與 OP（只補看，不能主導波浪）。'] },
  { cat: 'w', dir: 'info', title: '轉浪四關（跌深反彈怎麼確認）', go: ['@regime'], isNew: true,
    pts: ['<b>前提</b>：60 分先越過<b>下降趨勢線</b>（起跌高點連第一個反彈高點）＝小級數完成切組。', '<b>第一關</b>：站上前一個反彈高點 → 初步止跌。', '<b>第二關</b>：站穩整段的 <b>0.382</b> → 確認轉浪；站不上 → 這一大段<b>還有第 5 段下跌</b>。', '<b>第三關</b>：<b>0.5～0.618</b> ＋「第 1 段低點領地」（例 48240～48413）＝反彈目標區，原則上在這裡開始下一段主跌。', '漲多回檔反過來看（上升趨勢線、跌破 0.382、0.5～0.618）。'],
    stop: '反彈裡的低點（b）跌破＝這段反彈的數法不成立；跌破極值＝第 5 段' },
  { cat: 'w', dir: 'info', title: '1、4 浪重疊＝推動被化解成三段', go: ['@regime'], isNew: true,
    pts: ['五段推動的規則：<b>第 4 段不能碰到第 1 段的價格區</b>。', '反彈碰到第 1 段低點區 → 下跌只有三段（abc），不是五段推動 → 大一級換成「C-1／C-A 已結束、走 C-2／C-B 反彈」。', '<b>碰不到</b> → 下跌推動還在，<b>一樣要殺第 5 段</b>去破低。', '例外：楔形（傾斜三角形）允許 1、4 重疊，所以還要看各段是不是都是三段。'] },
  { cat: 'w', dir: 'info', title: '目標價：截短 vs 標準', isNew: true,
    pts: ['同一段給兩個落點：<b>截短或失敗</b>的會先到近的價位，<b>標準完成</b>的到遠一點的價位（例：C-1-4-a 截短 46838～46873、標準 47051～47168）。', '第 3 段用延伸（1.618、2.618 倍第 1 段），還有延伸區；第 4 段用下降斜率找臨界點（偏強再加一段）。', '到了近的先觀察「有沒有交代」，沒到遠的就不要急著改數法。'] },
  { cat: 'w', dir: 'long', title: '進場：第一根壓下來上車', isNew: true,
    pts: ['結構還沒確認前，只<b>短線介入、手腳要快</b>。', '等 b 段<b>第一根壓下來不破</b>前低（a 的起點）再上車；成本附近的「<b>多空線</b>」就是防守。', '路徑 A／路徑 B 先寫好：關鍵時間（例 09:45、10:15 收 K）守住某條線走 A（往上看哪幾個價）、跌破走 B（轉成箱體／三角整理或三段提前結束）。'],
    stop: '跌破多空線（成本或 b 的低點）就出場' },
  { cat: 'w', dir: 'info', title: '先辨認級數，再等市場裁決（共同事實 vs 真正分歧）', go: ['@regime'], isNew: true,
    pts: ['每次都先寫<b>共同事實</b>（例：50265 起向下運行），再寫<b>真正分歧</b>（例：第四大波還在修正 vs 五大波已完成、進入更上層修正）。', '每個版本都要列出「<b>市場怎麼裁決</b>」：跌破哪幾個價位才算正式成立（例：大 C 波要依序跌破 47630 → 46574 → 45330）。', '「波浪標記皆為候選」：還沒裁決前不急著選邊，部位照關卡分批。'] },
  { cat: 'w', dir: 'info', title: '日線定位：母尺、防守區、鐵律底線', go: ['@regime'], isNew: true,
    pts: ['用<b>前一段</b>當母尺（例：45330→50265 整組 5-3-1），現在這段是它的回檔。', '0.382＝48380；<b>第一防守區</b>＝0.5（47798）＋前一個橫盤底（47630）；<b>第二極限防守區</b>＝0.618（47215）＋前波頂（46574）。', '<b>鐵律底線</b>＝這一段的起點（45330）：跌破就不是正常回檔，換威脅版本。', '大結構用<b>最大總尺</b>（例：17016→50265）：0.146＝A-1 極限底、0.236＝A-3 基本目標、0.382＝大 A 標準目標、0.5＝極端深跌。'],
    stop: '鐵律底線（這一段的起點）' },
  { cat: 'w', dir: 'info', title: '數到一半變大：級數放大思考', go: ['@regime'], isNew: true,
    pts: ['「這個 60 分的 3 浪<b>不見結束</b>，就要把日線修正幅度<b>放大思考</b>」——原本以為是 C-3，走太長就改成整段只是更大一浪的第 1 段（C-1-3）。', '時間也是證據：第 4 段時間跟第 2 段差太多、或跟第 2 段一樣急（沒有一急一橫的交替），通常還沒走完。', '系統的「浪名演變」會列出每天收盤時怎麼數、哪天換了數法、為什麼換。'] },
  { cat: 'w', dir: 'info', title: '她這兩週的看法怎麼變（照貼文時間）', isNew: true,
    pts: ['<b>10/12</b>：下跌脈動至少要彈過 49253 才看轉脈動；日線 50265＝5-3-1 或 3-2-b 結束，進行 5-3-2A 或 3-2 的 C。', '<b>10/13</b>：主要追蹤「第五浪裡的 3-2 修正」，版本一（48946＝5-3-1）／版本二（50265＝5-3-1，主選）；Fib：48136、48380、47798。', '<b>10/15</b>：日線定位 A（5-3-2 深壓回，防守 47630～47850、46574～47215，鐵律 45330）vs B（大 B 假突破→大 C）；母結構 17016 起漲兩版本；50265 起跌暫定日線 A-1，60 分要走五步。', '<b>10/16</b>：60 分反彈 3-4 或 4，還要探 3-5；站不回 48240～48413 就化解不了下跌推動。', '<b>10/17</b>：46107 附近考慮買 C-4 反彈。<b>10/19</b>：C-1-3 落底、C-1-4-a。<b>10/20</b>：C-1-4-b（備選 3-5-2）。<b>10/21</b>：C-1-4-C（或日線 C-1 落底轉 C-2），走一口留一口。', '<b>10/21 晚</b>：逐漸轉為「60 分 ABC 5-3-5 在 46107 結束」→ 日線 C-1／C-A 結束、醞釀 C-2／C-B；前提越過趨勢線、站穩 47695～47723。'] },
  { cat: 'w', dir: 'exit', title: '出場：走一口留一口、逃命波', isNew: true,
    pts: ['第一個目標到了<b>先走一口、留一口</b>，留的那口<b>防守拉高到多空線</b>。', '逆著大趨勢的反彈（C-2／C-B）<b>目的是逃命</b>：漲得再高也不要過度歡樂，到 0.5～0.618 區分批出。', '<b>盤中轉浪</b>：壓回是「失速」的、出現加速往下推動 → 立刻改判（例：47033 只是 3-5 裡的 2 浪反彈，3 還沒跌完）。'],
    stop: '第二口：跌破拉高後的防守線' },
  // B80：她 9/22～10/8 的貼文（系統「大盤解析」→ 結論卡、價位梯、🔋 量能、🧭 劇本分頁照這幾則寫成規則）
  { cat: 'w', dir: 'info', title: '最後一推的四個跡象（量能）', go: ['@regime'], isNew: true,
    pts: ['新一段上攻如果只是<b>最後一推</b>，通常會出現：<b>漲幅縮小</b>、<b>量能沒有同步擴張</b>、<b>動能背離</b>、<b>突破前高後無法保留成果</b>。', '反過來：突破後<b>斜率、量能同步擴張</b>，而且持續站穩前高 → 比較像內部換氣後續推（例：突破 49240 後）。', '「<b>60 分帶量突破</b> 48296 才把 5-3-2 完成明顯升權」——沒量的突破先當候選。', '系統：圖表分頁 🔋 量能卡逐項打勾（⚠️／✅），並寫這段保留了幾 %（她：保留整段升幅 85.8%）；回測結果照實標 ✅／△。'] },
  { cat: 'w', dir: 'info', title: '三條路：轉強要依序過關、轉弱要依序跌破', go: ['@regime'], isNew: true,
    pts: ['<b>向上取得操作權</b>：先突破 48070 → 再過 48127 → 回測 48070／48095 不破 → 60 分帶量突破 48296 → 才算升權。', '<b>繼續震盪</b>：48070／48127 反覆壓回、47896～48296 持續來回交疊——多空動能消耗在區間裡，會反覆長出 5 分、15 分的短波段。', '<b>偏空變質</b>：跌破 47956 再破 47896 → 反彈收不回 47956，往 47769 測試。', '系統：劇本分頁「🛣️ 三條路」每一步打勾；「⚖️ 如果…就…」寫哪個價位讓哪個版本升權或作廢（她 10/8 的路徑一、二、三）。'] },
  { cat: 'w', dir: 'info', title: '目標 T1／T2／T3 與過渡壓力', go: ['@regime'], isNew: true,
    pts: ['T1＝3 與 1 等長（48830）、T2＝前高區（48927～48946）、T3＝1.618 延伸（49051）；父級 0.5／0.618 投射常跟籌碼價位重疊（50029、50445）。', '<b>T1 是第一個完成度檢查點</b>：到了不急著全出，先確認防守成功的位置；T2 開始處理獲利（15 分延伸目標跟 60 分前高重疊）。', '<b>15 分收穩</b>前高上，才把剩下的目標升到 T3。', '<b>過渡壓力</b>：目標之間容易先震盪換手的地方（例 49900～49920、50190～50210），不要在這裡追。'] },
  { cat: 'w', dir: 'info', title: '修正走完了沒：空間＋時間', go: ['@regime'], isNew: true,
    pts: ['48946→47630 共修正 1316 點，回吐前段約 <b>36.4%（接近 0.382）</b>；時間上跟 45330→48946 的推升接近 <b>1:1</b> → 空間、時間都成熟，具備修正終點的條件。', '反例：50265→49253 只回撤整段 5-3 的 <b>16.5%</b>，空間和時間都不足以完成整個 5-4-A。', '回檔落點照順序看：<b>第一優先既有橫盤</b>（47769～47876）→ 前波高點（47550～47600）→ 0.5（47138）→ 0.618（46711）。', '系統：🔋 量能卡「修正成熟度」、價位梯的「回檔第一／第二／第三落點」和「成交密集區」。'] },
];

const _NOTE_CATS = [
  ['all', '全部'], ['t', '📈 技術面'], ['c', '🧮 籌碼面'], ['f', '🏭 基本面／族群'], ['e', '📰 事件'], ['m', '🧠 心法'], ['w', '🌊 波浪（芬妮）'], ['check', '✅ 下單前檢查'],
];
const _NOTE_DIR = { long: ['做多', '#ef4444'], exit: ['做空／出場', '#22c55e'], info: ['觀念', '#58a6ff'] };
let _notesCat = 'all', _notesDir = '', _notesAuto = false, _notesView = 'card';
try { _notesView = localStorage.getItem('notes_view') || 'card'; } catch (e) {}

function _noteLabel(k) {
  if (k === '@cb') return '可轉債分頁';
  if (k === '@regime') return '大盤解析（多層浪名）';
  if (k === '@mna') return '收購併購分頁';
  if (k === '@sector') return '產業輪動分頁';
  return (typeof STRATEGY_SHORT !== 'undefined' && STRATEGY_SHORT[k]) || k;
}

function notesRender() {
  const root = document.getElementById('notes-root');
  if (!root) return;
  const auto = NOTES.filter(n => n.go).length;
  const cnt = c => NOTES.filter(n => c === 'all' || n.cat === c).length;
  const chip = (on, label, onclick, color = 'var(--accent)') =>
    `<button onclick="${onclick}" style="flex:0 0 auto;cursor:pointer;border-radius:14px;padding:4px 12px;font-size:.8rem;border:1px solid ${on ? color : '#30363d'};background:${on ? color + '22' : 'transparent'};color:${on ? color : 'var(--muted)'}">${label}</button>`;
  const head = `
    <div class="notes-stats">
      <span>共 <b>${NOTES.length}</b> 則</span>
      <span>🤖 能自動選股 <b>${auto}</b></span>
      <span>✍️ 要手動查／觀念 <b>${NOTES.length - auto}</b></span>
      <span>🆕 這次新增 <b>${NOTES.filter(n => n.isNew).length}</b></span>
    </div>
    <div class="notes-bar">${_NOTE_CATS.map(([k, l]) => chip(_notesCat === k, k === 'check' ? l : `${l} <b>${cnt(k)}</b>`, `_notesCat='${k}';notesRender()`)).join('')}</div>
    ${_notesCat === 'check' ? '' : `<div class="notes-bar" style="margin-top:6px">
      ${chip(!_notesDir, '全部方向', "_notesDir='';notesRender()")}
      ${Object.entries(_NOTE_DIR).map(([k, [l, c]]) => chip(_notesDir === k, l, `_notesDir='${k}';notesRender()`, c)).join('')}
      ${chip(_notesAuto, '🤖 只看能自動選股', '_notesAuto=!_notesAuto;notesRender()', '#a78bfa')}
      <span style="flex:0 0 auto;margin-left:auto;display:flex;gap:4px">
        ${chip(_notesView === 'card', '卡片', "_notesSetView('card')", '#94a3b8')}${chip(_notesView === 'list', '一覽表', "_notesSetView('list')", '#94a3b8')}
      </span></div>`}`;
  if (_notesCat === 'check') { root.innerHTML = head + _notesChecklistHtml(); _notesInitChecklist(); return; }
  const rows = NOTES.filter(n => (_notesCat === 'all' || n.cat === _notesCat) && (!_notesDir || n.dir === _notesDir) && (!_notesAuto || n.go));
  if (!rows.length) { root.innerHTML = head + '<div class="muted" style="text-align:center;padding:30px">這個條件沒有筆記</div>'; return; }
  const body = _notesView === 'list' ? _notesListHtml(rows) : _notesCardsHtml(rows);
  root.innerHTML = head + body;
}

function _notesSetView(v) {
  _notesView = v;
  try { localStorage.setItem('notes_view', v); } catch (e) {}
  notesRender();
}

function _noteGoBtns(n, sm = '') {
  return n.go ? n.go.map(k => `<button class="btn sm ghost" style="${sm}" onclick="notesGo('${k}')">🔍 ${_noteLabel(k)}</button>`).join('')
    : '<span class="note-tag" style="color:var(--muted);border-color:#30363d">✍️ 手動查</span>';
}

function _notesCardsHtml(rows) {
  const catName = Object.fromEntries(_NOTE_CATS);
  const groups = [];
  rows.forEach(n => {
    const key = `${n.cat}|${n.dir}`;
    let g = groups.find(x => x.key === key);
    if (!g) groups.push(g = { key, cat: n.cat, dir: n.dir, items: [] });
    g.items.push(n);
  });
  return groups.map(g => {
    const [dl, dc] = _NOTE_DIR[g.dir];
    return `<h3 class="notes-h3">${catName[g.cat]}<span style="color:${dc};font-size:.82rem;margin-left:8px">${dl}</span></h3>
      <div class="note-grid">${g.items.map(n => `
        <div class="note-card" style="border-left:3px solid ${dc}">
          <div class="note-h"><b>${n.title}${n.isNew ? ' <span class="note-tag" style="color:#f59e0b;border-color:#f59e0b66">🆕</span>' : ''}</b></div>
          <ul>${n.pts.map(x => `<li>${x}</li>`).join('')}</ul>
          ${n.stop ? `<div class="note-stop">🛑 ${n.stop}</div>` : ''}
          <div class="note-go">${_noteGoBtns(n)}</div>
        </div>`).join('')}</div>`;
  }).join('');
}

function _notesListHtml(rows) {
  const catName = Object.fromEntries(_NOTE_CATS);
  return `<div class="notes-list">${rows.map(n => {
    const [dl, dc] = _NOTE_DIR[n.dir];
    return `<div class="notes-li">
      <div class="notes-li-t"><span class="note-tag" style="color:${dc};border-color:${dc}66">${dl}</span> <b>${n.title}</b>${n.isNew ? ' 🆕' : ''}
        <span class="muted" style="font-size:.72rem">・${catName[n.cat].replace(/^\S+\s/, '')}</span></div>
      <div class="notes-li-s">${n.stop ? `🛑 ${n.stop}` : '<span class="muted">（觀念，無停損規則）</span>'}</div>
      <div class="notes-li-g">${_noteGoBtns(n, 'padding:1px 8px;font-size:.72rem')}</div>
    </div>`;
  }).join('')}</div>`;
}

const _NOTE_CHECKS = [
  '進場理由是哪一條規則？不是因為「感覺」或聽消息',
  '停損價（前低／長黑低點／頸線／缺口下緣／爆量低點）已經決定，跌破就走',
  '出場條件（破 5 日線／20 週線／KDJ 死叉先賣一半／跌回布林上軌內…）已經寫下來',
  '不看成本價做決定（沒有「等回本再賣」）',
  '這筆資金比例：大資金穩、小資金快；單一標的不超過約 1/3',
  '不是因為上次停損後反彈，這次就不設停損',
  '回測途中有沒有大幅向下跳空缺口？有就不抄底',
];

function _notesChecklistHtml() {
  return `<div class="note-card" id="notes-checklist" style="border-left:3px solid #58a6ff;margin-top:12px">
    <div class="muted" style="font-size:.74rem;margin-bottom:4px">每次下單前勾一遍（勾選只存在這台裝置；按「清空」重來）</div>
    ${_NOTE_CHECKS.map(t => `<label><input type="checkbox"> ${t}</label>`).join('')}
    <div style="text-align:right;margin-top:6px"><button class="btn sm ghost" onclick="notesClearChecklist()">清空</button></div>
  </div>`;
}

function _notesInitChecklist() {
  const boxes = document.querySelectorAll('#notes-checklist input[type=checkbox]');
  let saved = [];
  try { saved = JSON.parse(localStorage.getItem('notes_checklist') || '[]'); } catch (e) {}
  boxes.forEach((b, i) => {
    b.checked = !!saved[i];
    b.onchange = () => { try { localStorage.setItem('notes_checklist', JSON.stringify([...boxes].map(x => x.checked))); } catch (e) {} };
  });
}

function notesClearChecklist() {
  document.querySelectorAll('#notes-checklist input[type=checkbox]').forEach(b => { b.checked = false; });
  try { localStorage.removeItem('notes_checklist'); } catch (e) {}
}

// 🔍：跳到對應選股結果／分頁
function notesGo(k) {
  if (k === '@cb') { switchTab('cb'); return; }
  if (k === '@mna') { switchTab('mna'); return; }
  if (k === '@sector') { switchTab('sector'); return; }
  if (k === '@regime') { switchTab('regime'); return; }
  switchTab('screen');
  setTimeout(() => { viewStrategy(k); document.getElementById('screen-result-card')?.scrollIntoView({ behavior: 'smooth' }); }, 50);
}

function _notesInit() { notesRender(); }
