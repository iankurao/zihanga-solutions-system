// Farmer portal: today's tasks, my batches and quick recording forms.
document.addEventListener('DOMContentLoaded', function () {
  var dialog = document.getElementById('farmerDialog');
  var form = document.getElementById('farmerForm');
  var fieldsBox = document.getElementById('dialogFields');
  var errorBox = document.getElementById('dialogError');
  var toast = document.getElementById('farmerToast');
  var me = { username: '' };
  var current = null; // { batch, kind }

  var STATUS_TEXT = {
    PLANNED: 'Planned', ACTIVE: 'Growing', MONITORING: 'Growing', READY_FOR_HARVEST: 'Ready to harvest',
    PAUSED: 'Paused', HEALTH_ALERT: 'Health alert'
  };
  var TASK_ICON = { feed: 'fa-utensils', harvest: 'fa-basket-shopping', overdue: 'fa-clock', health: 'fa-kit-medical' };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function ago(value) {
    if (!value) return 'never';
    var minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000));
    if (minutes < 60) return minutes + ' min ago';
    var hours = Math.round(minutes / 60);
    if (hours < 24) return hours + ' h ago';
    return Math.round(hours / 24) + ' days ago';
  }

  function shortDate(value) {
    return value ? new Date(value).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : '—';
  }

  function say(text, isError) {
    toast.textContent = text;
    toast.className = 'farmer-toast' + (isError ? ' is-error' : '');
    toast.hidden = false;
    clearTimeout(say.timer);
    say.timer = setTimeout(function () { toast.hidden = true; }, 6000);
  }

  async function api(url, options) {
    var response = await fetch(url, Object.assign({ credentials: 'include' }, options || {}));
    var payload = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(payload.message || payload.error || 'Something went wrong. Please try again.');
    return payload;
  }

  // ---- forms -------------------------------------------------------------------
  function field(spec) {
    var wrap = el('div', 'farmer-field');
    var id = 'f_' + spec.name;
    var label = el('label', null, spec.label);
    label.htmlFor = id;
    wrap.appendChild(label);
    var input;
    if (spec.type === 'select') {
      input = el('select');
      spec.options.forEach(function (o) { input.add(new Option(o[1], o[0])); });
    } else if (spec.type === 'textarea') {
      input = el('textarea');
      input.rows = 2;
    } else {
      input = el('input');
      input.type = spec.type || 'text';
      if (spec.type === 'number') {
        input.inputMode = 'decimal';
        input.step = spec.step || '0.1';
        input.min = spec.min != null ? spec.min : '0';
        if (spec.max != null) input.max = spec.max;
      }
    }
    input.id = id;
    input.name = spec.name;
    if (spec.required) input.required = true;
    if (spec.value != null) input.value = spec.value;
    if (spec.placeholder) input.placeholder = spec.placeholder;
    wrap.appendChild(input);
    if (spec.help) wrap.appendChild(el('small', null, spec.help));
    return wrap;
  }

  function doneBy() {
    var remembered = '';
    try { remembered = localStorage.getItem('zehunger.farmer.doneBy') || ''; } catch (e) { /* optional */ }
    return remembered || me.full_name || me.username || '';
  }

  var FORMS = {
    feeding: {
      title: 'Record feeding',
      fields: function () {
        return [
          { name: 'feed_type', label: 'What did you feed?', required: true, value: 'Vegetable substrate' },
          { name: 'quantity_offered', label: 'Amount (kg)', type: 'number', required: true, min: '0.1' },
          { name: 'larvae_biomass', label: 'Larvae weight (kg, if weighed)', type: 'number' },
          { name: 'operator', label: 'Done by', required: true, value: doneBy() },
          { name: 'notes', label: 'Notes', type: 'textarea' }
        ];
      },
      payload: function (v) {
        return { feed_type: v.feed_type, quantity_offered: v.quantity_offered, offered_unit: 'kg',
          larvae_biomass: v.larvae_biomass || null, biomass_unit: v.larvae_biomass ? 'kg' : null,
          operator: v.operator, notes: v.notes };
      }
    },
    monitoring: {
      title: 'Record a check',
      fields: function (batch) {
        return [
          { name: 'temperature', label: 'Temperature (°C)', type: 'number', required: true, min: '-10', max: '60' },
          { name: 'humidity', label: 'Humidity (%)', type: 'number', required: true, max: '100' },
          { name: 'ammonia_odor', label: 'Ammonia smell?', type: 'select', options: [['no', 'No'], ['yes', 'Yes']] },
          { name: 'asset_reference', label: 'Bio-pod / tray', type: 'select',
            options: [['Whole batch', 'Whole batch']].concat(batch.units.map(function (u) { return [u, u]; })) },
          { name: 'notes', label: 'Notes', type: 'textarea' }
        ];
      },
      payload: function (v) {
        return { temperature: v.temperature, humidity: v.humidity, ammonia_odor: v.ammonia_odor,
          asset_reference: v.asset_reference || 'Whole batch', notes: v.notes };
      }
    },
    health: {
      title: 'Report a health problem',
      fields: function () {
        return [
          { name: 'observed_issue', label: 'What did you see?', required: true, placeholder: 'e.g. mites on tray edges' },
          { name: 'severity', label: 'How serious?', type: 'select',
            options: [['low', 'Low'], ['medium', 'Medium'], ['high', 'High'], ['critical', 'Critical']] },
          { name: 'action_taken', label: 'What did you do?', required: true, type: 'textarea' },
          { name: 'follow_up_date', label: 'Check again on (optional)', type: 'date' }
        ];
      },
      payload: function (v) {
        return { observed_issue: v.observed_issue, severity: v.severity, action_taken: v.action_taken,
          follow_up_date: v.follow_up_date || null };
      }
    },
    harvest: {
      title: 'Record harvest',
      fields: function (batch) {
        return [
          { name: 'wet_weight', label: 'Wet weight harvested (kg)', type: 'number', required: true, min: '0.1' },
          { name: 'harvest_stage', label: 'Larvae stage', type: 'select',
            options: [['larvae', 'Larvae'], ['prepupae', 'Pre-pupae'], ['mixed', 'Mixed']] },
          { name: 'location', label: 'Where', required: true, value: batch.facility_name },
          { name: 'operator', label: 'Harvested by', required: true, value: doneBy() },
          { name: 'notes', label: 'Notes', type: 'textarea' }
        ];
      },
      payload: function (v) {
        return { wet_weight: v.wet_weight, unit: 'kg', harvest_stage: v.harvest_stage, location: v.location,
          operator: v.operator, notes: v.notes };
      }
    }
  };

  function openForm(batch, kind) {
    current = { batch: batch, kind: kind };
    var spec = FORMS[kind];
    document.getElementById('dialogTitle').textContent = spec.title;
    document.getElementById('dialogBatch').textContent = batch.business_id + ' · ' + batch.facility_name;
    fieldsBox.replaceChildren.apply(fieldsBox, spec.fields(batch).map(field));
    errorBox.textContent = '';
    document.getElementById('dialogSave').disabled = false;
    dialog.showModal();
    var first = fieldsBox.querySelector('input, select, textarea');
    if (first) first.focus();
  }

  document.getElementById('dialogCancel').addEventListener('click', function () { dialog.close(); });

  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    var missing = [].filter.call(fieldsBox.querySelectorAll('[required]'), function (i) { return !i.value.trim(); });
    if (missing.length) {
      errorBox.textContent = 'Please fill in: ' + missing.map(function (i) {
        return i.previousElementSibling.textContent;
      }).join(', ');
      missing[0].focus();
      return;
    }
    var invalid = [].find.call(fieldsBox.querySelectorAll('input[type="number"]'), function (i) {
      return i.value !== '' && !i.checkValidity();
    });
    if (invalid) {
      errorBox.textContent = invalid.previousElementSibling.textContent + ' looks wrong. Please check the number.';
      invalid.focus();
      return;
    }
    var values = {};
    fieldsBox.querySelectorAll('[name]').forEach(function (i) { values[i.name] = i.value.trim(); });
    var body = FORMS[current.kind].payload(values);
    body.occurred_at = new Date().toISOString();
    if (values.operator) {
      try { localStorage.setItem('zehunger.farmer.doneBy', values.operator); } catch (e) { /* optional */ }
    }
    var save = document.getElementById('dialogSave');
    save.disabled = true;
    try {
      await api('/api/production/batches/' + encodeURIComponent(current.batch.business_id) + '/events/' + current.kind, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      dialog.close();
      say('Saved for ' + current.batch.business_id + '.');
      load();
    } catch (error) {
      errorBox.textContent = error.message;
      save.disabled = false;
    }
  });

  // ---- page ----------------------------------------------------------------
  function renderTasks(tasks) {
    var list = document.getElementById('farmerTasks');
    list.textContent = '';
    if (!tasks.length) {
      var done = el('li', 'farmer-task is-done');
      done.append(el('i', 'fas fa-circle-check'), el('span', null, 'All caught up. Nothing is waiting for you right now.'));
      list.appendChild(done);
      return;
    }
    tasks.forEach(function (task) {
      var item = el('li', 'farmer-task' + (task.priority === 0 ? ' is-urgent' : task.priority === 1 ? ' is-soon' : ''));
      item.append(el('i', 'fas ' + (TASK_ICON[task.kind] || 'fa-circle')), el('span', null, task.text));
      list.appendChild(item);
    });
  }

  function renderBatches(batches) {
    var box = document.getElementById('farmerBatches');
    box.textContent = '';
    if (!batches.length) {
      box.appendChild(el('p', 'farmer-empty', 'You have no active batches. Ask your farm manager if this looks wrong.'));
      return;
    }
    batches.forEach(function (b) {
      var card = el('article', 'farmer-batch');
      var head = el('div', 'farmer-batch-head');
      head.append(el('strong', null, b.business_id),
        el('span', 'farmer-pill' + (b.status === 'HEALTH_ALERT' ? ' is-alert' : b.status === 'PAUSED' || b.status === 'PLANNED' ? ' is-wait' : ''),
          STATUS_TEXT[b.status] || b.status));
      card.appendChild(head);
      var facts = el('div', 'farmer-facts');
      [
        ['Where', b.facility_name + (b.units.length ? ' · ' + b.units.join(', ') : '')],
        ['Age', b.age_days + ' days'],
        ['Last fed', ago(b.last_fed_at)],
        ['Last check', b.last_check ? (b.last_check.temperature + '°C · ' + b.last_check.humidity + '% · ' + ago(b.last_check.at)) : 'never'],
        ['Expected harvest', shortDate(b.expected_harvest_at)],
        ['Health issues', b.open_health ? b.open_health + ' open' : 'none']
      ].forEach(function (pair) {
        var cell = el('div');
        cell.append(el('span', null, pair[0]), el('b', null, pair[1]));
        facts.appendChild(cell);
      });
      card.appendChild(facts);
      var actions = el('div', 'farmer-actions');
      var buttons = [['feeding', 'Feed', 'fa-utensils'], ['monitoring', 'Check', 'fa-temperature-half'],
        ['health', 'Health issue', 'fa-kit-medical']];
      if (b.status === 'READY_FOR_HARVEST') buttons.push(['harvest', 'Harvest', 'fa-basket-shopping']);
      buttons.forEach(function (spec) {
        var button = el('button', spec[0] === 'harvest' ? 'is-harvest' : null);
        button.type = 'button';
        button.append(el('i', 'fas ' + spec[2]), document.createTextNode(' ' + spec[1]));
        button.addEventListener('click', function () { openForm(b, spec[0]); });
        actions.appendChild(button);
      });
      card.appendChild(actions);
      var link = el('a', 'farmer-batch-link', 'See full history →');
      link.href = '/batch-360?ref=' + encodeURIComponent(b.business_id);
      card.appendChild(link);
      box.appendChild(card);
    });
  }

  function renderUnits(units) {
    var box = document.getElementById('farmerUnits');
    box.textContent = '';
    if (!units.length) {
      box.appendChild(el('p', 'farmer-empty', 'No bio-pods or trays are set up for your facilities yet.'));
      return;
    }
    units.forEach(function (u) {
      var card = el('div', 'farmer-unit' + (u.status === 'maintenance' ? ' is-maintenance' : !u.batch_business_id ? ' is-free' : ''));
      card.append(el('strong', null, u.unit_code + ' · ' + u.name),
        el('small', null, u.status === 'maintenance' ? 'Under maintenance'
          : u.batch_business_id ? 'Holds ' + u.batch_business_id : 'Free'));
      box.appendChild(card);
    });
  }

  async function load() {
    try {
      var data = (await api('/api/farmer/overview')).data;
      renderTasks(data.tasks);
      renderBatches(data.batches);
      renderUnits(data.units);
    } catch (error) {
      say(error.message, true);
    }
  }

  (async function init() {
    try {
      me = (await api('/api/me')).data;
      var name = me.full_name || me.username;
      document.getElementById('farmerGreeting').textContent = 'Hello, ' + name.split(' ')[0];
    } catch (e) { /* greeting stays generic */ }
    try {
      var rows = (await api('/api/locations/hierarchy')).data || [];
      var farms = {};
      rows.forEach(function (r) {
        if (!r.facility_name) return;
        farms[r.farm_name] = farms[r.farm_name] || [];
        if (farms[r.farm_name].indexOf(r.facility_name) === -1) farms[r.farm_name].push(r.facility_name);
      });
      var lines = Object.keys(farms).map(function (farm) {
        var list = farms[farm];
        return farm + ': ' + list.slice(0, 2).join(', ') + (list.length > 2 ? ' +' + (list.length - 2) + ' more' : '');
      });
      document.getElementById('farmerPlaces').textContent = lines.length
        ? lines.join(' · ')
        : 'No farm assigned yet — ask your farm manager.';
    } catch (e) { /* optional */ }
    load();
  })();
});
