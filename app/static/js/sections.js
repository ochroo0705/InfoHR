// Personal tab: the section menu follows the section in view, and a section with unsaved changes asks
// before another section's "Засах" replaces it. Sections are plain elements with id sec-<name>.
(function () {
  var menu = document.getElementById('personal-nav');
  if (!menu) return;
  var ON = ['text-violet-700', 'font-semibold'];
  var dirty = {};  // section name -> true while its form has unsaved input
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function nameOf(id) { return id && id.indexOf('sec-') === 0 ? id.slice(4) : ''; }

  function highlight(name) {
    menu.querySelectorAll('a[data-sec]').forEach(function (a) {
      var on = a.getAttribute('data-sec') === name;
      ON.forEach(function (c) { a.classList.toggle(c, on); });
      if (on) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
    });
  }

  // The section that is most in view (under the top bar) gets its menu link marked.
  var io = null;
  function observe() {
    if (!('IntersectionObserver' in window)) return;
    if (io) io.disconnect();
    io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) highlight(nameOf(entry.target.id));
      });
    }, { rootMargin: '-96px 0px -60% 0px' });
    document.querySelectorAll('section[id^="sec-"]').forEach(function (s) { io.observe(s); });
  }

  // Menu links scroll to the section; the URL is not changed (the page reloads on its #hash).
  menu.addEventListener('click', function (e) {
    var a = e.target.closest('a[data-sec]');
    if (!a) return;
    var el = document.getElementById('sec-' + a.getAttribute('data-sec'));
    if (!el) return;
    e.preventDefault();
    el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
  });

  // Typing in a section form marks that section dirty; a save or cancel swaps the section and clears it.
  document.addEventListener('input', function (e) { markDirty(e); });
  document.addEventListener('change', function (e) { markDirty(e); });
  function markDirty(e) {
    var form = e.target.form;
    if (form && form.id && /^sec-.+-form$/.test(form.id)) dirty[form.id.slice(4, -5)] = true;
  }

  // A "Засах" button of another section would replace the dirty one: ask first.
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[hx-get*="edit=1"]');
    if (!btn) return;
    var target = nameOf((btn.getAttribute('hx-target') || '').replace('#', ''));
    var others = Object.keys(dirty).filter(function (name) { return dirty[name] && name !== target; });
    if (!others.length) return;
    if (window.confirm('Хадгалаагүй өөрчлөлт байна. Орхих уу?')) {
      dirty = {};
      return;
    }
    e.preventDefault();
    e.stopPropagation();
  }, true);

  // A swap that leaves a section in read mode (saved or cancelled) clears its flag. A re-rendered form
  // (a failed save) keeps it, because the typed values are still unsaved.
  document.addEventListener('htmx:afterSwap', function (e) {
    var el = e.detail && e.detail.target;
    var name = nameOf(el && el.id);
    if (!name) return;
    var section = document.getElementById('sec-' + name);
    if (!section || !section.querySelector('form')) delete dirty[name];
  });
  document.addEventListener('htmx:afterSettle', observe);

  observe();
})();
