// Shared UI helpers (design system). Every page renders status badges,
// loading / empty / error states, busy buttons and confirmations through
// these, so they look and behave the same everywhere. All text is set with
// textContent - never pass HTML.
(function () {
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function icon(name) {
    var i = el('i', 'fas ' + name);
    i.setAttribute('aria-hidden', 'true');
    return i;
  }

  // When something happened, from a date and optional time typed in local
  // farm time. A date alone means now (if it is today) or midday.
  function localOccurredAt(day, time) {
    if (!day) return null;
    if (time) return new Date(day + 'T' + time).toISOString();
    var now = new Date();
    var pad = function (n) { return String(n).padStart(2, '0'); };
    var today = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate());
    return day === today ? now.toISOString() : new Date(day + 'T12:00').toISOString();
  }

  // 'READY_FOR_HARVEST' -> 'Ready for harvest'
  function humanize(value) {
    var text = String(value == null ? '' : value).replace(/_/g, ' ').trim().toLowerCase();
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
  }

  // One meaning per colour across the ERP:
  //   success = done or approved, info = in progress, warning = waiting or
  //   needs attention, danger = failed, stopped or unsafe, neutral = other.
  var TONES = {
    success: ['completed', 'harvested', 'approved', 'released', 'passed', 'delivered',
      'fulfilled', 'resolved', 'available', 'sent', 'healthy'],
    info: ['active', 'monitoring', 'ready_for_harvest', 'drying', 'curing', 'received', 'dispatched',
      'submitted', 'acknowledged', 'info', 'posted', 'low'],
    warning: ['planned', 'paused', 'pending', 'qc_pending', 'draft', 'open', 'snoozed',
      'conditional', 'awaiting decision', 'warning', 'maintenance', 'follow_up', 'medium'],
    danger: ['cancelled', 'failed', 'rejected', 'revoked', 'blocked', 'quarantined',
      'health_alert', 'critical', 'high', 'void', 'voided']
    // Anything else (closed, consumed, superseded, inactive, retired, recorded, ...) is neutral.
  };
  var LOOKUP = {};
  Object.keys(TONES).forEach(function (tone) {
    TONES[tone].forEach(function (status) { LOOKUP[status] = tone; });
  });

  function statusTone(status) {
    var key = String(status == null ? '' : status).trim().toLowerCase();
    if (LOOKUP[key]) return LOOKUP[key];
    if (/(fail|reject|revok|block|cancel|quarantin|critical)/.test(key)) return 'danger';
    if (/(pending|paus|draft|plan|wait|open|snooz)/.test(key)) return 'warning';
    if (/(complete|approv|releas|pass|deliver|fulfil|resolv)/.test(key)) return 'success';
    return 'neutral';
  }

  // Status badge; `text` overrides the label shown (the tone still follows status).
  function badge(status, text) {
    var tone = statusTone(status);
    var node = el('span', 'erp-badge' + (tone === 'neutral' ? '' : ' is-' + tone),
      text != null ? text : humanize(status));
    return node;
  }

  function clear(container) {
    container.textContent = '';
    return container;
  }

  function state(kind, options) {
    options = options || {};
    var box = el('div', 'erp-state erp-state--' + kind + (options.compact ? ' erp-state--compact' : ''));
    if (kind === 'loading') {
      box.setAttribute('role', 'status');
      box.appendChild(el('div', 'erp-spinner'));
      box.appendChild(el('p', null, options.text || 'Loading…'));
      return box;
    }
    box.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    box.appendChild(icon(options.icon || (kind === 'error' ? 'fa-triangle-exclamation' : 'fa-inbox')));
    if (options.title) box.appendChild(el('strong', null, options.title));
    if (options.text) box.appendChild(el('p', null, options.text));
    if (options.actionLabel && options.onAction) {
      var button = el('button', 'erp-btn erp-btn--secondary erp-btn--sm', options.actionLabel);
      button.type = 'button';
      button.addEventListener('click', options.onAction);
      box.appendChild(button);
    } else if (options.actionLabel && options.href) {
      var link = el('a', 'erp-btn erp-btn--secondary erp-btn--sm', options.actionLabel);
      link.href = options.href;
      box.appendChild(link);
    }
    return box;
  }

  function loading(container, text, compact) {
    clear(container).appendChild(state('loading', { text: text, compact: compact }));
  }

  function empty(container, title, text, action) {
    clear(container).appendChild(state('empty', Object.assign({ title: title, text: text }, action || {})));
  }

  function error(container, message, retry) {
    clear(container).appendChild(state('error', {
      title: 'Something went wrong',
      text: message || 'Please try again.',
      actionLabel: retry ? 'Try again' : null,
      onAction: retry
    }));
  }

  // Inline banner for messages above a form or list. tone: info|success|warning|danger
  function message(container, text, tone) {
    clear(container);
    if (!text) { container.hidden = true; return; }
    container.hidden = false;
    var banner = el('div', 'erp-alert is-' + (tone || 'info'));
    banner.setAttribute('role', tone === 'danger' ? 'alert' : 'status');
    var name = { success: 'fa-circle-check', warning: 'fa-triangle-exclamation', danger: 'fa-circle-exclamation' }[tone] || 'fa-circle-info';
    banner.append(icon(name), el('span', null, text));
    container.appendChild(banner);
  }

  // Disable a button and show a spinner while `work` (a promise) runs.
  async function busy(button, work) {
    button.classList.add('is-busy');
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    try {
      return await work;
    } finally {
      button.classList.remove('is-busy');
      button.disabled = false;
      button.removeAttribute('aria-busy');
    }
  }

  // Table from rows of cells (strings, numbers or nodes).
  // columns: [{ label, numeric }] or plain labels.
  function table(columns, rows, caption) {
    var wrap = el('div', 'erp-table-wrap');
    var tableNode = el('table', 'erp-table');
    if (caption) tableNode.appendChild(el('caption', 'sr-only', caption));
    var head = el('tr');
    columns.forEach(function (column) {
      var spec = typeof column === 'string' ? { label: column } : column;
      var th = el('th', spec.numeric ? 'is-num' : null, spec.label);
      th.scope = 'col';
      head.appendChild(th);
    });
    var thead = el('thead');
    thead.appendChild(head);
    var tbody = el('tbody');
    rows.forEach(function (cells) {
      var tr = el('tr');
      cells.forEach(function (cell, index) {
        var spec = typeof columns[index] === 'string' ? {} : (columns[index] || {});
        var td = el('td', spec.numeric ? 'is-num' : null);
        if (cell instanceof Node) td.appendChild(cell);
        else td.textContent = cell == null || cell === '' ? '—' : String(cell);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    tableNode.append(thead, tbody);
    wrap.appendChild(tableNode);
    return wrap;
  }

  // "Load more" pager. Returns the element; call update(hasMore, shownText).
  function pager(onMore) {
    var bar = el('div', 'erp-pager');
    var info = el('span', null, '');
    var button = el('button', 'erp-btn erp-btn--secondary erp-btn--sm', 'Load more');
    button.type = 'button';
    button.addEventListener('click', function () { busy(button, Promise.resolve(onMore())); });
    bar.append(info, button);
    bar.update = function (hasMore, shownText) {
      info.textContent = shownText || '';
      button.hidden = !hasMore;
      bar.hidden = !hasMore && !shownText;
    };
    return bar;
  }

  // Accessible confirmation dialog. Resolves true when confirmed.
  function confirmDialog(options) {
    options = options || {};
    return new Promise(function (resolve) {
      var dialog = el('dialog', 'erp-modal');
      dialog.setAttribute('aria-labelledby', 'erpModalTitle');
      var body = el('div', 'erp-modal-body');
      var title = el('h2', null, options.title || 'Are you sure?');
      title.id = 'erpModalTitle';
      body.appendChild(title);
      if (options.text) body.appendChild(el('p', null, options.text));
      var foot = el('div', 'erp-modal-foot');
      var cancel = el('button', 'erp-btn erp-btn--secondary', options.cancelLabel || 'Cancel');
      var ok = el('button', 'erp-btn' + (options.danger ? ' erp-btn--danger' : ''), options.confirmLabel || 'Confirm');
      cancel.type = ok.type = 'button';
      foot.append(cancel, ok);
      dialog.append(body, foot);
      document.body.appendChild(dialog);
      function done(result) {
        dialog.close();
        dialog.remove();
        resolve(result);
      }
      cancel.addEventListener('click', function () { done(false); });
      ok.addEventListener('click', function () { done(true); });
      dialog.addEventListener('cancel', function (event) { event.preventDefault(); done(false); });
      dialog.showModal();
      cancel.focus();
    });
  }

  window.ErpUI = {
    el: el,
    icon: icon,
    humanize: humanize,
    statusTone: statusTone,
    badge: badge,
    state: state,
    loading: loading,
    empty: empty,
    error: error,
    message: message,
    busy: busy,
    table: table,
    pager: pager,
    confirm: confirmDialog,
    localOccurredAt: localOccurredAt
  };
})();
