/* ── 跨 iframe 選股（從大戶選股主頁 postMessage 觸發） ── */
window.addEventListener('message', e => {
  if (e.data && e.data.type === 'selectStock' && e.data.code) {
    selectUnderlying(e.data.code, e.data.name || e.data.code);
  }
});

/* ── State ── */
let currentUnderlying = null;   // { code, name }
let currentSide = 'call';
let holdingDays = 7;
let maxOtmPct = 10;
let sortMode = 'entry';   // 'entry' | 'total'
let currentCards = [];          // raw API response
let quoteTimer = null;
let searchTimeout = null;
let lastFetchTime = null;

/* ── Helpers ── */
const $ = id => document.getElementById(id);
const show = el => el.classList.remove('hidden');
const hide = el => el.classList.add('hidden');

function fmt(v, d = 2) {
  if (v == null || v === '' || v === '—') return '—';
  const n = parseFloat(v);
  return isNaN(n) ? '—' : n.toFixed(d);
}
function fmtPct(v, d = 1) {
  if (v == null) return '—';
  return fmt(v * 100, d) + '%';
}
function fmtSign(v) {
  if (v == null) return '—';
  const n = parseFloat(v);
  if (isNaN(n)) return '—';
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
}

/* ── Search ── */
$('searchInput').addEventListener('input', e => {
  clearTimeout(searchTimeout);
  const q = e.target.value.trim();
  if (!q) { hide($('searchDropdown')); return; }
  searchTimeout = setTimeout(() => doSearch(q), 250);
});

$('searchInput').addEventListener('keydown', e => {
  if (e.key === 'Escape') { hide($('searchDropdown')); $('searchInput').blur(); }
});

document.addEventListener('click', e => {
  if (!e.target.closest('.search-wrap')) hide($('searchDropdown'));
});

