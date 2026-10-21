// 🌊 大盤解析（PLAN-B74；B75：加權／台指期切換、超短線 60 分 K、30／60 分 K、轉折點、期貨＋籌碼綜合研判、融資增減）
// 10-20 用戶：「字太小、太亂、K 線超混亂，要簡單清晰、說明數據的意義」→ 先給白話結論，細節收起來；K 線預設只畫最重要的線
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
  const DEG_NAME = { intra30: '30 分 K 級數', intra: '60 分 K 級數', small: '小級（日 K）', mid: '中級（週 K）', big: '大級（長期）' };
  // B76：每個週期自己的分析。lv／key＝快照 levels／key 的鍵（舊名：ultra＝60 分、short＝日 K、swing＝週 K）、wv＝waves 的鍵
  const TF = {
    '30m': { name: '30 分', hz: '當沖～隔天', lv: 'm30', wv: 'intra30', chart: 'i30', intra: true, win: '2%' },
    '60m': { name: '60 分', hz: '1～3 天', lv: 'ultra', wv: 'intra', chart: 'i60', intra: true, win: '3%' },
    '1d': { name: '日 K', hz: '1～2 週', lv: 'short', wv: 'small', chart: 'bars', intra: false, win: '6%' },
    '1wk': { name: '週 K', hz: '1～3 個月', lv: 'swing', wv: 'mid', chart: 'weekly', intra: false, win: '15%' },
  };
  const OLD_MODE = { ultra: '60m', short: '1d', swing: '1wk' };
  // 台北時間（分 K 用 UTC epoch，不依賴瀏覽器時區；審查 R2 G-F1）
  const TPE = { timeZone: 'Asia/Taipei', hour12: false };
  const fmtTpe = (ts, opt) => new Intl.DateTimeFormat('zh-TW', { ...TPE, ...opt }).format(new Date(ts * 1000));
  const hm = ts => fmtTpe(ts, { hour: '2-digit', minute: '2-digit' });
  const mdhm = ts => fmtTpe(ts, { month: 'numeric', day: 'numeric' }) + ' ' + hm(ts);
  // AI 立場的底色（CSS 變數不能直接接透明度字尾，用固定的 rgba）
  const stanceBg = s => /多/.test(s || '') ? 'rgba(240,72,72,.15)' : /空/.test(s || '') ? 'rgba(34,197,94,.15)' : 'rgba(148,163,184,.15)';

  const DATA = {};
  let S = null, panelData = null;
  const st = { sym: lsGet('wv_sym', 'TWII'), tf: lsGet('wv_tf', OLD_MODE[lsGet('wv_mode', '')] || '1d'), degSel: lsGet('wv_deg2', 'auto'), alt: false,
               show: { fib: false, tg: false, inv: false, cone: false } };
  if (!TF[st.tf]) st.tf = '1d';
  if (!['TWII', 'TX'].includes(st.sym)) st.sym = 'TWII';
  const T_ = () => TF[st.tf];
  // 進階「自己選級數」只影響日 K／週 K（分 K 一律用自己的級數）
  const deg = () => T_().intra || st.degSel === 'auto' ? T_().wv : st.degSel;
  const modeName = () => `${T_().name}（${T_().hz}）`;
  const intraIv = () => T_().intra;
  const wv = d => (S.waves || {})[d] || {};
  let chart = null, chartKind = null, candle = null, ma = {}, zz = null, cone = [], pls = [], panelPoll = null;

  // ── 波浪 → 白話 ──
  function plain(c) {
    if (!c) return null;
    const cur = c.current, up = c.dir > 0;
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
    renderHead();
    renderSummary();
    renderScenario();
    renderLevels();
    renderAdvice();
    renderLadder();
    renderComposite();
    renderMargin();
    renderChips();
    renderGlobal();
    renderForecast();
    renderContext();
    renderResearch();
    drawChart();
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
    document.querySelectorAll('[data-wv-tf]').forEach(b => b.classList.toggle('on', b.dataset.wvTf === st.tf));
    document.querySelectorAll('[data-wv-deg]').forEach(b => b.classList.toggle('on', b.dataset.wvDeg === st.degSel));
    document.querySelectorAll('[data-wv-show]').forEach(cb => { cb.checked = !!st.show[cb.dataset.wvShow]; });
    $('wv-alt').classList.toggle('on', st.alt);
    $('wv-alt').textContent = st.alt ? '看主要劇本' : '看替代劇本';
  }

  // ── 一眼看懂 ──
  function keyTile(k) {
    if (!k) return { k: '轉折點', v: '—', m: T_().intra ? `${T_().name} K 資料還不夠` : '最近沒有可用的轉折', color: 'var(--warn)' };
    let m;
    if (k.broken) m = k.side === 'below' ? '<b>已經跌破</b> → 這段上漲可能結束，照停損' : '<b>已經站上</b> → 這段下跌可能結束';
    else m = k.side === 'below' ? '跌破＝這段上漲可能結束' : '站上＝這段下跌可能結束';
    if (k.leg_start && !k.broken) m += k.side === 'below' ? '（中間沒有回檔低點，就用起漲點）' : '（中間沒有反彈高點，就用起跌點）';
    if (num(k.wave_invalid) != null) m += `。波浪最後防線 ${fmt(k.wave_invalid)}（${pctS(k.wave_invalid_pct, 1)}）`;
    if (k.sig) m += '。回測：過了通常會再走一段';
    return { k: k.kind, v: `${fmt(k.price)}<small style="color:var(--muted)">${pctS(k.dist_pct, 1)}</small>`, m, color: 'var(--warn)' };
  }

  function fourthTile() {
    if (S.sym === 'TX') {
      const b = S.basis;
      if (!b) return { k: '期現價差', v: '—', m: '加權資料還沒進來', color: '' };
      return { k: '期現價差', v: `${sgn(b.pts)}<small style="color:var(--muted)">${pctS(b.pct, 2)}</small>`, color: colorOf(b.pts),
               m: `台指期比加權${b.pts >= 0 ? '高' : '低'} ${fmt(Math.abs(b.pts))} 點（${b.pts >= 0 ? '正價差' : '逆價差'}，${esc(b.when || '')}）。對之後漲跌沒有預測力；6～8 月除息季常逆價差` };
    }
    const o = S.open_ref, so = (S.global || {}).sox_overnight;
    if (o) {
      const when = o.live ? '夜盤進行中（即時）' : (o.date ? `${md(o.date)} 夜盤` : '夜盤');
      return { k: o.live ? '明天開盤參考' : '今天開盤參考', v: pctS(o.gap), color: colorOf(o.gap),
               m: `${when} ${pctS(o.night_ret)} → 歷史平均開盤 ${pctS(o.gap)}（±${fmt(o.gap_sd, 1)}%）、收盤 ${pctS(o.r1)}。回測最準的領先指標` };
    }
    return { k: '今天開盤參考', v: so ? pctS(so.tw_expect) : '—', color: so ? colorOf(so.tw_expect) : '',
             m: so ? `費半昨晚 ${pctS(so.sox_ret)}，過去平均讓加權隔天 ${pctS(so.tw_expect)}（±${fmt(so.sd, 1)}%）（夜盤資料還沒進來，先用費半）` : '美股資料還沒進來' };
  }

  function stateTag(s) {
    if (s == null) return '<span class="wv-st" style="color:var(--muted)">—</span>';
    const t = s > 0 ? '偏多' : s < 0 ? '偏空' : '中性';
    const bg = s > 0 ? 'rgba(240,72,72,.15)' : s < 0 ? 'rgba(34,197,94,.15)' : 'rgba(148,163,184,.15)';
    return `<span class="wv-st" style="background:${bg};color:${colorOf(s)}">${t}</span>`;
  }

  function compLine() {
    const cp = S.composite;
    if (!cp) return '';
    const dn = cp.dir.next || {}, w2 = cp.dir.w2 || {};
    const lab = d => d.score == null ? `<span class="wv-dim">${esc(d.label)}</span>` : stateTag(d.score);
    const o = S.open_ref;
    const nx = o ? `（夜盤 ${pctS(o.night_ret)} → 加權${o.live ? '明天' : '今天'}開盤參考 ${pctS(o.gap)}）` : '';
    const desc = (cp.rows || []).filter(r => ['fut_chg1', 'retail', 'f_net'].includes(r.key)).map(r => {
      const c = r.cells.next || r.cells.w2 || {};
      return `${esc(r.name)}${c.state == null ? '' : (c.state > 0 ? '偏多' : c.state < 0 ? '偏空' : '中性')}`;
    }).join('、');
    return `<div class="wv-compline">🧭 <b>期貨＋籌碼綜合</b>：隔天 ${lab(dn)}${nx}｜1～2 週、1～3 個月 ${lab(w2)}
      <span class="wv-dim">（${esc(desc)}——回測都沒有預測力，只當參考；↓ 下面看完整表）</span></div>`;
  }

  function renderSummary() {
    const w = wv(deg());
    const p = plain(w.primary);
    const lv = (S.levels || {})[T_().lv] || {};
    const s1 = (lv.support || [])[0], s2 = (lv.support || [])[1];
    const r1 = (lv.resistance || [])[0], r2 = (lv.resistance || [])[1];
    const tile = (k, v, m, color) => `<div class="wv-tile"><div class="k">${k}</div><div class="v" style="color:${color || 'var(--text)'}">${v}</div><div class="m">${m}</div></div>`;
    const kt = keyTile((S.key || {})[T_().lv]);
    const ft = fourthTile();
    let ai = '';
    const pr = panelData && panelData.result;
    const mo = pr && pr.moderator;
    if (mo && mo.summary) {
      const sc = /多/.test(mo.stance || '') ? 'var(--up)' : /空/.test(mo.stance || '') ? 'var(--down)' : 'var(--muted)';
      ai = `<div class="wv-ailine">🤖 <b>AI 圓桌</b>（${md(pr.day)}）：<b style="color:${sc}">${esc(mo.stance || '')}</b>・${esc(mo.summary)} <span class="wv-dim">${esc(mo.agree_count || '')}　↓ 下面看討論內容</span></div>`;
    } else if (panelData) {
      ai = `<div class="wv-ailine wv-dim">🤖 AI 圓桌還沒討論（每個交易日 16:30 自動討論，也可以在下面按「開始討論」）</div>`;
    }
    const inote = st.tf === '30m' ? ((S.intra || {}).m30 || {}) : st.tf === '60m' ? (S.intra || {}) : { ok: true };
    const intraNote = !inote.ok ? `<div class="wv-note">${esc(inote.note || '分 K 資料還不夠')}</div>` : '';
    $('wv-sum').innerHTML = `
      <div class="wv-head">${S.sym === 'TX' ? '台指期・' : ''}${esc(T_().name)}（${esc(T_().hz)}）走勢：${p ? esc(p.title) : '結構不清楚，看支撐壓力就好'}
        <small>${p ? esc(p.meaning) : ''}</small></div>
      ${intraNote}
      <div class="wv-tiles">
        ${tile('最近支撐', s1 ? `${fmt(s1.price)}<small style="color:var(--muted)">${pctS(s1.dist_pct, 1)}</small>` : '—',
               s1 ? `跌到這附近容易止跌；${s2 ? `跌破的話下一個看 ${fmt(s2.price)}` : '再往下附近沒有支撐'}` : '附近沒有支撐區', 'var(--down)')}
        ${tile('最近壓力', r1 ? `${fmt(r1.price)}<small style="color:var(--muted)">${pctS(r1.dist_pct, 1)}</small>` : '—',
               r1 ? `漲到這附近容易遇到賣壓；${r2 ? `站上的話下一個看 ${fmt(r2.price)}` : '再往上附近沒有壓力'}` : '附近沒有壓力區', 'var(--up)')}
        ${tile(kt.k, kt.v, kt.m, kt.color)}
        ${tile(ft.k, ft.v, ft.m, ft.color)}
      </div>
      ${compLine()}
      ${ai}
      <div class="wv-what"><b>怎麼用：</b>支撐、壓力是過去高低點、整數關卡、均線、費波那契重疊的位置；<b>${esc(kt.k)}</b>是這一段走勢裡最近一個反向的小轉折，
        過了代表這一段可能結束（比「波浪最後防線」近很多，適合當停損）。回測這些價位「守住」或「過了繼續走」的機率都跟隨便畫一條線差不多，
        所以當作<b>參考點＋停損位置</b>，不是一定會在那裡反轉。${esc(S.disclaimer || '')}。</div>`;
  }

  // ── 劇本 ──
  function countBox(c, label) {
    const p = plain(c);
    if (!p) return `<div class="wv-count"><div class="t">${label}：結構不清楚</div><div class="p wv-dim">最近的轉折不符合波浪規則，先看支撐壓力</div></div>`;
    const ends = (c.targets || []).filter(t => t.kind === 'end').slice(0, 2);
    return `<div class="wv-count"${label === '替代劇本' ? ' style="border-left-color:var(--warn);background:rgba(251,146,60,.05)"' : ''}>
      <div class="wv-dim">${label}</div><div class="t">${esc(p.title)}</div>
      <div class="wv-steps">${p.steps.map(s => `<span class="${s === p.cur ? 'on' : ''}">${s}</span>`).join('')}</div>
      <div class="p">${esc(p.meaning)}</div>
      ${ends.length ? `<div class="p">這段可能走到：${ends.map(t => `<b>${fmt(t.price)}</b>`).join('、')}</div>` : ''}
      ${invText(c) ? `<div class="x">${esc(invText(c))}</div>` : ''}</div>`;
  }

  function renderScenario() {
    const d = deg();
    const w = wv(d);
    const others = ['intra30', 'intra', 'small', 'mid', 'big'].filter(k => k !== d && (S.waves || {})[k]).map(k => {
      const p = plain(wv(k).primary);
      return `<div>${DEG_NAME[k]}：${p ? esc(p.title) : '結構不清楚'}</div>`;
    }).join('');
    const mp = Object.values(S.waves || {}).map(v => v.maybe_pivot).filter(Boolean);
    $('wv-scen').innerHTML = `
      <div class="wv-h3">📜 波浪劇本 <span class="wv-dim">${S.sym === 'TX' ? '台指期・' : ''}${DEG_NAME[d] || ''}</span></div>
      ${(S.waves || {})[d] ? countBox(w.primary, '主要劇本') : `<div class="wv-dim">${esc((S.intra || {}).note || '這個級數還沒有資料')}</div>`}
      ${w.alternate ? `<details class="wv-alt-box"><summary>另一種數法（替代劇本）</summary>${countBox(w.alternate, '替代劇本')}</details>` : ''}
      ${mp.length ? `<div class="wv-note">📍 ${mp.map(esc).join('<br>📍 ')}</div>` : ''}
      ${d === 'intra30' ? '<div class="wv-note">30 分 K 的級數只有 60 天資料校準，只當參考</div>' : ''}
      <div class="wv-what"><b>波浪理論是什麼：</b>上漲常走 5 段（1、3、5 往上，2、4 回檔），之後修正走 3 段（A 跌、B 彈、C 跌）。
        程式用固定規則判斷現在走到哪一段。<b>很主觀</b>：26 年回測，各段之後的漲跌跟平常差不多，所以只當「劇本」參考。</div>
      <details class="wv-alt-box"><summary>其他級數怎麼看</summary><div class="p" style="font-size:.92rem">${others}</div></details>`;
  }

  // ── 支撐壓力表 ──
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

  function renderLevels() {
    const lv = (S.levels || {})[T_().lv] || {};
    const res = (lv.resistance || []).slice().reverse();
    const sup = lv.support || [];
    const row = (z, side) => `<tr><td class="n" style="color:${side === 'S' ? 'var(--down)' : 'var(--up)'};font-weight:800;font-size:1.05rem">${fmt(z.price)}</td>
      <td class="n" style="color:var(--muted)">${pctS(z.dist_pct, 1)}</td>
      <td>${side === 'S' ? '支撐' : '壓力'}${(z.sources || []).length >= 2 ? '<span class="wv-dim">（多種重疊，較重要）</span>' : ''}</td>
      <td class="wv-why wv-hide-m">${esc(srcText(z))}</td></tr>`;
    const holds = [...sup, ...res].map(z => (z.hold || {})).filter(h => num(h.rate) != null);
    const avgH = holds.length ? holds.reduce((a, h) => a + h.rate, 0) / holds.length : null;
    const avgP = holds.length ? holds.reduce((a, h) => a + (h.placebo || 0), 0) / holds.length : null;
    $('wv-levels').innerHTML = `
      <div class="wv-h3">🎯 ${S.sym === 'TX' ? '台指期・' : ''}${modeName()}的支撐與壓力 <span class="wv-dim">最上面可以切換週期</span></div>
      <table class="wv-tbl"><tr><th>價位</th><th>離現價</th><th>是什麼</th><th class="wv-hide-m">為什麼是這裡</th></tr>
        ${res.map(z => row(z, 'R')).join('') || '<tr><td colspan="4" class="wv-dim">上方附近沒有壓力</td></tr>'}
        <tr class="wv-now"><td colspan="4">現在 ${fmt(S.price, 0)}</td></tr>
        ${sup.map(z => row(z, 'S')).join('') || '<tr><td colspan="4" class="wv-dim">下方附近沒有支撐</td></tr>'}
      </table>
      ${(lv.note || []).map(n => `<div class="wv-note">${esc(n)}</div>`).join('')}
      <div class="wv-what">${avgH != null ? `歷史上碰到這類價位後，<b>先反彈的機率約 ${rateS(avgH)}</b>（隨便畫一條線約 ${rateS(avgP)}）。` : ''}
        ${T_().intra ? `${T_().name} K 用自己的轉折、昨天高低收、` + (S.sym === 'TX' ? '夜盤高低、' : '') + `日 K 月線和整數關卡（上下 ${T_().win} 內）。` : ''}
        意思是：價位附近值得注意，但不保證會撐住或壓住，<b>跌破支撐就要照停損</b>。</div>`;
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

  // ── 💡 操作建議（B76：條件式細部解讀；總經原本的建議由總經程式填在上面）──
  function renderAdvice() {
    const a = S.advice || {};
    const el = $('wv-advice');
    if (!el) return;
    if (!a.ok) { el.innerHTML = '<div class="wv-dim" style="margin-top:8px">細部解讀暫時算不出來，先看上面總經的建議。</div>'; return; }
    const rg = a.range || {};
    const lines = (a.lines || []).map(x => `<span class="k">${esc(x.k)}</span><span>${esc(x.t)}</span>`).join('');
    const conds = (a.conds || []).map(c => `<div class="wv-cond ${c.side === 'up' ? 'up' : 'down'}">
        <b style="color:${c.side === 'up' ? 'var(--up)' : 'var(--down)'}">${c.side === 'up' ? '站上' : '跌破'} ${fmt(c.price)}</b>
        <span class="wv-dim">（${esc(c.label)}，${pctS((c.price / S.price - 1) * 100, 1)}）</span><br>${esc(c.act)}</div>`).join('');
    el.innerHTML = `
      <div class="wv-adv-head">${S.sym === 'TX' ? '台指期・' : ''}<span class="rg">建議持股 ${esc(rg.lo)}～${esc(rg.hi)}%</span>：${esc(String(a.headline || '').replace(/^建議持股[^：]*：/, ''))}</div>
      <div class="wv-dim" style="font-size:.88rem">為什麼：${(rg.why || []).map(esc).join('；')}（總經基本 ${esc(rg.base_lo)}～${esc(rg.base_hi)}%）</div>
      <div class="wv-adv-lines" style="margin-top:8px">${lines}</div>
      ${conds ? `<div class="wv-conds">${conds}</div>` : `<div class="wv-note">${esc(a.cond_note || '附近沒有系統價位')}</div>`}
      <div class="wv-what">${esc(a.note || '')}</div>`;
  }

  // ── 📶 多週期一覽（小週期 → 大週期；點一列切過去）──
  function renderLadder() {
    const rows = S.ladder || [];
    const el = $('wv-ladder');
    if (!el) return;
    const dirTxt = d => d === 1 ? '<span class="wv-dir" style="color:var(--up)">↑ 上漲段</span>' : d === -1 ? '<span class="wv-dir" style="color:var(--down)">↓ 下跌段</span>' : '<span class="wv-dir wv-dim">－ 不明</span>';
    const tr = rows.map(r => {
      const k = r.key;
      const kt = k ? `${esc(k.kind)} <b>${fmt(k.price)}</b> <span class="wv-dim">${pctS(k.dist_pct, 1)}${k.broken ? (k.side === 'below' ? '・已跌破' : '・已站上') : ''}</span>` : '<span class="wv-dim">—</span>';
      const sr = `<span style="color:var(--down)">${r.s1 ? fmt(r.s1.price) : '—'}</span>／<span style="color:var(--up)">${r.r1 ? fmt(r.r1.price) : '—'}</span>`;
      return `<tr data-tf="${esc(r.tf)}" class="${r.tf === st.tf ? 'on' : ''}" title="點一下切到 ${esc(r.label)}"><td style="white-space:nowrap"><b>${esc(r.label)}</b><div class="wv-why">${esc((TF[r.tf] || {}).hz || '')}</div></td>
        <td>${dirTxt(r.dir)}</td><td>${esc(r.title)}</td><td>${kt}</td><td class="n wv-hide-m">${sr}</td></tr>`;
    }).join('');
    el.innerHTML = `<div class="wv-h3">📶 多週期一覽 <span class="wv-dim">小週期 → 大週期，點一列切過去</span></div>
      <div style="font-size:1.02rem;font-weight:700;margin-bottom:6px">${esc(S.ladder_text || '')}</div>
      <table class="wv-tbl wv-ladder-tbl"><tr><th>週期</th><th>這一段</th><th>波浪</th><th>轉折點</th><th class="wv-hide-m">最近撐／壓</th></tr>${tr}</table>
      <div class="wv-what">每個週期用自己的 K 棒和級數算（30 分 K 只有 60 天資料校準，只當參考）。小週期先轉向、大週期還沒跟上時，通常是反彈或回檔；四個都同方向才是比較一致的趨勢。</div>`;
    el.querySelectorAll('tr[data-tf]').forEach(x => x.onclick = () => setTf(x.dataset.tf));
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
    keepOpen(el, `<summary>🔬 這些方法準不準？（加權 26 年＋台指期 2017 年起回測）<span class="s">結論：只有「前一晚費半」和「台指期夜盤」對隔天有效；費波那契、波浪、支撐壓力、轉折點、籌碼都跟隨便猜差不多</span></summary>
      <ul>${(r.summary || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
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
    ma = {}; cone = []; pls = [];
    const intra = kind === 'intra';
    chart = LW.createChart(el, {
      height: el.clientHeight || 500, layout: { background: { type: 'solid', color: 'transparent' }, textColor: C.muted, fontSize: 13 },
      grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
      rightPriceScale: { borderColor: 'rgba(148,163,184,.2)', scaleMargins: { top: 0.1, bottom: 0.08 } },
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
    if (!el._ro && window.ResizeObserver) {
      el._ro = new ResizeObserver(() => chart && chart.applyOptions({ width: el.clientWidth, height: el.clientHeight || 500 }));
      el._ro.observe(el);
    }
    chartKind = kind;
  }

  async function drawChart() {
    if (!(await loadLWC())) { $('wv-chart').innerHTML = '<div class="wv-dim" style="padding:20px">K 線圖載入失敗（CDN 連不上）</div>'; return; }
    const intra = intraIv();
    const kind = intra ? 'intra' : 'day';
    if (!chart || chartKind !== kind) makeChart(kind);
    const weekly = st.tf === '1wk';
    let bars = S.chart[T_().chart] || [];
    bars = bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }));
    if (!bars.length) {
      candle.setData([]); zz.setData([]); Object.values(ma).forEach(s => s.setData([])); cone.forEach(s => s.setData([]));
      $('wv-legend').innerHTML = intra ? `<span>${esc(((st.tf === '30m' ? (S.intra || {}).m30 : S.intra) || {}).note || '分 K 資料還在累積／回補，稍後再看')}</span>` : '<span>沒有 K 線資料</span>';
      return;
    }
    candle.setData(bars);
    for (const k of ['20', '60']) ma[k].setData(intra || weekly ? [] : (S.chart.ma[k] || []));
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
    if (cnt) {
      const all = cnt.labels || [];
      all.forEach((x, j) => {
        if (x.label === '0') return;
        const t = T(x);
        if (t == null) return;
        const prev = all[j - 1];
        const high = prev ? x.p > prev.p : true;
        marks.push({ time: t, position: high ? 'aboveBar' : 'belowBar', color: 'ABC'.includes(x.label) ? C.warn : '#c7d7ff',
                     shape: 'circle', size: 0.1, text: x.label + (x.tentative ? '?' : '') });
      });
    }
    marks.sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0);
    candle.setMarkers(marks);
    // 價位線
    pls.forEach(p => { try { candle.removePriceLine(p); } catch (e) { /* 已移除 */ } });
    pls = [];
    const add = (price, color, title, style = 2, width = 1, axis = true) => { if (num(price) != null) pls.push(candle.createPriceLine({ price: Number(price), color, lineWidth: width, lineStyle: style, axisLabelVisible: axis, title })); };
    const lv = (S.levels || {})[T_().lv] || {};
    (lv.support || []).slice(0, 2).forEach(z => add(z.price, C.down, '撐'));
    (lv.resistance || []).slice(0, 2).forEach(z => add(z.price, C.up, '壓'));
    const k = (S.key || {})[T_().lv];
    if (k) add(k.price, C.warn, k.kind.slice(0, 2), 0, 2);
    if (st.show.inv && cnt && num(cnt.invalid) != null) add(cnt.invalid, C.warn, '失效', 1, 1, false);
    if (st.show.fib && w.fib) (w.fib.levels || []).forEach(f => add(f.price, C.fib, `${f.ratio}`, 1, 1, false));
    if (st.show.tg && cnt) (cnt.targets || []).filter(t => t.kind === 'end').slice(0, 2).forEach(t => add(t.price, C.warn, '目標', 1, 1, false));
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
    const span = intra ? (st.tf === '30m' ? 160 : 120) : weekly ? 110 : (deg() === 'small' ? 90 : deg() === 'mid' ? 170 : 280);
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - span), to: n + (intra || weekly ? 3 : (st.show.cone ? 22 : 4)) });
    const src = S.chart[T_().chart];
    const partial = src && src.length && src[src.length - 1].partial;
    $('wv-legend').innerHTML = `${intra ? '' : '<span><b style="color:#facc15">━</b> 月線</span><span><b style="color:#38bdf8">━</b> 季線</span>'}
      <span><b style="color:#93aaff">━</b> 波浪轉折（${DEG_NAME[deg()] || ''}；數字＝第幾段，${st.alt ? '替代' : '主要'}劇本）</span>
      <span><b style="color:${C.down}">┅</b> 支撐</span><span><b style="color:${C.up}">┅</b> 壓力</span><span><b style="color:${C.warn}">━</b> ${esc(k ? k.kind : '轉折點')}</span>
      ${intra && S.sym === 'TX' ? '<span>夜盤、日盤接在一起畫</span>' : ''}${partial ? '<span>最後一根還沒收完</span>' : ''}
      `;
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

  // ── 控制 ──
  function bind() {
    document.querySelectorAll('[data-wv-sym]').forEach(b => b.onclick = () => {
      if (st.sym === b.dataset.wvSym) return;
      st.sym = b.dataset.wvSym; lsSet('wv_sym', st.sym);
      if (DATA[st.sym]) { S = DATA[st.sym]; render(); } else { document.querySelectorAll('[data-wv-sym]').forEach(x => x.classList.toggle('on', x.dataset.wvSym === st.sym)); }
      load(false);
    });
    document.querySelectorAll('[data-wv-tf]').forEach(b => b.onclick = () => setTf(b.dataset.wvTf));
    document.querySelectorAll('[data-wv-deg]').forEach(b => b.onclick = () => { st.degSel = b.dataset.wvDeg; lsSet('wv_deg2', st.degSel); if (S) render(); });
    $('wv-alt').onclick = () => { st.alt = !st.alt; if (S) { renderHead(); drawChart(); } };
    document.querySelectorAll('[data-wv-show]').forEach(cb => cb.onchange = () => { st.show[cb.dataset.wvShow] = cb.checked; if (S) drawChart(); });
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

  window.addEventListener('DOMContentLoaded', () => {
    if (!$('wv-root')) return;
    bind();
    load(false);
    loadPanel();
    setInterval(() => { if (isSession(st.sym) && document.visibilityState === 'visible') load(false); }, 120000);
  });
})();
