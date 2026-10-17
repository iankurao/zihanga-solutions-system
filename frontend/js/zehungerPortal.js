'use strict';

// ── State ──────────────────────────────────────────────────────────────────
let allFarmers = [];
let filteredFarmers = [];
let currentSection = 'overview';
let currentDays = 0;
let statusFilter = 'all';
let productionChart = null;

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  loadAdminInfo();
  loadOverview(0);
  loadFarmers();
  loadActivity();
  loadInactiveFarmers(14);
});

// ── Section Navigation ────────────────────────────────────────────────────
function showSection(name) {
  ['overview', 'farmers', 'activity'].forEach(function (s) {
    var el = document.getElementById('section-' + s);
    if (el) el.style.display = s === name ? '' : 'none';
  });
  document.querySelectorAll('.sidebar-link[data-section]').forEach(function (btn) {
    btn.classList.toggle('active', btn.dataset.section === name);
  });
  currentSection = name;
  if (name === 'activity') renderActivityFull();
  if (name === 'farmers') renderFarmersFull();
}

// ── Admin Info ────────────────────────────────────────────────────────────
async function loadAdminInfo() {
  try {
    var res = await fetch('/api/admin/me', { credentials: 'include' });
    var data = await res.json();
    if (data.success) {
      // The shared ERP app bar shows the signed-in user; older layouts had their own badge.
      var name = data.data.full_name || data.data.username;
      var nameNode = document.getElementById('adminName');
      var initialsNode = document.getElementById('adminInitials');
      if (nameNode) nameNode.textContent = name;
      if (initialsNode) {
        initialsNode.textContent = name.split(' ').map(function (n) { return n[0]; }).join('').substring(0, 2).toUpperCase();
      }
    }
  } catch (e) { /* silently ignore */ }
}

// ── Date Range Filter ─────────────────────────────────────────────────────
function setDateFilter(days, btn) {
  currentDays = days;
  document.querySelectorAll('.filter-btn').forEach(function (b) { b.classList.remove('active'); });
  if (btn) btn.classList.add('active');
  loadOverview(days);
}

