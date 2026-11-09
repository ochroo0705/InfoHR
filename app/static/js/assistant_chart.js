// The chart pane of an assistant table answer (assistant/_chart_modal.html, docs/UI_RULES.md §6c). The pop-up carries
// its numbers twice: as JSON (#assistant-chart-data) for the chart, and as a plain text list that is always there. The
// chart library (Plotly, our own file under static/vendor/plotly) is loaded the first time a chart is drawn, never from a
// CDN. Colours are read from the page's CSS variables, so the dark theme works; a theme change redraws the charts.
(function () {
  "use strict";

  var DATA_ID = "assistant-chart-data";
  var CONFIG = { displaylogo: false, displayModeBar: false, responsive: true };
  var PIE_COLORS = ["--color-violet-600", "--color-violet-300", "--color-amber-500", "--color-violet-800",
    "--color-slate-500", "--color-amber-300", "--color-violet-400", "--color-slate-400"];
  var waiting = [];  // callbacks that wait for the library
  var loading = false;
  var drawn = [];  // charts on screen: each one's resize listener is released when its pop-up is gone

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  var pane = document.querySelector("[data-chart-pane]");  // the docked chart pane (base.html)
  var panel = document.querySelector("[data-assistant-panel]");

  function popupOf(el) {
    return el.closest("[data-chart-pane]") || document;
  }

  // Opens the pane at once (so the chart is measured at its real size), then loads the chart fragment into it.
  function openPane(href) {
    if (!pane) return false;
    // A pane that is sliding out is taken back: its pending done() does nothing (the token is cleared).
    pane.__closing = null;
    pane.removeAttribute("data-leaving");
    pane.inert = false;
    pane.hidden = false;
    pane.innerHTML = '<p role="status" class="p-4 text-sm text-slate-500">График ачаалж байна…</p>';
    if (window.htmx) window.htmx.ajax("GET", href, { target: "#" + pane.id, swap: "innerHTML" });
    else window.location.assign(href);
    return true;
  }

  // The pane slides out through window.hrLeave (plan 2026-11-08-selection-motion, task 9); it is hidden and emptied when the
  // exit ends. Its token (pane.__closing) lets openPane take it back in the meantime.
  function closePane() {
    if (!pane || pane.hidden || pane.hasAttribute("data-leaving")) return;
    var token = pane.__closing = {};
    function done() {
      if (pane.__closing !== token) return;  // reopened by openPane while sliding out
      pane.__closing = null;
      pane.removeAttribute("data-leaving");
      pane.inert = false;
      pane.hidden = true;
      pane.textContent = "";  // the observer below purges the chart that was in it
    }
    if (window.hrLeave) window.hrLeave(pane, { done: done });
    else done();
  }

  // The open chart's state (filters, kind, grouping), read from the marker in the pane; null when no chart is open.
  // palette.js sends it with a typed question, so a question can change the chart that is on screen. A pane that is
  // sliding out is not open.
  window.openChartState = function () {
    var mark = pane && !pane.hidden && !pane.hasAttribute("data-leaving") && pane.querySelector("[data-chart-state]");
    if (!mark) return null;
    return { query: mark.getAttribute("data-query") || "", kind: mark.getAttribute("data-kind") || "", by: mark.getAttribute("data-by") || "" };
  };
  // Opens or replaces the chart in the pane (palette.js calls it for a live answer that carries data-chart-auto).
  window.openAssistantChart = openPane;

  if (pane) {
    document.addEventListener("click", function (e) {
      var t = e.target;
      if (!t || !t.closest) return;
      // Also the old pop-up link (data-palette-modal) of a thread kept in sessionStorage before the pane existed.
      var open = t.closest('a[data-chart-open], a[data-palette-modal][href*="/assistant/chart/"]');
      if (open) {
        if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;  // a new tab keeps the pop-up address working
        e.preventDefault();
        e.stopPropagation();  // the thread's own pop-up handler must not also load the fragment into the page
        openPane(open.getAttribute("href"));
        return;
      }
      if (t.closest("[data-chart-close]")) {
        e.preventDefault();
        closePane();
      }
    }, true);  // capture phase: runs before the thread's click handler
    // Esc closes the pane only while focus is inside it (the panel's own Esc rule is the same).
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !pane.hidden && pane.contains(document.activeElement)) {
        e.preventDefault();
        closePane();
      }
    });
    // The pane belongs to the panel: it goes when the panel closes. It starts its own exit as soon as the panel starts
    // sliding out (data-leaving), so both leave together; a panel that is reopened in time brings nothing back here.
    if (panel) {
      new MutationObserver(function () { if (panel.hidden || panel.hasAttribute("data-leaving")) closePane(); })
        .observe(panel, { attributes: true, attributeFilter: ["hidden", "data-leaving"] });
    }
  }

  // Loads the library once. Every caller gets the answer: true when window.Plotly is there, false when the file failed.
  function loadLibrary(src, done) {
    if (window.Plotly) {
      done(true);
      return;
    }
    waiting.push(done);
    if (loading) return;
    loading = true;
    var script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = function () { finish(!!window.Plotly); };
    script.onerror = function () {
      script.remove();  // a later pop-up may try again
      finish(false);
    };
    document.head.appendChild(script);
  }

  function finish(ok) {
    loading = false;
    var queue = waiting;
    waiting = [];
    queue.forEach(function (cb) { cb(ok); });
  }

  function readData(el) {
    var script = popupOf(el).querySelector("#" + DATA_ID);
    try {
      return script ? JSON.parse(script.textContent) : null;
    } catch (err) {
      return null;
    }
  }

  function percent(count, total) {
    return total ? Math.round((count * 100) / total) : 0;
  }

  function hoverTexts(data) {
    return data.labels.map(function (label, i) {
      return "«" + label + "»: " + data.counts[i] + " (" + percent(data.counts[i], data.total) + "%)";
    });
  }

  // Bars lie flat (longest on top) when there are many groups or long names: rotated labels were unreadable.
  function isHorizontal(data) {
    var longest = data.labels.reduce(function (m, l) { return Math.max(m, l.length); }, 0);
    return data.kind !== "pie" && (data.labels.length > 6 || longest > 14);
  }

  // The chart's height follows the number of bars when they lie flat (the pane's body scrolls).
  function sizeFor(el, data) {
    if (data.kind === "pie") el.style.height = "380px";
    else el.style.height = isHorizontal(data) ? Math.max(320, data.labels.length * 32 + 60) + "px" : "";
  }

  function layout(data, maxCount) {
    var text = cssVar("--color-slate-700");
    var base = {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: text, size: 13 },
      autosize: true,
    };
    if (data.kind === "pie") {
      return Object.assign(base, {
        showlegend: true,
        legend: { font: { color: text }, orientation: "h", y: -0.05 },
        margin: { l: 8, r: 8, t: 8, b: 8 },
        // The total sits in the hole of the ring.
        annotations: [{
          text: "<b>" + data.total + "</b><br>хүн", showarrow: false, x: 0.5, y: 0.5,
          font: { size: 22, color: text },
        }],
      });
    }
    var grid = cssVar("--color-slate-200");
    var count = { color: text, gridcolor: grid, rangemode: "tozero", tickformat: "d", zeroline: false,
      range: [0, maxCount * 1.18] };  // room above the longest bar for its number
    if (maxCount <= 10) count.dtick = 1;  // whole people on the axis, never 0.5 steps
    if (isHorizontal(data)) {
      return Object.assign(base, {
        showlegend: false,
        bargap: 0.35,
        margin: { l: 8, r: 24, t: 8, b: 32 },
        xaxis: count,
        yaxis: { color: text, automargin: true, autorange: "reversed", showgrid: false, ticklen: 0 },
      });
    }
    return Object.assign(base, {
      showlegend: false,
      bargap: 0.35,
      margin: { l: 40, r: 16, t: 16, b: 64 },
      xaxis: { color: text, tickangle: -30, automargin: true },
      yaxis: count,
    });
  }

  function traces(data) {
    var texts = hoverTexts(data);
    if (data.kind === "pie") {
      return [{
        type: "pie",
        labels: data.labels,
        values: data.counts,
        sort: false,
        hole: 0.55,
        hovertext: texts,
        hoverinfo: "text",
        // Whole percent inside the slice, and nothing on a slice under 5% (the numbers would overlap).
        text: data.counts.map(function (c) { var p = percent(c, data.total); return p >= 5 ? p + "%" : ""; }),
        textinfo: "text",
        textposition: "inside",
        textfont: { color: "#fff" },
        marker: {
          colors: PIE_COLORS.map(cssVar),
          line: { color: cssVar("--color-surface"), width: 2 },
        },
      }];
    }
    // The biggest group is the strong colour, the rest are lighter, so the eye lands on the leader.
    var strong = cssVar("--color-violet-600");
    var soft = cssVar("--color-violet-400");
    var colors = data.counts.map(function (_, i) { return i === 0 ? strong : soft; });
    var horizontal = isHorizontal(data);
    return [{
      type: "bar",
      orientation: horizontal ? "h" : "v",
      x: horizontal ? data.counts : data.labels,
      y: horizontal ? data.labels : data.counts,
      text: data.counts.map(String),
      textposition: "outside",
      cliponaxis: false,
      textfont: { color: cssVar("--color-slate-700") },
      hovertext: texts,
      hoverinfo: "text",
      marker: { color: colors },
    }];
  }

  function showFailed(el) {
    el.hidden = true;
    var note = popupOf(el).querySelector("[data-chart-failed]");
    if (note) note.hidden = false;
  }

  function draw(el) {
    el.setAttribute("data-drawn", "1");
    var data = readData(el);
    if (!data || !data.total || !Array.isArray(data.labels)) return;
    loadLibrary(el.getAttribute("data-plotly-src") || "", function (ok) {
      if (!ok) {
        showFailed(el);
        return;
      }
      var maxCount = Math.max.apply(null, data.counts.concat([0]));
      try {
        sizeFor(el, data);
        window.Plotly.newPlot(el, traces(data), layout(data, maxCount), CONFIG);
        if (drawn.indexOf(el) < 0) drawn.push(el);
      } catch (err) {
        showFailed(el);
      }
    });
  }

  // Draws every chart in the page that is not drawn yet (a pop-up was just swapped in).
  function drawAll(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll("[data-assistant-chart]"), function (el) {
      if (!el.hasAttribute("data-drawn")) draw(el);
    });
  }

  document.addEventListener("htmx:afterSettle", function () { drawAll(document); });

  // A chart that leaves the page (the pane emptied or refilled) stays in Plotly's registry: purge it.
  function purgeGone() {
    drawn = drawn.filter(function (el) {
      if (el.isConnected) return true;
      try { window.Plotly.purge(el); } catch (err) { /* already gone */ }
      return false;
    });
  }
  new MutationObserver(purgeGone).observe(document.body, { childList: true });
  if (pane) new MutationObserver(purgeGone).observe(pane, { childList: true });

  // The pop-up is fetched by htmx, which shows nothing for an error answer: a stale link (another login, a changed
  // right) must not look like a dead button.
  document.addEventListener("htmx:responseError", function (e) {
    var url = (e.detail && e.detail.xhr && e.detail.xhr.responseURL) || "";
    if (url.indexOf("/assistant/chart/") < 0) return;
    closePane();
    var note = document.createElement("div");
    note.setAttribute("role", "alert");
    note.className = "fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-slate-800 px-4 py-2 text-sm text-white shadow-lg";
    note.textContent = "График нээж чадсангүй. Хуудсыг шинэчлээд дахин оролдоно уу.";
    document.body.appendChild(note);
    setTimeout(function () { note.remove(); }, 6000);
  });
  drawAll(document);

  // The PNG of the chart in this pop-up, from the chart library's own download.
  document.addEventListener("click", function (e) {
    var btn = e.target && e.target.closest ? e.target.closest("[data-chart-png]") : null;
    if (!btn) return;
    e.preventDefault();
    var el = popupOf(btn).querySelector("[data-assistant-chart]");
    if (!el || !window.Plotly || !el.data) return;
    window.Plotly.downloadImage(el, { format: "png", filename: "assistant-chart" }).catch(function () {});
  });

  // A theme change (data-theme on <html>) redraws the drawn charts with the new colours.
  new MutationObserver(function () {
    Array.prototype.forEach.call(document.querySelectorAll("[data-assistant-chart][data-drawn]"), draw);
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
})();
