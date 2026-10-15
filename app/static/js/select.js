// Dropdown list for every <select>: the native select stays as the visible field (its
// styling, width and error state are unchanged) but opens this list instead of the
// browser's. Lists with SEARCH_FROM or more options get a search box; data-search="on"
// or "off" on the select overrides that. Picking sets select.value and fires "change",
// so forms, filters and htmx triggers work as before. Touch devices keep the native picker.
(function () {
  "use strict";
  var SEARCH_FROM = 8;
  if (window.matchMedia && window.matchMedia("(pointer: coarse)").matches) return;

  var popup = null, current = null, search = null, list = null, items = [], active = -1;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function wantsSearch(select) {
    var flag = select.getAttribute("data-search");
    if (flag === "on") return true;
    if (flag === "off") return false;
    return select.options.length >= SEARCH_FROM;
  }

  function place() {
    if (!popup || !current) return;
    var r = current.getBoundingClientRect();
    popup.style.minWidth = r.width + "px";
    var below = window.innerHeight - r.bottom, h = popup.offsetHeight;
    var top = below < h + 8 && r.top > below ? r.top - h - 4 : r.bottom + 4;
    popup.style.top = Math.max(4, top) + "px";
    popup.style.left = Math.max(4, Math.min(r.left, window.innerWidth - popup.offsetWidth - 4)) + "px";
  }

  function setActive(i) {
    var shown = items.filter(function (it) { return !it.hidden; });
    if (!shown.length) { active = -1; return; }
    i = Math.max(0, Math.min(i, shown.length - 1));
    items.forEach(function (it) { it.classList.remove("sel-active"); });
    shown[i].classList.add("sel-active");
    shown[i].scrollIntoView({ block: "nearest" });
    active = i;
  }
  function visible() { return items.filter(function (it) { return !it.hidden; }); }

  function filter() {
    var q = search.value.trim().toLowerCase(), any = false;
    items.forEach(function (it) {
      var hit = !q || it.textContent.toLowerCase().indexOf(q) !== -1;
      it.hidden = !hit;
      if (hit) any = true;
    });
    list.querySelector(".sel-empty").hidden = any;
    setActive(0);
  }

  function pick(index) {
    var select = current;
    if (select.selectedIndex !== index) {
      select.selectedIndex = index;
      select.dispatchEvent(new Event("input", { bubbles: true }));
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
    close();
    select.focus();
  }

  function close() {
    if (!popup) return;
    popup.remove();
    popup = null; current = null; search = null; list = null; items = []; active = -1;
    document.removeEventListener("mousedown", outside, true);
  }
  function outside(e) {
    if (popup && !popup.contains(e.target) && e.target !== current) close();
  }

  function onKey(e) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
    else if (e.key === "Enter") {
      e.preventDefault();
      var it = visible()[active];
      if (it) pick(+it.dataset.index);
    } else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); var s = current; close(); s.focus(); }
    else if (e.key === "Tab") { close(); }
  }

  function open(select, typed) {
    close();
    current = select;
    popup = el("div", "sel-popup");
    popup.setAttribute("role", "listbox");
    if (wantsSearch(select)) {
      search = el("input", "sel-search");
      search.type = "text";
      search.placeholder = "Хайх…";
      search.setAttribute("aria-label", "Хайх");
      search.addEventListener("input", filter);
      search.addEventListener("keydown", onKey);
      popup.appendChild(search);
    }
    list = el("div", "sel-list");
    Array.prototype.forEach.call(select.options, function (opt, i) {
      if (opt.hidden) return;
      var it = el("button", "sel-item" + (i === select.selectedIndex ? " sel-selected" : ""), opt.text || " ");
      it.type = "button";
      it.tabIndex = -1;
      it.dataset.index = i;
      it.disabled = opt.disabled;
      it.setAttribute("role", "option");
      it.addEventListener("mousedown", function (e) { e.preventDefault(); });
      it.addEventListener("click", function () { pick(i); });
      it.addEventListener("mousemove", function () { setActive(visible().indexOf(it)); });
      list.appendChild(it);
      items.push(it);
    });
    var empty = el("div", "sel-empty", "Олдсонгүй");
    empty.hidden = true;
    list.appendChild(empty);
    popup.appendChild(list);
    popup.addEventListener("keydown", onKey);
    document.body.appendChild(popup);
    place();
    var sel = visible().findIndex(function (it) { return +it.dataset.index === select.selectedIndex; });
    setActive(sel < 0 ? 0 : sel);
    if (search) {
      if (typed) { search.value = typed; filter(); }
      search.focus();
    } else {
      popup.tabIndex = -1;
      popup.focus();
    }
    document.addEventListener("mousedown", outside, true);
  }

  function enhance(select) {
    if (select.dataset.selReady || select.multiple || select.size > 1 || select.classList.contains("dp-select")) return;
    select.dataset.selReady = "1";
    select.addEventListener("mousedown", function (e) {
      if (e.button !== 0 || select.disabled) return;
      e.preventDefault();
      select.focus();
      if (current === select) close(); else open(select);
    });
    select.addEventListener("keydown", function (e) {
      if (select.disabled || current === select) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " " || e.key === "F4") {
        e.preventDefault();
        open(select);
      } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && wantsSearch(select)) {
        e.preventDefault();
        open(select, e.key);
      }
    });
  }

  function init(root) {
    (root.matches && root.matches("select") ? [root] : root.querySelectorAll("select")).forEach(enhance);
  }
  document.addEventListener("DOMContentLoaded", function () { init(document); });
  document.addEventListener("htmx:load", function (e) { init(e.detail.elt); });
  document.addEventListener("htmx:beforeSwap", close);
  window.addEventListener("resize", close);
  document.addEventListener("scroll", function (e) { if (!popup || !popup.contains(e.target)) place(); }, true);
})();
