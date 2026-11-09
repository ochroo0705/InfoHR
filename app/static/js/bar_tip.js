/* A quick tooltip for timeline bars (reports): the name and the exact dates under the pointer, with no wait like the
   browser's own title text. One floating box, kept inside the window; keyboard focus shows it too. */
(function () {
  "use strict";

  var tip = null;

  function box() {
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "bar-tip";
      tip.setAttribute("role", "tooltip");
      tip.hidden = true;
      document.body.appendChild(tip);
    }
    return tip;
  }

  function show(bar) {
    var t = box();
    t.textContent = "";
    var head = document.createElement("strong");
    head.textContent = bar.getAttribute("data-tip-title") || "";
    var line = document.createElement("span");
    line.textContent = bar.getAttribute("data-tip") || "";
    t.appendChild(head);
    t.appendChild(line);
    t.hidden = false;
    var r = bar.getBoundingClientRect();
    var w = t.offsetWidth, h = t.offsetHeight;
    var left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
    var top = r.top - h - 8;
    if (top < 8) top = r.bottom + 8;  // no room above: below the bar
    t.style.left = left + "px";
    t.style.top = top + "px";
  }

  function hide() { if (tip) tip.hidden = true; }

  function bar(e) { return e.target.closest ? e.target.closest("[data-bar][data-tip]") : null; }

  document.addEventListener("mouseover", function (e) { var b = bar(e); if (b) show(b); });
  document.addEventListener("mouseout", function (e) { if (bar(e)) hide(); });
  document.addEventListener("focusin", function (e) { var b = bar(e); if (b) show(b); });
  document.addEventListener("focusout", hide);
  window.addEventListener("scroll", hide, true);
  document.addEventListener("htmx:beforeSwap", hide);
})();
