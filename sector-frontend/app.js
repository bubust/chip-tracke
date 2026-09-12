/**
 * app.js — 台股產業輪動引擎 V1 前端
 */

const BASE = "";  // 同源

// ── 狀態 ────────────────────────────────────────────────────────────────────
let _sectors = [];       // 當前表格資料
let _sortKey = "relative_rank_5d";
let _sortAsc = true;
let _currentTab = "rank";  // rank | change | event | events-list
let _statusTimer = null;

// ── 初始化 ──────────────────────────────────────────────────────────────────

async function init() {
  await loadStatus();
  await loadSectors(_currentTab);
  // 每 30s 自動刷狀態
  _statusTimer = setInterval(loadStatus, 30000);
}

// ── 狀態列 ──────────────────────────────────────────────────────────────────

async function loadStatus() {
  try {
    const r = await fetch(`${BASE}/sector/api/status`);
    const d = await r.json();

    document.getElementById("stat-sectors").textContent = d.sector_count ?? "—";
    document.getElementById("stat-stocks").textContent = d.stock_count ?? "—";
    document.getElementById("stat-date").textContent = formatDate(d.latest_date) || "尚無資料";

    const dot = document.getElementById("status-dot");
    const runTxt = document.getElementById("engine-running-txt");
    if (d.engine_running) {
      dot.className = "status-dot running";
      runTxt.style.display = "";
    } else {
      dot.className = d.initialized ? "status-dot ok" : "status-dot";
      runTxt.style.display = "none";
    }

    // 若未初始化，顯示提示
    if (!d.initialized) {
      showEmpty("尚未初始化", "請點擊右上角「初始化」按鈕，從 FinMind 建立產業對照表");
    }
  } catch (e) {
    console.error("loadStatus:", e);
  }
}

// ── 排序 Tab ────────────────────────────────────────────────────────────────

function switchSortTab(tab, el) {
  _currentTab = tab;
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  el.classList.add("active");

  if (tab === "events-list") {
    document.getElementById("sectors-panel").style.display = "none";
    document.getElementById("detail-panel").style.display = "none";
    document.getElementById("events-panel").style.display = "";
    loadEvents();
  } else {
    document.getElementById("events-panel").style.display = "none";
    document.getElementById("detail-panel").style.display = "none";
    document.getElementById("sectors-panel").style.display = "";
    loadSectors(tab);
  }
}

// ── 載入產業列表 ─────────────────────────────────────────────────────────────

async function loadSectors(tab) {
  const sortByMap = {
    rank: "rank5d",
    change: "rank_change",
    event: "event",
  };
  const sortBy = sortByMap[tab] || "rank5d";

  showLoading(true);
  try {
    const r = await fetch(`${BASE}/sector/api/sectors?sort_by=${sortBy}`);
    const d = await r.json();
    _sectors = d.sectors || [];
    renderTable(_sectors);
  } catch (e) {
    showToast("載入失敗：" + e.message, "err");
  } finally {
    showLoading(false);
  }
}

// ── 表格渲染 ─────────────────────────────────────────────────────────────────

function renderTable(sectors) {
  if (!sectors || sectors.length === 0) {
    showEmpty("尚無資料", "請先初始化並執行計算");
    return;
  }

  document.getElementById("sectors-panel").style.display = "";
  document.getElementById("loading-indicator").style.display = "none";

  const tbody = document.getElementById("sectors-tbody");
  tbody.innerHTML = "";

  sectors.forEach((s, i) => {
    const tr = document.createElement("tr");
    tr.id = `row-${i}`;
    tr.innerHTML = buildSectorRow(s, i);
    tbody.appendChild(tr);

    // 展開列（預設隱藏）
    const expandTr = document.createElement("tr");
    expandTr.id = `expand-${i}`;
    expandTr.className = "expand-row";
    expandTr.style.display = "none";
    expandTr.innerHTML = `<td colspan="12"><div class="expand-inner" id="expand-inner-${i}"></div></td>`;
    tbody.appendChild(expandTr);
  });
}

