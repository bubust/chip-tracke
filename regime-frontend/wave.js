// 🌊 大盤解析（PLAN-B74；B75：加權／台指期切換、分 K、轉折點、期貨＋籌碼；B76：每個週期自己的解析；B79：多層浪名）
// B80（10-22 用戶：「版面好混亂，又很多重複的資訊」）：結論卡＋頁內分頁（圖表／劇本／籌碼／AI／總經），每樣資訊只放一個地方；
//   15 分 K；成交量（K 線下方量柱、相對量、最後一推、修正成熟度、帶量突破、成交密集區）；價位梯、如果…就…、三條路、版本樹
// B81（10-22 用戶：「讓我清楚知道現在的價位進去，支撐壓力在哪邊可以試單，拆解她的進出場」）：🎯 試單地圖（結論卡一行＋劇本分頁拆解）、
//   停損格不空白、兩種數法方向不同時明講、量能那行白話、手機三格橫排
// 顏色：漲／壓力＝紅 var(--up)、跌／支撐＝綠 var(--down)、轉折點＝橘、費波那契＝紫
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = v => (v == null || v === '' || !isFinite(Number(v))) ? null : Number(v);
  const fmt = (v, nd = 0) => num(v) == null ? '—' : Number(v).toLocaleString('zh-TW', { minimumFractionDigits: nd, maximumFractionDigits: nd });
  const pctS = (v, nd = 2) => num(v) == null ? '—' : (v > 0 ? '+' : '') + Number(v).toFixed(nd) + '%';
  const sgn = (v, nd = 0) => num(v) == null ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + fmt(Math.abs(v), nd);
  const rateS = v => num(v) == null ? '—' : (v * 100).toFixed(0) + '%';
  const md = d => d && d.length >= 10 ? `${+d.slice(5, 7)}/${+d.slice(8, 10)}` : (d || '');
  const cssVar = (k, d) => (getComputedStyle(document.documentElement).getPropertyValue(k) || '').trim() || d;
  const C = { up: cssVar('--up', '#f04848'), down: cssVar('--down', '#22c55e'), warn: '#fb923c', muted: '#94a3b8', accent: '#5b8cff', fib: '#a78bfa', grid: 'rgba(148,163,184,.07)' };
  const lsGet = (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* 私密模式 */ } };
  const colorOf = v => num(v) == null ? 'var(--muted)' : v > 0 ? 'var(--up)' : v < 0 ? 'var(--down)' : 'var(--muted)';
  const DEG_NAME = { intra15: '15 分 K 級數', intra30: '30 分 K 級數', intra: '60 分 K 級數', small: '小級（日 K）', mid: '中級（週 K）', big: '大級（長期）' };
  // 每個週期：lv／key＝快照 levels／key 的鍵（舊名：ultra＝60 分、short＝日 K、swing＝週 K）、wv＝waves 的鍵、nest＝多層浪名的鍵
  const TF = {
    '15m': { name: '15 分', hz: '當沖', lv: 'm15', wv: 'intra15', chart: 'i15', intra: true, win: '1.5%', nest: '15m' },
    '30m': { name: '30 分', hz: '當沖～隔天', lv: 'm30', wv: 'intra30', chart: 'i30', intra: true, win: '2%', nest: '30m' },
    '60m': { name: '60 分', hz: '1～3 天', lv: 'ultra', wv: 'intra', chart: 'i60', intra: true, win: '3%', nest: '60m' },
    '1d': { name: '日 K', hz: '1～2 週', lv: 'short', wv: 'small', chart: 'bars', intra: false, win: '6%' },
    '1wk': { name: '週 K', hz: '1～3 個月', lv: 'swing', wv: 'mid', chart: 'weekly', intra: false, win: '15%' },
  };
  const OLD_MODE = { ultra: '60m', short: '1d', swing: '1wk' };
  const TABS = ['chart', 'plan', 'chips', 'ai', 'macro'];
  // 台北時間（分 K 用 UTC epoch，不依賴瀏覽器時區）
  const TPE = { timeZone: 'Asia/Taipei', hour12: false };
  const fmtTpe = (ts, opt) => new Intl.DateTimeFormat('zh-TW', { ...TPE, ...opt }).format(new Date(ts * 1000));
  const hm = ts => fmtTpe(ts, { hour: '2-digit', minute: '2-digit' });
  const mdhm = ts => fmtTpe(ts, { month: 'numeric', day: 'numeric' }) + ' ' + hm(ts);
  const stanceBg = s => /多/.test(s || '') ? 'rgba(240,72,72,.15)' : /空/.test(s || '') ? 'rgba(34,197,94,.15)' : 'rgba(148,163,184,.15)';

  const DATA = {};
  let S = null, panelData = null;
  const st = { sym: lsGet('wv_sym', 'TWII'), tf: lsGet('wv_tf', OLD_MODE[lsGet('wv_mode', '')] || '1d'), degSel: lsGet('wv_deg2', 'auto'), alt: false,
               show: { fib: false, tg: false, inv: false, cone: false, nest: lsGet('wv_nest_show', '1') === '1' }, tab: lsGet('wv_tab', 'chart') };
  if (!TF[st.tf]) st.tf = '1d';
  if (!['TWII', 'TX'].includes(st.sym)) st.sym = 'TWII';
  if (!TABS.includes(st.tab)) st.tab = 'chart';           // 存的值不對 → 圖表（審查 R3 Groq S2）
  const T_ = () => TF[st.tf];
  // 進階「自己選級數」只影響日 K／週 K（分 K 一律用自己的級數）
  const deg = () => T_().intra || st.degSel === 'auto' ? T_().wv : st.degSel;
  const intraIv = () => T_().intra;
  const wv = d => ((S && S.waves) || {})[d] || {};
  const nestOf = tf => (TF[tf] && TF[tf].nest) ? (((S && S.nest) || {})[TF[tf].nest] || null) : null;
  const lmOf = tf => ((S && S.levelmap) || {})[tf] || null;
  const volOf = tf => ((S && S.volume) || {})[tf] || null;
  const vres = k => ((((S && S.research) || {}).volume) || {})[k] || {};
  // 分 K（15／30／60 分）看 60 分 K 的回測、日 K／週 K 看日 K 的回測
  const vpass = k => !!(TF[st.tf] && TF[st.tf].intra ? vres(k).pass_d2 : vres(k).pass_d1);
  const resTag = k => vpass(k) ? '<span class="wv-ok" title="回測通過">✅</span>' : '<span class="wv-ref" title="回測跟隨機差不多，只當參考">△</span>';
  let chart = null, chartKind = null, candle = null, ma = {}, zz = null, cone = [], pls = [], panelPoll = null, tline = null, vol = null, vma = {};

  // ── 波浪 → 白話 ──
  // B78 複合修正 W-X-Y（-X-Z）、三角形、楔形（文字跟 wave/plain.py 同一套）
  const COMBO_LB = ['Wa', 'Wb', 'W', 'X', 'Ya', 'Yb', 'Y', 'X2', 'Za', 'Zb', 'Z'];
  const COMBO_DISP = ['a', 'b', 'W', 'X', 'a', 'b', 'Y', 'X', 'a', 'b', 'Z'];
  function plainComplex(c, cur, up) {
    if (c.kind === 'combo') {
      const [dn, rb] = up ? ['反彈', '回落'] : ['下跌', '反彈'];
      const head = up ? '複合反彈' : '複合修正';
      const three = up ? '「彈－回－彈」' : '「跌－彈－跌」';
      const end = up ? '可能再往下' : '修正可能結束、重新開始上漲';
      const T = {
        X: [`${head}中的${rb}（X 浪）`, `第一組${three}（W）走完了，這段是中間的連接；照規則後面還有第二組（Y）`],
        Ya: [`${head}・第二組的第一段${dn}（Y 的 a）`, '修正拉長成兩組三段（W-X-Y），這是第二組的開始'],
        Yb: [`${head}・第二組中的${rb}（Y 的 b）`, `${rb}走完，照規則還有最後一段${dn}（Y 的 c）`],
        Y: [`${head}的最後一段${dn}（Y 的 c）`, `這段走完，兩組修正（W-X-Y）${end}；也可能再接一個 X 變成三組`],
        X2: [`${head}中的第二次${rb}（第二個 X）`, '已經走了兩組三段（W、Y），這段連接到第三組（Z）；三組是上限'],
        Za: [`${head}・第三組的第一段${dn}（Z 的 a）`, '修正拉長成三組三段（W-X-Y-X-Z），這是最後一組的開始'],
        Zb: [`${head}・第三組中的${rb}（Z 的 b）`, `${rb}走完，照規則還有最後一段${dn}（Z 的 c）`],
        Z: [`${head}的最後一段${dn}（Z 的 c）`, `三組是修正的上限，這段走完${end}`] };
      const idx = COMBO_LB.indexOf(cur);
      if (!T[cur] || idx < 0) return null;
      return { title: T[cur][0], meaning: T[cur][1], steps: COMBO_DISP.slice(0, idx >= 7 ? 11 : 7), idx };
    }
    if (c.kind === 'triangle') {
      const shape = c.corr_kind === 'expanding' ? '擴散' : '收斂';
      const way = up ? '往下' : '往上';
      const swing = c.corr_kind === 'expanding' ? '上下震盪越來越大' : '上下震盪越來越小';
      const T = {
        D: [`${shape}三角形整理・第 4 段（D）`, `盤整走五段（A-B-C-D-E）${swing}，後面還有 E；走完通常${way}突破（順著原本的方向）`],
        E: [`${shape}三角形整理・最後一段（E）`, `E 走完通常${way}突破，幅度大約是三角形最寬那段（A）`] };
      if (!T[cur]) return null;
      return { title: T[cur][0], meaning: T[cur][1], steps: ['A', 'B', 'C', 'D', 'E'], cur };
    }
    const T = {
      '4': [up ? '上升楔形・第 4 段回檔' : '下跌楔形・第 4 段反彈',
            up ? '越漲越弱的五段（第 4 段可以跌進第 1 段的價格區），後面還有第 5 段上漲；照教科書，楔形走完常快速跌回起點附近'
               : '越跌越弱的五段（第 4 段可以彈進第 1 段的價格區），後面還有第 5 段下跌；照教科書，楔形走完常快速彈回起點附近'],
      '5': [up ? '上升楔形・最後一段（第 5 段）上漲' : '下跌楔形・最後一段（第 5 段）下跌',
            up ? '楔形的最後一段；照教科書，走完常快速跌回楔形起點附近' : '楔形的最後一段；照教科書，走完常快速彈回楔形起點附近'] };
    if (!T[cur]) return null;
    return { title: T[cur][0], meaning: T[cur][1], steps: ['1', '2', '3', '4', '5'], cur };
  }

  function plain(c) {
    if (!c) return null;
    const cur = c.current, up = c.dir > 0;
    if (['combo', 'triangle', 'diagonal'].includes(c.kind)) return plainComplex(c, cur, up);
    if (c.kind === 'impulse' && '12345'.includes(cur)) {
      const steps = ['1', '2', '3', '4', '5'];
      if ('135'.includes(cur)) {
        const m = { '1': '新一波的第一段，還需要後面走勢確認', '3': '通常是整波裡最強、最長的一段', '5': '這一波的最後一段，走完通常會有比較大的修正' }[cur];
        return { title: up ? `上漲波・第 ${cur} 段上漲中` : `下跌波・第 ${cur} 段下跌中`, meaning: m, steps, cur };
      }
      return { title: up ? `上漲途中的回檔（第 ${cur} 段）` : `下跌途中的反彈（第 ${cur} 段）`,
               meaning: up ? `回檔走完，照規則後面還有第 ${+cur + 1} 段上漲` : `反彈走完，照規則後面還有第 ${+cur + 1} 段下跌`, steps, cur };
    }
    // A-B-C：漲多後的修正（跌－彈－跌）或跌深後的反彈（彈－回－彈）
    const corrDown = (c.kind === 'impulse' && up) || (c.kind === 'correction' && !up);
    const steps = c.kind === 'impulse' ? ['1', '2', '3', '4', '5', 'A', 'B', 'C'] : ['A', 'B', 'C'];
    const T = corrDown
      ? { A: ['漲多後的修正・第一段下跌（A）', '修正通常走「跌－彈－跌」三段，這是第一段'],
          B: ['修正中的反彈（B）', '反彈走完，照規則還有最後一段下跌（C）'],
          C: ['修正的最後一段下跌（C）', '這段跌完，修正可能結束、重新開始上漲'] }
      : { A: ['跌深後的反彈・第一段（A）', '跌深反彈通常走「彈－回－彈」三段，這是第一段'],
          B: ['反彈中的回落（B）', '回落走完，照規則還有最後一段反彈（C）'],
          C: ['反彈的最後一段（C）', '這段反彈走完，可能再往下'] };
    if (!T[cur]) return null;   // 防呆：沒對應的浪別就當「結構不清楚」
    return { title: T[cur][0], meaning: T[cur][1], steps, cur };
  }

  function invText(c) {
    if (!c || num(c.invalid) == null) return '';
    return `波浪規則：${c.invalid_side === 'below' ? '跌破' : '漲過'} ${fmt(c.invalid)} 整個劇本作廢`;
  }

  // ── LightweightCharts（同 dashboard 兩段 CDN 備援）──
  async function loadLWC() {
    if (window.LightweightCharts) return true;
    for (const u of ['https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js',
                     'https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js']) {
      try {
        await new Promise((ok, bad) => {
          const t = setTimeout(() => bad(new Error('timeout')), 8000);
          const s = document.createElement('script');
          s.src = u; s.onload = () => { clearTimeout(t); ok(); }; s.onerror = () => { clearTimeout(t); bad(new Error('load')); };
          document.head.appendChild(s);
        });
        if (window.LightweightCharts) return true;
      } catch (e) { console.warn('[wave] LWC CDN 失敗', u); }
    }
    return false;
  }

  // ── 載入 ──
  let loadSeq = 0;
  async function load(force) {
    if (!$('wv-root')) return;
    const sym = st.sym, seq = ++loadSeq;
    try {
      const r = await fetch(`/api/wave/snapshot?sym=${encodeURIComponent(sym)}` + (force ? '&force=1' : ''));
      const d = await r.json();
      if (seq !== loadSeq || sym !== st.sym) return;      // 中途切換商品：丟掉舊的回應
      if (!d.ok) {   // 第一次啟動還在下載歷史 → 20 秒後自己再試
        $('wv-msg').innerHTML = `⏳ ${esc(d.error || d.detail || '大盤資料準備中')}（20 秒後自動重試）`; $('wv-msg').style.display = 'block';
        setTimeout(() => { if (sym === st.sym) load(false); }, 20000);
        return;
      }
      DATA[sym] = d;
      S = d;
      $('wv-msg').style.display = 'none';
      render();
    } catch (e) {
      $('wv-msg').innerHTML = `⚠️ 大盤解析載入失敗：${esc(e.message)}`; $('wv-msg').style.display = 'block';
    }
  }

  function render() {
    if (!S || S.sym !== st.sym) return;          // 切商品後資料還沒回來：先不畫（不然會拿上一個商品的資料標成新的）
    renderHead();
    renderSummary();
    renderLmap();
    renderVol();
    renderPlan();
    renderTimeline();
    renderRules();
    renderComposite();
    renderMargin();
    renderChips();
    renderGlobal();
    renderForecast();
    renderContext();
    renderResearch();
    if (st.tab === 'chart') drawChart();
  }

  function renderHead() {
    const live = S.asof.live;
    $('wv-price').innerHTML = `<b>${fmt(S.price, S.sym === 'TX' ? 0 : 2)}</b> <span style="color:${colorOf(S.chg)}">${S.chg > 0 ? '▲' : S.chg < 0 ? '▼' : ''} ${fmt(Math.abs(S.chg ?? 0), S.sym === 'TX' ? 0 : 2)}（${pctS(S.chg_pct)}）</span>`;
    const sess = S.asof.session && S.asof.session !== '休市' ? S.asof.session : '';
    let asof = live ? `${esc(sess || '盤中')} ${esc(live.time || '')}` : `${md(S.asof.date)} 收盤`;
    if (S.sym === 'TX') asof = `<span class="wv-dim">台指期近月（含夜盤）</span> ` + asof;
    if (S.basis) asof += ` <span class="wv-badge" style="background:rgba(148,163,184,.12);color:var(--text);border-color:rgba(148,163,184,.3)" title="台指期 − 加權（${esc(S.basis.when || '')}）">${esc(S.basis.label)} ${sgn(S.basis.pts)} 點</span>`;
    if (S.asof.stale) asof += ` <span class="wv-badge">⚠ ${esc(S.asof.stale_reason || '資料過期')}</span>`;
    if ((S.problems || []).length) asof += ` <span class="wv-badge" title="${esc(S.problems.map(p => p.src + ' 連續失敗 ' + p.fails + ' 次').join('、'))}">⚠ ${S.problems.length} 個資料來源有問題</span>`;
    $('wv-asof').innerHTML = asof;
    document.querySelectorAll('[data-wv-sym]').forEach(b => b.classList.toggle('on', b.dataset.wvSym === st.sym));
    document.querySelectorAll('[data-wv-deg]').forEach(b => b.classList.toggle('on', b.dataset.wvDeg === st.degSel));
    document.querySelectorAll('[data-wv-show]').forEach(cb => { cb.checked = !!st.show[cb.dataset.wvShow]; });
    $('wv-alt').classList.toggle('on', st.alt);
    $('wv-alt').textContent = st.alt ? '看主要' : '看備選';
    // 週期按鈕＝多週期一覽：每個按鈕顯示這個週期的方向
    const rows = {};
    (S.ladder || []).forEach(r => { rows[r.tf] = r; });
    document.querySelectorAll('[data-wv-tf]').forEach(b => {
      const tf = b.dataset.wvTf, T = TF[tf], r = rows[tf];
      const ar = !r ? '' : r.dir === 1 ? `<span class="ar" style="color:var(--up)">↑</span>` : r.dir === -1 ? `<span class="ar" style="color:var(--down)">↓</span>` : '<span class="ar wv-dim">－</span>';
      b.innerHTML = `<span>${esc(T.name)}${ar}</span><small>${esc(T.hz)}</small>`;
      b.title = r ? `${T.name}：${r.title}` : T.name;
      b.classList.toggle('on', tf === st.tf);
    });
    $('wv-ladtext').textContent = S.ladder_text || '';
  }

  // ── ① 結論卡 ──
  // B83 她 10/28 的說法：維持原架構（大段還在走）vs 級數轉浪（大段走完）
  const trendTxt = (c, nz) => c.with_trend ? `維持原架構・${nz.dir < 0 ? '下跌' : '上漲'}大段還在走` : `級數轉浪・大段走完、${nz.dir < 0 ? '反彈' : '回檔'}中`;
  const fmtV = v => num(v) == null ? '—' : `${fmt(v, S.vol_unit === '億' ? 0 : 0)} ${esc(S.vol_unit || '')}`;
  const FIBS = r => r == null ? '' : `接近 ${r}`;

  function pushText(lg) {
    const up = lg.dir === 1;
    const v = { last: '<b style="color:var(--warn)">像最後一推</b>', ok: '<b>還在續推</b>', mixed: '<b>力道轉弱中</b>' }[lg.verdict] || '';
    return `這段${up ? '漲' : '跌'}過前${up ? '高' : '低'}了，最後一推的跡象 ${num(lg.n) ?? 0}/4 → ${v}`;
  }

  function corrText(lg) {
    const sp = num(lg.space), tm = num(lg.time);
    const m = lg.mature ? '<b>回得夠深也夠久</b>（可能快走完）' : lg.shallow ? '<b>回得還不夠深</b>' : '<b>還沒走完</b>';
    const vs = { shrink: '量縮（健康）', swell: lg.dir === -1 ? '帶量下跌（賣壓重）' : '帶量反彈', flat: '量沒有明顯變化' }[lg.vol_state] || '';
    const w = lg.dir === -1 ? '回檔' : '反彈';
    return `${w}了前一段的 ${sp == null ? '—' : (sp * 100).toFixed(0) + '%'}、時間只有前一段的 ${tm == null ? '—' : tm.toFixed(1)} 倍 → ${m}${vs ? '；' + vs : ''}`;
  }

  function volLine(tf) {
    const vx = volOf(tf);
    if (!vx) return '';
    if (!vx.ok) return `<span class="wv-dim">${esc(vx.note || '量能算不出來')}</span>`;
    if (!vx.has_vol) return `<span class="wv-dim">${esc(vx.note || '這段沒有量的資料')}</span>`;
    const out = [];
    const pa = vx.partial, la = vx.last;
    if (pa && num(pa.est) != null) out.push(`今天到目前 ${fmtV(pa.v)}，預估全天 ${fmtV(pa.est)}${num(pa.rv) != null ? `＝平常的 <b>${pa.rv.toFixed(1)} 倍</b>（${esc(pa.label)}）` : ''}`);
    else if (pa && num(pa.rv) != null) out.push(`進行中這根 <b>${pa.rv.toFixed(1)} 倍</b>（${esc(pa.label)}）`);
    else if (la && num(la.rv) != null) out.push(`最後一根（${esc(la.t)}）是平常的 <b>${la.rv.toFixed(1)} 倍</b>（${esc(la.label)}）`);
    const lg = vx.leg;
    let k = null;
    if (lg && lg.mode === 'push') { out.push(pushText(lg)); k = 'V2'; }
    else if (lg && lg.mode === 'corr') { out.push(corrText(lg)); k = 'V3'; }
    if (!out.length) return '<span class="wv-dim">量能沒有特別訊號</span>';
    // 回測標籤整行只出現一次（B81）
    return out.join('｜') + (k ? (vpass(k) ? ` ${resTag(k)}` : ' <span class="wv-dim">（量的規則回測 △，參考）</span>') : '');
  }

  function tileHtml(lab, it, color) {
    if (!it) return `<div class="wv-tile"><div class="k">${lab}</div><div class="v">—</div><div class="m wv-dim">附近沒有系統價位</div></div>`;
    return `<div class="wv-tile" title="點一下看完整說明"><div class="k">${lab}</div><div class="v" style="color:${color}">${fmt(it.price)}<small>${pctS(it.dist_pct, 1)}</small></div>
      <div class="m"><b>${esc(it.name || '')}</b>　${esc(it.act || '')}${it.vol ? `<span class="vh">${esc(it.vol)}</span>` : ''}</div></div>`;
  }

  // ── B81 🎯 試單地圖 ──
  const setupsOf = tf => { const lm = lmOf(tf); return lm && lm.setups && lm.setups.ok && Array.isArray(lm.setups.list) ? lm.setups : null; };   // 審查 Groq F1
  const isShortTW = x => x.id === 'S' && S.sym === 'TWII';
  function setupShort(x) {
    const nm = isShortTW(x) ? '減碼' : x.id === 'L' ? '試多' : x.id === 'S' ? '試空' : '追多';
    const col = isShortTW(x) ? 'var(--warn)' : x.side > 0 ? 'var(--up)' : 'var(--down)';
    const where = (x.in_zone ? '<b>現在就在這區</b>，' : '') +
      (x.id === 'L' ? `回到 ${fmt(x.zone[0])}～${fmt(x.zone[1])} 不破` : x.id === 'S' ? `彈到 ${fmt(x.zone[0])}～${fmt(x.zone[1])} 壓回` : `站上 ${fmt(x.level)} 回測不破`);
    const tail = isShortTW(x) ? '' : `，停損 ${fmt(x.stop)} → 目標 ${fmt(x.t1)}`;
    const tr = x.trend === '逆勢' ? ' <span class="wv-dim">（逆勢）</span>' : '';
    const bad = (x.rr == null || x.rr < 1) && !isShortTW(x) ? ' <span class="wv-dim">（賠率不夠）</span>' : '';
    return `<b style="color:${col}">${nm}</b> ${where}${tail}${tr}${bad}`;
  }
  function setupLine(tf) {
    const su = setupsOf(tf);
    const lm = lmOf(tf);
    if (!su) return lm && lm.setups ? `<span class="wv-dim">${esc(lm.setups.note || '這個週期先不給試單')}</span>` : '';
    const pick = ['L', 'S'].map(id => su.list.find(x => x.id === id)).filter(Boolean);
    if (!pick.length) return `<span class="wv-dim">${esc(su.note || '附近沒有可以試單的價位')}</span>`;
    return pick.map(setupShort).join('｜') + ' <a data-goto-tab="plan">看拆解 →</a>';
  }
  function setupCard(x, su) {
    const col = isShortTW(x) ? 'var(--warn)' : x.side > 0 ? 'var(--up)' : 'var(--down)';
    const r = x.res;
    const src = !r ? '' : r.tfc === 'intra' ? '60 分 K 3 年資料' : r.tfc === '1wk' ? '週 K 價位、2001 年起' : '日 K 2001 年起';
    const resTxt = r ? `回測（${src}、${esc(x.trend || '')}）：先到目標 ${rateS(r.win)}，隨機 ${rateS(r.rw)}（${esc(r.n)} 筆）→ ${r.pass ? '✅' : '△'}` +
      (r.worse ? ' <b style="color:var(--warn)">比隨機差，這個週期不建議這樣做</b>' : r.pass ? '' : '，當紀律參考：停損明確、賠率夠才做') : '回測：這個組合沒有足夠資料';
    const body = isShortTW(x)
      ? `<div>彈到這裡：<b>減碼</b>（${esc(x.cond)}）</div><div>站回 ${fmt(x.stop)} 以上 → 這個壓力被突破，減掉的買回</div>`
      : `<div>進場：${esc(x.cond)}</div>
         <div>停損（多空線）<b>${fmt(x.stop)}</b>　目標 T1 <b>${fmt(x.t1)}</b>${x.t2 != null ? `、T2 ${fmt(x.t2)}` : ''}　賠率 1：${x.rr == null ? '—' : Number(x.rr).toFixed(1)}</div>`;
    return `<div class="wv-setup${su.main === x.id ? ' main' : ''}">
      <div class="t"><b style="color:${col}">${isShortTW(x) ? '⚠ 減碼區' : esc(x.title)}</b> <span class="wv-dim">${fmt(x.level)}（${pctS(x.dist_pct, 1)}）${x.lv_name ? '・' + esc(x.lv_name) : ''}</span>
        ${x.trend ? `<span class="wv-tag ${x.trend === '順勢' ? 'ok' : 'ng'}">${esc(x.trend)}</span>` : ''}${su.main === x.id ? '<span class="wv-tag main">主要</span>' : ''}</div>
      ${x.in_zone ? '<div><b>現在就在這區</b>：照下面的條件等收盤確認</div>' : ''}
      ${body}
      ${x.warn ? `<div class="wv-warn">⚠ ${esc(x.warn)}</div>` : ''}
      <div class="wv-why">${resTxt}</div></div>`;
  }
  function exitSteps(su) {
    const x = su.list.find(y => y.id === su.main && !isShortTW(y)) || su.list.find(y => !isShortTW(y) && y.rr != null && y.rr >= 1) || su.list.find(y => !isShortTW(y));
    if (!x) return '';
    const up = x.side > 0;
    const brk = up ? '跌破' : '漲過';
    const steps = [
      `進場後${brk} <b>${fmt(x.stop)}</b>（多空線）→ 出場，不凹單`,
      `到 T1 <b>${fmt(x.t1)}</b> → 先走一口、留一口`,
      `留的那口：防守拉到成本（約 ${fmt(x.entry)}），${up ? '跌回' : '漲回'}成本就走`,
      x.t2 != null ? `到 T2 <b>${fmt(x.t2)}</b> → 開始處理獲利；15 分收穩前${up ? '高' : '低'}才看更${up ? '上' : '下'}面` : 'T1 之後沒有下一個價位 → 留的那口用多空線慢慢拉',
      `目標之間的過渡${up ? '壓力' : '支撐'}不追；壓回「失速」、出現加速${up ? '往下' : '往上'} → 立刻改判（看下面的如果…就…）`,
    ];
    if (x.trend === '逆勢') steps.push('這筆是逆勢：小量、快進快出；反彈（逃命波）到 0.5～0.618 就分批出，不要過度歡樂');
    return `<div class="wv-exit"><div class="t">🚪 出場（她的寫法，代入「${esc(x.title)}」這筆）</div><ol>${steps.map(t => `<li>${t}</li>`).join('')}</ol></div>`;
  }
  function setupBlock(tf) {
    const su = setupsOf(tf), lm = lmOf(tf);
    if (!lm || !lm.setups) return '';
    if (!su) return `<div class="wv-h3">🎯 現在怎麼試單</div><div class="wv-dim">${esc(lm.setups.note || '這個週期先不給試單')}</div>`;
    const nu = (su.near || {}).up, nd = (su.near || {}).down;
    const near = `現價 <b>${fmt(S.price)}</b>：上面最近 ${nu ? `<b style="color:var(--up)">${fmt(nu.price)}</b>（${esc(nu.name)}，${pctS(nu.dist_pct, 1)}）` : '沒有價位'}、
      下面最近 ${nd ? `<b style="color:var(--down)">${fmt(nd.price)}</b>（${esc(nd.name)}，${pctS(nd.dist_pct, 1)}）` : '沒有價位'}`;
    return `<div class="wv-h3">🎯 現在怎麼試單 <span class="wv-dim">她的進出場拆解；${esc(T_().name)}</span></div>
      <div class="wv-near">${near}</div>
      ${su.note ? `<div class="wv-note">${esc(su.note)}</div>` : ''}
      <div class="wv-setups">${su.list.map(x => setupCard(x, su)).join('')}</div>
      <div class="wv-in"><b>進場三種（她）</b>：① 回測支撐，第一根壓下來不破前低再上車　② 彈到壓力壓回 → ${S.sym === 'TWII' ? '減碼（台指期才試空）' : '試空'}　③ 站上壓力、回測不破再追（三條路的「轉強依序」）</div>
      ${exitSteps(su)}
      <div class="wv-dim" style="margin-top:6px">系統照她的規則找出來的位置，不是她的實際下單；波浪標記皆為候選，部位照關卡分批。</div>`;
  }

  function renderSummary() {
    const T = T_(), tf = st.tf;
    const nz = T.intra ? nestOf(tf) : null;
    const w = wv(deg());
    const p = plain(w.primary);
    const pre = S.sym === 'TX' ? '台指期・' : '';
    let head;
    const sub = [];
    if (nz && nz.ok && nz.primary) {
      head = `${pre}${esc(T.name)}：<span class="path">${esc(nz.primary.path)}</span> <span class="wv-dim">${esc(trendTxt(nz.primary, nz))}</span>`;
      if (nz.primary.text) sub.push(esc(nz.primary.text));
      if (nz.alternate) sub.push(`備選 <b>${esc(nz.alternate.path)}</b>（${esc(trendTxt(nz.alternate, nz))}）`);
    } else {
      head = `${pre}${esc(T.name)}：${p ? esc(p.title) : '結構不清楚，看價位梯就好'}`;
      if (p) sub.push(esc(p.meaning));
      const a = plain(w.alternate);
      if (a) sub.push(`備選：${esc(a.title)}`);
    }
    // B81：分 K 的多層浪名（她的寫法）跟週期按鈕的單層數浪方向不同 → 明講，以價位梯裁決
    const lrow = ((Array.isArray(S.ladder) ? S.ladder : []).find(r => r && r.tf === tf)) || {};
    if (nz && nz.ok && (nz.cur_dir === 1 || nz.cur_dir === -1) && (lrow.dir === 1 || lrow.dir === -1) && nz.cur_dir !== lrow.dir)
      sub.push(`<span class="wv-warn">⚠ 兩種數法方向不同：多層浪名這一小段${nz.cur_dir > 0 ? '往上' : '往下'}、單層數浪「${esc(lrow.title || '')}」${lrow.dir > 0 ? '往上' : '往下'}；以價位梯的價位裁決</span>`);
    const parents = T.intra ? [['日 K', 'small'], ['週 K', 'mid']] : st.tf === '1d' ? [['週 K', 'mid']] : [['大級', 'big']];
    sub.push('母級：' + parents.map(([nm, k]) => { const q = plain(wv(k).primary); return `${nm} <b>${q ? esc(q.title) : '結構不清楚'}</b>`; }).join('；'));
    const inote = st.tf === '15m' ? ((S.intra || {}).m15 || {}) : st.tf === '30m' ? ((S.intra || {}).m30 || {}) : st.tf === '60m' ? (S.intra || {}) : { ok: true };
    const intraNote = inote && inote.ok === false ? `<div class="wv-note">${esc(inote.note || '分 K 資料還不夠')}</div>` : '';
    // 三格：從價位梯挑（舊快照沒有價位梯 → 用撐壓、轉折點）
    const lm = lmOf(tf);
    let top = (lm && lm.top3) || null;
    if (!top) {
      const lv = (S.levels || {})[T.lv] || {}, k = (S.key || {})[T.lv];
      const z2 = (z, nm) => z ? { price: z.price, dist_pct: z.dist_pct, name: nm, act: '' } : null;
      top = { up: z2((lv.resistance || [])[0], '壓力'), down: z2((lv.support || [])[0], '支撐'), stop: k ? { price: k.price, dist_pct: k.dist_pct, name: k.kind, act: '' } : null };
    }
    // 操作建議、今天、風險、AI
    const a = S.advice || {};
    const rg = a.range || {};
    const lines = [];
    const sl = setupLine(tf);
    if (sl) lines.push(['🎯 試單', sl]);
    const vl = volLine(tf);
    if (vl) lines.push(['🔋 量能', vl]);
    if (a.ok) {
      const regime = ((S.context || {}).regime || {}).label;
      lines.push(['💡 操作', `<span class="wv-rg" title="${esc((rg.why || []).join('；'))}">建議持股 ${esc(rg.lo)}～${esc(rg.hi)}%</span>：${esc(String(a.headline || '').replace(/^建議持股[^：]*：/, ''))}` +
        (regime ? ` <span class="wv-dim">（總經：${esc(String(regime).replace(/^\S+\s/, ''))}${rg.bt ? `；方向調持股 回測 ${esc(rg.bt)}` : ''}）</span>` : '')]);
      const today = (a.lines || []).find(x => x.k === '今天' || x.k === '明天');
      if (today) lines.push([`🌙 ${esc(today.k)}`, esc(today.t)]);
      const risks = (a.risks || []).slice(0, 2);
      if (risks.length) lines.push(['⚠ 風險', esc(risks.join('；')), 'mh']);      // 手機先收起來（籌碼分頁有完整的）
    }
    const pr = panelData && panelData.result, mo = pr && pr.moderator;
    if (mo && mo.summary) {
      const sc = /多/.test(mo.stance || '') ? 'var(--up)' : /空/.test(mo.stance || '') ? 'var(--down)' : 'var(--muted)';
      const sm = String(mo.summary);
      lines.push(['🤖 AI', `<b style="color:${sc}">${esc(mo.stance || '')}</b>・${esc(sm.length > 70 ? sm.slice(0, 70) + '…' : sm)} <a data-goto-tab="ai">看討論 →</a>`, 'mh']);
    }
    $('wv-sum').innerHTML = `
      <div class="wv-head">${head}</div>
      <div class="wv-sub">${sub.join('<br>')}</div>
      ${intraNote}
      <div class="wv-tiles${top.stop ? '' : ' two'}">
        ${tileHtml(top.stop_same === 'up' ? '⬆ 上方關鍵（也是停損）' : '⬆ 上方關鍵', top.up, 'var(--up)')}
        ${tileHtml(top.stop_same === 'down' ? '⬇ 下方關鍵（也是停損）' : '⬇ 下方關鍵', top.down, 'var(--down)')}
        ${top.stop ? tileHtml(top.stop_src === 'setup' ? '🛑 多空線（試單停損）' : top.stop_pos === 'before' ? (top.stop_same === 'down' ? '⬇ 途中先遇到' : '⬆ 途中先遇到')
                   : top.stop_same === 'down' ? '⬇⬇ 跌破後再看' : top.stop_same === 'up' ? '⬆⬆ 站上後再看' : '🛑 停損（轉折點）', top.stop,
                   top.stop_same === 'down' ? 'var(--down)' : top.stop_same === 'up' ? 'var(--up)' : 'var(--warn)') : ''}
      </div>
      <div class="wv-lines">${lines.map(([k, v, c]) => `<span class="k${c ? ' ' + c : ''}">${k}</span><span${c ? ` class="${c}"` : ''}>${v}</span>`).join('')}</div>
      ${lines.some(x => x[2]) ? '<button type="button" class="wv-more-btn">更多（風險、AI）▾</button>' : ''}`;
    $('wv-sum').querySelectorAll('[data-goto-tab]').forEach(x => x.onclick = () => setTab(x.dataset.gotoTab));
    $('wv-sum').querySelectorAll('.wv-tile').forEach(x => x.onclick = () => x.classList.toggle('open'));   // 手機：點開看完整說明
    const mb = $('wv-sum').querySelector('.wv-more-btn');
    if (mb) mb.onclick = () => { const on = $('wv-sum').classList.toggle('more'); mb.textContent = on ? '收起 ▴' : '更多（風險、AI）▾'; };
  }

  // ── 📈 價位梯 ──
  function srcText(z) {
    const seen = new Set();
    const parts = [];
    for (const s of z.sources || []) {
      let t = s.label || '';
      const dm = t.match(/(\d{4})-(\d{2})-(\d{2})/);
      if (dm) t = t.replace(dm[0], `${+dm[2]}/${+dm[3]}`);
      t = t.replace(/^小級|^中級|^大級/, '').replace('整數關卡', '整數');
      if (seen.has(t)) continue;
      seen.add(t);
      parts.push(t);
      if (parts.length >= 3) break;
    }
    const more = (z.sources || []).length - parts.length;
    return parts.join('＋') + (more > 0 ? ` 等 ${z.sources.length} 個` : '');
  }

  function renderLmap() {
    const el = $('wv-lmap');
    const T = T_(), lm = lmOf(st.tf);
    const head = `<div class="wv-h3">🪜 價位梯 <span class="wv-dim">${S.sym === 'TX' ? '台指期・' : ''}${esc(T.name)}；每個價位寫站上／跌破代表什麼</span></div>`;
    const row = it => {
      const col = it.kind === 'key' ? 'var(--warn)' : it.side === 'up' ? 'var(--up)' : 'var(--down)';
      return `<tr><td class="n"><span class="p" style="color:${col}">${fmt(it.price)}</span><div class="wv-why">${pctS(it.dist_pct, 1)}</div></td>
        <td><div class="nm">${esc(it.name || '')}</div><div class="act">${esc(it.act || '')}</div>${it.vol ? `<div class="vh">${esc(it.vol)}</div>` : ''}
        ${it.src ? `<div class="src wv-hide-m">${esc(it.src)}</div>` : ''}</td></tr>`;
    };
    if (!lm || !lm.items) {     // 舊快照：照舊顯示撐壓表
      const lv = (S.levels || {})[T.lv] || {};
      const z2 = (z, side) => ({ price: z.price, dist_pct: z.dist_pct, side, kind: 'level', name: side === 'up' ? '壓力' : '支撐', act: '', src: srcText(z) });
      const ups = (lv.resistance || []).slice().reverse().map(z => z2(z, 'up')), dns = (lv.support || []).map(z => z2(z, 'down'));
      el.innerHTML = head + `<table class="wv-tbl wv-lm">${ups.map(row).join('')}<tr class="wv-now"><td colspan="2">現在 ${fmt(S.price, 0)}</td></tr>${dns.map(row).join('')}</table>`;
      return;
    }
    const ups = lm.items.filter(it => it.side === 'up'), dns = lm.items.filter(it => it.side === 'down');
    const tg = (lm.targets || []).map(t => `<b>${esc(t.t)} ${fmt(t.price)}</b>`).join('、');
    const notes = (((S.levels || {})[T.lv] || {}).note || []).map(n => `<div class="wv-note">${esc(n)}</div>`).join('');
    el.innerHTML = head + `
      ${tg ? `<div style="margin-bottom:6px">目標（現在這段方向）：${tg}</div>` : ''}
      <table class="wv-tbl wv-lm">
        ${ups.map(row).join('') || '<tr><td colspan="2" class="wv-dim">上方附近沒有系統價位</td></tr>'}
        <tr class="wv-now"><td colspan="2">▶ 現在 ${fmt(S.price, 0)}</td></tr>
        ${dns.map(row).join('') || '<tr><td colspan="2" class="wv-dim">下方附近沒有系統價位</td></tr>'}
      </table>${notes}
      <div class="wv-what">價位來自前高前低、均線、整數、費波那契、波浪目標、多層浪名的關卡和換數法價位、日線母尺、成交密集區，0.15% 內併成一列。
        回測這些價位「守住」的機率跟隨便畫一條線差不多 △，當<b>參考點＋停損位置</b>；過渡壓力＝目標之間容易先震盪換手的地方（她的寫法）。</div>`;
  }

  // ── 📈 量能與力道 ──
  function renderVol() {
    const el = $('wv-vol');
    const T = T_(), vx = volOf(st.tf);
    const head = `<div class="wv-h3">🔋 量能與力道 <span class="wv-dim">${esc(T.name)}；${S.vol_unit === '口' ? '台指期口數' : '加權成交金額（億）'}</span></div>`;
    if (!vx) { el.innerHTML = head + '<div class="wv-dim">這份資料沒有量能（舊版快照），重新整理後就有</div>'; return; }
    if (!vx.ok || !vx.has_vol) {
      el.innerHTML = head + `<div class="wv-dim">${esc(vx.note || '這段沒有量的資料')}</div>` + (vx.leg ? `<div style="margin-top:6px">${vx.leg.mode === 'push' ? pushText(vx.leg) : corrText(vx.leg)}（量的那一項沒有資料）</div>` : '');
      return;
    }
    const la = vx.last || {}, pa = vx.partial;
    const qty = [];
    if (la.v != null) qty.push(`最後一根（${esc(la.t)}）${fmtV(la.v)}${num(la.rv) != null ? `，是平常同時段的 <b>${la.rv.toFixed(1)} 倍</b>（${esc(la.label)}）` : '（同時段資料不足，回補中）'}`);
    if (pa) {
      if (num(pa.est) != null) qty.push(`今天到目前 ${fmtV(pa.v)}，預估全天 <b>${fmtV(pa.est)}</b>${num(pa.rv) != null ? `＝平常的 <b>${pa.rv.toFixed(1)} 倍</b>（${esc(pa.label)}）` : ''}`);
      else if (pa.early) qty.push('進行中這根剛開始，還不判斷');
      else if (pa.v != null) qty.push(`進行中這根到目前 ${fmtV(pa.v)}${num(pa.rv) != null ? `，換算 <b>${pa.rv.toFixed(1)} 倍</b>（${esc(pa.label)}）` : ''}`);
    }
    const lg = vx.leg;
    let legBox = '';
    if (lg && lg.mode === 'push') {
      const up = lg.dir === 1, sg = lg.signals || {};
      const it = (k, on, txt) => `<li><span class="mk">${on === true ? '⚠️' : on === false ? '✅' : '⬜'}</span>${txt}</li>`;
      legBox = `<div class="wv-vbox${lg.verdict === 'last' ? ' warn' : ''}"><div class="t">💪 最後一推檢查（她：最後一推會漲幅縮小、量沒放大、動能背離、突破後站不住）</div>
        <div>${pushText(lg)} ${resTag('V2')}</div>
        <ul class="wv-chk">
          ${it('amp', sg.amp, `幅度：這段 ${num(lg.amp_ratio) == null ? '—' : lg.amp_ratio.toFixed(2)} 倍前一段（${sg.amp ? (up ? '漲幅縮小' : '跌幅縮小') : '沒有縮小'}）`)}
          ${it('vol', sg.vol, `量：這段平均 ${num(lg.vol_ratio) == null ? '—' : lg.vol_ratio.toFixed(2)} 倍前一段（${sg.vol == null ? '量的資料不夠' : sg.vol ? '沒有跟著放大' : '有跟著放大'}）`)}
          ${it('mom', sg.mom, `動能：${sg.mom == null ? '資料不夠' : sg.mom ? 'MACD 沒過前一個高點（背離）' : 'MACD 跟著創新高'}`)}
          ${it('hold', sg.hold, `站不站得住：${sg.hold ? `已經收回前${up ? '高' : '低'}以${up ? '下' : '上'}` : `還在前${up ? '高' : '低'}以${up ? '上' : '下'}`}${num(lg.retain) != null ? `，保留這段 ${(lg.retain * 100).toFixed(0)}%` : ''}`)}
        </ul><div class="wv-why">⚠️＝出現最後一推的跡象、✅＝沒有；≥3 項像最後一推、≤1 項像續推。V2b（突破後 3 根收回前高）${resTag('V2b')}</div></div>`;
    } else if (lg && lg.mode === 'corr') {
      legBox = `<div class="wv-vbox${lg.mature ? '' : ' warn'}"><div class="t">⏳ 修正成熟度（她：回吐約 0.382、時間跟前段 1:1 → 具備修正結束的條件）</div>
        <div>${corrText(lg)}</div>
        <ul class="wv-chk">
          <li><span class="mk">${lg.space >= 0.362 ? '✅' : '⬜'}</span>空間：回了前一段（${fmt(lg.prev.from)} → ${fmt(lg.prev.to)}）的 ${num(lg.space) == null ? '—' : (lg.space * 100).toFixed(1) + '%'}　${resTag('V3')}</li>
          <li><span class="mk">${lg.time >= 0.8 ? '✅' : '⬜'}</span>時間：這段 ${fmt(lg.bars)} 根，前一段 ${fmt(lg.prev.bars)} 根（${num(lg.time) == null ? '—' : lg.time.toFixed(2)} 倍）</li>
          <li><span class="mk">${lg.vol_state === 'shrink' ? '✅' : lg.vol_state == null ? '⬜' : '⚠️'}</span>量：這段平均 ${num(lg.vol_ratio) == null ? '—' : lg.vol_ratio.toFixed(2)} 倍前一段（≤0.85 量縮＝健康、≥1.15 帶量）　${resTag('V4')}</li>
        </ul></div>`;
    }
    const br = (vx.breaks || []).slice().reverse().map(e => `<li>${esc(e.t)} ${e.kind === 'vol' ? '<b>帶量</b>' : e.kind === 'dry' ? '沒量' : '量普通'}${e.dir === 1 ? '站上' : '跌破'} ${fmt(e.level)}（前一個轉折${e.dir === 1 ? '高' : '低'}點；量 ${num(e.rv) == null ? '—' : e.rv.toFixed(1) + ' 倍'}）</li>`).join('');
    const zs = (vx.zones || []).map(z => `<li><b>${fmt(z.lo)}～${fmt(z.hi)}</b>（${z.by === 'vol' ? `${(z.share * 100).toFixed(0)}% 的量` : '停留最久'}）${z.mid > S.price ? '在上方＝壓力' : '在下方＝支撐'}</li>`).join('');
    el.innerHTML = head + `
      <div class="wv-vgrid">
        <div class="wv-vbox"><div class="t">📊 量</div>${qty.map(x => `<div>${x}</div>`).join('') || '<div class="wv-dim">—</div>'}</div>
        ${legBox || '<div class="wv-vbox"><div class="t">💪 力道</div><div class="wv-dim">轉折還不夠，算不出這段跟前一段的比較</div></div>'}
        <div class="wv-vbox"><div class="t">🚀 帶量突破／跌破 ${resTag('V1')}</div>${br ? `<ul class="wv-chk">${br}</ul>` : '<div class="wv-dim">最近沒有越過前一個轉折高低點</div>'}
          <div class="wv-why">帶量＝那根 ≥1.3 倍、沒量＝&lt;1.0 倍（她：「60 分帶量突破才升權」）；回測扣掉距離後帶量、沒量之後走勢差不多</div></div>
        <div class="wv-vbox"><div class="t">🧱 成交密集區 ${resTag('V5')}</div>${zs ? `<ul class="wv-chk">${zs}</ul>` : '<div class="wv-dim">—</div>'}
          <div class="wv-why">這段時間量最多的價位帶（她的「既有橫盤」）；回測碰到後先反彈的比例沒有比隨便一個價位帶好，當參考位置</div></div>
      </div>
      <details class="wv-who"><summary>ⓘ 量怎麼算、回測結果</summary>
        <div class="wv-what">相對量＝這根量 ÷ 之前 20 個交易日<b>同一時段</b>的平均（開盤、收盤量本來就大，要比同時段）；日 K／週 K＝÷ 前 20 根。
          ≥2 爆量、≥1.3 放量、≤0.7 量縮。加權用證交所每 5 秒成交統計（成交金額），台指期用口數。
          <ul>${['V1', 'V2', 'V2b', 'V3', 'V4', 'V5'].map(k => `<li>${esc(k)}：${esc(vres(k).text || '')}</li>`).join('')}</ul>
          ${esc((((S.research || {}).volume) || {}).note || '')}</div></details>`;
  }

  // ── 🧭 劇本 ──
  function treeHtml(nodes) {
    if (!nodes || !nodes.length) return '';
    return `<ul class="wv-tree">${nodes.map(n => `<li class="${n.now ? 'now' : ''}"><div class="row"><span class="lb">${esc(n.lab)}</span>${fmt(n.from && n.from.p)} → ${n.now ? `運行中（目前 ${fmt(n.to && n.to.p)}）` : fmt(n.to && n.to.p)}
      <span class="kd">${n.split ? esc(n.kind) : ''}${n.now ? ' ← 現在' : ''}</span></div>${treeHtml(n.subs)}</li>`).join('')}</ul>`;
  }

  function nestTreeBox(c, label, nz, alt) {
    if (!c) return '';
    const side = r => r.side === 'below' ? '跌破' : '漲過';
    const rules = (c.rules || []).map(r => `${side(r)} <b>${fmt(r.price)}</b>：${esc(r.why)}`).join('<br>');
    const tr = c.tree || {};
    return `<div class="wv-tree-box${alt ? ' alt' : ''}"><div class="hd">${label}<span class="path">${esc(c.path || '—')}</span><span class="wv-dim">${esc(trendTxt(c, nz))}</span></div>
      ${tr.from ? `<div class="wv-why">${esc(tr.kind || '')}：${fmt(tr.from.p)}（${esc(tr.from.t)}）起</div>` : ''}
      ${treeHtml(tr.subs) || `<div class="wv-dim">${esc(c.text || '')}</div>`}
      ${rules ? `<div class="wv-why" style="margin-top:6px;color:var(--warn)">換數法的價位：<br>${rules}</div>` : ''}</div>`;
  }

  function waveTreeBox(cnt, label, alt) {
    if (!cnt) return '';
    const p = plain(cnt);
    const L = cnt.labels || [];
    const nodes = [];
    for (let j = 1; j < L.length; j++) {
      nodes.push({ lab: (L[j].disp || L[j].label) + (L[j].tentative ? '?' : ''), from: { p: L[j - 1].p }, to: { p: L[j].p }, now: j === L.length - 1, split: false, subs: [] });
    }
    return `<div class="wv-tree-box${alt ? ' alt' : ''}"><div class="hd">${label}<span class="path">${esc(cnt.current || '')}</span></div>
      <div class="wv-why">${p ? esc(p.title) : '結構不清楚'}</div>${treeHtml(nodes)}
      ${num(cnt.invalid) != null ? `<div class="wv-why" style="margin-top:6px;color:var(--warn)">${cnt.invalid_side === 'below' ? '跌破' : '漲過'} ${fmt(cnt.invalid)} 這個劇本作廢</div>` : ''}</div>`;
  }

  function renderPlan() {
    const el = $('wv-plan');
    const T = T_(), tf = st.tf;
    const nz = T.intra ? nestOf(tf) : null;
    const lm = lmOf(tf) || {};
    const P1 = (S.positioning || {})['1wk'], P2 = (S.positioning || {})['1d'];
    const same = P1 && P2 && JSON.stringify(P1.ruler) === JSON.stringify(P2.ruler);
    const pos = (same ? [{ ...P2, tf: '日 K／週 K（同一把母尺）' }] : [P1, P2]).filter(Boolean).map(x =>
      `<div><b>${esc(x.tf)}</b>：${x.lines.map(esc).join('<br>')}</div>`).join('');
    let trees, extra = '';
    if (nz && nz.ok) {
      trees = nestTreeBox(nz.primary, '版本一（主要）', nz, false) + nestTreeBox(nz.alternate, '版本二（備選）', nz, true);
      const ev = nz.evidence || {};
      const P = nz.primary || {}, A = nz.alternate;
      const kill = c => (c.rules || []).filter(r => !/這一小段的起點/.test(r.why)).slice(0, 1).map(r => `${r.side === 'below' ? '跌破' : '漲過'} <b>${fmt(r.price)}</b> → ${esc(c.path)} 作廢`).join('');
      // B83 關鍵分水嶺＋她的兩個版本怎麼確認（nest.plan 裡「版本 1／版本 2」那兩行）
      const ws = (nz.gates || []).find(g => g.k === '分水嶺');
      const vlines = (nz.plan || []).filter(x => /^版本 [12]/.test(x));
      const wsBox = ws ? `<div class="wv-ws${ws.ok ? ' ok' : ''}"><div class="t">🚦 ${esc(ws.t.split('：')[0])}</div>
          <div>${esc(ws.t.split('：').slice(1).join('：'))}</div>${vlines.length ? `<ul>${vlines.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}</div>` : '';
      extra = `${wsBox}<div style="margin-top:8px">起點：<b>${esc(nz.anchor.label)} ${fmt(nz.anchor.p)}</b>
          <span class="wv-dim">（${nz.anchor.how === 'parent' ? '60 分這一段的起點（她：15 分是在 60 分結構裡找短脈動）' : nz.anchor.how === 'daily' ? '日 K 這一浪的起點' : '這段時間最早的極值'}）</span>
          → ${nz.dir < 0 ? '最低' : '最高'} <b>${fmt(nz.extreme.p)}</b> <span class="wv-dim">${esc(nz.extreme.label)}</span></div>
        ${nz.merged ? `<div class="wv-dim" style="margin-top:4px">起點之後有 ${nz.n_seg + nz.merged} 段轉折，先把最小的 ${nz.merged} 段併掉、拆 ${nz.n_seg} 段（她的圖也只標大段＋子浪）</div>` : ''}
        <div style="margin-top:6px">盤面證據：<span class="wv-ev${ev.trend ? ' on' : ''}">${ev.trend ? '✅' : '⬜'} 越過${nz.dir < 0 ? '下降' : '上升'}趨勢線</span><span class="wv-ev${ev.f382 ? ' on' : ''}">${ev.f382 ? '✅' : '⬜'} ${nz.dir < 0 ? '站上' : '跌破'} 0.382</span>
          <span class="wv-dim">（她：沒越過趨勢線前「維持原架構」優先；越過並站穩分水嶺才「級數轉浪」）</span></div>
        ${A ? `<div class="wv-what"><b>共同事實</b>：${fmt(nz.anchor.p)} 起${nz.dir < 0 ? '下跌' : '上漲'}，現在這一小段${nz.cur_dir < 0 ? '往下' : '往上'}。
          <b>真正分歧</b>：${esc(P.path)}（${P.with_trend ? '大段還沒走完' : '大段已走完'}）vs ${esc(A.path)}（${A.with_trend ? '大段還沒走完' : '大段已走完'}）。
          <b>市場裁決</b>：${[kill(P), kill(A)].filter(Boolean).join('；') || '看下面的如果…就…'}</div>` : ''}
        ${nz.third ? `<details class="wv-who"><summary>第三個候選：${esc(nz.third.path)}（分數很接近）</summary>${nestTreeBox(nz.third, '版本三', nz, true)}</details>` : ''}`;
    } else {
      const w = wv(deg());
      trees = waveTreeBox(w.primary, '主要劇本', false) + waveTreeBox(w.alternate, '替代劇本', true);
      if (T.intra && nz && !nz.ok) extra = `<div class="wv-note">${esc(nz.note || '多層浪名算不出來')}</div>`;
    }
    const dec = (lm.decision || []).map(d => `<li class="${d.side === 'up' ? 'up' : 'down'}"><b class="if">${esc(d.if)}</b> → ${esc(d.then)}</li>`).join('');
    const stp = lm.steps || {};
    const road = (arr, cls, title) => {
      if (!arr || !arr.length) return `<div class="wv-road ${cls}"><div class="t">${title}</div><div class="wv-dim">附近沒有系統價位</div></div>`;
      return `<div class="wv-road ${cls}${arr[0].ok ? ' cur' : ''}"><div class="t">${title}</div>${arr.map(s => `<div>${s.ok ? '✅' : '⬜'} ${esc(s.t)}${s.note ? ` <span class="wv-dim">（${esc(s.note)}）</span>` : ''}</div>`).join('')}</div>`;
    };
    const rg = stp.range;
    el.innerHTML = `${setupBlock(tf)}
      <div class="wv-h3" style="margin-top:16px">🧭 劇本 <span class="wv-dim">${S.sym === 'TX' ? '台指期・' : ''}${esc(T.name)}；學 @fanny55520：先定母級、再列版本、用價位裁決</span></div>
      ${lm.mother_note ? `<div class="wv-dim" style="margin-bottom:6px">ℹ️ ${esc(lm.mother_note)}</div>` : ''}
      ${pos ? `<div class="wv-pos"><div class="wv-dim" style="margin-bottom:2px">🗺️ 母級定位（她的日線定位：母尺、防守區、鐵律、威脅版本）</div>${pos}</div>` : ''}
      <div class="wv-trees">${trees || '<div class="wv-dim">這個週期還沒有劇本</div>'}</div>
      ${extra}
      <div class="wv-h3" style="margin-top:14px">⚖️ 如果…就…</div>
      ${dec ? `<ul class="wv-dec">${dec}</ul>` : '<div class="wv-dim">附近沒有會讓數法改變的價位</div>'}
      <div class="wv-h3" style="margin-top:14px">🛣️ 三條路 <span class="wv-dim">她的寫法：轉強要依序過關、轉弱要依序跌破；✅＝已經做到</span></div>
      <div class="wv-roads">
        ${road(stp.up, 'up', '📈 轉強（依序）')}
        <div class="wv-road${rg && rg.ok ? ' cur' : ''}"><div class="t">↔️ 繼續震盪</div>${rg ? `<div>${rg.ok ? '✅' : '⬜'} ${esc(rg.t)}</div><div class="wv-why">多空在區間裡消耗，反覆長出 5 分、15 分的短波段</div>` : '<div class="wv-dim">—</div>'}</div>
        ${road(stp.down, 'down', '📉 轉弱（依序）')}
      </div>`;
  }

  function renderTimeline() {
    const el = $('wv-tl');
    const nz = T_().intra ? nestOf(st.tf) : null;
    if (!nz || !nz.ok || !(nz.timeline || []).length) {
      keepOpen(el, `<summary>📅 浪名演變<span class="s">${T_().intra ? '這個週期還沒有紀錄' : '分 K（15／30／60 分）才有：每天收盤時系統怎麼數'}</span></summary>`);
      return;
    }
    const tl = nz.timeline.slice().reverse().map(r => `<tr class="${r.changed ? 'wv-chg' : ''}"><td class="n">${esc(r.label)}</td><td class="n">${fmt(r.price)}</td>
        <td><b>${esc(r.primary || '—')}</b>${r.alternate ? ` <span class="wv-dim">／${esc(r.alternate)}</span>` : ''}</td>
        <td class="wv-why">${r.changed ? '🔄 換數法：' + esc(r.why || '') : r.step ? '→ 照原本數法走到下一段' : ''}</td></tr>`).join('');
    const nchg = nz.timeline.filter(r => r.changed).length;
    keepOpen(el, `<summary>📅 浪名演變（${esc(T_().name)}，最近 ${nz.timeline.length} 天）<span class="s">每天收盤時系統只用那時候的資料怎麼數；換了 ${nchg} 次數法</span></summary>
      <div style="overflow-x:auto"><table class="wv-tbl" style="font-size:.9rem"><tr><th>時間</th><th>價格</th><th>主要／備選</th><th>變化</th></tr>${tl}</table></div>
      <div class="wv-why" style="margin-top:4px">她的貼文也是這樣一篇一篇改：同一個數法走到下一段是正常的；🔄 才是換數法（新的轉折讓原本的數法違規、證據成立、或分數被超過）。</div>`);
  }

  function renderRules() {
    const el = $('wv-rules');
    const nz = T_().intra ? nestOf(st.tf) : null;
    const others = ['intra15', 'intra30', 'intra', 'small', 'mid', 'big'].filter(k => k !== deg() && (S.waves || {})[k]).map(k => {
      const p = plain(wv(k).primary);
      return `<li>${DEG_NAME[k]}：${p ? esc(p.title) : '結構不清楚'}</li>`;
    }).join('');
    const mp = Object.values(S.waves || {}).map(v => v.maybe_pivot).filter(Boolean);
    keepOpen(el, `<summary>📖 她的操作紀律、波浪說明、其他級數<span class="s">第一根壓下來上車、多空線、走一口留一口、失速就換數法</span></summary>
      ${nz && nz.ok ? `<ul class="wv-plan">${(nz.plan || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
      ${mp.length ? `<div class="wv-note">📍 ${mp.map(esc).join('<br>📍 ')}</div>` : ''}
      <div class="wv-what"><b>波浪理論是什麼：</b>上漲常走 5 段（1、3、5 往上，2、4 回檔），之後修正走 3 段（A 跌、B 彈、C 跌）；
        修正也可能拉長成兩、三組三段（W-X-Y、W-X-Y-X-Z），或走 A-B-C-D-E 三角形；推進力道變弱時會走成楔形。
        多層浪名＝每一段再拆一層（推動拆 5 段、修正拆 3 段），寫成 C-1-4-b。程式學的是她的<b>框架</b>，學不到她看盤的判斷，所以候選都列出來、用價位裁決。
        <b>回測</b>：浪別之後的漲跌跟平常差不多；她的關卡站上 0.382 後先到 0.5 的比例 96%、隨機 94% → 當「劇本＋停損位置」△。</div>
      <div class="wv-dim" style="margin-top:4px">其他級數：</div><ul class="wv-plan">${others}</ul>`);
  }

  function stateTag(s) {
    if (s == null) return '<span class="wv-st" style="color:var(--muted)">—</span>';
    const t = s > 0 ? '偏多' : s < 0 ? '偏空' : '中性';
    const bg = s > 0 ? 'rgba(240,72,72,.15)' : s < 0 ? 'rgba(34,197,94,.15)' : 'rgba(148,163,184,.15)';
    return `<span class="wv-st" style="background:${bg};color:${colorOf(s)}">${t}</span>`;
  }

  // ── 收起來的區塊（標題直接寫結論）──
  function keepOpen(el, html) {
    if (!el) return;
    const open = el.open;
    el.innerHTML = html;
    el.open = open;
  }

  function valText(r) {
    const v = num(r.value);
    if (v == null) return '—';
    switch (r.unit) {
      case 'pct': return pctS(v * 100);
      case 'z': return (v > 0 ? '+' : '') + v.toFixed(2) + ' 標準差';
      case 'lots': return sgn(v) + ' 口';
      case 'k': return sgn(v / 1e5, 1) + ' 億';
      case 'ratio': return (v > 0 ? '散戶淨多 ' : v < 0 ? '散戶淨空 ' : '') + (Math.abs(v) * 100).toFixed(1) + '%';
      case 'yi': return sgn(v, 0) + ' 億';
      default: return fmt(v, 2);
    }
  }

  function renderComposite() {
    const cp = S.composite;
    const el = $('wv-comp');
    if (!cp) { keepOpen(el, '<summary>🧭 期貨＋籌碼綜合研判<span class="s">資料暫缺</span></summary>'); return; }
    const H = cp.horizons || {};
    const dir = cp.dir || {};
    const head = Object.keys(H).map(h => `${H[h]} ${dir[h] && dir[h].score != null ? (dir[h].score > 0 ? '偏多' : dir[h].score < 0 ? '偏空' : '中性') : '不判斷'}`).join('、');
    const cell = (r, h) => {
      const c = (r.cells || {})[h];
      if (!c) return '<td class="wv-dim">—</td>';
      return `<td>${stateTag(c.state)} ${c.pass ? '<span class="wv-ok" title="回測通過">✅</span>' : '<span class="wv-ref" title="回測沒通過，只當參考">△</span>'}</td>`;
    };
    const rows = (cp.rows || []).map(r => `<tr><td><b>${esc(r.name)}</b><div class="wv-why">${esc(r.meaning)}</div></td>
      <td class="n">${valText(r)}<div class="wv-why">${esc(r.date && r.date.length >= 10 ? md(r.date) : (r.date || ''))}</div></td>
      ${cell(r, 'next')}${cell(r, 'w2')}${cell(r, 'm3')}</tr>`).join('');
    const rs = cp.research || {};
    keepOpen(el, `<summary>🧭 期貨＋籌碼綜合研判：${esc(head)}
        <span class="s">夜盤、正逆價差、外資期貨／選擇權、散戶小台、外資現貨、融資、費半，各自偏多偏空；只有 ✅（回測有效）的算進方向</span></summary>
      <div style="overflow-x:auto"><table class="wv-tbl"><tr><th>指標</th><th>現在</th><th>${esc(H.next || '隔天')}</th><th>${esc(H.w2 || '1～2 週')}</th><th>${esc(H.m3 || '1～3 個月')}</th></tr>${rows}</table></div>
      <div class="wv-what"><b>怎麼看：</b>「偏多／偏空」是現在的數值落在歷史的哪一段（例如散戶小台淨多太多，歷史上反而偏空）。
        ✅＝${esc(rs.is || '')} 找規律、${esc(rs.oos || '')} 驗證都有效；△＝驗證沒過，跟隨便猜差不多，<b>只當描述</b>
        （△ 的偏多偏空是市場一般的解讀，例如散戶太偏多→偏空、融資減少→籌碼乾淨偏多）。
        結論：<b>只有台指期夜盤、前一晚費半對「隔天」有效</b>；其他籌碼對隔天（扣掉夜盤已經反映的）、1～2 週、1～3 個月都沒有預測力。</div>`);
  }

  function spark(hist) {
    if (!hist || hist.length < 2) return '';
    const W = 600, Hh = 70, n = hist.length, bw = W / n;
    const mx = Math.max(...hist.map(x => Math.abs(num(x.chg) || 0)), 1);
    const amts = hist.map(x => num(x.amt)).filter(v => v != null);
    const lo = Math.min(...amts), hi = Math.max(...amts);
    const bars = hist.map((x, i) => {
      const v = num(x.chg) || 0, h = Math.abs(v) / mx * (Hh / 2 - 2);
      const y = v >= 0 ? Hh / 2 - h : Hh / 2;
      return `<rect x="${(i * bw + 1).toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(1, bw - 2).toFixed(1)}" height="${Math.max(0.5, h).toFixed(1)}" fill="${v >= 0 ? C.up : C.down}" opacity=".8"><title>${esc(md(x.date))} ${sgn(v, 1)} 億（餘額 ${fmt(x.amt)} 億）</title></rect>`;
    }).join('');
    const line = hi > lo ? hist.map((x, i) => `${(i * bw + bw / 2).toFixed(1)},${(Hh - 4 - ((num(x.amt) - lo) / (hi - lo)) * (Hh - 8)).toFixed(1)}`).join(' ') : '';
    return `<svg class="wv-spark" viewBox="0 0 ${W} ${Hh}" preserveAspectRatio="none" role="img" aria-label="近 60 天融資每天增減">
      <line x1="0" y1="${Hh / 2}" x2="${W}" y2="${Hh / 2}" stroke="rgba(148,163,184,.3)" stroke-width="1"/>${bars}
      ${line ? `<polyline points="${line}" fill="none" stroke="#facc15" stroke-width="1.5" opacity=".9"/>` : ''}</svg>`;
  }

  function setTf(tf) {
    if (!TF[tf]) return;
    st.tf = tf; lsSet('wv_tf', st.tf);
    if (S) render();
  }

  function last10(rows) {
    if (!rows || !rows.length) return '';
    return `<table class="wv-tbl wv-m10" style="margin-top:10px"><tr><th>日期</th><th>融資餘額</th><th>增減</th><th>%</th></tr>
      ${rows.map(r => `<tr><td>${esc(md(r.date))}</td><td class="n">${fmt(r.amt)} 億</td>
        <td class="n" style="color:${colorOf(r.chg)};font-weight:700">${num(r.chg) == null ? '—' : sgn(r.chg, 1) + ' 億'}</td>
        <td class="n" style="color:${colorOf(r.pct)}">${pctS(r.pct)}</td></tr>`).join('')}</table>`;
  }

  function renderMargin() {
    const m = S.margin || {};
    const el = $('wv-margin');
    if (!m.ok) { keepOpen(el, `<summary>💰 融資餘額<span class="s">${esc(m.note || '資料暫缺')}</span></summary>`); return; }
    const stk = m.streak > 0 ? `連增 ${m.streak} 天` : m.streak < 0 ? `連減 ${-m.streak} 天` : '';
    const yi = (v, nd = 0) => `<b style="color:${colorOf(v)}">${sgn(v, nd)} 億</b>`;
    keepOpen(el, `<summary>💰 融資餘額 ${fmt(m.amt)} 億：${md(m.date)} ${sgn(m.chg1, 0)} 億${stk ? '，' + stk : ''}
        <span class="s">5 天 ${sgn(m.chg5, 0)} 億、20 天 ${sgn(m.chg20, 0)} 億（${pctS(m.pct20, 1)}）；增加＝散戶加碼${m.pending ? '。' + esc(m.pending) : ''}</span></summary>
      <div class="wv-kv">
        <span class="k">餘額（${md(m.date)}）</span><span><b>${fmt(m.amt)} 億</b></span>
        <span class="k">這一天</span><span>${yi(m.chg1, 1)}（${pctS(m.pct1)}）${stk ? `，<b>${stk}</b>` : ''}</span>
        <span class="k">5 天</span><span>${yi(m.chg5)}（${pctS(m.pct5)}）</span>
        <span class="k">20 天</span><span>${yi(m.chg20)}（${pctS(m.pct20)}）</span>
      </div>
      ${last10(m.last10)}
      ${spark(m.hist)}
      <div class="wv-dim" style="font-size:.84rem">柱子＝近 60 天每天增減（紅＝增加、綠＝減少，滑過看數字）；黃線＝餘額走勢</div>
      <div class="wv-what">融資＝散戶借錢買股票。<b>增加</b>代表散戶加碼（漲多時大增要小心過熱），<b>減少</b>代表散戶退場或斷頭。
        回測：融資 5 天、20 天的變化對大盤之後 1～4 週<b>沒有預測力</b>，只當描述。每天晚上 21:30 後更新。</div>`);
  }

  function renderChips() {
    const ch = S.chips || {};
    const fc = S.fut_chips || {};
    const el = $('wv-chips');
    if (!ch.ok) { keepOpen(el, `<summary>🏦 籌碼<span class="s">${esc(ch.note || '籌碼資料暫缺')}</span></summary>`); return; }
    const streak = ch.f_streak > 0 ? `外資連買 ${ch.f_streak} 天` : ch.f_streak < 0 ? `外資連賣 ${-ch.f_streak} 天` : '外資今天沒動';
    const yi = v => `<b style="color:${colorOf(v)}">${fmt(v, 0)} 億</b>`;
    const pos = num(ch.fut_pct) == null ? '' : (ch.fut_pct < 0.2 ? '，在近一年偏空的位置' : ch.fut_pct > 0.8 ? '，在近一年偏多的位置' : '，在近一年中間的位置');
    const rr = num(fc.retail_ratio);
    keepOpen(el, `<summary>🏦 籌碼：${streak}，5 天合計 ${fmt(ch.f5, 0)} 億
        <span class="s">外資、投信、期貨、選擇權、散戶小台（回測：對之後 1～4 週沒有預測力，只當描述）</span></summary>
      <div class="wv-kv">
        <span class="k">外資今天</span><span>${yi(ch.f_net)}（${streak}）</span>
        <span class="k">外資 5 天／20 天</span><span>${yi(ch.f5)}／${yi(ch.f20)}</span>
        <span class="k">投信 5 天</span><span>${yi(ch.t5)}</span>
        <span class="k">外資台指期</span><span><b style="color:${colorOf(ch.fut_f_oi)}">${(ch.fut_f_oi || 0) < 0 ? '淨空單' : '淨多單'} ${fmt(Math.abs(ch.fut_f_oi || 0))} 口</b>
          <span class="wv-dim">（5 天${(ch.fut_chg5 || 0) > 0 ? '多單增加' : '空單增加'} ${fmt(Math.abs(ch.fut_chg5 || 0))} 口${pos}）</span></span>
        ${fc.ok ? `<span class="k">散戶小台</span><span><b style="color:${colorOf(rr)}">${rr >= 0 ? '淨多' : '淨空'} ${(Math.abs(rr) * 100).toFixed(1)}%</b>
          <span class="wv-dim">（${md(fc.date)}，1 天 ${pctS(num(fc.retail_chg1) == null ? null : fc.retail_chg1 * 100, 1)}；小台未平倉 ${fmt(fc.mtx_oi)} 口扣掉三大法人。散戶太偏多常被當反向指標）</span></span>
        <span class="k">外資選擇權</span><span><b style="color:${colorOf(fc.opt_f_bull)}">${(fc.opt_f_bull || 0) >= 0 ? '偏多' : '偏空'} ${fmt(Math.abs(fc.opt_f_bull || 0) / 1e5, 1)} 億</b>
          <span class="wv-dim">（未平倉：買買權＋賣賣權 − 買賣權 − 賣買權；1 天 ${sgn(num(fc.opt_chg1) == null ? null : fc.opt_chg1 / 1e5, 1)} 億）</span></span>` : ''}
      </div>
      <div class="wv-what">紅＝買超／偏多、綠＝賣超／偏空。外資連續大賣常讓人緊張，但回測這些籌碼對大盤之後 1～4 週的漲跌<b>沒有預測力</b>。融資在上面「💰 融資餘額」。</div>`);
  }

  function renderGlobal() {
    const g = S.global || {};
    const el = $('wv-global');
    const sox = (g.items || []).find(i => i.sym === 'SOX' && i.ok);
    const so = g.sox_overnight;
    const rows = (g.items || []).filter(i => i.ok).map(i => `<tr><td>${esc(i.name)}</td><td class="n" style="color:${colorOf(i.chg1)}">${pctS(i.chg1)}</td>
      <td class="n" style="color:${colorOf(i.chg20)}">${pctS(i.chg20, 1)}</td><td>${i.above_ma60 ? '<span style="color:var(--up)">季線上</span>' : '<span style="color:var(--down)">季線下</span>'}</td>
      <td class="n">${num(i.corr60) == null ? '—' : Number(i.corr60).toFixed(2)}</td></tr>`).join('');
    keepOpen(el, `<summary>🌏 國際：${sox ? `費半昨晚 ${pctS(sox.chg1)}、近 20 天 ${pctS(sox.chg20, 1)}、在${sox.above_ma60 ? '季線上' : '季線下'}` : '資料還沒進來'}
        <span class="s">台股最常跟著美國半導體（費半）走${so ? `；昨晚費半換算加權今天平均 ${pctS(so.tw_expect)}` : ''}</span></summary>
      <table class="wv-tbl"><tr><th>指數</th><th>昨天</th><th>20 天</th><th>趨勢</th><th>跟${S.sym === 'TX' ? '台指期' : '加權'}連動</th></tr>${rows}</table>
      ${g.sox_wave ? `<div class="wv-what"><b>費半的波浪：</b>${esc(g.sox_wave.text)}；支撐 ${(g.sox_wave.support || []).map(v => fmt(v)).join('、') || '—'}、壓力 ${(g.sox_wave.resistance || []).map(v => fmt(v)).join('、') || '—'}</div>` : ''}
      <div class="wv-what">「連動」＝近 60 天每天漲跌的相關係數，1 代表完全同步、0 代表沒關係。前一晚費半、台指期夜盤是回測<b>有效</b>的指標（只對隔天有用，對 1～4 週沒有）。</div>`);
  }

  function renderForecast() {
    const fc = S.forecast || {};
    const el = $('wv-fc');
    const r = (hz, nm) => {
      const x = fc[hz];
      return x ? `<tr><td>${nm}</td><td class="n">${rateS(x.p_up)}</td><td class="n">${fmt(x.lo_px)}～${fmt(x.hi_px)}</td></tr>` : '';
    };
    const h20 = fc.h20 || {};
    keepOpen(el, `<summary>📈 過去經驗：20 天後上漲 ${rateS(h20.p_up)}，八成落在 ${fmt(h20.lo_px)}～${fmt(h20.hi_px)}
        <span class="s">${S.sym === 'TX' ? '台指期 2017 年以來' : '26 年來'}任何一天之後的漲跌統計，換算成現在的點數（不是預測方向）</span></summary>
      <table class="wv-tbl"><tr><th>多久之後</th><th>上漲的機率</th><th>八成的情況落在</th></tr>${r('h5', '1 週（5 天）')}${r('h20', '1 個月（20 天）')}${r('h60', '3 個月（60 天）')}</table>
      <div class="wv-what">例：1 個月後「八成落在」＝過去每 10 次有 8 次 20 天後的指數在這個範圍內，可以拿來估「正常會震盪多大」。
        圖上勾「歷史範圍」會畫成灰色錐形（只有日 K）。</div>`);
  }

  function renderContext() {
    const c = S.context || {};
    const el = $('wv-ctx');
    const L = [];
    if (c.regime) L.push(['總經狀態', `${esc(c.regime.label)}（${md(c.regime.date)}）`, '下面總經面板七個因子的綜合判斷']);
    if (c.box) L.push(['均線格局', esc(c.box), '收盤在月線、100 日線上下的組合（宏爺的四種格局）']);
    if (c.mslope) L.push(['月線方向', `${pctS(c.mslope.slope)}・${esc(c.mslope.tier || '')}`, '月線每天變化的幅度（權證小哥的月線斜率）']);
    if (c.crash) L.push(['大跌買點', (c.crash.deep || []).length ? '<b style="color:var(--warn)">出現深跌訊號</b>' : `沒有（離 60 天高點 ${pctS(c.crash.dd * 100, 1)}，要 −15% 才算）`, '過去 5 次深跌，有 4 次之後 2～6 個月是賺的']);
    if (c.dist_day) L.push(['大盤出貨日', c.dist_day.dist_day ? '<b style="color:var(--warn)">今天是</b>' : '沒有', '研究發現不是賣出訊號（5 年 6 次之後都漲）']);
    const head = [c.regime ? esc(String(c.regime.label).replace(/^\S+\s/, '')) : '', c.box ? `格局${esc(c.box)}` : '',
                  c.crash ? ((c.crash.deep || []).length ? '有深跌訊號' : '沒有深跌訊號') : ''].filter(Boolean).join('、');
    keepOpen(el, `<summary>🧭 之前研究的訊號：${head || '—'}<span class="s">網站其他分頁研究過的大盤指標（看加權）</span></summary>
      <table class="wv-tbl">${L.map(([k, v, m]) => `<tr><td style="white-space:nowrap;color:var(--muted)">${k}</td><td>${v}<div class="wv-why">${m}</div></td></tr>`).join('')}</table>`);
  }

  function renderResearch() {
    const r = S.research || {};
    const el = $('wv-research');
    const hold = r.hold || {};
    const NAME = { pivot: '前高前低', pivot_k3: '近期高低點', fib: '費波那契回檔', target: '波浪目標價', ma20: '月線', ma60: '季線', ma120: '半年線', ma240: '年線', round: '整數關卡', multi: '多種重疊' };
    const rows = Object.entries(hold).map(([k, v]) => `<tr><td>${esc(NAME[k] || k)}</td><td class="n">${rateS(v.rate)}</td><td class="n">${rateS(v.placebo)}</td><td>${v.pass ? '✅' : '△ 差不多'}</td></tr>`).join('');
    keepOpen(el, `<summary>🔬 這些方法準不準？（加權 26 年＋台指期 2017 年起回測）<span class="s">結論：只有「前一晚費半」和「台指期夜盤」對隔天有效；費波那契、波浪、支撐壓力、轉折點、籌碼都跟隨便猜差不多；量能規則見下面 ✅／△</span></summary>
      <ul>${(r.summary || []).map(x => `<li>${esc(x)}</li>`).join('')}
        ${['V1', 'V2', 'V2b', 'V3', 'V4', 'V5'].map(k => `<li>量能 ${k}：${esc(vres(k).text || '')}</li>`).join('')}</ul>
      <table class="wv-tbl"><tr><th>價位種類</th><th>先反彈的機率</th><th>隨便畫線</th><th>結果</th></tr>${rows}</table>
      <div class="wv-what">「先反彈的機率」＝價格第一次碰到這個價位後，先反彈一段（約 1 天平均波動）的比例；跟「隨便挑同樣距離的價位」比。
        ✅ 要明顯比隨便畫線好、而且每個時期都一樣才算。${esc(r.data_end || '')} 為止，${esc(r.n_tests || '')} 個測試一起校正。
        <a href="/api/wave/report" target="_blank" rel="noopener">完整研究報告</a>・<a href="/api/wave/report?part=futures" target="_blank" rel="noopener">期貨＋轉折點研究</a></div>`);
  }

  // ── K 線圖（預設只畫：K 棒、月線、季線、轉折、浪別、最近 2 支撐＋2 壓力、轉折點）──
  function futureDays(last, n) {   // 全部用 UTC 算（本地時區 +8 時 toISOString 會少一天）
    const out = [];
    const [y, m, day] = last.split('-').map(Number);
    const d = new Date(Date.UTC(y, m - 1, day));
    while (out.length < n) {
      d.setUTCDate(d.getUTCDate() + 1);
      if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) out.push(d.toISOString().slice(0, 10));
    }
    return out;
  }

  function weekTime(bars, date) {
    for (const b of bars) if (b.time >= date) return b.time;
    return bars.length ? bars[bars.length - 1].time : date;
  }

  function barAt(bars, ts) {      // 分 K：轉折時間 → 圖上那根（30 分 K 用 60 分 K 的時間也對得到開頭那根）
    let best = null;
    for (const b of bars) { if (b.time <= ts) best = b.time; else break; }
    return best;
  }

  function makeChart(kind) {
    const el = $('wv-chart');
    const LW = window.LightweightCharts;
    if (chart) { try { chart.remove(); } catch (e) { /* 已移除 */ } }
    ma = {}; cone = []; pls = []; vma = {};
    const intra = kind === 'intra';
    chart = LW.createChart(el, {
      width: el.clientWidth || undefined, height: el.clientHeight || 540,
      layout: { background: { type: 'solid', color: 'transparent' }, textColor: C.muted, fontSize: 13 },
      grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
      rightPriceScale: { borderColor: 'rgba(148,163,184,.2)', scaleMargins: { top: 0.08, bottom: 0.26 } },   // 下面 22% 給成交量
      timeScale: { borderColor: 'rgba(148,163,184,.2)', rightOffset: 4, timeVisible: intra, secondsVisible: false,
                   tickMarkFormatter: intra ? ((t, type) => type <= 2 ? fmtTpe(t, { month: 'numeric', day: 'numeric' }) : hm(t)) : undefined },
      crosshair: { mode: 0 },
      localization: { priceFormatter: p => Math.round(p).toLocaleString('zh-TW'), ...(intra ? { timeFormatter: t => mdhm(t) } : {}) },
    });
    candle = chart.addCandlestickSeries({ upColor: C.up, downColor: C.down, wickUpColor: C.up, wickDownColor: C.down, borderVisible: false, priceLineVisible: false });
    const noScale = { autoscaleInfoProvider: () => null, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false };
    ma['20'] = chart.addLineSeries({ color: 'rgba(250,204,21,.8)', lineWidth: 1, ...noScale });
    ma['60'] = chart.addLineSeries({ color: 'rgba(56,189,248,.8)', lineWidth: 1, ...noScale });
    zz = chart.addLineSeries({ color: 'rgba(147,170,255,.9)', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    for (let k = 0; k < 3; k++) cone.push(chart.addLineSeries({ color: 'rgba(148,163,184,.55)', lineWidth: 1, lineStyle: k === 1 ? 0 : 2, ...noScale }));
    tline = chart.addLineSeries({ color: 'rgba(251,191,36,.95)', lineWidth: 2, ...noScale });
    // B80 成交量：同一張圖下方 22%（自己的價格軸），5／10 均量線（跟她的圖一樣）
    vol = chart.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.78, bottom: 0 }, visible: false });
    const vline = color => chart.addLineSeries({ priceScaleId: 'vol', color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    vma['5'] = vline('rgba(250,204,21,.85)');
    vma['10'] = vline('rgba(56,189,248,.85)');
    if (!el._ro && window.ResizeObserver) {
      el._ro = new ResizeObserver(() => chart && el.clientWidth > 0 && chart.applyOptions({ width: el.clientWidth, height: el.clientHeight || 540 }));
      el._ro.observe(el);
    }
    chartKind = kind;
  }

  function volMA(src, n) {
    const out = [];
    const buf = [];
    for (const b of src) {
      if (num(b.volume) == null) continue;
      buf.push(Number(b.volume));
      if (buf.length > n) buf.shift();
      if (buf.length === n) out.push({ time: b.time, value: buf.reduce((a, x) => a + x, 0) / n });
    }
    return out;
  }

  async function drawChart() {
    if (!S || S.sym !== st.sym) return;
    if (!(await loadLWC())) { $('wv-chart').innerHTML = '<div class="wv-dim" style="padding:20px">K 線圖載入失敗（CDN 連不上）</div>'; return; }
    const intra = intraIv();
    const kind = intra ? 'intra' : 'day';
    if (!chart || chartKind !== kind) makeChart(kind);
    const el = $('wv-chart');
    if (el.clientWidth > 0) chart.applyOptions({ width: el.clientWidth });     // 藏起來的分頁建立時寬度是 0（審查 R1 Gemini F3）
    const weekly = st.tf === '1wk';
    const src = (S.chart || {})[T_().chart] || [];
    const bars = src.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }));
    if (!bars.length) {
      candle.setData([]); zz.setData([]); vol.setData([]); Object.values(ma).forEach(s => s.setData([])); Object.values(vma).forEach(s => s.setData([])); cone.forEach(s => s.setData([]));
      const note = st.tf === '15m' ? (S.intra || {}).m15 : st.tf === '30m' ? (S.intra || {}).m30 : S.intra;
      $('wv-legend').innerHTML = intra ? `<span>${esc((note || {}).note || '分 K 資料還在累積／回補，稍後再看')}</span>` : '<span>沒有 K 線資料</span>';
      window.__wvState = { sym: S.sym, tf: st.tf, candles: 0, vols: 0, volsExpected: 0 };
      return;
    }
    candle.setData(bars);
    for (const k of ['20', '60']) ma[k].setData(intra || weekly ? [] : ((S.chart || {}).ma || {})[k] || []);
    // 成交量柱：漲紅跌綠半透明，最後一根沒收完的更淡；沒有量的那根留空
    const vd = src.map(b => num(b.volume) == null ? { time: b.time } : {
      time: b.time, value: Number(b.volume),
      color: b.close >= b.open ? (b.partial ? 'rgba(240,72,72,.22)' : 'rgba(240,72,72,.45)') : (b.partial ? 'rgba(34,197,94,.22)' : 'rgba(34,197,94,.45)') });
    vol.setData(vd);
    const done = src.filter(b => !b.partial);
    vma['5'].setData(volMA(done, 5));
    vma['10'].setData(volMA(done, 10));
    const nv = vd.filter(x => x.value != null).length;
    // 轉折連線＋浪別（起點 0 不標）
    const d = deg();
    const w = wv(d);
    const cnt = st.alt ? w.alternate : w.primary;
    const T = intra ? (p => barAt(bars, p.time)) : (p => weekly ? weekTime(bars, p.date) : p.date);
    const srcPts = (w.pivots || []).concat(w.tentative ? [w.tentative] : []);
    const pts = [];
    const seen = new Set();
    for (const p of srcPts) {
      const t = T(p);
      if (t == null || seen.has(t)) continue;
      seen.add(t); pts.push({ time: t, value: p.p });
    }
    pts.sort((a, b) => a.time < b.time ? -1 : 1);
    zz.setData(pts);
    const marks = [];
    const nz = nestOf(st.tf);
    const useNest = intra && st.show.nest && nz && nz.ok;
    const nc = useNest ? (st.alt && nz.alternate ? nz.alternate : nz.primary) : null;
    if (nc) {
      for (const x of nc.marks || []) {
        const t = barAt(bars, x.time);
        if (t == null) continue;
        marks.push({ time: t, position: x.t === 'H' ? 'aboveBar' : 'belowBar',
                     color: x.top ? '#fbbf24' : x.done ? '#64748b' : (/^[1-5]/.test(x.text) ? '#c7d7ff' : C.warn),
                     shape: 'circle', size: 0.1, text: x.text });
      }
      const t0 = barAt(bars, nz.anchor.time);
      if (t0 != null) marks.push({ time: t0, position: nz.dir < 0 ? 'aboveBar' : 'belowBar', color: '#fbbf24', shape: 'circle', size: 0.1, text: '起點' });
    } else if (cnt) {
      const all = cnt.labels || [];
      all.forEach((x, j) => {
        if (x.label === '0') return;
        const t = T(x);
        if (t == null) return;
        const prev = all[j - 1];
        const high = prev ? x.p > prev.p : true;
        marks.push({ time: t, position: high ? 'aboveBar' : 'belowBar', color: /^[1-5]$/.test(x.label) ? '#c7d7ff' : C.warn,
                     shape: 'circle', size: 0.1, text: (x.disp || x.label) + (x.tentative ? '?' : '') });
      });
    }
    marks.sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0);
    candle.setMarkers(marks);
    // 價位線：價位梯上方、下方各最近 2 個＋停損（轉折點）
    pls.forEach(p => { try { candle.removePriceLine(p); } catch (e) { /* 已移除 */ } });
    pls = [];
    const add = (price, color, title, style = 2, width = 1, axis = true) => { if (num(price) != null) pls.push(candle.createPriceLine({ price: Number(price), color, lineWidth: width, lineStyle: style, axisLabelVisible: axis, title })); };
    const lm = lmOf(st.tf);
    const k = (S.key || {})[T_().lv];
    const short = it => it.t || ({ rule: '換數法', key: '停損', inv: '失效', mother: '母尺', zone: '密集區' }[it.kind]) ||
      (it.kind === 'gate' ? String(it.name || '關卡').replace('第', '').slice(0, 3) : it.side === 'up' ? '壓' : '撐');
    if (lm && lm.items) {
      lm.items.filter(it => it.side === 'up').slice(-2).forEach(it => add(it.price, C.up, short(it)));
      lm.items.filter(it => it.side === 'down').slice(0, 2).forEach(it => add(it.price, C.down, short(it)));
    } else {
      const lv = (S.levels || {})[T_().lv] || {};
      (lv.support || []).slice(0, 2).forEach(z => add(z.price, C.down, '撐'));
      (lv.resistance || []).slice(0, 2).forEach(z => add(z.price, C.up, '壓'));
    }
    if (k) add(k.price, C.warn, k.kind.slice(0, 2), 0, 2);
    if (st.show.inv && cnt && num(cnt.invalid) != null) add(cnt.invalid, C.warn, '失效', 1, 1, false);
    if (st.show.fib && w.fib) (w.fib.levels || []).forEach(f => add(f.price, C.fib, `${f.ratio}`, 1, 1, false));
    if (st.show.tg && cnt) (cnt.targets || []).filter(t => t.kind === 'end').slice(0, 2).forEach(t => add(t.price, C.warn, '目標', 1, 1, false));
    // 多層浪名：趨勢線＋關卡
    const tl = useNest && nz.trendline;
    if (tl) {
      const a = barAt(bars, tl.from.time), b = barAt(bars, tl.time_now);
      tline.setData(a != null && b != null && a < b ? [{ time: a, value: tl.from.p }, { time: b, value: tl.now }] : []);
    } else if (tline) tline.setData([]);
    if (useNest) (nz.gates || []).filter(g => /關|分水嶺/.test(g.k)).forEach(g => add(g.price, g.k === '分水嶺' ? '#f472b6' : '#fbbf24', g.k.replace('第', ''), 2, 1, false));
    // 歷史範圍錐形（只有日 K、勾選才畫）
    const fc = S.forecast || {};
    if (!intra && !weekly && st.show.cone && fc.h5 && fc.h20) {
      const last = bars[bars.length - 1].time;
      const fd = futureDays(last, 20);
      const p0 = { time: last, value: S.price };
      cone[0].setData([p0, { time: fd[4], value: fc.h5.hi_px }, { time: fd[19], value: fc.h20.hi_px }]);
      cone[1].setData([p0, { time: fd[4], value: fc.h5.mid_px }, { time: fd[19], value: fc.h20.mid_px }]);
      cone[2].setData([p0, { time: fd[4], value: fc.h5.lo_px }, { time: fd[19], value: fc.h20.lo_px }]);
    } else cone.forEach(s => s.setData([]));
    const n = bars.length;
    const span = intra ? (st.tf === '15m' ? 200 : st.tf === '30m' ? 160 : 120) : weekly ? 110 : (deg() === 'small' ? 90 : deg() === 'mid' ? 170 : 280);
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - span), to: n + (intra || weekly ? 3 : (st.show.cone ? 22 : 4)) });
    const partial = src.length && src[src.length - 1].partial;
    $('wv-legend').innerHTML = `${intra ? '' : '<span><b style="color:#facc15">━</b> 月線</span><span><b style="color:#38bdf8">━</b> 季線</span>'}
      <span><b style="color:#93aaff">━</b> 波浪轉折（${DEG_NAME[deg()] || ''}；${useNest ? `多層浪名 ${esc(nc ? nc.path : '')}，${st.alt ? '備選' : '主要'}數法` : `數字＝第幾段，${st.alt ? '替代' : '主要'}劇本`}）</span>
      ${useNest && nz.trendline ? '<span><b style="color:#fbbf24">━</b> 趨勢線、┅ 關卡</span>' : ''}
      <span><b style="color:${C.down}">┅</b> 下方價位</span><span><b style="color:${C.up}">┅</b> 上方價位</span><span><b style="color:${C.warn}">━</b> ${esc(k ? k.kind : '轉折點')}</span>
      <span>${nv ? `▮ 成交量（${esc(S.vol_unit || '')}；<b style="color:#facc15">━</b> 5 均量 <b style="color:#38bdf8">━</b> 10 均量）` : '這段沒有量的資料'}</span>
      ${intra && S.sym === 'TX' ? '<span>夜盤、日盤接在一起畫</span>' : ''}${partial ? '<span>最後一根還沒收完</span>' : ''}`;
    window.__wvState = { sym: S.sym, tf: st.tf, candles: n, vols: nv, volsExpected: src.filter(b => num(b.volume) != null).length };
  }

  // ── 🤖 AI 圓桌 ──
  async function loadPanel() {
    try {
      panelData = await (await fetch('/api/wave/panel')).json();
      renderPanel(panelData);
      if (S) renderSummary();
      if (panelData.running && !panelPoll) pollJob(panelData.running);
    } catch (e) { $('wv-ai').innerHTML = `<div class="wv-h3">🤖 AI 圓桌</div><div class="wv-dim">載入失敗：${esc(e.message)}</div>`; }
  }

  function renderPanel(d) {
    const ps = d.providers || [];
    const r = d.result;
    const btnTxt = d.running ? '⏳ 討論中…（約 2 分鐘）' : (r ? `🔄 再討論一次（今天還剩 ${d.manual_left} 次）` : `▶ 開始討論（今天還剩 ${d.manual_left} 次）`);
    const btn = ps.length ? `<button class="btn" id="wv-ai-run" ${d.running || !d.manual_left ? 'disabled' : ''}>${btnTxt}</button>` : '';
    let html = `<div class="wv-h3">🤖 AI 圓桌 ${btn}</div>
      <div class="wv-dim">參加：${ps.map(p => esc(p.name)).join('、') || '還沒設定 AI 金鑰'}。先各自看系統資料（加權＋台指期＋籌碼）寫看法、再互相回應，最後整理共識和分歧。</div>`;
    if (d.note) html += `<div class="wv-note">${esc(d.note)}</div>`;
    if (!r) { $('wv-ai').innerHTML = html + '<div class="wv-what">還沒有討論紀錄：每個交易日 16:30 自動討論一次，或按上面的按鈕（約 2 分鐘）。</div>'; bindRun(); return; }
    const mo = r.moderator || {};
    const stanceColor = s => /多/.test(s || '') ? 'var(--up)' : /空/.test(s || '') ? 'var(--down)' : 'var(--muted)';
    const mode = { roundtable: '', single: `⚠ 只有 ${esc(((r.participants || [])[0] || {}).name || '')} 的看法（其他 AI 沒回應）`, none: '⚠ AI 都沒回應' }[r.mode] || '';
    if (mode) html += `<div class="wv-note">${mode}</div>`;
    if (mo.summary) {
      html += `<div class="wv-ai-sum"><span class="wv-stance" style="background:${stanceBg(mo.stance)};color:${stanceColor(mo.stance)}">${esc(mo.stance || '')}</span>
        <b>${esc(mo.summary)}</b> <span class="wv-dim">（${esc(mo.agree_count || '')} 位同意；信心 ${esc(mo.confidence || '')}）</span></div>
        <div class="wv-ai-grid">
          <div><b>大家都同意</b><ul>${(mo.consensus || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>
          <div><b>意見不同</b><ul>${(mo.disagreements || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>
        </div>
        <div style="margin-top:8px"><b>短線：</b>${esc(mo.short || '')}<br><b>波段：</b>${esc(mo.swing || '')}</div>
        <div class="wv-chips">${(mo.watch_levels || []).map(w => `<span class="wv-chip"><b>${fmt(w.price)}</b> ${esc(w.why || '')}</span>`).join('')}</div>`;
    }
    if ((r.flagged || []).length) html += `<div class="wv-note">⚠ 這些價位是 AI 自己算的、不是系統價位，不可靠：${r.flagged.map(v => fmt(v)).join('、')}</div>`;
    const ids = Object.keys(r.round1 || {});
    html += `<details class="wv-who"><summary>看每位 AI 說了什麼（兩輪）</summary>` + ids.map(id => {
      const a = r.round1[id] || {}, b = (r.round2 || {})[id];
      return `<div style="margin:8px 0;padding-top:6px;border-top:1px dashed var(--border)"><b>${esc(a.name)}</b>：<b style="color:${stanceColor(a.stance)}">${esc(a.stance || '')}</b>
        <div>第一輪：${esc(a.short || '')}${a.swing ? '；' + esc(a.swing) : ''}</div>
        ${b ? `<div>第二輪（${esc(b.stance || '')}）：${esc(b.view || '')}${(b.disagree || []).length ? `<div class="wv-dim">不同意：${(b.disagree || []).map(esc).join('；')}</div>` : ''}</div>` : '<div class="wv-dim">第二輪沒有回應</div>'}</div>`;
    }).join('') + (r.failed || []).map(f => `<div class="wv-dim">${esc(f.name)} 第 ${esc(f.round)} 輪沒回應</div>`).join('') + '</details>';
    const nw = r.news || {};
    if ((nw.items || []).length) html += `<details class="wv-who"><summary>討論用的新聞（Google 搜尋近 7 天，${nw.items.length} 則）</summary>
      <ul>${nw.items.map(x => `<li>${esc(x.date || '')} ${esc(x.title)}<span class="wv-dim">：${esc(x.why || '')}</span></li>`).join('')}</ul>
      <div class="wv-dim">${(nw.sources || []).slice(0, 8).map(s => `<a href="${esc(s.uri)}" target="_blank" rel="noopener">${esc(s.title || '來源')}</a>`).join('、')}</div></details>`;
    html += `<div class="wv-what">${esc(md(r.day))} ${esc((r.finished || '').slice(11, 16))}（${r.trigger === 'manual' ? '手動' : '每日自動'}）。AI 只能用系統算的價位，自己編的會標 ⚠；AI 看法不是系統計算、不是投資建議。</div>`;
    $('wv-ai').innerHTML = html;
    bindRun();
  }

  function bindRun() {
    const b = $('wv-ai-run');
    if (b) b.onclick = runPanel;
  }

  async function runPanel() {
    const b = $('wv-ai-run');
    if (b) { b.disabled = true; b.textContent = '⏳ 討論中…（約 2 分鐘）'; }
    try {
      const r = await fetch('/api/wave/panel/run', { method: 'POST' });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.status);
      pollJob(d.job);
    } catch (e) {
      alert('AI 圓桌：' + e.message);
      loadPanel();
    }
  }

  function pollJob(jid) {
    clearInterval(panelPoll);
    panelPoll = setInterval(async () => {
      try {
        const j = await (await fetch('/api/wave/panel/job/' + encodeURIComponent(jid))).json();
        if (j.status !== 'running') { clearInterval(panelPoll); panelPoll = null; if (j.status === 'error') alert('AI 圓桌失敗：' + (j.error || '')); loadPanel(); }
      } catch (e) { /* 下一輪再試 */ }
    }, 6000);
  }

  // ── 分頁 ──
  function setTab(tab) {
    if (!TABS.includes(tab)) tab = 'chart';
    st.tab = tab; lsSet('wv_tab', tab);
    document.querySelectorAll('[data-wv-tab]').forEach(b => { b.classList.toggle('on', b.dataset.wvTab === tab); b.setAttribute('aria-selected', b.dataset.wvTab === tab ? 'true' : 'false'); });
    document.querySelectorAll('.wv-pane').forEach(p => { p.hidden = p.dataset.pane !== tab; });
    if (tab === 'chart' && S) requestAnimationFrame(() => drawChart());          // 切回來明確重設寬度再畫（審查 R1 Gemini F3）
    if (tab === 'macro' && window.__regimeRedraw) requestAnimationFrame(() => window.__regimeRedraw());
  }

  // ── 控制 ──
  function bind() {
    document.querySelectorAll('[data-wv-sym]').forEach(b => b.onclick = () => {
      if (st.sym === b.dataset.wvSym) return;
      st.sym = b.dataset.wvSym; lsSet('wv_sym', st.sym);
      if (DATA[st.sym]) { S = DATA[st.sym]; render(); } else {
        document.querySelectorAll('[data-wv-sym]').forEach(x => x.classList.toggle('on', x.dataset.wvSym === st.sym));
        $('wv-msg').innerHTML = `⏳ ${st.sym === 'TX' ? '台指期' : '加權'}資料載入中…`; $('wv-msg').style.display = 'block';
      }
      load(false);
    });
    document.querySelectorAll('[data-wv-tf]').forEach(b => b.onclick = () => setTf(b.dataset.wvTf));
    document.querySelectorAll('[data-wv-tab]').forEach(b => b.onclick = () => setTab(b.dataset.wvTab));
    document.querySelectorAll('[data-wv-deg]').forEach(b => b.onclick = () => { st.degSel = b.dataset.wvDeg; lsSet('wv_deg2', st.degSel); if (S) render(); });
    $('wv-alt').onclick = () => { st.alt = !st.alt; if (S) { renderHead(); drawChart(); } };
    document.querySelectorAll('[data-wv-show]').forEach(cb => cb.onchange = () => {
      st.show[cb.dataset.wvShow] = cb.checked;
      if (cb.dataset.wvShow === 'nest') lsSet('wv_nest_show', cb.checked ? '1' : '0');
      if (S) drawChart();
    });
    $('wv-refresh').onclick = async () => {
      $('wv-refresh').disabled = true;
      try { await fetch('/api/wave/refresh', { method: 'POST' }); } catch (e) { /* 照樣重新載入 */ }
      setTimeout(async () => { await load(true); $('wv-refresh').disabled = false; }, 15000);
    };
  }

  // 盤中判斷跟後端一樣（台北時間）：加權 週一～五 09:00～13:35；台指期 日盤 08:45～13:50、夜盤 15:00～05:05（週二～六凌晨）
  function isSession(sym) {
    const now = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Taipei' }));
    const m = now.getHours() * 60 + now.getMinutes(), wd = now.getDay();   // 0＝週日
    const weekday = wd >= 1 && wd <= 5;
    if (sym === 'TWII') return weekday && m >= 540 && m <= 815;
    if (weekday && m >= 525 && m <= 830) return true;
    if (weekday && m >= 900) return true;
    return wd >= 2 && wd <= 6 && m <= 305;
  }

  // 上方固定（10-29 用戶）：哨兵捲出畫面＝標題列已經黏在上面 → 加 .stuck 縮小
  function bindSticky() {
    const sen = $('wv-sticky-sentinel'), stk = $('wv-sticky');
    if (!sen || !stk || !('IntersectionObserver' in window)) return;
    new IntersectionObserver(([e]) => stk.classList.toggle('stuck', !e.isIntersecting && e.boundingClientRect.top < 0)).observe(sen);
  }

  window.addEventListener('DOMContentLoaded', () => {
    if (!$('wv-root')) return;
    bindSticky();
    bind();
    setTab(st.tab);
    load(false);
    loadPanel();
    // 盤中每 2 分鐘；總經分頁沒在看（iframe 藏起來）就不抓（PLAN-B77 C2）
    const shown = () => { if (document.visibilityState !== 'visible') return false; try { const fe = window.frameElement; return !fe || fe.offsetParent !== null; } catch (e) { return true; } };
    setInterval(() => { if (isSession(st.sym) && shown()) load(false); }, 120000);
  });
})();
