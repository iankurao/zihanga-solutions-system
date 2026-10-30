document.addEventListener('DOMContentLoaded', function () {
  var listNode = document.getElementById('orderList');
  var statusFilter = document.getElementById('orderStatusFilter');
  var message = document.getElementById('ordersMessage');
  var welcome = document.getElementById('ordersWelcome');
  var newForm = document.getElementById('newOrderForm');
  var detailNode = document.getElementById('orderDetail');
  var activeRef = null;

  // ---- helpers -------------------------------------------------------------
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function label(value) {
    return value == null || value === '' ? '—' : String(value).replace(/_/g, ' ');
  }

  function kg(value) {
    if (value == null || value === '') return '—';
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 }) + ' kg';
  }

  var currency = 'KES';
  function money(value) {
    if (value == null || value === '') return '—';
    return currency + ' ' + Number(value).toLocaleString(undefined,
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function when(value, withTime) {
    if (!value) return '—';
    var date = new Date(value.length === 10 ? value + 'T00:00:00' : value);
    var options = { day: 'numeric', month: 'short', year: 'numeric' };
    if (withTime) { options.hour = '2-digit'; options.minute = '2-digit'; }
    return date.toLocaleString(undefined, options);
  }

  // Status badge with the ERP-wide colour meaning (see js/ui.js).
  function pill(status) {
    return ErpUI.badge(status);
  }

  function button(text, className, onClick) {
    var node = el('button', className, text);
    node.type = 'button';
    node.addEventListener('click', onClick);
    return node;
  }

  function input(type, attrs) {
    var node = el('input');
    node.type = type;
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    return node;
  }

  function table(headers, rows) {
    return ErpUI.table(headers, rows);
  }

  function empty(text) {
    return ErpUI.state('empty', { text: text, compact: true });
  }

  function card(iconName, title) {
    var section = el('section', 'erp-card');
    var heading = el('h3', 'erp-card-title');
    var badge = el('span', 'erp-chip');
    badge.appendChild(ErpUI.icon(iconName));
    heading.append(badge, document.createTextNode(title));
    section.appendChild(heading);
    return section;
  }

  async function api(url, options) {
    var response = await fetch(url, Object.assign({ credentials: 'include' }, options || {}));
    var payload = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(payload.message || payload.error || 'Request failed');
    return payload;
  }

  function post(url, body) {
    return api(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
  }

  function put(url, body) {
    return api(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
  }

  function showMessage(text, isError) {
    ErpUI.message(message, text, isError ? 'danger' : 'success');
  }

  // Run an action that returns the updated order, then redraw.
  async function act(control, promise, successText) {
    try {
      var payload = await (control ? ErpUI.busy(control, promise) : promise);
      showMessage(successText, false);
      renderDetail(payload.data);
      loadList();
    } catch (error) {
      showMessage(error.message, true);
    }
  }

  // ---- list ----------------------------------------------------------------
  async function loadList() {
    if (!listNode.children.length) ErpUI.loading(listNode, 'Loading orders…', true);
    try {
      var status = statusFilter.value;
      var payload = await api('/api/orders' + (status ? '?status=' + status : ''));
      listNode.textContent = '';
      if (!payload.data.length) {
        ErpUI.empty(listNode, 'No orders here', status ? 'No ' + ErpUI.humanize(status).toLowerCase() + ' orders.' : 'Create the first customer order.');
        return;
      }
      payload.data.forEach(function (order) {
        if (order.currency) currency = order.currency;
        var item = el('button', 'order-item' + (order.business_id === activeRef ? ' is-active' : ''));
        item.type = 'button';
        var top = el('div', 'order-item-top');
        top.append(el('strong', null, order.business_id), pill(order.status));
        var ordered = Number(order.ordered_kg || 0);
        var dispatched = Number(order.dispatched_kg || 0);
        var bar = el('div', 'order-progress');
        var fill = el('span');
        fill.style.width = (ordered ? Math.min(100, (dispatched / ordered) * 100) : 0) + '%';
        bar.appendChild(fill);
        item.append(
          top,
          el('small', null, order.customer_name + ' · ' + order.farm_name),
          el('small', null, kg(dispatched) + ' of ' + kg(ordered) + ' dispatched' +
            (order.order_value != null ? ' · ' + money(order.order_value) : '')),
          bar
        );
        item.addEventListener('click', function () { openOrder(order.business_id); });
        listNode.appendChild(item);
      });
    } catch (error) {
      ErpUI.error(listNode, error.message, loadList);
    }
  }

  // ---- new order -----------------------------------------------------------
  function addLine() {
    var row = el('div', 'order-line');
    var product = input('text', { list: 'productTypes', placeholder: 'Product: dried_larvae or frass_fertilizer', maxlength: '50', required: '' });
    product.className = 'order-line-product';
    var quantity = input('number', { min: '0.001', step: '0.001', placeholder: 'kg', required: '' });
    quantity.className = 'order-line-qty';
    var price = input('number', { min: '0', step: '0.01', placeholder: currency + ' per kg', required: '' });
    price.className = 'order-line-price';
    price.setAttribute('aria-label', 'Price per kg');
    row.append(product, quantity, price, button('Remove', 'erp-btn erp-btn--danger', function () {
      if (document.querySelectorAll('.order-line').length > 1) row.remove();
    }));
    document.getElementById('orderLines').appendChild(row);
  }

  async function loadCustomers(selectId) {
    var customer = document.getElementById('orderCustomer');
    try {
      var customers = await api('/api/customers');
      var rows = (Array.isArray(customers) ? customers : customers.data || []).slice()
        .sort(function (a, b) { return String(a.name).localeCompare(String(b.name)); });
      customer.replaceChildren(new Option(rows.length ? 'Select customer' : 'No customers yet — add one with New customer', ''));
      rows.forEach(function (c) { customer.add(new Option(c.name, c.id)); });
      if (selectId != null) customer.value = String(selectId);
    } catch (error) {
      customer.replaceChildren(new Option('Customers could not be loaded', ''));
    }
  }

  // ---- new customer (a small panel inside the order form) -------------------
  var customerPanel = document.getElementById('newCustomerPanel');
  var customerFields = ['customerName', 'customerContact', 'customerEmail', 'customerAddress']
    .map(function (id) { return document.getElementById(id); });

  function closeCustomerPanel() {
    customerPanel.hidden = true;
    customerFields.forEach(function (field) { field.value = ''; });
  }

  document.getElementById('newCustomerButton').addEventListener('click', function () {
    customerPanel.hidden = false;
    customerFields[0].focus();
  });
  document.getElementById('cancelCustomer').addEventListener('click', closeCustomerPanel);
  document.getElementById('saveCustomer').addEventListener('click', async function () {
    var name = customerFields[0].value.trim();
    if (!name) {
      showMessage('Give the customer a name.', true);
      customerFields[0].focus();
      return;
    }
    if (customerFields[2].value && !customerFields[2].checkValidity()) {
      showMessage('The email address is not valid.', true);
      customerFields[2].focus();
      return;
    }
    try {
      var created = await ErpUI.busy(this, post('/api/customers', {
        name: name,
        contact: customerFields[1].value.trim(),
        email: customerFields[2].value.trim(),
        address: customerFields[3].value.trim()
      }));
      await loadCustomers(created.id);
      closeCustomerPanel();
      showMessage(name + ' added and picked for this order.', false);
    } catch (error) {
      showMessage(error.message, true);
    }
  });

  async function loadFormOptions() {
    var farm = document.getElementById('orderFarm');
    await loadCustomers();
    try {
      var hierarchy = await api('/api/locations/hierarchy');
      var seen = {};
      farm.replaceChildren(new Option('Select farm', ''));
      (hierarchy.data || []).forEach(function (row) {
        if (row.farm_id && row.farm_status === 'active' && !seen[row.farm_id]) {
          seen[row.farm_id] = true;
          farm.add(new Option(row.farm_name, row.farm_id));
        }
      });
    } catch (error) {
      farm.replaceChildren(new Option('Farms could not be loaded', ''));
    }
    try {
      var stock = await api('/api/inventory');
      var list = document.getElementById('productTypes');
      list.textContent = '';
      // The farm's products, with what is free in stock now.
      var free = {};
      (stock.totals || []).forEach(function (total) { free[total.product_type] = total.available_kg; });
      ['dried_larvae', 'frass_fertilizer'].concat(Object.keys(free)).filter(function (type, index, all) {
        return all.indexOf(type) === index;
      }).forEach(function (type) {
        var option = el('option');
        option.value = type;
        option.label = type in free ? kg(free[type]) + ' free' : 'none in stock';
        list.appendChild(option);
      });
    } catch (error) { /* suggestions are optional */ }
  }

  document.getElementById('newOrderButton').addEventListener('click', function () {
    activeRef = null;
    welcome.hidden = true;
    detailNode.hidden = true;
    newForm.hidden = false;
    showMessage('');
    if (!document.querySelector('.order-line')) addLine();
    loadFormOptions();
    // On narrow screens the form sits below the order list.
    newForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  document.getElementById('addOrderLine').addEventListener('click', addLine);

  newForm.addEventListener('submit', async function (event) {
    event.preventDefault();
    var submit = newForm.querySelector('button[type="submit"]');
    var lines = [].map.call(document.querySelectorAll('.order-line'), function (row) {
      return {
        product_type: row.querySelector('.order-line-product').value.trim(),
        quantity_kg: row.querySelector('.order-line-qty').value,
        unit_price: row.querySelector('.order-line-price').value
      };
    });
    submit.disabled = true;
    try {
      var payload = await post('/api/orders', {
        customer_id: document.getElementById('orderCustomer').value,
        farm_id: document.getElementById('orderFarm').value,
        requested_delivery_date: document.getElementById('orderRequested').value || null,
        customer_reference: document.getElementById('orderReference').value,
        lines: lines
      });
      newForm.reset();
      document.getElementById('orderLines').textContent = '';
      showMessage(payload.data.business_id + ' created. Allocate stock to it below.', false);
      statusFilter.value = 'OPEN';
      renderDetail(payload.data);
      loadList();
    } catch (error) {
      showMessage(error.message, true);
    } finally {
      submit.disabled = false;
    }
  });

  // ---- detail --------------------------------------------------------------
  async function openOrder(ref) {
    try {
      var payload = await api('/api/orders/' + encodeURIComponent(ref));
      showMessage('');
      renderDetail(payload.data);
      loadList();
    } catch (error) {
      showMessage(error.message, true);
    }
  }

  function renderDetail(order) {
    activeRef = order.business_id;
    history.replaceState(null, '', '/orders?ref=' + encodeURIComponent(order.business_id));
    welcome.hidden = true;
    newForm.hidden = true;
    detailNode.hidden = false;
    detailNode.textContent = '';
    var open = order.status === 'OPEN';
    var base = '/api/orders/' + encodeURIComponent(order.business_id);
    if (order.totals.currency) currency = order.totals.currency;

    // Header
    var summary = el('section', 'erp-card trace-summary');
    var header = el('div', 'order-header');
    var title = el('div');
    title.append(el('p', 'erp-eyebrow', 'Customer order'), el('h2', null, order.business_id),
      el('p', null, order.customer_name + ' · supplied by ' + order.farm_name));
    var side = el('div', 'trace-summary-side');
    var trace = el('a', 'trace-open', 'Trace order ');
    trace.href = '/traceability?ref=' + encodeURIComponent(order.business_id) + '&type=customer_order';
    trace.appendChild(el('i', 'fas fa-route'));
    side.append(pill(order.status), trace);
    header.append(title, side);
    var facts = el('dl', 'erp-facts');
    [['Order date', when(order.order_date)], ['Requested delivery', when(order.requested_delivery_date)],
      ['Customer reference', order.customer_reference], ['Created by', order.created_by]]
      .concat(order.cancel_reason ? [['Cancelled', order.cancel_reason]] : [])
      .forEach(function (pair) {
        var item = el('div');
        item.append(el('dt', null, pair[0]), el('dd', null, pair[1] || '—'));
        facts.appendChild(item);
      });
    var kpis = el('div', 'erp-kpis order-kpis');
    [['Ordered', order.totals.ordered_kg], ['Reserved', order.totals.allocated_kg],
      ['Dispatched', order.totals.dispatched_kg], ['Delivered', order.totals.delivered_kg]]
      .forEach(function (pair) {
        var tile = el('div', 'erp-kpi');
        tile.append(el('span', null, pair[0]), el('strong', null, kg(pair[1])));
        kpis.appendChild(tile);
      });
    [['Order value', order.totals.order_value], ['Delivered value (revenue)', order.totals.delivered_value]]
      .forEach(function (pair) {
        var tile = el('div', 'erp-kpi');
        tile.append(el('span', null, pair[0]), el('strong', null, money(pair[1])));
        kpis.appendChild(tile);
      });
    summary.append(header, facts, kpis);
    if (order.totals.unpriced_lines) {
      summary.appendChild(el('p', 'erp-hint', order.totals.unpriced_lines +
        ' line(s) have no price yet and are left out of the values. Set a price below.'));
    }
    detailNode.appendChild(summary);

    // Lines and allocation
    var linesCard = card('fa-list-check', 'Order lines');
    var lineRows = order.lines.map(function (line) {
      var actionCell = el('div');
      if (open && Number(line.remaining_to_allocate_kg) > 0) {
        actionCell.appendChild(button('Allocate stock', 'erp-btn erp-btn--secondary erp-btn--sm', function () {
          showStockPicker(order, line, pickerHost);
        }));
      }
      // The price can be set or corrected until anything on the line is dispatched.
      if (order.status !== 'CANCELLED' && Number(line.dispatched_kg) === 0) {
        actionCell.appendChild(button(line.unit_price == null ? 'Set price' : 'Change price',
          'erp-btn erp-btn--secondary erp-btn--sm', function () {
            showReasonForm(actionCell, 'Price per kg (' + currency + ')', function (value, control) {
              act(control, put(base + '/lines/' + line.id + '/price', { unit_price: value }), 'Price saved.');
            });
          }));
      }
      return [line.line_no, line.product_type, kg(line.quantity_kg), money(line.unit_price), money(line.line_value),
        kg(line.outstanding_allocated_kg), kg(line.dispatched_kg), kg(line.remaining_to_allocate_kg), actionCell];
    });
    linesCard.appendChild(table(['#', 'Product', 'Ordered', 'Price / kg', 'Value', 'Reserved', 'Dispatched',
      'To allocate', ''], lineRows));
    var pickerHost = el('div');
    linesCard.appendChild(pickerHost);
    detailNode.appendChild(linesCard);

    // Allocations
    var allocCard = card('fa-boxes-stacked', 'Reserved stock');
    if (!order.allocations.length) {
      allocCard.appendChild(empty('No stock has been reserved for this order yet.'));
    } else {
      allocCard.appendChild(table(
        ['Product lot', 'Location', 'Reserved', 'Dispatched', 'Released', 'Outstanding', ''],
        order.allocations.map(function (a) {
          var lot = el('a', 'erp-link', a.product_lot_business_id);
          lot.href = '/product-lot?ref=' + encodeURIComponent(a.product_lot_business_id);
          var cell = el('div');
          if (Number(a.outstanding_kg) > 0) {
            cell.appendChild(button('Release', 'erp-btn erp-btn--danger erp-btn--sm', function () {
              showReasonForm(cell, 'Reason for releasing ' + kg(a.outstanding_kg), function (reason, control) {
                act(control, post(base + '/allocations/' + a.id + '/release', { reason: reason }), 'Allocation released.');
              });
            }));
          }
          return [lot, a.location_name + ' (' + a.location_code + ')', kg(a.quantity_kg),
            kg(a.dispatched_kg), kg(a.released_kg), kg(a.outstanding_kg), cell];
        })
      ));
    }
    detailNode.appendChild(allocCard);

    // Dispatch
    var dispatchable = order.allocations.filter(function (a) { return Number(a.outstanding_kg) > 0; });
    if (open && dispatchable.length) {
      var dispatchCard = card('fa-truck', 'Dispatch a delivery');
      var qtyInputs = [];
      dispatchCard.appendChild(table(['Product lot', 'Location', 'Outstanding', 'Dispatch now (kg)'],
        dispatchable.map(function (a) {
          var qty = input('number', { min: '0', step: '0.001', max: a.outstanding_kg, value: a.outstanding_kg });
          qty.className = 'qty-input';
          qty.setAttribute('aria-label', 'Quantity to dispatch from ' + a.product_lot_business_id);
          qtyInputs.push({ allocation: a, input: qty });
          return [a.product_lot_business_id, a.location_code, kg(a.outstanding_kg), qty];
        })));
      var form = el('div', 'inline-form');
      var vehicle = input('text', { placeholder: 'Vehicle (optional)', maxlength: '60' });
      var driver = input('text', { placeholder: 'Driver (optional)', maxlength: '100' });
      var dispatchButton = button('Dispatch', 'erp-btn', function () {
        var lines = qtyInputs.filter(function (row) { return Number(row.input.value) > 0; })
          .map(function (row) { return { allocation_id: row.allocation.id, quantity_kg: row.input.value }; });
        if (!lines.length) { showMessage('Enter a quantity to dispatch.', true); return; }
        act(dispatchButton, post(base + '/deliveries', { lines: lines, vehicle: vehicle.value, driver: driver.value }),
          'Delivery dispatched and stock movements posted.');
      });
      form.append(vehicle, driver, dispatchButton);
      dispatchCard.appendChild(form);
      detailNode.appendChild(dispatchCard);
    }

    // Deliveries
    var deliveryCard = card('fa-clipboard-check', 'Deliveries');
    if (!order.deliveries.length) {
      deliveryCard.appendChild(empty('Nothing has been dispatched for this order.'));
    } else {
      deliveryCard.appendChild(table(
        ['Delivery', 'Status', 'Dispatched', 'Quantity', 'Lots', 'Received', ''],
        order.deliveries.map(function (d) {
          var ref = el('a', 'erp-link', d.business_id);
          ref.href = '/traceability?ref=' + encodeURIComponent(d.business_id) + '&type=delivery';
          ref.title = 'Trace this delivery back to its waste lots';
          var cell = el('div');
          if (d.status === 'DISPATCHED') {
            cell.appendChild(button('Confirm delivered', 'erp-btn erp-btn--secondary erp-btn--sm', function () {
              showReasonForm(cell, 'Received by', function (receivedBy, control) {
                act(control, post('/api/deliveries/' + encodeURIComponent(d.business_id) + '/confirm',
                  { received_by: receivedBy }), d.business_id + ' confirmed as delivered.');
              });
            }));
          }
          var lots = (d.lines || []).map(function (l) {
            return l.product_lot_business_id + ' ' + kg(l.quantity_kg);
          }).join(', ');
          return [ref, pill(d.status), when(d.dispatched_at, true), kg(d.quantity_kg), lots,
            d.received_by ? d.received_by + ' · ' + when(d.delivered_at, true) : '—', cell];
        })
      ));
    }
    detailNode.appendChild(deliveryCard);

    // Cancel
    if (open && !order.deliveries.length) {
      var cancelCard = card('fa-ban', 'Cancel order');
      cancelCard.appendChild(el('p', 'erp-hint', 'Cancelling releases all reserved stock back to inventory.'));
      var cancelForm = el('div', 'inline-form');
      var reason = input('text', { placeholder: 'Reason for cancelling', maxlength: '500' });
      var cancelButton = button('Cancel order', 'erp-btn erp-btn--danger', function () {
        if (!reason.value.trim()) {
          reason.setAttribute('aria-invalid', 'true');
          showMessage('Enter a reason to cancel the order.', true);
          return;
        }
        reason.removeAttribute('aria-invalid');
        ErpUI.confirm({
          title: 'Cancel ' + order.business_id + '?',
          text: 'All stock reserved for this order goes back to free stock. This cannot be undone.',
          confirmLabel: 'Cancel order',
          cancelLabel: 'Keep order',
          danger: true
        }).then(function (confirmed) {
          if (confirmed) act(cancelButton, post(base + '/cancel', { reason: reason.value }), order.business_id + ' cancelled.');
        });
      });
      cancelForm.append(reason, cancelButton);
      cancelCard.appendChild(cancelForm);
      detailNode.appendChild(cancelCard);
    }
  }

  function showReasonForm(host, placeholder, onSubmit) {
    host.textContent = '';
    var form = el('div', 'inline-form');
    var field = input('text', { placeholder: placeholder, maxlength: '500' });
    field.setAttribute('aria-label', placeholder);
    var ok = button('Save', 'erp-btn', function () {
      if (!field.value.trim()) { showMessage(placeholder + ' is required.', true); return; }
      onSubmit(field.value.trim(), ok);
    });
    form.append(field, ok);
    host.appendChild(form);
    field.focus();
  }

  async function showStockPicker(order, line, host) {
    host.textContent = '';
    var picker = el('div', 'stock-picker');
    picker.appendChild(el('p', 'erp-subhead',
      'Free ' + line.product_type + ' stock on ' + order.farm_name + ' (oldest lots first) · ' +
      kg(line.remaining_to_allocate_kg) + ' still to allocate'));
    host.appendChild(picker);
    try {
      var payload = await api('/api/orders/' + encodeURIComponent(order.business_id) +
        '/available-stock?line_id=' + line.id);
      if (!payload.data.length) {
        picker.appendChild(empty('No free, QC-released ' + line.product_type + ' stock on this farm.'));
        return;
      }
      // Suggest amounts oldest lot first, only until the line is covered.
      var remaining = Number(line.remaining_to_allocate_kg);
      picker.appendChild(table(['Product lot', 'Produced', 'Location', 'On hand', 'Reserved', 'Free', 'Allocate (kg)', ''],
        payload.data.map(function (row) {
          var suggested = Math.max(0, Math.min(remaining, Number(row.free_kg)));
          remaining -= suggested;
          var qty = input('number', {
            min: '0.001', step: '0.001',
            value: suggested > 0 ? suggested.toFixed(3) : ''
          });
          qty.className = 'qty-input';
          qty.setAttribute('aria-label', 'Quantity to allocate from ' + row.product_lot_business_id);
          var allocateButton = button('Allocate', 'erp-btn erp-btn--sm', function () {
            act(allocateButton, post('/api/orders/' + encodeURIComponent(order.business_id) + '/allocations', {
              order_line_id: line.id, product_lot_id: row.product_lot_id,
              location_id: row.location_id, quantity_kg: qty.value
            }), 'Stock reserved for ' + order.business_id + '.');
          });
          return [row.product_lot_business_id, when(row.production_date), row.facility_name + ' — ' + row.location_name,
            kg(row.on_hand_kg), kg(row.reserved_kg), kg(row.free_kg), qty, allocateButton];
        })));
    } catch (error) {
      picker.appendChild(empty(error.message));
    }
  }

  statusFilter.addEventListener('change', loadList);
  loadList();
  var initial = new URLSearchParams(window.location.search).get('ref');
  if (initial) openOrder(initial);
});