function buildSectorRow(s, i) {
  const name = s.sector_name || s.sector_id;
  const trend = s.trend_state || "—";
  const trendBadge = trendBadgeHtml(trend);

  const rank5 = rankHtml(s.relative_rank_5d, _sectors.length);
  const rank20 = rankHtml(s.relative_rank_20d, _sectors.length);
  const rank60 = rankHtml(s.relative_rank_60d, _sectors.length);

  const rankTrend = rankTrendHtml(s.rank_trend, s.rank_change_5d);
  const ret5 = retHtml(s.return_ew_5d);
  const ret20 = retHtml(s.return_ew_20d);

  const evBadge = s.structure_event ? eventBadgeHtml(s.structure_event) : '<span style="color:var(--muted)">—</span>';
  const healthBadge = healthBadgeHtml(s.internal_health);
  const regimeBadge = s.sector_regime
    ? `<span class="regime-chip regime-${s.sector_regime}">${s.sector_regime}</span>`
    : '<span style="color:var(--muted)">—</span>';

  return `
    <td style="font-weight:600;cursor:pointer" onclick="toggleDetail(${i}, '${escHtml(s.sector_id)}')">${name}</td>
    <td>${trendBadge}</td>
    <td>${rank5}</td>
    <td>${rank20}</td>
    <td>${rank60}</td>
    <td>${rankTrend}</td>
    <td>${ret5}</td>
    <td>${ret20}</td>
    <td>${evBadge}</td>
    <td>${healthBadge}</td>
    <td>${regimeBadge}</td>
    <td><button class="btn" style="padding:3px 8px;font-size:.75rem" onclick="openDetail('${escHtml(s.sector_id)}')">詳細</button></td>
  `;
}

// ── 行內展開 ────────────────────────────────────────────────────────────────

async function toggleDetail(i, sectorId) {
  const expandTr = document.getElementById(`expand-${i}`);
  const mainTr = document.getElementById(`row-${i}`);
  if (expandTr.style.display === "none") {
    expandTr.style.display = "";
    mainTr.classList.add("expanded");
    const inner = document.getElementById(`expand-inner-${i}`);
    inner.innerHTML = '<div class="loading"><div class="spinner"></div> 載入中...</div>';
    try {
      const r = await fetch(`${BASE}/sector/api/sector/${encodeURIComponent(sectorId)}?days=30`);
      const d = await r.json();
      inner.innerHTML = buildExpandContent(d.latest, d.stocks);
    } catch (e) {
      inner.innerHTML = '<span style="color:var(--red)">載入失敗</span>';
    }
  } else {
    expandTr.style.display = "none";
    mainTr.classList.remove("expanded");
  }
}

