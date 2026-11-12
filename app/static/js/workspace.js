// Row ticks and copy on the workspace table (assistant workspace, docs/UI_RULES.md §4b). The table pane is swapped by htmx;
// every swap re-reads the DOM, so nothing is kept in the page except the «all rows» flag, which resets with the table.
// Ticks copy the drawn rows here, in the browser. «Бүх M мөр» (the header box plus the link) uses the server: Хуулах
// fetches the TSV from the copy address, and Excel and print are the export links with the same address.
// The pure helpers are exported under Node (workspace.test.mjs); in the browser only the DOM wiring runs.
(function () {
  "use strict";

  const NETWORK_MSG = "Холбогдож чадсангүй. Дахин оролдоно уу.";
  const FAILED_MSG = "Татаж чадсангүй. Дахин оролдоно уу.";
  const COPY_FAILED = "Хуулж чадсангүй.";
  const CHAT_FAILED_MSG = "Алдаа гарлаа. Дахин оролдоно уу.";
  const NOTE_MS = 4000;

  // ---- Pure helpers (no DOM) ----

  // The edge characters a copied cell loses: one explicit set, identical to ws_excel.py (COPY_EDGE); trim() and strip()
  // defaults differ between the two languages, so neither is used.
  const COPY_EDGE = /^[ \t\r\n\u00a0\ufeff\u2028\u2029\x1c-\x1f\x85]+|[ \t\r\n\u00a0\ufeff\u2028\u2029\x1c-\x1f\x85]+$/g;

  // One copied cell: line breaks and tabs become spaces, the edge characters go, and then a cell that starts with
  // = + - or @ gets one single quote in front, so Excel reads the paste as text. The rule is applied to the cleaned
  // text, so no whitespace or line break can hide the start. The same steps are in ws_excel.py (copy_clean, formula_safe).
  function cleanCell(text) {
    const out = String(text == null ? "" : text).replace(/[\t\r\n]+/g, " ").replace(COPY_EDGE, "");
    return /^[=+\-@]/.test(out) ? "'" + out : out;
  }

  // The header line and the rows as tab-separated text, one line each.
  function tsvText(headers, rows) {
    const lines = [headers.map(cleanCell).join("\t")];
    rows.forEach((row) => lines.push(row.map(cleanCell).join("\t")));
    return lines.join("\n");
  }

  // The bar's count line: «N мөр сонгосон», or with every matching row «M мөр сонгосон (бүгд)».
  function countLabel(n, all) {
    return all ? n + " мөр сонгосон (бүгд)" : n + " мөр сонгосон";
  }

  // The «Бүх M мөрийг сонгох» link is offered when the header box holds every drawn row and more rows match.
  function moreOffered(all, headerChecked, drawn, total, hasCopyUrl) {
    return !all && headerChecked && hasCopyUrl && total > drawn;
  }

  const helpers = { cleanCell, tsvText, countLabel, moreOffered };
  if (typeof module !== "undefined" && module.exports) module.exports = helpers;
  if (typeof document === "undefined") return;

  // ---- Page wiring ----

  let all = false; // every matching row is selected (server copy and the export links)
  let table = null; // the table element the flag belongs to; a new element (a swap) starts again
  let noteTimer = 0;

  function bar() {
    return document.querySelector("[data-ws-bar]");
  }

  function currentTable() {
    return document.querySelector("[data-ws-table]");
  }

  // The data rows of the table: the ones with a tick box (the «Олдсонгүй» row has none).
  function dataRows(t) {
    return Array.from(t.querySelectorAll("tbody tr")).filter((r) => r.querySelector("input[data-ws-row]"));
  }

  function boxOf(row) {
    return row.querySelector("input[data-ws-row]");
  }

  function ticked(t) {
    return dataRows(t).filter((r) => boxOf(r).checked);
  }

  // The column names without the tick column and without the sort arrow.
  function headerNames(t) {
    return Array.from(t.querySelectorAll("thead th"))
      .slice(1)
      .map((th) => th.textContent.replace(/\s*[↑↓]\s*$/, ""));
  }

  function cellTexts(row) {
    return Array.from(row.querySelectorAll("td"))
      .slice(1)
      .map((td) => td.textContent);
  }

  function showMessage(text, isError) {
    const b = bar();
    const msg = b && b.querySelector("[data-ws-msg]");
    if (!msg) return;
    clearTimeout(noteTimer);
    msg.textContent = text;
    msg.hidden = false;
    msg.classList.toggle("text-red-700", isError);
    msg.classList.toggle("text-slate-700", !isError);
    if (!isError) noteTimer = setTimeout(clearNote, NOTE_MS);
  }

  function clearNote() {
    clearTimeout(noteTimer);
    const b = bar();
    const msg = b && b.querySelector("[data-ws-msg]");
    if (msg) {
      msg.textContent = "";
      msg.hidden = true;
    }
  }

  // Re-paints the bar from the table: the header box, the count, the link and the server-only actions.
  function sync() {
    const t = currentTable();
    if (t !== table) {
      table = t;
      all = false;
      clearNote();
    }
    const b = bar();
    if (!t || !b) return;
    const rows = dataRows(t);
    rows.forEach((r) => r.classList.toggle("is-picked", boxOf(r).checked)); // the navy tint and edge bar (input.css)
    const n = rows.filter((r) => boxOf(r).checked).length;
    // The header box, and the «Бүгдийг сонгох» box shown on a phone, where the header row is hidden.
    const headers = Array.from(document.querySelectorAll("#ws-table-pane input[data-ws-all]"));
    const header = headers[0];
    headers.forEach((box) => {
      box.checked = rows.length > 0 && n === rows.length;
      box.indeterminate = n > 0 && n < rows.length;
    });
    const total = b.dataset.total === "" ? 0 : Number(b.dataset.total);
    const offer = moreOffered(all, !!(header && header.checked), rows.length, total, !!b.dataset.copyUrl);
    const more = b.querySelector("[data-ws-more]");
    if (more) more.hidden = !offer;
    b.hidden = !(all || n > 0);
    const count = b.querySelector("[data-ws-count]");
    if (count) count.textContent = countLabel(all ? total : n, all);
    // Excel and print cover every row, so they are offered only for all matching rows (rows have no stable ids).
    ["[data-ws-excel]", "[data-ws-print]"].forEach((sel) => {
      const link = b.querySelector(sel);
      if (link) link.hidden = !all;
    });
    // Selection mode, as on report tables: while a row is ticked, a click anywhere on a row toggles it (input.css).
    if (all || n > 0) document.body.dataset.wsSelecting = "1";
    else delete document.body.dataset.wsSelecting;
  }

  function cancelSelection() {
    const t = currentTable();
    if (t) dataRows(t).forEach((r) => {
      boxOf(r).checked = false;
    });
    all = false;
    clearNote();
    sync();
  }

  // In selection mode a click on a row (not on its own tick box) toggles that row; links in the row are swallowed.
  document.addEventListener(
    "click",
    (e) => {
      if (!document.body.dataset.wsSelecting) return;
      const target = e.target instanceof Element ? e.target : null;
      const row = target && target.closest("#ws-table-pane tbody tr");
      const box = row && boxOf(row);
      if (!box || target.closest("input, label")) return;
      e.preventDefault();
      e.stopPropagation();
      box.checked = !box.checked;
      all = false;
      sync();
    },
    true,
  );

  // Escape leaves selection mode, unless a menu is open (that Escape closes the menu) or the key was already used.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.defaultPrevented || !document.body.dataset.wsSelecting) return;
    if (document.querySelector("details[data-ws-menu][open], #ws-table-pane details[open]")) return;
    cancelSelection();
  });

  // The fallback copy for a browser without the clipboard API (or outside a secure page).
  function fallbackCopy(text) {
    const area = document.createElement("textarea");
    area.value = text;
    area.readOnly = true;
    area.className = "sr-only";
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (err) {
      ok = false;
    }
    area.remove();
    return ok;
  }

  function writeClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(() => true, () => fallbackCopy(text));
    }
    return Promise.resolve(fallbackCopy(text));
  }

  // The server answers a refusal with a short plain-text Mongolian line; anything else gets the generic one.
  async function errorText(r) {
    const plain = (r.headers.get("Content-Type") || "").indexOf("text/plain") === 0;
    const text = plain ? (await r.text()).trim() : "";
    return text || FAILED_MSG;
  }

  async function copyTicked() {
    const t = currentTable();
    const picked = ticked(t);
    const text = tsvText(headerNames(t), picked.map(cellTexts));
    const ok = await writeClipboard(text);
    if (ok) showMessage("Хууллаа: " + picked.length + " мөр", false);
    else showMessage(COPY_FAILED, true);
  }

  async function copyAll(url) {
    const r = await fetch(url, { credentials: "same-origin" });
    if (r.redirected) {  // the session ended: the login page came back instead of the text
      window.location.reload();
      return;
    }
    if (!r.ok) {
      showMessage(await errorText(r), true);
      return;
    }
    const text = await r.text();
    const lines = Math.max(0, text.split("\n").length - 1); // the header line is not a row
    const cut = r.headers.get("X-Cut") === "1" ? " · эхний хэсгийг хууллаа" : "";
    const ok = await writeClipboard(text);
    if (ok) showMessage("Хууллаа: " + lines + " мөр" + cut, false);
    else showMessage(COPY_FAILED, true);
  }

  function copy() {
    const b = bar();
    const job = all && b.dataset.copyUrl ? copyAll(b.dataset.copyUrl) : copyTicked();
    job.catch(() => showMessage(NETWORK_MSG, true));
  }

  // ---- Events ----

  // A tick box in the table, or the header box. Any change of one row leaves the all-rows mode.
  document.addEventListener("change", (e) => {
    const target = e.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (target.matches("[data-ws-all]")) {
      const t = currentTable();
      if (!t) return;
      dataRows(t).forEach((r) => {
        boxOf(r).checked = target.checked;
      });
      all = false;
    } else if (target.matches("[data-ws-row]")) {
      all = false;
    } else {
      return;
    }
    sync();
  });

  document.addEventListener("click", (e) => {
    const b = bar();
    const target = e.target instanceof Element ? e.target : null;
    if (!b || !target || !target.closest("[data-ws-bar]")) return;
    if (target.closest("[data-ws-more]")) {
      all = true;
      sync();
    } else if (target.closest("[data-ws-cancel]")) {
      cancelSelection();
    } else if (target.closest("[data-ws-copy]")) {
      copy();
    }
  });

  // ---- Chat pane: what the viewer sees while a line or an undo is on its way ----

  let chatBusy = false; // a request from the chat pane (a line or an undo) is on its way
  let sentText = ""; // the line that was sent, put back in the box when the request fails

  function chatPane() {
    return document.getElementById("ws-chat-pane");
  }

  function askInput() {
    const pane = chatPane();
    return pane && pane.querySelector("form[data-ws-ask] input[name=q]");
  }

  // The sent line and a «working» line go into the log at once; the box empties and locks until the answer comes.
  function showPending(form) {
    const pane = chatPane();
    const input = form.querySelector("input[name=q]");
    const log = pane && pane.querySelector("#ws-chat-log");
    const tpl = pane && pane.querySelector("template[data-ws-pending-tpl]");
    if (!input || !log || !tpl) return;
    sentText = input.value;
    const piece = tpl.content.cloneNode(true);
    const text = piece.querySelector("[data-ws-pending-text]");
    if (text) text.textContent = sentText.trim();
    const empty = log.querySelector("[data-ws-empty]");
    if (empty) empty.hidden = true;
    log.appendChild(piece);
    log.scrollTop = log.scrollHeight;
    input.value = "";
    input.readOnly = true;
    const note = pane.querySelector("[data-ws-send-error]");
    if (note) note.hidden = true;
  }

  // The request did not come back with a pane to show: the «working» lines go, the line returns to the box.
  function chatFailed(message) {
    const pane = chatPane();
    if (!pane || !chatBusy) return;
    chatBusy = false;
    pane.removeAttribute("aria-busy");
    pane.querySelectorAll("[data-ws-pending]").forEach((el) => el.remove());
    const empty = pane.querySelector("[data-ws-empty]");
    if (empty) empty.hidden = false;
    const input = askInput();
    if (input) {
      input.readOnly = false;
      if (sentText) input.value = sentText;
      input.focus();
    }
    sentText = "";
    const note = pane.querySelector("[data-ws-send-error]");
    if (note) {
      note.textContent = message;
      note.hidden = false;
    }
  }

  document.addEventListener("htmx:beforeRequest", (e) => {
    const form = e.target instanceof Element ? e.target.closest("form[data-ws-ask], form[data-ws-undo]") : null;
    const pane = chatPane();
    if (!form || !pane || !pane.contains(form)) return;
    chatBusy = true;
    pane.setAttribute("aria-busy", "true");
    if (form.matches("[data-ws-ask]")) showPending(form);
  });
  document.addEventListener("htmx:sendError", () => chatFailed(NETWORK_MSG));
  document.addEventListener("htmx:timeout", () => chatFailed(NETWORK_MSG));
  document.addEventListener("htmx:sendAbort", () => chatFailed(NETWORK_MSG));
  document.addEventListener("htmx:responseError", () => chatFailed(CHAT_FAILED_MSG));

  // The dock is a one-line bar until «Түүх харах» opens the log, the SQL and the hint. The state lives on the pane
  // (data-expanded), which a swap does not replace; the swapped-in button only gets its aria-expanded back.
  function syncDock() {
    const pane = chatPane();
    const button = pane && pane.querySelector("[data-ws-dock-toggle]");
    if (button) button.setAttribute("aria-expanded", pane.hasAttribute("data-expanded") ? "true" : "false");
  }
  document.addEventListener("click", (e) => {
    const button = e.target instanceof Element ? e.target.closest("[data-ws-dock-toggle]") : null;
    const pane = chatPane();
    if (!button || !pane || !pane.contains(button)) return;
    pane.toggleAttribute("data-expanded");
    syncDock();
    const log = pane.querySelector("#ws-chat-log");
    if (log) log.scrollTop = log.scrollHeight;
  });
  document.addEventListener("htmx:afterSettle", (e) => {
    if (e.target instanceof Element && e.target.id === "ws-chat-pane") syncDock();
  });

  // «Зөв гэж тэмдэглэх» (form[data-ws-verify]): one POST for the source answer; on success the button is replaced by the
  // «илгээлээ» line. A failure only enables the button again.
  document.addEventListener("submit", (e) => {
    const form = e.target instanceof Element ? e.target.closest("form[data-ws-verify]") : null;
    if (!form) return;
    e.preventDefault();
    const button = form.querySelector("button");
    if (button) button.disabled = true;
    fetch(form.action, { method: "POST", credentials: "same-origin", body: new FormData(form) })
      .then((r) => (r.ok ? r.json() : { ok: false }))
      .then((data) => {
        if (!data || !data.ok) {
          if (button) button.disabled = false;
          return;
        }
        form.hidden = true;
        const done = form.parentNode.querySelector("[data-ws-verify-done]");
        if (done) done.hidden = false;
      })
      .catch(() => {
        if (button) button.disabled = false;
      });
  });

  // ---- Table pane: keep the keyboard place after a swap, and say what changed ----

  let tableFocus = null; // what the viewer used inside the table pane: a sort column, or "pane" for any other control

  function tablePane() {
    return document.getElementById("ws-table-pane");
  }

  // The live region is outside both panes, so a swap does not replace it; an unchanged text is cleared first, so a
  // second identical answer is still announced.
  function say(text) {
    const live = document.getElementById("ws-live");
    if (!live || !text) return;
    live.textContent = "";
    setTimeout(() => {
      live.textContent = text;
    }, 50);
  }

  document.addEventListener("htmx:beforeRequest", (e) => {
    const pane = tablePane();
    const source = e.target instanceof Element ? e.target : null;
    if (!pane || !source || !pane.contains(source)) return;
    const sort = source.closest("[data-ws-sort]");
    tableFocus = sort ? { col: sort.dataset.wsSort } : { col: "" };
  });

  // Every htmx swap of the table pane (filter, sort, page, refine) starts the selection again; the bar re-paints, the
  // keyboard place comes back (the sort link of the same column, else the pane itself) and the total is said.
  // A swap of the chat pane that answers a line or an undo puts the caret back in the question box and says the reply.
  document.addEventListener("htmx:afterSettle", (e) => {
    sync();
    const table = tablePane();
    if (table && e.target === table) {
      const total = table.querySelector("[data-ws-total]");
      say(total ? total.textContent.trim() : "");
      if (tableFocus) {
        const again = tableFocus.col
          ? Array.from(table.querySelectorAll("[data-ws-sort]")).find((a) => a.dataset.wsSort === tableFocus.col)
          : null;
        if (again) again.focus();
        else {
          table.setAttribute("tabindex", "-1");
          table.focus({ preventScroll: true });
        }
        tableFocus = null;
      }
    }
    const pane = chatPane();
    if (!pane || e.target !== pane) return;
    const last = Array.from(pane.querySelectorAll("#ws-chat-log > div p")).pop();
    const zero = pane.querySelector("[role=status]");
    if (chatBusy) say([last ? last.textContent.trim() : "", zero ? zero.textContent.trim() : ""].join(" ").trim());
    if (!chatBusy) return;
    chatBusy = false;
    sentText = "";
    pane.removeAttribute("aria-busy");
    const input = askInput();
    if (input) input.focus();
  });

  // ---- Menus and tabs ----

  // An open «Үйлдэл ▾» or «Багана сонгох» panel closes with Escape (focus back on its label) and on a click outside.
  function openMenus() {
    return Array.from(document.querySelectorAll("details[data-ws-menu][open], #ws-table-pane details[open]"));
  }
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const menus = openMenus();
    if (!menus.length) return;
    const summary = menus[0].querySelector("summary");
    menus.forEach((m) => m.removeAttribute("open"));
    if (summary) summary.focus();
  });
  document.addEventListener("click", (e) => {
    const target = e.target instanceof Element ? e.target : null;
    openMenus().forEach((m) => {
      if (!target || !m.contains(target)) m.removeAttribute("open");
    });
  });

  // The current tab is scrolled into view in the strip (20 tabs do not fit).
  function showCurrentTab() {
    const current = document.querySelector("[data-ws-tabs] [aria-current]");
    if (current && current.scrollIntoView) current.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
  showCurrentTab();
  // A page shown from the browser's history may restore checkbox states: the bar follows the boxes it finds.
  window.addEventListener("pageshow", () => sync());

  sync();
})();
