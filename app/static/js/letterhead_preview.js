// Letterhead mock (plan 2026-11-13-order-template-editor, task 8). A classic browser script:
// window.LetterheadPreview = { mockStyle, expandLines, render, init }. It draws a small, locked picture of the
// letterhead presets (logo place, text align, logo size, rule line) on a page of A4 width. Two places use it:
//   - the company settings form: a read-only field renders <div data-letterhead-mock> inside the form, and the
//     mock redraws on every change of a letterhead field (bindSettingsForm);
//   - the template editor: the block gets its values from a json_script element named by data-letterhead-data.
// Under node (typeof module !== "undefined") only the pure helpers are exported. Text is set with textContent only.
(function () {
  "use strict";

  var PAGE_MM = 210;
  // Logo widths in mm, the same as models.LETTERHEAD_LOGO_MM. The mock scales them to the page width in percent.
  var LOGO_MM = { small: 20, medium: 30, large: 45 };
  var PLACES = ["left", "right", "top", "logo_only"];
  var ALIGNS = ["left", "center", "right"];
  var DEFAULT_PLACE = "left";
  var DEFAULT_ALIGN = "left";
  var DEFAULT_SIZE = "medium";

  function pick(list, value, fallback) {
    return list.indexOf(value) >= 0 ? value : fallback;
  }

  // Values -> what the mock draws. Unknown or missing values fall back to the defaults; the rule is on only for true.
  function mockStyle(values) {
    var v = values || {};
    var place = pick(PLACES, v.logo_place, DEFAULT_PLACE);
    var align = pick(ALIGNS, v.text_align, DEFAULT_ALIGN);
    var size = Object.prototype.hasOwnProperty.call(LOGO_MM, v.logo_size) ? v.logo_size : DEFAULT_SIZE;
    var rule = v.rule === true;
    var classes = ["lh-mock", "lh-place-" + place, "lh-align-" + align, "lh-size-" + size];
    if (rule) classes.push("lh-rule");
    return {
      classes: classes,
      place: place,
      textAlign: align,
      logoSize: size,
      logoWidthPct: Math.round((LOGO_MM[size] / PAGE_MM) * 1000) / 10,
      showLogo: true,
      showText: place !== "logo_only",
      rule: rule,
    };
  }

  // The letterhead lines as the PDF prints them: the company and director names replace their tokens, and a line
  // that is empty afterwards is dropped (the same rule as CompanySettings.letterhead_text).
  function expandLines(raw, companyName, directorName) {
    var lines = [];
    String(raw || "").split(/\r?\n/).forEach(function (line) {
      var text = line
        .split("{company_name}").join(String(companyName || ""))
        .split("{director_name}").join(String(directorName || ""))
        .trim();
      if (text) lines.push(text);
    });
    return lines;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { mockStyle: mockStyle, expandLines: expandLines };
    return;
  }
  if (typeof window === "undefined" || typeof document === "undefined") return;

  function el(tag, className) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    return node;
  }

  // Draws the mock into root (replacing what was there). lines are already expanded.
  function render(root, values, lines) {
    var style = mockStyle(values);
    while (root.firstChild) root.removeChild(root.firstChild);
    var box = el("div", style.classes.join(" "));
    var logo = el("div", "lh-logo");
    logo.style.width = style.logoWidthPct + "%";
    logo.textContent = "Лого";
    var text = el("div", "lh-text");
    if (lines && lines.length) {
      lines.forEach(function (line) {
        var p = el("p");
        p.textContent = line;
        text.appendChild(p);
      });
    } else {
      var empty = el("p", "lh-empty");
      empty.textContent = "Бланкны мөр хоосон байна";
      text.appendChild(empty);
    }
    if (style.showLogo) box.appendChild(logo);
    if (style.showText) box.appendChild(text);
    root.appendChild(box);
  }

  // Redraws root from the fields of a company settings form, on every change of one of them.
  function bindSettingsForm(form, root) {
    function field(name) {
      return form.querySelector('[name="' + name + '"]');
    }
    function valueOf(name) {
      var node = field(name);
      return node ? node.value : "";
    }
    function refresh() {
      var rule = field("letterhead_rule");
      render(
        root,
        {
          logo_place: valueOf("letterhead_logo_place"),
          text_align: valueOf("letterhead_text_align"),
          logo_size: valueOf("letterhead_logo_size"),
          rule: !!(rule && rule.checked),
        },
        expandLines(valueOf("letterhead_lines"), valueOf("name"), valueOf("director_name"))
      );
    }
    form.addEventListener("change", refresh);
    form.addEventListener("input", refresh);
    refresh();
  }

  function readJson(id) {
    var node = id ? document.getElementById(id) : null;
    if (!node) return {};
    try {
      return JSON.parse(node.textContent) || {};
    } catch (e) {
      return {};
    }
  }

  // Draws every mock on the page once. A mock inside a form follows the form; otherwise it reads its json_script.
  function init() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-letterhead-mock]"), function (root) {
      var form = root.closest("form");
      if (form) {
        bindSettingsForm(form, root);
        return;
      }
      var data = readJson(root.getAttribute("data-letterhead-data"));
      render(root, data, data.lines || []);
    });
  }

  window.LetterheadPreview = { mockStyle: mockStyle, expandLines: expandLines, render: render, init: init };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