// ── Overview Stats ────────────────────────────────────────────────────────
async function loadOverview(days) {
  try {
    var url = '/api/admin/overview' + (days > 0 ? '?days=' + days : '');
    var res = await fetch(url, { credentials: 'include' });
    var data = await res.json();
    if (!data.success) return;
    var d = data.data;
    document.getElementById('statsGrid').innerHTML = [
      stat('fa-tractor',     'green', d.active_farmers + ' of ' + d.total_farmers, 'Active Farmers'),
      stat('fa-users',       'blue',  d.active_accounts + ' of ' + d.total_accounts, 'Active Team Accounts'),
      stat('fa-recycle',     'amber', fmt(d.total_waste_kg) + ' kg',     'Waste Collected'),
      stat('fa-seedling',    'navy',  fmt(d.total_harvest_kg) + ' kg',   'Larvae Harvested'),
      stat('fa-box',         'teal',  fmt(d.total_dried_kg) + ' kg',     'Dried Output'),
      stat('fa-truck',       'rose',  fmt(d.total_delivered_kg) + ' kg', 'Delivered to Customers'),
      // Revenue is counted when a delivery is confirmed (delivered kg x price).
      stat('fa-coins',       'green', d.currency + ' ' + Number(d.total_revenue || 0).toLocaleString(undefined,
        { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
        'Revenue (delivered)' + (d.total_unpriced_delivered_kg > 0
          ? ' · excl. ' + fmt(d.total_unpriced_delivered_kg) + ' kg without a price' : '')),
    ].join('');
  } catch (e) {
    console.error('Overview error:', e);
  }
}

function stat(icon, color, value, label) {
  return '<div class="stat-card">' +
    '<div class="stat-icon ' + color + '"><i class="fas ' + icon + '"></i></div>' +
    '<div class="stat-info">' +
      '<div class="stat-value">' + value + '</div>' +
      '<div class="stat-label">' + label + '</div>' +
    '</div>' +
  '</div>';
}

// ── Inactive Farmer Alert ─────────────────────────────────────────────────
async function loadInactiveFarmers(days) {
  try {
    var res = await fetch('/api/admin/inactive-farmers?days=' + days, { credentials: 'include' });
    var data = await res.json();
    renderInactiveAlert(data.data || [], days);
  } catch (e) {
    console.error('Inactive farmers error:', e);
  }
}

function renderInactiveAlert(farmers, days) {
  var el = document.getElementById('inactiveAlert');
  if (!el) return;
  if (!farmers.length) {
    el.style.display = 'none';
    return;
  }
  el.style.display = '';
  var names = farmers.slice(0, 3).map(function (f) {
    return '<span class="inactive-tag" onclick="openFarmerById(' + Number(f.user_id) + ')">' +
      esc(f.full_name || f.username) + '</span>';
  }).join('');
  var extra = farmers.length > 3 ? ' <span style="color:var(--amber);font-weight:600;">+' + (farmers.length - 3) + ' more</span>' : '';
  el.innerHTML =
    '<div class="alert-icon"><i class="fas fa-exclamation-triangle"></i></div>' +
    '<div class="alert-body">' +
      '<strong>' + farmers.length + (farmers.length > 1 ? ' people who record' : ' person who records') +
        ' production with no data in ' + days + '+ days</strong>' +
      '<div class="alert-names">' + names + extra + '</div>' +
    '</div>' +
    '<div class="alert-actions">' +
      '<select class="alert-days-select" onchange="loadInactiveFarmers(this.value)">' +
        '<option value="7"' + (days==7?' selected':'') + '>7 days</option>' +
        '<option value="14"' + (days==14?' selected':'') + '>14 days</option>' +
        '<option value="30"' + (days==30?' selected':'') + '>30 days</option>' +
      '</select>' +
    '</div>';
}

// ── Farmers ───────────────────────────────────────────────────────────────
async function loadFarmers() {
  try {
    var res = await fetch('/api/admin/farmers', { credentials: 'include' });
    var data = await res.json();
    if (!data.success) return;
    allFarmers = data.data;
    applyFilters();
    document.getElementById('farmerCount').textContent = allFarmers.length;
    renderLeaderboard(allFarmers);
    renderProductionChart(allFarmers);
  } catch (e) {
    console.error('Farmers error:', e);
  }
}

function applyFilters() {
  var q = (document.getElementById('farmerSearch') ? document.getElementById('farmerSearch').value : '').toLowerCase();
  filteredFarmers = allFarmers.filter(function (f) {
    var matchSearch = !q ||
      (f.full_name || '').toLowerCase().includes(q) ||
      f.username.toLowerCase().includes(q) ||
      (f.email || '').toLowerCase().includes(q);
    var matchStatus = statusFilter === 'all' ||
      (statusFilter === 'active' && f.is_active) ||
      (statusFilter === 'inactive' && !f.is_active);
    return matchSearch && matchStatus;
  });
  renderFarmersOverview(filteredFarmers);
  renderFarmersFull();
}

function setStatusFilter(val) {
  statusFilter = val;
  document.querySelectorAll('.status-btn').forEach(function (b) {
    b.classList.toggle('active', b.dataset.status === val);
  });
  applyFilters();
}

function filterFarmers() { applyFilters(); }
function filterFarmers2() {
  var q = (document.getElementById('farmerSearch2').value || '').toLowerCase();
  var base = allFarmers.filter(function (f) {
    var matchStatus = statusFilter === 'all' ||
      (statusFilter === 'active' && f.is_active) ||
      (statusFilter === 'inactive' && !f.is_active);
    var matchSearch = !q ||
      (f.full_name || '').toLowerCase().includes(q) ||
      f.username.toLowerCase().includes(q) ||
      (f.email || '').toLowerCase().includes(q);
    return matchSearch && matchStatus;
  });
  renderFarmersList2(base);
}

function renderFarmersOverview(farmers) {
  var tbody = document.getElementById('farmerTableBody');
  if (!farmers.length) {
    tbody.innerHTML = '<tr><td colspan="7"><div class="empty-state"><i class="fas fa-users"></i><p>No team members found.</p></div></td></tr>';
    return;
  }
  tbody.innerHTML = farmers.map(function (f) {
    var active = f.is_active;
    return '<tr onclick="openFarmerById(' + Number(f.user_id) + ')">' +
      '<td><div class="farmer-name">' + esc(f.full_name || f.username) + '</div><div class="farmer-email">' + esc(f.email) + ' · ' + esc(roleLabel(f.role)) + '</div></td>' +
      '<td>' + statusBadge(active) + '</td>' +
      '<td style="font-size:.8rem;color:var(--slate-mid);">' + relDate(f.last_activity || f.last_login) + '</td>' +
      '<td><span class="metric-pill">' + fmt(f.total_waste_kg) + '</span></td>' +
      '<td><span class="metric-pill">' + fmt(f.total_harvest_kg) + '</span></td>' +
      '<td><span class="metric-pill">' + fmt(f.total_dried_kg) + '</span></td>' +
      '<td onclick="event.stopPropagation();" style="white-space:nowrap;">' +
        '<button class="btn-detail" onclick="openFarmerById(' + Number(f.user_id) + ')">View</button> ' +
        '<button class="toggle-btn ' + (active ? 'deactivate' : 'activate') + '" onclick="toggleFarmer(' + Number(f.user_id) + ', this)">' +
          (active ? 'Deactivate' : 'Activate') +
        '</button>' +
      '</td>' +
    '</tr>';
  }).join('');
}

function renderFarmersFull() {
  var q = document.getElementById('farmerSearch2') ? document.getElementById('farmerSearch2').value.toLowerCase() : '';
  var base = allFarmers.filter(function (f) {
    var matchStatus = statusFilter === 'all' ||
      (statusFilter === 'active' && f.is_active) ||
      (statusFilter === 'inactive' && !f.is_active);
    var matchSearch = !q ||
      (f.full_name || '').toLowerCase().includes(q) ||
      f.username.toLowerCase().includes(q) ||
      (f.email || '').toLowerCase().includes(q);
    return matchSearch && matchStatus;
  });
  renderFarmersList2(base);
}

function renderFarmersList2(farmers) {
  var tbody = document.getElementById('farmerTableBody2');
  if (!tbody) return;
  if (!farmers.length) {
    tbody.innerHTML = '<tr><td colspan="11"><div class="empty-state"><i class="fas fa-search"></i><p>No team members match your filter.</p></div></td></tr>';
    return;
  }
  tbody.innerHTML = farmers.map(function (f) {
    var active = f.is_active;
    return '<tr onclick="openFarmerById(' + Number(f.user_id) + ')">' +
      '<td><div class="farmer-name">' + esc(f.full_name || f.username) + '</div><div class="farmer-email">' + esc(f.email) + ' · ' + esc(roleLabel(f.role)) + '</div></td>' +
      '<td>' + statusBadge(active) + '</td>' +
      '<td style="font-size:.8rem;">' + shortDate(f.created_at) + '</td>' +
      '<td style="font-size:.8rem;color:var(--slate-mid);">' + relDate(f.last_activity || f.last_login) + '</td>' +
      '<td>' + (f.waste_records || 0) + '</td>' +
      '<td>' + fmt(f.total_waste_kg) + '</td>' +
      '<td>' + (f.harvest_records || 0) + '</td>' +
      '<td>' + fmt(f.total_harvest_kg) + '</td>' +
      '<td>' + fmt(f.total_dried_kg) + '</td>' +
      '<td onclick="event.stopPropagation();" style="white-space:nowrap;display:flex;gap:.3rem;flex-wrap:wrap;">' +
        '<button class="btn-detail" onclick="openFarmerById(' + Number(f.user_id) + ')">View</button>' +
        '<button class="btn-edit" onclick="openEditModal(' + Number(f.user_id) + ')"><i class="fas fa-pen"></i></button>' +
        '<button class="btn-reset" onclick="openResetModal(' + Number(f.user_id) + ')"><i class="fas fa-key"></i></button>' +
        '<button class="btn-delete" onclick="openDeleteModal(' + Number(f.user_id) + ')"><i class="fas fa-trash"></i></button>' +
        '<button class="toggle-btn ' + (active ? 'deactivate' : 'activate') + '" onclick="toggleFarmer(' + Number(f.user_id) + ', this)">' +
          (active ? 'Deactivate' : 'Activate') +
        '</button>' +
      '</td>' +
    '</tr>';
  }).join('');
}

// ── Production Chart ──────────────────────────────────────────────────────
function renderProductionChart(farmers) {
  var canvas = document.getElementById('productionChart');
  if (!canvas || typeof Chart === 'undefined') return;
  var top = farmers.slice().sort(function (a, b) {
    return (parseFloat(b.total_waste_kg) + parseFloat(b.total_harvest_kg) + parseFloat(b.total_dried_kg)) -
           (parseFloat(a.total_waste_kg) + parseFloat(a.total_harvest_kg) + parseFloat(a.total_dried_kg));
  }).slice(0, 8);

  var labels = top.map(function (f) { return f.full_name || f.username; });
  if (productionChart) productionChart.destroy();
  productionChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        { label: 'Waste (kg)',   data: top.map(function(f){ return parseFloat(f.total_waste_kg)||0; }),   backgroundColor: '#f59e0b' },
        { label: 'Harvest (kg)', data: top.map(function(f){ return parseFloat(f.total_harvest_kg)||0; }), backgroundColor: '#16a34a' },
        { label: 'Dried (kg)',   data: top.map(function(f){ return parseFloat(f.total_dried_kg)||0; }),   backgroundColor: '#3b82f6' },
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom' } },
      scales: {
        x: { stacked: false, ticks: { maxRotation: 30, font: { size: 11 } } },
        y: { beginAtZero: true, ticks: { font: { size: 11 } } }
      }
    }
  });
}

