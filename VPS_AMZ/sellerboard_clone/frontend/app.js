// SellerVision SPA - gọi REST API của FastAPI backend (kiến trúc Headless).
// Mặc định cùng origin (tự khớp domain khi backend phục vụ luôn frontend).
// Nếu tách frontend/back-end khác domain: đặt window.SV_API_BASE trước khi load app.js.
const API = (window.SV_API_BASE || location.origin).replace(/\/$/, '');
let TOKEN = localStorage.getItem('sv_token') || null;
let salesChart = null, marketChart = null;

const $ = (id) => document.getElementById(id);
const fmtMoney = (n) => '$' + Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 2 });
const fmtNum = (n) => Number(n || 0).toLocaleString('vi-VN');
const fmtPct = (v) => (v === null || v === undefined) ? '·' : v + '%';

// Spinner: đếm số request đang chạy để khi chồng nhiều request không tắt sớm.
let _pending = 0;
function _loading(on) {
  _pending = Math.max(0, _pending + (on ? 1 : -1));
  const el = $('sv-loading');
  if (el) el.classList.toggle('hidden', _pending === 0);
}

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (TOKEN) headers['Authorization'] = 'Bearer ' + TOKEN;
  if (opts.json) { headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(opts.json); delete opts.json; }
  _loading(true);                                  // BẬT spinner
  try {
    const res = await fetch(API + path, { ...opts, headers });
    if (res.status === 401) { App.logout(); throw new Error('401'); }
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    return res.status === 204 ? null : res.json();
  } finally {
    _loading(false);                               // TẮT spinner (kể cả khi lỗi)
  }
}