function buildExpandContent(latest, stocks) {
  if (!latest) return "無資料";

  const items = [
    ["指數水位", latest.index_level?.toFixed(2)],
    ["MA20", latest.ma20?.toFixed(2)],
    ["MA60", latest.ma60?.toFixed(2)],
    ["MA120", latest.ma120?.toFixed(2)],
    ["MA60 斜率", latest.ma60_slope !== null ? (latest.ma60_slope * 100).toFixed(3) + "%" : "—"],
    ["1D 報酬", pctFmt(latest.return_ew_1d)],
    ["5D 報酬", pctFmt(latest.return_ew_5d)],
    ["20D 報酬", pctFmt(latest.return_ew_20d)],
    ["60D 報酬", pctFmt(latest.return_ew_60d)],
    ["中位數 1D", pctFmt(latest.return_median_1d)],
    ["漲跌比", latest.breadth_up_ratio !== null ? (latest.breadth_up_ratio * 100).toFixed(1) + "%" : "—"],
    ["站上MA20", latest.above_ma20_ratio !== null ? (latest.above_ma20_ratio * 100).toFixed(1) + "%" : "—"],
    ["站上MA60", latest.above_ma60_ratio !== null ? (latest.above_ma60_ratio * 100).toFixed(1) + "%" : "—"],
    ["量能偏多比", latest.up_volume_ratio !== null ? (latest.up_volume_ratio * 100).toFixed(1) + "%" : "—"],
    ["Top3 貢獻", latest.top3_contribution !== null ? (latest.top3_contribution * 100).toFixed(1) + "%" : "—"],
    ["Swing High", latest.swing_high?.toFixed(2) + (latest.swing_high_date ? ` (${formatDate(latest.swing_high_date)})` : "") || "—"],
    ["Swing Low",  latest.swing_low?.toFixed(2)  + (latest.swing_low_date  ? ` (${formatDate(latest.swing_low_date)})` : "")  || "—"],
    ["市場相對 5D", latest.market_relative_5d !== null ? pctFmt(latest.market_relative_5d) : "—"],
    ["轉換狀態", latest.transition_state || "None"],
    ["股票數", latest.stock_count],
  ];

  const gridItems = items.map(([label, val]) =>
    `<div class="detail-item"><span class="detail-label">${label}</span><span class="detail-value">${val ?? "—"}</span></div>`
  ).join("");

  const stockList = (stocks || []).slice(0, 20).join("、");
  const moreStocks = (stocks || []).length > 20 ? ` 等 ${(stocks || []).length} 支` : "";

  return `
    <div class="expand-section">
      <h4>詳細指標</h4>
      <div class="detail-grid">${gridItems}</div>
    </div>
    <div class="expand-section" style="flex:1;min-width:200px">
      <h4>成份股（${(stocks || []).length} 支）</h4>
      <div style="color:var(--muted);font-size:.78rem;line-height:1.7">${stockList}${moreStocks}</div>
    </div>
  `;
}

// ── 產業詳細頁 ────────────────────────────────────────────────────────────────

async function openDetail(sectorId) {
  document.getElementById("sectors-panel").style.display = "none";
  document.getElementById("events-panel").style.display = "none";
  const detailPanel = document.getElementById("detail-panel");
  detailPanel.style.display = "";
  document.getElementById("detail-content").innerHTML = '<div class="loading"><div class="spinner"></div> 載入中...</div>';

  try {
    const r = await fetch(`${BASE}/sector/api/sector/${encodeURIComponent(sectorId)}?days=60`);
    const d = await r.json();
    renderDetailPage(d);
  } catch (e) {
    document.getElementById("detail-content").innerHTML = `<div style="color:var(--red)">載入失敗：${e.message}</div>`;
  }
}

