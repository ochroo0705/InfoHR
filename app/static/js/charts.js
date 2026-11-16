// The charts of the product (docs/UI_RULES.md, the assistant and the report chart layout). Each element [data-chart]
// is drawn with ECharts: the library is our own file (data-echarts-src), loaded the first time a chart is drawn, never
// from a CDN. The numbers are in the JSON element named by data-chart-data (a json_script id), so one page can hold
// several charts. When a chart cannot be drawn, the note [data-chart-failed] next to it is shown.
// ECharts cannot read the page's oklch() colours, so the colours are hex constants, one set for the light theme and one
// for the dark theme (data-theme on <html>, set by base.html). A theme change redraws the charts. Labels are plain text
// in ECharts, so no label is turned into markup.
(function () {
  "use strict";

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
  var drawn = [];  // charts on the page that are drawn
  var resizers = [];  // {el, observer}: one ResizeObserver per drawn chart

  function theme() {
    return THEMES[document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light"];
  }

  function readData(id) {
    var script = id ? document.getElementById(id) : null;
    try {
      return script ? JSON.parse(script.textContent) : null;
    } catch (err) {
      return null;
    }
  }

  // Loads the library once. Every caller gets the answer: true when window.echarts is there, false when the file failed.
  function loadLibrary(src, done) {
    if (window.echarts) {
      done(true);
      return;
    }
    if (!src) {
      done(false);
      return;
    }
    waiting.push(done);
    if (loading) return;
    loading = true;
    var script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = function () { finish(!!window.echarts); };
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

  // A value that is not a finite number shows as a dash. The text can reach ECharts' HTML tooltip, so it is never
  // the raw value (String(value) would pass markup through).
  var NOT_A_NUMBER = "—";

  // Thousands with commas: 1234 gives "1,234"; one decimal at most, as the data gives it.
  function formatNumber(value) {
    var n = typeof value === "number" ? value : NaN;
    if (!isFinite(n)) return NOT_A_NUMBER;
    var parts = String(Math.round(n * 10) / 10).split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return parts.join(".");
  }

  function formatMoney(value) {
    var n = typeof value === "number" ? value : NaN;
    if (!isFinite(n)) return NOT_A_NUMBER;
    return formatNumber(Math.round(n)) + "₮";
  }

  function formatPercent(value) {
    var n = typeof value === "number" ? value : NaN;
    if (!isFinite(n)) return NOT_A_NUMBER;
    return formatNumber(n) + "%";
  }

  function formatterFor(data) {
    if (data.money) return formatMoney;
    if (data.percent) return formatPercent;
    return formatNumber;
  }

  // An hbar is always horizontal. Long category names or many categories lie the bars flat: rotated labels were
  // unreadable, so a bar or stacked chart with them is drawn horizontally too.
  function isHorizontal(data) {
    if (data.kind === "hbar") return true;
    var longest = data.labels.reduce(function (m, l) { return Math.max(m, String(l).length); }, 0);
    return (data.kind === "bar" || data.kind === "stacked") && (data.labels.length > 6 || longest > 14);
  }

  // The height of a horizontal chart: 32 px a bar and 60 px for the axis, at least 320 px, at most 1200 px (a long list
  // scrolls on the page rather than stretching the chart past a screen).
  function horizontalHeight(count) {
    return Math.min(1200, Math.max(320, count * 32 + 60));
  }

  // The ECharts option of one chart. data: the JSON payload; t: THEMES.light or THEMES.dark.
  function toOption(data, t) {
    var fmt = formatterFor(data);
    var labels = data.labels.map(function (l) { return String(l); });
    var option = {
      backgroundColor: "transparent",
      animation: true,
      animationDuration: 600,
      color: t.series,
      textStyle: { color: t.text },
      toolbox: { right: 0, feature: { saveAsImage: {} } },
      tooltip: { trigger: "axis", valueFormatter: fmt },
    };

    if (data.kind === "donut" || data.kind === "pie") {
      option.tooltip = { trigger: "item", valueFormatter: fmt };
      option.legend = { show: true, bottom: 0, textStyle: { color: t.text } };
      option.series = [{
        type: "pie",
        radius: data.kind === "donut" ? ["55%", "80%"] : "75%",
        center: ["50%", "45%"],
        label: { show: true, formatter: "{d}%", color: "#ffffff" },
        itemStyle: { borderColor: t.surface, borderWidth: 2 },
        data: labels.map(function (name, i) { return { name: name, value: data.values[i] }; }),
      }];
      return option;
    }

    var horizontal = isHorizontal(data);
    var stacked = data.kind === "stacked" && Array.isArray(data.series) && data.series.length > 0;
    var isLine = data.kind === "line" || data.kind === "area";
    var series;
    if (stacked) {
      series = data.series.map(function (s, i) {
        return {
          type: "bar", name: String(s.label), stack: "total", data: s.values,
          itemStyle: { color: t.series[i % t.series.length] },
        };
      });
    } else if (isLine) {
      series = [{
        type: "line", data: data.values, symbol: "circle", symbolSize: 8,
        lineStyle: { color: t.accent, width: 2 }, itemStyle: { color: t.accent },
      }];
      if (data.kind === "area") series[0].areaStyle = { color: t.accent, opacity: 0.25 };
    } else {
      series = [{
        type: "bar", data: data.values, barMaxWidth: 48, itemStyle: { color: t.accent },
        label: {
          show: true, color: t.text, position: horizontal ? "right" : "top",
          formatter: function (p) { return fmt(p.value); },
        },
      }];
    }

    var category = {
      type: "category", data: labels,
      axisLabel: { color: t.text, rotate: horizontal ? 0 : 30 },
      axisLine: { lineStyle: { color: t.grid } },
    };
    var value = {
      type: "value",
      axisLabel: { color: t.text, formatter: function (v) { return fmt(v); } },
      splitLine: { lineStyle: { color: t.grid } },
    };
    if (horizontal) {
      category.inverse = true;  // the first category is at the top, as the table has it
      option.xAxis = value;
      option.yAxis = category;
    } else {
      option.xAxis = category;
      option.yAxis = value;
    }
    option.grid = { left: 8, right: 24, top: 40, bottom: stacked ? 72 : 40, containLabel: true };
    option.legend = { show: stacked, bottom: 0, textStyle: { color: t.text } };
    option.series = series;
    return option;
  }

  function showFailed(el) {
    el.hidden = true;
    var note = el.parentNode && el.parentNode.querySelector("[data-chart-failed]");
    if (note) note.hidden = false;
  }

  // The click target of the category at this index (data.hrefs, one per point), "" when there is none.
  function clickTarget(data, pointNumber) {
    var hrefs = data && data.hrefs;
    if (!Array.isArray(hrefs) || typeof pointNumber !== "number" || pointNumber % 1 !== 0) return "";
    if (pointNumber < 0 || pointNumber >= hrefs.length) return "";
    return typeof hrefs[pointNumber] === "string" ? hrefs[pointNumber] : "";
  }

  // The instance ECharts keeps for this element, or undefined.
  function instanceOf(el) {
    return window.echarts && typeof window.echarts.getInstanceByDom === "function"
      ? window.echarts.getInstanceByDom(el)
      : undefined;
  }

  function disposeInstance(el) {
    var chart = instanceOf(el);
    if (chart) chart.dispose();
  }

  function watchSize(el) {
    if (typeof ResizeObserver === "undefined") return;
    unwatchSize(el);
    var observer = new ResizeObserver(function () {
      var chart = instanceOf(el);
      if (chart) chart.resize();
    });
    observer.observe(el);
    resizers.push({ el: el, observer: observer });
  }

  function unwatchSize(el) {
    resizers = resizers.filter(function (r) {
      if (r.el !== el) return true;
      r.observer.disconnect();
      return false;
    });
  }

  // A category with a table link: the pointer cursor, and a click opens that table.
  function linkPoints(el, chart, data) {
    if (!Array.isArray(data.hrefs) || !data.hrefs.some(function (h) { return typeof h === "string" && h !== ""; })) return;
    el.classList.add("cursor-pointer");
    chart.on("click", function (params) {
      var href = params ? clickTarget(data, params.dataIndex) : "";
      if (href) window.location.href = href;
    });
  }

  function draw(el) {
    el.setAttribute("data-drawn", "1");
    var data = readData(el.getAttribute("data-chart-data"));
    if (!data || !Array.isArray(data.labels)) {
      showFailed(el);  // the JSON is missing or unparsable
      return;
    }
    if (data.labels.length === 0) return;  // the template shows its own "no data" line
    loadLibrary(el.getAttribute("data-echarts-src") || "", function (ok) {
      if (!ok || !el.isConnected) {
        if (ok === false) showFailed(el);
        return;
      }
      var t = theme();
      try {
        // a theme redraw calls this again on the same element: the old instance goes first
        disposeInstance(el);
        el.classList.remove("cursor-pointer");
        if (isHorizontal(data)) el.style.height = horizontalHeight(data.labels.length) + "px";
        var chart = window.echarts.init(el, null, { renderer: "svg" });
        chart.setOption(toOption(data, t));
        linkPoints(el, chart, data);
        watchSize(el);
        if (drawn.indexOf(el) < 0) drawn.push(el);
      } catch (err) {
        showFailed(el);
      }
    });
  }

  function drawAll(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll("[data-chart]"), function (el) {
      if (!el.hasAttribute("data-drawn")) draw(el);
    });
  }

  // Releases one chart: ECharts disposes its instance, the size watcher stops, the element forgets it was drawn.
  function purge(el) {
    try {
      disposeInstance(el);
    } catch (err) { /* already gone */ }
    unwatchSize(el);
    drawn = drawn.filter(function (d) { return d !== el; });
    el.removeAttribute("data-drawn");
  }

  // Under Node (charts.test.mjs) only the pure helpers are exported: the listeners below need a browser.
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { toOption: toOption, clickTarget: clickTarget, horizontalHeight: horizontalHeight };
    return;
  }

  // The content is about to be replaced by htmx: its charts go before the swap, the new ones are drawn after it.
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
        disposeInstance(el);
      } catch (err) { /* already gone */ }
      unwatchSize(el);
      return false;
    });
  }).observe(document.body, { childList: true, subtree: true });

  // A theme change (data-theme on <html>) redraws the drawn charts with the new colours.
  new MutationObserver(function () {
    Array.prototype.forEach.call(document.querySelectorAll("[data-chart][data-drawn]"), draw);
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  drawAll(document);
})();
