// Pop-ups (docs/UI_RULES.md §6): every `.fixed.inset-0.z-50` shell that closes on an outside click also closes
// with Escape and a ✕ in its top-right corner. A pop-up with typed input asks before an outside click, Escape or ✕
// throws the input away; «Болих» stays a plain, silent cancel. Shells without the outside-click close (the one-time
// password) get none of this.
(function () {
  "use strict";

  var SHELL = ".fixed.inset-0.z-50";
  var ASK = "Оруулсан мэдээлэл хадгалагдахгүй. Хаах уу?";

  function closable(shell) {
    return (shell.getAttribute("onclick") || "").indexOf("remove()") >= 0;
  }

  // The Escape picker: the topmost closable shell that is not already leaving (a leaving shell is on its way out).
  function pickTopShell(shells, isClosable) {
    for (var i = shells.length - 1; i >= 0; i--) {
      if (shells[i].hasAttribute("data-leaving")) continue;
      if (isClosable(shells[i])) return shells[i];
    }
    return null;
  }

  // Whether remove() on el plays the pop-up exit first. Only a pop-up shell does; a shell already leaving, a no-anim
  // shell (rebuilt from an open pop-up) and a page without motion.js are removed at once.
  function shouldAnimateRemoval(el, canLeave) {
    if (!canLeave || !el || !el.matches || !el.matches(SHELL)) return false;
    // By design, a second remove() on a leaving shell removes it at once (the exit is cut short, nothing is removed twice).
    if (el.hasAttribute("data-leaving") || el.classList.contains("no-anim")) return false;
    return true;
  }

  // Closes a pop-up through the dirty check. confirmFn defaults to window.confirm (the browser path); tests pass their
  // own. A shell already leaving is not closed again (no second prompt, no second remove).
  function tryClose(shell, confirmFn) {
    if (shell.hasAttribute("data-leaving")) return;
    if (shell.dataset.dirty && !confirmFn && typeof window !== "undefined" && typeof window.hrConfirm === "function") {
      // the in-app dialog answers later: close then, if the user agrees
      window.hrConfirm(ASK, function () { if (!shell.hasAttribute("data-leaving")) shell.remove(); }, { ok: "Хаах" });
      return;
    }
    var ask = confirmFn || function (msg) { return window.confirm(msg); };
    if (shell.dataset.dirty && !ask(ASK)) return;
    shell.remove();  // the Element.prototype.remove override below plays the exit
  }

  // Pure helpers are exported for modal.test.mjs; the DOM part below needs a document.
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { pickTopShell: pickTopShell, shouldAnimateRemoval: shouldAnimateRemoval, tryClose: tryClose };
  }
  if (typeof document === "undefined") return;

  // The in-app confirm (UI_RULES §6): window.hrConfirm(message, onYes, {ok, cancel, danger}) shows a small dialog over
  // everything (z-[70], above the pop-ups) instead of the browser's own box. Escape or an outside click cancels;
  // focus starts on the cancel button so a stray Enter keeps the user's work. Never matches SHELL (no ✕, no dirty check).
  window.hrConfirm = function (message, onYes, opts) {
    opts = opts || {};
    var opener = document.activeElement;
    var shell = document.createElement("div");
    shell.className = "hr-confirm fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4";
    shell.setAttribute("role", "alertdialog");
    shell.setAttribute("aria-modal", "true");
    shell.setAttribute("aria-label", message);
    var panel = document.createElement("div");
    panel.className = "hr-confirm-panel";
    var text = document.createElement("p");
    text.className = "hr-confirm-text";
    text.textContent = message;
    var row = document.createElement("div");
    row.className = "hr-confirm-row";
    var no = document.createElement("button");
    no.type = "button";
    no.className = "hr-confirm-no";
    no.textContent = opts.cancel || "Болих";
    var yes = document.createElement("button");
    yes.type = "button";
    yes.className = "hr-confirm-yes";
    yes.textContent = opts.ok || "Тийм";
    row.appendChild(no);
    row.appendChild(yes);
    panel.appendChild(text);
    panel.appendChild(row);
    shell.appendChild(panel);
    function done(ok) {
      document.removeEventListener("keydown", onKey, true);
      nativeRemove.call(shell);
      if (opener && opener.focus && document.contains(opener)) opener.focus();
      if (ok && onYes) onYes();
      else if (!ok && opts.onNo) opts.onNo();
    }
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); done(false); }
      else if (e.key === "Tab") {  // keep focus between the two buttons
        e.preventDefault();
        (document.activeElement === no ? yes : no).focus();
      }
    }
    no.addEventListener("click", function () { done(false); });
    yes.addEventListener("click", function () { done(true); });
    shell.addEventListener("click", function (e) { if (e.target === shell) done(false); });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(shell);
    no.focus();
  };

  // <form data-confirm="Question?"> asks first, then submits (the in-app replacement for onsubmit="return confirm()").
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.getAttribute || !form.getAttribute("data-confirm") || form.dataset.confirmed) return;
    e.preventDefault();
    window.hrConfirm(form.getAttribute("data-confirm"), function () {
      form.dataset.confirmed = "1";
      if (form.requestSubmit) form.requestSubmit(e.submitter || undefined);
      else form.submit();
    }, { ok: form.getAttribute("data-confirm-ok") || "Тийм" });
  }, true);

  function topShell() {
    return pickTopShell(Array.prototype.slice.call(document.querySelectorAll(SHELL)), closable);
  }

  // Every pop-up shell closes through its exit: remove() on it (the inline onclick="...remove()" in the templates,
  // hx-on::after-request removals, tryClose) runs hrLeave first and removes the element when the exit ends. Anything
  // else, and a shell already leaving, is removed at once by the original method.
  var nativeRemove = Element.prototype.remove;
  Element.prototype.remove = function () {
    var el = this;
    if (!shouldAnimateRemoval(el, typeof window.hrLeave === "function")) return nativeRemove.call(el);
    window.hrLeave(el, { done: function () { nativeRemove.call(el); } });
  };

  function addCross(shell) {
    var panel = shell.firstElementChild;
    if (!panel || panel.querySelector("[data-modal-x]")) return;
    if (getComputedStyle(panel).position === "static") panel.classList.add("relative");
    var x = document.createElement("button");
    x.type = "button";
    x.setAttribute("data-modal-x", "");
    x.setAttribute("aria-label", "Хаах");
    x.title = "Хаах (Esc)";
    x.className = "absolute top-3 right-3 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700";
    x.innerHTML =
      '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
    x.addEventListener("click", function () { tryClose(shell); });
    panel.appendChild(x);
    // A server-side error shown in the pop-up means it was rebuilt with typed values. A hidden error slot (an empty
    // <p class="hidden text-red-600"> waiting for a message) is not an error.
    var shown = Array.prototype.some.call(shell.querySelectorAll(".text-red-600, .bg-red-50"), function (n) {
      return !n.hidden && !n.closest(".hidden, button, summary, a") && n.textContent.trim() !== "";  // a red «Устгах» button is not an error
    });
    if (shown) shell.dataset.dirty = "1";
  }

  function scan(root) {
    if (!root.querySelectorAll) return;
    if (root.matches && root.matches(SHELL) && closable(root)) addCross(root);
    root.querySelectorAll(SHELL).forEach(function (s) { if (closable(s)) addCross(s); });
  }

  // Typed input marks its pop-up; a pop-up rebuilt by the server after a failed save is a new element and starts
  // clean, but it still shows the typed values, so an error message in it counts as typed input too.
  function mark(e) {
    var shell = e.target.closest && e.target.closest(SHELL);
    if (shell && closable(shell)) shell.dataset.dirty = "1";
  }
  document.addEventListener("input", mark, true);
  document.addEventListener("change", mark, true);

  // Runs before the shell's own onclick (capture), so a dirty pop-up can refuse the outside click.
  document.addEventListener(
    "click",
    function (e) {
      var shell = e.target;
      if (!shell.matches || !shell.matches(SHELL) || !closable(shell) || !shell.dataset.dirty) return;
      if (shell.hasAttribute("data-leaving")) return;  // already closing: the click passes to the pop-up below
      e.stopPropagation();
      tryClose(shell);
    },
    true
  );

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape" || e.defaultPrevented) return;  // a dropdown or calendar handled it first
    if (document.querySelector(SHELL + "[data-leaving]")) return;  // an exit is under way: the next Escape waits for it
    var shell = topShell();
    if (!shell) return;
    e.preventDefault();
    tryClose(shell);
  });

  // One modal per trigger (UI_RULES §6): a pop-up opened from the body is tagged with its request path
  // (data-modal-src) once swapped in. A click for a path whose pop-up is already open, or whose request is still on
  // its way, sends nothing. Another path (a quick-add pop-up over another pop-up) is never blocked.
  var pending = {};

  function fromBody(evt) {
    return !!evt.detail && evt.detail.target === document.body && !!evt.detail.pathInfo;
  }

  function isOpen(path) {
    var all = document.querySelectorAll("div.fixed[data-modal-src]");
    for (var i = 0; i < all.length; i++) {
      if (all[i].hasAttribute("data-leaving")) continue;  // closing: a new open of the same path is allowed
      if (all[i].getAttribute("data-modal-src") === path) return true;
    }
    return false;
  }

  document.addEventListener("htmx:beforeRequest", function (evt) {
    if (evt.defaultPrevented || !fromBody(evt)) return;  // another listener already stopped it
    var path = evt.detail.pathInfo.requestPath;
    if (pending[path] || isOpen(path)) {
      evt.preventDefault();  // htmx does not send the request
      return;
    }
    pending[path] = true;
    // loadend fires on the request itself, so the mark goes even if the trigger was removed mid-flight
    // (htmx's own afterRequest then reaches no listener on the document).
    var xhr = evt.detail.xhr;
    if (xhr && xhr.addEventListener) xhr.addEventListener("loadend", function () { delete pending[path]; });
  });

  // htmx runs beforeSwap and afterSwap back to back for one swap, so the body children seen just before the swap are
  // enough to find the overlay that this swap added (not one another script appended while the request was out).
  var beforeSwapKids = null;
  document.addEventListener("htmx:beforeSwap", function (evt) {
    beforeSwapKids = fromBody(evt) ? Array.prototype.slice.call(document.body.children) : null;
  });

  document.addEventListener("htmx:afterSwap", function (evt) {
    var before = beforeSwapKids;
    beforeSwapKids = null;
    if (!before || !fromBody(evt)) return;
    var kids = document.body.children;
    for (var i = kids.length - 1; i >= 0; i--) {
      if (before.indexOf(kids[i]) >= 0) continue;  // already there before this swap
      if (kids[i].matches("div.fixed") && !kids[i].hasAttribute("data-modal-src")) {
        kids[i].setAttribute("data-modal-src", evt.detail.pathInfo.requestPath);
        break;
      }
    }
  });

  function start() {
    scan(document.body);
    new MutationObserver(function (records) {
      records.forEach(function (r) { r.addedNodes.forEach(scan); });
    }).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