const App = {
  // ---------- Auth ----------
  async login() {
    const body = new URLSearchParams();
    body.append('username', $('login-email').value);
    body.append('password', $('login-password').value);
    try {
      const data = await api('/api/auth/login', { method: 'POST', body });
      TOKEN = data.access_token; localStorage.setItem('sv_token', TOKEN);
      this.enter();
    } catch (e) { this.authError('Sai email hoặc mật khẩu'); }
  },
  async register() {
    try {
      await api('/api/auth/register', { method: 'POST', json: {
        email: $('login-email').value, password: $('login-password').value, full_name: 'Người bán mới' } });
      this.authError('Đã tạo tài khoản, hãy đăng nhập.', false);
    } catch (e) { this.authError(e.message); }
  },
  authError(msg, isErr = true) {
    const el = $('auth-error'); el.textContent = msg; el.classList.remove('hidden');
    el.className = 'mb-3 text-sm px-3 py-2 rounded ' + (isErr ? 'text-red-600 bg-red-50' : 'text-green-700 bg-green-50');
  },
  logout() { TOKEN = null; localStorage.removeItem('sv_token'); $('app').classList.add('hidden'); $('auth-screen').classList.remove('hidden'); },

  async enter() {
    $('auth-screen').classList.add('hidden'); $('app').classList.remove('hidden');
    try { const me = await api('/api/auth/me'); $('user-name').textContent = me.full_name || me.email; } catch (e) {}
    this.go('dashboard');
    this.refreshAlertBadge();
  },

  // ---------- Điều hướng ----------
  go(page) {
    document.querySelectorAll('[id^="page-"]').forEach(s => { if (s.id.startsWith('page-')) s.classList.add('hidden'); });
    $('page-' + page).classList.remove('hidden');
    document.querySelectorAll('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.page === page));
    const titles = { dashboard:'Tổng quan', products:'Sản phẩm', inventory:'Nhập hàng',
      bsr:'BSR & LTV', alerts:'Cảnh báo', reimburse:'Bồi thường FBA', ppc:'PPC_LHHKMT', ads:'Amazon Ads', ethics:'Quyền riêng tư' };
    $('page-title').textContent = titles[page] || '';
    const loaders = { dashboard:'loadDashboard', products:'loadProducts', inventory:'loadInventory',
      bsr:'loadBsr', alerts:'loadAlerts', reimburse:'loadReimburse', ppc:'loadPpc', ads:'loadAmazonAds', ethics:'loadEthics' };
    this[loaders[page]] && this[loaders[page]]();
  },

  // ---------- Dashboard ----------
  async loadDashboard() {
    await Promise.all([
      this.loadPeriods(),
      this.loadProductPerf(),
    ]);
  },
  // Quy đổi key kỳ (chọn ở dropdown) -> {start, end} dạng YYYY-MM-DD,
  // theo cùng định nghĩa kỳ với 5 thẻ tổng quan ở profit.period_overview().
  _periodRange(key) {
    const now = new Date();
    const fmt = (d) => d.toISOString().slice(0, 10);
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    if (key === 'today') return { start: fmt(today), end: fmt(today) };
    if (key === 'yesterday') {
      const y = new Date(today); y.setDate(y.getDate() - 1);
      return { start: fmt(y), end: fmt(y) };
    }
    if (key === 'mtd') {
      const ms = new Date(today.getFullYear(), today.getMonth(), 1);
      return { start: fmt(ms), end: fmt(today) };
    }
    if (key === 'last_month') {
      const ms = new Date(today.getFullYear(), today.getMonth() - 1, 1);
      const me = new Date(today.getFullYear(), today.getMonth(), 0);
      return { start: fmt(ms), end: fmt(me) };
    }
    // N ngày gần nhất (7/30/90)
    const days = Number(key) || 30;
    const start = new Date(today); start.setDate(start.getDate() - (days - 1));
    return { start: fmt(start), end: fmt(today) };
  },
  // Bảng hiệu suất sản phẩm chi tiết kiểu Sellerboard (NEW_summary_products)
  async loadProductPerf() {
    const { start, end } = this._periodRange($('range-select').value);
    const d = await api(`/api/analytics/dashboard/summary?tab=products&start=${start}&end=${end}`);
    $('top-products').innerHTML = (d.products || []).map(p => `<tr class="border-b last:border-0 hover:bg-slate-50">
      <td class="py-2"><div class="font-medium">${p.product}</div><div class="text-xs text-slate-400">${p.asin} · ${p.sku}</div></td>
      <td class="text-right">${fmtNum(p.units)}</td>
      <td class="text-right ${p.refunds>0?'text-red-500':'text-slate-400'}">${fmtNum(p.refunds)}</td>
      <td class="text-right">${fmtMoney(p.sales)}</td>
      <td class="text-right text-slate-500">${fmtMoney(p.average_sales_price)}</td>
      <td class="text-right ${p.ads<0?'text-red-500':'text-slate-500'}">${fmtMoney(p.ads)}</td>
      <td class="text-right text-slate-500">${fmtMoney(p.gross_profit)}</td>
      <td class="text-right font-semibold ${p.net_profit>=0?'text-green-600':'text-red-600'}">${fmtMoney(p.net_profit)}</td>
      <td class="text-right">${p.margin_pct}%</td>
      <td class="text-right">${p.roi_pct}%</td>
      <td class="text-right text-slate-500">${p.bsr ? '#' + fmtNum(p.bsr) : '·'}</td></tr>`).join('')
      || '<tr><td colspan="11" class="py-4 text-slate-400 text-center">Chưa có dữ liệu cho kỳ này</td></tr>';
  },
  drawSales(ts) {
    const ctx = $('sales-chart');
    if (salesChart) salesChart.destroy();
    salesChart = new Chart(ctx, { type: 'line', data: {
      labels: ts.map(t => t.date.slice(5)),
      datasets: [
        { label:'Doanh thu', data: ts.map(t=>t.sales), borderColor:'#6366f1', backgroundColor:'rgba(99,102,241,.1)', fill:true, tension:.3 },
        { label:'Lợi nhuận', data: ts.map(t=>t.profit), borderColor:'#10b981', backgroundColor:'rgba(16,185,129,.1)', fill:true, tension:.3 },
      ]}, options: { responsive:true, plugins:{legend:{position:'bottom'}}, scales:{y:{beginAtZero:true}} } });
  },
  // ---------- Thẻ kỳ so sánh (Today / Yesterday / Month to date / Forecast / Last month) ----------
  _PERIOD_COLORS: ['from-sky-500 to-sky-600', 'from-cyan-500 to-cyan-600', 'from-teal-500 to-teal-600',
                   'from-emerald-500 to-emerald-600', 'from-slate-500 to-slate-600'],
  async loadPeriods() {
    const d = await api('/api/analytics/periods');
    $('period-cards').innerHTML = (d.periods || [])
      .map((p, i) => this.periodCard(p, this._PERIOD_COLORS[i % this._PERIOD_COLORS.length])).join('');
  },
  periodCard(p, gradient) {
    const delta = (v) => (v === null || v === undefined) ? '' :
      `<span class="text-xs font-semibold ${v >= 0 ? 'text-emerald-600' : 'text-red-500'} ml-1.5">${v >= 0 ? '▲' : '▼'} ${Math.abs(v)}%</span>`;
    return `<div class="bg-white rounded-xl shadow-sm overflow-hidden flex flex-col">
      <div class="bg-gradient-to-r ${gradient} text-white px-4 py-3">
        <div class="text-sm font-semibold">${p.label}</div>
        <div class="text-xs text-white/80">${p.range_label}</div>
      </div>
      <div class="p-4 flex-1 flex flex-col gap-3 text-sm">
        <div>
          <div class="text-xs text-slate-400">Sales</div>
          <div class="text-xl font-bold">${fmtMoney(p.sales)}${delta(p.sales_delta_pct)}</div>
        </div>
        <div class="grid grid-cols-2 gap-y-2 gap-x-3">
          <div><div class="text-xs text-slate-400">Orders / Units</div><div class="font-medium">${fmtNum(p.orders)} / ${fmtNum(p.units)}</div></div>
          <div><div class="text-xs text-slate-400">Refunds</div><div class="font-medium">${fmtNum(p.refunds)}</div></div>
          <div><div class="text-xs text-slate-400">Adv. cost</div><div class="font-medium text-red-500">-${fmtMoney(Math.abs(p.adv_cost))}</div></div>
          <div><div class="text-xs text-slate-400">Est. payout</div><div class="font-medium">${fmtMoney(p.est_payout)}</div></div>
        </div>
        <div class="mt-auto pt-3 border-t border-slate-100">
          <div class="text-xs text-slate-400">Net profit</div>
          <div class="text-lg font-bold ${p.net_profit >= 0 ? 'text-emerald-600' : 'text-red-500'}">${fmtMoney(p.net_profit)}${delta(p.net_profit_delta_pct)}</div>
        </div>
      </div>
    </div>`;
  },
  drawMarket(bd) {
    const ctx = $('market-chart');
    if (marketChart) marketChart.destroy();
    const labels = Object.keys(bd), data = Object.values(bd);
    marketChart = new Chart(ctx, { type: 'doughnut', data: { labels,
      datasets:[{ data, backgroundColor:['#6366f1','#10b981','#f59e0b','#ef4444','#8b5cf6'] }] },
      options:{ plugins:{legend:{position:'bottom'}} } });
  },

  // ---------- Products ----------
  async loadProducts() {
    const ps = await api('/api/products');
    $('product-rows').innerHTML = ps.map(p => `<tr class="border-b last:border-0 hover:bg-slate-50">
      <td class="py-2 font-mono text-xs">${p.asin}</td><td>${p.sku}</td><td>${p.title}</td>
      <td><span class="text-xs bg-slate-100 px-2 py-0.5 rounded">${p.marketplace}</span></td>
      <td class="text-right">${fmtMoney(p.price)}</td><td class="text-right">${fmtNum(p.current_stock)}</td>
      <td class="text-right text-slate-500">${fmtNum(p.inbound_stock)}</td></tr>`).join('');
  },

  // ---------- Inventory ----------
  async loadInventory() {
    const g = (Number($('growth').value) || 0) / 100;
    const rows = await api('/api/inventory/restock?monthly_growth_target=' + g);
    const colors = { 'khẩn cấp':'bg-red-100 text-red-700', 'cần đặt ngay':'bg-orange-100 text-orange-700',
      'theo dõi':'bg-yellow-100 text-yellow-700', 'ổn định':'bg-green-100 text-green-700' };
    $('restock-rows').innerHTML = rows.map(r => `<tr class="border-b last:border-0 hover:bg-slate-50">
      <td class="py-2"><div class="font-medium">${r.title}</div><div class="text-xs text-slate-400">${r.asin}</div></td>
      <td class="text-right">${r.daily_velocity}</td><td class="text-right">${fmtNum(r.current_stock)}</td>
      <td class="text-right">${r.days_of_stock>=9999?'∞':r.days_of_stock}</td><td class="text-right">${fmtNum(r.reorder_point)}</td>
      <td class="text-right font-semibold ${r.suggested_order_qty>0?'text-indigo-600':'text-slate-400'}">${fmtNum(r.suggested_order_qty)}</td>
      <td class="text-xs">${r.stockout_date || '—'}</td>
      <td><span class="text-xs px-2 py-0.5 rounded ${colors[r.urgency]||''}">${r.urgency}</span></td></tr>`).join('');
  },

  // ---------- BSR + LTV ----------
  async loadBsr() {
    const [ltv, bsr] = await Promise.all([api('/api/analytics/ltv'), api('/api/analytics/bsr')]);
    $('ltv-cards').innerHTML = [
      ['LTV trung bình', fmtMoney(ltv.avg_ltv)], ['Đơn / khách', ltv.avg_orders_per_customer],
      ['Số khách hàng', fmtNum(ltv.customers)], ['Tỷ lệ mua lại', ltv.repeat_rate_pct + '%'],
    ].map(([l,v]) => `<div class="bg-white rounded-xl p-4 shadow-sm"><div class="text-xs text-slate-500 mb-1">${l}</div><div class="text-xl font-bold">${v}</div></div>`).join('');
    $('bsr-rows').innerHTML = bsr.map(b => {
      const w = b.vs_week_pct, m = b.vs_month_pct;
      const tag = (x) => `<span class="${x>=0?'text-green-600':'text-red-600'}">${x>=0?'▲':'▼'} ${Math.abs(x)}%</span>`;
      return `<tr class="border-b last:border-0 hover:bg-slate-50">
        <td class="py-2"><div class="font-medium">${b.title}</div><div class="text-xs text-slate-400">${b.asin}</div></td>
        <td class="text-right">#${fmtNum(b.current_bsr)}</td><td class="text-right text-slate-500">#${fmtNum(b.avg_week)}</td>
        <td class="text-right text-slate-500">#${fmtNum(b.avg_month)}</td><td class="text-right">${tag(w)}</td><td class="text-right">${tag(m)}</td></tr>`;
    }).join('') || '<tr><td class="py-4 text-slate-400">Chưa có dữ liệu BSR</td></tr>';
  },

  // ---------- Alerts ----------
  async loadAlerts() {
    const list = await api('/api/alerts');
    const sev = { critical:'border-red-400 bg-red-50', warning:'border-yellow-400 bg-yellow-50', info:'border-slate-300 bg-white' };
    const icon = { buybox_lost:'🛑', hijacker:'🥷', fee_changed:'💸', image_changed:'🖼️', title_changed:'✏️', dimensions_changed:'📏' };
    $('alert-list').innerHTML = list.map(a => `<div class="border-l-4 ${sev[a.severity]||'bg-white'} rounded-lg p-4 shadow-sm flex items-start gap-3">
      <span class="text-xl">${icon[a.type]||'🔔'}</span>
      <div class="flex-1"><div class="text-sm">${a.message}</div>
        <div class="text-xs text-slate-400 mt-1">${new Date(a.created_at).toLocaleString('vi-VN')} · ${a.severity}</div></div>
      ${a.is_read?'':`<button onclick="App.readAlert(${a.id})" class="text-xs text-indigo-600 hover:underline">Đánh dấu đã đọc</button>`}
      </div>`).join('') || '<div class="text-slate-400 text-sm">Không có cảnh báo nào 🎉</div>';
    this.refreshAlertBadge();
  },
  async scanAlerts() { await api('/api/alerts/scan', { method:'POST' }); this.loadAlerts(); },
  async readAlert(id) { await api('/api/alerts/' + id + '/read', { method:'POST' }); this.loadAlerts(); },
  async refreshAlertBadge() {
    try { const list = await api('/api/alerts'); const n = list.filter(a => !a.is_read).length;
      const b = $('alert-badge'); if (n>0){ b.textContent = n; b.classList.remove('hidden'); } else b.classList.add('hidden'); } catch(e){}
  },

  // ---------- Reimbursements ----------
  async loadReimburse() {
    const rows = await api('/api/reimbursements');
    const reason = { refund_no_return:'Hoàn tiền không trả hàng', lost:'FBA làm mất', damaged:'FBA làm hư' };
    $('reimburse-rows').innerHTML = rows.map(r => `<tr class="border-b last:border-0 hover:bg-slate-50">
      <td class="py-2">#${r.product_id}</td><td>${reason[r.reason]||r.reason}</td><td class="text-right">${r.quantity}</td>
      <td class="text-right font-semibold text-green-600">${fmtMoney(r.estimated_amount)}</td>
      <td><span class="text-xs bg-slate-100 px-2 py-0.5 rounded">${r.status}</span></td>
      <td class="text-xs">${new Date(r.detected_at).toLocaleDateString('vi-VN')}</td></tr>`).join('')
      || '<tr><td class="py-4 text-slate-400">Chưa có hồ sơ bồi thường</td></tr>';
  },
  async scanReimburse() { await api('/api/reimbursements/scan', { method:'POST' }); this.loadReimburse(); },

  // ---------- PPC_LHHKMT (đa store · drill-down 3 cấp · CTR/CVR · export) ----------
  _ppc: { listing: [], store: null, sku: null, camp: null, detail: null },

  ppcView(which) {
    ['listing', 'campaigns', 'detail'].forEach(v =>
      $('ppc-view-' + v).classList.toggle('hidden', v !== which));
  },
  ppcCrumb() {
    const s = this._ppc;
    const parts = [`<span class="cursor-pointer hover:text-indigo-600" onclick="App.ppcShowListing()">📋 Listing</span>`];
    if (s.sku) parts.push(`<span class="cursor-pointer hover:text-indigo-600" onclick="App.ppcOpenSku('${encodeURIComponent(s.sku)}')">${s.sku}</span>`);
    if (s.camp) parts.push(`<span class="text-slate-700 font-medium">${s.camp}</span>`);
    $('ppc-breadcrumb').innerHTML = parts.join(' <span class="text-slate-300">/</span> ');
  },

  async loadPpc() {
    this._ppc = { listing: [], store: null, sku: null, camp: null, detail: null };
    const stores = await api('/api/ppc/stores');
    const sel = $('ppc-store-select');
    sel.innerHTML = (stores || []).map(s => `<option value="${s.store}">${s.store}</option>`).join('');
    this._ppc.store = stores && stores.length ? stores[0].store : null;
    await this.ppcLoadListing();
  },
  ppcChangeStore() { this._ppc.store = $('ppc-store-select').value; this.ppcLoadListing(); },
  async ppcUpload(input) {
    const file = input.files && input.files[0];
    if (!file) return;
    const fd = new FormData(); fd.append('file', file);
    _loading(true);
    let res;
    try {
      res = await fetch(API + '/api/ppc/upload', {
        method: 'POST', headers: { Authorization: 'Bearer ' + TOKEN }, body: fd });
    } finally { _loading(false); }
    input.value = '';
    const r = await res.json().catch(() => ({}));
    if (!res.ok || r.error) { alert('Upload lỗi: ' + (r.error || res.status)); return; }
    // nạp lại danh sách store và chọn store vừa upload
    const stores = await api('/api/ppc/stores');
    const sel = $('ppc-store-select');
    sel.innerHTML = (stores || []).map(s => `<option value="${s.store}">${s.store}</option>`).join('');
    sel.value = r.store; this._ppc.store = r.store;
    await this.ppcLoadListing();
    alert('Đã tải lên store: ' + r.store);
  },
  async ppcLoadListing() {
    const d = await api('/api/ppc/listing?store=' + encodeURIComponent(this._ppc.store || ''));
    $('ppc-store').textContent = d.store || '';
    $('ppc-store-file').textContent = d.file ? '· ' + d.file : '';
    if (d.error) $('ppc-listing-rows').innerHTML = `<tr><td colspan="6" class="py-4 text-red-500">${d.error}</td></tr>`;
    this._ppc.listing = d.listing || [];
    this.ppcShowListing();
  },
  ppcShowListing() {
    this._ppc.sku = null; this._ppc.camp = null;
    this.ppcView('listing'); this.ppcCrumb(); this.ppcRenderListing(this._ppc.listing);
  },
  ppcFilter() {
    const q = ($('ppc-search').value || '').toLowerCase();
    this.ppcRenderListing(this._ppc.listing.filter(r =>
      (r.sku + ' ' + r.portfolio_name).toLowerCase().includes(q)));
  },
  ppcRenderListing(rows) {
    $('ppc-listing-rows').innerHTML = rows.map(r => {
      const clickable = r.has_detail;
      const skuCell = clickable
        ? `<span class="text-indigo-600 font-medium cursor-pointer hover:underline" onclick="App.ppcOpenSku('${encodeURIComponent(r.sku)}')">${r.sku}</span>`
        : `<span class="text-slate-700">${r.sku}</span>`;
      const badge = clickable
        ? `<button onclick="App.ppcOpenSku('${encodeURIComponent(r.sku)}')" class="text-xs bg-indigo-50 text-indigo-600 px-2 py-1 rounded hover:bg-indigo-100">Xem campaign →</button>`
        : `<span class="text-xs text-slate-300">—</span>`;
      return `<tr class="border-b last:border-0 hover:bg-slate-50">
        <td class="py-2 text-slate-400">${r.stt}</td><td>${skuCell}</td>
        <td class="text-slate-600">${r.portfolio_name || ''}</td>
        <td><span class="text-xs bg-slate-100 px-2 py-0.5 rounded">${r.status || ''}</span></td>
        <td>${r.link ? `<a href="${r.link}" target="_blank" class="text-xs text-blue-500 hover:underline">Mở Amazon ↗</a>` : ''}</td>
        <td class="text-right">${badge}</td></tr>`;
    }).join('') || '<tr><td colspan="6" class="py-4 text-slate-400">Không có dòng nào</td></tr>';
  },

  async ppcOpenSku(skuEnc) {
    const sku = decodeURIComponent(skuEnc);
    this._ppc.sku = sku; this._ppc.camp = null;
    const d = await api('/api/ppc/sku?sku=' + encodeURIComponent(sku) + '&store=' + encodeURIComponent(this._ppc.store || ''));
    this._ppc.detail = d;
    $('ppc-sku-name').textContent = sku;
    $('ppc-sku-msg').textContent = d.message || (d.campaigns?.length ? `${d.campaigns.length} campaign · các kỳ: ${(d.periods||[]).join(', ') || '—'}` : 'Không có campaign');
    $('ppc-campaign-rows').innerHTML = (d.campaigns || []).map((c, i) => `<tr class="border-b last:border-0 hover:bg-slate-50">
      <td class="py-2"><span class="text-indigo-600 font-medium cursor-pointer hover:underline" onclick="App.ppcOpenCampaign(${i})">${c.name}</span></td>
      <td class="text-slate-600">${c.type || ''}</td>
      <td><span class="text-xs bg-slate-100 px-2 py-0.5 rounded">${c.status || ''}</span></td>
      <td class="text-right">${fmtNum(c.totals.impression)}</td>
      <td class="text-right">${fmtNum(c.totals.click)}</td>
      <td class="text-right font-semibold ${c.totals.order>0?'text-green-600':''}">${fmtNum(c.totals.order)}</td>
      <td class="text-right">${fmtPct(c.totals.ctr)}</td>
      <td class="text-right">${fmtPct(c.totals.cvr)}</td>
      <td class="text-right"><button onclick="App.ppcOpenCampaign(${i})" class="text-xs text-indigo-600 hover:underline">Chi tiết →</button></td>
    </tr>`).join('') || '<tr><td colspan="9" class="py-4 text-slate-400">SKU này chưa có campaign chi tiết</td></tr>';
    this.ppcView('campaigns'); this.ppcCrumb();
  },

  ppcOpenCampaign(idx) {
    const c = this._ppc.detail.campaigns[idx];
    const periods = this._ppc.detail.periods || [];
    this._ppc.camp = c.name;
    $('ppc-camp-name').textContent = c.name;
    // Header 2 tầng: Target | [kỳ: Imp/Click/Order]×N | CTR | CVR | Note
    let head = '<tr class="text-left"><th class="py-2" rowspan="2">Target (keyword)</th>';
    if (periods.length === 0) head += '<th class="text-right" rowspan="2">Impression</th><th class="text-right" rowspan="2">Click</th><th class="text-right" rowspan="2">Order</th>';
    periods.forEach(p => head += `<th class="text-center border-l" colspan="3">${p}</th>`);
    head += '<th class="text-right" rowspan="2">CTR</th><th class="text-right" rowspan="2">CVR</th><th rowspan="2">Note</th></tr>';
    if (periods.length > 0) {
      head += '<tr class="text-xs text-slate-400">';
      periods.forEach(() => head += '<th class="text-right border-l">Imp</th><th class="text-right">Click</th><th class="text-right">Order</th>');
      head += '</tr>';
    }
    $('ppc-detail-head').innerHTML = head;

    const n = (v) => v === null || v === undefined ? '·' : fmtNum(v);
    $('ppc-detail-rows').innerHTML = (c.targets || []).map(t => {
      const tt = t.totals || {};
      let row = `<tr class="border-b last:border-0 hover:bg-slate-50"><td class="py-2 font-medium">${t.target || '—'}</td>`;
      const ms = t.metrics && t.metrics.length ? t.metrics : [{impression:null,click:null,order:null}];
      ms.forEach(m => row += `<td class="text-right border-l">${n(m.impression)}</td><td class="text-right">${n(m.click)}</td><td class="text-right ${m.order>0?'text-green-600 font-semibold':''}">${n(m.order)}</td>`);
      row += `<td class="text-right">${fmtPct(tt.ctr)}</td><td class="text-right">${fmtPct(tt.cvr)}</td>`;
      row += `<td class="text-xs text-slate-400">${t.note || ''}</td></tr>`;
      return row;
    }).join('') || '<tr><td class="py-4 text-slate-400">Không có target</td></tr>';
    this.ppcView('detail'); this.ppcCrumb();
  },

  async ppcExport(fmt) {
    const s = this._ppc;
    const p = new URLSearchParams({ format: fmt });
    if (s.store) p.set('store', s.store);
    if (s.sku) p.set('sku', s.sku);            // đang ở 1 SKU → xuất SKU đó; nếu không → cả store
    _loading(true);
    let res;
    try {
      res = await fetch(API + '/api/ppc/export?' + p.toString(), { headers: { Authorization: 'Bearer ' + TOKEN } });
    } finally { _loading(false); }
    if (!res.ok) { alert('Xuất file lỗi: ' + res.status); return; }
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename="?([^"]+)"?/);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = m ? m[1] : ('PPC.' + fmt); a.click();
    URL.revokeObjectURL(url);
  },


  // ---------- Amazon Sync (chay nen — bam la tra ve ngay, theo doi tien do qua polling) ----------
  async syncAmazon() {
    const btn = $('btn-sync');
    btn.disabled = true;
    try {
      const r = await api('/api/amazon/sync?days=' + (window.SV_SYNC_DAYS || 7), { method: 'POST' });
      if (r.status === 'already_running') {
        btn.textContent = '⏳ Đang sync (tiến trình trước đó)...';
      } else {
        btn.textContent = '⏳ Đang sync...';
      }
      await this._pollAmazonSync(btn);
    } catch(e) {
      alert('Lỗi sync: ' + e.message);
      btn.textContent = '🔄 Sync Amazon'; btn.disabled = false;
    }
  },

  async _pollAmazonSync(btn) {
    while (true) {
      await new Promise(r => setTimeout(r, 3000));
      let p;
      try { p = await api('/api/amazon/sync/progress'); } catch(e) { continue; }

      if (p.status === 'running') {
        const total = p.total || 0;
        const pct = total ? Math.round((p.processed || 0) / total * 100) : 0;
        btn.textContent = total
          ? `⏳ Đang sync... ${p.processed || 0}/${total} đơn (${pct}%)`
          : '⏳ Đang sync... (đang tải danh sách đơn hàng)';
        continue;
      }

      if (p.status === 'done') {
        alert('✅ Sync xong!\n' +
          '📦 Orders mới: ' + p.orders_synced + '\n' +
          '🛍 Sản phẩm tạo: ' + p.products_created + '\n' +
          '📊 Inventory: ' + p.inventory_updated +
          ((p.errors || []).length ? '\n⚠️ Lỗi: ' + p.errors.slice(0,3).join(', ') : ''));
        this.loadDashboard();
      } else if (p.status === 'error') {
        alert('❌ Sync lỗi: ' + ((p.errors || []).join(', ') || 'không rõ nguyên nhân'));
      }
      break;
    }
    btn.textContent = '🔄 Sync Amazon'; btn.disabled = false;
  },

  // ---------- Amazon Ads ----------
  async loadAmazonAds() {
    const statusEl = $('ads-sync-info');
    try {
      const st = await api('/api/amazon/sync/status');
      if (statusEl) statusEl.textContent =
        '📦 ' + st.orders_in_db + ' đơn · 🛍 ' + st.products_in_db + ' SP trong DB';
    } catch(e) {}

    try {
      const campaigns = await api('/api/ads/campaigns');
      const stateColor = { ENABLED:'bg-green-100 text-green-700', PAUSED:'bg-yellow-100 text-yellow-700', ARCHIVED:'bg-slate-100 text-slate-500' };
      $('ads-campaign-rows').innerHTML = campaigns.map(c => {
        const state = (c.state || '').toUpperCase();
        const budget = c.budget ? '$' + Number(c.budget.budget || 0).toFixed(2) : '—';
        const strategy = (c.dynamicBidding || {}).strategy || '—';
        return `<tr class="border-b last:border-0 hover:bg-slate-50">
          <td class="py-2 font-medium max-w-xs truncate" title="${c.name}">${c.name}</td>
          <td class="text-slate-500 text-xs">${c.portfolioId || '—'}</td>
          <td class="text-xs">${strategy}</td>
          <td class="text-right">${budget}</td>
          <td class="text-xs text-slate-500">${c.startDate || '—'}</td>
          <td><span class="text-xs px-2 py-0.5 rounded ${stateColor[state]||''}">${state}</span></td>
        </tr>`;
      }).join('') || '<tr><td class="py-4 text-slate-400">Không có campaigns</td></tr>';
    } catch(e) {
      $('ads-campaign-rows').innerHTML = '<tr><td class="py-4 text-red-500">Lỗi: ' + e.message + '</td></tr>';
    }
  },
  // ---------- Ethics ----------
  async loadEthics() {
    const t = await api('/api/ethics/transparency');
    $('ethics-summary').textContent = t.summary;
    $('ethics-rows').innerHTML = t.data_catalog.map(d => `<tr class="border-b last:border-0">
      <td class="py-2 font-medium">${d.category}</td><td>${d.data}</td><td>${d.purpose}</td><td>${d.retention}</td>
      <td>${d.required?'<span class="text-red-500">Bắt buộc</span>':'<span class="text-green-600">Tuỳ chọn</span>'}</td></tr>`).join('');
    const consent = await api('/api/ethics/consent');
    const labels = { analytics:'Phân tích sử dụng', marketing:'Nhận tiếp thị', data_sharing:'Chia sẻ dữ liệu ẩn danh' };
    $('consent-toggles').innerHTML = Object.keys(labels).map(k => `<label class="flex items-center gap-2">
      <input type="checkbox" ${consent[k]?'checked':''} onchange="App.setConsent('${k}', this.checked)" class="w-4 h-4"> ${labels[k]}</label>`).join('');
  },
  async setConsent(key, val) {
    const consent = await api('/api/ethics/consent'); consent[key] = val;
    await api('/api/ethics/consent', { method:'PUT', json: consent });
  },
  async minimize() {
    const r = await api('/api/ethics/minimize', { method:'POST' });
    alert('Đã xoá ' + r.deleted_records + ' bản ghi thô quá hạn lưu trữ.');
  },
};

// Tự đăng nhập lại nếu còn token
if (TOKEN) App.enter();
