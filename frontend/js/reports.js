// Operational reports tab on the analytics page.
document.addEventListener('DOMContentLoaded', function () {
  var keySelect = document.getElementById('reportKey');
  if (!keySelect) return;
  var message = document.getElementById('reportMessage');
  var result = document.getElementById('reportResult');
  var catalog = {};
  var locations = [];
  var current = null; // last successful report response

  // Columns whose values can open a record page.
  var LINKS = {
    production_batch: function (v) { return '/batch-360?ref=' + encodeURIComponent(v); },
    product_lot: function (v) { return '/product-lot?ref=' + encodeURIComponent(v); },
    order_ref: function (v) { return '/orders?ref=' + encodeURIComponent(v); },
    delivery: function (v) { return '/traceability?ref=' + encodeURIComponent(v) + '&type=delivery'; },
    waste_lot: function (v) { return '/traceability?ref=' + encodeURIComponent(v) + '&type=waste_lot'; },
    substrate_batch: function (v) { return '/traceability?ref=' + encodeURIComponent(v) + '&type=substrate_batch'; },
    harvest: function (v) { return '/traceability?ref=' + encodeURIComponent(v) + '&type=harvest'; },
    drying_batch: function (v) { return '/traceability?ref=' + encodeURIComponent(v) + '&type=drying_batch'; }
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function isoDay(offsetDays) {
    var d = new Date();
    d.setDate(d.getDate() + offsetDays);
    return d.toISOString().slice(0, 10);
  }

  function format(column, value) {
    if (value === null || value === undefined || value === '') return '—';
    switch (column.type) {
      case 'kg': return Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 });
      case 'percent': return Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }) + '%';
      case 'money': return Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      case 'number': return Number(value).toLocaleString();
      case 'date': return new Date(String(value).slice(0, 10) + 'T00:00:00').toLocaleDateString();
      case 'datetime': return new Date(value).toLocaleString();
      default: return String(value);
    }
  }

  function numeric(column) {
    return ['kg', 'percent', 'number', 'money'].indexOf(column.type) !== -1;
  }

  async function api(url) {
    var response = await fetch(url, { credentials: 'include' });
    var payload = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(payload.message || 'Request failed');
    return payload;
  }

  function fillFacilities() {
    var farm = document.getElementById('reportFarm').value;
    var facility = document.getElementById('reportFacility');
    var seen = {};
    facility.replaceChildren(new Option('All facilities', ''));
    locations.forEach(function (row) {
      if (!row.facility_id || seen[row.facility_id] || (farm && String(row.farm_id) !== farm)) return;
      seen[row.facility_id] = true;
      facility.add(new Option(row.farm_name + ' / ' + row.facility_name, row.facility_id));
    });
  }

  function applyFilters() {
    var spec = catalog[keySelect.value];
    if (!spec) return;
    document.querySelectorAll('.report-field[data-filter]').forEach(function (field) {
      field.hidden = spec.filters.indexOf(field.dataset.filter) === -1;
    });
    var status = document.getElementById('reportStatus');
    status.replaceChildren(new Option('Any status', ''));
    (spec.statuses || []).forEach(function (value) { status.add(new Option(value.replace(/_/g, ' ').toLowerCase(), value)); });
  }

  function query() {
    var spec = catalog[keySelect.value];
    var params = new URLSearchParams();
    function add(filter, name, id) {
      var value = document.getElementById(id).value;
      if (spec.filters.indexOf(filter) !== -1 && value) params.set(name, value);
    }
    add('dates', 'date_from', 'reportFrom');
    add('dates', 'date_to', 'reportTo');
    add('farm', 'farm_id', 'reportFarm');
    add('facility', 'facility_id', 'reportFacility');
    add('status', 'status', 'reportStatus');
    add('product', 'product_type', 'reportProduct');
    return params;
  }

  function filterSummary(params) {
    var lines = [];
    var from = params.get('date_from'), to = params.get('date_to');
    if (from || to) lines.push('Period: ' + (from || 'start') + ' to ' + (to || 'today'));
    [['reportFarm', 'farm_id', 'Farm'], ['reportFacility', 'facility_id', 'Facility'],
      ['reportStatus', 'status', 'Status']].forEach(function (f) {
      if (params.get(f[1])) {
        var select = document.getElementById(f[0]);
        lines.push(f[2] + ': ' + select.options[select.selectedIndex].text);
      }
    });
    if (params.get('product_type')) lines.push('Product: ' + params.get('product_type'));
    return lines.length ? lines : ['All records you can access'];
  }

  function render(payload, params) {
    var columns = payload.report.columns;
    document.getElementById('reportTitle').textContent = payload.report.title;
    document.getElementById('reportMeta').textContent = filterSummary(params).join(' · ') + ' · ' +
      payload.row_count + ' rows' + (payload.truncated ? ' (first 5,000 shown — narrow the filters)' : '');

    var totals = document.getElementById('reportTotals');
    totals.textContent = '';
    columns.filter(function (c) { return payload.totals[c.key] !== undefined; }).forEach(function (c) {
      var tile = el('div', 'report-total');
      tile.append(el('span', null, c.label), el('strong', null, format(c, payload.totals[c.key])));
      totals.appendChild(tile);
    });

    var table = document.getElementById('reportTable');
    var head = el('tr');
    columns.forEach(function (c) { head.appendChild(el('th', numeric(c) ? 'is-number' : null, c.label)); });
    table.tHead.replaceChildren(head);
    var body = table.tBodies[0];
    body.textContent = '';
    if (!payload.data.length) {
      var empty = el('tr');
      var cell = el('td', null, 'No records match these filters.');
      cell.colSpan = columns.length;
      empty.appendChild(cell);
      body.appendChild(empty);
    }
    payload.data.forEach(function (row) {
      var tr = el('tr');
      columns.forEach(function (c) {
        var td = el('td', numeric(c) ? 'is-number' : null);
        var value = row[c.key];
        if (LINKS[c.key] && value && String(value).indexOf(',') === -1) {
          var link = el('a', null, String(value));
          link.href = LINKS[c.key](value);
          td.appendChild(link);
        } else {
          td.textContent = format(c, value);
        }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    var foot = table.tFoot;
    foot.textContent = '';
    if (Object.keys(payload.totals).length && payload.data.length) {
      var totalRow = el('tr');
      columns.forEach(function (c, index) {
        var value = payload.totals[c.key];
        totalRow.appendChild(el('td', numeric(c) ? 'is-number' : null,
          index === 0 ? 'Total' : value !== undefined ? format(c, value) : ''));
      });
      foot.appendChild(totalRow);
    }
    result.hidden = false;
  }

  async function run() {
    var button = document.getElementById('reportRun');
    var params = query();
    button.disabled = true;
    message.textContent = '';
    try {
      var payload = await api('/api/reports/' + keySelect.value + '?' + params.toString());
      current = { payload: payload, params: params };
      render(payload, params);
      try { localStorage.setItem('zehunger.report', keySelect.value); } catch (error) { /* optional */ }
    } catch (error) {
      result.hidden = true;
      message.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  function exportLines() {
    var lines = filterSummary(current.params);
    var payload = current.payload;
    payload.report.columns.forEach(function (c) {
      if (payload.totals[c.key] !== undefined) lines.push(c.label + ' total: ' + format(c, payload.totals[c.key]));
    });
    return lines;
  }

  document.getElementById('reportCsv').addEventListener('click', function () {
    if (!current) return;
    var params = new URLSearchParams(current.params);
    params.set('format', 'csv');
    window.location.href = '/api/reports/' + current.payload.report.key + '?' + params.toString();
  });
  document.getElementById('reportExcel').addEventListener('click', function () {
    if (!current) return;
    ExportManager.rowsToExcel(current.payload.report.title, current.payload.report.columns,
      current.payload.data, exportLines());
  });
  document.getElementById('reportPdf').addEventListener('click', function () {
    if (!current) return;
    ExportManager.rowsToPDF(current.payload.report.title, current.payload.report.columns,
      current.payload.data, exportLines(), format);
  });

  keySelect.addEventListener('change', function () { applyFilters(); result.hidden = true; });
  document.getElementById('reportFarm').addEventListener('change', fillFacilities);
  document.getElementById('reportRun').addEventListener('click', run);

  document.getElementById('reportFrom').value = isoDay(-30);
  document.getElementById('reportTo').value = isoDay(0);

  (async function init() {
    try {
      var reports = (await api('/api/reports')).data;
      var groups = {};
      reports.forEach(function (r) {
        catalog[r.key] = r;
        if (!groups[r.group]) {
          groups[r.group] = el('optgroup');
          groups[r.group].label = r.group;
          keySelect.appendChild(groups[r.group]);
        }
        groups[r.group].appendChild(new Option(r.title, r.key));
      });
      var remembered = null;
      try { remembered = localStorage.getItem('zehunger.report'); } catch (error) { /* optional */ }
      if (remembered && catalog[remembered]) keySelect.value = remembered;
      applyFilters();
    } catch (error) {
      message.textContent = error.message;
      return;
    }
    try {
      locations = (await api('/api/locations/hierarchy')).data || [];
      var farm = document.getElementById('reportFarm');
      var seen = {};
      locations.forEach(function (row) {
        if (row.farm_id && !seen[row.farm_id]) {
          seen[row.farm_id] = true;
          farm.add(new Option(row.farm_name, row.farm_id));
        }
      });
      fillFacilities();
    } catch (error) { /* filters stay at "all" */ }
    try {
      var stock = await api('/api/inventory');
      (stock.totals || []).forEach(function (t) {
        var option = el('option');
        option.value = t.product_type;
        document.getElementById('reportProducts').appendChild(option);
      });
    } catch (error) { /* suggestions are optional */ }
  })();
});
