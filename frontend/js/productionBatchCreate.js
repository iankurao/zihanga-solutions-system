// "New production batch" form on the Production Batch page.
document.addEventListener('DOMContentLoaded', function () {
  var card = document.getElementById('newBatchCard');
  var form = document.getElementById('newBatchForm');
  if (!card || !form) return;
  var farm = document.getElementById('nbFarm');
  var site = document.getElementById('nbSite');
  var facility = document.getElementById('nbFacility');
  var substrateBox = document.getElementById('nbSubstrate');
  var unitsBox = document.getElementById('nbUnits');
  var message = document.getElementById('nbMessage');
  var rows = [];
  var substrates = [];

  function option(select, items, idKey, nameKey, placeholder) {
    var previous = select.value;
    var seen = {};
    select.replaceChildren(new Option(placeholder, ''));
    items.forEach(function (row) {
      if (row[idKey] != null && !seen[row[idKey]]) {
        seen[row[idKey]] = true;
        select.add(new Option(row[nameKey], row[idKey]));
      }
    });
    if ([].some.call(select.options, function (o) { return o.value === previous && previous; })) select.value = previous;
  }

  function renderPickers() {
    option(farm, rows, 'farm_id', 'farm_name', 'Select farm');
    var sites = rows.filter(function (r) { return String(r.farm_id) === farm.value; });
    option(site, sites, 'site_id', 'site_name', farm.value ? 'Select site' : 'Select a farm first');
    var facilities = sites.filter(function (r) { return String(r.site_id) === site.value; });
    option(facility, facilities, 'facility_id', 'facility_name', site.value ? 'Select facility' : 'Select a site first');
  }

  async function loadUnits() {
    unitsBox.textContent = '';
    if (!facility.value) {
      unitsBox.textContent = 'Select a facility to see its free units.';
      return;
    }
    try {
      var response = await fetch('/api/production/units?free=1&facility_id=' + encodeURIComponent(facility.value),
        { credentials: 'include' });
      var payload = await response.json();
      if (!response.ok) throw new Error(payload.message || 'Could not load units');
      var units = payload.data || [];
      if (!units.length) {
        unitsBox.textContent = 'No free bio-pods or trays at this facility.';
        return;
      }
      units.forEach(function (u) {
        var label = document.createElement('label');
        label.className = 'nb-unit';
        var check = document.createElement('input');
        check.type = 'checkbox';
        check.value = u.id;
        label.append(check, document.createTextNode(' ' + u.unit_code + ' · ' + u.name));
        unitsBox.appendChild(label);
      });
    } catch (error) {
      unitsBox.textContent = error.message;
    }
  }

  async function loadSubstrate() {
    loadUnits();
    substrateBox.textContent = '';
    substrates = [];
    if (!facility.value) {
      substrateBox.textContent = 'Select a facility to see its available substrate.';
      return;
    }
    try {
      var response = await fetch('/api/substrate-batches?facility_id=' + encodeURIComponent(facility.value), { credentials: 'include' });
      var payload = await response.json();
      if (!response.ok) throw new Error(payload.message || 'Could not load substrate');
      substrates = (payload.data || []).filter(function (s) { return Number(s.available_kg) > 0; });
    } catch (error) {
      substrateBox.textContent = error.message;
      return;
    }
    if (!substrates.length) {
      substrateBox.textContent = 'No substrate with remaining quantity at this facility. Prepare substrate first.';
      return;
    }
    substrates.forEach(function (s) {
      var line = document.createElement('div');
      line.className = 'nb-substrate-line';
      var check = document.createElement('input');
      check.type = 'checkbox';
      check.id = 'nbSub' + s.id;
      var label = document.createElement('label');
      label.htmlFor = check.id;
      label.textContent = (s.business_id || s.batch_code) + ' · prepared ' + s.preparation_date + ' · ' +
        Number(s.available_kg).toLocaleString() + ' kg available';
      var qty = document.createElement('input');
      qty.type = 'number';
      qty.min = '0.001';
      qty.step = '0.001';
      qty.max = s.available_kg;
      qty.placeholder = 'kg to issue';
      qty.setAttribute('aria-label', 'Kilograms to issue from ' + (s.business_id || s.batch_code));
      qty.addEventListener('input', function () { check.checked = Number(qty.value) > 0; });
      line.append(check, label, qty);
      line.dataset.substrateId = s.id;
      substrateBox.appendChild(line);
    });
  }

  document.getElementById('newBatchToggle').addEventListener('click', async function () {
    card.hidden = !card.hidden;
    if (card.hidden || rows.length) return;
    document.getElementById('nbStart').value = new Date().toISOString().slice(0, 10);
    try {
      var response = await fetch('/api/locations/hierarchy', { credentials: 'include' });
      var payload = await response.json();
      rows = (payload.data || []).filter(function (r) {
        return r.facility_id && r.farm_status === 'active' && r.site_status === 'active' && r.facility_status === 'active';
      });
    } catch (error) {
      rows = [];
    }
    renderPickers();
  });

  [farm, site].forEach(function (select) {
    select.addEventListener('change', function () { renderPickers(); loadSubstrate(); });
  });
  facility.addEventListener('change', loadSubstrate);

  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    var inputs = [].filter.call(substrateBox.querySelectorAll('.nb-substrate-line'), function (line) {
      return line.querySelector('input[type="checkbox"]').checked;
    }).map(function (line) {
      return {
        substrate_batch_id: Number(line.dataset.substrateId),
        quantity_issued: line.querySelector('input[type="number"]').value
      };
    });
    if (!inputs.length) {
      message.textContent = 'Choose at least one substrate batch and a quantity.';
      return;
    }
    var expected = document.getElementById('nbExpected').value;
    var button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    message.textContent = '';
    try {
      var response = await fetch('/api/production/batches', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          farm_id: farm.value,
          site_id: site.value,
          facility_id: facility.value,
          batch_code: document.getElementById('nbCode').value.trim(),
          start_date: document.getElementById('nbStart').value,
          expected_harvest_at: expected ? expected + 'T12:00:00' : null,
          harvest_limit_kg: document.getElementById('nbLimit').value || null,
          current_stage: document.getElementById('nbStage').value.trim() || 'STARTING',
          unit_ids: [].map.call(unitsBox.querySelectorAll('input:checked'), function (c) { return Number(c.value); }),
          inputs: inputs
        })
      });
      var payload = await response.json();
      if (!response.ok) throw new Error(payload.message || 'Could not create the batch');
      window.location.href = '/production_batch.html?batch=' + encodeURIComponent(payload.record.business_id);
    } catch (error) {
      message.textContent = error.message;
      button.disabled = false;
    }
  });
});
