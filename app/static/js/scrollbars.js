// The app's scrollbars (UI_RULES §4). Native scrollbars cannot animate, so every scroll box gets its native bars hidden
// (.sbar-on) and two rails drawn over its edges: a hairline track with a progress fill that starts at the share in view
// and grows from the start edge as you scroll, tipped in the accent; on hover or drag the fill thickens into the page
// loading bar's gradient (CSS: .sbar-*). Press-and-drag anywhere on a rail; wheel, keyboard and touch scrolling of the
// box itself keep working, the rails only mirror and drive scrollTop/Left. Three kinds:
//   host  - long table frames (.ptable-fit): wrapped in .sbar-host, rails inside it, plus edge fades for hidden columns
//   float - any other scroll box (overflow auto/scroll: menus, lists, pop-ups, tab strips): rails are position: fixed
//           in <body>, laid over the box's edges and clipped to what of it is visible; the page structure is untouched
//   page  - the document itself: one vertical rail on the right edge, under the top bar
// Text areas keep the native style (it is styled to match at the end of input.css).
(function () {
  var MIN = 28;    // shortest fill, px
  var LANE = 12;   // rail thickness, px
  var bars = [];
  var CANDIDATES = ".ptable, .sel-list, [class*='overflow-x-auto'], [class*='overflow-y-auto'], [class*='overflow-auto']," +
    " [class*='overflow-scroll'], [class*='overflow-x-scroll'], [class*='overflow-y-scroll'], [style*='overflow']";

  function el(cls) {
    var d = document.createElement("div");
    d.className = cls;
    d.setAttribute("aria-hidden", "true");
    return d;
  }

  function scrolls(node) {
    if (node.tagName === "TEXTAREA" || node.closest(".sbar-rail, [data-sbar='off']")) return false;
    var s = getComputedStyle(node);
    return /(auto|scroll)/.test(s.overflowX + s.overflowY);
  }

  function zOf(node) {  // float rails sit just above the stacking layer their box lives in
    var z = 0;
    for (var e = node; e && e !== document.body; e = e.parentElement) {
      var v = parseInt(getComputedStyle(e).zIndex, 10);
      if (!isNaN(v)) z = Math.max(z, v);
    }
    return z + 1;
  }

  function clipOf(node) {  // the part of the viewport the box can be seen in (its scrolling / clipping ancestors)
    var c = { l: 0, t: 0, r: window.innerWidth, b: window.innerHeight };
    for (var e = node.parentElement; e && e !== document.body && e !== document.documentElement; e = e.parentElement) {
      var s = getComputedStyle(e);
      if (s.overflowX === "visible" && s.overflowY === "visible") continue;
      var r = e.getBoundingClientRect();
      c.l = Math.max(c.l, r.left); c.t = Math.max(c.t, r.top); c.r = Math.min(c.r, r.right); c.b = Math.min(c.b, r.bottom);
    }
    return c;
  }

  function Bar(box, kind) {
    var page = kind === "page";
    var sc = page ? document.scrollingElement : box;  // what holds the scroll values
    var self = { box: box, kind: kind };
    var rails = { x: rail("x"), y: rail("y") };
    var fades = null, host = null;

    function rail(axis) {
      var r = el("sbar-rail sbar-" + axis + (kind === "host" ? "" : " sbar-fixed") + (page ? " sbar-page" : ""));
      var thumb = el("sbar-thumb");
      r.appendChild(thumb);
      return { el: r, thumb: thumb, axis: axis };
    }

    if (kind === "host") {
      host = box.parentElement;
      if (host && host.classList.contains("sbar-host")) {  // the frame was swapped in place (htmx outerHTML): reuse the host
        host.querySelectorAll(":scope > .sbar-rail, :scope > .sbar-fade").forEach(function (r) { r.remove(); });
      } else {
        host = document.createElement("div");
        host.className = "sbar-host";
        box.parentNode.insertBefore(host, box);
        host.appendChild(box);
      }
      fades = { l: el("sbar-fade sbar-fade-l"), r: el("sbar-fade sbar-fade-r") };
      [fades.l, fades.r, rails.x.el, rails.y.el].forEach(function (n) { host.appendChild(n); });
    } else {
      document.body.appendChild(rails.x.el);
      document.body.appendChild(rails.y.el);
      if (!page) self.z = zOf(box);
    }
    if (page) document.documentElement.classList.add("sbar-page-on");
    else box.classList.add("sbar-on");

    function sizes(r) {
      var x = r.axis === "x";
      var view = page ? (x ? window.innerWidth : window.innerHeight) : (x ? sc.clientWidth : sc.clientHeight);
      var full = x ? sc.scrollWidth : sc.scrollHeight;
      var track = x ? r.el.clientWidth : r.el.clientHeight;
      return { view: view, full: full, track: track, max: Math.max(0, full - view) };
    }

    function fill(r) {  // progress fill: starts at the share in view, grows to the whole rail at the end
      var s = sizes(r);
      var done = s.max > 0 ? (r.axis === "x" ? sc.scrollLeft : sc.scrollTop) / s.max : 0;
      var start = Math.max(MIN, Math.min(s.track, s.track * s.view / Math.max(1, s.full)));
      r.thumb.style[r.axis === "x" ? "width" : "height"] = Math.round(start + (s.track - start) * Math.min(1, done)) + "px";
    }

    function show(r, on) { r.el.classList.toggle("is-on", on); return on; }

    self.paint = function () {
      var rx = rails.x.el.style, ry = rails.y.el.style;
      if (page) {
        var lock = getComputedStyle(document.body).overflowY === "hidden";  // a pop-up holds the page still
        var head = document.querySelector("body > header");
        var top = head ? Math.max(0, head.getBoundingClientRect().bottom) : 0;
        show(rails.x, false);
        if (show(rails.y, !lock && sc.scrollHeight > window.innerHeight + 1)) {
          ry.top = top + "px"; ry.height = (window.innerHeight - top) + "px"; ry.left = (window.innerWidth - LANE) + "px";
          fill(rails.y);
        }
        return;
      }
      var w = box.clientWidth, h = box.clientHeight;
      var needX = box.scrollWidth > w + 1, needY = box.scrollHeight > h + 1;
      if (kind === "host") {
        var t = box.offsetTop + box.clientTop, l = box.offsetLeft + box.clientLeft;
        if (show(rails.x, needX)) { rx.left = l + "px"; rx.width = (w - (needY ? LANE : 0)) + "px"; rx.top = (t + h - LANE) + "px"; fill(rails.x); }
        if (show(rails.y, needY)) { ry.top = t + "px"; ry.height = (h - (needX ? LANE : 0)) + "px"; ry.left = (l + w - LANE) + "px"; fill(rails.y); }
        // edge fades: a soft shade on a side while columns are hidden past it; the left one starts after pinned columns
        var maxX = box.scrollWidth - w, pin = 0;
        box.querySelectorAll("thead th.sticky").forEach(function (th) { pin = Math.max(pin, th.offsetLeft + th.offsetWidth); });
        var fl = fades.l.style, fr = fades.r.style;
        fl.top = fr.top = t + "px"; fl.height = fr.height = h + "px";
        fl.left = (l + pin) + "px"; fr.left = (l + w - 24) + "px";
        fades.l.classList.toggle("is-on", needX && box.scrollLeft > 1);
        fades.r.classList.toggle("is-on", needX && box.scrollLeft < maxX - 1);
        return;
      }
      // float: the box's inner edges on screen, cut to the part of it that can be seen
      var b = box.getBoundingClientRect();
      var L = b.left + box.clientLeft, T = b.top + box.clientTop, R = L + w, B = T + h;
      var c = clipOf(box);
      var vis = box.checkVisibility ? box.checkVisibility({ visibilityProperty: true }) : true;  // closed <details> content keeps a size
      var seen = vis && b.width > 0 && b.height > 0 && R > c.l && L < c.r && B > c.t && T < c.b;
      rx.zIndex = ry.zIndex = self.z;
      // a box taller than the screen keeps its sideways bar at the bottom of what is visible, not off-screen below
      var xb = Math.min(B, c.b);
      if (show(rails.x, seen && needX && xb - LANE >= Math.max(T, c.t))) {
        var x0 = Math.max(L, c.l), x1 = Math.min(R - (needY ? LANE : 0), c.r);
        rx.left = x0 + "px"; rx.width = Math.max(0, x1 - x0) + "px"; rx.top = (xb - LANE) + "px";
        fill(rails.x);
      }
      if (show(rails.y, seen && needY && R - LANE >= c.l && R <= c.r + 1)) {
        var y0 = Math.max(T, c.t), y1 = Math.min(B - (needX ? LANE : 0), c.b);
        ry.top = y0 + "px"; ry.height = Math.max(0, y1 - y0) + "px"; ry.left = (R - LANE) + "px";
        fill(rails.y);
      }
    };

    // press anywhere on a rail and drag: the fill's end follows the pointer, so the box scrolls to that point
    function drag(r, e) {
      e.preventDefault();
      var x = r.axis === "x";
      function to(ev) {
        var rect = r.el.getBoundingClientRect(), s = sizes(r);
        var at = (x ? ev.clientX - rect.left : ev.clientY - rect.top) - MIN / 2;
        var v = Math.max(0, Math.min(1, at / Math.max(1, s.track - MIN))) * s.max;
        if (x) sc.scrollLeft = v; else sc.scrollTop = v;
      }
      r.el.classList.add("is-drag");
      r.el.setPointerCapture(e.pointerId);
      to(e);
      function up() {
        r.el.classList.remove("is-drag");
        r.el.removeEventListener("pointermove", to);
        r.el.removeEventListener("pointerup", up);
        r.el.removeEventListener("pointercancel", up);
      }
      r.el.addEventListener("pointermove", to);
      r.el.addEventListener("pointerup", up);
      r.el.addEventListener("pointercancel", up);
    }
    ["x", "y"].forEach(function (a) {
      rails[a].el.addEventListener("pointerdown", function (e) { drag(rails[a], e); });
      rails[a].el.addEventListener("wheel", function (e) {  // a wheel over a float rail still scrolls its box
        if (kind === "float") { e.preventDefault(); sc.scrollBy(e.deltaX, e.deltaY); }
      }, { passive: false });
    });

    self.alive = function () { return page || box.isConnected; };
    self.destroy = function () {
      rails.x.el.remove(); rails.y.el.remove();
      if (fades) { fades.l.remove(); fades.r.remove(); }
    };
    if (window.ResizeObserver && !page) {
      var ro = new ResizeObserver(schedule);
      ro.observe(box);
      if (box.firstElementChild) ro.observe(box.firstElementChild);
      self.destroy = (function (d) { return function () { ro.disconnect(); d(); }; })(self.destroy);
    }
    box._sbar = self;
    bars.push(self);
    self.paint();
    return self;
  }

  function scan() {
    if (!document.body) return;
    if (!document.documentElement._sbar) Bar(document.documentElement, "page");
    document.querySelectorAll(".ptable-fit").forEach(function (b) { if (!b._sbar) Bar(b, "host"); });
    document.querySelectorAll(CANDIDATES).forEach(function (b) {
      if (!b._sbar && !b.classList.contains("ptable-fit") && scrolls(b)) Bar(b, "float");
    });
  }

  var queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(function () {
      queued = false;
      bars = bars.filter(function (b) {
        if (b.alive()) return true;
        b.destroy(); b.box._sbar = null;
        return false;
      });
      bars.forEach(function (b) { b.paint(); });
    });
  }

  var scanQueued = false;
  function rescan() {  // DOM changed (pop-up opened, menu built, htmx swap): pick up new scroll boxes
    if (scanQueued) return;
    scanQueued = true;
    setTimeout(function () { scanQueued = false; scan(); schedule(); }, 60);
  }

  window.hrScrollbars = { init: rescan, repaint: schedule };
  document.addEventListener("scroll", schedule, { capture: true, passive: true });
  window.addEventListener("resize", schedule);
  ["toggle", "animationend", "transitionend", "htmx:afterSettle", "pointerup", "keyup"].forEach(function (t) {
    document.addEventListener(t, schedule, true);
  });
  function start() {
    scan();
    new MutationObserver(function (list) {
      for (var i = 0; i < list.length; i++) {  // ignore the rails' own changes
        var t = list[i].target;
        if (!(t.classList && /sbar-/.test(t.className))) { rescan(); return; }
      }
    }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "open", "hidden"] });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
