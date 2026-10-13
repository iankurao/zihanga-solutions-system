// In-app notification bell, shared by every page. Self-contained: it adds its
// own button, panel and styles, and only talks to /api/notifications.
(function () {
  if (window.ZehungerNotificationCenter) return;
  window.ZehungerNotificationCenter = true;

  var POLL_MS = 60000;
  var style = document.createElement('style');
  style.textContent = [
    '.znc-bell{position:fixed;right:18px;bottom:18px;z-index:1050;width:52px;height:52px;border:0;border-radius:50%;',
    'background:#143c2d;color:#fff;font-size:20px;box-shadow:0 6px 18px rgba(0,0,0,.25);cursor:pointer}',
    '.znc-bell:focus-visible{outline:3px solid #9fd8b6;outline-offset:2px}',
    '.znc-badge{position:absolute;top:-4px;right:-4px;min-width:20px;height:20px;padding:0 5px;border-radius:10px;',
    'background:#c0392b;color:#fff;font:700 12px/20px system-ui,sans-serif}',
    '.znc-badge[hidden]{display:none}',
    '.znc-panel{position:fixed;right:18px;bottom:80px;z-index:1050;width:min(380px,calc(100vw - 36px));max-height:min(520px,70vh);',
    'display:flex;flex-direction:column;border:1px solid #dbe6df;border-radius:14px;background:#fff;color:#16302a;',
    'box-shadow:0 14px 40px rgba(0,0,0,.22);font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}',
    '.znc-panel[hidden]{display:none}',
    '.znc-head{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:12px 14px;border-bottom:1px solid #e6eee9}',
    '.znc-head strong{font-size:15px}',
    '.znc-link{border:0;background:none;color:#19804b;font:inherit;font-weight:700;cursor:pointer;padding:0;text-decoration:none}',
    '.znc-list{overflow-y:auto;margin:0;padding:0;list-style:none}',
    '.znc-item{display:block;width:100%;padding:10px 14px;border:0;border-bottom:1px solid #eef3f0;border-left:4px solid #3b6fb6;',
    'background:#fff;color:inherit;font:inherit;text-align:left;cursor:pointer}',
    '.znc-item.is-warning{border-left-color:#a86a12}.znc-item.is-critical{border-left-color:#a13b30}',
    '.znc-item.is-unread{background:#f3faf6}.znc-item:hover{background:#eef6f1}',
    '.znc-item b{display:block;font-size:13.5px}.znc-item span{display:block;color:#5f7068;font-size:12.5px}',
    '.znc-item time{display:block;margin-top:2px;color:#8a9a92;font-size:11.5px}',
    '.znc-empty{padding:18px 14px;color:#5f7068}',
    '.znc-foot{padding:10px 14px;border-top:1px solid #e6eee9;text-align:right}'
  ].join('');
  document.head.appendChild(style);

  var bell = document.createElement('button');
  bell.type = 'button';
  bell.className = 'znc-bell';
  bell.setAttribute('aria-label', 'Notifications');
  bell.setAttribute('aria-expanded', 'false');
  bell.innerHTML = '<span aria-hidden="true">&#128276;</span>';
  var badge = document.createElement('span');
  badge.className = 'znc-badge';
  badge.hidden = true;
  bell.appendChild(badge);

  var panel = document.createElement('section');
  panel.className = 'znc-panel';
  panel.hidden = true;
  panel.setAttribute('aria-label', 'Notifications');
  var head = document.createElement('div');
  head.className = 'znc-head';
  var title = document.createElement('strong');
  title.textContent = 'Notifications';
  var readAll = document.createElement('button');
  readAll.type = 'button';
  readAll.className = 'znc-link';
  readAll.textContent = 'Mark all read';
  head.append(title, readAll);
  var list = document.createElement('ul');
  list.className = 'znc-list';
  var foot = document.createElement('div');
  foot.className = 'znc-foot';
  var settings = document.createElement('a');
  settings.className = 'znc-link';
  settings.href = '/alerts#notification-settings';
  settings.textContent = 'Notification settings';
  foot.appendChild(settings);
  panel.append(head, list, foot);

  function mount() {
    document.body.append(panel, bell);
  }

  async function api(url, method) {
    var response = await fetch(url, { method: method || 'GET', credentials: 'include' });
    if (!response.ok) throw new Error('Notification request failed');
    return response.json();
  }

  function setBadge(count) {
    badge.textContent = count > 99 ? '99+' : String(count);
    badge.hidden = !count;
    bell.setAttribute('aria-label', count ? 'Notifications, ' + count + ' unread' : 'Notifications');
  }

  function ago(value) {
    var minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000));
    if (minutes < 60) return minutes + ' min ago';
    var hours = Math.round(minutes / 60);
    return hours < 48 ? hours + ' h ago' : Math.round(hours / 24) + ' days ago';
  }

  async function refreshCount() {
    if (document.hidden) return;
    try {
      var data = await api('/api/notifications/unread-count');
      setBadge(data.unread || 0);
    } catch (error) { /* signed out or offline: leave the bell quiet */ }
  }

  async function loadList() {
    list.textContent = '';
    try {
      var data = await api('/api/notifications?limit=20');
      setBadge(data.unread || 0);
      if (!data.data.length) {
        var empty = document.createElement('li');
        empty.className = 'znc-empty';
        empty.textContent = 'No notifications yet.';
        list.appendChild(empty);
        return;
      }
      data.data.forEach(function (item) {
        var li = document.createElement('li');
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'znc-item is-' + item.severity + (item.read_at ? '' : ' is-unread');
        var heading = document.createElement('b');
        heading.textContent = item.title;
        var body = document.createElement('span');
        body.textContent = item.body;
        var time = document.createElement('time');
        time.textContent = ago(item.created_at) + (item.alert_status === 'RESOLVED' ? ' · resolved' : '');
        button.append(heading, body, time);
        button.addEventListener('click', async function () {
          try { await api('/api/notifications/' + item.id + '/read', 'POST'); } catch (error) { /* ignore */ }
          if (item.href) window.location.href = item.href;
          else loadList();
        });
        li.appendChild(button);
        list.appendChild(li);
      });
    } catch (error) {
      var failed = document.createElement('li');
      failed.className = 'znc-empty';
      failed.textContent = 'Notifications could not be loaded.';
      list.appendChild(failed);
    }
  }

  bell.addEventListener('click', function () {
    var opening = panel.hidden;
    panel.hidden = !opening;
    bell.setAttribute('aria-expanded', String(opening));
    if (opening) loadList();
  });
  readAll.addEventListener('click', async function () {
    try { await api('/api/notifications/read-all', 'POST'); } catch (error) { /* ignore */ }
    loadList();
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !panel.hidden) {
      panel.hidden = true;
      bell.setAttribute('aria-expanded', 'false');
      bell.focus();
    }
  });
  document.addEventListener('visibilitychange', refreshCount);

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
  refreshCount();
  setInterval(refreshCount, POLL_MS);
})();
