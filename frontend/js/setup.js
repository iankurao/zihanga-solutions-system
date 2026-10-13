document.addEventListener('DOMContentLoaded', function () {
  var message = document.getElementById('setupMessage');
  var tree = document.getElementById('locationTree');
  var userSelect = document.getElementById('accessUser');
  var grantForm = document.getElementById('grantForm');
  var model = { organizations: [], farms: [], sites: [], facilities: [], stores: [] };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  async function api(url, method, body) {
    var options = { method: method || 'GET', credentials: 'include' };
    if (body) {
      options.headers = { 'Content-Type': 'application/json' };
      options.body = JSON.stringify(body);
    }
    var response = await fetch(url, options);
    var payload = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      throw new Error(payload.message || payload.error ||
        (response.status === 403 ? 'Only administrators can change farm setup.' : 'Request failed'));
    }
    return payload;
  }

  function say(text, isError) {
    message.textContent = text || '';
    message.style.color = isError ? '' : 'var(--accent)';
  }

  function uniqueBy(rows, key, map) {
    var seen = {};
    var out = [];
    rows.forEach(function (row) {
      if (row[key] != null && !seen[row[key]]) {
        seen[row[key]] = true;
        out.push(map(row));
      }
    });
    return out;
  }

  async function loadModel() {
    var hierarchy = (await api('/api/locations/hierarchy')).data || [];
    var stores = (await api('/api/inventory/locations?include_inactive=1')).data || [];
    model.organizations = uniqueBy(hierarchy, 'organization_id', function (r) {
      return { id: r.organization_id, name: r.organization_name, code: r.organization_code, status: r.organization_status };
    });
    model.farms = uniqueBy(hierarchy, 'farm_id', function (r) {
      return { id: r.farm_id, parent: r.organization_id, name: r.farm_name, code: r.farm_code, status: r.farm_status };
    });
    model.sites = uniqueBy(hierarchy, 'site_id', function (r) {
      return { id: r.site_id, parent: r.farm_id, farm: r.farm_id, name: r.site_name, code: r.site_code, status: r.site_status,
        label: r.farm_name + ' / ' + r.site_name };
    });
    model.facilities = uniqueBy(hierarchy, 'facility_id', function (r) {
      return { id: r.facility_id, parent: r.site_id, site: r.site_id, farm: r.farm_id, name: r.facility_name,
        code: r.facility_code, type: r.facility_type, status: r.facility_status,
        label: r.farm_name + ' / ' + r.site_name + ' / ' + r.facility_name };
    });
    model.stores = stores.map(function (s) {
      return { id: s.id, parent: s.facility_id, name: s.name, code: s.location_code, status: s.status };
    });
  }

  function toggle(kind, item) {
    var next = item.status === 'active' ? 'inactive' : 'active';
    var url = kind === 'store'
      ? '/api/inventory/locations/' + item.id + '/status'
      : '/api/locations/' + kind + '/' + item.id + '/status';
    var button = el('button', null, next === 'inactive' ? 'Deactivate' : 'Reactivate');
    button.type = 'button';
    button.addEventListener('click', function () {
      button.disabled = true;
      api(url, 'POST', { status: next })
        .then(function () { say(item.name + ' is now ' + next + '.'); refresh(); })
        .catch(function (error) { say(error.message, true); button.disabled = false; });
    });
    return button;
  }

  function node(kind, item, detail) {
    var li = el('li');
    var line = el('div', 'setup-node' + (item.status === 'active' ? '' : ' is-inactive'));
    line.append(el('strong', null, item.name), el('small', null, [item.code, detail, item.status].filter(Boolean).join(' · ')),
      toggle(kind, item));
    li.appendChild(line);
    return li;
  }

  function renderTree() {
    tree.textContent = '';
    if (!model.organizations.length) {
      tree.appendChild(el('p', 'b360-empty', 'Nothing set up yet. Start by adding an organization.'));
      return;
    }
    var root = el('ul');
    model.organizations.forEach(function (org) {
      var orgNode = node('organization', org);
      var farms = el('ul');
      model.farms.filter(function (f) { return f.parent === org.id; }).forEach(function (farm) {
        var farmNode = node('farm', farm);
        var sites = el('ul');
        model.sites.filter(function (s) { return s.parent === farm.id; }).forEach(function (site) {
          var siteNode = node('site', site);
          var facilities = el('ul');
          model.facilities.filter(function (f) { return f.parent === site.id; }).forEach(function (facility) {
            var facilityNode = node('facility', facility, facility.type.replace(/_/g, ' '));
            var stores = el('ul');
            model.stores.filter(function (s) { return s.parent === facility.id; }).forEach(function (store) {
              stores.appendChild(node('store', store, 'storage'));
            });
            if (stores.children.length) facilityNode.appendChild(stores);
            facilities.appendChild(facilityNode);
          });
          if (facilities.children.length) siteNode.appendChild(facilities);
          sites.appendChild(siteNode);
        });
        if (sites.children.length) farmNode.appendChild(sites);
        farms.appendChild(farmNode);
      });
      if (farms.children.length) orgNode.appendChild(farms);
      root.appendChild(orgNode);
    });
    tree.appendChild(root);
  }

  function fillSelects() {
    document.querySelectorAll('select[data-options]').forEach(function (select) {
      var rows = model[select.dataset.options].filter(function (r) { return r.status === 'active'; });
      select.replaceChildren(new Option('Select ' + select.dataset.options.replace(/s$/, ''), ''));
      rows.forEach(function (r) { select.add(new Option(r.label || r.name, r.id)); });
    });
    fillGrantTargets();
  }

  function fillGrantTargets() {
    var scope = document.getElementById('grantScope').value;
    var target = document.getElementById('grantTarget');
    var rows = { organization: model.organizations, farm: model.farms, site: model.sites, facility: model.facilities }[scope];
    target.replaceChildren(new Option('Select ' + scope, ''));
    rows.forEach(function (r) { target.add(new Option(r.label || r.name, r.id)); });
  }

  document.querySelectorAll('.setup-form').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var data = {};
      new FormData(form).forEach(function (value, key) { data[key] = value; });
      var url = '/api/locations/' + form.dataset.kind;
      if (form.dataset.kind === 'stores') {
        var facility = model.facilities.find(function (f) { return String(f.id) === data.facility_id; });
        if (!facility) { say('Select a facility.', true); return; }
        url = '/api/inventory/locations';
        data.site_id = facility.site;
        data.farm_id = facility.farm;
      }
      api(url, 'POST', data)
        .then(function () { say('Saved.'); form.reset(); refresh(); })
        .catch(function (error) { say(error.message, true); });
    });
  });

  // ---- user access -----------------------------------------------------------
  async function loadUsers() {
    var payload = await api('/api/admin/farmers');
    var users = Array.isArray(payload) ? payload : payload.data || payload.farmers || [];
    userSelect.replaceChildren(new Option(users.length ? 'Select a user' : 'No users yet', ''));
    users.forEach(function (u) {
      userSelect.add(new Option((u.full_name || u.username) + ' (' + u.email + ')', u.user_id));
    });
  }

  async function loadAccess() {
    var list = document.getElementById('accessList');
    list.textContent = '';
    grantForm.hidden = !userSelect.value;
    if (!userSelect.value) return;
    try {
      var data = (await api('/api/locations/users/' + userSelect.value + '/access')).data;
      var rows = [];
      ['organization', 'farm', 'site', 'facility'].forEach(function (scope) {
        (data[scope] || []).forEach(function (item) { rows.push({ scope: scope, item: item }); });
      });
      if (!rows.length) {
        list.appendChild(el('p', 'b360-empty', 'This user has no location access yet and sees no operational records.'));
        return;
      }
      var ul = el('ul', 'setup-tree');
      rows.forEach(function (row) {
        var li = el('li', 'setup-node');
        var revoke = el('button', null, 'Revoke');
        revoke.type = 'button';
        revoke.addEventListener('click', function () {
          api('/api/locations/access', 'DELETE', { user_id: userSelect.value, scope: row.scope, scope_id: row.item.id })
            .then(function () { say('Access revoked.'); loadAccess(); })
            .catch(function (error) { say(error.message, true); });
        });
        li.append(el('strong', null, row.item.name), el('small', null, row.scope), revoke);
        ul.appendChild(li);
      });
      list.appendChild(ul);
    } catch (error) {
      say(error.message, true);
    }
  }

  userSelect.addEventListener('change', loadAccess);
  document.getElementById('grantScope').addEventListener('change', fillGrantTargets);
  grantForm.addEventListener('submit', function (event) {
    event.preventDefault();
    api('/api/locations/access', 'POST', {
      user_id: userSelect.value,
      scope: document.getElementById('grantScope').value,
      scope_id: document.getElementById('grantTarget').value
    }).then(function () { say('Access granted.'); loadAccess(); })
      .catch(function (error) { say(error.message, true); });
  });

  async function refresh() {
    try {
      await loadModel();
      renderTree();
      fillSelects();
    } catch (error) {
      say(error.message, true);
    }
  }

  refresh();
  loadUsers().catch(function (error) { say(error.message, true); });
});
