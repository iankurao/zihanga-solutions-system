// Guided tour of a demo database (/tour). Chapters come from /api/demo/tour,
// each opening a real page at a real demo record; js/appNav.js shows the
// tour bar on those pages. Signed-out visitors get guest access when the
// server offers it, otherwise a sign-in link.
(function () {
  var ui = window.ErpUI;
  var el = ui.el;
  var who = document.getElementById('tourWho');
  var start = document.getElementById('tourStart');
  var messageBox = document.getElementById('tourMessage');
  var list = document.getElementById('tourChapters');

  function button(label, iconName, secondary) {
    var b = el('button', 'erp-btn' + (secondary ? ' erp-btn--secondary' : ''));
    b.type = 'button';
    if (iconName) b.appendChild(ui.icon(iconName));
    b.append(el('span', null, label));
    return b;
  }

  function signedOut(info) {
    list.textContent = '';
    if (info && info.guest_access) {
      who.textContent = 'No account needed: guests can look at everything a read-only visitor may see, '
        + 'and cannot change any record.';
      var guest = button('Explore as a guest', 'fa-door-open');
      guest.addEventListener('click', function () {
        ui.busy(guest, fetch('/api/demo/guest', {
          method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: '{}'
        })
          .then(function (response) {
            return response.json().catch(function () { return {}; })
              .then(function (body) { return { ok: response.ok, body: body }; });
          })
          .then(function (result) {
            if (!result.ok) throw new Error(result.body.message || 'Guest access is not available.');
            window.location.href = result.body.redirect || '/tour';
          }))
          .catch(function (err) { ui.message(messageBox, err.message, 'danger'); });
      });
      start.append(guest);
    } else {
      who.textContent = 'Sign in with a demo account to start the tour.';
    }
    var signIn = el('a', 'erp-btn' + (info && info.guest_access ? ' erp-btn--secondary' : ''), 'Sign in');
    signIn.href = '/login?next=' + encodeURIComponent('/tour');
    start.append(signIn);
  }

  function chapterItem(chapter, index, chapters) {
    var item = el('li', 'tour-chapter');
    var body = el('div');
    body.append(el('h2', null, chapter.title), el('p', null, chapter.text));
    if (chapter.look_for) body.append(el('p', 'tour-look', 'Look for: ' + chapter.look_for));
    var show = button('Show me', 'fa-arrow-right', index !== 0);
    show.addEventListener('click', function () { window.ErpTour.go(chapters, index); });
    item.append(body, show);
    return item;
  }

  function signedIn(profile) {
    who.textContent = 'You are signed in as ' + (profile.full_name || profile.username) + ' · '
      + (profile.role_label || profile.role) + '.';
    ui.loading(list, 'Loading the tour…');
    fetch('/api/demo/tour', { credentials: 'include' })
      .then(function (response) {
        if (!response.ok) throw new Error('The tour could not be loaded.');
        return response.json();
      })
      .then(function (payload) {
        var chapters = payload.data.chapters;
        if (payload.data.read_only) who.textContent += ' This account can look but not change anything.';
        list.textContent = '';
        chapters.forEach(function (chapter, index) { list.append(chapterItem(chapter, index, chapters)); });
        var begin = button(window.ErpTour.read() ? 'Restart the tour' : 'Start the tour', 'fa-play');
        begin.addEventListener('click', function () { window.ErpTour.go(chapters, 0); });
        start.append(begin);
        if (new URLSearchParams(window.location.search).get('done')) {
          ui.message(messageBox, 'That was the whole tour. Open any chapter again, or explore on your own '
            + 'from the menu.', 'success');
        }
      })
      .catch(function (err) { ui.error(list, err.message, function () { signedIn(profile); }); });
  }

  Promise.all([
    window.currentUser,
    fetch('/api/demo/info', { credentials: 'include' }).then(function (r) { return r.json(); })
      .then(function (p) { return p.data; }).catch(function () { return null; })
  ]).then(function (results) {
    if (results[0]) signedIn(results[0]);
    else signedOut(results[1]);
  });
})();
