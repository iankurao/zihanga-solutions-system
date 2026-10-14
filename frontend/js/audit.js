// Audit log viewer (super admins). All record text is set with textContent.
document.addEventListener('DOMContentLoaded', function () {
  var form = document.getElementById('auditForm');
  var rowsBody = document.getElementById('auditRows');
  var message = document.getElementById('auditMessage');
  var more = document.getElementById('auditMore');
  var typeSelect = document.getElementById('auditType');
  var nextBefore = null;
  var shown = 0;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function when(value) {
    var date = new Date(value);
    return isNaN(date) ? String(value) : date.toLocaleString(undefined, {
      day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
  }

  function show(value) {
    if (value === null || value === undefined) return '—';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }

  // One line per changed field: "status: ACTIVE → HARVESTED".
  function changeList(entry) {
    var list = el('ul', 'audit-changes');
    var before = entry.old_value || {};
    var after = entry.new_value || {};
    var keys = Object.keys(Object.assign({}, before, after));
    // Events (sign-ins, refusals) and new records have no previous value.
    var created = entry.action.endsWith('.created') || entry.old_value == null;
    var deleted = entry.action.endsWith('.deleted');
    keys.slice(0, 12).forEach(function (key) {
      var item = el('li');
      item.appendChild(el('span', 'audit-key', key + ': '));
      if (created) {
        item.appendChild(document.createTextNode(show(after[key])));
      } else if (deleted) {
        item.appendChild(document.createTextNode(show(before[key])));
      } else {
        item.appendChild(el('span', 'audit-old', show(before[key])));
        item.appendChild(document.createTextNode(' → '));
        item.appendChild(document.createTextNode(show(after[key])));
      }
      list.appendChild(item);
    });
    if (keys.length > 12) list.appendChild(el('li', 'audit-more', '+' + (keys.length - 12) + ' more fields'));
    if (entry.reason) {
      var reason = el('li', 'audit-reason');
      reason.appendChild(el('span', 'audit-key', 'reason: '));
      reason.appendChild(document.createTextNode(entry.reason));
      list.appendChild(reason);
    }
    return list;
  }

  function row(entry) {
    var tr = el('tr');
    var whenCell = el('td', 'audit-when', when(entry.occurred_at));
    tr.appendChild(whenCell);

    var who = el('td');
    who.appendChild(el('strong', null, entry.actor_username || 'system'));
    if (entry.actor_role) who.appendChild(el('small', null, entry.actor_role));
    if (entry.ip_address) who.appendChild(el('small', 'audit-ip', entry.ip_address));
    who.title = entry.user_agent || '';
    tr.appendChild(who);

    var action = el('td');
    var tag = el('span', 'audit-action', entry.action);
    if (/^(security\.|auth\.sign_in_failed|auth\.sign_in_throttled)/.test(entry.action)) tag.classList.add('is-warning');
    if (/\.deleted$/.test(entry.action)) tag.classList.add('is-danger');
    action.appendChild(tag);
    tr.appendChild(action);

    var record = el('td');
    record.appendChild(el('strong', null, entry.entity_ref || entry.entity_id || '—'));
    record.appendChild(el('small', null, entry.entity_type + (entry.entity_id ? ' #' + entry.entity_id : '')));
    tr.appendChild(record);

    var change = el('td');
    change.appendChild(changeList(entry));
    tr.appendChild(change);
    return tr;
  }

  function query(before) {
    var params = new URLSearchParams();
    var fields = { entity_type: 'auditType', record: 'auditRecord', actor: 'auditActor',
                   action: 'auditAction', from: 'auditFrom', to: 'auditTo' };
    Object.keys(fields).forEach(function (key) {
      var value = document.getElementById(fields[key]).value.trim();
      if (value) params.set(key, value);
    });
    if (before) params.set('before', before);
    return params.toString();
  }

  async function load(append) {
    ErpUI.message(message, '');
    try {
      var response = await fetch('/api/audit?' + query(append ? nextBefore : null), { credentials: 'include' });
      var payload = await response.json();
      if (!response.ok) throw new Error(payload.message || 'Could not load the audit log');
      if (!append) { rowsBody.textContent = ''; shown = 0; }
      payload.data.forEach(function (entry) { rowsBody.appendChild(row(entry)); });
      shown += payload.data.length;
      if (!append && !payload.data.length) {
        var empty = el('tr');
        var cell = el('td');
        cell.appendChild(ErpUI.state('empty', { title: 'No entries', text: 'No entries match these filters.', compact: true }));
        cell.colSpan = 5;
        empty.appendChild(cell);
        rowsBody.appendChild(empty);
      }
      nextBefore = payload.next_before;
      more.hidden = !nextBefore;
      document.getElementById('auditShown').textContent = !shown ? ''
        : nextBefore ? 'Showing the newest ' + shown + ' entries' : 'Showing all ' + shown + ' entries';
      var current = typeSelect.value;
      if (typeSelect.options.length === 1) {
        payload.entity_types.forEach(function (type) { typeSelect.add(new Option(type, type)); });
        typeSelect.value = current;
      }
    } catch (error) {
      ErpUI.message(message, error.message, 'danger');
    }
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    ErpUI.busy(form.querySelector('button[type="submit"]'), load(false));
  });
  more.addEventListener('click', function () { ErpUI.busy(more, load(true)); });

  var params = new URLSearchParams(window.location.search);
  if (params.get('record')) document.getElementById('auditRecord').value = params.get('record');
  ErpUI.loading(rowsBody.appendChild(document.createElement('tr')).appendChild(
    Object.assign(document.createElement('td'), { colSpan: 5 })), 'Loading the audit log…', true);
  load(false);
});
