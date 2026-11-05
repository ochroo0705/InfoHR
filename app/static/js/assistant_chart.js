// The chart pop-up of an assistant table answer (assistant/_chart_modal.html, docs/UI_RULES.md §6c). The pop-up carries
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

  function popupOf(el) {
    return el.closest(".fixed.inset-0") || document;
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

  function layout(kind, maxCount) {
    var text = cssVar("--color-slate-700");
    var base = {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: text, size: 13 },
      autosize: true,
    };
    if (kind === "pie") {
      return Object.assign(base, { showlegend: true, legend: { font: { color: text } }, margin: { l: 8, r: 8, t: 8, b: 8 } });
    }
    var yaxis = { color: text, gridcolor: cssVar("--color-slate-200"), rangemode: "tozero", tickformat: "d" };
    if (maxCount <= 10) yaxis.dtick = 1;  // whole people on the axis, never 0.5 steps
    return Object.assign(base, {
      showlegend: false,
      margin: { l: 48, r: 16, t: 8, b: 64 },
      xaxis: { color: text, tickangle: -30, automargin: true },
      yaxis: yaxis,
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
        hovertext: texts,
        hoverinfo: "text",
        textinfo: "none",
        marker: {
          colors: PIE_COLORS.map(cssVar),
          line: { color: cssVar("--color-surface"), width: 1 },
        },
      }];
    }
    return [{
      type: "bar",
      x: data.labels,
      y: data.counts,
      hovertext: texts,
      hoverinfo: "text",
      marker: { color: cssVar("--color-violet-600") },
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
        window.Plotly.newPlot(el, traces(data), layout(data.kind, maxCount), CONFIG);
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

  // A pop-up that is removed (×, Esc, a click outside) leaves its chart behind in Plotly's registry: purge it.
  new MutationObserver(function () {
    drawn = drawn.filter(function (el) {
      if (el.isConnected) return true;
      try { window.Plotly.purge(el); } catch (err) { /* already gone */ }
      return false;
    });
  }).observe(document.body, { childList: true });

  // The pop-up is fetched by htmx, which shows nothing for an error answer: a stale link (another login, a changed
  // right) must not look like a dead button.
  document.addEventListener("htmx:responseError", function (e) {
    var url = (e.detail && e.detail.xhr && e.detail.xhr.responseURL) || "";
    if (url.indexOf("/assistant/chart/") < 0) return;
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
