// Top bar menus (base.html, details[data-nav-menu]): open on hover with a mouse; one open at a time; an outside
// click, Escape, scrolling the menu strip or resizing the window closes them. A strip menu's panel is `fixed` so the
// strip's sideways scroll box does not cut it off; when it would run past the window's right edge it is moved left.
(function () {
  function closeAll(except) {
    document.querySelectorAll('details[data-nav-menu][open]').forEach(function (menu) {
      if (menu !== except) menu.open = false;
    });
  }

  document.addEventListener('toggle', function (e) {
    var menu = e.target;
    if (!(menu instanceof HTMLDetailsElement) || !menu.matches('[data-nav-menu]') || !menu.open) return;
    closeAll(menu);
    var panel = menu.querySelector('[data-nav-panel]');
    if (!panel || getComputedStyle(panel).position !== 'fixed') return;
    panel.style.left = '';
    var box = panel.getBoundingClientRect();
    if (box.right > window.innerWidth - 8) panel.style.left = Math.max(8, window.innerWidth - box.width - 8) + 'px';
  }, true);  // toggle does not bubble

  document.addEventListener('click', function (e) {
    if (!(e.target instanceof Element) || !e.target.closest('details[data-nav-menu]')) closeAll(null);
  });

  // Capture phase, so Escape that closes a menu does not also close the activity drawer.
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var open = document.querySelector('details[data-nav-menu][open]');
    if (!open) return;
    open.open = false;
    open.querySelector('summary').focus();
    e.stopPropagation();
  }, true);

  // With a mouse, a menu opens on hover and closes a moment after the pointer leaves (so it can cross the gap to the
  // panel). A click on an open menu's label keeps it open; keyboard and touch still open and close it by click/Enter.
  var hover = window.matchMedia('(hover: hover) and (pointer: fine)');
  document.querySelectorAll('details[data-nav-menu]').forEach(function (menu) {
    var timer = 0;
    function later(open, ms) {
      clearTimeout(timer);
      timer = setTimeout(function () { menu.open = open; }, ms);
    }
    menu.addEventListener('mouseenter', function () { if (hover.matches) later(true, 60); });
    menu.addEventListener('mouseleave', function () { if (hover.matches) later(false, 200); });
    menu.querySelector('summary').addEventListener('click', function (e) {
      clearTimeout(timer);
      if (hover.matches && e.detail > 0 && menu.open) e.preventDefault();  // e.detail 0 = keyboard: toggle as usual
    });
  });

  var strip = document.querySelector('[data-nav]');
  if (strip) strip.addEventListener('scroll', function () { closeAll(null); }, { passive: true });
  window.addEventListener('resize', function () { closeAll(null); });

  // Theme switch (its own header menu): Цайвар / Бараан saves the choice in this browser; Автомат forgets it and follows
  // the computer's setting, live. The script at the top of base.html applies the saved choice before first paint.
  var systemDark = window.matchMedia('(prefers-color-scheme: dark)');
  function savedTheme() {
    try { return localStorage.getItem('theme'); } catch (e) { return null; }
  }
  function applyTheme(picked) {
    var saved = picked || savedTheme();
    var choice = saved === 'light' || saved === 'dark' ? saved : 'auto';
    document.documentElement.dataset.theme = choice === 'auto' ? (systemDark.matches ? 'dark' : 'light') : choice;
    document.querySelectorAll('[data-theme-choice]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.themeChoice === choice));
    });
  }
  document.addEventListener('click', function (e) {
    var b = e.target instanceof Element && e.target.closest('[data-theme-choice]');
    if (!b) return;
    try {
      if (b.dataset.themeChoice === 'auto') localStorage.removeItem('theme');
      else localStorage.setItem('theme', b.dataset.themeChoice);
    } catch (err) { /* storage blocked: the choice lasts until the page changes */ }
    applyTheme(b.dataset.themeChoice);
  });
  systemDark.addEventListener('change', function () { applyTheme(); });
  applyTheme();
})();
