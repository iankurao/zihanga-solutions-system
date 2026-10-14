document.addEventListener('DOMContentLoaded', function () {
  var picker = document.getElementById('b360Picker');
  var select = document.getElementById('b360BatchSelect');
  var message = document.getElementById('b360Message');
  var content = document.getElementById('b360Content');
  var welcome = document.getElementById('b360Empty');

  // ---- small DOM helpers (all text is set with textContent) ---------------
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function setText(id, value) {
    document.getElementById(id).textContent = value == null || value === '' ? '—' : String(value);
  }

  function num(value, digits) {
    if (value == null || value === '') return '—';
    return Number(value).toLocaleString(undefined, {
      minimumFractionDigits: digits == null ? 0 : digits,
      maximumFractionDigits: digits == null ? 3 : digits
    });
  }

  function kg(value) {
    return value == null ? '—' : num(value) + ' kg';
  }

  function pct(value) {
    return value == null ? '—' : num(value, 1) + '%';
  }

  function day(value) {
    if (!value) return '—';
    var date = new Date(value.length === 10 ? value + 'T00:00:00' : value);
    return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function moment(value) {
    if (!value) return '—';
    return new Date(value).toLocaleString(undefined, {
      day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'
    });
  }

  // Status codes such as READY_FOR_HARVEST read better as words.
  function label(value) {
    return value == null ? '—' : String(value).replace(/_/g, ' ');
  }

  function count(n, singular, plural) {
    return n + ' ' + (n === 1 ? singular : plural || singular + 's');
  }

  function empty(text) {
    return ErpUI.state('empty', { text: text, compact: true });
  }

  function facts(pairs) {
    var list = el('dl', 'erp-facts');
    pairs.forEach(function (pair) {
      var item = el('div');
      item.append(el('dt', null, pair[0]), el('dd', null, pair[1] == null || pair[1] === '' ? '—' : pair[1]));
      list.appendChild(item);
    });
    return list;
  }

  function table(headers, rows) {
    return ErpUI.table(headers, rows);
  }

  // Status badge with the ERP-wide colour meaning (see js/ui.js).
  function pill(status) {
    return ErpUI.badge(status);
  }

  function body(name) {
    var node = document.querySelector('[data-body="' + name + '"]');
    node.textContent = '';
    return node;
  }

  function subtitle(text) {
    return el('p', 'erp-subhead', text);
  }

  // ---- sections ------------------------------------------------------------
  function renderHeader(data) {
    var batch = data.batch;
    setText('b360BatchId', batch.business_id || batch.batch_code);
    var status = document.getElementById('b360Status');
    status.replaceWith(Object.assign(ErpUI.badge(batch.status), { id: 'b360Status' }));
    setText('b360Farm', [batch.farm_name, batch.site_name].filter(Boolean).join(' / ') || 'Unassigned (legacy)');
    setText('b360Facility', batch.facility_name || 'Unassigned (legacy)');
    setText('b360Started', day(batch.started_at || batch.start_date));
    setText('b360Age', batch.age_days == null ? '—' : batch.age_days + (batch.age_days === 1 ? ' day' : ' days'));
    document.title = (batch.business_id || 'Batch') + ' · Batch 360 | Zehunger';
    document.getElementById('b360LabelLink').href =
      '/labels?type=production_batch&ref=' + encodeURIComponent(batch.business_id || batch.id);
    document.getElementById('b360OperationalLink').href =
      '/production_batch.html?batch=' + encodeURIComponent(batch.business_id || batch.id);

    var stages = document.getElementById('b360Stages');
    stages.textContent = '';
    data.stages.forEach(function (stage) {
      var item = el('li', 'b360-stage' + (stage.done ? ' is-done' : ''));
      var dot = el('span', 'b360-stage-dot');
      dot.appendChild(el('i', 'fas fa-check'));
      item.append(dot, el('span', null, stage.label));
      item.title = stage.done ? 'Recorded' : 'Not yet recorded';
      stages.appendChild(item);
    });

    var kpis = document.getElementById('b360Kpis');
    kpis.textContent = '';
    [
      ['Substrate issued', kg(data.source.substrate_issued_kg), count(data.source.substrate_batches.length, 'substrate batch', 'substrate batches')],
      ['Wet harvest', kg(data.harvest.total_wet_kg), count(data.harvest.count, 'harvest event')],
      ['Dry output', kg(data.processing.dry_output_kg), count(data.processing.drying_batches.length, 'drying batch', 'drying batches')],
      ['Drying yield', pct(dryingYield(data.processing)), 'dry ÷ wet into drying'],
      ['Available stock', kg(data.inventory.available_kg), count(data.product_lots.length, 'product lot')]
    ].forEach(function (kpi) {
      var tile = el('div', 'b360-kpi');
      tile.append(el('span', null, kpi[0]), el('strong', null, kpi[1]), el('small', null, kpi[2]));
      kpis.appendChild(tile);
    });
  }

  function dryingYield(processing) {
    var input = processing.drying_batches.reduce(function (sum, row) { return sum + Number(row.total_input_kg || 0); }, 0);
    var output = processing.drying_batches.reduce(function (sum, row) { return sum + Number(row.total_output_kg || 0); }, 0);
    var hasOutput = processing.drying_batches.some(function (row) { return row.outputs.length; });
    return hasOutput && input ? (output / input) * 100 : null;
  }

  function renderSource(data) {
    var target = body('source');
    var substrates = data.source.substrate_batches;
    if (!substrates.length) {
      target.appendChild(empty('No substrate has been issued to this batch.'));
      return;
    }
    target.appendChild(facts([
      ['Substrate issued', kg(data.source.substrate_issued_kg)],
      ['Substrate batches', substrates.length],
      ['Waste lots', substrates.reduce(function (n, s) { return n + s.waste_lots.length; }, 0)]
    ]));
    substrates.forEach(function (substrate) {
      target.appendChild(subtitle(substrate.business_id + ' · ' + kg(substrate.quantity_issued) + ' issued · prepared ' + day(substrate.preparation_date)));
      if (!substrate.waste_lots.length) {
        target.appendChild(empty('No waste lot inputs are recorded for this substrate batch.'));
        return;
      }
      target.appendChild(table(
        ['Waste lot', 'Source', 'Waste type', 'Collected', 'Used in substrate batch'],
        substrate.waste_lots.map(function (lot) {
          return [lot.business_id, lot.source_name, lot.waste_type, day(lot.collection_date), kg(lot.quantity_used)];
        })
      ));
    });
  }

  function renderProduction(data) {
    var target = body('production');
    var p = data.production;
    var expected = p.expected_harvest_at
      ? day(p.expected_harvest_at) + (p.days_to_expected_harvest == null ? '' :
        p.days_to_expected_harvest >= 0 ? ' (in ' + p.days_to_expected_harvest + ' d)' :
          ' (' + Math.abs(p.days_to_expected_harvest) + ' d ago)')
      : 'Not set';
    target.appendChild(facts([
      ['Lifecycle status', label(p.status)],
      ['Production stage', label(p.current_stage)],
      ['Start date', day(p.start_date)],
      ['Current duration', p.age_days == null ? '—' : p.age_days + ' days'],
      ['Expected harvest', expected],
      ['Harvest limit', kg(data.harvest.harvest_limit_kg)]
    ]));
  }

  function renderOperations(data) {
    var target = body('operations');
    var ops = data.operations;
    var grid = el('div', 'b360-ops');

    function tile(icon, title, big, lines) {
      var box = el('div', 'b360-op');
      var heading = el('h4');
      heading.append(el('i', 'fas ' + icon), document.createTextNode(title));
      box.append(heading, el('p', 'b360-op-big', big));
      lines.forEach(function (line) { box.appendChild(el('p', null, line)); });
      return box;
    }

    var latest = ops.monitoring.latest;
    grid.append(
      tile('fa-utensils', 'Feeding', count(ops.feeding.count, 'event'), [
        kg(ops.feeding.total_offered_kg) + ' feed offered',
        ops.feeding.feed_types.length ? 'Feed: ' + ops.feeding.feed_types.join(', ') : 'No feed types recorded',
        'Last: ' + moment(ops.feeding.last_at)
      ]),
      tile('fa-temperature-half', 'Monitoring', count(ops.monitoring.count, 'reading'), latest ? [
        'Latest: ' + num(latest.temperature, 1) + ' °C · ' + num(latest.humidity, 1) + '% RH',
        'Range: ' + num(ops.monitoring.temperature_min, 1) + '–' + num(ops.monitoring.temperature_max, 1) + ' °C',
        'Last: ' + moment(latest.occurred_at)
      ] : ['No environmental readings recorded']),
      tile('fa-kit-medical', 'Health', count(ops.health.count, 'intervention'), [
        ops.health.open_count ? ops.health.open_count + ' open or awaiting follow-up' : 'No open issues',
        ops.health.items.length ? 'Latest: ' + ops.health.items[0].observed_issue : 'No interventions recorded'
      ])
    );
    target.appendChild(grid);
    if (ops.health.items.length) {
      target.appendChild(subtitle('Health interventions'));
      target.appendChild(table(
        ['When', 'Issue', 'Severity', 'Action', 'Status'],
        ops.health.items.map(function (item) {
          return [moment(item.occurred_at), item.observed_issue, pill(item.severity),
            item.action_taken, pill(item.health_status)];
        })
      ));
    }
  }

  function renderHarvest(data) {
    var target = body('harvest');
    var h = data.harvest;
    if (!h.count) {
      target.appendChild(empty('No harvest has been recorded for this batch yet.'));
      return;
    }
    target.appendChild(facts([
      ['Total wet harvest', kg(h.total_wet_kg)],
      ['Harvest dates', h.first_at === h.last_at ? day(h.first_at) : day(h.first_at) + ' – ' + day(h.last_at)],
      ['Harvest per kg substrate', pct(h.substrate_conversion_percent)],
      ['Harvest limit used', pct(h.limit_used_percent)]
    ]));
    target.appendChild(table(
      ['Harvest', 'When', 'Wet weight', 'Stage', 'Operator'],
      h.items.map(function (item) {
        return [item.harvest_code, moment(item.occurred_at), kg(item.quantity), item.harvest_stage, item.operator];
      })
    ));
  }

  function renderProcessing(data) {
    var target = body('processing');
    var proc = data.processing;
    if (!proc.drying_batches.length) {
      target.appendChild(empty('No harvest from this batch has entered drying yet.'));
      return;
    }
    target.appendChild(facts([
      ['Wet input from this batch', kg(proc.wet_input_kg)],
      ['Dry output', kg(proc.dry_output_kg)],
      ['Yield', pct(dryingYield(proc))]
    ]));
    target.appendChild(table(
      ['Drying batch', 'Status', 'Method', 'Wet in', 'Dry out', 'Moisture', 'Yield'],
      proc.drying_batches.map(function (row) {
        return [row.business_id || row.batch_code, pill(row.status), row.drying_method,
          kg(row.total_input_kg), row.outputs.length ? kg(row.total_output_kg) : 'Not recorded',
          pct(row.output_moisture_percent), pct(row.yield_percent)];
      })
    ));
    if (proc.any_shared) {
      target.appendChild(el('div', 'erp-alert is-warning',
        'At least one drying batch also contains harvest from other production batches. Output and yield are shown for the whole drying batch, not split by source.'));
    }
  }

  function renderQuality(data) {
    var target = body('quality');
    if (!data.quality.length) {
      target.appendChild(empty('No quality check has been recorded on this batch\'s drying output.'));
      return;
    }
    target.appendChild(table(
      ['Check', 'Result', 'Moisture', 'Inspector', 'Decision', 'Approver', 'Decided'],
      data.quality.map(function (q) {
        return [q.check_code, pill(q.check_status), pct(q.moisture_percent), q.inspector,
          q.decision ? pill(q.decision) : pill('Awaiting decision'),
          q.approver, moment(q.decided_at)];
      })
    ));
  }

  function lotLink(businessId) {
    var link = el('a', 'erp-link', businessId);
    link.href = '/product-lot?ref=' + encodeURIComponent(businessId);
    return link;
  }

  function renderProduct(data) {
    var target = body('product');
    if (!data.product_lots.length) {
      target.appendChild(empty('No product lot has been released from this batch.'));
      return;
    }
    target.appendChild(table(
      ['Product lot', 'Product', 'Released', 'On hand', 'Status'],
      data.product_lots.map(function (lot) {
        return [lotLink(lot.business_id), lot.product_type, kg(lot.quantity_kg), kg(lot.on_hand_kg),
          pill(lot.status)];
      })
    ));
  }

  function renderInventory(data) {
    var target = body('inventory');
    var inv = data.inventory;
    if (!inv.movements.length) {
      target.appendChild(empty('Nothing from this batch has been received into inventory.'));
      return;
    }
    target.appendChild(facts([
      ['Current stock', kg(inv.on_hand_kg)],
      ['Available (QC released)', kg(inv.available_kg)],
      ['Storage locations', inv.balances.length],
      ['Movements', inv.movements.length]
    ]));
    if (inv.balances.length) {
      target.appendChild(subtitle('Stock by location'));
      target.appendChild(table(
        ['Product lot', 'Location', 'Facility', 'On hand', 'Last movement'],
        inv.balances.map(function (row) {
          return [row.product_lot_business_id, row.location_name + ' (' + row.location_code + ')',
            row.facility_name, kg(row.quantity_kg), moment(row.last_movement_at)];
        })
      ));
    }
    target.appendChild(subtitle('Movement history'));
    target.appendChild(table(
      ['Movement', 'Type', 'Quantity', 'From', 'To', 'When', 'By'],
      inv.movements.slice().reverse().map(function (row) {
        return [row.business_id, row.movement_type, kg(row.quantity_kg), row.from_location_name,
          row.to_location_name, moment(row.occurred_at), row.recorded_by];
      })
    ));
  }

  function renderTraceability(data) {
    var target = body('traceability');
    var up = data.traceability.upstream;
    var down = data.traceability.downstream;
    target.appendChild(el('p', 'b360-direction',
      'Upstream sources on the left, downstream outputs on the right. Every link is a stored database relationship.'));
    var chain = el('div', 'b360-chain');

    function node(title, items, extraClass) {
      var box = el('div', 'b360-node' + (extraClass ? ' ' + extraClass : (items.length ? '' : ' is-missing')));
      box.appendChild(el('h5', null, title));
      var list = el('ul');
      (items.length ? items : ['Not yet recorded']).forEach(function (text) { list.appendChild(el('li', null, text)); });
      box.appendChild(list);
      return box;
    }

    function commercialNode(commercial) {
      if (!commercial || commercial.restricted) {
        var hidden = node('Customers', [], 'is-missing');
        hidden.querySelector('li').textContent = 'Visible to farm-level users only';
        return hidden;
      }
      return node('Customers', commercial.orders.map(function (o) {
        return o.business_id + ' · ' + o.customer_name + ' · ' + kg(o.committed_kg);
      }).concat(commercial.deliveries.map(function (d) {
        return d.business_id + ' · ' + label(d.status) + ' · ' + kg(d.quantity_kg);
      })));
    }

    var nodes = [
      node('Waste lots', up.waste_lots.map(function (w) { return w.business_id + ' · ' + w.source_name; })),
      node('Substrate', up.substrate_batches.map(function (s) { return s.business_id + ' · ' + kg(s.quantity_issued); })),
      node('Production batch', [data.batch.business_id + ' · ' + label(data.batch.status)], 'is-current'),
      node('Harvest', down.harvests.map(function (h) { return h.harvest_code + ' · ' + kg(h.wet_kg); })),
      node('Drying', down.drying_batches.map(function (d) { return (d.business_id || '—') + ' · ' + kg(d.output_kg); })),
      node('Product lots', down.product_lots.map(function (p) { return p.business_id + ' · ' + label(p.status); })),
      node('Inventory', down.locations),
      commercialNode(down.commercial)
    ];
    nodes.forEach(function (item, index) {
      if (index) {
        var arrow = el('span', 'b360-arrow');
        arrow.appendChild(el('i', 'fas fa-chevron-right'));
        chain.appendChild(arrow);
      }
      chain.appendChild(item);
    });
    target.appendChild(chain);
    var full = el('a', 'erp-link', 'Open full traceability for ' + data.batch.business_id + ' →');
    full.href = '/traceability?ref=' + encodeURIComponent(data.batch.business_id) + '&type=production_batch';
    var line = el('p', 'b360-direction');
    line.appendChild(full);
    target.appendChild(line);
  }

  function renderAudit(data) {
    var target = body('audit');
    if (!data.audit.length) {
      target.appendChild(empty('No lifecycle changes recorded.'));
      return;
    }
    var list = el('ol', 'b360-timeline');
    data.audit.slice().reverse().forEach(function (entry) {
      var item = el('li');
      item.dataset.kind = entry.kind;
      var when = el('time', null, moment(entry.at));
      when.dateTime = entry.at;
      var what = el('div');
      what.appendChild(el('strong', null, entry.title));
      var detail = [entry.actor ? 'by ' + entry.actor : '', entry.detail || ''].filter(Boolean).join(' · ');
      if (detail) what.appendChild(el('span', null, detail));
      item.append(when, what);
      list.appendChild(item);
    });
    target.appendChild(list);
  }

  function renderAlerts(data) {
    var target = document.getElementById('b360Alerts');
    target.textContent = '';
    var alerts = data.alerts || [];
    target.hidden = !alerts.length;
    alerts.forEach(function (alert) {
      var item = el('a', 'b360-alert is-' + alert.severity);
      item.href = '/alerts';
      item.appendChild(el('i', 'fas fa-triangle-exclamation'));
      var text = el('span');
      text.append(el('strong', null, alert.title), document.createTextNode(' — ' + alert.message));
      item.appendChild(text);
      if (alert.status !== 'OPEN') item.appendChild(el('em', null, label(alert.status).toLowerCase()));
      target.appendChild(item);
    });
  }

  function render(data) {
    renderHeader(data);
    renderAlerts(data);
    renderSource(data);
    renderProduction(data);
    renderOperations(data);
    renderHarvest(data);
    renderProcessing(data);
    renderQuality(data);
    renderProduct(data);
    renderInventory(data);
    renderTraceability(data);
    renderAudit(data);
    welcome.hidden = true;
    content.hidden = false;
  }

  // ---- loading -------------------------------------------------------------
  async function load(reference) {
    var ref = String(reference || '').trim();
    if (!ref) return;
    ErpUI.message(message, 'Loading batch…', 'info');
    try {
      var response = await fetch('/api/production/batches/' + encodeURIComponent(ref) + '/360', {
        credentials: 'include'
      });
      var result = await response.json();
      if (!response.ok) throw new Error(result.message || result.error || 'Could not load this batch.');
      render(result.data);
      ErpUI.message(message, '');
      if ([].some.call(select.options, function (option) { return option.value === ref; })) select.value = ref;
      history.replaceState(null, '', '/batch-360?ref=' + encodeURIComponent(ref));
    } catch (error) {
      ErpUI.message(message, error.message, 'danger');
    }
  }

  async function loadBatchList() {
    try {
      var response = await fetch('/api/production/batches', { credentials: 'include' });
      var result = await response.json();
      if (!response.ok) throw new Error(result.message || 'Could not load batches.');
      var rows = result.data || [];
      select.replaceChildren(new Option(rows.length ? 'Select a production batch' : 'No production batches yet', ''));
      rows.forEach(function (row) {
        var text = (row.business_id || row.batch_code) + ' · ' + label(row.status) +
          (row.facility_name ? ' · ' + row.facility_name : '');
        select.add(new Option(text, row.business_id || String(row.id)));
      });
    } catch (error) {
      select.replaceChildren(new Option('Batches could not be loaded', ''));
    }
  }

  picker.addEventListener('submit', function (event) {
    event.preventDefault();
    load(select.value);
  });
  select.addEventListener('change', function () { load(select.value); });

  loadBatchList().then(function () {
    var initial = new URLSearchParams(window.location.search).get('ref');
    if (initial) load(initial);
  });
});