// ── Leaderboard ───────────────────────────────────────────────────────────
function renderLeaderboard(farmers) {
  var el = document.getElementById('leaderboard');
  if (!el) return;
  var sorted = farmers.slice().sort(function (a, b) {
    var ta = (parseFloat(a.total_waste_kg)||0) + (parseFloat(a.total_harvest_kg)||0) + (parseFloat(a.total_dried_kg)||0);
    var tb = (parseFloat(b.total_waste_kg)||0) + (parseFloat(b.total_harvest_kg)||0) + (parseFloat(b.total_dried_kg)||0);
    return tb - ta;
  }).slice(0, 5);

  if (!sorted.length) {
    el.innerHTML = '<div class="empty-state"><i class="fas fa-trophy"></i><p>No production data yet.</p></div>';
    return;
  }

  var medals = ['🥇', '🥈', '🥉', '4', '5'];
  el.innerHTML = sorted.map(function (f, i) {
    var total = (parseFloat(f.total_waste_kg)||0) + (parseFloat(f.total_harvest_kg)||0) + (parseFloat(f.total_dried_kg)||0);
    var initials = (f.full_name || f.username).split(' ').map(function(n){return n[0];}).join('').substring(0,2).toUpperCase();
    return '<div class="lb-row" onclick="openFarmerById(' + Number(f.user_id) + ')">' +
      '<div class="lb-rank">' + medals[i] + '</div>' +
      '<div class="lb-avatar">' + initials + '</div>' +
      '<div class="lb-info">' +
        '<div class="lb-name">' + esc(f.full_name || f.username) + '</div>' +
        '<div class="lb-sub">' + statusBadge(f.is_active) + '</div>' +
      '</div>' +
      '<div class="lb-total">' + fmt(total) + '<span class="lb-unit"> kg</span></div>' +
    '</div>';
  }).join('');
}

