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

  document.addEventListener("change", sync);
  document.addEventListener("input", sync);
  document.addEventListener("htmx:afterSettle", sync);
  document.addEventListener("htmx:historyRestore", sync);
  window.addEventListener("pageshow", sync);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", sync);
  else sync();
})();
