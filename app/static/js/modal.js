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

  function topShell() {
    var all = document.querySelectorAll(SHELL);
    for (var i = all.length - 1; i >= 0; i--) if (closable(all[i])) return all[i];
    return null;
  }

  function tryClose(shell) {
    if (shell.dataset.dirty && !window.confirm(ASK)) return;
    shell.remove();
  }

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
    if (shell.querySelector(".text-red-600, .bg-red-50")) shell.dataset.dirty = "1";
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
      e.stopPropagation();
      tryClose(shell);
    },
    true
  );

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape" || e.defaultPrevented) return;  // a dropdown or calendar handled it first
    var shell = topShell();
    if (!shell) return;
    e.preventDefault();
    tryClose(shell);
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
