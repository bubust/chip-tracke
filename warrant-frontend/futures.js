/* ── 個股期貨小幫手 ── */

let _futData    = null;
let _futDir     = 'long';
let _futStockId = null;

/* ── Tab 切換 ── */
function switchTab(tab) {
  const isWarrant = tab === 'warrant';
  document.getElementById('tabWarrant').classList.toggle('active', isWarrant);
  document.getElementById('tabFutures').classList.toggle('active', !isWarrant);
  document.getElementById('warrantSection').classList.toggle('hidden', !isWarrant);
  document.getElementById('futuresSection').classList.toggle('hidden', isWarrant);
  if (!isWarrant && _futStockId) loadFutures(_futStockId);
}

/* ── 方向切換 ── */
function setFutDir(dir) {
  _futDir = dir;
  document.getElementById('futBtnLong').classList.toggle('active', dir === 'long');
  document.getElementById('futBtnShort').classList.toggle('active', dir === 'short');
  if (_futData) renderFutGrid(_futData);
}

/* ── 由 app.js selectUnderlying 觸發 ── */
function onFuturesStockSelected(code) {
  _futStockId = code;
  if (!document.getElementById('futuresSection').classList.contains('hidden')) {
    loadFutures(code);
  }
}

/* ── 主查詢 ── */
async function loadFutures(stockId) {
  const content = document.getElementById('futuresContent');
  content.innerHTML = '<div class="fut-loading">載入中…</div>';
  try {
    const res  = await fetch(`/warrant/api/futures/${encodeURIComponent(stockId)}`);
    const data = await res.json();
    if (!res.ok) {
      content.innerHTML = `<div class="fut-placeholder"><div class="fut-placeholder-icon">❌</div><div>${data.detail || '查詢失敗'}</div></div>`;
      return;
    }
    _futData = data;
    renderFutGrid(data);
  } catch (e) {
    content.innerHTML = `<div class="fut-placeholder"><div class="fut-placeholder-icon">❌</div><div>網路錯誤：${e.message}</div></div>`;
  }
}

