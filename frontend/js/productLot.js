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

  function render(lot) {
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
    content.hidden = false;
  }

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

  var initialReference = new URLSearchParams(window.location.search).get('ref');
  if (initialReference) load(initialReference);
});