document.addEventListener('DOMContentLoaded', function () {
  var form = document.getElementById('traceForm');
  var refInput = document.getElementById('traceRef');
  var typeSelect = document.getElementById('traceType');
  var suggestions = document.getElementById('traceSuggestions');
  var message = document.getElementById('traceMessage');
  var result = document.getElementById('traceResult');

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function label(value) {
    return value == null || value === '' ? '—' : String(value).replace(/_/g, ' ');
  }

  function kg(value, unit) {
    if (value == null) return null;
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 }) + ' ' + (unit || 'kg');
  }

  function when(value) {
    if (!value) return null;
    var date = new Date(value.length === 10 ? value + 'T00:00:00' : value);
    return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function tone(status) {
    var value = String(status || '').toLowerCase();
    if (/(fail|reject|revok|blocked|cancel|alert|quarantin)/.test(value)) return ' is-bad';
    if (/(pending|paused|draft|planned)/.test(value)) return ' is-warn';
    return '';
  }

  // ---- summary -------------------------------------------------------------
  function renderSummary(data) {
    var root = data.root;
    document.getElementById('traceRootType').textContent = root.type_label.toUpperCase();
    document.getElementById('traceRootRef').textContent = root.ref;
    document.getElementById('traceRootTitle').textContent = root.title || '';
    var status = document.getElementById('traceRootStatus');
    status.textContent = label(root.status);
    status.className = 'b360-pill' + tone(root.status);
    status.hidden = !root.status;
    var link = document.getElementById('traceRootLink');
    link.hidden = !root.href;
    if (root.href) link.href = root.href;
    // Orders and deliveries are not physical items, so they get no label.
    var labelLink = document.getElementById('traceLabelLink');
    var labelled = ['customer_order', 'delivery'].indexOf(root.type) === -1;
    labelLink.hidden = !labelled;
    if (labelled) labelLink.href = '/labels?type=' + root.type + '&ref=' + encodeURIComponent(root.ref);

    var facts = document.getElementById('traceRootFacts');
    facts.textContent = '';
    var details = root.details || {};
    [
      ['Date', when(root.occurred)],
      ['Quantity', kg(root.quantity, root.unit)],
      ['Recorded by', root.actor],
      ['Farm / site / facility', root.location || 'Unassigned (legacy record)'],
      ['QC status', details.qc_status || details.qc],
      ['QC decision', details.approval],
      ['Quality', details.quality_status],
      ['Source type', details.source_type]
    ].forEach(function (pair) {
      if (pair[1] == null || pair[1] === '') return;
      var item = el('div');
      item.append(el('dt', null, pair[0]), el('dd', null, label(pair[1])));
      facts.appendChild(item);
    });

    var counts = data.counts;
    var text = counts.upstream + ' upstream and ' + counts.downstream + ' downstream records linked.';
    if (counts.restricted) {
      text += ' ' + counts.restricted + ' belong to locations you cannot access and are shown without details.';
    }
    document.getElementById('traceCounts').textContent = text;
    document.getElementById('traceTruncated').hidden = !data.truncated;
  }

  // ---- flow ----------------------------------------------------------------
  function renderFlow(data) {
    var nodesByKey = {};
    data.stages.forEach(function (stage) {
      stage.nodes.forEach(function (node) { nodesByKey[node.key] = node; });
    });
    var incoming = {};
    data.edges.forEach(function (edge) {
      (incoming[edge.to] = incoming[edge.to] || []).push(edge);
    });

    var flow = document.getElementById('traceFlow');
    flow.textContent = '';
    data.stages.forEach(function (stage) {
      var column = el('section', 'trace-column');
      var heading = el('h4');
      heading.append(el('span', null, stage.label), el('span', null, String(stage.nodes.length)));
      column.appendChild(heading);
      if (!stage.nodes.length) column.appendChild(el('p', 'trace-none', 'None recorded'));
      stage.nodes.forEach(function (node) {
        if (node.is_root) column.classList.add('has-root');
        column.appendChild(nodeCard(node, incoming[node.key] || [], nodesByKey));
      });
      flow.appendChild(column);
    });

  }

  function nodeCard(node, edgesIn, nodesByKey) {
    var classes = 'trace-node';
    if (node.is_root) classes += ' is-root';
    else if (node.restricted) classes += ' is-restricted';
    else if (node.direction === 'upstream') classes += ' is-upstream';
    var card = el('button', classes);
    card.type = 'button';

    if (node.restricted) {
      card.disabled = true;
      card.append(el('strong', null, 'Restricted record'),
        el('small', null, 'Another location — no access'));
      return card;
    }

    card.appendChild(el('strong', null, node.ref));
    var line = [node.title, label(node.status)].filter(function (part) {
      return part && part !== '—';
    }).join(' · ');
    if (line) card.appendChild(el('small', null, line));
    var meta = [when(node.occurred), node.type === 'inventory_location' ? null : kg(node.quantity, node.unit)]
      .filter(Boolean).join(' · ');
    if (meta) card.appendChild(el('small', null, meta));

    if (edgesIn.length) {
      var links = el('div', 'trace-links');
      edgesIn.forEach(function (edge) {
        var source = nodesByKey[edge.from];
        var name = !source ? '—' : source.restricted ? 'restricted record' : source.ref;
        var quantity = kg(edge.quantity, edge.unit);
        var verb = node.type === 'inventory_location' ? 'holds ' : 'from ';
        var text = node.type === 'inventory_location'
          ? verb + (quantity || '—') + ' of ' + name
          : verb + name + (quantity ? ' · ' + quantity : '');
        links.appendChild(el('small', null, text));
      });
      card.appendChild(links);
    }

    if (node.is_root) {
      card.setAttribute('aria-current', 'true');
    } else if (node.type !== 'inventory_location') {
      card.title = 'Trace from ' + node.ref;
      card.addEventListener('click', function () {
        refInput.value = node.ref;
        typeSelect.value = node.type;
        trace(node.ref, node.type);
      });
    } else {
      card.disabled = true;
    }
    return card;
  }

  // ---- links table ---------------------------------------------------------
  function renderEdges(data) {
    var target = document.getElementById('traceEdges');
    target.textContent = '';
    var nodesByKey = {};
    data.stages.forEach(function (stage) {
      stage.nodes.forEach(function (node) { nodesByKey[node.key] = node; });
    });
    if (!data.edges.length) {
      target.appendChild(el('p', 'b360-empty', 'This record has no recorded links to other records yet.'));
      return;
    }
    function name(key) {
      var node = nodesByKey[key];
      if (!node) return '—';
      return node.restricted ? node.type_label + ' (restricted)' : node.type_label + ' ' + node.ref;
    }
    var wrap = el('div', 'b360-table-wrap');
    var table = el('table', 'b360-table');
    var head = el('tr');
    ['From', 'To', 'Quantity'].forEach(function (text) { head.appendChild(el('th', null, text)); });
    var thead = el('thead');
    thead.appendChild(head);
    var tbody = el('tbody');
    data.edges.forEach(function (edge) {
      var row = el('tr');
      row.append(el('td', null, name(edge.from)), el('td', null, name(edge.to)),
        el('td', null, kg(edge.quantity, edge.unit) || '—'));
      tbody.appendChild(row);
    });
    table.append(thead, tbody);
    wrap.appendChild(table);
    target.appendChild(wrap);
  }

  // ---- loading -------------------------------------------------------------
  async function trace(ref, type) {
    var value = String(ref || '').trim();
    if (!value) return;
    message.textContent = 'Tracing ' + value + '…';
    try {
      var url = '/api/traceability?ref=' + encodeURIComponent(value) + (type ? '&type=' + encodeURIComponent(type) : '');
      var response = await fetch(url, { credentials: 'include' });
      var payload = await response.json();
      if (!response.ok) throw new Error(payload.message || payload.error || 'Could not trace this record.');
      renderSummary(payload.data);
      renderFlow(payload.data);
      renderEdges(payload.data);
      result.hidden = false;
      message.textContent = '';
      document.title = payload.data.root.ref + ' · Traceability | Zehunger';
      history.replaceState(null, '', '/traceability?ref=' + encodeURIComponent(payload.data.root.ref) +
        '&type=' + encodeURIComponent(payload.data.root.type));
    } catch (error) {
      result.hidden = true;
      message.textContent = error.message;
    }
  }

  var suggestTimer = null;
  refInput.addEventListener('input', function () {
    clearTimeout(suggestTimer);
    var query = refInput.value.trim();
    if (query.length < 2) return;
    suggestTimer = setTimeout(async function () {
      try {
        var response = await fetch('/api/traceability/search?q=' + encodeURIComponent(query), {
          credentials: 'include'
        });
        var payload = await response.json();
        if (!response.ok) return;
        suggestions.textContent = '';
        (payload.data || []).forEach(function (item) {
          var option = el('option');
          option.value = item.ref;
          option.label = item.type_label;
          suggestions.appendChild(option);
        });
      } catch (error) {
        console.error('Suggestion lookup failed', error);
      }
    }, 200);
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    trace(refInput.value, typeSelect.value);
  });

  var params = new URLSearchParams(window.location.search);
  if (params.get('ref')) {
    refInput.value = params.get('ref');
    typeSelect.value = params.get('type') || '';
    trace(params.get('ref'), params.get('type'));
  }
});
