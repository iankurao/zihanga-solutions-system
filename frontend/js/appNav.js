// Shared navigation bar for every ERP page (design system).
// Put <header data-erp-nav></header> first in <body> and load
// /js/permissions.js before this script. Links a role cannot use are not
// shown; the server enforces every permission regardless.
(function () {
  var PRIMARY = [
    { href: '/operations', label: 'Operations', icon: 'fa-gauge-high' },
    { href: '/batch-360', label: 'Batches', icon: 'fa-layer-group' },
    { href: '/traceability', label: 'Traceability', icon: 'fa-diagram-project' },
    { href: '/product-lot', label: 'Product lots', icon: 'fa-box' },
    { href: '/orders', label: 'Orders', icon: 'fa-truck', permission: 'sales.read' },
    { href: '/alerts', label: 'Alerts', icon: 'fa-bell' },
    { href: '/analytics', label: 'Reports', icon: 'fa-chart-line' }
  ];
  var MORE = [
    { href: '/farmer', label: 'Farmer portal', icon: 'fa-seedling', permission: 'production.write' },
    { href: '/dashboard', label: 'Data entry forms', icon: 'fa-pen-to-square', permission: 'production.write' },
    { href: '/production_batch.html', label: 'New production batch', icon: 'fa-plus', permission: 'production.write' },
    { href: '/labels', label: 'QR labels', icon: 'fa-qrcode' },
    { href: '/setup', label: 'Farm setup', icon: 'fa-sitemap', permission: 'setup.manage' },
    { href: '/audit', label: 'Audit log', icon: 'fa-clipboard-list', permission: 'audit.read' },
    { href: '/zehunger', label: 'Admin portal', icon: 'fa-user-shield', role: 'super_admin' }
  ];

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

  function allowed(item, profile) {
    if (!profile) return false;
    if (item.role) return profile.role === item.role;
    return !item.permission || (profile.permissions || []).indexOf(item.permission) !== -1;
  }

  function link(item) {
    var a = el('a');
    a.href = item.href;
    a.append(icon(item.icon), el('span', null, item.label));
    if (window.location.pathname === item.href) a.setAttribute('aria-current', 'page');
    return a;
  }

  function render(header, profile) {
    header.className = 'erp-appbar no-print';
    header.textContent = '';
    var inner = el('div', 'erp-appbar-inner');

    var brand = el('a', 'erp-brand');
    brand.href = profile ? profile.home || '/operations' : '/';
    var logo = el('img');
    logo.src = '/images/logo.png';
    logo.alt = '';
    brand.append(logo, el('span', null, 'Zehunger ERP'));

    var toggle = el('button', 'erp-nav-toggle');
    toggle.type = 'button';
    toggle.setAttribute('aria-label', 'Menu');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-controls', 'erpNavLinks');
    toggle.appendChild(icon('fa-bars'));
    toggle.addEventListener('click', function () {
      var open = header.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', String(open));
    });

    var nav = el('nav', 'erp-nav');
    nav.id = 'erpNavLinks';
    nav.setAttribute('aria-label', 'Main');
    var primary = PRIMARY.filter(function (item) { return allowed(item, profile); });
    var more = MORE.filter(function (item) { return allowed(item, profile); });
    // Operators and farmers start from their portal.
    if (profile && profile.role === 'operator') {
      primary = more.filter(function (item) { return item.href === '/farmer'; }).concat(primary);
      more = more.filter(function (item) { return item.href !== '/farmer'; });
    }
    primary.forEach(function (item) { nav.appendChild(link(item)); });
    if (more.length) {
      var details = el('details', 'erp-nav-more');
      var summary = el('summary');
      summary.append(icon('fa-ellipsis'), el('span', null, 'More'));
      var menu = el('div', 'erp-nav-menu');
      more.forEach(function (item) { menu.appendChild(link(item)); });
      // The current page may live under More: mark the button, never auto-open
      // the menu over the page.
      if (more.some(function (item) { return item.href === window.location.pathname; })) {
        summary.classList.add('has-current');
      }
      details.append(summary, menu);
      nav.appendChild(details);
      document.addEventListener('click', function (event) {
        if (!details.contains(event.target) && window.innerWidth > 1080) details.open = false;
      });
    }

    var user = el('div', 'erp-user');
    if (profile) {
      var name = el('span', 'erp-user-name');
      name.append(el('strong', null, profile.full_name || profile.username), el('small', null, profile.role_label || ''));
      var out = el('a');
      out.href = '/logout';
      out.title = 'Sign out';
      out.setAttribute('aria-label', 'Sign out');
      out.appendChild(icon('fa-right-from-bracket'));
      if (profile.demo) {
        var demo = el('span', 'erp-badge is-warning erp-demo-badge', 'Demo data');
        demo.title = 'Demonstration records - not real farms, customers or orders';
        user.append(demo);
      }
      user.append(name, out);
    } else {
      var signIn = el('a');
      signIn.href = '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search);
      signIn.title = 'Sign in';
      signIn.setAttribute('aria-label', 'Sign in');
      signIn.appendChild(icon('fa-right-to-bracket'));
      user.appendChild(signIn);
    }

    inner.append(toggle, brand, nav, user);
    header.appendChild(inner);
  }

  function start() {
    var header = document.querySelector('[data-erp-nav]');
    if (!header) return;
    render(header, null);
    (window.currentUser || Promise.resolve(null)).then(function (profile) { render(header, profile); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