async function doSearch(q) {
  try {
    const res = await fetch(`/warrant/api/search?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    renderDropdown(data.results || []);
  } catch { renderDropdown([]); }
}

function renderDropdown(results) {
  const dd = $('searchDropdown');
  if (!results.length) { hide(dd); return; }
  dd.innerHTML = results.map(r => `
    <div class="dropdown-item" onclick="selectUnderlying('${r.code}','${escHtml(r.name)}')">
      <span>${escHtml(r.name)} <span style="color:var(--muted);font-size:13px">${r.code}</span></span>
      <span class="cnt">${r.warrant_count} 檔</span>
    </div>`).join('');
  show(dd);
}

/* ── Quick Tags ── */
document.querySelectorAll('.quick-tag').forEach(tag => {
  tag.addEventListener('click', () => {
    const code = tag.dataset.code;
    const name = tag.textContent;
    selectUnderlying(code, name);
  });
});

/* ── Select Underlying ── */
function selectUnderlying(code, name) {
  hide($('searchDropdown'));
  $('searchInput').value = name + ' ' + code;
  currentUnderlying = { code, name };
  loadWarrants();
  onFuturesStockSelected(code);
}

/* ── Side Switch ── */
function setSide(side) {
  currentSide = side;
  $('btnCall').classList.toggle('active', side === 'call');
  $('btnPut').classList.toggle('active', side === 'put');
  if (currentUnderlying) loadWarrants();
}

/* ── Sort Mode ── */
function setSort(mode) {
  sortMode = mode;
  $('btnSortEntry').classList.toggle('active', mode === 'entry');
  $('btnSortTotal').classList.toggle('active', mode === 'total');
  if (currentUnderlying) loadWarrants();
}

/* ── Sliders ── */
function onSliderChange(val) {
  holdingDays = parseInt(val);
  $('holdingDaysLabel').textContent = holdingDays;
  if (currentUnderlying) loadWarrants();
}

function onOtmChange(val) {
  maxOtmPct = parseInt(val);
  $('otmLabel').textContent = maxOtmPct;
  if (currentUnderlying) loadWarrants();
}

/* ── Load Warrants ── */
async function loadWarrants() {
  if (!currentUnderlying) return;

  $('resultArea').innerHTML = '<div class="loading">載入中...</div>';
  hide($('excludedSummary'));
  show($('controls'));

  try {
    const url = `/warrant/api/warrants?underlying=${currentUnderlying.code}&side=${currentSide}&holding_days=${holdingDays}&max_otm=${maxOtmPct / 100}&sort=${sortMode}`;
    const res = await fetch(url);
    if (!res.ok || res.headers.get('content-type')?.includes('text/html')) {
      const txt = await res.text();
      const msg = (txt.includes('<') || res.status >= 500)
        ? '伺服器喚醒中，請稍後 30 秒再試'
        : `載入失敗：${res.status} ${txt.slice(0, 80)}`;
      $('resultArea').innerHTML = `<div class="empty">${msg}
        <button onclick="loadWarrants()" style="margin-left:8px;padding:3px 10px;background:var(--accent);border:none;border-radius:4px;color:#fff;cursor:pointer;font-size:13px">🔄 重試</button>
      </div>`;
      return;
    }
    const data = await res.json();

    updateUnderlyingBar(data.underlying || {});
    updateAfterHours(data.market_state);
    currentCards = data.warrants || [];
    renderCards(currentCards);
    renderExcluded(data.excluded_count || 0, data.excluded_reasons || []);
    lastFetchTime = Date.now();
    startQuoteTimer();
  } catch (e) {
    const isHtml = e.message.includes("token '<'") || e.message.includes('Unexpected token');
    $('resultArea').innerHTML = `<div class="empty">
      ${isHtml ? '伺服器喚醒中，請稍後 30 秒再試' : '載入失敗：' + e.message}
      <button onclick="loadWarrants()" style="margin-left:8px;padding:3px 10px;background:var(--accent);border:none;border-radius:4px;color:#fff;cursor:pointer;font-size:13px">🔄 重試</button>
    </div>`;
  }
}

/* ── Underlying Bar ── */
function updateUnderlyingBar(ul) {
  show($('underlyingBar'));
  $('ulName').textContent = ul.name || '—';
  $('ulCode').textContent = ul.code || '';
  $('ulPrice').textContent = ul.price != null ? ul.price.toFixed(2) : '—';
  const chg = ul.change_pct;
  const chgEl = $('ulChange');
  if (chg != null) {
    chgEl.textContent = fmtSign(chg);
    chgEl.className = 'ul-change ' + (chg >= 0 ? 'green' : 'red');
  } else {
    chgEl.textContent = '';
    chgEl.className = 'ul-change';
  }
  $('ulHV').textContent = ul.hv20 != null ? `HV20 ${fmtPct(ul.hv20)}` : 'HV20 —';
  $('quoteTime').textContent = ul.data_time ? ul.data_time.slice(11, 16) : '—';
  $('quoteTime').classList.remove('stale');
  const st = ul.market_state || '';
  const stateMap = { OPEN: '盤中', PRE_OPEN: '開盤前', CLOSING_AUCTION: '收盤競價', AFTER_HOURS: '盤後' };
  $('stateLabel').textContent = stateMap[st] || st;
}

function updateAfterHours(state) {
  if (state === 'AFTER_HOURS' || state === 'PRE_OPEN') {
    show($('afterHoursBanner'));
  } else {
    hide($('afterHoursBanner'));
  }
}

/* ── Quote Timer ── */
function startQuoteTimer() {
  if (quoteTimer) clearInterval(quoteTimer);
  quoteTimer = setInterval(() => {
    if (!lastFetchTime) return;
    const stale = (Date.now() - lastFetchTime) > 30000;
    $('quoteTime').classList.toggle('stale', stale);
  }, 5000);
}

/* ── Render Cards ── */
function renderCards(cards) {
  const area = $('resultArea');
  if (!cards.length) {
    area.innerHTML = '<div class="empty">目前沒有符合條件的權證</div>';
    return;
  }
  area.innerHTML = `<div class="warrant-grid">${cards.map((c, i) => renderCard(c, i)).join('')}</div>`;
}

function renderCard(c, idx) {
  const lights = renderLights(c.lights, idx);
  const hurdlePct = c.total_hurdle_pct != null ? (c.total_hurdle_pct * 100).toFixed(1) : '—';
  const bid = fmt(c.bid);
  const ask = fmt(c.ask);
  const leverage = c.effective_leverage != null ? fmt(c.effective_leverage, 1) + 'x' : '—';
  const days = c.days_to_expiry != null ? c.days_to_expiry : (c.days_to_last_trade != null ? c.days_to_last_trade : '—');
  const entryHurdle = c.entry_hurdle_pct != null ? c.entry_hurdle_pct : (c.entry_hurdle || 0);
  const slrStr = (entryHurdle * 100).toFixed(2) + '%';
  const slrClass = entryHurdle < 0.003 ? 'green' : entryHurdle < 0.008 ? 'yellow' : 'red';
  const flags = (c.flags || []).map(f => `<span class="flag-badge">${escHtml(flagLabel(f))}</span>`).join('');
  const badge = idx === 0 ? '<div class="wc-badge">最推薦</div>' : '';

  return `<div class="wc${c.highlighted ? ' wc--highlight' : ''}" id="card-${idx}">
  <div class="wc-body" onclick="toggleDetail(${idx})">
    <div class="wc-header">
      <div class="wc-header-left">
        <span class="wc-issuer">${escHtml(c.issuer || '')}</span>
        <span class="wc-code">${escHtml(c.code)}</span>
      </div>
      <div class="wc-header-right">
        ${badge}
        ${lights}
      </div>
    </div>
    <div class="wc-hurdle">
      需漲 <span class="wc-hurdle-num">${hurdlePct}%</span> 才回本
    </div>
    <div class="wc-rows">
      <div class="wc-row"><span>委買／賣</span><span>${bid} / ${ask}</span></div>
      <div class="wc-row"><span>有效槓桿</span><span class="yellow">${leverage}</span></div>
      <div class="wc-row"><span>差槓比</span><span class="${slrClass}">${slrStr}</span></div>
      <div class="wc-row"><span>剩餘天數</span><span>${days} 天</span></div>
    </div>
    <div class="wc-footer">
      <div class="wc-flags">${flags}</div>
      <button class="wc-copy" onclick="copyCode('${escHtml(c.code)}', event)">複製</button>
    </div>
  </div>
  <div id="detail-${idx}" class="card-detail">
    ${renderDetail(c)}
  </div>
</div>`;
}

function renderLights(lights, idx) {
  if (!lights) return '';
  const entries = [
    { key: 'entry',   label: '進' },
    { key: 'holding', label: '持' },
    { key: 'exit',    label: '出' },
  ];
  const colorMap = {
    green:  { bg: '#22c55e', text: '#fff' },
    yellow: { bg: '#f59e0b', text: '#fff' },
    red:    { bg: '#ef4444', text: '#fff' },
    grey:   { bg: '#3a3d52', text: '#7b82a0' },
  };
  const dots = entries.map(({ key, label }) => {
    const val = lights[key] || 'grey';
    const col = colorMap[val] || colorMap.grey;
    return `<span class="light-dot" style="background:${col.bg};color:${col.text}"
      onclick="showLightModal('${key}',${idx},event)">${label}</span>`;
  }).join('');
  return `<div class="lights">${dots}</div>`;
}

function renderDetail(c) {
  const rows = [
    ['履約價', fmt(c.strike)],
    ['行使比例', c.exercise_ratio != null ? fmt(c.exercise_ratio, 4) : '—'],
    ['隱含波動率', c.iv != null ? fmtPct(c.iv) : '—'],
    ['Delta', c.delta != null ? fmt(c.delta, 3) : '—'],
    ['Theta/日', c.theta_daily != null ? fmt(Math.abs(c.theta_daily), 4) : '—'],
    ['Vega', c.vega != null ? fmt(c.vega, 4) : '—'],
    ['進場門檻', c.entry_hurdle_pct != null ? fmtPct(c.entry_hurdle_pct) : '—'],
    ['時間門檻', c.time_hurdle_pct != null ? fmtPct(c.time_hurdle_pct) : '—'],
    ['IV門檻', c.iv_hurdle_pct != null ? fmtPct(c.iv_hurdle_pct) : '—'],
    ['到期日', c.expiry_date || c.last_trade_date || '—'],
    ['結算方式', c.settlement || '—'],
    ['發行商', c.issuer || '—'],
  ];

  const grid = rows.map(([label, val]) =>
    `<div class="detail-row"><span class="detail-label">${label}</span><span class="detail-val">${val}</span></div>`
  ).join('');

  // Cost bar
  let bar = '';
  const ep = c.entry_hurdle_pct || c.entry_hurdle || 0;
  const tp = c.time_hurdle_pct || c.time_hurdle || 0;
  const ip = c.iv_hurdle_pct || c.iv_hurdle || 0;
  const total = ep + tp + ip;
  if (total > 0) {
    const ep_w = (ep / total * 100).toFixed(1);
    const tp_w = (tp / total * 100).toFixed(1);
    const ip_w = (ip / total * 100).toFixed(1);
    bar = `<div class="cost-breakdown">
      <div style="font-size:12px;color:var(--muted);margin-bottom:4px">回本成本結構</div>
      <div class="cost-bar">
        <div class="bar-entry" style="width:${ep_w}%"></div>
        <div class="bar-time"  style="width:${tp_w}%"></div>
        <div class="bar-iv"   style="width:${ip_w}%"></div>
      </div>
      <div class="cost-legend">
        <span><span class="leg-dot" style="background:var(--yellow)"></span>進場 ${fmtPct(ep)}</span>
        <span><span class="leg-dot" style="background:var(--red)"></span>時間 ${fmtPct(tp)}</span>
        <span><span class="leg-dot" style="background:#8b5cf6"></span>IV ${fmtPct(ip)}</span>
      </div>
    </div>`;
  }

  return `<div class="detail-grid">${grid}</div>${bar}`;
}

function flagLabel(flag) {
  const map = {
    RESET: '重設型',
    CAPPED: '上限型',
    OTC: '上櫃',
    DEEP_OTM: '深度價外',
    LOW_LIQUIDITY: '低流動性',
    WIDE_SPREAD: '大價差',
    NEAR_EXPIRY: '近到期',
    HIGH_OUTSTANDING: '高流通',
    NO_IV: 'IV失效',
  };
  return map[flag] || flag;
}

/* ── Toggle Detail ── */
function toggleDetail(idx) {
  const el = $(`detail-${idx}`);
  el.classList.toggle('open');
}

/* ── Excluded Summary ── */
function renderExcluded(count, reasons) {
  if (!count) { hide($('excludedSummary')); return; }
  show($('excludedSummary'));
  $('excludedText').textContent = `▸ 已排除 ${count} 檔（點此查看原因）`;
  $('excludedSummary').onclick = () => showExcludedModal(count, reasons);
}

/* ── Copy ── */
async function copyCode(code, event) {
  event.stopPropagation();
  try {
    await navigator.clipboard.writeText(code);
  } catch {
    // fallback
    const ta = document.createElement('textarea');
    ta.value = code;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
  if (navigator.vibrate) navigator.vibrate(30);
  showToast(`已複製 ${code}`);
}

/* ── Toast ── */
function showToast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.style.opacity = '1';
  show(t);
  setTimeout(() => {
    t.style.opacity = '0';
    setTimeout(() => hide(t), 300);
  }, 1800);
}

/* ── Modal ── */
function showLightModal(key, idx, event) {
  event.stopPropagation();
  const c = currentCards[idx];
  if (!c) return;

  const defs = {
    entry: {
      title: '💰 進場成本燈號',
      desc: '衡量買入權證的點差成本（委賣 − 委買）折算成標的需漲幅度。點差愈小，燈號愈綠。',
      val: c.entry_hurdle_pct != null ? c.entry_hurdle_pct : c.entry_hurdle,
      thresholds: '綠 < 0.5% ／ 黃 < 1.5% ／ 紅 ≥ 1.5%',
    },
    holding: {
      title: '⏳ 持有成本燈號',
      desc: '持有期間的時間價值衰減（Theta × 天數）加上 IV 均值回歸損失，折算成標的需漲幅度。',
      val: ((c.time_hurdle_pct ?? c.time_hurdle ?? 0) + (c.iv_hurdle_pct ?? c.iv_hurdle ?? 0)) || null,
      thresholds: '綠 < 1% ／ 黃 < 3% ／ 紅 ≥ 3%',
    },
    exit: {
      title: '🚪 出場流動性燈號',
      desc: '出場時的委買單量（張數）。量愈大，出場愈容易。',
      val: c.bid_lots,
      unit: '張',
      thresholds: '綠 ≥ 50張 ／ 黃 ≥ 10張 ／ 紅 < 10張',
    },
  };

  const d = defs[key];
  if (!d) return;

  const valText = d.unit
    ? (d.val != null ? d.val + ' ' + d.unit : '—')
    : (d.val != null ? fmtPct(d.val) : '—');

  $('modalContent').innerHTML = `
    <h3>${d.title}</h3>
    <p>${d.desc}</p>
    <div class="detail-row" style="margin:12px 0">
      <span class="detail-label">目前數值</span>
      <span class="modal-value">${valText}</span>
    </div>
    <p style="font-size:12px">${d.thresholds}</p>`;
  show($('modal'));
}

function showExcludedModal(count, reasons) {
  const items = (reasons || []).map(r =>
    `<div style="margin:4px 0;font-size:13px">・${escHtml(r)}</div>`
  ).join('') || '（無詳細資料）';

  $('modalContent').innerHTML = `
    <h3>已排除 ${count} 檔</h3>
    <p>以下條件觸發排除：</p>
    ${items}`;
  show($('modal'));
}

function closeModal() { hide($('modal')); }

/* ── Re-ingest Contracts ── */
let _ingestPollTimer = null;

async function reingestContracts() {
  const btn = document.getElementById('btn-reingest');
  if (!btn) return;
  btn.textContent = '⏳ 更新中...';
  btn.style.pointerEvents = 'none';
  try {
    await fetch('/warrant/api/ingest/now', { method: 'POST' });
    showToast('合約更新已啟動，約 2 分鐘後完成');
    _startIngestPoll();
  } catch (e) {
    btn.textContent = '❌ 失敗';
    setTimeout(() => { btn.textContent = '🔄 更新合約'; btn.style.pointerEvents = ''; }, 3000);
  }
}

function _startIngestPoll() {
  if (_ingestPollTimer) return;
  let elapsed = 0;
  _ingestPollTimer = setInterval(async () => {
    elapsed += 5;
    try {
      const r = await fetch('/warrant/api/ingest/log');
      const d = await r.json();
      const btn = document.getElementById('btn-reingest');
      if (d.db_warrants > 0 && !d.running) {
        // 完成
        clearInterval(_ingestPollTimer); _ingestPollTimer = null;
        if (btn) { btn.textContent = `✅ ${d.db_warrants} 檔`; btn.style.pointerEvents = ''; }
        setTimeout(() => { if (btn) btn.textContent = '🔄 更新合約'; }, 4000);
        // 重新載入掃描結果
        if (!document.getElementById('scannerSection')?.classList.contains('hidden')) {
          loadScanner();
        }
      } else {
        if (btn) btn.textContent = `⏳ 更新中 ${elapsed}s`;
      }
      // 逾時 5 分鐘
      if (elapsed > 300) {
        clearInterval(_ingestPollTimer); _ingestPollTimer = null;
        if (btn) { btn.textContent = '🔄 更新合約'; btn.style.pointerEvents = ''; }
      }
    } catch(e) {}
  }, 5000);
}

/* ── Escape HTML ── */
function escHtml(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* ════ 掃描器 ════ */
let _scanMinLots   = 3000;
let _scanMinVolume = 500;
let _scanMinValue  = 0;
let _scanKind      = 'all';
let _scanData      = null;
let _scanMode      = 'after';  // 'open' | 'after'
let _scanView      = 'warrant'; // 'warrant' | 'underlying'
let _scanSortCol   = null;
let _scanSortAsc   = false;

function onScanLotChange(v) {
  _scanMinLots = parseInt(v);
  $('scanLotLabel').textContent = Number(v).toLocaleString();
  renderScanner(_scanData);
}

function onScanVolumeChange(v) {
  _scanMinVolume = parseInt(v);
  $('scanVolLabel').textContent = Number(v).toLocaleString();
  renderScanner(_scanData);
}

function onScanValueChange(v) {
  _scanMinValue = parseInt(v);
  $('scanValueLabel').textContent = v;
  renderScanner(_scanData);
}

function setScanKind(kind) {
  _scanKind = kind;
  $('scanBtnAll').classList.toggle('active',  kind === 'all');
  $('scanBtnCall').classList.toggle('active', kind === 'call');
  $('scanBtnPut').classList.toggle('active',  kind === 'put');
  renderScanner(_scanData);
}

async function loadScanner() {
  try {
    const res  = await fetch('/warrant/api/scanner?min_bid_lots=100&min_volume=100');
    const data = await res.json();
    _scanData = data;
    _scanMode = (data.mode === '盤中') ? 'open' : 'after';
    updateScanControls();
    updateScanStatus(data);
    renderScanner(data);
  } catch(e) {
    $('scannerStatus').textContent = '載入失敗：' + e.message;
  }
}

async function triggerScan() {
  const btn = $('scanRunBtn');
  btn.disabled = true;
  btn.textContent = '掃描中...';
  $('scannerStatus').textContent = '⏳ 掃描中，約需 20~40 秒...';
  try {
    await fetch('/warrant/api/scanner/run', { method: 'POST' });
  } catch(e) { /* ignore */ }

  let tries = 0;
  const poll = setInterval(async () => {
    tries++;
    try {
      const res  = await fetch('/warrant/api/scanner?min_bid_lots=100&min_volume=100');
      const data = await res.json();
      if (!data.is_scanning || tries > 60) {
        clearInterval(poll);
        btn.disabled = false;
        btn.textContent = '立刻掃描';
        _scanData = data;
        _scanMode = (data.mode === '盤中') ? 'open' : 'after';
        updateScanControls();
        updateScanStatus(data);
        renderScanner(data);
      } else {
        $('scannerStatus').textContent = `⏳ 掃描中... (${tries * 2}s)`;
      }
    } catch(e) {
      clearInterval(poll);
      btn.disabled = false;
      btn.textContent = '立刻掃描';
    }
  }, 2000);
}

function updateScanControls() {
  // 依盤中/盤外切換滑桿標籤
  const lotWrap = $('scanLotWrap');
  const volWrap = $('scanVolWrap');
  if (_scanMode === 'open') {
    if (lotWrap) lotWrap.style.display = '';
    if (volWrap) volWrap.style.display = 'none';
  } else {
    if (lotWrap) lotWrap.style.display = 'none';
    if (volWrap) volWrap.style.display = '';
  }
}

function updateScanStatus(data) {
  if (!data) return;
  const t    = data.scanned_at ? data.scanned_at.slice(11, 19) : '—';
  const cnt  = (data.results || []).length;
  const db   = data.db_warrants != null ? data.db_warrants : '?';
  const mode = data.mode || '盤外';

  // DB 空時自動開始輪詢 ingest 進度
  if (db === 0) {
    $('scannerStatus').innerHTML =
      '<span style="color:var(--yellow)">⏳ 合約資料初始化中（約 2 分鐘），請稍候…</span>';
    _startIngestPoll();
    return;
  }

  const note = data.total_scanned === 0 && db > 0
    ? '　<span style="color:var(--yellow)">⚠ 尚未掃描，請點「立刻掃描」</span>'
    : '';
  const modeTag = mode === '盤中'
    ? '<span style="color:var(--green);font-weight:700">盤中 委買量模式</span>'
    : '<span style="color:var(--yellow);font-weight:700">盤外 成交量模式</span>';
  $('scannerStatus').innerHTML =
    `${modeTag}　DB：<b>${db}</b> 檔　上次掃描：<b>${t}</b>　` +
    `共掃 <b>${data.total_scanned || 0}</b> 檔　找到 <b>${cnt}</b> 檔${note}`;
}

function sortScanner(col) {
  if (_scanSortCol === col) { _scanSortAsc = !_scanSortAsc; }
  else { _scanSortCol = col; _scanSortAsc = false; }
  renderScanner(_scanData);
}

function setScanView(v) {
  _scanView = v;
  $('scanViewBtnWarrant').classList.toggle('active',    v === 'warrant');
  $('scanViewBtnUnderlying').classList.toggle('active', v === 'underlying');
  renderScanner(_scanData);
}

async function loadScannerUnderlying() {
  const minLots = _scanMode === 'open' ? _scanMinLots : 100;
  const minVol  = _scanMinVolume;
  const res  = await fetch(`/warrant/api/scanner/underlying?min_bid_lots=${minLots}&min_volume=${minVol}`);
  return res.json();
}

function renderScanner(data) {
  if (_scanView === 'underlying') { renderScannerUnderlying(); return; }
  const tbl = $('scannerTable');
  if (!data) { tbl.innerHTML = '<div class="scan-empty">尚無資料，請點「立刻掃描」</div>'; return; }

  const isOpen = _scanMode === 'open';
  const minVal = _scanMinValue * 10000;

  const rows = (data.results || []).filter(r => {
    if (isOpen && r.bid_lots < _scanMinLots) return false;
    if (!isOpen && r.volume < _scanMinVolume) return false;
    if (minVal > 0 && r.bid_value < minVal) return false;
    if (_scanKind === 'call' && r.kind !== 'CALL') return false;
    if (_scanKind === 'put'  && r.kind !== 'PUT')  return false;
    return true;
  });

  if (!rows.length) {
    tbl.innerHTML = '<div class="scan-empty">目前沒有符合條件的權證</div>';
    return;
  }

  // 排序
  if (_scanSortCol) {
    rows.sort((a, b) => {
      const va = a[_scanSortCol] ?? 0;
      const vb = b[_scanSortCol] ?? 0;
      return _scanSortAsc ? va - vb : vb - va;
    });
  }

  const kindBadge = k => k === 'CALL'
    ? '<span class="scan-badge scan-badge--call">認購</span>'
    : '<span class="scan-badge scan-badge--put">認售</span>';

  const fmtWan = v => v >= 10000 ? (v / 10000).toFixed(1) + '萬' : v.toLocaleString();
  const fmtPrice = v => v != null ? Number(v).toFixed(2) : '—';

  const keyColHeader = isOpen ? '委買量 (張)' : '成交量 (張)';
  const keyColClass  = 'scan-th-lots';
  const keySortCol   = isOpen ? 'bid_lots' : 'volume';
  const sortArrow    = col => _scanSortCol === col ? (_scanSortAsc ? ' ↑' : ' ↓') : '';

  tbl.innerHTML = `
    <table class="scan-table">
      <thead>
        <tr>
          <th>代號</th>
          <th>標的</th>
          <th>類型</th>
          <th style="text-align:right">${isOpen ? '委買價' : '收盤價'}</th>
          <th class="${keyColClass}" style="text-align:right;cursor:pointer" onclick="sortScanner('${keySortCol}')">${keyColHeader}${sortArrow(keySortCol)}</th>
          ${isOpen ? '<th style="text-align:right">委買金額</th>' : `<th style="text-align:right;cursor:pointer" onclick="sortScanner('turnover')">成交金額${sortArrow('turnover')}</th>`}
          <th style="text-align:right;cursor:pointer" onclick="sortScanner('strike')">履約價${sortArrow('strike')}</th>
          <th>到期日</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(r => `
          <tr class="scan-row" ${r.underlying_code ? `onclick="selectUnderlying('${escHtml(r.underlying_code)}','${escHtml(r.underlying_name)}'); switchTab('warrant')"` : ''}>
            <td>
              <div class="scan-code">${escHtml(r.code)}</div>
              <div class="scan-issuer">${escHtml(r.issuer)}</div>
            </td>
            <td>
              <div class="scan-ul">${escHtml(r.underlying_name || r.underlying_code || '—')}</div>
              <div class="scan-issuer">${escHtml(r.underlying_code || '')}</div>
            </td>
            <td>${kindBadge(r.kind)}</td>
            <td class="scan-num">${isOpen ? fmtPrice(r.bid) : fmtPrice(r.price)}</td>
            <td class="scan-num scan-lots">${isOpen ? r.bid_lots.toLocaleString() : (r.volume||0).toLocaleString()}</td>
            ${isOpen ? `<td class="scan-num">${fmtWan(r.bid_value)}</td>` : `<td class="scan-num">${fmtWan(r.turnover || 0)}</td>`}
            <td class="scan-num">${r.strike != null ? r.strike : '—'}</td>
            <td class="scan-date">${(r.expiry_date || '').slice(2)}</td>
            <td><button class="wc-copy" onclick="copyCode('${escHtml(r.code)}',event)">複製</button></td>
          </tr>`).join('')}
      </tbody>
    </table>
    <div class="scan-count">${rows.length} 筆</div>`;
}

async function renderScannerUnderlying() {
  const tbl = $('scannerTable');
  tbl.innerHTML = '<div class="scan-empty">載入中...</div>';
  try {
    const data = await loadScannerUnderlying();
    const rows = (data.results || []).filter(r => {
      if (_scanKind === 'call' && r.call_vol === 0) return false;
      if (_scanKind === 'put'  && r.put_vol  === 0) return false;
      return true;
    });
    if (!rows.length) {
      tbl.innerHTML = '<div class="scan-empty">目前沒有資料，請先掃描</div>';
      return;
    }
    const isOpen   = _scanMode === 'open';
    const volLabel = isOpen ? '委買量' : '成交量';
    const maxVol   = rows[0]?.total_vol || 1;

    const barPct = v => Math.max(2, Math.round(v / maxVol * 100));
    const fmtK   = v => v >= 1000 ? (v / 1000).toFixed(1) + 'k' : String(v);

    tbl.innerHTML = `
      <table class="scan-table">
        <thead>
          <tr>
            <th>標的</th>
            <th style="text-align:center">認購 ${volLabel}</th>
            <th style="text-align:center">認售 ${volLabel}</th>
            <th style="text-align:center">偏向</th>
            <th>代表權證</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(r => {
            const total   = r.total_vol;
            const callPct = total > 0 ? r.call_vol / total : 0;
            const biasLbl = r.bias > total * 0.3
              ? '<span style="color:var(--green);font-weight:700">偏多 ▲</span>'
              : r.bias < -total * 0.3
                ? '<span style="color:var(--red);font-weight:700">偏空 ▼</span>'
                : '<span style="color:var(--text-dim)">中性 —</span>';
            const topCallStr = r.top_call.map(w =>
              `<span class="scan-badge scan-badge--call" style="cursor:pointer" onclick="switchTab('warrant');copyCode('${escHtml(w.code)}')">${escHtml(w.code)}<small> ${fmtK(w.vol)}</small></span>`
            ).join(' ');
            const topPutStr  = r.top_put.map(w =>
              `<span class="scan-badge scan-badge--put" style="cursor:pointer" onclick="switchTab('warrant');copyCode('${escHtml(w.code)}')">${escHtml(w.code)}<small> ${fmtK(w.vol)}</small></span>`
            ).join(' ');
            return `<tr class="scan-row" onclick="selectUnderlying('${escHtml(r.underlying_code)}','${escHtml(r.underlying_name)}'); switchTab('warrant')">
              <td>
                <div class="scan-ul">${escHtml(r.underlying_name || r.underlying_code)}</div>
                <div class="scan-issuer">${escHtml(r.underlying_code)}</div>
              </td>
              <td class="scan-num">
                <div style="color:var(--green)">${r.call_vol.toLocaleString()}</div>
                <div class="scan-mini-bar" style="background:var(--green);opacity:.7;width:${barPct(r.call_vol)}%;height:3px;border-radius:2px"></div>
              </td>
              <td class="scan-num">
                <div style="color:var(--red)">${r.put_vol.toLocaleString()}</div>
                <div class="scan-mini-bar" style="background:var(--red);opacity:.7;width:${barPct(r.put_vol)}%;height:3px;border-radius:2px"></div>
              </td>
              <td style="text-align:center">${biasLbl}</td>
              <td style="font-size:.7rem;line-height:1.6">${topCallStr}${topPutStr || ''}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
      <div class="scan-count">${rows.length} 檔標的</div>`;
  } catch(e) {
    tbl.innerHTML = `<div class="scan-empty">載入失敗：${e.message}</div>`;
  }
}
