// Personal tab: each topic group is a collapsible <details data-pgroup> (UI_RULES §8). A group that holds an error or unsaved
// input opens itself, and the address (#personal-<group>) opens its group and scrolls to it. Sections edited on the spot
// show their save strip once changed, and unsaved changes ask before the page is left. Sections are plain elements with id sec-<name>.
(function () {
  if (!document.querySelector('[data-pgroup]')) return;
  var dirty = {};  // section name -> true while its form has unsaved input
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function nameOf(id) { return id && id.indexOf('sec-') === 0 ? id.slice(4) : ''; }

  // The groups are looked up on each use: a Work-tab save redraws <main>, groups included.
  function groups() { return document.querySelectorAll('[data-pgroup]'); }
  function groupEl(key) {
    var found = null;
    groups().forEach(function (g) { if (g.getAttribute('data-pgroup') === key) found = g; });
    return found;
  }
  // The open state each group was left in by the reader (a Work-tab save redraws the groups; see restoreGroups).
  // Only the reader's own clicks on a group's summary record it: a <details open> that the parser makes after a redraw
  // fires toggle too, and recording that would reopen a group the reader had closed.
  var openState = {};
  function recordOpen(g) { openState[g.getAttribute('data-pgroup')] = g.open; }
  document.addEventListener('click', function (e) {
    var s = e.target.closest && e.target.closest('details[data-pgroup] > summary');
    if (!s) return;
    var g = s.parentNode;
    // The browser flips g.open as the click's default action, after this listener: read it once that has happened.
    setTimeout(function () { recordOpen(g); }, 0);
  });

  // A group with an error or unsaved input opens itself (UI_RULES §2d, §2f). It only ever opens, never closes.
  function openMarked() {
    groups().forEach(function (g) {
      if (g.querySelector('[aria-invalid="true"], [data-dirty]')) g.open = true;
    });
  }
  // A redraw puts every group back to its server state: the groups keep the state the reader left them in, and a
  // group with an error or unsaved input opens.
  function restoreGroups() {
    groups().forEach(function (g) {
      var key = g.getAttribute('data-pgroup');
      if (Object.prototype.hasOwnProperty.call(openState, key)) g.open = openState[key];
    });
    openMarked();
  }
  // employee_field_focus.js opens the closed group of a field through this (UI_RULES §2e). It does not scroll: the field does.
  // The animate argument is kept for its callers; a group opens at once, it no longer swaps in.
  window.hrOpenGroup = function (key, animate) {
    var g = groupEl(key);
    if (g) { g.open = true; recordOpen(g); }  // a link the reader followed counts as their choice
  };
  // The address names a group as #personal-<group>: that group opens and scrolls into view, so a reload or Back keeps it.
  function hashGroup() {
    var h = location.hash.slice(1);
    return h.indexOf('personal-') === 0 ? h.slice(9) : '';
  }
  function showHashGroup() {
    var g = groupEl(hashGroup());
    if (!g) return;
    g.open = true;
    recordOpen(g);
    g.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
  }
  window.addEventListener('hashchange', showHashGroup);

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
    // The in-app dialog answers later: stop this send, and on «yes» forget the unsaved values and send the form again.
    var form = e.detail.elt;
    e.preventDefault();
    window.hrConfirm('Хувийн табын хадгалаагүй өөрчлөлт алдагдана. Үргэлжлүүлэх үү?', function () {
      dirty = {};
      rowDirty = {};
      if (form.requestSubmit) form.requestSubmit(); else form.submit();
    }, { ok: 'Үргэлжлүүлэх' });
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
  document.addEventListener('htmx:afterSettle', restoreGroups);

  // Inline list rows (UI_RULES §2f): Esc closes the open row unless it only closed a dropdown or a calendar,
  // and a row that a list redraw just opened gets the cursor (in its first box with an error, else its first box).
  // Other swaps (pop-ups, section saves, notes) never move the cursor into a row.
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    var row = e.target.closest && e.target.closest('[data-inline-row]');
    if (!row || document.querySelector('.sel-popup:not([data-leaving]), .dp-popup:not([data-leaving])')) return;
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

  // Inline list swaps (UI_RULES §2f; plan task 8). A list is redrawn as a whole (#list-<kind>), so htmx's own added class
  // would fade the whole block; sections.js instead marks the rows that a swap added (.row-enter, styled in input.css). Before
  // the swap it notes the row keys the list had; after it, a row with a new key fades in.
  var listKeys = null, listKeysId = '';
  function rowKeys(block) {
    return Array.prototype.map.call(block.querySelectorAll('tr[data-row-key]'), function (r) { return r.getAttribute('data-row-key'); });
  }
  // One listener for every list swap. A successful delete (the Тийм button, data-inline-delete) collapses its row first; its
  // swap waits 140 ms (swap:140ms on the button). A failed delete comes back with the row open and its message, so it stays.
  document.addEventListener('htmx:beforeSwap', function (e) {
    var d = e.detail || {};
    var t = d.target;
    if (t && t.id && t.id.indexOf('list-') === 0) { listKeys = rowKeys(t); listKeysId = t.id; }
    // The issuing button is requestConfig.elt (detail.elt is the swap target); the decision is motion.js deleteRow.
    var row = window.hrDeleteRow && window.hrDeleteRow(d);
    if (row && window.hrCollapse) window.hrCollapse(row);
  });
  // The event's target is the replaced element, so the redrawn list is looked up by its id.
  document.addEventListener('htmx:afterSwap', function (e) {
    var id = e.detail && e.detail.target && e.detail.target.id;
    if (!id || id !== listKeysId || !listKeys) return;
    var before = listKeys;
    listKeys = null;
    var block = document.getElementById(id);
    if (!block) return;
    block.querySelectorAll('tr[data-row-key]').forEach(function (tr) {
      if (before.indexOf(tr.getAttribute('data-row-key')) === -1) tr.classList.add('row-enter');
    });
  });

  // Printing shows every group: a closed one opens for the print and closes again after it (a closed <details> hides its content).
  var printOpened = [];
  window.addEventListener('beforeprint', function () {
    printOpened = [];
    groups().forEach(function (g) { if (!g.open) { g.open = true; printOpened.push(g); } });
  });
  window.addEventListener('afterprint', function () {
    printOpened.forEach(function (g) { g.open = false; });
    printOpened = [];
  });

  openMarked();
  showHashGroup();
})();
