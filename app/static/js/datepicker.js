// Calendar picker for every <input type="date">: Mongolian labels, weeks start on
// Monday, month/year dropdowns for fast jumps (birth dates), typed YYYY-MM-DD still
// works. The input keeps its name and ISO value, so the server side is unchanged.
(function () {
  "use strict";
  var MONTHS = ["1-р сар", "2-р сар", "3-р сар", "4-р сар", "5-р сар", "6-р сар",
    "7-р сар", "8-р сар", "9-р сар", "10-р сар", "11-р сар", "12-р сар"];
  var DAYS = ["Да", "Мя", "Лх", "Пү", "Ба", "Бя", "Ня"];
  var popup = null, current = null, view = null;

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function iso(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
  function parse(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || "");
    if (!m) return null;
    var d = new Date(+m[1], +m[2] - 1, +m[3]);
    return d.getMonth() === +m[2] - 1 ? d : null;
  }
  // "20261014" or "2026.10.14" / "2026/10/14" -> "2026-10-14"
  function normalize(s) {
    var digits = (s || "").replace(/\D/g, "");
    if (/^\d{8}$/.test(digits) && !parse(s)) return digits.slice(0, 4) + "-" + digits.slice(4, 6) + "-" + digits.slice(6);
    return s;
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function fire(input) {
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function setValue(input, value) {
    if (input.value === value) return;
    input.value = value;
    fire(input);
  }

  function close() {
    if (popup) popup.remove();
    popup = current = null;
    document.removeEventListener("mousedown", outside, true);
    window.removeEventListener("resize", close);
    document.removeEventListener("scroll", place, true);
  }
  function outside(e) {
    if (popup && !popup.contains(e.target) && e.target !== current && !(current && current.parentNode.contains(e.target))) close();
  }
  function place() {
    if (!popup || !current) return;
    var r = current.getBoundingClientRect(), h = popup.offsetHeight, w = popup.offsetWidth;
    var top = r.bottom + 4;
    if (top + h > window.innerHeight - 8 && r.top - h - 4 > 8) top = r.top - h - 4;
    popup.style.top = top + "px";
    popup.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + "px";
  }

  function render() {
    var input = current, selected = parse(input.value), today = new Date();
    var min = parse(input.min), max = parse(input.max);
    popup.textContent = "";

    var head = el("div", "dp-head");
    var prev = el("button", "dp-nav", "‹"), next = el("button", "dp-nav", "›");
    prev.type = next.type = "button";
    prev.setAttribute("aria-label", "Өмнөх сар");
    next.setAttribute("aria-label", "Дараах сар");
    prev.onclick = function () { view = new Date(view.getFullYear(), view.getMonth() - 1, 1); render(); };
    next.onclick = function () { view = new Date(view.getFullYear(), view.getMonth() + 1, 1); render(); };
    var month = el("select", "dp-select"), year = el("select", "dp-select");
    month.setAttribute("aria-label", "Сар");
    year.setAttribute("aria-label", "Он");
    MONTHS.forEach(function (name, i) { var o = el("option", null, name); o.value = i; month.appendChild(o); });
    var from = min ? min.getFullYear() : 1940, to = max ? max.getFullYear() : today.getFullYear() + 10;
    from = Math.min(from, view.getFullYear()); to = Math.max(to, view.getFullYear());
    for (var y = to; y >= from; y--) { var o = el("option", null, y); o.value = y; year.appendChild(o); }
    month.value = view.getMonth();
    year.value = view.getFullYear();
    month.onchange = year.onchange = function () { view = new Date(+year.value, +month.value, 1); render(); };
    head.append(prev, year, month, next);
    popup.appendChild(head);

    var grid = el("div", "dp-grid");
    grid.setAttribute("role", "grid");
    DAYS.forEach(function (d, i) { grid.appendChild(el("div", "dp-dow" + (i > 4 ? " dp-weekend" : ""), d)); });
    var first = new Date(view.getFullYear(), view.getMonth(), 1);
    var start = new Date(first);
    start.setDate(1 - ((first.getDay() + 6) % 7));  // back to Monday
    for (var i = 0; i < 42; i++) {
      var day = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
      if (i === 35 && day.getMonth() !== view.getMonth()) break;  // skip an all-next-month 6th row
      var b = el("button", "dp-day", day.getDate());
      b.type = "button";
      b.dataset.value = iso(day);
      if (day.getMonth() !== view.getMonth()) b.classList.add("dp-other");
      if ((i % 7) > 4) b.classList.add("dp-weekend");
      if (iso(day) === iso(today)) b.classList.add("dp-today");
      if (selected && iso(day) === iso(selected)) { b.classList.add("dp-selected"); b.setAttribute("aria-selected", "true"); }
      if ((min && day < min) || (max && day > max)) b.disabled = true;
      b.onclick = function () { var inp = current; setValue(inp, this.dataset.value); close(); inp.focus(); };
      grid.appendChild(b);
    }
    popup.appendChild(grid);

    var foot = el("div", "dp-foot");
    var todayBtn = el("button", "dp-link", "Өнөөдөр"), clear = el("button", "dp-link dp-muted", "Цэвэрлэх");
    todayBtn.type = clear.type = "button";
    todayBtn.onclick = function () { var inp = current; setValue(inp, iso(today)); close(); inp.focus(); };
    clear.onclick = function () { var inp = current; setValue(inp, ""); close(); inp.focus(); };
    if (input.required) clear.hidden = true;
    foot.append(clear, todayBtn);
    popup.appendChild(foot);
    place();
  }

  function open(input) {
    if (current === input) return;
    close();
    current = input;
    var d = parse(input.value) || parse(input.min) && new Date() < parse(input.min) && parse(input.min) || new Date();
    view = new Date(d.getFullYear(), d.getMonth(), 1);
    popup = el("div", "dp-popup");
    popup.setAttribute("role", "dialog");
    popup.setAttribute("aria-label", "Огноо сонгох");
    popup.addEventListener("keydown", function (e) { if (e.key === "Escape") { e.stopPropagation(); var inp = current; close(); inp.focus(); } });
    document.body.appendChild(popup);
    render();
    document.addEventListener("mousedown", outside, true);
    window.addEventListener("resize", close);
    document.addEventListener("scroll", place, true);
  }

  function enhance(input) {
    if (input.dataset.dp) return;
    input.dataset.dp = "1";
    input.type = "text";
    input.inputMode = "numeric";
    input.autocomplete = "off";
    input.placeholder = "ОООО-СС-ӨӨ";
    input.maxLength = 10;
    var wrap = el("span", "dp-wrap");
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    var btn = el("button", "dp-icon");
    btn.type = "button";
    btn.tabIndex = -1;
    btn.setAttribute("aria-label", "Хуанли нээх");
    btn.innerHTML = '<svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="4.5" width="14" height="12" rx="2"/><path d="M3 8.5h14M7 2.5v4M13 2.5v4"/></svg>';
    btn.onclick = function () { if (current === input) close(); else { open(input); input.focus(); } };
    wrap.appendChild(btn);
    input.addEventListener("click", function () { open(input); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && current === input) { e.stopPropagation(); close(); }
      else if (e.key === "ArrowDown" && current !== input) { e.preventDefault(); open(input); }
      else if (e.key === "Tab") close();
    });
    input.addEventListener("input", function () {
      var d = parse(input.value);
      if (d && current === input) { view = new Date(d.getFullYear(), d.getMonth(), 1); render(); }
    });
    input.addEventListener("blur", function () {
      var v = normalize(input.value.trim());
      if (v !== input.value) { input.value = v; fire(input); }
    });
  }

  function init(root) {
    (root.matches && root.matches('input[type="date"]') ? [root] : root.querySelectorAll('input[type="date"]')).forEach(enhance);
  }
  document.addEventListener("DOMContentLoaded", function () { init(document); });
  document.addEventListener("htmx:load", function (e) { init(e.detail.elt); });
  // A swapped-out form takes its open picker with it.
  document.addEventListener("htmx:beforeSwap", close);
})();