// ── Toggle Active ─────────────────────────────────────────────────────────
async function toggleFarmer(userId, btn) {
  btn.disabled = true;
  try {
    var res = await fetch('/api/admin/users/' + userId + '/toggle', { method: 'POST', credentials: 'include' });
    var data = await res.json();
    if (data.success) {
      toast(data.message, 'success');
      var farmer = allFarmers.find(function (f) { return f.user_id === userId; });
      if (farmer) farmer.is_active = data.is_active;
      applyFilters();
      renderLeaderboard(allFarmers);
    } else {
      toast(data.message || 'Toggle failed', 'error');
    }
  } catch (e) {
    toast('Network error', 'error');
  } finally {
    btn.disabled = false;
  }
}

// ── Export CSV ────────────────────────────────────────────────────────────
function exportFarmers() {
  window.location.href = '/api/admin/farmers/export';
}

// ── Activity Feed ─────────────────────────────────────────────────────────
var activityData = [];

async function loadActivity() {
  try {
    var res = await fetch('/api/admin/activity', { credentials: 'include' });
    var data = await res.json();
    if (!data.success) return;
    activityData = data.data;
    renderActivitySidebar();
    if (currentSection === 'activity') renderActivityFull();
  } catch (e) {
    console.error('Activity error:', e);
  }
}

