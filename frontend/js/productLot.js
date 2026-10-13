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

  function addCell(row, value) {
    var cell = document.createElement('td');
    cell.textContent = value == null || value === '' ? '—' : String(value);
    row.appendChild(cell);
  }

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
        kg(item.quantity_kg), when(item.last_movement_at)];
    });
    fillTable('lotMovementRows', 'lotMovementEmpty', inventory.movements, function (item) {
      return [item.business_id, item.movement_type, kg(item.quantity_kg),
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
        var card = document.createElement('div');
        card.className = 'stock-total';
        var label = document.createElement('span');
        label.textContent = total.product_type;
        var value = document.createElement('strong');
        value.textContent = kg(total.available_kg) + ' available';
        card.append(label, value);
        totals.appendChild(card);
      });
      fillTable('stockRows', 'stockEmpty', result.data || [], function (item) {
        var link = document.createElement('button');
        link.type = 'button';
        link.className = 'lot-link';
        link.textContent = item.business_id;
        link.addEventListener('click', function () { load(item.business_id); });
        return [item.product_type, link,
          item.facility_name + ' — ' + place(item.location_code, item.location_name),
          kg(item.quantity_kg), item.lot_status, when(item.last_movement_at)];
      });
    } catch (error) {
      document.getElementById('stockEmpty').hidden = false;
      document.getElementById('stockEmpty').textContent = error.message;
    }
  }

  function render(lot) {
    currentLot = lot;
    text('lotBusinessId', lot.business_id);
    text('lotNumber', 'Lot number ' + (lot.lot_code || '—'));
    text('lotProductType', lot.product_type);
    text('lotQuantity', Number(lot.quantity).toFixed(3) + ' ' + lot.unit);
    text('lotProductionDate', lot.production_date);
    text('lotFarm', lot.farm_name);
    text('lotQcStatus', lot.qc_status);
    text('lotApprovalStatus', lot.approval_status);
    text('lotStorageLocation', lot.storage_location || 'Not recorded');
    text('lotReleasedBy', lot.released_by);
    var status = document.getElementById('lotStatus');
    status.textContent = lot.status;
    status.className = 'lot-status lot-status-' + String(lot.status).toLowerCase();
    renderTrace(lot);
    renderInventory(lot);
    loadMovementLocations(lot);
    content.hidden = false;
  }

  var movementForm = document.getElementById('movementForm');
  var movementMessage = document.getElementById('movementMessage');
  document.getElementById('movementType').addEventListener('change', syncMovementFields);
  syncMovementFields();

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
    movementMessage.className = 'movement-message';
    movementMessage.textContent = 'Posting movement…';
    try {
      var response = await fetch('/api/inventory/movements', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload)
      });
      var result = await response.json();
      if (!response.ok) throw new Error(result.message || result.error || 'Movement was not posted.');
      movementMessage.className = 'movement-message is-success';
      movementMessage.textContent = result.data.business_id + ' posted.';
      movementForm.reset();
      syncMovementFields();
      currentLot.inventory = result.data.inventory;
      renderInventory(currentLot);
      loadStock();
    } catch (error) {
      movementMessage.className = 'movement-message is-error';
      movementMessage.textContent = error.message;
    }
  });

  async function load(referenceValue) {
    var lookup = String(referenceValue || '').trim();
    if (!lookup) return;
    message.textContent = 'Loading Product Lot…';
    content.hidden = true;
    try {
      var response = await fetch('/api/product-lots/' + encodeURIComponent(lookup), {
        credentials: 'include'
      });
      var result = await response.json();
      if (!response.ok) throw new Error(result.message || 'Could not load Product Lot.');
      render(result.data);
      message.textContent = '';
      referenceInput.value = lookup;
      history.replaceState(null, '', '/product-lot?ref=' + encodeURIComponent(lookup));
    } catch (error) {
      message.textContent = error.message;
    }
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    load(referenceInput.value);
  });

  loadStock();
  var initialReference = new URLSearchParams(window.location.search).get('ref');
  if (initialReference) load(initialReference);
});