// A report remembers how the user left it (filters, sort, columns, layout): opening it again by its plain address
// (the top bar, a link) returns to that state. Back/forward and reload already keep their own address. Per browser,
// per report, in localStorage; «Цэвэрлэх» (an htmx swap to the plain address) forgets it.
(function () {
  var m = /^\/reports\/([^/]+)\/$/.exec(location.pathname);
  var PREFIX = "hr.reportQuery.";
  function key(path) { var k = /^\/reports\/([^/]+)\/$/.exec(path); return k ? PREFIX + k[1] : null; }
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, search) {
    try { if (search) { localStorage.setItem(k, search); } else { localStorage.removeItem(k); } } catch (e) { /* blocked */ }
  }
  var k = m && key(location.pathname);
  if (k && !window.__hrReportMemory) {
    var nav = performance.getEntriesByType("navigation")[0];
    var type = nav && nav.type;
    if (type === "navigate" && !location.search) {
      var saved = load(k);
      if (saved && saved.charAt(0) === "?") { location.replace(location.pathname + saved); return; }
    }
    if (location.search) { save(k, location.search); }
  }
  if (window.__hrReportMemory) { return; }
  window.__hrReportMemory = true;
  function remember() { var key2 = key(location.pathname); if (key2) { save(key2, location.search); } }
  document.addEventListener("htmx:pushedIntoHistory", remember);
  document.addEventListener("htmx:historyRestore", remember);
})();
