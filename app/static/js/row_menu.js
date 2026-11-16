// Row menus inside a scrolling table frame (UI_RULES §4, .ptable-fit): a <details data-row-menu> whose panel is marked
// [data-row-menu-panel]. A scroll box would clip an absolute panel, so on open the panel is pinned to the screen
// (position: fixed) under its button, right edges aligned, and opens upward when there is no room below. Scrolling the
// table or the page, or resizing, closes it, so it never drifts away from its row.
(function () {
  function place(menu) {
    var panel = menu.querySelector("[data-row-menu-panel]");
    var btn = menu.querySelector("summary");
    if (!panel || !btn) return;
    var r = btn.getBoundingClientRect();
    panel.style.position = "fixed";
    panel.style.zIndex = "40";  // above the pinned header row (z-20/30)
    panel.style.marginTop = "0";
    var w = panel.offsetWidth;
    if (r.right - w >= 8) { panel.style.left = "auto"; panel.style.right = Math.max(8, window.innerWidth - r.right) + "px"; }
    else { panel.style.right = "auto"; panel.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + "px"; }  // no room on the left (narrow screen): align to the button's left edge
    var h = panel.offsetHeight;
    var below = window.innerHeight - r.bottom;
    if (below < h + 8 && r.top > below) { panel.style.top = "auto"; panel.style.bottom = (window.innerHeight - r.top + 4) + "px"; }
    else { panel.style.bottom = "auto"; panel.style.top = (r.bottom + 4) + "px"; }
  }

  function closeAll(except) {
    document.querySelectorAll("details[data-row-menu][open]").forEach(function (m) {
      if (m === except) return;
      if (window.hrCloseMenu) window.hrCloseMenu(m); else m.removeAttribute("open");
    });
  }

  document.addEventListener("toggle", function (e) {
    var m = e.target;
    if (!(m instanceof HTMLDetailsElement) || !m.hasAttribute("data-row-menu") || !m.open) return;
    closeAll(m);
    place(m);
  }, true);  // toggle does not bubble

  document.addEventListener("click", function (e) {
    if (!(e.target instanceof Element) || !e.target.closest("details[data-row-menu]")) closeAll(null);
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeAll(null); });
  document.addEventListener("scroll", function (e) {
    if (e.target instanceof Element && e.target.closest("[data-row-menu-panel]")) return;  // a long panel scrolling itself
    closeAll(null);
  }, { capture: true, passive: true });
  window.addEventListener("resize", function () { closeAll(null); });
})();
