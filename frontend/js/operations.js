// Operations dashboard: live KPIs and charts from /api/dashboard.
document.addEventListener('DOMContentLoaded', function () {
  var SVG = 'http://www.w3.org/2000/svg';
  var SERIES = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)'];
  var tooltip = document.getElementById('opsTooltip');
  var farmSelect = document.getElementById('opsFarm');
  var facilitySelect = document.getElementById('opsFacility');
  var message = document.getElementById('opsMessage');
  var locations = [];
  var days = 30;

  // ---- helpers ---------------------------------------------------------------
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function svg(tag, attrs, text) {
    var node = document.createElementNS(SVG, tag);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text != null) node.textContent = text;
    return node;
  }

  function kg(value) {
    var n = Number(value || 0);
    return n.toLocaleString(undefined, { maximumFractionDigits: n >= 100 ? 0 : 1 }) + ' kg';
  }

  function count(value) { return Number(value || 0).toLocaleString(); }

  function niceMax(value) {
    if (value <= 0) return 1;
    var power = Math.pow(10, Math.floor(Math.log10(value)));
    var scaled = value / power;
    var nice = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10;
    return nice * power;
  }

  function day(value, short) {
    var d = new Date(String(value).slice(0, 10) + 'T00:00:00');
    return d.toLocaleDateString(undefined, short ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function showTip(event, title, lines) {
    tooltip.replaceChildren(el('b', null, title));
    lines.forEach(function (line) {
      var row = el('div');
      if (line.color) {
        var dot = el('i');
        dot.style.background = line.color;
        row.appendChild(dot);
      }
      row.appendChild(document.createTextNode(line.text));
      tooltip.appendChild(row);
    });
    tooltip.hidden = false;
    var x = Math.min(event.clientX + 14, window.innerWidth - tooltip.offsetWidth - 8);
    var y = Math.min(event.clientY + 14, window.innerHeight - tooltip.offsetHeight - 8);
    tooltip.style.left = x + 'px';
    tooltip.style.top = y + 'px';
  }

  function hideTip() { tooltip.hidden = true; }

  function table(target, headers, rows) {
    var wrap = el('div', 'b360-table-wrap');
    var t = el('table', 'b360-table');
    var head = el('tr');
    headers.forEach(function (h) { head.appendChild(el('th', null, h)); });
    var thead = el('thead');
    thead.appendChild(head);
    var tbody = el('tbody');
    rows.forEach(function (cells) {
      var tr = el('tr');
      cells.forEach(function (c) { tr.appendChild(el('td', null, c)); });
      tbody.appendChild(tr);
    });
    t.append(thead, tbody);
    wrap.appendChild(t);
    document.getElementById(target).replaceChildren(wrap);
  }

  // ---- horizontal bar chart (single hue) -----------------------------------
  // Charts are drawn at the container's pixel width so text stays 12px.
  function widthOf(target) {
    return Math.max(280, Math.round(document.getElementById(target).clientWidth || 760));
  }

  function hbars(target, rows, format, tipFor) {
    var width = widthOf(target);
    var labelW = Math.min(170, Math.round(width * 0.34)), valueW = 70, rowH = 28, gap = 8;
    var height = rows.length * (rowH + gap);
    // Labelled bars without an axis: scale to the largest value itself.
    var max = Math.max.apply(null, rows.map(function (r) { return r.value; }).concat([0])) || 1;
    var plotW = width - labelW - valueW;
    var root = svg('svg', { viewBox: '0 0 ' + width + ' ' + height, role: 'img' });
    root.appendChild(svg('title', {}, rows.map(function (r) { return r.label + ' ' + format(r.value); }).join(', ')));
    root.appendChild(svg('line', { x1: labelW, x2: labelW, y1: 0, y2: height - gap, stroke: 'var(--axis)', 'stroke-width': 1 }));
    rows.forEach(function (r, i) {
      var y = i * (rowH + gap);
      var w = r.value > 0 ? Math.max(2, (r.value / max) * plotW) : 0;
      root.appendChild(svg('text', { x: labelW - 10, y: y + rowH / 2 + 4, 'text-anchor': 'end' }, r.label));
      if (w > 0) {
        var radius = Math.min(4, w);
        root.appendChild(svg('path', {
          d: 'M' + labelW + ',' + y + 'h' + (w - radius) + 'a' + radius + ',' + radius + ' 0 0 1 ' + radius + ',' + radius +
             'v' + (rowH - 2 * radius) + 'a' + radius + ',' + radius + ' 0 0 1 -' + radius + ',' + radius + 'h-' + (w - radius) + 'z',
          fill: 'var(--bar)'
        }));
      }
      root.appendChild(svg('text', { x: labelW + w + 8, y: y + rowH / 2 + 4, class: 'value-label' }, format(r.value)));
      var hit = svg('rect', { x: 0, y: y - gap / 2, width: width, height: rowH + gap, fill: 'transparent' });
      hit.addEventListener('mousemove', function (event) { showTip(event, r.label, tipFor(r)); });
      hit.addEventListener('mouseleave', hideTip);
      root.appendChild(hit);
    });
    document.getElementById(target).replaceChildren(root);
  }

  // ---- multi-series line chart with crosshair -------------------------------
  function lines(target, buckets, series, weekly) {
    var width = widthOf(target);
    var directLabels = width >= 480; // narrow screens rely on the legend and table
    var height = 260, left = 56, right = directLabels ? 120 : 16, top = 12, bottom = 30;
    var plotW = width - left - right, plotH = height - top - bottom;
    var all = [];
    series.forEach(function (s) { all = all.concat(s.values.map(Number)); });
    var max = niceMax(Math.max.apply(null, all.concat([0])));
    var n = buckets.length;
    function x(i) { return left + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW); }
    function y(v) { return top + plotH - (Number(v) / max) * plotH; }
    var root = svg('svg', { viewBox: '0 0 ' + width + ' ' + height, role: 'img' });
    root.appendChild(svg('title', {}, 'Output over time for ' + series.map(function (s) { return s.name; }).join(', ')));

    for (var g = 0; g <= 4; g++) {
      var gy = top + (g / 4) * plotH;
      root.appendChild(svg('line', { x1: left, x2: left + plotW, y1: gy, y2: gy, stroke: 'var(--grid)', 'stroke-width': 1 }));
      root.appendChild(svg('text', { x: left - 8, y: gy + 4, 'text-anchor': 'end' }, kg(max * (1 - g / 4))));
    }
    var every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(plotW / 72))));
    buckets.forEach(function (b, i) {
      if (i % every === 0 || i === n - 1) {
        root.appendChild(svg('text', { x: x(i), y: height - 8, 'text-anchor': 'middle' }, (weekly ? 'wk ' : '') + day(b, true)));
      }
    });

    var ends = [];
    series.forEach(function (s, si) {
      var d = s.values.map(function (v, i) { return (i ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(v).toFixed(1); }).join('');
      root.appendChild(svg('path', { d: d, fill: 'none', stroke: SERIES[si], 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
      ends.push({ y: y(s.values[n - 1]), name: s.name, color: SERIES[si] });
    });
    // Direct labels at line ends, nudged apart so they never collide.
    ends.sort(function (a, b) { return a.y - b.y; });
    for (var k = 1; k < ends.length; k++) {
      if (ends[k].y - ends[k - 1].y < 15) ends[k].y = ends[k - 1].y + 15;
    }
    if (directLabels) {
      ends.forEach(function (e) {
        root.appendChild(svg('text', { x: left + plotW + 8, y: e.y + 4, class: 'value-label' }, e.name));
      });
    }

    var cross = svg('line', { y1: top, y2: top + plotH, stroke: 'var(--axis)', 'stroke-width': 1, visibility: 'hidden' });
    root.appendChild(cross);
    var markers = series.map(function (s, si) {
      var m = svg('circle', { r: 4, fill: SERIES[si], stroke: '#fff', 'stroke-width': 2, visibility: 'hidden' });
      root.appendChild(m);
      return m;
    });
    var overlay = svg('rect', { x: left, y: top, width: plotW, height: plotH, fill: 'transparent' });
    overlay.addEventListener('mousemove', function (event) {
      var box = root.getBoundingClientRect();
      var px = (event.clientX - box.left) * (width / box.width);
      var i = Math.max(0, Math.min(n - 1, Math.round(((px - left) / plotW) * (n - 1))));
      cross.setAttribute('x1', x(i));
      cross.setAttribute('x2', x(i));
      cross.setAttribute('visibility', 'visible');
      markers.forEach(function (m, si) {
        m.setAttribute('cx', x(i));
        m.setAttribute('cy', y(series[si].values[i]));
        m.setAttribute('visibility', 'visible');
      });
      showTip(event, (weekly ? 'Week of ' : '') + day(buckets[i]), series.map(function (s, si) {
        return { color: SERIES[si], text: s.name + ': ' + kg(s.values[i]) };
      }));
    });
    overlay.addEventListener('mouseleave', function () {
      cross.setAttribute('visibility', 'hidden');
      markers.forEach(function (m) { m.setAttribute('visibility', 'hidden'); });
      hideTip();
    });
    root.appendChild(overlay);
    document.getElementById(target).replaceChildren(root);

    var legend = document.getElementById('trendLegend');
    legend.textContent = '';
    series.forEach(function (s, si) {
      var item = el('li');
      var swatch = el('i');
      swatch.style.background = SERIES[si];
      item.append(swatch, document.createTextNode(s.name));
      legend.appendChild(item);
    });
  }

  // ---- render ----------------------------------------------------------------
  function kpi(label, value, note, href, critical) {
    var tile = el(href ? 'a' : 'div', 'ops-kpi' + (critical ? ' is-critical' : ''));
    if (href) tile.href = href;
    tile.append(el('span', null, label), el('strong', null, value), el('small', null, note));
    return tile;
  }

  var lastData = null;
  var resizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { if (lastData) render(lastData); }, 200);
  });

  function render(data) {
    lastData = data;
    var k = data.kpis;
    var c = data.commercial;
    var period = 'last ' + data.period.days + ' days';
    var tiles = document.getElementById('opsKpis');
    tiles.replaceChildren(
      kpi('Batches in production', count(k.active_batches),
        count(k.ready_for_harvest) + ' ready to harvest · ' + count(k.planned_batches) + ' planned', '/batch-360'),
      kpi('Harvested', kg(k.harvested_kg), 'wet larvae, ' + period),
      kpi('Dried', kg(k.dried_kg), count(k.drying_in_progress) + ' drying batches in progress'),
      kpi('QC pending', count(k.qc_pending), 'drying batches awaiting a decision', '/alerts', k.qc_pending > 0),
      kpi('Available stock', kg(k.stock_available_kg),
        kg(k.stock_reserved_kg) + ' reserved · ' + kg(k.stock_blocked_kg) + ' blocked', '/product-lot', Number(k.stock_blocked_kg) > 0),
      c ? kpi('Open orders', count(c.open_orders),
            kg(c.outstanding_kg) + ' to ship · ' + count(c.overdue_orders) + ' overdue', '/orders', c.overdue_orders > 0)
        : kpi('Open orders', '—', 'Visible to farm-level users'),
      c ? kpi('Delivered', kg(c.delivered_kg), count(c.in_transit) + ' in transit · ' + period, '/orders')
        : kpi('Delivered', '—', 'Visible to farm-level users'),
      kpi('Open alerts', count(data.alerts.critical + data.alerts.warning + data.alerts.info),
        count(data.alerts.critical) + ' critical · ' + count(data.alerts.warning) + ' warning', '/alerts', data.alerts.critical > 0)
    );

    document.getElementById('flowPeriod').textContent = '· ' + period;
    var received = Number(data.flow[0].kg) || 0;
    hbars('flowChart', data.flow.map(function (f) { return { label: f.stage, value: Number(f.kg) }; }), kg, function (r) {
      return [{ text: kg(r.value) }].concat(received && r.label !== 'Waste received'
        ? [{ text: Math.round((r.value / received) * 1000) / 10 + '% of waste received' }] : []);
    });
    table('flowTable', ['Stage', 'Kilograms'], data.flow.map(function (f) { return [f.stage, kg(f.kg)]; }));

    document.getElementById('trendPeriod').textContent = '· ' + (data.trend.weekly ? 'weekly' : 'daily') + ', ' + period;
    lines('trendChart', data.trend.buckets, data.trend.series, data.trend.weekly);
    table('trendTable', ['Period'].concat(data.trend.series.map(function (s) { return s.name; })),
      data.trend.buckets.map(function (b, i) {
        return [(data.trend.weekly ? 'Week of ' : '') + day(b)].concat(data.trend.series.map(function (s) { return kg(s.values[i]); }));
      }));

    var pipeline = data.pipeline.map(function (p) { return { label: p.status.replace(/_/g, ' ').toLowerCase(), value: p.count }; });
    hbars('pipelineChart', pipeline, count, function (r) { return [{ text: count(r.value) + ' batches' }]; });
    table('pipelineTable', ['Status', 'Batches'], pipeline.map(function (p) { return [p.label, count(p.value)]; }));

    var alerts = document.getElementById('opsAlerts');
    alerts.textContent = '';
    if (!data.alerts.top.length) alerts.appendChild(el('p', 'b360-empty', 'No open alerts. Nothing needs attention right now.'));
    data.alerts.top.forEach(function (a) {
      var row = el('a', 'ops-alert is-' + a.severity);
      row.href = a.href || '/alerts';
      row.appendChild(el('i', 'fas ' + (a.severity === 'info' ? 'fa-circle-info' : 'fa-triangle-exclamation')));
      var text = el('div');
      text.append(el('em', null, a.severity), el('strong', null, a.title), el('span', null, a.message));
      row.appendChild(text);
      alerts.appendChild(row);
    });
    document.getElementById('opsUpdated').textContent = 'Updated ' + new Date().toLocaleTimeString();
  }

  async function load() {
    var params = new URLSearchParams({ days: String(days) });
    if (farmSelect.value) params.set('farm_id', farmSelect.value);
    if (facilitySelect.value) params.set('facility_id', facilitySelect.value);
    try {
      var response = await fetch('/api/dashboard?' + params.toString(), { credentials: 'include' });
      var payload = await response.json();
      if (!response.ok) throw new Error(payload.message || 'Could not load the dashboard');
      message.textContent = '';
      render(payload.data);
      try { localStorage.setItem('zehunger.ops', JSON.stringify({ days: days, farm: farmSelect.value })); } catch (e) { /* optional */ }
    } catch (error) {
      message.textContent = error.message;
    }
  }

  function fillFacilities() {
    var seen = {};
    facilitySelect.replaceChildren(new Option('All facilities', ''));
    locations.forEach(function (row) {
      if (!row.facility_id || seen[row.facility_id] || (farmSelect.value && String(row.farm_id) !== farmSelect.value)) return;
      seen[row.facility_id] = true;
      facilitySelect.add(new Option(row.facility_name, row.facility_id));
    });
  }

  document.querySelectorAll('.ops-period button').forEach(function (button) {
    button.addEventListener('click', function () {
      days = Number(button.dataset.days);
      document.querySelectorAll('.ops-period button').forEach(function (b) {
        b.setAttribute('aria-checked', String(b === button));
      });
      load();
    });
  });
  farmSelect.addEventListener('change', function () { fillFacilities(); load(); });
  facilitySelect.addEventListener('change', load);

  (async function init() {
    try {
      var saved = JSON.parse(localStorage.getItem('zehunger.ops') || '{}');
      if ([7, 30, 90].indexOf(saved.days) !== -1) {
        days = saved.days;
        document.querySelectorAll('.ops-period button').forEach(function (b) {
          b.setAttribute('aria-checked', String(Number(b.dataset.days) === days));
        });
      }
    } catch (e) { /* optional */ }
    try {
      var response = await fetch('/api/locations/hierarchy', { credentials: 'include' });
      locations = ((await response.json()).data || []).filter(function (r) { return r.farm_id; });
      var seen = {};
      locations.forEach(function (row) {
        if (!seen[row.farm_id]) {
          seen[row.farm_id] = true;
          farmSelect.add(new Option(row.farm_name, row.farm_id));
        }
      });
      fillFacilities();
    } catch (e) { /* filters stay at "all" */ }
    load();
    setInterval(function () { if (!document.hidden) load(); }, 5 * 60 * 1000);
  })();
});
