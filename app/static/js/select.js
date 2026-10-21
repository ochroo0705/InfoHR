// Dropdown for every <select> (docs/UI_RULES.md §2 and §2a). The real <select> stays in the form (hidden
// when it has a typing box) so it is still the submitted field.
// - Click list: a select with fewer than SEARCH_FROM options, or data-search="off". Touch devices keep the native picker.
// - Typing dropdown: a select with SEARCH_FROM options or more, data-search="on", or data-add-url. The visible
//   field is a text box that is also the search. Touch devices use it only for data-add-url selects.
// - Add on the spot (data-add-url, only when <body data-can-add-lists>): when the typed text matches no entry,
//   a last line «+ "text" нэмэх» adds it. data-add-modal opens a pop-up for the other fields.
// Picking sets select.value and fires "input" and "change", so forms, filters and htmx triggers keep working.
(function () {
  "use strict";
  var SEARCH_FROM = 8;
  var coarse = !!(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);

  var popup = null;     // the open list (div.sel-popup)
  var owner = null;     // { select, input } of the open list; input is null for a click list
  var anchor = null;    // element the list hangs under
  var list = null, items = [], active = -1, typed = false, addLine = null;
  var note = null;      // short line under a typing box
  var quickModal = null, quickSelect = null;

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
  function isCombo(select) {
    return select.hasAttribute("data-add-url") || wantsSearch(select);
  }
  function canAdd(select) {
    return select.hasAttribute("data-add-url") && document.body.hasAttribute("data-can-add-lists");
  }
  function shownText(select) {
    var o = select.options[select.selectedIndex];
    return o && o.value !== "" ? o.text : "";
  }
  function emptyIndex(select) {
    for (var i = 0; i < select.options.length; i++) if (select.options[i].value === "") return i;
    return -1;
  }
  function csrfToken(select) {
    var field = select.form && select.form.querySelector("[name=csrfmiddlewaretoken]");
    if (field) return field.value;
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function place() {
    if (!popup || !anchor) return;
    var r = anchor.getBoundingClientRect();
    popup.style.minWidth = r.width + "px";
    var below = window.innerHeight - r.bottom, h = popup.offsetHeight;
    var top = below < h + 8 && r.top > below ? r.top - h - 4 : r.bottom + 4;
    popup.style.top = Math.max(4, top) + "px";
    popup.style.left = Math.max(4, Math.min(r.left, window.innerWidth - popup.offsetWidth - 4)) + "px";
  }

  function visible() { return items.filter(function (it) { return !it.hidden; }); }

  function setActive(i) {
    var shown = visible();
    if (!shown.length) { active = -1; return; }
    i = Math.max(0, Math.min(i, shown.length - 1));
    items.forEach(function (it) { it.classList.remove("sel-active"); });
    shown[i].classList.add("sel-active");
    shown[i].scrollIntoView({ block: "nearest" });
    active = i;
  }

  function filter() {
    var text = owner.input ? owner.input.value.trim() : "";
    var q = typed ? text.toLowerCase() : "";
    var any = false, exact = false;
    items.forEach(function (it) {
      if (it === addLine) return;
      var label = it.textContent.trim().toLowerCase();
      var hit = !q || label.indexOf(q) !== -1;
      it.hidden = !hit;
      if (hit) any = true;
      if (q && label === q) exact = true;
    });
    var showAdd = !!addLine && !!q && !exact;
    if (addLine) {
      addLine.hidden = !showAdd;
      addLine.textContent = '+ "' + text + '" нэмэх';
    }
    list.querySelector(".sel-empty").hidden = any || showAdd;
    setActive(0);
  }

  function choose(select, index) {
    if (select.selectedIndex !== index) {
      select.selectedIndex = index;
      select.dispatchEvent(new Event("input", { bubbles: true }));
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  function syncText(c) {
    c.input.value = shownText(c.select);
    c.input.disabled = c.select.disabled;
    c.input.required = c.select.required;
  }

  function clearNote() {
    if (note) note.remove();
    note = null;
  }
  function flash(c, text, isError) {
    clearNote();
    note = el("small", "sel-note" + (isError ? " sel-error" : ""), text);
    c.input.insertAdjacentElement("afterend", note);
  }

  function close() {
    if (!popup) return;
    var c = owner;
    popup.remove();
    popup = null; owner = null; anchor = null; list = null;
    items = []; addLine = null; active = -1; typed = false;
    document.removeEventListener("mousedown", outside, true);
    if (c && c.input) c.input.setAttribute("aria-expanded", "false");
  }
  function outside(e) {
    if (popup && !popup.contains(e.target) && e.target !== anchor) close();
  }

  function pick(c, index) {
    choose(c.select, index);
    close();
    clearNote();
    if (c.input) { syncText(c); c.input.focus(); } else c.select.focus();
  }

  function addTyped(c) {
    var name = c.input.value.trim();
    close();
    if (!name) return;
    if (c.select.hasAttribute("data-add-modal")) openQuickModal(c, name);
    else postName(c, name);
  }

  function onKey(c, e) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
    else if (e.key === "Enter") {
      e.preventDefault();
      if (c.input && !c.input.value.trim()) { close(); leave(c); return; }
      var it = visible()[active];
      if (it === addLine) addTyped(c);
      else if (it) pick(c, +it.dataset.index);
    } else if (e.key === "Escape") {
      e.preventDefault(); e.stopPropagation();
      close();
      if (c.input) syncText(c); else c.select.focus();
    } else if (e.key === "Tab") {
      close();
    }
  }

  function openPopup(c) {
    close();
    owner = c;
    anchor = c.input || c.select;
    typed = false;
    popup = el("div", "sel-popup");
    popup.setAttribute("role", "listbox");
    popup.tabIndex = -1;
    list = el("div", "sel-list");
    items = [];
    Array.prototype.forEach.call(c.select.options, function (opt, i) {
      if (opt.hidden) return;
      var it = el("button", "sel-item" + (i === c.select.selectedIndex ? " sel-selected" : ""), opt.text || " ");
      it.type = "button";
      it.tabIndex = -1;
      it.dataset.index = i;
      it.disabled = opt.disabled;
      it.setAttribute("role", "option");
      it.addEventListener("mousedown", function (e) { e.preventDefault(); });
      it.addEventListener("click", function () { pick(c, i); });
      it.addEventListener("mousemove", function () { setActive(visible().indexOf(it)); });
      list.appendChild(it);
      items.push(it);
    });
    addLine = null;
    if (c.input && canAdd(c.select)) {
      addLine = el("button", "sel-item sel-add", "");
      addLine.type = "button";
      addLine.tabIndex = -1;
      addLine.hidden = true;
      addLine.addEventListener("mousedown", function (e) { e.preventDefault(); });
      addLine.addEventListener("click", function () { addTyped(c); });
      addLine.addEventListener("mousemove", function () { setActive(visible().indexOf(addLine)); });
      list.appendChild(addLine);
      items.push(addLine);
    }
    var empty = el("div", "sel-empty", "Олдсонгүй");
    empty.hidden = true;
    list.appendChild(empty);
    popup.appendChild(list);
    popup.addEventListener("keydown", function (e) { onKey(c, e); });
    popup.addEventListener("mousedown", function (e) {
      if (e.target.tagName !== "INPUT") e.preventDefault();  // keep focus in the text box
    });
    document.body.appendChild(popup);
    if (c.input) c.input.setAttribute("aria-expanded", "true");
    place();
    var sel = visible().findIndex(function (it) { return +it.dataset.index === c.select.selectedIndex; });
    setActive(sel < 0 ? 0 : sel);
    if (!c.input) popup.focus();
    document.addEventListener("mousedown", outside, true);
  }

  // A text box in place of a typing dropdown: leaving it without a pick restores the text; an emptied box
  // clears the select when the select is optional and has an empty entry.
  function leave(c) {
    if (!c.input.value.trim() && !c.select.required) {
      var empty = emptyIndex(c.select);
      if (empty >= 0) choose(c.select, empty);
    }
    syncText(c);
  }

  function combo(select) {
    var c = { select: select, input: null };
    var input = el("input");
    input.type = "text";
    input.className = select.className + " sel-combo";
    input.autocomplete = "off";
    input.spellcheck = false;
    // The hint shows only while the box has focus (docs/UI_RULES.md §2a); the text source is unchanged.
    var hint = select.dataset.placeholder || "Хайх…";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-autocomplete", "list");
    if (select.id) input.id = "sel-" + select.id;
    c.input = input;
    select._selCombo = c;
    select.style.display = "none";
    select.parentNode.insertBefore(input, select);
    if (select.id) {
      // Labels point at the select by id; move them to the text box so a click on the label focuses it.
      Array.prototype.forEach.call(document.getElementsByTagName("label"), function (label) {
        if (label.htmlFor === select.id) label.htmlFor = input.id;
      });
    }
    syncText(c);
    select.addEventListener("change", function () { syncText(c); });

    var justFocused = false;
    input.addEventListener("focus", function () {
      input.placeholder = hint;
      clearNote();
      openPopup(c);
      justFocused = true;
      setTimeout(function () { input.select(); }, 0);
    });
    input.addEventListener("mouseup", function (e) {
      if (justFocused) { e.preventDefault(); justFocused = false; }
    });
    input.addEventListener("click", function () {
      if (!popup || owner !== c) openPopup(c);
    });
    input.addEventListener("input", function () {
      if (!popup || owner !== c) openPopup(c);
      typed = true;
      clearNote();
      filter();
    });
    input.addEventListener("keydown", function (e) {
      if (!popup || owner !== c) {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); openPopup(c); }
        return;
      }
      onKey(c, e);
    });
    input.addEventListener("blur", function () {
      input.removeAttribute("placeholder");
      justFocused = false;
      close();
      leave(c);
    });
  }

  function openQuickModal(c, name) {
    var url = c.select.getAttribute("data-add-url") + "?name=" + encodeURIComponent(name);
    var parent = c.select.getAttribute("data-add-parent");
    var parentField = parent && c.select.form ? c.select.form.elements[parent] : null;
    if (parentField && parentField.value) url += "&" + encodeURIComponent(parent) + "=" + encodeURIComponent(parentField.value);
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        closeQuickModal();
        var wrap = el("div");
        wrap.innerHTML = html;
        quickModal = wrap.firstElementChild;
        quickSelect = c.select;
        document.body.appendChild(quickModal);
        var first = quickModal.querySelector("input:not([type=hidden]), select");
        if (first) first.focus();
      })
      .catch(function () { flash(c, "Сүлжээний алдаа гарлаа.", true); });
  }
  function closeQuickModal() {
    if (quickModal) quickModal.remove();
    quickModal = null;
    quickSelect = null;
  }

  function readReply(r) {
    return r.text().then(function (text) {
      var data = null;
      try { data = JSON.parse(text); } catch (err) { data = null; }
      return { ok: r.ok, status: r.status, data: data, text: text };
    });
  }
  function errorFor(status) {
    return status === 403 ? "Нэмэх эрхгүй." : "Серверийн алдаа гарлаа. Дахин оролдоно уу.";
  }

  function postName(c, name) {
    var body = new FormData();
    body.append("name", name);
    fetch(c.select.getAttribute("data-add-url"), {
      method: "POST",
      body: body,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken(c.select) },
    })
      .then(readReply)
      .then(function (res) {
        if (res.ok && res.data) applyEntry(c.select, res.data);
        else flash(c, (res.data && res.data.error) || errorFor(res.status), true);
      })
      .catch(function () { flash(c, "Сүлжээний алдаа гарлаа.", true); });
  }

  // Put the saved entry into the list (sorted by name) and select it. An entry that already existed is only selected.
  function applyEntry(select, data) {
    var value = String(data.id), index = -1;
    Array.prototype.forEach.call(select.options, function (o, i) { if (o.value === value) index = i; });
    if (index < 0) {
      var before = null;
      Array.prototype.some.call(select.options, function (o) {
        if (o.value !== "" && o.text.localeCompare(data.name) > 0) { before = o; return true; }
        return false;
      });
      var opt = new Option(data.name, value);
      select.add(opt, before);
      index = Array.prototype.indexOf.call(select.options, opt);
    }
    choose(select, index);
    var c = select._selCombo;
    if (c) {
      syncText(c);
      if (data.existed) flash(c, "Ийм бичлэг аль хэдийн бүртгэлтэй байсан тул түүнийг сонголоо.", false);
    }
  }

  function showModalError(text) {
    if (!quickModal) return;
    var form = quickModal.querySelector("form");
    var old = form && form.querySelector(".sel-modal-error");
    if (old) old.remove();
    if (form) form.insertBefore(el("p", "sel-modal-error rounded bg-red-50 p-2 text-sm text-red-700", text), form.firstChild);
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && quickModal) { e.preventDefault(); closeQuickModal(); }
  });

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form || !form.hasAttribute || !form.hasAttribute("data-quick-form")) return;
    e.preventDefault();
    var select = quickSelect;
    if (!select) return;
    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken(select) },
    })
      .then(readReply)
      .then(function (res) {
        if (res.ok && res.data) {
          closeQuickModal();
          applyEntry(select, res.data);
        } else if (res.status === 400 && res.data === null) {
          // Field errors: the server sends the modal back with the messages.
          var wrap = el("div");
          wrap.innerHTML = res.text;
          var fresh = wrap.firstElementChild;
          if (quickModal && fresh) quickModal.replaceWith(fresh);
          quickModal = fresh;
        } else {
          showModalError((res.data && res.data.error) || errorFor(res.status));
        }
      })
      .catch(function () { showModalError("Сүлжээний алдаа гарлаа."); });
  });

  function enhance(select) {
    // Ready state lives on the element, not in an attribute: htmx settling copies the old element's
    // attributes onto a same-id new one and restores them later, which would fake or undo it.
    if (select._selReady) {
      if (select._selCombo) select.style.display = "none";
      return;
    }
    if (select.multiple || select.size > 1 || select.classList.contains("dp-select")) return;
    if (coarse && !select.hasAttribute("data-add-url")) return;
    select._selReady = true;
    if (isCombo(select)) { combo(select); return; }
    var c = { select: select, input: null };
    select.addEventListener("mousedown", function (e) {
      if (e.button !== 0 || select.disabled) return;
      e.preventDefault();
      select.focus();
      if (owner && owner.select === select) close(); else openPopup(c);
    });
    select.addEventListener("keydown", function (e) {
      if (select.disabled || (owner && owner.select === select)) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " " || e.key === "F4") {
        e.preventDefault();
        openPopup(c);
      }
    });
  }

  function init(root) {
    if (!root || !root.querySelectorAll) return;
    (root.matches && root.matches("select") ? [root] : root.querySelectorAll("select")).forEach(enhance);
  }
  document.addEventListener("DOMContentLoaded", function () {
    init(document);
    // Selects added later (formset rows, htmx swaps, pop-ups) are upgraded as they appear.
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        Array.prototype.forEach.call(record.addedNodes, function (node) {
          if (node.nodeType === 1) init(node);
        });
      });
    }).observe(document.documentElement, { childList: true, subtree: true });
  });
  document.addEventListener("htmx:load", function (e) { init(e.detail.elt); });
  // Settling puts back the new element's own attributes (no display:none) after we hid it; hide it again.
  document.addEventListener("htmx:afterSettle", function (e) { init(e.detail.elt); });
  document.addEventListener("htmx:beforeSwap", close);
  window.addEventListener("resize", place);
  document.addEventListener("scroll", function (e) { if (!popup || !popup.contains(e.target)) place(); }, true);
})();