function renderActivitySidebar() {
  var el = document.getElementById('activityList');
  if (el) renderActivityIn(el, activityData);
}
function renderActivityFull() {
  var el = document.getElementById('activityListFull');
  if (el) renderActivityIn(el, activityData);
}

function renderActivityIn(container, items) {
  if (!items.length) {
    container.innerHTML = '<div class="empty-state"><i class="fas fa-stream"></i><p>No activity recorded yet.</p></div>';
    return;
  }
  container.innerHTML = items.map(function (a) {
    var typeKey = (a.type || '').toLowerCase().replace(/\s+/g, '');
    var icon    = typeKey.includes('waste') ? 'fa-recycle' : typeKey.includes('harvest') ? 'fa-seedling' : 'fa-box';
    var dotCls  = typeKey.includes('waste') ? 'waste' : typeKey.includes('harvest') ? 'harvest' : 'drying';
    return '<div class="activity-item">' +
      '<div class="activity-dot ' + dotCls + '"><i class="fas ' + icon + '"></i></div>' +
      '<div class="activity-text">' +
        '<div class="activity-who">' + esc(a.recorded_by || 'System') + ' &mdash; ' + esc(a.type) + '</div>' +
        '<div class="activity-what">' + esc(a.detail || '') + (a.amount ? ' &bull; ' + esc(a.amount) : '') + '</div>' +
        '<div class="activity-when">' + relDate(a.created_at) + '</div>' +
      '</div>' +
    '</div>';
  }).join('');
}

