/* Module ADS — render_ads.js
 * Trang "📣 Amazon Ads": chỉ số quảng cáo ĐỌC từ DB (NEW_ads_*) — ACOS/ROAS/TACOS/
 * CTR/CVR/CPC ở cấp overview / campaign / SKU.
 *
 * Cách hoạt động (KHÔNG sửa app.js gốc — giống render_performance.js):
 *   - Nạp SAU app.js (patch_ads_page.py chèn <script src="/static/render_ads.js">).
 *   - Tiêm DOM metrics (#ads-metrics) vào ĐẦU #page-ads ngay lần đầu.
 *   - Ghi đè App.loadAmazonAds: tải metrics từ /api/ads/analytics/* (luôn chạy được),
 *     đồng thời gọi bản gốc trong try/catch để bảng entity live cũ vẫn hoạt động.
 *
 * Dữ liệu: GET /api/ads/analytics/overview|campaigns|skus?start&end&window
 * (backend/app/routers/ads.py -> ads/ads_aggregator.py). cost/sales là số DƯƠNG.
 */
(function () {
  'use strict';

  // ── Helper định dạng ──────────────────────────────────────────────────────
  var fmtMoney = function (v) {
    var n = Number(v) || 0;
    return (n < 0 ? '-' : '') + '$' + Math.abs(n).toLocaleString('en-US',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  var fmtNum = function (v) { return (Number(v) || 0).toLocaleString('en-US'); };
  var pct = function (r) { return r == null ? '—' : (Number(r) * 100).toFixed(1) + '%'; };
  var roasx = function (r) { return r == null ? '—' : Number(r).toFixed(2) + '×'; };
  var cpc = function (r) { return r == null ? '—' : fmtMoney(r); };
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  // ACOS: thấp = tốt -> xanh; cao -> đỏ (ngưỡng mềm chỉ để nhìn nhanh)
  var acosCls = function (r) {
    if (r == null) return 'text-slate-400';
    return r <= 0.25 ? 'text-green-600' : r >= 0.5 ? 'text-red-600' : 'text-slate-700';
  };

  var state = { start: null, end: null, window: '7d' };

  // ── Tiêm khung metrics vào #page-ads (1 lần) ──────────────────────────────
  function ensureAdsUI() {
    var page = document.getElementById('page-ads');
    if (!page || document.getElementById('ads-metrics')) return;

    var box = document.createElement('div');
    box.id = 'ads-metrics';
    box.className = 'space-y-4 mb-5';
    box.innerHTML =
      // Thanh điều khiển khoảng ngày + cửa sổ attribution
      '<div class="flex flex-wrap items-center gap-3 bg-white rounded-xl p-3 shadow-sm">' +
        '<span class="text-sm font-semibold">📣 Chỉ số quảng cáo</span>' +
        '<label class="text-sm text-slate-500 ml-2">Từ <input type="date" id="ads-start" class="border rounded px-2 py-1 ml-1"></label>' +
        '<label class="text-sm text-slate-500">đến <input type="date" id="ads-end" class="border rounded px-2 py-1 ml-1"></label>' +
        '<label class="text-sm text-slate-500">Cửa sổ <select id="ads-window" class="border rounded px-2 py-1 ml-1">' +
          '<option value="1d">1 ngày</option><option value="7d" selected>7 ngày</option><option value="14d">14 ngày</option>' +
        '</select></label>' +
        '<button id="ads-apply" class="bg-indigo-600 text-white text-sm px-3 py-1.5 rounded-lg hover:bg-indigo-700">Áp dụng</button>' +
        '<span id="ads-meta" class="text-xs text-slate-400 ml-auto"></span>' +
      '</div>' +
      // Hàng thẻ KPI
      '<div id="ads-kpi" class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3"></div>' +
      // Bảng campaign
      '<div class="bg-white rounded-xl p-5 shadow-sm">' +
        '<h3 class="font-semibold mb-3">Hiệu quả theo Campaign</h3>' +
        '<div class="overflow-x-auto"><table class="w-full text-sm whitespace-nowrap">' +
          '<thead class="text-slate-500 border-b"><tr class="text-left">' +
            '<th class="py-2">Campaign</th><th>Loại</th><th>State</th>' +
            '<th class="text-right">Spend</th><th class="text-right">Ad Sales</th>' +
            '<th class="text-right">ACOS</th><th class="text-right">ROAS</th>' +
            '<th class="text-right">Orders</th><th class="text-right">CTR</th>' +
            '<th class="text-right">CVR</th><th class="text-right">CPC</th>' +
          '</tr></thead><tbody id="ads-camp-rows"></tbody></table></div>' +
      '</div>' +
      // Bảng SKU
      '<div class="bg-white rounded-xl p-5 shadow-sm">' +
        '<h3 class="font-semibold mb-3">Hiệu quả theo SKU / ASIN</h3>' +
        '<div class="overflow-x-auto"><table class="w-full text-sm whitespace-nowrap">' +
          '<thead class="text-slate-500 border-b"><tr class="text-left">' +
            '<th class="py-2">SKU</th><th>ASIN</th><th>Sản phẩm</th>' +
            '<th class="text-right">Spend</th><th class="text-right">Ad Sales</th>' +
            '<th class="text-right">ACOS</th><th class="text-right">ROAS</th>' +
            '<th class="text-right">Orders</th><th class="text-right">CTR</th>' +
            '<th class="text-right">CVR</th><th class="text-right">CPC</th>' +
          '</tr></thead><tbody id="ads-sku-rows"></tbody></table></div>' +
      '</div>';

    page.insertBefore(box, page.firstChild);

    document.getElementById('ads-apply').addEventListener('click', function () {
      state.start = document.getElementById('ads-start').value || null;
      state.end = document.getElementById('ads-end').value || null;
      state.window = document.getElementById('ads-window').value || '7d';
      loadAdsMetrics();
    });
  }

  function qs() {
    var p = ['window=' + encodeURIComponent(state.window)];
    if (state.start) p.push('start=' + state.start);
    if (state.end) p.push('end=' + state.end);
    return '?' + p.join('&');
  }

  function tile(label, value, sub) {
    return '<div class="bg-white rounded-xl p-4 shadow-sm">' +
      '<div class="text-xs text-slate-500">' + esc(label) + '</div>' +
      '<div class="text-lg font-semibold mt-1">' + value + '</div>' +
      (sub ? '<div class="text-xs text-slate-400 mt-0.5">' + sub + '</div>' : '') +
      '</div>';
  }

  function renderKpi(ov) {
    var k = (ov && ov.kpis) || {};
    var el = document.getElementById('ads-kpi');
    if (!el) return;
    el.innerHTML =
      tile('Ad Spend', fmtMoney(k.spend)) +
      tile('Ad Sales', fmtMoney(k.ad_sales)) +
      tile('ACOS', '<span class="' + acosCls(k.acos) + '">' + pct(k.acos) + '</span>') +
      tile('ROAS', roasx(k.roas)) +
      tile('TACOS', pct(k.tacos), ov.total_sales != null ? 'Tổng sales ' + fmtMoney(ov.total_sales) : 'thiếu summary') +
      tile('Orders', fmtNum(k.orders)) +
      tile('CTR', pct(k.ctr), fmtNum(k.clicks) + ' clicks') +
      tile('CVR', pct(k.cvr)) +
      tile('CPC', cpc(k.cpc)) +
      tile('Impressions', fmtNum(k.impressions));
    var meta = document.getElementById('ads-meta');
    if (meta && ov.period) meta.textContent = ov.period.start + ' → ' + ov.period.end + ' · attr ' + ov.window;
  }

  function campRow(c) {
    return '<tr class="border-b border-slate-50 hover:bg-slate-50">' +
      '<td class="py-2 max-w-[22rem] truncate" title="' + esc(c.campaign_name) + '">' + esc(c.campaign_name || c.campaign_id) + '</td>' +
      '<td class="text-slate-500">' + esc(c.ad_product || '') + '</td>' +
      '<td class="text-slate-500">' + esc(c.state || '—') + '</td>' +
      '<td class="text-right">' + fmtMoney(c.spend) + '</td>' +
      '<td class="text-right">' + fmtMoney(c.ad_sales) + '</td>' +
      '<td class="text-right ' + acosCls(c.acos) + '">' + pct(c.acos) + '</td>' +
      '<td class="text-right">' + roasx(c.roas) + '</td>' +
      '<td class="text-right">' + fmtNum(c.orders) + '</td>' +
      '<td class="text-right text-slate-500">' + pct(c.ctr) + '</td>' +
      '<td class="text-right text-slate-500">' + pct(c.cvr) + '</td>' +
      '<td class="text-right text-slate-500">' + cpc(c.cpc) + '</td>' +
    '</tr>';
  }

  function skuRow(s) {
    return '<tr class="border-b border-slate-50 hover:bg-slate-50">' +
      '<td class="py-2 font-mono text-xs">' + esc(s.sku || '—') + '</td>' +
      '<td class="font-mono text-xs text-slate-500">' + esc(s.asin || '—') + '</td>' +
      '<td class="max-w-[20rem] truncate" title="' + esc(s.title) + '">' + esc(s.title || '') + '</td>' +
      '<td class="text-right">' + fmtMoney(s.spend) + '</td>' +
      '<td class="text-right">' + fmtMoney(s.ad_sales) + '</td>' +
      '<td class="text-right ' + acosCls(s.acos) + '">' + pct(s.acos) + '</td>' +
      '<td class="text-right">' + roasx(s.roas) + '</td>' +
      '<td class="text-right">' + fmtNum(s.orders) + '</td>' +
      '<td class="text-right text-slate-500">' + pct(s.ctr) + '</td>' +
      '<td class="text-right text-slate-500">' + pct(s.cvr) + '</td>' +
      '<td class="text-right text-slate-500">' + cpc(s.cpc) + '</td>' +
    '</tr>';
  }

  function rowsInto(id, html, cols, empty) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = html || ('<tr><td colspan="' + cols + '" class="py-4 text-slate-400 text-center">' + empty + '</td></tr>');
  }

  // ── Tải + render toàn bộ metrics ──────────────────────────────────────────
  function loadAdsMetrics() {
    ensureAdsUI();
    rowsInto('ads-camp-rows', '', 11, 'Đang tải...');
    rowsInto('ads-sku-rows', '', 11, 'Đang tải...');

    api('/api/ads/analytics/overview' + qs()).then(function (ov) {
      renderKpi(ov);
      // Lần đầu (chưa chọn ngày): đồng bộ ô date theo kỳ backend trả về (giờ Pacific)
      if (ov.period) {
        var si = document.getElementById('ads-start'), ei = document.getElementById('ads-end');
        if (si && !si.value) si.value = ov.period.start;
        if (ei && !ei.value) ei.value = ov.period.end;
      }
    }).catch(function (e) {
      var el = document.getElementById('ads-kpi');
      if (el) el.innerHTML = '<div class="col-span-full text-sm text-red-600">Lỗi tải KPI: ' + esc(e && e.message) + '</div>';
    });

    api('/api/ads/analytics/campaigns' + qs()).then(function (rows) {
      rowsInto('ads-camp-rows', (rows || []).map(campRow).join(''), 11, 'Chưa có dữ liệu campaign trong kỳ.');
    }).catch(function (e) {
      rowsInto('ads-camp-rows', '', 11, 'Lỗi: ' + esc(e && e.message));
    });

    api('/api/ads/analytics/skus' + qs()).then(function (rows) {
      rowsInto('ads-sku-rows', (rows || []).map(skuRow).join(''), 11, 'Chưa có dữ liệu SKU trong kỳ.');
    }).catch(function (e) {
      rowsInto('ads-sku-rows', '', 11, 'Lỗi: ' + esc(e && e.message));
    });
  }

  // ── Ghi đè App.loadAmazonAds (giữ bản gốc cho bảng entity live) ────────────
  function install() {
    if (typeof App === 'undefined') { return setTimeout(install, 200); }
    var orig = App.loadAmazonAds;
    App.loadAmazonAds = function () {
      ensureAdsUI();
      loadAdsMetrics();
      try { if (typeof orig === 'function') orig.call(App); } catch (e) { /* Ads API chưa cấu hình -> bỏ qua */ }
    };
  }
  install();
})();
