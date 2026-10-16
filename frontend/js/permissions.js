// Hides controls the signed-in user's role cannot use. The server enforces
// every permission; this only keeps the screen honest.
//
//   <a data-permission="sales.read">…</a>   shown only with that permission
//   <a data-permission="production.write|quality.decide">…</a>   with either
//
// Elements start hidden (add the `hidden` attribute in the markup) so nothing
// flashes before the profile loads. window.currentUser resolves to the
// /api/me profile (or null) for page scripts that need it.
(function () {
  window.currentUser = window.currentUser || fetch('/api/me', { credentials: 'include' })
    .then(function (response) { return response.ok ? response.json() : null; })
    .then(function (payload) { return payload && payload.data; })
    .catch(function () { return null; });

  function apply(profile) {
    var granted = (profile && profile.permissions) || [];
    document.querySelectorAll('[data-permission]').forEach(function (node) {
      node.hidden = !node.getAttribute('data-permission').split('|').some(function (permission) {
        return granted.indexOf(permission) !== -1;
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { window.currentUser.then(apply); });
  } else {
    window.currentUser.then(apply);
  }
})();
