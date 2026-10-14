document.addEventListener('DOMContentLoaded', function () {
  var form = document.getElementById('lotLookupForm');
  var referenceInput = document.getElementById('lotLookupRef');
  var message = document.getElementById('lotMessage');
  var content = document.getElementById('lotContent');
  var traceRows = document.getElementById('traceRows');

  function text(id, value) {
    var element = document.getElementById(id);
    if (element) element.textContent = value == null || value === '' ? '—' : String(value);
  }

  function reference(value, businessId, code) {
    var parts = [value, businessId, code].filter(function (part) {
      return part != null && part !== '';
    });
    return parts.length ? parts.join(' · ') : '—';
  }

  function addCell(row, value, numeric) {
    var cell = document.createElement('td');
    if (numeric) cell.className = 'is-num';
    cell.textContent = value == null || value === '' ? '—' : String(value);
    row.appendChild(cell);
  }

  // Quantities are shown right-aligned (see erp-table .is-num).
  function Num(value) { this.value = value; }
  function num(value) { return new Num(value); }

  function renderTrace(lot) {
    var lines = lot.source_chain || [];
    traceRows.textContent = '';
    lines.forEach(function (line) {
      var row = document.createElement('tr');
      addCell(row, reference(lot.drying_output_id, lot.drying_batch_business_id, lot.drying_batch_code));
      addCell(row, reference(line.harvest_code, line.harvest_id,
        line.drying_input_quantity == null ? '' :
          Number(line.drying_input_quantity).toFixed(3) + ' ' + line.drying_input_unit));
      addCell(row, reference(line.production_batch_business_id,
        line.production_batch_code, line.production_batch_id));
      addCell(row, reference(line.substrate_batch_business_id,
        line.substrate_batch_code, line.substrate_batch_id));
      var wasteLot = reference(line.waste_lot_business_id, line.waste_lot_id, line.waste_type);
      if (line.source_name) wasteLot += ' · ' + line.source_name;
      addCell(row, wasteLot);
      traceRows.appendChild(row);
    });
    document.getElementById('traceEmpty').hidden = lines.length !== 0;
  }

  var currentLot = null;

  function kg(value) {
    return value == null || value === '' ? '—' : Number(value).toFixed(3) + ' kg';
  }

  function when(value) {
    return value ? new Date(value).toLocaleString() : '—';
  }

  function place(code, name) {
    return code ? name + ' (' + code + ')' : '';
  }

  function fillTable(bodyId, emptyId, rows, cells) {
    var body = document.getElementById(bodyId);
    body.textContent = '';
    rows.forEach(function (item) {
      var row = document.createElement('tr');
      cells(item).forEach(function (value) {
        if (value instanceof Node) {
          var cell = document.createElement('td');
          cell.appendChild(value);
          row.appendChild(cell);
        } else if (value instanceof Num) {
          addCell(row, value.value, true);
        } else {
          addCell(row, value);
        }
      });
      body.appendChild(row);
    });
    document.getElementById(emptyId).hidden = rows.length !== 0;
  }

  function renderInventory(lot) {
    var inventory = lot.inventory || { balances: [], movements: [], on_hand_kg: 0 };
    text('lotOnHand', kg(inventory.on_hand_kg) + ' on hand');
    fillTable('lotBalanceRows', 'lotBalanceEmpty', inventory.balances, function (item) {
      return [place(item.location_code, item.location_name), item.facility_name,
        num(kg(item.quantity_kg)), num(kg(item.reserved_kg)), num(kg(item.free_kg)), when(item.last_movement_at)];
    });
    fillTable('lotMovementRows', 'lotMovementEmpty', inventory.movements, function (item) {
      return [item.business_id, ErpUI.humanize(item.movement_type), num(kg(item.quantity_kg)),
        place(item.from_location_code, item.from_location_name),
        place(item.to_location_code, item.to_location_name),
        when(item.occurred_at), item.recorded_by,
        [item.reason, item.notes].filter(Boolean).join(' · ')];
    });
  }

  async function loadMovementLocations(lot) {
    var selects = [document.getElementById('movementFrom'), document.getElementById('movementTo')];
    try {
      var response = await fetch('/api/inventory/locations?farm_id=' + encodeURIComponent(lot.farm_id), {
        credentials: 'include'
      });
      var result = await response.json();
      if (!response.ok) throw new Error(result.message || 'Could not load inventory locations.');
      selects.forEach(function (select) {
        select.replaceChildren(new Option('Select location', ''));
        (result.data || []).forEach(function (location) {
          select.add(new Option(location.facility_name + ' — ' + place(location.location_code, location.name), location.id));
        });
      });
    } catch (error) {
      selects.forEach(function (select) {
        select.replaceChildren(new Option('Locations unavailable', ''));
      });
    }
  }

  function syncMovementFields() {
    var type = document.getElementById('movementType').value;
    var needsFrom = type !== 'ADJUSTMENT_IN';
    var needsTo = type === 'TRANSFER' || type === 'ADJUSTMENT_IN';
    document.getElementById('movementFromField').hidden = !needsFrom;
    document.getElementById('movementToField').hidden = !needsTo;
    document.getElementById('movementFrom').required = needsFrom;
    document.getElementById('movementTo').required = needsTo;
    document.getElementById('movementReason').required = type !== 'TRANSFER';
  }

  async function loadStock() {
    try {
      var response = await fetch('/api/inventory', { credentials: 'include' });
      var result = await response.json();
      if (!response.ok) throw new Error(result.message || 'Could not load stock.');
      var totals = document.getElementById('stockTotals');
      totals.textContent = '';
      (result.totals || []).forEach(function (total) {
        var card = ErpUI.el('div', 'erp-kpi');
        card.append(ErpUI.el('span', null, ErpUI.humanize(total.product_type) + ' available'),
          ErpUI.el('strong', null, kg(total.available_kg)));
        totals.appendChild(card);
      });
      totals.hidden = !totals.children.length;
      fillTable('stockRows', 'stockEmpty', result.data || [], function (item) {
        var link = document.createElement('button');
        link.type = 'button';
        link.className = 'lot-link';
        link.textContent = item.business_id;
        link.addEventListener('click', function () { load(item.business_id); });
        return [ErpUI.humanize(item.product_type), link,
          item.facility_name + ' — ' + place(item.location_code, item.location_name),
          num(kg(item.quantity_kg)), ErpUI.badge(item.lot_status), when(item.last_movement_at)];
      });
    } catch (error) {
      var stockEmpty = document.getElementById('stockEmpty');
      stockEmpty.hidden = false;
      stockEmpty.replaceWith(Object.assign(ErpUI.state('error', {
        title: 'Stock could not be loaded', text: error.message, actionLabel: 'Try again', onAction: loadStock
      }), { id: 'stockEmpty' }));
    }
  }

  function render(lot) {
    currentLot = lot;
    text('lotBusinessId', lot.business_id);
    text('lotNumber', 'Lot number ' + (lot.lot_code || '—'));
    text('lotProductType', ErpUI.humanize(lot.product_type));
    text('lotQuantity', Number(lot.quantity).toFixed(3) + ' ' + lot.unit);
    text('lotProductionDate', lot.production_date);
    text('lotFarm', lot.farm_name);
    text('lotQcStatus', ErpUI.humanize(lot.qc_status));
    text('lotApprovalStatus', ErpUI.humanize(lot.approval_status));
    text('lotStorageLocation', lot.storage_location || 'Not recorded');
    text('lotReleasedBy', lot.released_by);
    document.getElementById('lotStatus').replaceWith(Object.assign(ErpUI.badge(lot.status), { id: 'lotStatus' }));
    renderTrace(lot);
    document.getElementById('lotLabelLink').href =
      '/labels?type=product_lot&ref=' + encodeURIComponent(lot.business_id);
    document.getElementById('lotTraceLink').href =
      '/traceability?ref=' + encodeURIComponent(lot.business_id) + '&type=product_lot';
    renderInventory(lot);
    loadMovementLocations(lot);
    content.hidden = false;
  }

  var movementForm = document.getElementById('movementForm');
  var movementMessage = document.getElementById('movementMessage');
  document.getElementById('movementType').addEventListener('change', syncMovementFields);
  syncMovementFields();
  // Write-offs and adjustments are for roles with inventory.adjust (managers).
  (window.currentUser || Promise.resolve(null)).then(function (profile) {
    var canAdjust = !!profile && (profile.permissions || []).indexOf('inventory.adjust') !== -1;
    document.querySelectorAll('#movementType option[data-adjust]').forEach(function (option) {
      option.hidden = option.disabled = !canAdjust;
    });
  });

  movementForm.addEventListener('submit', async function (event) {
    event.preventDefault();
    if (!currentLot) return;
    var type = document.getElementById('movementType').value;
    var payload = {
      product_lot_id: currentLot.business_id,
      movement_type: type,
      quantity_kg: document.getElementById('movementQuantity').value,
      unit: 'kg',
      reason: document.getElementById('movementReason').value
    };
    if (!document.getElementById('movementFromField').hidden) {
      payload.from_location_id = document.getElementById('movementFrom').value;
    }
    if (!document.getElementById('movementToField').hidden) {
      payload.to_location_id = document.getElementById('movementTo').value;
    }
    if (type !== 'TRANSFER' && type !== 'ADJUSTMENT_IN') {
      var confirmed = await ErpUI.confirm({
        title: (type === 'WASTAGE' ? 'Write off ' : 'Remove ') + payload.quantity_kg + ' kg of ' + currentLot.business_id + '?',
        text: 'This takes the stock out of the ledger. It is recorded with your name and reason and cannot be deleted.',
        confirmLabel: type === 'WASTAGE' ? 'Write off stock' : 'Post adjustment',
        danger: true
      });
      if (!confirmed) return;
    }
    var submit = movementForm.querySelector('button[type="submit"]');
    ErpUI.message(movementMessage, '');
    try {
      var response = await ErpUI.busy(submit, fetch('/api/inventory/movements', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload)
      }));
      var result = await response.json();
      if (!response.ok) throw new Error(result.message || result.error || 'Movement was not posted.');
      ErpUI.message(movementMessage, result.data.business_id + ' posted.', 'success');
      movementForm.reset();
      syncMovementFields();
      currentLot.inventory = result.data.inventory;
      renderInventory(currentLot);
      loadStock();
    } catch (error) {
      ErpUI.message(movementMessage, error.message, 'danger');
    }
  });

  async function load(referenceValue) {
    var lookup = String(referenceValue || '').trim();
    if (!lookup) return;
    ErpUI.message(message, 'Loading product lot…', 'info');
    content.hidden = true;
    try {
      var response = await fetch('/api/product-lots/' + encodeURIComponent(lookup), {
        credentials: 'include'
      });
      var result = await response.json();
      if (!response.ok) throw new Error(result.message || 'Could not load Product Lot.');
      render(result.data);
      ErpUI.message(message, '');
      referenceInput.value = lookup;
      history.replaceState(null, '', '/product-lot?ref=' + encodeURIComponent(lookup));
    } catch (error) {
      ErpUI.message(message, error.message, 'danger');
    }
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    load(referenceInput.value);
  });

  ErpUI.loading(document.getElementById('stockTotals'), 'Loading stock…', true);
  loadStock();
  var initialReference = new URLSearchParams(window.location.search).get('ref');
  if (initialReference) load(initialReference);
});