/* Report filter bar (docs/UI_RULES.md §4b).
   1. A control that holds a value other than its default is painted violet (data-applied), so the applied filters can
      be told at a glance. Default = the first option of a select, an empty box, or this year's span for «from»/«to».
   2. «Цэвэрлэх» is shown only while something is applied.
   Pure marking: it never changes a value. Re-read on every change and after every htmx swap.
   (The folding of a long bar is done by the server: views._secondary_filters and the «Шүүлтүүр нэмэх» menu.) */
(function () {
  "use strict";

  var PLAIN = { quarter: 1, attribute: 1, year: 1, cols: 1, sort: 1, rules: 1 };

  function applied(ctl) {
    if (ctl.disabled || ctl.type === "hidden" || PLAIN[ctl.name]) return false;
    if (ctl.tagName === "SELECT") return ctl.options.length > 0 && ctl.selectedIndex > 0 && ctl.value !== ctl.options[0].value;
    var year = new Date().getFullYear();
    if (ctl.name === "from") return ctl.value !== "" && ctl.value !== year + "-01-01";  // the period's default span
    if (ctl.name === "to") return ctl.value !== "" && ctl.value !== year + "-12-31";
    return ctl.value.trim() !== "";
  }

  function holder(ctl) {
    if (ctl.name === "q") return ctl;  // the search box sits in a wrapper for its icon; the box itself is lit
    var p = ctl.parentElement;
    return p && p.tagName !== "FORM" && p.closest("#report-filters") !== p && !p.hasAttribute("data-filter-wrap") ? p : ctl;
  }

  function sync() {
    var form = document.getElementById("report-filters");
    if (!form) return;
    form.querySelectorAll("[data-applied]").forEach(function (n) { n.removeAttribute("data-applied"); });
    // A holder (the date label, the age pair) is lit when any control in it is applied.
    form.querySelectorAll("select[name], input[name]").forEach(function (ctl) {
      if (applied(ctl)) holder(ctl).setAttribute("data-applied", "");
    });
    var clear = document.querySelector("[data-filters-clear]");
    if (clear) clear.hidden = !form.querySelector("[data-applied], [data-column-chip]");
  }

  // The search box (name q) is replaced when the page swaps. If it had the focus, the swap gives the focus back, with
  // the caret at the end and any text typed while the request ran (UI_RULES §4b «Pop-up scripts»). Only a swap of
  // #report-page is watched, so another pop-up's swap never moves the focus.
  var searchTyped = null;  // the live text of the search box when the page swap began, or null
  document.addEventListener("htmx:beforeSwap", function (e) {
    var a = document.activeElement;
    var target = e.detail && e.detail.target;
    searchTyped = null;
    if (a && a.name === "q" && a.form && a.form.id === "report-filters" && target && target.id === "report-page") {
      searchTyped = a.value;
    }
  });
  document.addEventListener("htmx:afterSettle", function () {
    if (searchTyped === null) return;
    var typed = searchTyped;
    searchTyped = null;
    var box = document.querySelector('#report-filters input[name="q"]');
    if (!box || (document.activeElement && document.activeElement !== document.body)) return;  // the user moved on
    box.focus();
    if (box.value !== typed) {
      box.value = typed;
      box.dispatchEvent(new Event("input", { bubbles: true }));  // asks for the page with the text typed meanwhile
    }
    box.setSelectionRange(box.value.length, box.value.length);
  });

  document.addEventListener("change", sync);
  document.addEventListener("input", sync);
  document.addEventListener("htmx:afterSettle", sync);
  document.addEventListener("htmx:historyRestore", sync);
  window.addEventListener("pageshow", sync);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", sync);
  else sync();
})();
