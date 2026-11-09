// A report's column sort swaps the rows, and the browser sizes the columns from the rows it got, so the headings
// jump left and right. Keep every column at least as wide as it was just before the sort.
(function () {
  var widths = null;
  document.addEventListener("htmx:beforeRequest", function (e) {
    var a = e.detail && e.detail.elt;
    var th = a && a.closest && a.closest("#report-page thead th");
    widths = th ? Array.prototype.map.call(th.parentNode.children, function (c) { return c.getBoundingClientRect().width; }) : null;
  });
  document.addEventListener("htmx:afterSwap", function () {
    var saved = widths;
    widths = null;
    if (!saved) { return; }
    var cells = document.querySelectorAll("#report-page thead th");
    if (cells.length !== saved.length) { return; }
    cells.forEach(function (c, i) { c.style.minWidth = Math.ceil(saved[i]) + "px"; });
  });
})();
