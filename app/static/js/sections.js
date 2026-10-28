// Personal tab: topic groups open as pages, the section menu follows the section in view; sections edited on the spot show their save
// strip once changed, and unsaved changes ask before the page is left. Sections are plain elements with id sec-<name>.
(function () {
  if (!document.getElementById('personal-nav')) return;
  var dirty = {};  // section name -> true while its form has unsaved input
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  // The menu and the groups are looked up on each use: a Work-tab save redraws <main>, menu included.
  function menu() { return document.getElementById('personal-nav'); }

  function nameOf(id) { return id && id.indexOf('sec-') === 0 ? id.slice(4) : ''; }
  function shown(el) { return el.getClientRects().length > 0; }

  // Topic groups are pages (UI_RULES §8): on wide screens only the open group is shown (CSS hides
  // [data-pgroup][data-off] from lg up); narrow screens have no menu and keep the whole tab as one page.
  // The open group is in the address as #personal-<group>, so a reload or Back keeps it.
  var group = '';
  function groups() { return document.querySelectorAll('[data-pgroup]'); }
  function openGroup(key) {
    var keys = Array.prototype.map.call(groups(), function (g) { return g.getAttribute('data-pgroup'); });
    if (keys.indexOf(key) === -1) key = keys[0] || '';
    group = key;
    groups().forEach(function (g) {
      if (g.getAttribute('data-pgroup') === key) g.removeAttribute('data-off'); else g.setAttribute('data-off', '');
    });
    var m = menu();
    if (m) m.querySelectorAll('a[data-pgroup-link]').forEach(function (a) {
      if (a.getAttribute('data-pgroup-link') === key) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
    });
  }
  function hashGroup() {
    var h = location.hash.slice(1);
    return h.indexOf('personal-') === 0 ? h.slice(9) : '';
  }
  function remember() {
    if (location.hash.indexOf('#personal') === 0) history.replaceState(null, '', '#personal-' + group);
  }
  openGroup(hashGroup());

  // The link of the section in view gets aria-current (styled in _personal_menu_item.html).
  function highlight(name) {
    var m = menu();
    if (m) m.querySelectorAll('a[data-sec]').forEach(function (a) {
      if (a.getAttribute('data-sec') === name) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
    });
  }

  // The last shown section whose top has scrolled above the top bar's edge is the current one; above the
  // first one, the first shown section is. After a menu click the clicked section stays current until the
  // reader scrolls by hand: near a group page's end a section can't reach the top, and another would win.
  var ticking = false, pinned = '';
  ['wheel', 'touchmove', 'keydown'].forEach(function (type) {
    window.addEventListener(type, function () { pinned = ''; }, { passive: true });
  });
  function current() {
    ticking = false;
    if (pinned) { highlight(pinned); return; }
    var name = '', first = '';
    document.querySelectorAll('section[id^="sec-"]').forEach(function (s) {
      if (!shown(s)) return;
      if (!first) first = nameOf(s.id);
      if (s.getBoundingClientRect().top <= 120) name = nameOf(s.id);
    });
    highlight(name || first);
  }
  function observe() { if (group) openGroup(group); current(); }
  window.addEventListener('scroll', function () {
    if (!ticking) { ticking = true; window.requestAnimationFrame(current); }
  }, { passive: true });

  // A short highlight on the section the menu link scrolled to, started once the scroll has arrived
  // (scrollend, or a timer where the browser has no such event / nothing needed to scroll).
  function flash(el) {
    var done = false;
    function go() {
      if (done) return;
      done = true;
      window.removeEventListener('scrollend', go);
      el.classList.remove('sec-flash');
      void el.offsetWidth;  // restart the animation on a repeated click
      el.classList.add('sec-flash');
      el.addEventListener('animationend', function end() {
        el.classList.remove('sec-flash');
        el.removeEventListener('animationend', end);
      });
    }
    window.addEventListener('scrollend', go);
    window.setTimeout(go, reduce ? 0 : 700);
  }

  // A group link opens that group at its top; an entry opens its group and scrolls to the section.
  document.addEventListener('click', function (e) {
    var m = menu();
    if (!m || !m.contains(e.target)) return;
    var g = e.target.closest('a[data-pgroup-link]');
    if (g) {
      e.preventDefault();
      openGroup(g.getAttribute('data-pgroup-link'));
      remember();
      var tab = document.getElementById('tab-personal');
      if (tab && tab.getBoundingClientRect().top < 0) window.scrollTo(0, window.scrollY + tab.getBoundingClientRect().top - 80);
      pinned = '';
      current();
      return;
    }
    var a = e.target.closest('a[data-sec]');
    if (!a) return;
    var el = document.getElementById('sec-' + a.getAttribute('data-sec'));
    if (!el) return;
    e.preventDefault();
    var home = el.closest('[data-pgroup]');
    if (home && home.getAttribute('data-pgroup') !== group) { openGroup(home.getAttribute('data-pgroup')); remember(); }
    pinned = a.getAttribute('data-sec');
    highlight(pinned);
    el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
    flash(el);
  });
  // The «Хувийн» tab link writes #personal: keep the open group in the address.
  window.addEventListener('hashchange', function () { if (hashGroup()) openGroup(hashGroup()); });
  document.addEventListener('click', function (e) {
    if (e.target.closest('a[href="#personal"]')) window.setTimeout(function () { remember(); current(); }, 0);
  });

  // Typing in a section form marks that section dirty; a save or cancel swaps the section and clears it.
  document.addEventListener('input', function (e) { markDirty(e); });
  document.addEventListener('change', function (e) { markDirty(e); });
  var rowDirty = {};  // list kind -> true while its open inline row (UI_RULES §2f) holds typed, unsaved values
  function markDirty(e) {
    var form = e.target.form;
    if (form && form.id && form.id.indexOf('inline-') === 0) { rowDirty[form.id.slice(7, -5)] = true; return; }
    if (!form || !form.id || !/^sec-.+-form$/.test(form.id)) return;
    dirty[form.id.slice(4, -5)] = true;
    // A section edited on the spot (UI_RULES §2f): show its save strip and the violet edge on the changed box.
    if (!form.hasAttribute('data-on-spot')) return;
    var strip = form.querySelector('[data-strip]');
    if (strip) strip.hidden = false;
    var dd = e.target.closest('dd');
    if (dd) dd.classList.add('f-changed');
  }
  function unsaved() {
    var open = function (map) { return Object.keys(map).some(function (name) { return map[name]; }); };
    return open(rowDirty) || open(dirty);
  }
  window.addEventListener('beforeunload', function (e) {
    if (unsaved()) { e.preventDefault(); e.returnValue = ''; }
  });
  // The page form (Work tab, emp-form) redraws <main> on an error and reloads on success: either way this tab's
  // unsaved values go. Ask once before it is sent, then forget them so the reload does not ask again.
  document.addEventListener('htmx:beforeRequest', function (e) {
    if (!e.detail || !e.detail.elt || e.detail.elt.id !== 'emp-form' || !unsaved()) return;
    if (!window.confirm('Хувийн табын хадгалаагүй өөрчлөлт алдагдана. Үргэлжлүүлэх үү?')) { e.preventDefault(); return; }
    dirty = {};
    rowDirty = {};
  });

  // A swap that leaves a section's field block clean (saved or cancelled) clears its flag. A re-rendered form
  // (a failed save, data-dirty) keeps it, because the typed values are still unsaved.
  document.addEventListener('htmx:afterSwap', function (e) {
    var el = e.detail && e.detail.target;
    if (el && el.tagName === 'MAIN') { dirty = {}; rowDirty = {}; return; }  // the whole tab was redrawn
    var id = (el && el.id) || '';
    // A redrawn inline list keeps its row unsaved only when it came back with errors (its form is data-dirty);
    // other lists' rows are left as they are.
    if (id.indexOf('list-') === 0) {
      var kind = id.slice(5);
      rowDirty[kind] = !!document.querySelector('#inline-' + kind + '-form[data-dirty]');
      return;
    }
    var name = nameOf(id) || (id.indexOf('fields-') === 0 ? id.slice(7) : '');  // a field block (§2f) swaps alone
    if (!name) return;
    var form = document.getElementById('sec-' + name + '-form');  // not an inline list's form in the same section
    if (!form || (form.hasAttribute('data-on-spot') && !form.hasAttribute('data-dirty'))) delete dirty[name];
  });
  document.addEventListener('htmx:afterSettle', observe);

  // Inline list rows (UI_RULES §2f): Esc closes the open row unless it only closed a dropdown or a calendar,
  // and a row that a list redraw just opened gets the cursor (in its first box with an error, else its first box).
  // Other swaps (pop-ups, section saves, notes) never move the cursor into a row.
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    var row = e.target.closest && e.target.closest('[data-inline-row]');
    if (!row || document.querySelector('.sel-popup, .dp-popup')) return;
    var cancel = row.querySelector('[data-inline-cancel]');
    if (cancel) cancel.click();
  });
  document.addEventListener('htmx:afterSettle', function (e) {
    var id = (e.detail && e.detail.target && e.detail.target.id) || '';
    if (id.indexOf('list-') !== 0) return;
    var row = document.querySelector('#' + id + ' [data-inline-row]');
    if (!row || row.contains(document.activeElement)) return;
    var visible = function (el) { return el.offsetParent; };
    var invalid = row.querySelector('[aria-invalid="true"]');
    var target = invalid && (invalid.offsetParent ? invalid : invalid.parentNode.querySelector('.sel-combo'));
    var box = target || Array.prototype.find.call(row.querySelectorAll('input:not([type=hidden]), textarea'), visible);
    if (box) box.focus();
  });

  observe();
})();
