document.addEventListener('DOMContentLoaded', function () {
  var listNode = document.getElementById('alertList');
  var viewSelect = document.getElementById('alertView');
  var severitySelect = document.getElementById('alertSeverity');
  var message = document.getElementById('alertMessage');
  var isAdmin = false;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function when(value) {
    if (!value) return '—';
    return new Date(value).toLocaleString(undefined, {
      day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'
    });
  }

  function since(value) {
    var minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000));
    if (minutes < 60) return minutes + ' min ago';
    var hours = Math.round(minutes / 60);
    if (hours < 48) return hours + ' h ago';
    return Math.round(hours / 24) + ' days ago';
  }

  function button(text, className, onClick) {
    var node = el('button', className, text);
    node.type = 'button';
    node.addEventListener('click', onClick);
    return node;
  }

  async function api(url, options) {
    var response = await fetch(url, Object.assign({ credentials: 'include' }, options || {}));
    var payload = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(payload.message || payload.error || 'Request failed');
    return payload;
  }

  function send(url, method, body) {
    return api(url, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
  }

  function say(text, isError) {
    message.textContent = text || '';
    message.style.color = isError ? '' : 'var(--accent)';
  }

  function renderCounts(counts) {
    var target = document.getElementById('alertCounts');
    target.textContent = '';
    [['critical', 'Critical'], ['warning', 'Warning'], ['info', 'Info'],
      ['acknowledged', 'Acknowledged'], ['snoozed', 'Snoozed']].forEach(function (pair) {
      var tile = el('div', 'alert-count is-' + pair[0]);
      tile.append(el('span', null, pair[1]), el('strong', null, String(counts[pair[0]] || 0)));
      target.appendChild(tile);
    });
  }

  function alertCard(alert) {
    var muted = alert.status !== 'OPEN';
    var card = el('article', 'alert-card is-' + alert.severity + (muted ? ' is-muted' : ''));
    var head = el('div', 'alert-card-head');
    head.appendChild(el('h3', null, alert.title));
    var pills = el('div');
    pills.append(
      el('span', 'b360-pill ' + (alert.severity === 'critical' ? 'is-bad' : alert.severity === 'warning' ? 'is-warn' : 'is-info'),
        alert.severity),
      document.createTextNode(' '),
      el('span', 'b360-pill', alert.status.toLowerCase())
    );
    head.appendChild(pills);
    card.append(head, el('p', null, alert.message));

    var meta = ['Detected ' + since(alert.first_detected_at)];
    var place = [alert.farm_name, alert.facility_name].filter(Boolean).join(' / ');
    if (place) meta.push(place);
    if (alert.status === 'ACKNOWLEDGED') {
      meta.push('Acknowledged by ' + (alert.acknowledged_by || '—') +
        (alert.acknowledgement_note ? ': “' + alert.acknowledgement_note + '”' : ''));
    }
    if (alert.status === 'SNOOZED') meta.push('Snoozed until ' + when(alert.snoozed_until));
    if (alert.status === 'RESOLVED') meta.push('Resolved ' + when(alert.resolved_at) + ' · ' + (alert.resolved_reason || ''));
    card.appendChild(el('p', 'alert-meta', meta.join(' · ')));

    var actions = el('div', 'alert-actions');
    if (alert.href) {
      var link = el('a', 'alert-open-link', 'Open ' + (alert.entity_ref || 'record') + ' →');
      link.href = alert.href;
      actions.appendChild(link);
    }
    if (alert.status === 'OPEN' || alert.status === 'SNOOZED') {
      actions.appendChild(button('Acknowledge', 'orders-secondary', function () {
        var note = el('input');
        note.type = 'text';
        note.maxLength = 500;
        note.placeholder = 'Note (optional)';
        note.setAttribute('aria-label', 'Acknowledgement note');
        var save = button('Save', 'orders-primary', function () {
          save.disabled = true;
          send('/api/alerts/' + alert.id + '/acknowledge', 'POST', { note: note.value })
            .then(function () { say('Alert acknowledged.'); load(); })
            .catch(function (error) { say(error.message, true); save.disabled = false; });
        });
        actions.replaceChildren(note, save);
        note.focus();
      }));
    }
    if (alert.status !== 'RESOLVED') {
      var hours = el('select');
      hours.setAttribute('aria-label', 'Snooze duration');
      [[4, '4 hours'], [24, '1 day'], [72, '3 days'], [168, '1 week']].forEach(function (pair) {
        hours.add(new Option(pair[1], pair[0]));
      });
      var snooze = button('Snooze', 'orders-secondary', function () {
        snooze.disabled = true;
        send('/api/alerts/' + alert.id + '/snooze', 'POST', { hours: Number(hours.value) })
          .then(function () { say('Alert snoozed.'); load(); })
          .catch(function (error) { say(error.message, true); snooze.disabled = false; });
      });
      actions.append(hours, snooze);
    }
    card.appendChild(actions);
    return card;
  }

  async function load() {
    try {
      var url = '/api/alerts?status=' + viewSelect.value +
        (severitySelect.value ? '&severity=' + severitySelect.value : '');
      var payload = await api(url);
      renderCounts(payload.counts);
      listNode.textContent = '';
      if (!payload.data.length) {
        listNode.appendChild(el('p', 'b360-empty',
          viewSelect.value === 'active' ? 'No active alerts. Operations look healthy.' : 'No alerts in this view.'));
        return;
      }
      payload.data.forEach(function (alert) { listNode.appendChild(alertCard(alert)); });
    } catch (error) {
      say(error.message, true);
    }
  }

  async function loadThresholds() {
    var target = document.getElementById('thresholdList');
    try {
      var payload = await api('/api/alerts/thresholds');
      target.textContent = '';
      if (!payload.data.length) {
        target.appendChild(el('p', 'b360-empty', 'No minimums set, so no low-stock alerts are raised.'));
        return;
      }
      var wrap = el('div', 'b360-table-wrap');
      var table = el('table', 'b360-table');
      var head = el('tr');
      ['Farm', 'Product', 'Minimum', 'Updated by', ''].forEach(function (text) { head.appendChild(el('th', null, text)); });
      var thead = el('thead');
      thead.appendChild(head);
      var tbody = el('tbody');
      payload.data.forEach(function (row) {
        var tr = el('tr');
        tr.append(el('td', null, row.farm_name), el('td', null, row.product_type),
          el('td', null, Number(row.minimum_kg).toLocaleString() + ' kg'),
          el('td', null, row.updated_by + ' · ' + when(row.updated_at)));
        var cell = el('td');
        if (isAdmin) {
          cell.appendChild(button('Remove', 'orders-danger', function () {
            send('/api/alerts/thresholds/' + row.id, 'DELETE')
              .then(function () { say('Minimum removed.'); loadThresholds(); })
              .catch(function (error) { say(error.message, true); });
          }));
        }
        tr.appendChild(cell);
        tbody.appendChild(tr);
      });
      table.append(thead, tbody);
      wrap.appendChild(table);
      target.appendChild(wrap);
    } catch (error) {
      target.textContent = error.message;
    }
  }

  async function setupThresholdForm() {
    try {
      await api('/api/admin/me');
      isAdmin = true;
    } catch (error) {
      isAdmin = false;
    }
    var form = document.getElementById('thresholdForm');
    form.hidden = !isAdmin;
    if (!isAdmin) return;
    var farm = document.getElementById('thresholdFarm');
    try {
      var hierarchy = await api('/api/locations/hierarchy');
      var seen = {};
      farm.replaceChildren(new Option('Select farm', ''));
      (hierarchy.data || []).forEach(function (row) {
        if (row.farm_id && !seen[row.farm_id]) {
          seen[row.farm_id] = true;
          farm.add(new Option(row.farm_name, row.farm_id));
        }
      });
    } catch (error) {
      farm.replaceChildren(new Option('Farms could not be loaded', ''));
    }
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      send('/api/alerts/thresholds', 'PUT', {
        farm_id: farm.value,
        product_type: document.getElementById('thresholdProduct').value,
        minimum_kg: document.getElementById('thresholdMinimum').value
      }).then(function () {
        say('Minimum saved. Low-stock alerts update on the next check.');
        form.reset();
        loadThresholds();
      }).catch(function (error) { say(error.message, true); });
    });
  }

  document.getElementById('alertRefresh').addEventListener('click', function () {
    var refresh = this;
    refresh.disabled = true;
    send('/api/alerts/refresh', 'POST')
      .then(function (payload) {
        say(payload.refreshed ? 'Checked just now.' : 'Already checked in the last few seconds.');
        return load();
      })
      .catch(function (error) { say(error.message, true); })
      .finally(function () { refresh.disabled = false; });
  });
  viewSelect.addEventListener('change', load);
  severitySelect.addEventListener('change', load);

  load();
  setupThresholdForm().then(loadThresholds);
});
