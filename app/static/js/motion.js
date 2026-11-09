// Shared exit helpers (plan 2026-11-08-selection-motion, tasks 3 and 8).
//
// window.hrLeave(el, opts?) marks an element as leaving, makes it inert, plays its exit animation (the [data-leaving] rules
// in static/css/input.css) and then removes it, or calls opts.done. It finishes on the element's own animationend, or on a
// transitionend of opacity or transform, or after FALLBACK_MS, whichever comes first. Under prefers-reduced-motion, or when
// the element is not connected, it finishes at once. A second call on an element that is already leaving is ignored.
//
// CONTRACT for opts.done: it must remove or hide the element, and it must not throw. If it throws, the exit still ends
// (the leaving state is cleared in a finally block) and the error is rethrown; an element that is left in place and still
// inert would otherwise stay stuck, so keep done trivial.
//
// window.hrCollapse(el) is the removal form for table rows (inline lists, task 8): hrLeave with the default done, which
// removes the element. The row fades through the same [data-leaving] exit; a row cannot shrink its height without layout
// bugs, so it is not animated.
//
// Classic browser script: under Node it exports createLeave, createCollapse and hrLeave for tests.
(function () {
  "use strict";

  // The fallback exit timer. It must stay above --dur-out (140 ms in input.css), or the timer would end the exit before its
  // animation has played; it must stay under 300 ms, the longest motion anywhere in the app.
  var FALLBACK_MS = 250;
  var REDUCED_QUERY = "(prefers-reduced-motion: reduce)";
  // Only these transitions end an exit; a colour or border transition on the element must not cut the exit short.
  var EXIT_PROPERTIES = Object.assign(Object.create(null), { opacity: true, transform: true });

  // The browser's own accessors, looked up at call time (so a test can replace window.matchMedia).
  function browserEnv() {
    return {
      matchMedia: function (query) {
        if (typeof window !== "undefined" && window.matchMedia) return window.matchMedia(query);
        return { matches: false };
      },
      setTimeout: function (fn, ms) {
        return setTimeout(fn, ms);
      },
      clearTimeout: function (id) {
        clearTimeout(id);
      },
    };
  }

  // Builds hrLeave on the given env ({matchMedia, setTimeout, clearTimeout}); the browser uses the default env.
  function createLeave(env) {
    env = env || browserEnv();

    function reducedMotion() {
      var mq = env.matchMedia(REDUCED_QUERY);
      return !!(mq && mq.matches);
    }

    return function hrLeave(el, opts) {
      if (!el || el.hasAttribute("data-leaving")) return;

      var done =
        opts && typeof opts.done === "function"
          ? opts.done
          : function () {
              if (typeof el.remove === "function") el.remove();
            };
      var finished = false;
      var timer = null;
      // This call's own token. A caller that cancels an exit (clears data-leaving) and starts a new one replaces it; the
      // old exit's fallback and events then do nothing to the element, so they cannot clear the newer exit's state.
      var exit = {};
      el.__hrExit = exit;

      function superseded() {
        return el.__hrExit !== exit;
      }

      // Only this call's own timer and listeners; nothing on the element that another exit may own.
      function release() {
        if (timer !== null) env.clearTimeout(timer);
        timer = null;
        el.removeEventListener("animationend", onEvent);
        el.removeEventListener("transitionend", onEvent);
      }

      function finish() {
        if (finished) return;
        finished = true;
        release();
        if (superseded()) return;
        el.__hrExit = null;
        try {
          done();
        } finally {
          // Cleared even if done threw, so an element that is still in the page is not left inert.
          el.removeAttribute("data-leaving");
          el.inert = false;
        }
      }

      // Only the element's own events count: a child's animation bubbles up to el and must not end the exit.
      function onEvent(e) {
        if (e && e.target !== el) return;
        if (e && e.type === "transitionend" && EXIT_PROPERTIES[e.propertyName] !== true) return;
        finish();
      }

      el.setAttribute("data-leaving", "");
      el.inert = true;

      if (el.isConnected === false || reducedMotion()) {
        finish();
        return;
      }

      el.addEventListener("animationend", onEvent);
      el.addEventListener("transitionend", onEvent);
      timer = env.setTimeout(finish, FALLBACK_MS);
    };
  }

  // Builds hrCollapse on the given hrLeave: removes the element after its exit, once; a missing element is ignored.
  function createCollapse(hrLeave) {
    return function hrCollapse(el) {
      if (!el) return;
      hrLeave(el);
    };
  }

  // The row a successful inline-list delete removes, or null. The beforeSwap detail's elt is the SWAP TARGET (the list
  // block), not the element that issued the request: that is detail.requestConfig.elt (htmx 2.0.7 issueAjaxRequest), so
  // it is read first. A failed delete (not swapped, an error, or the row back open with its message) leaves the row alone.
  function deleteRow(detail) {
    var d = detail || {};
    var btn = (d.requestConfig && d.requestConfig.elt) || d.elt;
    if (!btn || !btn.hasAttribute || !btn.hasAttribute("data-inline-delete")) return null;
    if (!d.shouldSwap || d.isError) return null;
    if ((d.serverResponse || "").indexOf("data-inline-row") !== -1) return null;
    return btn.closest ? btn.closest("[data-inline-row]") || null : null;
  }

  var hrLeave = createLeave();
  var hrCollapse = createCollapse(hrLeave);

  if (typeof window !== "undefined") {
    window.hrLeave = hrLeave;
    window.hrCollapse = hrCollapse;
    window.hrDeleteRow = deleteRow;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      createLeave: createLeave,
      createCollapse: createCollapse,
      hrLeave: hrLeave,
      deleteRow: deleteRow,
    };
  }
})();
