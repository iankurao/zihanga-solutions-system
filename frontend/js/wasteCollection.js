// Waste collection page (/waste-collection): records one load of waste as a
// waste lot through POST /api/waste-sourcing. The place is chosen once and
// remembered on this device; date, time and collector default to now and the
// signed-in person; checks run while typing; the summary shows what will be
// created, and today's collections are listed under it.
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var form = $('wcForm');
  var PLACE_KEY = 'zehunger.wasteCollection.facility';
  var DRAFT_KEY = 'zehunger.wasteCollection.draft';
  var SOFT_LIMIT_KG = 1000;
  var WASTE_LABEL = {
    vegetable: 'Vegetable scraps', fruit: 'Fruit waste', brewers_grain: "Brewer's grain",
    potato: 'Potato waste', food_leftovers: 'Food leftovers'
  };

  var state = { facilities: [], place: null, recent: [], suppliers: [], maxKg: 5000, profile: null, repeatConfirmed: false };

  function store(key, value) {
    try {
      if (value == null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value));
    } catch (e) { /* storage blocked: the page works without it */ }
  }
  function load(key) {
    try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { return null; }
  }

  function pad(n) { return String(n).padStart(2, '0'); }
  function localToday() {
    var d = new Date();
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }
  function kg(value) {
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 }) + ' kg';
  }

  function checked(name) {
    var node = form.querySelector('input[name="' + name + '"]:checked');
    return node ? node.value : '';
  }
  function contaminants() {
    return [].map.call(form.querySelectorAll('input[name="contaminants"]:checked'), function (n) { return n.value; });
  }

  // The lot's status follows the server's rule: only clean organic waste is
  // available for substrate.
  function lotStatus() {
    if (checked('segregation_status') === 'inorganic') {
      return { value: 'rejected', label: 'Rejected', tone: 'danger', why: 'Inorganic waste cannot be fed to larvae.' };
    }
    if (checked('segregation_status') !== 'organic' || contaminants().length) {
      return { value: 'quarantined', label: 'Quarantined', tone: 'warning',
               why: 'Mixed or contaminated waste is held until it is sorted, and cannot be used for substrate yet.' };
    }
    return { value: 'available', label: 'Available', tone: 'success', why: 'Clean organic waste can go straight into substrate.' };
  }

  // ---- Field messages ------------------------------------------------------
  function fieldError(fieldId, errorId, text) {
    $(fieldId).classList.toggle('is-invalid', !!text);
    var node = $(errorId);
    node.textContent = text || '';
    node.hidden = !text;
  }

  function weightMessage(text, tone) {
    var node = $('wcWeightMsg');
    node.textContent = text || '';
    node.hidden = !text;
    node.className = 'wc-msg' + (tone ? ' is-' + tone : '');
    $('wcWeightField').classList.toggle('is-invalid', tone === 'error');
  }

  // Hard rules block saving; the soft warning only asks for a second look.
  function check() {
    var errors = [];
    var weight = parseFloat($('wcWeight').value);
    if ($('wcWeight').value === '') {
      weightMessage('');
    } else if (!(weight > 0)) {
      errors.push(['wcWeight', 'Enter the weight in kg, more than 0.']);
      weightMessage('Enter the weight in kg, more than 0.', 'error');
    } else if (weight > state.maxKg) {
      var tooMuch = 'More than ' + state.maxKg.toLocaleString() + ' kg is more than one collection. Record each load separately.';
      errors.push(['wcWeight', tooMuch]);
      weightMessage(tooMuch, 'error');
    } else if (weight > SOFT_LIMIT_KG) {
      weightMessage('That is a large load. Check the scale reading before saving.', 'warning');
    } else {
      weightMessage('');
    }
    if ($('wcWeight').value === '') errors.push(['wcWeight', 'Enter the weight in kg.']);

    var source = $('wcSource').value.trim();
    fieldError('wcSourceField', 'wcSourceError', '');
    if (!source) errors.push(['wcSource', 'Name the supplier.']);

    var today = localToday();
    var date = $('wcDate').value;
    var dateProblem = !date ? 'Pick the collection date.'
      : date > today ? 'The collection date cannot be in the future.' : '';
    fieldError('wcDateField', 'wcDateError', date > today ? dateProblem : '');
    if (dateProblem) errors.push(['wcDate', dateProblem]);
    $('wcDateNote').hidden = date !== today;

    if (!$('wcTime').value) errors.push(['wcTime', 'Enter the collection time.']);
    if (!$('wcCollector').value.trim()) errors.push(['wcCollector', 'Name who collected the load.']);

    var crates = parseInt($('wcCrates').value, 10);
    $('wcPerCrate').textContent = crates > 0 && weight > 0
      ? 'About ' + Math.round(weight / crates).toLocaleString() + ' kg per crate.'
      : 'Number of crates, if counted.';
    return errors;
  }

  // Shown on save: every missing or wrong field, each a link to the field.
  function showMissing(errors) {
    errors.forEach(function (problem) {
      if (problem[0] === 'wcSource') fieldError('wcSourceField', 'wcSourceError', problem[1]);
      if (problem[0] === 'wcDate') fieldError('wcDateField', 'wcDateError', problem[1]);
      if (problem[0] === 'wcTime') fieldError('wcTimeField', 'wcTimeError', problem[1]);
      if (problem[0] === 'wcCollector') fieldError('wcCollectorField', 'wcCollectorError', problem[1]);
      if (problem[0] === 'wcWeight' && $('wcWeightMsg').hidden) weightMessage(problem[1], 'error');
    });
    var unique = errors.filter(function (p, i) { return errors.findIndex(function (q) { return q[0] === p[0]; }) === i; });
    banner('danger', 'Not saved yet. Fix ' + (unique.length === 1 ? 'this' : 'these') + ' first:', unique.map(function (p) {
      var a = document.createElement('a');
      a.href = '#' + p[0];
      a.textContent = p[1];
      a.addEventListener('click', function (event) { event.preventDefault(); $(p[0]).focus(); });
      return a;
    }));
    $(unique[0][0]).focus();
  }

  // ---- Banner above the form -------------------------------------------------
  function banner(tone, title, items, links) {
    var box = $('wcBanner');
    box.textContent = '';
    if (!tone) return;
    var alert = document.createElement('div');
    alert.className = 'erp-alert is-' + tone;
    alert.setAttribute('role', tone === 'danger' ? 'alert' : 'status');
    var icon = document.createElement('i');
    icon.className = 'fas ' + ({ success: 'fa-circle-check', warning: 'fa-triangle-exclamation', danger: 'fa-circle-exclamation' }[tone]);
    icon.setAttribute('aria-hidden', 'true');
    var body = document.createElement('div');
    var head = document.createElement('strong');
    head.textContent = title;
    body.appendChild(head);
    if (items && items.length) {
      var list = document.createElement('ul');
      items.forEach(function (item) {
        var li = document.createElement('li');
        li.append(item);
        list.appendChild(li);
      });
      body.appendChild(list);
    }
    if (links && links.length) {
      var row = document.createElement('p');
      row.className = 'wc-banner-links';
      links.forEach(function (link) { row.appendChild(link); });
      body.appendChild(row);
    }
    alert.append(icon, body);
    box.appendChild(alert);
    box.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function link(text, href) {
    var a = document.createElement('a');
    a.href = href;
    a.textContent = text;
    return a;
  }

  // ---- Summary and today's list ------------------------------------------------
  function summary() {
    var weight = parseFloat($('wcWeight').value);
    var status = lotStatus();
    $('wcSumKg').textContent = weight > 0 ? kg(weight) : '—';
    $('wcSumType').textContent = WASTE_LABEL[checked('waste_type')] || '—';
    $('wcSumSource').textContent = $('wcSource').value.trim() || '—';
    $('wcSumPlace').textContent = state.place ? state.place.facility_name + ', ' + state.place.site_name : '—';
    var badge = $('wcSumStatus');
    badge.textContent = status.label;
    badge.className = 'erp-badge is-' + status.tone;
    $('wcSumWhy').textContent = status.why;
  }

  function renderRecent(fresh) {
    var list = $('wcRecent');
    list.textContent = '';
    $('wcRecentTitle').textContent = state.place ? 'Today at ' + state.place.facility_name : 'Today';
    var today = localToday();
    var rows = state.recent.filter(function (lot) { return String(lot.created_at || '').slice(0, 10) <= today; });
    if (!rows.length) {
      var empty = document.createElement('li');
      empty.className = 'wc-meta';
      empty.textContent = 'No collections recorded here today yet.';
      list.appendChild(empty);
      return;
    }
    rows.slice(0, 8).forEach(function (lot) {
      var li = document.createElement('li');
      if (fresh && lot.business_id === fresh) li.className = 'is-new';
      var ref = link(lot.business_id, '/traceability?ref=' + encodeURIComponent(lot.business_id) + '&type=waste_lot');
      var weight = document.createElement('span');
      weight.className = 'wc-kg';
      weight.textContent = kg(lot.quantity);
      var meta = document.createElement('span');
      meta.className = 'wc-meta';
      var time = lot.collection_time ? String(lot.collection_time).slice(0, 5) + ' · ' : '';
      meta.textContent = time + lot.source_name + ' · ' + lot.recorded_by + ' · ' + ErpUI.humanize(lot.status);
      li.append(ref, weight, meta);
      list.appendChild(li);
    });
  }

  async function loadRecent(fresh) {
    if (!state.place) return;
    try {
      var response = await fetch('/api/waste-lots/recent?days=1&facility_id=' + state.place.facility_id, { credentials: 'include' });
      var payload = await response.json();
      if (!response.ok) throw new Error(payload.message);
      state.recent = payload.data || [];
      state.suppliers = payload.suppliers || [];
      state.maxKg = payload.max_collection_kg || state.maxKg;
      var options = $('wcSuppliers');
      options.textContent = '';
      state.suppliers.forEach(function (supplier) { options.appendChild(new Option(supplier.name)); });
    } catch (error) {
      state.recent = [];
    }
    renderRecent(fresh);
  }

  // A known supplier fills in its usual source type.
  $('wcSource').addEventListener('change', function () {
    var name = this.value.trim().toLowerCase();
    var known = state.suppliers.find(function (s) { return s.name.toLowerCase() === name; });
    var input = known && form.querySelector('input[name="source_type"][value="' + known.source_type + '"]');
    if (input) input.checked = true;
    summary();
  });

  // ---- Working at --------------------------------------------------------------
  function showPlace() {
    var place = state.place;
    $('wcFarm').textContent = place ? place.farm_name : '—';
    $('wcSite').textContent = place ? place.site_name : '—';
    $('wcFacility').textContent = place ? place.facility_name : '—';
    $('wcFacilitySelect').value = place ? String(place.facility_id) : '';
    summary();
  }

  $('wcChange').addEventListener('click', function () {
    var picker = $('wcPicker');
    picker.hidden = !picker.hidden;
    this.setAttribute('aria-expanded', String(!picker.hidden));
    if (!picker.hidden) $('wcFacilitySelect').focus();
  });

  $('wcFacilitySelect').addEventListener('change', function () {
    var id = Number(this.value);
    state.place = state.facilities.find(function (f) { return f.facility_id === id; }) || state.place;
    store(PLACE_KEY, state.place && state.place.facility_id);
    $('wcPicker').hidden = true;
    $('wcChange').setAttribute('aria-expanded', 'false');
    showPlace();
    loadRecent();
  });

  async function loadPlaces() {
    var response = await fetch('/api/locations/hierarchy', { credentials: 'include' });
    var payload = await response.json();
    var rows = (payload.data || []).filter(function (row) {
      return row.facility_id && row.facility_status === 'active' && row.site_status === 'active' && row.farm_status === 'active';
    });
    // Waste facilities first: collections normally go there.
    rows.sort(function (a, b) {
      var wa = a.facility_type === 'waste_processing' ? 0 : 1;
      var wb = b.facility_type === 'waste_processing' ? 0 : 1;
      return wa - wb || a.farm_name.localeCompare(b.farm_name) || a.facility_name.localeCompare(b.facility_name);
    });
    state.facilities = rows;
    var select = $('wcFacilitySelect');
    select.textContent = '';
    rows.forEach(function (row) {
      select.appendChild(new Option(row.farm_name + ' › ' + row.site_name + ' › ' + row.facility_name, row.facility_id));
    });
    var saved = load(PLACE_KEY);
    state.place = rows.find(function (row) { return row.facility_id === saved; }) || rows[0] || null;
  }

  // ---- Draft kept on this device ----------------------------------------------------
  function saveDraft() {
    store(DRAFT_KEY, {
      source: $('wcSource').value, weight: $('wcWeight').value, crates: $('wcCrates').value,
      notes: $('wcNotes').value, source_type: checked('source_type'), waste_type: checked('waste_type')
    });
    $('wcDraft').textContent = 'Draft kept on this device';
  }

  function restoreDraft() {
    var draft = load(DRAFT_KEY);
    if (!draft) return;
    $('wcSource').value = draft.source || '';
    $('wcWeight').value = draft.weight || '';
    $('wcCrates').value = draft.crates || '';
    $('wcNotes').value = draft.notes || '';
    ['source_type', 'waste_type'].forEach(function (name) {
      var input = draft[name] && form.querySelector('input[name="' + name + '"][value="' + draft[name] + '"]');
      if (input) input.checked = true;
    });
    if (draft.source || draft.weight) $('wcDraft').textContent = 'Unsaved entry restored from this device';
  }

  // ---- Save ---------------------------------------------------------------------------
  function repeatOf() {
    var source = $('wcSource').value.trim().toLowerCase();
    var weight = parseFloat($('wcWeight').value);
    var since = Date.now() - 12 * 3600 * 1000;
    return state.recent.find(function (lot) {
      return String(lot.source_name).toLowerCase() === source && Math.abs(Number(lot.quantity) - weight) < 0.001 &&
        new Date(lot.created_at).getTime() >= since;
    });
  }

  function payload() {
    var crates = parseInt($('wcCrates').value, 10);
    var notes = $('wcNotes').value.trim();
    if (crates > 0) notes = (notes ? notes + ' · ' : '') + crates + ' crate' + (crates === 1 ? '' : 's');
    return {
      farm_id: state.place.farm_id,
      site_id: state.place.site_id,
      facility_id: state.place.facility_id,
      collection_date: $('wcDate').value,
      collection_time: $('wcTime').value,
      source_type: checked('source_type'),
      source_name: $('wcSource').value.trim(),
      waste_type: checked('waste_type'),
      waste_weight: $('wcWeight').value,
      segregation_status: checked('segregation_status'),
      contaminants_found: contaminants(),
      lot_status: lotStatus().value,
      collection_personnel: $('wcCollector').value.trim(),
      collection_notes: notes
    };
  }

  function resetForNext(keepSupplier) {
    var supplier = $('wcSource').value;
    $('wcWeight').value = '';
    $('wcCrates').value = '';
    $('wcNotes').value = '';
    form.querySelectorAll('input[name="contaminants"]').forEach(function (n) { n.checked = false; });
    $('wcSegOrganic').checked = true;
    if (!keepSupplier) $('wcSource').value = '';
    else $('wcSource').value = supplier;
    var now = new Date();
    $('wcDate').value = localToday();
    $('wcTime').value = pad(now.getHours()) + ':' + pad(now.getMinutes());
    store(DRAFT_KEY, null);
    $('wcDraft').textContent = '';
    check();
    summary();
  }

  async function save(addAnother) {
    var errors = check();
    if (errors.length) { showMissing(errors); return; }
    if (!state.place) return;
    var repeat = repeatOf();
    if (repeat && !state.repeatConfirmed) {
      var again = document.createElement('button');
      again.type = 'button';
      again.className = 'erp-link-button';
      again.textContent = 'Yes, this is another load: save it';
      again.addEventListener('click', function () { state.repeatConfirmed = true; save(addAnother); });
      banner('warning', 'This looks like ' + repeat.business_id + ' again: ' + kg(repeat.quantity) + ' from ' +
        repeat.source_name + ' was recorded earlier today. Save it only if it is a second load.', null, [again]);
      return;
    }
    state.repeatConfirmed = false;
    var buttons = [$('wcSave'), $('wcSaveAnother')];
    buttons.forEach(function (b) { b.disabled = true; });
    var label = $('wcSave').innerHTML;
    $('wcSave').innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> Saving…';
    try {
      var body = payload();
      var response = await fetch('/api/waste-sourcing', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      var result = await response.json().catch(function () { return {}; });
      if (!response.ok) throw new Error(result.message || 'The server did not accept the entry.');
      var lot = result.waste_lot || {};
      var ref = lot.business_id || 'the waste lot';
      var status = lotStatus();
      var links = [];
      if (status.value === 'available') links.push(link('Prepare substrate from it', '/dashboard#feeding'));
      links.push(link('Print QR label', '/labels?type=waste_lot&ref=' + encodeURIComponent(ref)));
      links.push(link('Open its record', '/traceability?ref=' + encodeURIComponent(ref) + '&type=waste_lot'));
      banner('success', 'Saved as ' + ref + ': ' + kg(body.waste_weight) + ' from ' + body.source_name + ', ' +
        status.label.toLowerCase() + '.', null, links);
      resetForNext(addAnother);
      await loadRecent(lot.business_id);
      if (addAnother) $('wcWeight').focus();
    } catch (error) {
      banner('danger', 'Not saved: ' + error.message);
    } finally {
      buttons.forEach(function (b) { b.disabled = false; });
      $('wcSave').innerHTML = label;
    }
  }

  form.addEventListener('submit', function (event) { event.preventDefault(); save(false); });
  $('wcSaveAnother').addEventListener('click', function () { save(true); });
  form.addEventListener('input', function () {
    check();
    summary();
    saveDraft();
    state.repeatConfirmed = false;
    var current = $('wcBanner').querySelector('.erp-alert');
    if (current && !current.classList.contains('is-success')) banner(null);
  });
  form.addEventListener('change', function () { check(); summary(); });

  // ---- Start ----------------------------------------------------------------------------
  function blockForm(text) {
    var note = $('wcNoAccess');
    note.hidden = false;
    ErpUI.message(note, text, 'warning');
    $('wcLayout').hidden = true;
  }

  (async function start() {
    var today = localToday();
    var now = new Date();
    $('wcDate').value = today;
    $('wcDate').max = today;
    $('wcTime').value = pad(now.getHours()) + ':' + pad(now.getMinutes());
    restoreDraft();
    state.profile = await (window.currentUser || Promise.resolve(null));
    var permissions = (state.profile && state.profile.permissions) || [];
    if (permissions.indexOf('production.write') === -1) {
      blockForm('Your role cannot record waste collections. Ask a farm manager if you need to.');
      return;
    }
    $('wcCollector').value = $('wcCollector').value || state.profile.full_name || state.profile.username || '';
    try {
      await loadPlaces();
    } catch (error) {
      blockForm('Could not load your farms. Check the connection and reload the page.');
      return;
    }
    if (!state.place) {
      blockForm('You have no farm or facility assigned yet. Ask an administrator to give you access in Setup.');
      return;
    }
    showPlace();
    check();
    summary();
    await loadRecent();
  })();
})();
