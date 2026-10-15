/* Admin change lists: clicking anywhere on a row opens that record (docs/UI_RULES.md §4).
   Django links only the first column; controls in the row (checkbox, links, inputs) keep their own action.
   Ctrl/Cmd or middle click opens the record in a new tab, like a normal link. */
(function () {
  "use strict";

  var CONTROLS = "a, button, input, select, textarea, label";

  function rowLink(row) {
    return row.querySelector("th a[href], td a[href]");
  }

  function mark(root) {
    root.querySelectorAll("#result_list tbody tr").forEach(function (row) {
      if (rowLink(row)) row.style.cursor = "pointer";
    });
  }

  function open(event) {
    var row = event.target.closest && event.target.closest("#result_list tbody tr");
    if (!row || event.target.closest(CONTROLS)) return;
    if (window.getSelection && String(window.getSelection())) return;  // selecting text is not a click
    var link = rowLink(row);
    if (!link) return;
    if (event.button === 1 || event.ctrlKey || event.metaKey) window.open(link.href, "_blank");
    else if (event.button === 0) location.href = link.href;
  }

  document.addEventListener("click", open);
  document.addEventListener("auxclick", open);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { mark(document); });
  else mark(document);
})();