// ── Farmer Detail Modal ───────────────────────────────────────────────────
async function openFarmerModal(username) {
  document.getElementById('modalFarmerName').textContent = 'Loading…';
  document.getElementById('modalBody').innerHTML = '<div class="empty-state"><i class="fas fa-spinner fa-spin"></i><p>Loading farmer data…</p></div>';
  document.getElementById('modalActionBar').innerHTML = '';
  document.getElementById('farmerModal').classList.add('open');

  try {
    var res = await fetch('/api/admin/farmer/' + encodeURIComponent(username) + '/stats', { credentials: 'include' });
    var data = await res.json();
    if (!data.success) throw new Error(data.message);
    var f = data.data.farmer;
    var t = data.data.totals;
    _farmerDetail = f;
    document.getElementById('modalFarmerName').textContent = f.full_name || f.username;

    document.getElementById('modalActionBar').innerHTML =
      '<button class="btn btn-outline btn-sm" onclick="openEditModal(' + Number(f.user_id) + ')"><i class="fas fa-pen"></i> Edit</button>' +
      '<button class="btn btn-outline btn-sm" onclick="openResetModal(' + Number(f.user_id) + ')"><i class="fas fa-key"></i> Reset Password</button>' +
      '<button class="btn btn-red btn-sm" onclick="openDeleteModal(' + Number(f.user_id) + ')"><i class="fas fa-trash"></i> Delete</button>';

    var initials = (f.full_name || f.username).split(' ').map(function (n) { return n[0]; }).join('').substring(0, 2).toUpperCase();
    var html = '<div class="farmer-meta">' +
      '<div class="farmer-avatar">' + initials + '</div>' +
      '<div class="farmer-meta-info">' +
        '<h3>' + esc(f.full_name || f.username) + '</h3>' +
        '<p>' + esc(f.email) + '</p>' +
        '<p style="margin-top:.25rem;">' + statusBadge(f.is_active) + ' &nbsp; Joined ' + shortDate(f.created_at) + '</p>' +
      '</div>' +
    '</div>';

    html += '<div class="mini-stats">' +
      miniStat(fmt(t.total_waste),   'kg', 'Total Waste') +
      miniStat(fmt(t.total_harvest), 'kg', 'Larvae Harvested') +
      miniStat(fmt(t.total_dried),   'kg', 'Dried Output') +
    '</div>';

    html += detailSection('Recent Waste Sourcing', data.data.recent_waste,
      ['collection_date', 'waste_type', 'waste_weight', 'source_type'], ['Date', 'Type', 'Weight (kg)', 'Source']);
    html += detailSection('Recent Harvest', data.data.recent_harvest,
      ['harvest_date', 'production_batch', 'wet_weight_kg', 'harvest_stage'], ['Date', 'Batch', 'Wet larvae (kg)', 'Stage']);
    html += detailSection('Recent Drying Output', data.data.recent_drying,
      ['created_at', 'batch_id', 'dried_produced_kg', 'yield_percentage'], ['Date', 'Batch', 'Dried (kg)', 'Yield %']);
    html += detailSection('Recent Feeding', data.data.recent_feeding,
      ['feeding_date', 'production_batch', 'feed_type', 'feed_quantity'], ['Date', 'Batch', 'Feed Type', 'Offered']);

    document.getElementById('modalBody').innerHTML = html;
  } catch (e) {
    document.getElementById('modalBody').innerHTML =
      '<div class="empty-state"><i class="fas fa-exclamation-circle" style="color:var(--red);"></i><p>' + esc(e.message) + '</p></div>';
  }
}

function closeFarmerModal(evt) {
  if (evt && evt.target !== document.getElementById('farmerModal')) return;
  document.getElementById('farmerModal').classList.remove('open');
}

// Inline handlers pass only the numeric user id; names and emails are read
// from the loaded list so user-supplied text never becomes script.
var _farmerDetail = null;
function farmerById(userId) {
  return allFarmers.find(function (f) { return f.user_id === userId; }) ||
    (_farmerDetail && _farmerDetail.user_id === userId ? _farmerDetail : null) || {};
}
function openFarmerById(userId) {
  var farmer = farmerById(userId);
  if (farmer.username) openFarmerModal(farmer.username);
}

// ── Roles ─────────────────────────────────────────────────────────────────
var roleOptions = [];
async function loadRoles() {
  try {
    var res = await fetch('/api/admin/roles', { credentials: 'include' });
    var data = await res.json();
    roleOptions = data.data || [];
  } catch (err) {
    roleOptions = [];
  }
  ['editRole', 'addRole'].forEach(function (id) {
    var select = document.getElementById(id);
    if (!select) return;
    select.textContent = '';
    roleOptions.forEach(function (role) {
      var option = new Option(role.label, role.key);
      option.title = role.permissions.join('; ') || 'Read only';
      select.add(option);
    });
  });
  var add = document.getElementById('addRole');
  if (add) add.value = 'operator';
  describeRole('addRole');
}
function roleLabel(key) {
  var role = roleOptions.find(function (r) { return r.key === key; });
  return role ? role.label : (key || '');
}
function describeRole(selectId) {
  var select = document.getElementById(selectId);
  var hint = document.getElementById(selectId + 'Hint');
  if (!select || !hint) return;
  var role = roleOptions.find(function (r) { return r.key === select.value; });
  hint.textContent = role ? (role.permissions.length ? 'Can: ' + role.permissions.join('; ') : 'Read only') : '';
}
loadRoles();

