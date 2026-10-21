// Money boxes (<input data-money>, see employees/money.py): digits are grouped by commas as the user types
// (2500000 -> 2,500,000). Only the display changes; the server ignores the commas. The caret stays after the
// same digit it was after, so typing or deleting in the middle works.
(function () {
  "use strict";

  function format(raw) {
    var clean = raw.replace(/[^\d.]/g, "");
    var dot = clean.indexOf(".");
    var whole = dot < 0 ? clean : clean.slice(0, dot);
    var frac = dot < 0 ? null : clean.slice(dot + 1).replace(/\./g, "").slice(0, 2);
    whole = whole.replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return frac === null ? whole : (whole || "0") + "." + frac;
  }

  function reformat(input) {
    var value = input.value, caret = input.selectionStart;
    var digitsBefore = caret == null ? null : value.slice(0, caret).replace(/[^\d.]/g, "").length;
    var next = format(value);
    if (next === value) return;
    input.value = next;
    if (digitsBefore == null || document.activeElement !== input) return;
    var pos = 0, seen = 0;
    while (pos < next.length && seen < digitsBefore) {
      if (/[\d.]/.test(next.charAt(pos))) seen++;
      pos++;
    }
    input.setSelectionRange(pos, pos);
  }

  // Backspace just after a comma (or Delete just before one) removes the digit beyond it, not only the comma.
  document.addEventListener("keydown", function (e) {
    var input = e.target;
    if (!input || !input.matches || !input.matches("input[data-money]")) return;
    var at = input.selectionStart;
    if (at == null || at !== input.selectionEnd) return;
    if (e.key === "Backspace" && input.value.charAt(at - 1) === ",") input.setSelectionRange(at - 1, at - 1);
    if (e.key === "Delete" && input.value.charAt(at) === ",") input.setSelectionRange(at + 1, at + 1);
  });

  document.addEventListener("input", function (e) {
    if (e.target && e.target.matches && e.target.matches("input[data-money]")) reformat(e.target);
  });
  function init(root) {
    if (!root || !root.querySelectorAll) return;
    Array.prototype.forEach.call(root.querySelectorAll("input[data-money]"), reformat);
  }
  document.addEventListener("DOMContentLoaded", function () { init(document); });
  document.addEventListener("htmx:load", function (e) { init(e.detail.elt); });
})();
