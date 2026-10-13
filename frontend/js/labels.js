// QR label printing. QR codes encode only the /scan/<type>/<ID> link.
document.addEventListener('DOMContentLoaded', function () {
  var SVG = 'http://www.w3.org/2000/svg';
  var typeSelect = document.getElementById('labelType');
  var search = document.getElementById('labelSearch');
  var sizeSelect = document.getElementById('labelSize');
  var choices = document.getElementById('labelChoices');
  var sheet = document.getElementById('labelSheet');
  var message = document.getElementById('labelMessage');
  var printButton = document.getElementById('printLabels');
  var rows = [];

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  // Build the QR as plain SVG squares from the library's module matrix.
  function qrSvg(text) {
    var qr = qrcode(0, 'M');
    qr.addData(text);
    qr.make();
    var count = qr.getModuleCount();
    var quiet = 2;
    var size = count + quiet * 2;
    var svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + size + ' ' + size);
    svg.setAttribute('shape-rendering', 'crispEdges');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'QR code');
    var background = document.createElementNS(SVG, 'rect');
    background.setAttribute('width', size);
    background.setAttribute('height', size);
    background.setAttribute('fill', '#fff');
    svg.appendChild(background);
    var path = '';
    for (var r = 0; r < count; r++) {
      for (var c = 0; c < count; c++) {
        if (qr.isDark(r, c)) path += 'M' + (c + quiet) + ',' + (r + quiet) + 'h1v1h-1z';
      }
    }
    var dark = document.createElementNS(SVG, 'path');
    dark.setAttribute('d', path);
    dark.setAttribute('fill', '#000');
    svg.appendChild(dark);
    return svg;
  }

  function label(row) {
    var card = el('div', 'qr-label is-' + sizeSelect.value);
    card.appendChild(qrSvg(row.scan_url));
    var text = el('div', 'qr-label-text');
    text.append(el('span', 'qr-kind', row.kind), el('strong', null, row.ref));
    [row.line1, row.line2, row.farm].forEach(function (line) {
      if (line) text.appendChild(el('span', null, line));
    });
    card.appendChild(text);
    return card;
  }

  function renderSheet() {
    sheet.textContent = '';
    var selected = rows.filter(function (row, i) {
      var box = document.getElementById('labelPick' + i);
      return box && box.checked;
    });
    selected.forEach(function (row) { sheet.appendChild(label(row)); });
    printButton.disabled = !selected.length;
    printButton.textContent = '';
    printButton.append(el('i', 'fas fa-print'),
      document.createTextNode(' Print ' + (selected.length ? selected.length + ' label' + (selected.length === 1 ? '' : 's') : 'selected')));
  }

  function renderChoices(preselectAll) {
    choices.textContent = '';
    if (!rows.length) {
      choices.appendChild(el('p', 'b360-empty', 'No records of this type that you can label.'));
    }
    rows.forEach(function (row, i) {
      var item = el('label', 'label-choice');
      var box = el('input');
      box.type = 'checkbox';
      box.id = 'labelPick' + i;
      box.checked = !!preselectAll;
      box.addEventListener('change', renderSheet);
      item.append(box, el('strong', null, row.ref), el('small', null, [row.line1, row.line2].filter(Boolean).join(' · ')));
      choices.appendChild(item);
    });
    renderSheet();
  }

  async function load(refs) {
    var params = new URLSearchParams();
    if (refs) params.set('refs', refs);
    else if (search.value.trim()) params.set('q', search.value.trim());
    message.textContent = '';
    try {
      var response = await fetch('/api/labels/' + typeSelect.value + '?' + params.toString(), { credentials: 'include' });
      var payload = await response.json();
      if (!response.ok) throw new Error(payload.message || 'Could not load records');
      rows = payload.data;
      renderChoices(!!refs);
      if (refs && !rows.length) message.textContent = 'That record is not available to you.';
    } catch (error) {
      message.textContent = error.message;
    }
  }

  document.getElementById('labelForm').addEventListener('submit', function (event) {
    event.preventDefault();
    load();
  });
  typeSelect.addEventListener('change', function () { search.value = ''; load(); });
  sizeSelect.addEventListener('change', renderSheet);
  document.getElementById('selectAll').addEventListener('click', function () {
    choices.querySelectorAll('input[type="checkbox"]').forEach(function (box) { box.checked = true; });
    renderSheet();
  });
  printButton.addEventListener('click', function () { window.print(); });

  var params = new URLSearchParams(window.location.search);
  (async function init() {
    try {
      var response = await fetch('/api/labels', { credentials: 'include' });
      var payload = await response.json();
      payload.data.forEach(function (type) { typeSelect.add(new Option(type.title, type.key)); });
    } catch (error) {
      message.textContent = 'Could not load label types.';
      return;
    }
    var requested = params.get('type');
    if (requested && [].some.call(typeSelect.options, function (o) { return o.value === requested; })) {
      typeSelect.value = requested;
    } else {
      typeSelect.value = 'production_batch';
    }
    load(params.get('ref') || null);
  })();
});
