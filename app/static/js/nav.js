// Top bar menus (base.html, details[data-nav-menu]): open on hover with a mouse; one open at a time; an outside
// click, Escape, scrolling the menu strip or resizing the window closes them. A strip menu's panel is `fixed` so the
// strip's sideways scroll box does not cut it off; when it would run past the window's right edge it is moved left.
(function () {
  // The one place that closes a menu (a details[data-nav-menu], or a row/header details menu whose panel is marked
  // [data-nav-panel]). The panel plays its exit through window.hrLeave and the menu closes when the exit is done, so a
  // closing menu does not vanish at once. While a panel is already leaving, a second close does nothing: the exit in
  // flight closes the menu. If the user clicks the summary during that exit, the native <details> toggles at once and
  // the exit's done() then leaves it closed, so the next click opens it (the in-flight exit completes; no cancel logic).
  // Without hrLeave, or with no panel, the menu closes at once. Each exit has its own token (menu.__closing): reopen()
  // clears it, so the stale done() of an undone exit does nothing. Exported for the Node tests (nav.test.mjs).
  function createCloser(hrLeaveFn) {
    return function closeMenu(menu) {
      if (!menu) return;
      var panel = menu.querySelector('[data-nav-panel]');
      if (menu.open && panel && typeof hrLeaveFn === 'function') {
        if (panel.hasAttribute('data-leaving')) return;
        var token = menu.__closing = {};
        hrLeaveFn(panel, {
          done: function () {
            if (menu.__closing !== token) return;  // undone by reopen(), or a newer exit has taken over
            menu.__closing = null;
            panel.removeAttribute('data-leaving');
            panel.inert = false;
            menu.open = false;
          },
        });
        return;
      }
      menu.open = false;
    };
  }

  // Cancels a menu's exit in flight (if any): the panel is shown again and the pending done() does nothing. A menu
  // that is not leaving is left alone.
  function reopen(menu) {
    if (!menu) return;
    var panel = menu.querySelector('[data-nav-panel]');
    if (!panel || !panel.hasAttribute('data-leaving')) return;
    menu.__closing = null;
    panel.removeAttribute('data-leaving');
    panel.inert = false;
  }

  // The open menu that Escape closes: the first open one whose panel is not leaving. A menu mid-exit is still [open]
  // until its exit ends, so it is skipped and the menu the user really has open is the one closed. Null when none.
  function pickOpenMenu(menus) {
    for (var i = 0; i < menus.length; i++) {
      var menu = menus[i];
      if (!menu.open) continue;
      var panel = menu.querySelector('[data-nav-panel]');
      if (panel && panel.hasAttribute('data-leaving')) continue;
      return menu;
    }
    return null;
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { createCloser: createCloser, reopen: reopen, pickOpenMenu: pickOpenMenu };
    return;
  }

  // Browser only from here on. motion.js (window.hrLeave) is loaded before this script (base.html).
  var closeMenu = createCloser(window.hrLeave);
  // Row and header «Үйлдэл ▾» / «Өөрчлөлт бүртгэх ▾» menus call this from an inline onclick.
  window.hrCloseMenu = closeMenu;

  function closeAll(except) {
    document.querySelectorAll('details[data-nav-menu][open]').forEach(function (menu) {
      if (menu !== except) closeMenu(menu);
    });
  }

  document.addEventListener('toggle', function (e) {
    var menu = e.target;
    if (!(menu instanceof HTMLDetailsElement) || !menu.matches('[data-nav-menu]') || !menu.open) return;
    reopen(menu);
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
    var open = pickOpenMenu(document.querySelectorAll('details[data-nav-menu][open]'));
    if (!open) return;
    closeMenu(open);
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
      timer = setTimeout(function () {
        if (open) {
          reopen(menu);
          menu.open = true;
        } else {
          closeMenu(menu);
        }
      }, ms);
    }
    menu.addEventListener('mouseenter', function () { if (hover.matches) later(true, 60); });
    menu.addEventListener('mouseleave', function () { if (hover.matches) later(false, 200); });
    // A summary click on an open menu is handled here so that every close is eased, not only the hover-out one:
    // a click during an exit reopens the menu; a mouse click on an open menu in hover mode keeps it open; any other
    // click on an open menu (keyboard, touch, no-hover pointer) closes it through closeMenu. A closed menu opens by the
    // native toggle (its panel is never leaving then).
    menu.querySelector('summary').addEventListener('click', function (e) {
      clearTimeout(timer);
      if (!menu.open) return;
      var panel = menu.querySelector('[data-nav-panel]');
      var leaving = !!(panel && panel.hasAttribute('data-leaving'));
      e.preventDefault();
      if (!leaving && hover.matches && e.detail > 0) return;  // hover mode, mouse: stays open
      if (leaving) reopen(menu);
      else closeMenu(menu);
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
