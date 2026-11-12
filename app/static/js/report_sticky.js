/* Report page: sticky tool strip and sticky table header (docs/UI_RULES.md §4b).
   1. Once the filter bar has scrolled under the top bar, a thin strip appears under it: the applied filters as chips plus
      the «Багана», «Шүүлтүүр», «Хэлбэр» buttons (they click the real tool buttons, data-tool) and «↑ Дээш».
   2. The table header row stays under the top bar (and the strip). `.ptable` scrolls sideways (overflow-x), which makes
      CSS `position: sticky; top` useless, and moving the cells from a scroll handler visibly lags behind the page. So a
      fixed copy of the header is shown while the real header is out of view, and only appears/disappears (never moves
      while scrolling); it follows the table's sideways scroll and its select-all box drives the real one.
   Pure display: no value is changed. Re-run on scroll, resize and after every htmx swap of #report-page. */
(function () {
  "use strict";

  var TOPBAR = 56;  // the top bar is h-14
  var ticking = false;

  function chipText(holder) {
    var ctl = holder.matches("select, input") ? holder : holder.querySelector("select, input");
    if (!ctl) return "";
    if (ctl.tagName === "SELECT") return ctl.options[ctl.selectedIndex] ? ctl.options[ctl.selectedIndex].text.trim() : "";
    var vals = Array.prototype.map.call(holder.querySelectorAll("input"), function (i) { return i.value; }).filter(Boolean);
    return vals.join(" – ");
  }

  function renderChips(strip) {
    var box = strip.querySelector("[data-sticky-strip-chips]");
    var form = document.getElementById("report-filters");
    box.textContent = "";
    var texts = [];
    if (form) form.querySelectorAll("[data-applied]").forEach(function (h) { var t = chipText(h); if (t) texts.push(t); });
    var rules = document.querySelector("[data-rules-text]");
    if (rules) texts.push(rules.textContent.trim());
    texts.forEach(function (t) {
      var chip = document.createElement("span");
      chip.className = "shrink-0 rounded-full bg-violet-50 px-2.5 py-1 text-xs text-violet-700";
      chip.textContent = t;
      box.appendChild(chip);
    });
  }

  var clone = null;  // the fixed copy of the table header, while it is shown

  function dropClone() {
    if (clone) { clone.remove(); clone = null; }
  }

  function buildClone(box, table, top) {
    var real = table.tHead;
    var wrap = document.createElement("div");
    wrap.setAttribute("data-sticky-head", "");
    wrap.className = "ptable";  // the same th look as the real header
    wrap.style.cssText = "position:fixed;margin:0;overflow:hidden;z-index:25;border-radius:0;border-top:0;" +
      "box-shadow:0 4px 6px -2px rgba(15,23,42,.18)";
    var copy = document.createElement("table");
    copy.style.cssText = "table-layout:fixed;border-collapse:collapse;width:" + table.offsetWidth + "px";
    var thead = real.cloneNode(true);
    var srcTh = real.querySelectorAll("th");
    thead.querySelectorAll("th").forEach(function (th, i) {
      th.style.width = th.style.minWidth = th.style.maxWidth = srcTh[i].getBoundingClientRect().width + "px";
      th.style.background = "var(--color-slate-100)";
      th.style.borderBottom = "1px solid var(--color-slate-300)";
      var cb = th.querySelector("[data-select-all]");
      if (cb) {  // the copy's box drives the real one, so the selection script stays the only owner of the state
        var mirror = document.createElement("input");
        mirror.type = "checkbox";
        mirror.setAttribute("aria-label", cb.getAttribute("aria-label") || "");
        mirror.checked = srcTh[i].querySelector("[data-select-all]").checked;
        mirror.addEventListener("click", function () { srcTh[i].querySelector("[data-select-all]").click(); });
        cb.replaceWith(mirror);
      }
    });
    copy.appendChild(thead);
    wrap.appendChild(copy);
    document.body.appendChild(wrap);
    wrap.style.top = top + "px";
    wrap.style.left = box.left + "px";
    wrap.style.width = box.width + "px";
    wrap.scrollLeft = table.parentElement.scrollLeft;
    return wrap;
  }

  function update() {
    ticking = false;
    var page = document.getElementById("report-page");
    if (!page) { dropClone(); return; }
    var wrap = page.querySelector("[data-sticky-strip]");
    var bar = page.querySelector("[data-sticky-strip-bar]");
    var form = document.getElementById("report-filters");
    var panel = form && form.parentElement;
    var show = !!(wrap && bar && panel) && panel.getBoundingClientRect().bottom < TOPBAR;
    if (bar) {
      if (show && bar.hidden) renderChips(wrap);
      bar.hidden = !show;
    }
    var top = TOPBAR + (show && bar ? bar.offsetHeight : 0);
    var table = page.querySelector(".ptable > table");
    if (!table || !table.tHead) { dropClone(); return; }
    var box = table.parentElement.getBoundingClientRect();
    var headH = table.tHead.getBoundingClientRect().height;
    var footH = table.tFoot ? table.tFoot.getBoundingClientRect().height : 0;
    // shown while the real header is above the line and the table still has body rows under it
    var want = box.top < top && box.bottom - footH - headH > top;
    if (!want) { dropClone(); return; }
    if (!clone) clone = buildClone(box, table, top);
    else {
      clone.style.top = top + "px";
      clone.style.left = box.left + "px";
      clone.style.width = box.width + "px";
    }
  }

  function schedule() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(update);
  }

  function rebuild() { dropClone(); schedule(); }  // widths, sort or rows may have changed

  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("[data-strip-tool]");
    if (t) {
      var real = document.querySelector('[data-tool="' + t.getAttribute("data-strip-tool") + '"]');
      if (real) real.click();
      return;
    }
    if (e.target.closest && e.target.closest("[data-strip-top]")) {
      var form = document.getElementById("report-filters");
      var panel = form && form.parentElement;
      if (panel) panel.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  });
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", rebuild);
  document.addEventListener("scroll", function (e) {  // the table scrolls sideways: the copy follows (scroll does not bubble)
    if (clone && e.target.classList && e.target.classList.contains("ptable")) clone.scrollLeft = e.target.scrollLeft;
  }, true);
  document.addEventListener("change", function (e) {  // keep the copy's select-all box in step with the real one
    if (clone && e.target.matches && e.target.matches("[data-select-all]")) rebuild();
  });
  document.addEventListener("htmx:afterSettle", rebuild);
  document.addEventListener("htmx:historyRestore", schedule);
  window.addEventListener("pageshow", schedule);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", schedule);
  else schedule();
})();