function renderDetailPage(d) {
  const s = d.latest || {};
  const name = s.sector_name || s.sector_id || sectorId;

  const metrics = [
    { label: "趨勢狀態", value: trendBadgeHtml(s.trend_state) },
    { label: "5D 排名", value: rankHtml(s.relative_rank_5d, null) },
    { label: "20D 排名", value: rankHtml(s.relative_rank_20d, null) },
    { label: "排名趨勢", value: rankTrendHtml(s.rank_trend, s.rank_change_5d) },
    { label: "5D 報酬", value: `<span class="${retClass(s.return_ew_5d)}">${pctFmt(s.return_ew_5d)}</span>` },
    { label: "20D 報酬", value: `<span class="${retClass(s.return_ew_20d)}">${pctFmt(s.return_ew_20d)}</span>` },
    { label: "60D 報酬", value: `<span class="${retClass(s.return_ew_60d)}">${pctFmt(s.return_ew_60d)}</span>` },
    { label: "指數水位", value: s.index_level?.toFixed(2) ?? "—" },
    { label: "健康度", value: healthBadgeHtml(s.internal_health) },
    { label: "漲跌比", value: s.breadth_up_ratio !== null && s.breadth_up_ratio !== undefined ? `<div class="health-bar-wrap"><div class="health-bar"><div class="health-bar-fill" style="width:${(s.breadth_up_ratio*100).toFixed(0)}%;background:${s.breadth_up_ratio>=0.5?'var(--green)':'var(--red)'}"></div></div>${(s.breadth_up_ratio*100).toFixed(1)}%</div>` : "—" },
    { label: "站上MA20", value: s.above_ma20_ratio !== null && s.above_ma20_ratio !== undefined ? `${(s.above_ma20_ratio*100).toFixed(1)}%` : "—" },
    { label: "結構事件", value: s.structure_event ? eventBadgeHtml(s.structure_event) : "—" },
  ];

  const metricCards = metrics.map(m =>
    `<div class="metric-card"><div class="metric-label">${m.label}</div><div class="metric-value">${m.value}</div></div>`
  ).join("");

  // 歷史事件
  const events = (d.events || []).map(ev =>
    `<div class="event-card">
      <span class="event-date">${formatDate(ev.observation_date)}</span>
      ${eventBadgeHtml(ev.event_type)}
      <span class="event-detail">參考價 ${ev.reference_price?.toFixed(2) ?? "—"} | 事件價 ${ev.event_price?.toFixed(2) ?? "—"}</span>
      <span style="color:var(--muted);font-size:.75rem">${ev.confirmation_status}</span>
    </div>`
  ).join("") || '<div style="color:var(--muted);font-size:.85rem">無近期事件</div>';

  // 歷史資料表格
  const historyRows = (d.history || []).slice(-20).reverse().map(h =>
    `<tr>
      <td>${formatDate(h.observation_date)}</td>
      <td>${h.index_level?.toFixed(2) ?? "—"}</td>
      <td class="${retClass(h.return_ew_1d)}">${pctFmt(h.return_ew_1d)}</td>
      <td class="${retClass(h.return_ew_5d)}">${pctFmt(h.return_ew_5d)}</td>
      <td>${h.ma20?.toFixed(2) ?? "—"}</td>
      <td>${h.ma60?.toFixed(2) ?? "—"}</td>
      <td>${trendBadgeHtml(h.trend_state)}</td>
      <td>${h.relative_rank_5d ?? "—"}</td>
    </tr>`
  ).join("");

  document.getElementById("detail-content").innerHTML = `
    <div class="detail-header">
      <h2>${name}</h2>
      <div class="meta">觀察日：${formatDate(s.observation_date)} | 股票數：${s.stock_count ?? "—"} | ${s.sector_regime ? `<span class="regime-chip regime-${s.sector_regime}">${s.sector_regime}</span>` : ""}</div>
    </div>

    <div class="metrics-grid">${metricCards}</div>

    <div style="margin-bottom:20px">
      <h4 style="color:var(--muted);margin-bottom:10px;font-size:.85rem">近期結構事件</h4>
      <div class="event-list">${events}</div>
    </div>

    <div>
      <h4 style="color:var(--muted);margin-bottom:10px;font-size:.85rem">歷史資料（最近 20 天）</h4>
      <div class="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>日期</th><th>指數</th><th>1D%</th><th>5D%</th>
              <th>MA20</th><th>MA60</th><th>趨勢</th><th>5D#</th>
            </tr>
          </thead>
          <tbody>${historyRows}</tbody>
        </table>
      </div>
    </div>
  `;
}

function backToList() {
  document.getElementById("detail-panel").style.display = "none";
  if (_currentTab === "events-list") {
    document.getElementById("events-panel").style.display = "";
  } else {
    document.getElementById("sectors-panel").style.display = "";
  }
}

// ── 事件記錄 ────────────────────────────────────────────────────────────────