// ── Edit Farmer Modal ─────────────────────────────────────────────────────
var _editUserId = null;
function openEditModal(userId) {
  var farmer = farmerById(userId);
  _editUserId = userId;
  document.getElementById('editFullName').value = farmer.full_name || '';
  document.getElementById('editEmail').value = farmer.email || '';
  document.getElementById('editRole').value = farmer.role || 'viewer';
  describeRole('editRole');
  document.getElementById('editFarmerModal').classList.add('open');
}
function closeEditModal(evt) {
  if (evt && evt.target !== document.getElementById('editFarmerModal')) return;
  document.getElementById('editFarmerModal').classList.remove('open');
}
async function submitEditFarmer(e) {
  e.preventDefault();
  var btn = document.getElementById('editFarmerBtn');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving…';
  try {
    var res = await fetch('/api/admin/users/' + _editUserId, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        full_name: document.getElementById('editFullName').value.trim(),
        email: document.getElementById('editEmail').value.trim(),
        role: document.getElementById('editRole').value
      })
    });
    var data = await res.json();
    if (data.success) {
      toast(data.message, 'success');
      document.getElementById('editFarmerModal').classList.remove('open');
      document.getElementById('farmerModal').classList.remove('open');
      loadFarmers(); loadOverview(currentDays);
    } else {
      toast(data.message || 'Update failed', 'error');
    }
  } catch (err) {
    toast('Network error', 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-save"></i> Save Changes';
  }
}

// ── Reset Password Modal ──────────────────────────────────────────────────
var _resetUserId = null;
function openResetModal(userId) {
  var farmer = farmerById(userId);
  _resetUserId = userId;
  document.getElementById('resetFarmerName').textContent = farmer.full_name || farmer.username || '';
  document.getElementById('resetPasswordForm').reset();
  document.getElementById('resetFarmerModal').classList.add('open');
}
function closeResetModal(evt) {
  if (evt && evt.target !== document.getElementById('resetFarmerModal')) return;
  document.getElementById('resetFarmerModal').classList.remove('open');
}
async function submitResetPassword(e) {
  e.preventDefault();
  var pw = document.getElementById('newPassword').value;
  var cpw = document.getElementById('confirmNewPassword').value;
  if (pw !== cpw) { toast('Passwords do not match', 'error'); return; }
  if (pw.length < 10) { toast('Password must be at least 10 characters', 'error'); return; }
  var btn = document.getElementById('resetPasswordBtn');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Resetting…';
  try {
    var res = await fetch('/api/admin/users/' + _resetUserId + '/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ password: pw })
    });
    var data = await res.json();
    if (data.success) {
      toast(data.message, 'success');
      document.getElementById('resetFarmerModal').classList.remove('open');
    } else {
      toast(data.message || 'Reset failed', 'error');
    }
  } catch (err) {
    toast('Network error', 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-key"></i> Reset Password';
  }
}

// ── Delete Farmer Modal ───────────────────────────────────────────────────
var _deleteUserId = null;
function openDeleteModal(userId) {
  var farmer = farmerById(userId);
  _deleteUserId = userId;
  document.getElementById('deleteFarmerName').textContent = farmer.full_name || farmer.username || '';
  document.getElementById('deleteFarmerModal').classList.add('open');
}
function closeDeleteModal(evt) {
  if (evt && evt.target !== document.getElementById('deleteFarmerModal')) return;
  document.getElementById('deleteFarmerModal').classList.remove('open');
}
async function confirmDeleteFarmer() {
  var btn = document.getElementById('confirmDeleteBtn');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Deleting…';
  try {
    var res = await fetch('/api/admin/users/' + _deleteUserId, {
      method: 'DELETE',
      credentials: 'include'
    });
    var data = await res.json();
    if (data.success) {
      toast(data.message, 'success');
      document.getElementById('deleteFarmerModal').classList.remove('open');
      document.getElementById('farmerModal').classList.remove('open');
      loadFarmers(); loadOverview(currentDays);
    } else {
      toast(data.message || 'Delete failed', 'error');
    }
  } catch (err) {
    toast('Network error', 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-trash"></i> Yes, Delete';
  }
}

// ── Add Farmer Modal ──────────────────────────────────────────────────────
function openAddFarmerModal() {
  document.getElementById('addFarmerForm').reset();
  document.getElementById('addRole').value = 'operator';
  describeRole('addRole');
  document.getElementById('addFarmerModal').classList.add('open');
}
function closeAddFarmerModal(evt) {
  if (evt && evt.target !== document.getElementById('addFarmerModal')) return;
  document.getElementById('addFarmerModal').classList.remove('open');
}
async function submitAddFarmer(e) {
  e.preventDefault();
  var form = e.target;
  var btn = document.getElementById('addFarmerBtn');
  var fd = new FormData(form);
  var password = fd.get('password');
  var confirm = fd.get('confirm_password');
  if (password !== confirm) { toast('Passwords do not match', 'error'); return; }
  if (password.length < 10) { toast('Password must be at least 10 characters', 'error'); return; }
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating…';
  try {
    var res = await fetch('/api/admin/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        username: fd.get('username').trim(),
        full_name: fd.get('full_name').trim(),
        email: fd.get('email').toLowerCase().trim(),
        password: password,
        role: fd.get('role')
      })
    });
    var data = await res.json();
    if (data.success) {
      toast(data.message, 'success');
      document.getElementById('addFarmerModal').classList.remove('open');
      loadFarmers(); loadOverview(currentDays);
    } else {
      toast(data.message || 'Failed to create account', 'error');
    }
  } catch (err) {
    toast('Network error', 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-user-plus"></i> Create Account';
  }
}

