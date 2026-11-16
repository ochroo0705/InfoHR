// Excel-style keyboard navigation on report tables (docs/UI_RULES.md §4, «Keyboard grid»; phases 1 and 2 of inline editing).
// Any <table data-grid> gets a cell cursor: click or Tab into a body cell, then move with the arrows, Home/End
// (row start/end), Ctrl+Home/End (first/last cell), PageUp/PageDown (10 rows), Tab/Shift+Tab (next/previous cell,
// wrapping to the next row). Shift+arrows grow a range; Ctrl+C copies the cell or range as tab-separated text that
// pastes into Excel. Enter opens the row's first link, Space ticks the row's checkbox, Esc drops the range.
// Phase 2: an editable cell (td[data-edit]) opens its editor on F2, double-click, Enter or a printable key. The editor
// is the server's form (GET the cell's URL). Enter saves and moves down, Tab saves and moves right, Esc cancels. The
// server's HTML is parsed in a <template> and its nodes moved, never set as page text.
// Phase 3 (D-080): Ctrl+V pastes rows and cells from the cursor (a single value fills a Shift range), Ctrl+D fills the
// range down, Delete clears it, Ctrl+Enter in an open editor sets its value on the whole range. Every batch is first a
// dry run on the server (POST data-bulk-url); the preview shows the new texts, Хадгалах saves, Буцаах undoes a save.
// Rows are read from the DOM on every key, so htmx swaps and «Цааш харуулах» batches need no re-wiring. Pure helpers
// are exported under Node (grid_nav.test.mjs).
(function () {
  "use strict";

  const PAGE = 10;
  const ACTIVE = "is-cell-active";
  const IN_RANGE = "is-cell-range";
  const FAIL = "Хадгалж чадсангүй";
  const SAVE_FAIL = "Хадгалж чадсангүй. Дахин оролдоно уу.";
  const LOGIN_MSG = "Нэвтрэх хугацаа дууссан. Хуудсаа шинэчилж дахин нэвтэрнэ үү.";
  const NO_FORM_MSG = "Засварлагч нээгдсэнгүй. Хуудсаа шинэчилнэ үү.";

  // ---- Pure helpers (no DOM) ----

  // True when the answer is the login page: an expired session makes @login_required redirect every fetch to
  // /login/?next=..., and fetch follows it, so the status is 200 and only the final URL shows it.
  function sessionLost(res) {
    try {
      return new URL(res.url, "http://localhost/").pathname.startsWith("/login");
    } catch (err) {
      return false;
    }
  }

  // The next position for a key. `pos` is {r, c}; `widths` is the cell count of each row. Returns null for a key
  // that is not a move. Columns are clamped to the target row's width (a group-title row has one wide cell).
  function move(pos, key, widths, ctrl) {
    const last = widths.length - 1;
    if (last < 0) return null;
    const clampC = (r, c) => Math.max(0, Math.min(c, widths[r] - 1));
    let { r, c } = pos;
    switch (key) {
      case "ArrowUp": r = ctrl ? 0 : r - 1; break;
      case "ArrowDown": r = ctrl ? last : r + 1; break;
      case "ArrowLeft": c = ctrl ? 0 : c - 1; break;
      case "ArrowRight": c = ctrl ? widths[r] - 1 : c + 1; break;
      case "Home": if (ctrl) r = 0; c = 0; break;
      case "End": if (ctrl) r = last; c = widths[Math.max(0, Math.min(r, last))] - 1; break;
      case "PageUp": r -= PAGE; break;
      case "PageDown": r += PAGE; break;
      case "Tab":
        c += 1;
        if (c >= widths[r]) { if (r >= last) return pos; r += 1; c = 0; }
        break;
      case "ShiftTab":
        c -= 1;
        if (c < 0) { if (r <= 0) return pos; r -= 1; c = widths[r] - 1; }
        break;
      default: return null;
    }
    r = Math.max(0, Math.min(r, last));
    return { r, c: clampC(r, c) };
  }

  // The rectangle between the anchor and the cursor, as {r0, r1, c0, c1}.
  function box(a, b) {
    return { r0: Math.min(a.r, b.r), r1: Math.max(a.r, b.r), c0: Math.min(a.c, b.c), c1: Math.max(a.c, b.c) };
  }

  // Text grid → tab-separated lines, the shape Excel pastes as cells. Tabs and line breaks inside a cell become spaces.
  function toTsv(grid) {
    return grid.map((row) => row.map((t) => String(t).replace(/[\t\r\n]+/g, " ").trim()).join("\t")).join("\n");
  }

  // Clipboard text → rows of cells, as Excel writes it: lines end at \n (\r\n is fine), cells at \t. A cell that starts
  // with a quote runs to the closing quote; "" inside it is one quote, and tabs or line breaks inside stay in the cell.
  // One trailing line break adds no row.
  function parseTsv(text) {
    const s = String(text);
    const rows = [];
    if (s === "") return rows;
    const isBreak = (i) => s[i] === "\n" || (s[i] === "\r" && s[i + 1] === "\n");
    const readPlain = (cell, i) => {
      while (i < s.length && s[i] !== "\t" && !isBreak(i)) cell += s[i++];
      return { cell, i };
    };
    let row = [];
    let i = 0;
    for (;;) {
      let cell = "";
      if (s[i] === '"') {
        i += 1;
        while (i < s.length) {
          if (s[i] === '"') {
            if (s[i + 1] === '"') { cell += '"'; i += 2; continue; }
            i += 1; // the closing quote
            break;
          }
          cell += s[i++];
        }
        ({ cell, i } = readPlain(cell, i)); // anything after the closing quote, up to the next delimiter
      } else {
        ({ cell, i } = readPlain(cell, i));
      }
      row.push(cell);
      if (i >= s.length) { rows.push(row); break; }
      if (s[i] === "\t") { i += 1; continue; }
      i += s[i] === "\r" ? 2 : 1; // a line break ends the row
      rows.push(row);
      row = [];
      if (i >= s.length) break;
    }
    return rows;
  }

  // The cells a paste writes: {r, c, text}. A single value (1×1) onto a Shift range fills the whole range; otherwise the
  // rows are laid from `origin` right and down. Rows past widths.length and cells past a row's width are dropped.
  function planPaste(origin, rows, widths, rangeBox) {
    const out = [];
    const fits = (r, c) => r >= 0 && r < widths.length && c >= 0 && c < widths[r];
    if (rows.length === 1 && rows[0].length === 1 && rangeBox) {
      const text = rows[0][0];
      for (let r = rangeBox.r0; r <= rangeBox.r1; r++) {
        for (let c = rangeBox.c0; c <= rangeBox.c1; c++) {
          if (fits(r, c)) out.push({ r, c, text });
        }
      }
      return out;
    }
    rows.forEach((cells, i) => {
      const r = origin.r + i;
      if (r >= widths.length) return;
      cells.forEach((text, j) => {
        const c = origin.c + j;
        if (fits(r, c)) out.push({ r, c, text });
      });
    });
    return out;
  }

  // Fill down: every cell below the top row of the range gets the top row's text of its column (textAt(r0, c)).
  function planFill(rangeBox, textAt) {
    const out = [];
    for (let c = rangeBox.c0; c <= rangeBox.c1; c++) {
      const text = textAt(rangeBox.r0, c);
      for (let r = rangeBox.r0 + 1; r <= rangeBox.r1; r++) out.push({ r, c, text });
    }
    return out;
  }

  // Every cell of the range gets the same text.
  function planSet(rangeBox, text) {
    const out = [];
    for (let r = rangeBox.r0; r <= rangeBox.r1; r++) {
      for (let c = rangeBox.c0; c <= rangeBox.c1; c++) out.push({ r, c, text });
    }
    return out;
  }

  // A key that types a character: one character (not a name like "Enter"), with no Ctrl, Meta or Alt.
  function isPrintable(e) {
    return typeof e.key === "string" && Array.from(e.key).length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey;
  }

  // Keys typed while an editor is still loading (phase 2): "Ctrl+A", "Backspace" and the printable characters change
  // the text; Enter, Tab, ShiftTab and Escape are the actions that run once the editor is open.
  const CONTROL_KEYS = ["Enter", "Tab", "ShiftTab", "Escape"];

  // The buffered keys before the first action key (the text part) and that action key, or null when there is none.
  function splitBuffered(keys) {
    const cut = keys.findIndex((k) => CONTROL_KEYS.includes(k));
    return cut < 0 ? { text: keys, action: null } : { text: keys.slice(0, cut), action: keys[cut] };
  }

  // The text after the buffered text keys. A character is added (replacing the text when Ctrl+A came before it),
  // Backspace removes the last character (or the whole text after Ctrl+A), Ctrl+A marks the text as selected.
  function applyBuffered(value, keys) {
    let v = value;
    let selected = false;
    keys.forEach((k) => {
      if (k === "Ctrl+A") { selected = true; return; }
      if (k === "Backspace") { v = selected ? "" : Array.from(v).slice(0, -1).join(""); selected = false; return; }
      if (CONTROL_KEYS.includes(k)) return;
      if (selected) { v = ""; selected = false; }
      v += k;
    });
    return v;
  }

  // Editable-column marks (UI_RULES §4b). `rows` is an array of rows, each an array of cells {edit, correct}: edit when
  // the cell is editable (data-edit), correct when it needs a reason (data-correct). Returns one kind per column index:
  // "correct" when any cell in the column is a correction cell, else "edit" when any cell is editable, else "".
  // Ragged rows are fine: the result is as wide as the widest row.
  function columnKinds(rows) {
    const width = rows.reduce((m, row) => Math.max(m, row.length), 0);
    const kinds = new Array(width).fill("");
    rows.forEach((row) => row.forEach((cell, c) => {
      if (cell.correct) kinds[c] = "correct";
      else if (cell.edit && kinds[c] === "") kinds[c] = "edit";
    }));
    return kinds;
  }

  const helpers = {
    move, box, toTsv, parseTsv, planPaste, planFill, planSet, isPrintable, splitBuffered, applyBuffered, sessionLost,
    columnKinds, ACTIVE, IN_RANGE, PAGE,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = helpers;
  if (typeof document === "undefined") return;

  // ---- Page wiring ----

  let anchor = null; // {table, r, c} where a Shift range started
  let editing = null; // the td whose editor is open or loading (one at a time)
  let loading = null; // {td, keys}: while the editor's fetch is in flight, the keys typed into the cell (see bufferKey)
  let openSeq = 0; // counts editor opens: a fetch answers only for the open it was started by
  let preview = null; // the open bulk action (phase 3): {table, bar, phase, entries, timer}; one at a time

  // An editor whose cell left the page (an htmx swap, a re-rendered table) can never be saved or cancelled from here:
  // forget it and invalidate its pending fetch.
  function dropDetached() {
    if (editing && !document.contains(editing)) {
      openSeq += 1;
      editing = null;
      loading = null;
    }
    dropPreview();
  }

  function bodyRows(table) {
    return Array.from(table.tBodies).flatMap((tb) => Array.from(tb.rows)).filter((tr) => !tr.hidden && tr.cells.length);
  }

  function posOf(td) {
    const table = td.closest("table[data-grid]");
    if (!table || !td.closest("tbody")) return null;
    const r = bodyRows(table).indexOf(td.parentElement);
    return r < 0 ? null : { table, r, c: td.cellIndex };
  }

  function cellAt(table, r, c) {
    const row = bodyRows(table)[r];
    return row ? row.cells[Math.min(c, row.cells.length - 1)] : null;
  }

  function clearMarks(table) {
    table.querySelectorAll("." + IN_RANGE).forEach((el) => el.classList.remove(IN_RANGE));
  }

  function activate(td, keepRange) {
    const table = td.closest("table[data-grid]");
    table.querySelectorAll("." + ACTIVE).forEach((el) => {
      el.classList.remove(ACTIVE);
      el.tabIndex = -1;
    });
    td.classList.add(ACTIVE);
    td.tabIndex = 0;
    td.focus({ preventScroll: false });
    td.scrollIntoView({ block: "nearest", inline: "nearest" });
    clearMarks(table);
    if (!keepRange) anchor = null;
    if (anchor && anchor.table === table) {
      const p = posOf(td);
      const b = box(anchor, p);
      const rows = bodyRows(table);
      for (let r = b.r0; r <= b.r1; r++) {
        for (let c = b.c0; c <= b.c1; c++) {
          const cell = rows[r] && rows[r].cells[c];
          if (cell) cell.classList.add(IN_RANGE);
        }
      }
    }
  }

  function cellText(td) {
    if (!td) return "";
    const box = td.querySelector("input[type=checkbox]");
    if (box && td.textContent.trim() === "") return box.checked ? "✓" : "";
    return td.innerText || td.textContent || "";
  }

  function copy(table, p) {
    const b = anchor && anchor.table === table ? box(anchor, p) : { r0: p.r, r1: p.r, c0: p.c, c1: p.c };
    const rows = bodyRows(table);
    const grid = [];
    for (let r = b.r0; r <= b.r1; r++) {
      const line = [];
      for (let c = b.c0; c <= b.c1; c++) line.push(cellText(rows[r] && rows[r].cells[c]));
      grid.push(line);
    }
    const text = toTsv(grid);
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).catch(() => {});
  }

  function isField(el) {
    return !!el.closest("input, select, textarea, button, summary, [contenteditable=true]") && !el.matches("td");
  }

  // ---- Editing (phase 2) ----

  function busy(td) {
    return td.classList.contains("opacity-50"); // a save is in flight
  }

  // Puts an editor into td. A floating editor (form.cell-pop: the correction editor, UI_RULES §4) opens as a panel over
  // the cell and its neighbours, so a narrow column still gets a full-width field, reason and note; the cell keeps its
  // old text underneath (faded) so the row does not change height. Near the table's right or bottom edge the panel
  // opens to the left or upwards.
  function mountEditor(td, content) {
    td.replaceChildren(content);
    const form = td.querySelector("form.cell-pop");
    td.classList.toggle("is-popped", !!form);
    if (!form) return;
    const ghost = document.createElement("span");
    ghost.setAttribute("data-cell-ghost", "");
    ghost.setAttribute("aria-hidden", "true");
    ghost.innerHTML = td.dataset.saved || "";
    td.prepend(ghost);
    const box = (td.closest(".ptable") || td.closest("table")).getBoundingClientRect();
    const r = form.getBoundingClientRect();
    if (r.right > box.right) form.classList.add("pop-left");
    const cell = td.getBoundingClientRect();
    if (r.bottom > box.bottom && cell.bottom - box.top > r.height) form.classList.add("pop-up");
  }

  // Put the cell back as it was before its editor opened (or drop the editor while it was still loading).
  function restore(td) {
    if (td.dataset.saved !== undefined) td.innerHTML = td.dataset.saved;
    delete td.dataset.saved;
    td.classList.remove("is-popped");
    td.classList.remove("opacity-50");
    if (editing === td) editing = null;
    if (loading && loading.td === td) loading = null;
  }

  function cancelEdit() {
    const td = editing;
    if (!td || busy(td)) return;
    restore(td);
    td.focus();
  }

  function focusField(td) {
    const f = td.querySelector("input:not([type=hidden]), select, textarea");
    if (f) f.focus();
  }

  // While the editor loads, its keys are kept in `loading` and played back by startEdit when it opens. Text keys
  // (printable, Backspace, Ctrl+A) and Enter, Tab, Shift+Tab, Escape are kept; the other keys are left alone.
  function bufferKey(e) {
    const ctrl = e.ctrlKey || e.metaKey;
    let k = null;
    if (ctrl && (e.key === "a" || e.key === "A")) k = "Ctrl+A";
    else if (ctrl) return; // other shortcuts are not for the cell
    else if (e.key === "Backspace") k = "Backspace";
    else if (e.key === "Enter") k = "Enter";
    else if (e.key === "Tab") k = e.shiftKey ? "ShiftTab" : "Tab";
    else if (e.key === "Escape") k = "Escape";
    else if (isPrintable(e)) k = e.key;
    if (k === null) return;
    e.preventDefault();
    loading.keys.push(k);
  }

  // Opens the editor in td. `typed` is the key that started it: it becomes the text box's value. Returns false when
  // no editor opens (another is open, or a bulk preview is). A Shift range may be held: Ctrl+Enter sets it.
  // Keys pressed while the fetch is in flight are applied to the text box when it opens (the text keys), then the
  // first action key (Enter saves and moves down, Tab saves and moves right, Escape cancels) runs. Keys after it are dropped.
  function startEdit(td, typed) {
    dropDetached();
    if (editing || preview) return false;
    editing = td;
    const mine = ++openSeq;
    loading = { td, keys: [] };
    td.removeAttribute("title");
    fetch(td.dataset.edit, { credentials: "same-origin", headers: { Accept: "text/html" } })
      .then((r) => {
        if (sessionLost(r)) return null; // the login page: no editor
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.text();
      })
      .then((html) => {
        if (mine !== openSeq || editing !== td) return; // cancelled, or another open started since
        const buffered = loading && loading.td === td ? loading.keys : [];
        loading = null;
        if (html === null) return openFailed(td, LOGIN_MSG);
        const tpl = document.createElement("template");
        tpl.innerHTML = html;
        if (!tpl.content.querySelector("form[data-cell-form]")) return openFailed(td, NO_FORM_MSG);
        if (td.dataset.saved === undefined) td.dataset.saved = td.innerHTML;
        mountEditor(td, tpl.content);
        const parts = splitBuffered(buffered);
        // the editor's main widget is the field's own one, not the correction reason box: typed text goes into it only
        // when it is a text input (a select takes no typed text, so the typed character is dropped)
        const main = [...td.querySelectorAll("input:not([type=hidden]):not([type=date]), select, textarea")].find(
          (el) => el.name !== "reason"
        );
        const text = main && main.tagName === "INPUT" ? main : null;
        if (text && (typed !== undefined || parts.text.length)) {
          text.value = applyBuffered(typed !== undefined ? typed : text.value, parts.text);
        }
        focusField(td);
        if (parts.action === "Escape") cancelEdit();
        else if (parts.action) submit(td, parts.action === "Enter" ? "ArrowDown" : parts.action === "ShiftTab" ? "ShiftTab" : "Tab");
      })
      .catch(() => {
        if (mine !== openSeq || editing !== td) return;
        restore(td);
        td.title = FAIL;
      });
    return true;
  }

  // The editor could not open: the cell goes back as it was; the reason is the cell's title and a bar with [Хаах].
  function openFailed(td, msg) {
    restore(td);
    td.title = msg;
    const table = td.closest("table[data-grid]");
    if (table && !preview) {
      const st = { table, bar: null, phase: "error", entries: new Map(), timer: 0 };
      preview = st;
      showBar(st, msg, [{ label: "Хаах", main: true, run: () => finish(st) }]);
    }
  }

  // A save failed and the editor stays open with the typed value: the message goes under the field (data-cell-error).
  function showSaveError(td, form, msg) {
    td.classList.remove("opacity-50");
    let el = form.querySelector("[data-cell-error]");
    if (!el) {
      el = document.createElement("p");
      el.className = "text-xs text-red-700";
      el.setAttribute("data-cell-error", "");
      form.appendChild(el);
    }
    el.textContent = msg;
    focusField(td);
  }

  // Saves the open editor, then moves the cursor by `dir` (an arrow key name) from the cell.
  function submit(td, dir) {
    const form = td.querySelector("form[data-cell-form]");
    if (!form || busy(td)) return;
    const token = form.querySelector("input[name=csrfmiddlewaretoken]");
    const table = td.closest("table[data-grid]");
    const pos = posOf(td);
    td.classList.add("opacity-50");
    fetch(td.dataset.edit, {
      method: "POST",
      body: new FormData(form),
      credentials: "same-origin",
      headers: { "X-CSRFToken": token ? token.value : "" },
    })
      .then((r) => {
        if (sessionLost(r)) return null; // the login page: the editor stays with the typed value
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.text();
      })
      .then((html) => {
        if (editing !== td) return;
        if (html === null) return showSaveError(td, form, LOGIN_MSG);
        const tpl = document.createElement("template");
        tpl.innerHTML = html;
        td.classList.remove("opacity-50");
        const value = tpl.content.querySelector("[data-cell-value]");
        if (!value) {
          if (!tpl.content.querySelector("form[data-cell-form]")) return showSaveError(td, form, SAVE_FAIL);
          // the editor again, with the server's error under the field
          mountEditor(td, tpl.content);
          focusField(td);
          return;
        }
        editing = null;
        delete td.dataset.saved;
        td.removeAttribute("title");
        td.classList.remove("is-popped");
        td.textContent = value.textContent;
        const next = pos ? move(pos, dir, bodyRows(table).map((tr) => tr.cells.length)) : null;
        activate((next && cellAt(table, next.r, next.c)) || td, false);
      })
      .catch(() => {
        // a network or server failure while saving: the editor stays open with the typed value, Enter retries
        if (editing !== td) return;
        showSaveError(td, form, SAVE_FAIL);
      });
  }

  // While an editor is open only its own keys are handled: Enter saves and moves down, Tab saves and moves to the next
  // cell (Shift+Tab to the previous one, wrapping rows like Tab does), Esc cancels. Everything else (typing, arrows) goes to the field.
  function editorKey(e) {
    const td = editing;
    if (!td.contains(e.target) || e.isComposing) return;
    if (e.key === "Escape") {
      if (!busy(td)) cancelEdit();
      e.preventDefault();
      return;
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      setMany();
      return;
    }
    if (!e.target.closest("form[data-cell-form]") || (e.key !== "Enter" && e.key !== "Tab")) return;
    e.preventDefault(); // the form must never submit natively
    if (busy(td)) return;
    submit(td, e.key === "Enter" ? "ArrowDown" : e.shiftKey ? "ShiftTab" : "Tab");
  }

  // ---- Bulk edit (phase 3, D-080) ----
  // Each action is first a dry run on the server (apply: false). The preview bar shows «N нүд өөрчлөгдөнө · M алдаатай
  // · K засах боломжгүй»; Хадгалах sends the changed cells with apply: true, Буцаах sends the old texts back the same way.

  const PENDING = "is-cell-pending";
  const REJECTED = "is-cell-rejected";
  const BAR = "selection-bar mb-1 flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-sm";
  const BTN = "rounded-lg border border-slate-300 bg-surface px-3 py-1.5 text-slate-800 hover:bg-slate-50";
  const BTN_MAIN = "rounded-lg bg-violet-700 px-3 py-1.5 text-white hover:bg-violet-800";
  const NET_FAIL = "Холбогдож чадсангүй. Дахин оролдоно уу.";
  const UNDO_MS = 4000;

  // CSRF token, read as report_select.js does: the cookie first, the hx-headers JSON on <body> as the fallback.
  function csrfToken() {
    const m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    try {
      return JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRFToken"] || "";
    } catch (err) {
      return "";
    }
  }

  // A preview whose table left the page (an htmx swap) has nothing left to restore: forget it.
  function dropPreview() {
    if (preview && !preview.table.isConnected) {
      clearTimeout(preview.timer);
      if (preview.bar) preview.bar.remove();
      preview = null;
    }
  }

  // The selection as a box: the Shift range when one started in this table, else the cursor cell.
  function selectionBox(p) {
    return anchor && anchor.table === p.table ? box(anchor, p) : box(p, p);
  }

  // The cells of a plan that the server may take: editable cells (td[data-edit]). Other cells are counted as skipped.
  // A correction cell (td[data-correct], D-080 phase 4) needs a reason, so the bulk edit skips it too. A list row cell
  // (td[data-row-edit], D-080 follow-up: children and contacts) is skipped for now: its key is per row, not per person.
  // Cells past a row's width are not in the table and are ignored.
  function targetsOf(table, cells) {
    const rows = bodyRows(table);
    const list = [];
    const seen = new Set();
    let skipped = 0;
    cells.forEach(({ r, c, text }) => {
      const row = rows[r];
      const td = row && row.cells[c];
      if (!td) return;
      if (!td.dataset.edit || td.hasAttribute("data-correct") || td.hasAttribute("data-row-edit")) {
        skipped += 1;
        return;
      }
      const q = new URL(td.dataset.edit, location.href).searchParams;
      const person = Number(q.get("person"));
      const field = q.get("field") || "";
      const key = person + "|" + field;
      if (seen.has(key)) { // the same employee field twice in one plan: one target, so the outcomes map 1:1
        skipped += 1;
        return;
      }
      seen.add(key);
      list.push({ key, td, person, field, req: text, old: cellText(td).trim() });
    });
    return { list, skipped };
  }

  // One cell as the server takes it for a save or a dry run.
  function toCell(e) {
    return { person: e.person, field: e.field, text: e.req, old: e.old };
  }

  // The server's outcomes, matched back to the cells by person|field.
  function outcomesByKey(cells) {
    const map = new Map();
    if (Array.isArray(cells)) cells.forEach((o) => { if (o) map.set(o.person + "|" + o.field, o); });
    return map;
  }

  // POSTs a batch. Resolves with the server's answer; rejects with the message to show (the server's error, or the
  // network text). A session that ended rejects with `lost` set.
  async function postBulk(url, apply, cells) {
    let r;
    try {
      r = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrfToken() },
        body: JSON.stringify({ apply, cells }),
      });
    } catch (err) {
      throw new Error(NET_FAIL);
    }
    if (sessionLost(r)) {
      const lost = new Error(LOGIN_MSG);
      lost.lost = true;
      throw lost;
    }
    let data = null;
    try {
      data = await r.json();
    } catch (err) {
      data = null;
    }
    if (!r.ok) throw new Error((data && data.error) || NET_FAIL);
    if (!data || !Array.isArray(data.cells)) throw new Error(NET_FAIL);
    return data;
  }

  // A cell back to what it was before the preview: its own HTML and title.
  function restoreEntry(e) {
    e.td.innerHTML = e.html;
    unmark(e);
  }

  // Drops the preview marks; the title goes back to the cell's own.
  function unmark(e) {
    e.td.classList.remove(PENDING, REJECTED);
    if (e.title === null) e.td.removeAttribute("title");
    else e.td.setAttribute("title", e.title);
  }

  function markRejected(e) {
    e.td.classList.add(REJECTED);
    e.td.title = e.error;
  }

  // Shows the bar (created once, above the table's frame) with a message and buttons; the first button gets focus.
  // A button is {label, main, run}.
  function showBar(st, message, buttons) {
    if (!st.bar) {
      st.bar = document.createElement("div");
      st.bar.className = BAR;
      st.bar.setAttribute("role", "status");
      const frame = st.table.closest(".ptable") || st.table;
      frame.parentNode.insertBefore(st.bar, frame);
    }
    const text = document.createElement("span");
    text.textContent = message;
    const kids = [text];
    buttons.forEach((b) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = b.main ? BTN_MAIN : BTN;
      btn.textContent = b.label;
      btn.addEventListener("click", b.run);
      kids.push(btn);
    });
    st.bar.replaceChildren(...kids);
    const first = st.bar.querySelector("button");
    if (first) first.focus();
  }

  // Closes the bar. Cells not saved go back to their own HTML; saved cells keep the saved text.
  function finish(st) {
    if (preview !== st) return;
    clearTimeout(st.timer);
    st.entries.forEach((e) => { if (e.state !== "saved") restoreEntry(e); });
    st.bar.remove();
    preview = null;
    const cur = st.table.querySelector("td." + ACTIVE);
    if (cur && st.table.isConnected) cur.focus();
  }

  // Asks the server to check the cells (dry run) and shows the preview. Only one preview at a time; a plan with no
  // editable cell does nothing.
  async function startBulk(table, cells) {
    if (preview || !table.dataset.bulkUrl) return;
    const { list, skipped } = targetsOf(table, cells);
    if (!list.length) {
      // every target was skipped (correction cells, non-editable cells): say so, so Delete on them is not silent
      if (!skipped || preview) return;
      const none = { table, bar: null, phase: "preview", entries: new Map(), timer: 0 };
      preview = none;
      showBar(none, `0 нүд өөрчлөгдөнө · 0 алдаатай · ${skipped} засах боломжгүй`, [
        { label: "Хаах", main: true, run: () => finish(none) },
      ]);
      return;
    }
    const st = { table, bar: null, phase: "busy", entries: new Map(), timer: 0 };
    preview = st;
    showBar(st, "Шалгаж байна…", []);
    let data;
    try {
      data = await postBulk(table.dataset.bulkUrl, false, list.map(toCell));
    } catch (err) {
      if (preview !== st) return;
      st.phase = "error";
      showBar(st, err.message, [{ label: "Хаах", main: true, run: () => finish(st) }]);
      return;
    }
    if (preview !== st) return;
    const got = outcomesByKey(data.cells);
    list.forEach((x) => {
      const o = got.get(x.key);
      const ok = !!(o && o.ok);
      const e = Object.assign({}, x, {
        ok,
        text: ok ? o.text || "" : "",
        error: ok ? "" : (o && o.error) || NET_FAIL,
        state: "",
        html: x.td.innerHTML,
        title: x.td.getAttribute("title"),
      });
      e.changed = ok && e.text !== e.old;
      st.entries.set(x.key, e);
      if (e.changed) {
        e.td.textContent = e.text;
        e.td.classList.add(PENDING);
      } else if (!ok) {
        markRejected(e);
      }
    });
    let changed = 0;
    let rejected = 0;
    st.entries.forEach((e) => {
      if (e.changed) changed += 1;
      if (!e.ok) rejected += 1;
    });
    st.phase = "preview";
    showBar(
      st,
      `${changed} нүд өөрчлөгдөнө · ${rejected} алдаатай · ${skipped} засах боломжгүй`,
      changed
        ? [{ label: "Хадгалах", main: true, run: () => saveBulk(st) }, { label: "Болих", run: () => finish(st) }]
        : [{ label: "Хаах", main: true, run: () => finish(st) }]
    );
  }

  // Хадгалах: the changed cells are saved, one by one on the server. A saved cell shows its saved text; a refused one
  // goes back to its own text and stays red with the reason.
  async function saveBulk(st) {
    if (preview !== st || st.phase !== "preview") return;
    const todo = [...st.entries.values()].filter((e) => e.changed);
    if (!todo.length) return;
    st.phase = "busy";
    showBar(st, "Хадгалж байна…", []);
    let data;
    try {
      data = await postBulk(st.table.dataset.bulkUrl, true, todo.map(toCell));
    } catch (err) {
      if (preview !== st) return;
      st.entries.forEach(restoreEntry);
      st.entries.clear();
      st.phase = "error";
      showBar(st, err.message, [{ label: "Хаах", main: true, run: () => finish(st) }]);
      return;
    }
    if (preview !== st) return;
    const got = outcomesByKey(data.cells);
    let saved = 0;
    todo.forEach((e) => {
      const o = got.get(e.key);
      if (o && o.ok) {
        e.state = "saved";
        e.text = o.text || "";
        saved += 1;
        e.td.textContent = e.text;
        unmark(e);
      } else {
        e.state = "failed";
        e.error = (o && o.error) || NET_FAIL;
        restoreEntry(e);
        markRejected(e);
      }
    });
    let notSaved = 0;
    st.entries.forEach((e) => { if (!e.ok || e.state === "failed") notSaved += 1; });
    st.phase = "saved";
    const message = `${saved} нүд хадгалагдлаа` + (notSaved ? ` · ${notSaved} хадгалагдсангүй` : "");
    const buttons = [];
    if (saved) buttons.push({ label: "Буцаах", run: () => undoBulk(st) });
    buttons.push({ label: "Хаах", run: () => finish(st) });
    showBar(st, message, buttons);
  }

  // Буцаах: the saved cells get their old texts back (same rules: a stale cell is refused).
  async function undoBulk(st) {
    if (preview !== st || st.phase !== "saved") return;
    const todo = [...st.entries.values()].filter((e) => e.state === "saved");
    if (!todo.length) return;
    st.phase = "busy";
    showBar(st, "Буцааж байна…", []);
    let data;
    try {
      data = await postBulk(
        st.table.dataset.bulkUrl,
        true,
        todo.map((e) => ({ person: e.person, field: e.field, text: e.old, old: e.text }))
      );
    } catch (err) {
      if (preview !== st) return;
      if (err.lost) { // nothing was undone; the saved cells keep their saved text when the bar closes
        st.phase = "error";
        showBar(st, err.message, [{ label: "Хаах", main: true, run: () => finish(st) }]);
        return;
      }
      st.phase = "saved";
      showBar(st, err.message, [
        { label: "Буцаах", run: () => undoBulk(st) },
        { label: "Хаах", run: () => finish(st) },
      ]);
      return;
    }
    if (preview !== st) return;
    const got = outcomesByKey(data.cells);
    let undone = 0;
    todo.forEach((e) => {
      const o = got.get(e.key);
      if (o && o.ok) {
        restoreEntry(e);
        e.state = "undone";
        undone += 1;
      }
    });
    const left = todo.length - undone;
    st.phase = "undone";
    showBar(st, `Буцаалаа: ${undone}` + (left ? ` · ${left} буцаагдсангүй` : ""), [
      { label: "Хаах", run: () => finish(st) },
    ]);
    st.timer = setTimeout(() => finish(st), UNDO_MS);
  }

  // Keys while a preview is open: Enter saves (from the grid, while the preview waits), Esc closes it (Болих, or the
  // closing of a finished bar; nothing while a request is in flight). The grid's own keys are blocked; the bar's
  // buttons keep their normal keys.
  function previewKey(e) {
    const st = preview;
    const inGrid = !!(e.target.closest && e.target.closest("table[data-grid]"));
    if (e.key === "Escape") {
      e.preventDefault();
      if (st.phase !== "busy") finish(st);
      return;
    }
    if (e.key === "Enter" && st.phase === "preview" && inGrid) {
      e.preventDefault();
      saveBulk(st);
      return;
    }
    if (inGrid) e.preventDefault();
  }

  // Ctrl+Enter in an open editor: the typed value goes to every editable cell of the range (the editor's own cell too).
  function setMany() {
    const td = editing;
    if (!td || busy(td)) return;
    const p = posOf(td);
    if (!p) return;
    const field = td.querySelector("form[data-cell-form] [name]:not([type=hidden])");
    let text = "";
    if (field && field.tagName === "SELECT") { // the blank choice is "no value", not its «---------» label
      const opt = field.selectedOptions[0];
      text = field.value === "" || !opt ? "" : opt.textContent;
    } else if (field) {
      text = field.value;
    }
    const range = selectionBox(p);
    restore(td);
    startBulk(p.table, planSet(range, text.trim()));
  }

  // Ctrl+V on a grid cell: the clipboard's rows and cells are laid from the cursor (a single value fills a Shift range).
  document.addEventListener("paste", (e) => {
    dropDetached();
    if (editing || preview) return;
    const td = e.target.closest && e.target.closest("table[data-grid] tbody td");
    if (!td || isField(e.target)) return;
    const p = posOf(td);
    if (!p) return;
    const text = e.clipboardData ? e.clipboardData.getData("text/plain") : "";
    if (!text) return;
    e.preventDefault();
    const widths = bodyRows(p.table).map((tr) => tr.cells.length);
    startBulk(p.table, planPaste(p, parseTsv(text), widths, anchor && anchor.table === p.table ? box(anchor, p) : null));
  });

  // A click on a body cell puts the cursor there (the click still does what it did before: link, row tick).
  document.addEventListener("mousedown", (e) => {
    if (editing && editing.contains(e.target)) return; // a click inside the open editor belongs to the editor
    if (editing) cancelEdit();
    const td = e.target.closest && e.target.closest("table[data-grid] tbody td");
    if (!td) return;
    if (e.shiftKey) {
      const cur = document.activeElement && document.activeElement.closest && document.activeElement.closest("td." + ACTIVE);
      const from = cur && posOf(cur);
      if (from && from.table === td.closest("table")) { anchor = anchor || from; activate(td, true); e.preventDefault(); return; }
    }
    anchor = null;
    activate(td, false);
  }, true);

  // Double-click opens the editor of an editable cell.
  document.addEventListener("dblclick", (e) => {
    const td = e.target.closest && e.target.closest("table[data-grid] tbody td[data-edit]");
    if (!td || (e.target !== td && isField(e.target))) return;
    startEdit(td);
  });

  // Tab into a table from above lands on the first cell.
  document.addEventListener("focusin", (e) => {
    const table = e.target.matches && e.target.matches("table[data-grid]") ? e.target : null;
    if (!table) return;
    const first = table.querySelector("td." + ACTIVE) || cellAt(table, 0, 0);
    if (first) activate(first, false);
  });

  document.addEventListener("keydown", (e) => {
    dropDetached();
    if (editing && loading) { if (editing.contains(e.target)) bufferKey(e); return; }
    if (editing) { editorKey(e); return; }
    if (preview) { previewKey(e); return; }
    const td = e.target.closest && e.target.closest("table[data-grid] tbody td");
    if (!td || (e.target !== td && isField(e.target))) return;
    const p = posOf(td);
    if (!p) return;
    const ctrl = e.ctrlKey || e.metaKey;

    if (ctrl && (e.key === "c" || e.key === "C")) {
      if (window.getSelection && String(window.getSelection()).length) return; // the user selected text: let the browser copy it
      copy(p.table, p);
      e.preventDefault();
      return;
    }
    if (ctrl && (e.key === "d" || e.key === "D")) { // fill down: the top row's text goes to the cells below it
      e.preventDefault();
      const table = p.table;
      startBulk(table, planFill(selectionBox(p), (r, c) => cellText(cellAt(table, r, c)).trim()));
      return;
    }
    if (e.key === "Delete" && !ctrl) { // clear: every editable cell of the range becomes empty
      e.preventDefault();
      startBulk(p.table, planSet(selectionBox(p), ""));
      return;
    }
    if (e.key === "Escape") { anchor = null; clearMarks(p.table); return; }
    if (e.key === " ") {
      const box = td.parentElement.querySelector("input[type=checkbox]");
      if (box) { box.click(); e.preventDefault(); }
      return;
    }
    if (e.key === "Enter") {
      if (td.dataset.edit) { if (startEdit(td)) e.preventDefault(); return; }
      const link = td.querySelector("a[href]") || td.parentElement.querySelector("a[href]");
      if (link) { link.click(); e.preventDefault(); }
      return;
    }
    if (e.key === "F2") {
      if (td.dataset.edit) { if (startEdit(td)) e.preventDefault(); }
      else noEditHere(p.table);
      return;
    }
    if (td.dataset.edit && isPrintable(e)) { if (startEdit(td, e.key)) e.preventDefault(); return; }

    const key = e.key === "Tab" && e.shiftKey ? "ShiftTab" : e.key;
    const widths = bodyRows(p.table).map((tr) => tr.cells.length);
    const next = move(p, key, widths, ctrl);
    if (!next) return;
    if (key === "Tab" || key === "ShiftTab") {
      if (next.r === p.r && next.c === p.c) return; // the edge: let Tab leave the table
    }
    const range = e.shiftKey && key.startsWith("Arrow");
    if (range && !anchor) anchor = p;
    const target = cellAt(p.table, next.r, next.c);
    if (target) activate(target, range);
    e.preventDefault();
  });

  // ---- Editable-column marks (UI_RULES §4b) ----
  // A column is marked when a body cell in it is editable (data-edit) or a correction (data-correct). Everything is
  // derived here from the DOM (the server's attributes already reflect the viewer's rights), so no server change.
  // The choice is kept in localStorage hr.editMarks ("1" on, "0" off; on by default).
  const EDIT_KEY = "hr.editMarks";
  const MARK_EDIT = "col-edit";
  const MARK_CORRECT = "col-correct";
  const TITLE_EDIT = "Шууд засна: нүдээ сонгоод F2, давхар товших эсвэл бичих";
  const TITLE_CORRECT = "Засвар: шалтгаантай";
  const NO_EDIT_MSG = "Энэ баганыг эндээс засах боломжгүй";
  const NOTE_MS = 3000;
  let noteTimer = null;

  function marksOn() {
    try { return localStorage.getItem(EDIT_KEY) !== "0"; } catch (err) { return true; }
  }

  function setMarksOn(on) {
    try { localStorage.setItem(EDIT_KEY, on ? "1" : "0"); } catch (err) { /* no storage: the choice lasts this page only */ }
  }

  // The kind of every column of a table, from all its body rows (hidden rows and «Цааш харуулах» batches included).
  function kindsOf(table) {
    const rows = Array.from(table.tBodies).flatMap((tb) => Array.from(tb.rows)).map((tr) =>
      Array.from(tr.cells, (td) => ({ edit: !!td.dataset.edit, correct: td.hasAttribute("data-correct") })));
    return columnKinds(rows);
  }

  // The frame the legend and the note sit above: the .ptable, or the scroll host scrollbars.js wraps it in.
  function frameOf(table) {
    const frame = table.closest(".ptable") || table;
    return frame.parentElement && frame.parentElement.classList.contains("sbar-host") ? frame.parentElement : frame;
  }

  function slotOf(table, attr) {
    const frame = frameOf(table);
    return { frame, parent: frame.parentNode, old: frame.parentNode.querySelector(":scope > [" + attr + "]") };
  }

  // Puts the mark on one cell (its column kind, when marks are on) and the header's title. A spanning cell gets none.
  function markCell(td, kind, on) {
    const want = on && td.colSpan <= 1 ? kind : "";
    const had = td.classList.contains(MARK_EDIT) || td.classList.contains(MARK_CORRECT);
    td.classList.toggle(MARK_EDIT, want === "edit");
    td.classList.toggle(MARK_CORRECT, want === "correct");
    if (td.tagName !== "TH") return;
    if (want === "edit") td.title = TITLE_EDIT;
    else if (want === "correct") td.title = TITLE_CORRECT;
    else if (had) td.removeAttribute("title");
  }

  function swatch(cls) {
    const s = document.createElement("span");
    s.className = cls;
    s.setAttribute("aria-hidden", "true");
    return s;
  }

  function legendItem(cls, text) {
    const item = document.createElement("span");
    item.className = "inline-flex items-center";
    item.append(swatch(cls), document.createTextNode(text));
    return item;
  }

  function makeLegend(withCorrect) {
    // An outer grid row that animates 0fr <-> 1fr (input.css .edit-legend), so opening pushes the table down smoothly;
    // the inner block clips the content while the row is short.
    const legend = document.createElement("div");
    legend.setAttribute("data-edit-legend", "");
    legend.dataset.correct = withCorrect ? "1" : "0";
    legend.className = "edit-legend";
    const inner = document.createElement("div");
    inner.className = "flex flex-wrap items-center gap-x-4 gap-y-1 pb-1 text-xs text-slate-600";
    inner.append(legendItem("edit-swatch", "Шууд засна (F2, давхар товших, бичих)"));
    if (withCorrect) inner.append(legendItem("correct-swatch", "Засвар — шалтгаантай"));
    const keys = document.createElement("span");
    keys.textContent = "Ctrl+V буулгах · Ctrl+D доош хуулах";
    inner.append(keys);
    legend.append(inner);
    return legend;
  }

  // The legend is shown only when the marks are on and the table has a marked column. A legend already in place is kept
  // (htmx swaps re-run this, and the table must not jump); `animate` is true only for the toggle button.
  function syncLegend(table, show, withCorrect, animate) {
    const { frame, parent, old } = slotOf(table, "data-edit-legend");
    const want = withCorrect ? "1" : "0";
    if (show) {
      if (old && !old.classList.contains("is-closing") && old.dataset.correct === want) return;
      if (old) old.remove();
      const legend = makeLegend(withCorrect);
      if (animate) legend.classList.add("is-closed");
      parent.insertBefore(legend, frame);
      if (animate) {
        void legend.offsetHeight; // lay out the closed state first, so removing the class transitions to open
        legend.classList.remove("is-closed");
      }
    } else if (old) {
      if (!animate) { old.remove(); return; }
      old.classList.add("is-closing", "is-closed");
      const done = () => old.remove();
      old.addEventListener("transitionend", done, { once: true });
      setTimeout(done, 400); // reduced motion or no transition: still removed
    }
  }

  // The note's line stays in place (a live region must already exist to be read out); only its text comes and goes.
  function syncNote(table, editable) {
    const { frame, parent, old } = slotOf(table, "data-edit-note");
    if (editable && !old) {
      const note = document.createElement("div");
      note.setAttribute("data-edit-note", "");
      note.setAttribute("role", "status");
      note.className = "mb-1 text-xs text-slate-700";
      parent.insertBefore(note, frame);
    } else if (!editable && old) {
      old.remove();
    }
  }

  // Applies the marks of one table, its legend and its note; a copy of the header that report_sticky.js made gets the
  // same marks. Returns true when the table has an editable column.
  function applyMarks(table, animate) {
    const on = marksOn();
    const kinds = kindsOf(table);
    const editable = kinds.some((k) => k !== "");
    table.classList.toggle("edit-marks", on);
    Array.from(table.rows).forEach((tr) => {
      if (tr.parentElement.tagName === "TFOOT") return; // the totals are not editable
      Array.from(tr.cells).forEach((td) => markCell(td, kinds[td.cellIndex] || "", on));
    });
    if (table.closest("#report-page")) {
      document.querySelectorAll("[data-sticky-head] thead tr").forEach((tr) => {
        Array.from(tr.cells).forEach((th) => markCell(th, kinds[th.cellIndex] || "", on));
      });
    }
    syncLegend(table, on && editable, kinds.includes("correct"), !!animate);
    syncNote(table, editable);
    return editable;
  }

  // Every table on the page, then the toggle: it shows only when a table has an editable column, and its pressed state
  // follows the choice.
  function applyAll(animate) {
    let any = false;
    document.querySelectorAll("table[data-grid]").forEach((table) => { if (applyMarks(table, animate)) any = true; });
    const on = marksOn();
    document.querySelectorAll("[data-edit-marks-toggle]").forEach((btn) => {
      btn.hidden = !any;
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  // F2 or a double-click on a cell that cannot be edited: the table's note says so for 3 s. Silent when the table has no
  // editable column.
  function noEditHere(table) {
    if (!table || !kindsOf(table).some((k) => k !== "")) return;
    const { old } = slotOf(table, "data-edit-note");
    if (!old) return;
    old.textContent = NO_EDIT_MSG;
    clearTimeout(noteTimer);
    noteTimer = setTimeout(() => { old.textContent = ""; }, NOTE_MS);
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest && e.target.closest("[data-edit-marks-toggle]");
    if (!btn) return;
    setMarksOn(!marksOn());
    applyAll(true);
  });

  document.addEventListener("dblclick", (e) => {
    const td = e.target.closest && e.target.closest("table[data-grid] tbody td");
    if (!td || td.dataset.edit || (e.target !== td && isField(e.target))) return;
    noEditHere(td.closest("table[data-grid]"));
  });

  document.addEventListener("htmx:afterSwap", () => applyAll(false));
  document.addEventListener("htmx:afterSettle", () => applyAll(false));
  applyAll(); // the page as it loaded (this script is deferred, so the DOM is ready)
})();
