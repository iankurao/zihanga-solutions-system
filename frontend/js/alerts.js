document.addEventListener('DOMContentLoaded', function () {
  var listNode = document.getElementById('alertList');
  var viewSelect = document.getElementById('alertView');
  var severitySelect = document.getElementById('alertSeverity');
  var message = document.getElementById('alertMessage');
  var isAdmin = false;
  var canManage = false;

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
    ErpUI.message(message, text, isError ? 'danger' : 'success');
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
    pills.append(ErpUI.badge(alert.severity), document.createTextNode(' '), ErpUI.badge(alert.status));
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
    if (canManage && (alert.status === 'OPEN' || alert.status === 'SNOOZED')) {
      actions.appendChild(button('Acknowledge', 'erp-btn erp-btn--secondary erp-btn--sm', function () {
        var note = el('input');
        note.type = 'text';
        note.maxLength = 500;
        note.placeholder = 'Note (optional)';
        note.setAttribute('aria-label', 'Acknowledgement note');
        var save = button('Save', 'erp-btn erp-btn--sm', function () {
          ErpUI.busy(save, send('/api/alerts/' + alert.id + '/acknowledge', 'POST', { note: note.value }))
            .then(function () { say('Alert acknowledged.'); load(); })
            .catch(function (error) { say(error.message, true); });
        });
        actions.replaceChildren(note, save);
        note.focus();
      }));
    }
    if (canManage && alert.status !== 'RESOLVED') {
      var hours = el('select');
      hours.setAttribute('aria-label', 'Snooze duration');
      [[4, '4 hours'], [24, '1 day'], [72, '3 days'], [168, '1 week']].forEach(function (pair) {
        hours.add(new Option(pair[1], pair[0]));
      });
      var snooze = button('Snooze', 'erp-btn erp-btn--secondary erp-btn--sm', function () {
        ErpUI.busy(snooze, send('/api/alerts/' + alert.id + '/snooze', 'POST', { hours: Number(hours.value) }))
          .then(function () { say('Alert snoozed.'); load(); })
          .catch(function (error) { say(error.message, true); });
      });
      actions.append(hours, snooze);
    }
    card.appendChild(actions);
    return card;
  }

  async function load() {
    if (!listNode.children.length) ErpUI.loading(listNode, 'Loading alerts…');
    try {
      var url = '/api/alerts?status=' + viewSelect.value +
        (severitySelect.value ? '&severity=' + severitySelect.value : '');
      var payload = await api(url);
      renderCounts(payload.counts);
      listNode.textContent = '';
      if (!payload.data.length) {
        if (viewSelect.value === 'active') {
          ErpUI.empty(listNode, 'No active alerts', 'Operations look healthy.', { icon: 'fa-circle-check' });
        } else {
          ErpUI.empty(listNode, 'No alerts in this view', 'Try another view or severity.');
        }
        return;
      }
      payload.data.forEach(function (alert) { listNode.appendChild(alertCard(alert)); });
    } catch (error) {
      ErpUI.error(listNode, error.message, load);
    }
  }

  async function loadThresholds() {
    var target = document.getElementById('thresholdList');
    try {
      var payload = await api('/api/alerts/thresholds');
      target.textContent = '';
      if (!payload.data.length) {
        target.appendChild(ErpUI.state('empty', { text: 'No minimums set, so no low-stock alerts are raised.', compact: true }));
        return;
      }
      var columns = ['Farm', 'Product', { label: 'Minimum', numeric: true }, 'Updated by'];
      if (isAdmin) columns.push({ label: 'Actions' });
      target.appendChild(ErpUI.table(columns, payload.data.map(function (row) {
        var cells = [row.farm_name, row.product_type, Number(row.minimum_kg).toLocaleString() + ' kg',
          row.updated_by + ' · ' + when(row.updated_at)];
        if (isAdmin) {
          cells.push(button('Remove', 'erp-btn erp-btn--danger erp-btn--sm', function () {
            ErpUI.confirm({
              title: 'Remove the ' + row.product_type + ' minimum for ' + row.farm_name + '?',
              text: 'Low-stock alerts for this product stop until a new minimum is set.',
              confirmLabel: 'Remove minimum',
              danger: true
            }).then(function (confirmed) {
              if (!confirmed) return;
              send('/api/alerts/thresholds/' + row.id, 'DELETE')
                .then(function () { say('Minimum removed.'); loadThresholds(); })
                .catch(function (error) { say(error.message, true); });
            });
          }));
        }
        return cells;
      }), 'Low-stock minimums'));
    } catch (error) {
      ErpUI.error(target, error.message, loadThresholds);
    }
  }

  async function setupThresholdForm() {
    var profile = await (window.currentUser || Promise.resolve(null));
    // Setting minimums is a super-admin action on the server.
    isAdmin = !!profile && profile.role === 'super_admin';
    canManage = !!profile && (profile.permissions || []).indexOf('alerts.manage') !== -1;
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

  async function setupPreferences() {
    var inApp = document.getElementById('prefInApp');
    var email = document.getElementById('prefEmail');
    var note = document.getElementById('preferenceNote');
    try {
      var payload = await api('/api/notifications/preferences');
      inApp.value = payload.data.in_app_min_severity;
      email.value = payload.data.email_min_severity;
      note.textContent = payload.data.email_configured
        ? 'Email goes to ' + (payload.data.email || 'your account address') + '.'
        : 'Email is not configured on this server yet, so only in-app notifications are sent.';
    } catch (error) {
      note.textContent = error.message;
    }
    document.getElementById('preferenceForm').addEventListener('submit', function (event) {
      event.preventDefault();
      send('/api/notifications/preferences', 'PUT', {
        in_app_min_severity: inApp.value, email_min_severity: email.value
      }).then(function () { say('Notification settings saved.'); })
        .catch(function (error) { say(error.message, true); });
    });
  }

  async function loadEmailStatus() {
    var card = document.getElementById('emailStatusCard');
    if (!isAdmin) return;
    card.hidden = false;
    var target = document.getElementById('emailStatus');
    try {
      var data = (await api('/api/notifications/email-status')).data;
      target.textContent = '';
      var facts = el('dl', 'erp-facts');
      [['SMTP configured', data.configured ? 'Yes' : 'No — set EMAIL_HOST_USER and EMAIL_HOST_PASSWORD'],
        ['Waiting to send', data.pending], ['Sent', data.sent], ['Failed', data.failed],
        ['Last sent', data.last_sent_at ? when(data.last_sent_at) : '—']].forEach(function (pair) {
        var item = el('div');
        item.append(el('dt', null, pair[0]), el('dd', null, String(pair[1])));
        facts.appendChild(item);
      });
      target.appendChild(facts);
      (data.recent_failures || []).forEach(function (row) {
        target.appendChild(el('p', 'alert-meta',
          row.recipient + ' · attempt ' + row.attempts + ' · ' + row.status.toLowerCase() + ': ' + row.last_error));
      });
    } catch (error) {
      ErpUI.error(target, error.message, loadEmailStatus);
    }
  }

  document.getElementById('testEmailButton').addEventListener('click', function () {
    ErpUI.busy(this, send('/api/notifications/test-email', 'POST'))
      .then(function () { say('Test email queued. Check your inbox in a minute.'); setTimeout(loadEmailStatus, 3000); })
      .catch(function (error) { say(error.message, true); });
  });

  document.getElementById('alertRefresh').addEventListener('click', function () {
    ErpUI.busy(this, send('/api/alerts/refresh', 'POST'))
      .then(function (payload) {
        say(payload.refreshed ? 'Checked just now.' : 'Already checked in the last few seconds.');
        return load();
      })
      .catch(function (error) { say(error.message, true); });
  });
  viewSelect.addEventListener('change', load);
  severitySelect.addEventListener('change', load);

  setupPreferences();
  setupThresholdForm().then(function () {
    load();
    loadThresholds();
    loadEmailStatus();
  });
});