// ── Detail Helpers ────────────────────────────────────────────────────────
function detailSection(title, records, fields, headers) {
  var html = '<div class="detail-section"><h4>' + title + '</h4>';
  if (!records || !records.length) {
    html += '<p class="no-data">No records yet.</p>';
  } else {
    html += '<table class="mini-table"><thead><tr>' +
      headers.map(function (h) { return '<th>' + h + '</th>'; }).join('') +
      '</tr></thead><tbody>' +
      records.map(function (r) {
        return '<tr>' + fields.map(function (f) {
          var v = r[f];
          if (v === null || v === undefined) return '<td style="color:var(--gray);">—</td>';
          if (typeof v === 'string' && v.match(/^\d{4}-\d{2}-\d{2}/)) return '<td>' + v.substring(0, 10) + '</td>';
          if (typeof v === 'number') return '<td>' + v.toLocaleString(undefined, { maximumFractionDigits: 2 }) + '</td>';
          return '<td>' + esc(String(v)) + '</td>';
        }).join('') + '</tr>';
      }).join('') +
      '</tbody></table>';
  }
  return html + '</div>';
}

function miniStat(val, unit, label) {
  return '<div class="mini-stat">' +
    '<div class="mini-stat-val">' + val + '<span class="mini-stat-unit"> ' + unit + '</span></div>' +
    '<div class="mini-stat-lbl">' + label + '</div>' +
  '</div>';
}

// ── Helpers ───────────────────────────────────────────────────────────────
function esc(str) {
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
function fmt(n) {
  var num = parseFloat(n);
  if (isNaN(num)) return '—';
  return num.toLocaleString(undefined, { maximumFractionDigits: 1 });
}
function statusBadge(isActive) {
  return isActive
    ? '<span class="badge badge-green"><i class="fas fa-circle" style="font-size:.55rem;"></i> Active</span>'
    : '<span class="badge badge-red"><i class="fas fa-circle" style="font-size:.55rem;"></i> Inactive</span>';
}
function relDate(dateStr) {
  if (!dateStr) return '<span style="color:var(--gray);">Never</span>';
  var d = new Date(dateStr), now = new Date();
  var diff = Math.floor((now - d) / 1000);
  if (diff < 60)     return 'Just now';
  if (diff < 3600)   return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400)  return Math.floor(diff / 3600) + 'h ago';
  if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}
function shortDate(dateStr) {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

// ── Toast ─────────────────────────────────────────────────────────────────
function toast(msg, type) {
  type = type || 'info';
  var icon = type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-exclamation-circle' : 'fa-info-circle';
  var el = document.createElement('div');
  el.className = 'toast ' + type;
  el.innerHTML = '<i class="fas ' + icon + '"></i> ' + esc(msg);
  document.getElementById('toastWrap').appendChild(el);
  setTimeout(function () { el.remove(); }, 4000);
}
