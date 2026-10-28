// Ctrl+K palette (docs/UI_RULES.md §6, spec §5). The pop-up is not in the page: base.html holds it in
// <template id="palette-template">, and this script clones it into <body> on open and removes it on close. An open
// `.fixed.inset-0.z-50` shell locks the page scroll (input.css), so a shell that stays in the page would lock it always.
// Pages without the template (the login page) get nothing from this script.
(function () {
  "use strict";

  var tpl = document.getElementById("palette-template");
  if (!tpl) return;

  var url = tpl.getAttribute("data-url");
  var DEBOUNCE_MS = 200;
  var RECENT_KEY = "palette-recent-" + (tpl.getAttribute("data-user") || "");  // per user: shared PCs do not mix them
  var RECENT_MAX = 5;
  var REF_SHAPE = /^(p:[0-9]{1,12}|s:\/[!-~]{0,200})$/;  // `p:<pk>` a person, `s:<path>` a fixed page; nothing else

  var shell = null;      // the open pop-up, null while closed
  var input = null;
  var results = null;
  var failed = null;     // the failure line, kept in the template; moved back into the box on a network error
  var opener = null;     // the element that had focus before opening, given focus back on close
  var timer = null;      // the debounce timer while a typed query waits
  var controller = null; // AbortController of the latest request
  var loading = false;   // true while the latest request is still in flight
  var busyTimer = null;  // the wait before a slow answer dims the list (markBusy)
  var BUSY_MS = 150;

  // Remembered references (Сүүлд нээсэн): short ids only, newest first, no names. Every storage access is guarded: a
  // blocked or full storage, or a value that is not ours, just means nothing is remembered or shown.
  function readRecent() {
    try {
      var list = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
      if (!Array.isArray(list)) return [];
      return list.filter(function (ref) { return typeof ref === "string" && REF_SHAPE.test(ref); }).slice(0, RECENT_MAX);
    } catch (err) {
      return [];
    }
  }

  function remember(ref) {
    if (!ref || !REF_SHAPE.test(ref)) return;
    var list = readRecent().filter(function (r) { return r !== ref; });
    list.unshift(ref);
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, RECENT_MAX)));
    } catch (err) {
      // storage blocked or full: the box is simply not remembered
    }
  }

  // A person or a fixed page the user opened from the palette. Quick actions carry no data-palette-ref, so they are not kept.
  function noteOpened(item) {
    remember(item.getAttribute("data-palette-ref"));
  }

  function open() {
    if (shell) return;
    opener = document.activeElement;
    shell = document.importNode(tpl.content.firstElementChild, true);
    document.body.appendChild(shell);
    input = shell.querySelector("[data-palette-input]");
    results = shell.querySelector("[data-palette-results]");
    failed = shell.querySelector("[data-palette-failed]");

    // A click on the dark overlay (not on the panel) closes; a click on a pop-up action opens it here (see activate);
    // a click on any other result follows its link as usual.
    shell.addEventListener("click", function (e) {
      var item = e.target.closest && e.target.closest("[data-palette-item]");
      if (item && !item.hasAttribute("data-palette-modal")) noteOpened(item);  // a plain result is a link: it is followed
      var modal = e.target.closest && e.target.closest("[data-palette-item][data-palette-modal]");
      if (modal) {
        e.preventDefault();
        activate(modal);
        return;
      }
      if (e.target === shell) close();
    });
    input.addEventListener("input", function () {
      clearTimeout(timer);
      clearSelection();  // the old answer must not be activated for the new query
      timer = setTimeout(function () {
        timer = null;
        search(input.value);
      }, DEBOUNCE_MS);
    });
    results.addEventListener("mousemove", function (e) {
      var item = e.target.closest && e.target.closest("[data-palette-item]");
      if (item && item.getAttribute("aria-selected") !== "true") select(item, false);
    });

    input.focus();
    search("");  // an empty box shows the screens list
  }

  function close() {
    if (!shell) return;
    clearTimeout(timer);
    timer = null;
    if (controller) controller.abort();
    controller = null;
    loading = false;
    clearBusy();
    shell.remove();
    shell = input = results = failed = null;
    var back = opener;
    opener = null;
    if (back && document.contains(back) && back.focus) back.focus();
  }

  // Opens a result. A quick action with data-palette-modal (a pop-up form) is loaded over the current page with htmx,
  // so the palette closes and the form appears where the user is; every other result is a page and is navigated to.
  function activate(item) {
    var href = item.getAttribute("href");
    noteOpened(item);
    if (!item.hasAttribute("data-palette-modal")) {
      window.location.assign(href);
      return;
    }
    close();
    if (window.htmx) window.htmx.ajax("GET", href, { target: "body", swap: "beforeend" });
    else window.location.assign(href);
  }

  // A slow answer dims the old list: after BUSY_MS the list gets opacity-60 and aria-busy, so a quick answer never flashes.
  // clearBusy runs on the answer, an error or close; a new query keeps the dim until its own answer.
  function markBusy() {
    clearTimeout(busyTimer);
    busyTimer = setTimeout(function () {
      busyTimer = null;
      if (!loading || !results) return;
      results.classList.add("opacity-60");
      results.setAttribute("aria-busy", "true");
    }, BUSY_MS);
  }

  function clearBusy() {
    clearTimeout(busyTimer);
    busyTimer = null;
    if (!results) return;
    results.classList.remove("opacity-60");
    results.removeAttribute("aria-busy");
  }

  function search(q) {
    if (controller) controller.abort();
    var mine = new AbortController();
    controller = mine;
    loading = true;
    markBusy();
    // The empty box also sends what the user opened last and the path of the page it was opened on (only the path,
    // no query or hash); the server re-checks every item, so these are only hints. A typed query sends neither.
    var extra = q.trim()
      ? ""
      : "&recent=" + encodeURIComponent(readRecent().join(",")) + "&from=" + encodeURIComponent(window.location.pathname);
    fetch(url + "?q=" + encodeURIComponent(q) + extra, { credentials: "same-origin", signal: mine.signal })
      .then(function (r) {
        // The session ended: the server sent the login page instead of the fragment. Reload the real page instead, so
        // the login page gets the page as `next`; do not show the login page in the box.
        if (r.redirected) {
          window.location.reload();
          return null;
        }
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.text();
      })
      .then(function (html) {
        if (html === null || !shell || mine !== controller) return;  // navigating away, closed, or superseded
        loading = false;
        clearBusy();
        results.innerHTML = html;  // the server's own fragment, trusted
        results.scrollTop = 0;
        highlightFirst();
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") return;  // a stale request, cancelled on purpose
        if (!shell || mine !== controller) return;
        loading = false;
        clearBusy();
        results.innerHTML = "";
        failed.hidden = false;
        results.appendChild(failed);
      });
  }

  function items() {
    return results ? results.querySelectorAll("[data-palette-item]") : [];
  }

  function highlightFirst() {
    var list = items();
    for (var i = 0; i < list.length; i++) list[i].setAttribute("aria-selected", i === 0 ? "true" : "false");
  }

  function clearSelection() {
    var list = items();
    for (var i = 0; i < list.length; i++) list[i].setAttribute("aria-selected", "false");
  }

  // scroll only for keyboard moves: a hover must not scroll the list under the pointer.
  function select(item, scroll) {
    var list = items();
    for (var i = 0; i < list.length; i++) {
      list[i].setAttribute("aria-selected", list[i] === item ? "true" : "false");
    }
    if (scroll) item.scrollIntoView({ block: "nearest" });
  }

  function move(step) {
    var list = items();
    if (!list.length) return;
    var cur = -1;
    for (var i = 0; i < list.length; i++) if (list[i].getAttribute("aria-selected") === "true") cur = i;
    var next;
    if (cur < 0) next = step > 0 ? 0 : list.length - 1;  // nothing highlighted yet
    else next = (cur + step + list.length) % list.length;  // wraps at both ends
    select(list[next], true);
  }

  // Capture phase on document: runs before any field, the employee page's drawer handler and modal.js, so while the
  // palette is open its keys stop here (Escape closes only the palette).
  document.addEventListener(
    "keydown",
    function (e) {
      // e.code, not e.key: on a Cyrillic layout the key that gives K reports e.key as «к». No AltGr (e.altKey) combos.
      if (e.code === "KeyK" && (e.ctrlKey || e.metaKey) && !e.altKey) {
        e.preventDefault();
        e.stopPropagation();
        if (e.repeat) return;  // holding the keys must not flicker the pop-up open and shut
        if (shell) close();
        else open();
        return;
      }
      // Keys of an IME composition belong to the input method, not to the palette.
      if (e.isComposing || e.keyCode === 229) return;
      if (!shell) return;
      if (e.key === "Tab") {
        // Focus must not leave into the page behind the pop-up.
        e.preventDefault();
        e.stopPropagation();
      } else if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        e.stopPropagation();
        move(1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        e.stopPropagation();
        move(-1);
      } else if (e.key === "Enter") {
        e.preventDefault();
        e.stopPropagation();
        // A query still waiting (debounce) or in flight: the highlighted row is not the answer yet, so do not
        // open it. A waiting query is sent now; the user presses Enter again once the new list is in.
        if (timer) {
          clearTimeout(timer);
          timer = null;
          search(input.value);
        }
        if (loading) return;
        var cur = results.querySelector('[data-palette-item][aria-selected="true"]');
        if (cur) activate(cur);
      }
    },
    true
  );

  // The top-bar button (base.html) opens the palette; delegated, so it works whatever the page does to the bar.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-palette-open]");
    if (!btn) return;
    e.preventDefault();
    open();
  });
})();
