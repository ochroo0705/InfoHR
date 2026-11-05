// Employee page: #<tab>-<key> (the assistant's field answer) shows the tab, scrolls to the field and rings it for two
// seconds. The tab part is read by detail.html; this script does the field part, after that inline script has run.
// The key is checked against [a-z0-9_] before it goes into a selector, and nothing happens when no field matches.
(function () {
  var KEY = /^[a-z0-9_]+$/;
  // Classes that already exist in static/css/app.css as plain rules (no rebuild needed for this file).
  var RING = ['ring-2', 'ring-violet-600', 'rounded-md'];
  var timer = 0;
  var marked = null;

  function visible(el) { return el.getClientRects().length > 0; }

  // The first shown hit; a hidden one (a select behind its typing box) gives its row instead. Null when none shows.
  function pick(hits) {
    for (var i = 0; i < hits.length; i++) {
      if (visible(hits[i])) return hits[i];
    }
    var row = hits[0].closest('div');
    return row && visible(row) ? row : null;
  }

  function clear() {
    if (marked) RING.forEach(function (c) { marked.classList.remove(c); });
    marked = null;
    clearTimeout(timer);
  }

  function focusField() {
    var hash = location.hash.slice(1);
    var cut = hash.indexOf('-');
    if (cut < 1) return;
    var tab = hash.slice(0, cut), key = hash.slice(cut + 1);
    if (!KEY.test(key)) return;
    var section = document.getElementById('tab-' + tab);
    if (!section) return;

    var hits = section.querySelectorAll('[name="' + key + '"], [data-field="' + key + '"]');
    if (!hits.length) return;
    var target = pick(hits);
    if (!target) {
      // A personal-tab field in a topic group that is not open (wide screens show one group at a time):
      // open it with the group's own menu link, as a click on it does (sections.js), then look again.
      var group = hits[0].closest('[data-pgroup]');
      var name = group && group.getAttribute('data-pgroup');
      var link = group && group.hasAttribute('data-off') && KEY.test(name)
        ? document.querySelector('#personal-nav a[data-pgroup-link="' + name + '"]') : null;
      if (link) {
        link.click();
        target = pick(hits);
      }
    }
    if (!target) return;

    clear();
    target.scrollIntoView({ block: 'center' });
    RING.forEach(function (c) { target.classList.add(c); });
    marked = target;
    timer = setTimeout(clear, 2000);
  }

  focusField();
})();