async function loadEvents() {
  const container = document.getElementById("events-list-container");
  container.innerHTML = '<div class="loading"><div class="spinner"></div> 載入中...</div>';
  try {
    const r = await fetch(`${BASE}/sector/api/events?limit=50`);
    const d = await r.json();
    const events = d.events || [];
    if (events.length === 0) {
      container.innerHTML = '<div class="empty-state"><h3>尚無事件記錄</h3><p>請先執行計算</p></div>';
      return;
    }
    container.innerHTML = events.map(ev =>
      `<div class="event-card">
        <span class="event-date">${formatDate(ev.observation_date)}</span>
        <span class="event-sector">${ev.sector_name || ev.sector_id}</span>
        ${eventBadgeHtml(ev.event_type)}
        <span class="event-detail">參考價 <b>${ev.reference_price?.toFixed(2) ?? "—"}</b> | 事件價 <b>${ev.event_price?.toFixed(2) ?? "—"}</b></span>
        <span style="color:var(--muted);font-size:.75rem">${ev.confirmation_status}</span>
      </div>`
    ).join("");
  } catch (e) {
    container.innerHTML = `<div style="color:var(--red)">載入失敗：${e.message}</div>`;
  }
}

// ── 排序 ────────────────────────────────────────────────────────────────────

let _lastSortKey = null;
let _lastSortAsc = true;

function sortTable(key) {
  if (_lastSortKey === key) {
    _lastSortAsc = !_lastSortAsc;
  } else {
    _lastSortKey = key;
    _lastSortAsc = key.startsWith("return") ? false : true;
  }

  const sorted = [..._sectors].sort((a, b) => {
    let va = a[key], vb = b[key];
    if (va === null || va === undefined) return 1;
    if (vb === null || vb === undefined) return -1;
    if (typeof va === "number") return _lastSortAsc ? va - vb : vb - va;
    return _lastSortAsc
      ? String(va).localeCompare(String(vb))
      : String(vb).localeCompare(String(va));
  });

  // 更新表頭箭頭
  document.querySelectorAll("th").forEach(th => th.classList.remove("sorted"));
  renderTable(sorted);
}

// ── Actions ──────────────────────────────────────────────────────────────────

async function triggerRefresh() {
  const btn = document.getElementById("btn-refresh");
  btn.disabled = true;
  btn.textContent = "計算中...";
  try {
    const r = await fetch(`${BASE}/sector/api/refresh?days_back=120`, { method: "POST" });
    const d = await r.json();
    if (d.ok) {
      showToast("引擎已開始計算（約需 3~10 分鐘）", "ok");
      // 每 10s 輪詢狀態，完成後自動刷新
      const poll = setInterval(async () => {
        const st = await fetch(`${BASE}/sector/api/status`).then(r => r.json()).catch(() => null);
        if (st && !st.engine_running) {
          clearInterval(poll);
          btn.disabled = false;
          btn.textContent = "🔄 更新計算";
          await loadStatus();
          await loadSectors(_currentTab);
          showToast("計算完成！", "ok");
        }
      }, 10000);
    } else {
      showToast(d.message || "啟動失敗", "err");
      btn.disabled = false;
      btn.textContent = "🔄 更新計算";
    }
  } catch (e) {
    showToast("請求失敗：" + e.message, "err");
    btn.disabled = false;
    btn.textContent = "🔄 更新計算";
  }
}

async function triggerInit() {
  if (!confirm("確定要從 FinMind 重新建立產業對照表？（需要有效的 FINMIND_TOKEN）")) return;
  const btn = document.getElementById("btn-init");
  btn.disabled = true;
  try {
    const r = await fetch(`${BASE}/sector/api/init`, { method: "POST" });
    const d = await r.json();
    showToast(d.message || "初始化已開始", "ok");
    setTimeout(loadStatus, 5000);
  } catch (e) {
    showToast("請求失敗：" + e.message, "err");
  } finally {
    btn.disabled = false;
  }
}

// ── UI helpers ────────────────────────────────────────────────────────────────

