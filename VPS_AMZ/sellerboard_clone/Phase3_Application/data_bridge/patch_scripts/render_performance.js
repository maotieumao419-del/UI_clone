/* Phase 3 — render_performance.js
 * Mở rộng giao diện bảng #top-products thành Ma trận hiệu suất sản phẩm
 * (Product Performance Grid) kiểu Sellerboard. JavaScript THUẦN, không framework.
 *
 * Cách hoạt động (KHÔNG sửa app.js gốc):
 *   - Nạp SAU app.js (patch_frontend.py chèn <script src="/static/render_performance.js">).
 *   - Ghi đè App.loadDashboard: gọi GET /api/analytics/dashboard/summary
 *     (tab=products, start/end tính từ range-select), thẻ kỳ vẫn qua loadPeriods()
 *     như cũ, và render bảng theo layout mới (renderGrid).
 *   - Backend Phase 3 không còn trả timeseries/marketplace_breakdown -> các chart
 *     sales/market được vẽ với dữ liệu rỗng (không lỗi, chỉ tạm trống).
 */
(function () {
  'use strict';

  // ---------- Helper định dạng ----------
  var fmtMoney = function (v) {
    return '$' + (Number(v) || 0).toLocaleString('en-US',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  var fmtNum = function (v) { return (Number(v) || 0).toLocaleString('en-US'); };

  // Escape HTML — tránh title/SKU chứa ký tự đặc biệt phá vỡ template string
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };

  // Logic màu sắc động kiểu Sellerboard:
  //   > 0 -> xanh lá đậm + dấu '+'   |   < 0 -> đỏ rực + dấu '-'
  function pnl(v, isPercent) {
    var n = Number(v) || 0;
    var sign = n > 0 ? '+' : (n < 0 ? '-' : '');
    var body = isPercent ? Math.abs(n).toFixed(1) + '%' : fmtMoney(Math.abs(n));
    var cls = n > 0 ? 'text-green-600 font-semibold'
            : n < 0 ? 'text-red-600 font-semibold'
            : 'text-slate-400';
    return '<span class="' + cls + '">' + sign + body + '</span>';
  }

  // Badge ASIN/SKU nhỏ gọn, click để copy nhanh
  function badge(text, label) {
    if (!text) return '';
    return '<button type="button" onclick="navigator.clipboard&&navigator.clipboard.writeText(\'' +
      esc(text) + '\');this.classList.add(\'ring-1\',\'ring-green-400\');' +
      'var b=this;setTimeout(function(){b.classList.remove(\'ring-1\',\'ring-green-400\')},800)" ' +
      'title="Click để copy ' + esc(label) + '" ' +
      'class="text-[10px] font-mono bg-slate-100 hover:bg-slate-200 text-slate-500 ' +
      'rounded px-1.5 py-0.5 mr-1 cursor-pointer select-all">' + esc(text) + '</button>';
  }

  // Ảnh thumb 50x50 từ ASIN (widget Amazon); lỗi ảnh -> hiện ô chữ cái đầu
  // của title (render sẵn ở trạng thái ẩn, onerror chỉ bật/tắt class).
  function thumb(p) {
    var initial = esc((p.title || p.product || '?').charAt(0).toUpperCase());
    var fallback = '<div class="w-10 h-10 rounded-lg bg-slate-200 hidden ' +
      'items-center justify-center text-slate-500 text-xs font-bold">' + initial + '</div>';
    if (!p.asin) {
      return fallback.replace('hidden', 'flex');
    }
    return '<img loading="lazy" src="https://ws-na.amazon-adsystem.com/widgets/q?_encoding=UTF8&ASIN=' +
      esc(p.asin) + '&Format=_SL64_&ID=AsinImage&MarketPlace=US&ServiceVersion=20070822&WS=1" ' +
      'class="w-10 h-10 rounded-lg object-contain bg-slate-100 border border-slate-200" ' +
      'onerror="this.style.display=\'none\';this.nextElementSibling.classList.remove(\'hidden\');' +
      'this.nextElementSibling.classList.add(\'flex\')">' + fallback;
  }

  var NEW_HEAD =
    '<tr class="text-left">' +
    '<th class="py-2 px-2">Sản phẩm</th>' +
    '<th class="text-right px-2">Số lượng</th>' +
    '<th class="text-right px-2">Doanh thu</th>' +
    '<th class="text-right px-2">Chi phí gốc (COGS)</th>' +
    '<th class="text-right px-2">Phí Amazon</th>' +
    '<th class="text-right px-2">Quảng cáo</th>' +
    '<th class="text-right px-2">Lợi nhuận ròng</th>' +
    '<th class="text-right px-2">Biên LN</th></tr>';

  // Tổng hợp dòng tfoot từ danh sách sản phẩm (get_sku_performance trả về —
  // không có sẵn khoá totals từ backend Phase 3).
  function computeTotals(rows) {
    var t = { quantity: 0, sales: 0, product_cost: 0, fees: 0, ad_spend: 0, net_profit: 0 };
    rows.forEach(function (p) {
      t.quantity += Number(p.units) || 0;
      t.sales += Number(p.sales) || 0;
      t.product_cost += Number(p.cost_of_goods) || 0;
      t.fees += Number(p.amazon_fees) || 0;
      t.ad_spend += Number(p.ads) || 0;
      t.net_profit += Number(p.net_profit) || 0;
    });
    t.margin = t.sales ? (t.net_profit / t.sales * 100) : 0;
    return t;
  }

  // ---------- Render ma trận hiệu suất ----------
  function renderGrid(d) {
    var tbody = document.getElementById('top-products');
    if (!tbody) return false;
    var table = tbody.closest('table');
    var rows = Array.isArray(d.top_products) ? d.top_products : [];

    // Đổi thead sang layout mới (8 cột chuẩn Sellerboard)
    try {
      var thead = table && table.querySelector('thead');
      if (thead) thead.innerHTML = NEW_HEAD;
    } catch (e) { /* thead lỗi không chặn render tbody */ }

    // Trường hợp biên: mảng rỗng -> thông báo sạch, không vỡ bố cục
    if (rows.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" class="py-8 text-center text-slate-400">' +
        'Không có dữ liệu hiệu suất cho khoảng thời gian này</td></tr>';
      removeTfoot(table);
      return true;
    }

    var html = rows.map(function (p) {
      var name = p.title || p.product || '';
      var fees = Number(p.amazon_fees) || 0;
      return '<tr class="border-b last:border-0 hover:bg-gray-50 transition-colors">' +
        '<td class="py-2 px-2"><div class="flex items-center gap-2.5">' + thumb(p) +
          '<div class="min-w-0">' +
            '<div class="font-medium max-w-[260px] truncate" title="' + esc(name) + '">' +
              (esc(name) || '(không có tên)') + '</div>' +
            '<div class="mt-0.5">' + badge(p.asin, 'ASIN') + badge(p.sku, 'SKU') + '</div>' +
          '</div></div></td>' +
        '<td class="text-right px-2">' + fmtNum(p.quantity != null ? p.quantity : p.units) + '</td>' +
        '<td class="text-right px-2"><div>' + fmtMoney(p.sales) + '</div>' +
          '<div class="text-[10px] text-slate-400">' + fmtMoney(p.price != null ? p.price : p.average_sales_price) + '/sp</div></td>' +
        '<td class="text-right px-2 text-slate-600">' + fmtMoney(p.product_cost != null ? p.product_cost : p.cost_of_goods) + '</td>' +
        '<td class="text-right px-2"><div class="text-slate-600">' + fmtMoney(fees) + '</div>' +
          '<div class="text-[10px] text-slate-400">Promo ' + fmtMoney(p.promo) + '</div></td>' +
        '<td class="text-right px-2 text-slate-600">' + fmtMoney(p.ad_spend != null ? p.ad_spend : p.ads) + '</td>' +
        '<td class="text-right px-2">' + pnl(p.net_profit) + '</td>' +
        '<td class="text-right px-2">' + pnl(p.margin != null ? p.margin : p.margin_pct, true) + '</td></tr>';
    }).join('');
    tbody.innerHTML = html;

    // Dòng tổng (tfoot) — tự tính từ danh sách sản phẩm
    try {
      var t = d.totals || computeTotals(rows);
      if (table) {
        var tfoot = table.querySelector('tfoot');
        if (!tfoot) { tfoot = document.createElement('tfoot'); table.appendChild(tfoot); }
        tfoot.className = 'border-t-2 bg-slate-50 font-semibold';
        tfoot.innerHTML = '<tr>' +
          '<td class="py-2 px-2">Tổng (' + rows.length + ' SKU)</td>' +
          '<td class="text-right px-2">' + fmtNum(t.quantity) + '</td>' +
          '<td class="text-right px-2">' + fmtMoney(t.sales) + '</td>' +
          '<td class="text-right px-2">' + fmtMoney(t.product_cost) + '</td>' +
          '<td class="text-right px-2">' + fmtMoney(t.fees) + '</td>' +
          '<td class="text-right px-2">' + fmtMoney(t.ad_spend) + '</td>' +
          '<td class="text-right px-2">' + pnl(t.net_profit) + '</td>' +
          '<td class="text-right px-2">' + pnl(t.margin, true) + '</td></tr>';
      }
    } catch (e) { /* tfoot lỗi không chặn UI */ }
    return true;
  }

  function removeTfoot(table) {
    try {
      var tfoot = table && table.querySelector('tfoot');
      if (tfoot) tfoot.innerHTML = '';
    } catch (e) { /* bỏ qua */ }
  }

  // ---------- Ghi đè App.loadDashboard ----------
  function install() {
    if (!window.App || typeof window.App.loadDashboard !== 'function') {
      return false; // app.js chưa nạp xong
    }

    window.App.loadDashboard = async function () {
      var sel = document.getElementById('range-select');
      var days = sel ? (parseInt(sel.value, 10) || 30) : 30;
      var tbody = document.getElementById('top-products');
      try {
        if (tbody) {
          tbody.innerHTML = '<tr><td colspan="8" class="py-8 text-center text-slate-400">' +
            'Đang tổng hợp dữ liệu hiệu suất từ Local Database...</td></tr>';
        }

        // start/end theo range-select, tính theo giờ trình duyệt
        var endDate = new Date();
        var startDate = new Date();
        startDate.setDate(endDate.getDate() - (days - 1));
        var iso = function (dt) { return dt.toISOString().slice(0, 10); };

        // 1 lần fetch duy nhất cho bảng Products + thẻ kỳ so sánh (Today/Yesterday/MTD...)
        var results = await Promise.all([
          window.api('/api/analytics/dashboard/summary?tab=products&start=' + iso(startDate) + '&end=' + iso(endDate)),
          typeof this.loadPeriods === 'function' ? this.loadPeriods() : null,
        ]);
        var d = results[0] || {};

        // Backend Phase 3 chưa trả timeseries/marketplace_breakdown -> vẽ chart rỗng,
        // không lỗi (lỗi chart không được chặn bảng).
        try { if (typeof this.drawSales === 'function') this.drawSales(d.timeseries || []); } catch (e) { console.warn('[Phase3] drawSales:', e); }
        try { if (typeof this.drawMarket === 'function') this.drawMarket(d.marketplace_breakdown || {}); } catch (e) { console.warn('[Phase3] drawMarket:', e); }

        renderGrid({ top_products: Array.isArray(d.products) ? d.products : [] });
      } catch (err) {
        console.error('[Phase3] render_performance: lỗi tải dashboard:', err);
        if (tbody) {
          tbody.innerHTML = '<tr><td colspan="8" class="py-8 text-center text-red-500">' +
            'Lỗi tải dữ liệu: ' + esc(err && err.message) + '</td></tr>';
        }
      }
    };
    console.info('[Phase3] render_performance.js đã kích hoạt (ghi đè App.loadDashboard).');
    return true;
  }

  // app.js nạp trước (script tag đứng trước) nên thường install được ngay;
  // phòng hờ thì thử lại sau DOMContentLoaded.
  if (!install()) {
    document.addEventListener('DOMContentLoaded', install);
  }
})();
