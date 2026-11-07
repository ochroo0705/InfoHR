// The chart layout of a report (reports/templates/reports/layouts/chart.html, docs/UI_RULES.md §4b). The numbers are in
// #report-chart-data (JSON); the element [data-report-chart] is drawn with Plotly basic. The library is our own file
// (data-plotly-src), loaded the first time a chart is drawn, never from a CDN. Plotly cannot read the page's oklch()
// colours, so the colours are hex constants, one set for the light theme and one for the dark theme (data-theme on
// <html>, set by base.html). A theme change redraws the charts. Category text is escaped before Plotly sees it, because
// Plotly renders a small HTML subset in labels and hover text.
(function () {
  "use strict";

  var DATA_ID = "report-chart-data";
  var CONFIG = { displaylogo: false, displayModeBar: false, responsive: true };
  var THEMES = {
    light: {
      accent: "#c0392b", text: "#34495e", grid: "#d5dcdf", surface: "#ffffff",
      series: ["#dc2626", "#f59e0b", "#16a34a", "#3b82f6", "#5f6b6d", "#bdc6c8", "#8a9598"],
    },
    dark: {
      accent: "#d9574a", text: "#d5dcdf", grid: "#2f4357", surface: "#1e2b38",
      series: ["#ef4444", "#fbbf24", "#22c55e", "#60a5fa", "#95a5a6", "#3b5167", "#6c7e8c"],
    },
  };

  var waiting = [];  // callbacks waiting for the library
  var loading = false;
  var drawn = [];  // charts on the page that Plotly has drawn

  function theme() {
    return THEMES[document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light"];
  }

  // Plotly reads &, < and > in labels as markup (its HTML subset): escape them so a category name is only text.
  function escapeText(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function readData() {
    var script = document.getElementById(DATA_ID);
    try {
      return script ? JSON.parse(script.textContent) : null;
    } catch (err) {
      return null;
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
      script.remove();  // a later page may try again
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

  // Long category names or many categories lie the bars flat: rotated labels were unreadable.
  function isHorizontal(data) {
    var longest = data.labels.reduce(function (m, l) { return Math.max(m, String(l).length); }, 0);
    return data.kind === "bar" && (data.labels.length > 6 || longest > 14);
  }

  function traces(data, t) {
    var labels = data.labels.map(escapeText);
    var fmt = data.money ? "%{y:,.0f}₮" : "%{y:,}";
    if (data.kind === "donut") {
      return [{
        type: "pie",
        labels: labels,
        values: data.values,
        sort: false,
        hole: 0.55,
        textinfo: "percent",
        textfont: { color: "#ffffff" },
        hovertemplate: "%{label}: " + (data.money ? "%{value:,.0f}₮" : "%{value:,}") + " (%{percent})<extra></extra>",
        marker: { colors: t.series, line: { color: t.surface, width: 2 } },
      }];
    }
    if (data.kind === "line") {
      return [{
        type: "scatter",
        mode: "lines+markers",
        x: labels,
        y: data.values,
        line: { color: t.accent, width: 2 },
        marker: { color: t.accent, size: 8 },
        hovertemplate: "%{x}: " + fmt + "<extra></extra>",
      }];
    }
    var horizontal = isHorizontal(data);
    return [{
      type: "bar",
      orientation: horizontal ? "h" : "v",
      x: horizontal ? data.values : labels,
      y: horizontal ? labels : data.values,
      marker: { color: t.accent },
      textposition: "outside",
      cliponaxis: false,
      hovertemplate: (horizontal ? "%{y}: %{x:,}" : "%{x}: " + fmt) + "<extra></extra>",
    }];
  }

  function layout(data, t) {
    var base = {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: t.text, size: 13 },
      autosize: true,
    };
    if (data.kind === "donut") {
      return Object.assign(base, {
        showlegend: true,
        legend: { font: { color: t.text }, orientation: "h", y: -0.05 },
        margin: { l: 8, r: 8, t: 8, b: 8 },
      });
    }
    var axis = { color: t.text, gridcolor: t.grid, zeroline: false, rangemode: "tozero",
      tickformat: data.money ? ",.0f" : "d" };
    if (data.kind === "line") {
      return Object.assign(base, {
        showlegend: false,
        margin: { l: 48, r: 16, t: 16, b: 64 },
        xaxis: { color: t.text, tickangle: -30, automargin: true },
        yaxis: axis,
      });
    }
    if (isHorizontal(data)) {
      return Object.assign(base, {
        showlegend: false,
        bargap: 0.35,
        margin: { l: 8, r: 40, t: 8, b: 40 },
        xaxis: axis,
        yaxis: { color: t.text, automargin: true, autorange: "reversed", showgrid: false, ticklen: 0 },
      });
    }
    return Object.assign(base, {
      showlegend: false,
      bargap: 0.35,
      margin: { l: 48, r: 16, t: 16, b: 64 },
      xaxis: { color: t.text, tickangle: -30, automargin: true },
      yaxis: axis,
    });
  }

  function showFailed(el) {
    el.hidden = true;
    var note = el.parentNode && el.parentNode.querySelector("[data-report-chart-failed]");
    if (note) note.hidden = false;
  }

  function draw(el) {
    el.setAttribute("data-drawn", "1");
    var data = readData();
    if (!data || !Array.isArray(data.labels) || data.labels.length === 0) return;
    loadLibrary(el.getAttribute("data-plotly-src") || "", function (ok) {
      if (!ok || !el.isConnected) {
        if (ok === false) showFailed(el);
        return;
      }
      var t = theme();
      try {
        if (isHorizontal(data)) el.style.height = Math.max(320, data.labels.length * 32 + 60) + "px";
        var drawing = window.Plotly.newPlot(el, traces(data, t), layout(data, t), CONFIG);
        if (drawing && typeof drawing.catch === "function") {
          drawing.catch(function () { showFailed(el); });
        }
        if (el.isConnected && drawn.indexOf(el) < 0) drawn.push(el);
      } catch (err) {
        showFailed(el);
      }
    });
  }

  function drawAll(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll("[data-report-chart]"), function (el) {
      if (!el.hasAttribute("data-drawn")) draw(el);
    });
  }

  // Releases one chart: Plotly removes its resize listener and the element forgets it was drawn.
  function purge(el) {
    try {
      if (window.Plotly) window.Plotly.purge(el);
    } catch (err) { /* already gone */ }
    drawn = drawn.filter(function (d) { return d !== el; });
    el.removeAttribute("data-drawn");
  }

  // The report is about to be replaced by htmx: its charts go before the swap, the new ones are drawn after it.
  // A swap that htmx cancels (shouldSwap false) leaves the page as it is.
  document.addEventListener("htmx:beforeSwap", function (e) {
    if (e.detail && e.detail.shouldSwap === false) return;
    var target = (e.detail && e.detail.target) || document.body;
    drawn.slice().forEach(function (el) {
      if (target.contains(el)) purge(el);
    });
  });
  document.addEventListener("htmx:afterSettle", function () { drawAll(document); });

  // A chart removed some other way is purged too.
  new MutationObserver(function () {
    drawn = drawn.filter(function (el) {
      if (el.isConnected) return true;
      try {
        if (window.Plotly) window.Plotly.purge(el);
      } catch (err) { /* already gone */ }
      return false;
    });
  }).observe(document.body, { childList: true, subtree: true });

  // A theme change (data-theme on <html>) redraws the drawn charts with the new colours.
  new MutationObserver(function () {
    Array.prototype.forEach.call(document.querySelectorAll("[data-report-chart][data-drawn]"), draw);
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  drawAll(document);
})();