function trendBadgeHtml(trend) {
  const map = { BULL: ["badge-bull", "多頭"], BEAR: ["badge-bear", "空頭"], RANGE: ["badge-range", "盤整"] };
  const [cls, label] = map[trend] || ["badge-stable", trend || "—"];
  return `<span class="badge ${cls}">${label}</span>`;
}

function rankHtml(rank, total) {
  if (rank === null || rank === undefined) return '<span style="color:var(--muted)">—</span>';
  let cls = "rank-num";
  if (total && rank <= Math.ceil(total * 0.15)) cls += " rank-top3";
  else if (total && rank >= Math.ceil(total * 0.85)) cls += " rank-bot3";
  return `<span class="${cls}">${rank}</span>`;
}

function rankTrendHtml(trend, change) {
  const changeStr = change !== null && change !== undefined
    ? ` (${change > 0 ? "+" : ""}${change})`
    : "";
  if (trend === "STRENGTHENING") return `<span class="badge badge-strong arrow-up">↑↑ 強化${changeStr}</span>`;
  if (trend === "WEAKENING")     return `<span class="badge badge-weak arrow-down">↓↓ 弱化${changeStr}</span>`;
  return `<span class="badge badge-stable">→ 穩定${changeStr}</span>`;
}

function eventBadgeHtml(event) {
  const labels = {
    BREAKOUT:        "突破",
    BREAKDOWN:       "跌破",
    FALSE_BREAKDOWN: "假跌破",
    FALSE_BREAKOUT:  "假突破",
    RECLAIM:         "收復",
  };
  const label = labels[event] || event;
  return `<span class="badge-event badge-event-${event}">${label}</span>`;
}

function healthBadgeHtml(health) {
  const map = {
    HEALTHY:      ["badge-strong", "健康"],
    CONCENTRATED: ["badge-range",  "集中"],
    WEAK:         ["badge-weak",   "弱勢"],
    IMPROVING:    ["badge-strong", "改善"],
    DETERIORATING:["badge-weak",  "惡化"],
    STABLE:       ["badge-stable", "穩定"],
  };
  const [cls, label] = map[health] || ["badge-stable", health || "—"];
  return `<span class="badge ${cls}">${label}</span>`;
}

function retClass(val) {
  if (val === null || val === undefined) return "ret-neu";
  return val > 0 ? "ret-pos" : val < 0 ? "ret-neg" : "ret-neu";
}

function retHtml(val) {
  if (val === null || val === undefined) return '<span class="ret-neu">—</span>';
  const pct = (val * 100).toFixed(2);
  const sign = val > 0 ? "+" : "";
  return `<span class="${retClass(val)}">${sign}${pct}%</span>`;
}

function pctFmt(val) {
  if (val === null || val === undefined) return "—";
  const pct = (val * 100).toFixed(2);
  const sign = val > 0 ? "+" : "";
  return `${sign}${pct}%`;
}

function formatDate(d) {
  if (!d) return "—";
  const s = String(d);
  if (s.length === 8) return `${s.slice(0, 4)}/${s.slice(4, 6)}/${s.slice(6, 8)}`;
  if (s.includes("T")) return s.slice(0, 10);
  return s;
}

function escHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[c]));
}

function showLoading(show) {
  const el = document.getElementById("loading-indicator");
  if (show) {
    el.style.display = "";
    document.getElementById("sectors-panel").style.display = "none";
  } else {
    el.style.display = "none";
  }
}

function showEmpty(title, msg) {
  document.getElementById("loading-indicator").style.display = "none";
  document.getElementById("sectors-panel").style.display = "";
  document.getElementById("sectors-tbody").innerHTML =
    `<tr><td colspan="12">
      <div class="empty-state">
        <h3>${title}</h3>
        <p style="margin-top:6px;font-size:.85rem">${msg}</p>
      </div>
    </td></tr>`;
}

function showToast(msg, type = "ok") {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = `toast show ${type}`;
  setTimeout(() => { t.className = "toast"; }, 3000);
}

// ── 啟動 ────────────────────────────────────────────────────────────────────
init();