/* ── 渲染 2×2 grid ── */
function renderFutGrid(data) {
  const content = document.getElementById('futuresContent');
  const hasStd  = data.standard_near || data.standard_far;
  const hasMini = data.mini_near || data.mini_far;

  if (!hasStd && !hasMini) {
    content.innerHTML = `
      <div class="fut-placeholder">
        <div class="fut-placeholder-icon">🔍</div>
        <div>找不到個股期合約</div>
        <div style="font-size:12px;color:var(--muted);margin-top:4px">此股票可能無個股期貨</div>
      </div>`;
    return;
  }

  const fmtN = (v, d = 0) => v == null ? '—'
    : Number(v).toLocaleString('zh-TW', { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmtM = v => v ? `${fmtN(v)} 元` : '—';

  function buildCard(c, nearFar, typeLabel) {
    if (!c) return `
      <div class="fut-grid-card fut-grid-card--empty">
        <div class="fgc-pills">
          <span class="fgc-pill-type">${typeLabel}</span>
          <span class="${nearFar === '近月' ? 'fgc-pill-near' : 'fgc-pill-far'}">${nearFar}</span>
        </div>
        <div class="fgc-empty-msg">無合約</div>
      </div>`;

    const chgSign  = (c.change != null && c.change >= 0) ? '+' : '';
    const chgCls   = c.change != null ? (c.change >= 0 ? 'green' : 'red') : '';
    const basisCls = c.basis != null ? (c.basis >= 0 ? 'red' : 'green') : '';
    const basisSign= c.basis != null ? (c.basis >= 0 ? '+' : '') : '';
    const basisStr = c.basis != null
      ? `${basisSign}${c.basis}（${basisSign}${c.basis_pct}%）`
      : '—';
    const urgent   = c.days_to_expiry != null && c.days_to_expiry <= 10;

    return `
    <div class="fut-grid-card">
      <div class="fgc-top">
        <div class="fgc-pills">
          <span class="fgc-pill-type">${typeLabel}</span>
          <span class="${nearFar === '近月' ? 'fgc-pill-near' : 'fgc-pill-far'}">${nearFar}</span>
        </div>
        <div class="fgc-expiry-wrap">
          <span class="fgc-expiry">${c.expiry_label}</span>
          <span class="fgc-days-tag${urgent ? ' urgent' : ''}">剩 ${c.days_to_expiry} 天</span>
        </div>
      </div>
      <div class="fgc-code">${c.product_code}</div>
      <div class="fgc-price-row">
        <span class="fgc-price">${c.price != null ? c.price.toFixed(2) : '—'}</span>
        ${c.change != null
          ? `<span class="fgc-change ${chgCls}">${chgSign}${c.change}（${c.change_pct}）</span>`
          : ''}
      </div>
      <div class="fgc-metric-grid">
        <div class="fgc-m">
          <span>每口市值</span><span>${fmtM(c.contract_value)}</span>
        </div>
        <div class="fgc-m fgc-m--lev">
          <span>有效槓桿</span><span>${c.leverage != null ? c.leverage + 'x' : '—'}</span>
        </div>
        <div class="fgc-m">
          <span>原始保證金</span><span>${fmtM(c.original_margin)}</span>
        </div>
        <div class="fgc-m">
          <span>維持保證金</span><span>${fmtM(c.maintenance_margin)}</span>
        </div>
      </div>
      <div class="fgc-bottom-row">
        <span class="fgc-basis ${basisCls}">基差 ${basisStr}</span>
        <span class="fgc-vol-oi">量 ${fmtN(c.volume)} 口<br>OI ${fmtN(c.open_interest)} 口</span>
      </div>
    </div>`;
  }

  // 本金試算
  const calcHtml = (hasStd || hasMini) ? `
    <div class="fgc-calc">
      <div class="fgc-calc-title">💰 本金試算</div>
      <div class="fgc-calc-row">
        <label>本金</label>
        <input id="futCapInput" class="fgc-calc-input" type="number" min="0" step="10000"
               placeholder="輸入本金（元）" oninput="calcFutPnl()" value="${document.getElementById('futCapInput')?.value || ''}">
        <span class="fgc-calc-unit">元</span>
      </div>
      <div id="futCalcResult" class="fgc-calc-results"></div>
    </div>` : '';

  // 組合 grid：有小型才顯示第二列
  content.innerHTML = `
    <div class="fut-grid-wrap">
      ${hasStd ? `
      <div class="fut-grid-section-label">標準（2000股/口）</div>
      <div class="fut-grid">
        ${buildCard(data.standard_near, '近月', '標準')}
        ${buildCard(data.standard_far,  '遠月', '標準')}
      </div>` : ''}
      ${hasMini ? `
      <div class="fut-grid-section-label">小型（200股/口）</div>
      <div class="fut-grid">
        ${buildCard(data.mini_near, '近月', '小型')}
        ${buildCard(data.mini_far,  '遠月', '小型')}
      </div>` : ''}
      ${calcHtml}
    </div>`;

  // 還原本金試算
  setTimeout(calcFutPnl, 0);
}

/* ── 本金試算 ── */
function calcFutPnl() {
  if (!_futData) return;
  const capital = parseInt(document.getElementById('futCapInput')?.value || '0');
  const resultEl = document.getElementById('futCalcResult');
  if (!resultEl) return;
  if (!capital) { resultEl.innerHTML = ''; return; }

  const sign = _futDir === 'long' ? 1 : -1;

  function calcLine(c, label) {
    if (!c || !c.original_margin) return '';
    const lots    = Math.floor(capital / c.original_margin);
    const used    = lots * c.original_margin;
    const left    = capital - used;
    const pnl1    = lots * (c.pnl_per_lot_1pct || 0);
    const fmtN    = v => Math.abs(v).toLocaleString('zh-TW');
    const fmtPnl  = v => {
      const cls = v >= 0 ? 'green' : 'red';
      return `<span class="${cls}">${v >= 0 ? '+' : '-'}${fmtN(v)}</span>`;
    };
    return `
      <div class="fgc-calc-line">
        <span class="fgc-calc-lbl">${label}</span>
        <span>${lots} 口・佔用 ${fmtN(used)} 元・剩餘 ${fmtN(left)} 元</span>
      </div>
      <div class="fgc-calc-pnl">
        <span>漲1%：${fmtPnl(sign * pnl1)}</span>
        <span>漲3%：${fmtPnl(sign * pnl1 * 3)}</span>
        <span>跌1%：${fmtPnl(-sign * pnl1)}</span>
        <span>跌3%：${fmtPnl(-sign * pnl1 * 3)}</span>
      </div>`;
  }

  resultEl.innerHTML = [
    calcLine(_futData.standard_near, '近月標準'),
    calcLine(_futData.standard_far,  '遠月標準'),
    calcLine(_futData.mini_near,     '近月小型'),
    calcLine(_futData.mini_far,      '遠月小型'),
  ].filter(Boolean).join('<div class="fgc-calc-sep"></div>');
}
