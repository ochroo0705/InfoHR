// Row selection on a report page (docs/UI_RULES.md §4b; spec 2026-11-07-reports-part3-selection-design).
// Ticking a row checkbox, or clicking a row while selection is on, picks that person. The bar above the table acts on
// the picked people (Excel, CSV, print, copy, checklist). The picked ids live in one state object per page; every htmx
// swap of the rows re-paints from it, and a new #report-page (filter, sort, layout, history) starts the selection again.
// The state machine and the helpers are pure: under Node the module exports them (report_select.test.mjs); in the
// browser there is no module object, so nothing is exported and only the DOM wiring runs.
(function () {
  "use strict";

  const NETWORK_MSG = "Холбогдож чадсангүй. Дахин оролдоно уу.";
  const FAILED_MSG = "Татаж чадсангүй. Дахин оролдоно уу.";
  const NOTE_MS = 4000;
  // The class of a picked row; its lime look is in static/css/input.css (.is-picked).
  const PICKED_CLASS = "is-picked";

  // ---- Pure helpers (no DOM) ----

  // A person id as the server writes it: ASCII digits only, at most 12 of them. Anything else is ignored.
  function isPersonId(value) {
    return /^\d{1,12}$/.test(String(value));
  }

  // The selection of one page: the picked ids (strings), the all-matching flag, the #report-page it belongs to, and
  // `held`: the mode was started by the «Сонгох» toggle (not by a tick), so it stays on with nothing picked.
  function createState() {
    return { ids: new Set(), all: false, page: null, held: false };
  }

  // The mode is on while the toggle holds it, or while anything is picked.
  function isOn(s) {
    return s.held || s.all || s.ids.size > 0;
  }

  // «Сонгох»: turns the mode on with nothing picked, or off (and clears) when it is on.
  function toggleMode(s) {
    if (isOn(s)) endMode(s);
    else s.held = true;
  }

  // Esc, «Болих», the toggle's off press, a page replacement or a history restore: picks and mode both go.
  function endMode(s) {
    clearPicks(s);
    s.held = false;
  }

  function isPicked(s, id) {
    return s.all || s.ids.has(String(id));
  }

  // The header box for the rows on screen: checked when all of them are picked, indeterminate when some are.
  function headerMark(s, visible) {
    const ids = visible.filter(isPersonId);
    const picked = ids.filter((id) => isPicked(s, id)).length;
    return { checked: ids.length > 0 && picked === ids.length, indeterminate: picked > 0 && picked < ids.length };
  }

  // Ticks or unticks one person. `visible` is the ids of the rows on screen. Unticking while all matching rows are
  // selected ends that mode: the rows on screen stay picked, minus this one.
  function setRow(s, id, on, visible) {
    if (!isPersonId(id)) return;
    const key = String(id);
    if (s.all) {
      if (on) return;
      s.all = false;
      s.ids = new Set(visible.filter((x) => isPersonId(x) && String(x) !== key).map(String));
      return;
    }
    if (on) s.ids.add(key);
    else s.ids.delete(key);
  }

  // The header box: picks every row on screen, or clears the selection.
  function setVisible(s, on, visible) {
    if (!on) {
      clearPicks(s);
      return;
    }
    visible.filter(isPersonId).forEach((id) => s.ids.add(String(id)));
  }

  // «Бүх N мөрийг сонгох»: every matching row, not only the ones on screen. The ids are not sent.
  function selectAll(s) {
    s.all = true;
    s.ids.clear();
  }

  function clearPicks(s) {
    s.all = false;
    s.ids.clear();
  }

  // A new #report-page element is a new list: its selection starts again. Returns true when it cleared.
  function resetIfNewPage(s, page) {
    if (s.page === page) return false;
    s.page = page;
    endMode(s);
    return true;
  }

  // The fields of one action: the report address, then `all=1`, or one `ids` field per picked person.
  function selectionPairs(query, ids, all) {
    const pairs = [["query", query]];
    if (all) pairs.push(["all", "1"]);
    else ids.forEach((id) => pairs.push(["ids", String(id)]));
    return pairs;
  }

  // The same fields as htmx `values`: a key that repeats becomes an array (htmx sends one field per element).
  function pairsToValues(pairs) {
    const values = {};
    pairs.forEach(([key, value]) => {
      values[key] = key in values ? [].concat(values[key], value) : value;
    });
    return values;
  }

  // The file name from Content-Disposition: the RFC 5987 form first, then the plain form, else the fallback.
  function filenameFrom(header, fallback) {
    if (!header) return fallback;
    const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
    if (star) {
      try {
        return decodeURIComponent(star[1].trim());
      } catch (err) {
        return fallback;
      }
    }
    const plain = /filename="?([^";]+)"?/i.exec(header);
    return plain ? plain[1].trim() : fallback;
  }

  // The note after «Хуулах»: the count, and how many rows the copy had to drop.
  function copyNote(data) {
    const dropped = data.dropped ? " · " + data.dropped + " хасагдсан" : "";
    return "Хууллаа: " + data.count + dropped;
  }

  const helpers = {
    PICKED_CLASS,
    isPersonId,
    createState,
    isOn,
    toggleMode,
    endMode,
    isPicked,
    headerMark,
    setRow,
    setVisible,
    selectAll,
    clearPicks,
    resetIfNewPage,
    selectionPairs,
    pairsToValues,
    filenameFrom,
    copyNote,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = helpers;
  if (typeof document === "undefined") return;

  // ---- Page wiring ----

  const state = createState();
  let noteTimer = 0;
  let pending = 0;             // requests and prints in flight; the action buttons are off while it is above 0
  let pendingChecklist = null; // { url, finish } of the checklist request in flight, for its error events

  function bar() {
    return document.getElementById("selection-bar");
  }

  function rows() {
    return Array.from(document.querySelectorAll("tbody tr[data-person]")).filter((row) => isPersonId(row.dataset.person));
  }

  function visibleIds() {
    return rows().map((row) => row.dataset.person);
  }

  function inReportPage(el) {
    return !!el.closest("#report-page");
  }

  // The nearest element at or above a node (a click on a text node starts at its parent).
  function closestOf(node, selector) {
    const el = node instanceof Element ? node : node && node.parentElement;
    return el ? el.closest(selector) : null;
  }

  // CSRF token, read as palette.js does: the cookie first, the hx-headers JSON on <body> as the fallback.
  function csrfToken() {
    const m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    try {
      return JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRFToken"] || "";
    } catch (err) {
      return "";
    }
  }

  function paintRow(row) {
    const on = isPicked(state, row.dataset.person);
    const box = row.querySelector("input[data-select-row]");
    // Always written from the state, never read back: a browser's form restore may have left the box ticked.
    if (box) {
      box.checked = on;
      box.indeterminate = false;
    }
    row.classList.toggle(PICKED_CLASS, on);
    row.setAttribute("aria-selected", on ? "true" : "false");
  }

  // The count shows the label's total in all-matching mode («Бүгд (N)»), else the picked ids.
  function totalOf(box, fallback) {
    const button = box.querySelector("[data-select-matching]");
    const found = button && /\d+/.exec(button.textContent);
    return found ? Number(found[0]) : fallback;
  }

  // Re-paints everything from the state: row boxes and highlights, the header box, the bar and its offers.
  function sync() {
    if (resetIfNewPage(state, document.getElementById("report-page"))) clearNote();
    const on = isOn(state);
    if (on) document.body.dataset.selecting = "1";
    else delete document.body.dataset.selecting;
    document.querySelectorAll("[data-select-toggle]").forEach((toggle) => {
      toggle.setAttribute("aria-pressed", on ? "true" : "false");
    });

    const list = rows();
    list.forEach(paintRow);
    const ids = list.map((row) => row.dataset.person);
    const picked = ids.filter((id) => isPicked(state, id)).length;
    const header = document.querySelector("input[data-select-all]");
    if (header) {
      const mark = headerMark(state, ids);
      header.checked = mark.checked;
      header.indeterminate = mark.indeterminate;
    }

    const box = bar();
    if (!box) return;
    box.hidden = !on;
    // Every row on screen is picked and more batches follow: offer «all matching» (or the over-cap note).
    const offer = !state.all && list.length > 0 && picked === list.length && !!document.querySelector("[data-more-batch]");
    const matching = box.querySelector("[data-select-matching]");
    const overCap = box.querySelector("[data-over-cap]");
    if (matching) matching.hidden = !offer;
    if (overCap) overCap.hidden = !offer;
    const count = box.querySelector("[data-count]");
    if (count) count.textContent = state.all ? "Бүгд (" + totalOf(box, list.length) + ")" : String(state.ids.size);
  }

  // ---- Message line and requests ----

  function messageEl() {
    const box = bar();
    return box ? box.querySelector("[data-select-msg]") : null;
  }

  function clearNote() {
    clearTimeout(noteTimer);
    const msg = messageEl();
    if (msg) {
      msg.textContent = "";
      msg.hidden = true;
    }
  }

  // A note clears itself after a few seconds; an error stays until the next action.
  function showMessage(text, isError) {
    const msg = messageEl();
    if (!msg) return;
    clearTimeout(noteTimer);
    msg.textContent = text;
    msg.hidden = false;
    msg.classList.toggle("text-red-700", isError);
    msg.classList.toggle("text-slate-700", !isError);
    if (!isError) noteTimer = setTimeout(clearNote, NOTE_MS);
  }

  // Every request or print takes one begin() and calls the returned finish() exactly once (a second call does nothing).
  // finish() is the only place that re-enables the action buttons, and they stay off while any request is pending.
  function begin() {
    pending += 1;
    setActionsDisabled(true);
    let done = false;
    return function finish() {
      if (done) return;
      done = true;
      pending -= 1;
      setActionsDisabled(pending > 0);
    };
  }

  function setActionsDisabled(off) {
    const box = bar();
    if (box) box.querySelectorAll("[data-action]").forEach((button) => { button.disabled = off; });
  }

  function currentPairs() {
    const query = bar() ? bar().dataset.query || "" : "";
    return selectionPairs(query, Array.from(state.ids), state.all);
  }

  function withCsrf(pairs) {
    return pairs.concat([["csrfmiddlewaretoken", csrfToken()]]);
  }

  function post(url, pairs) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(withCsrf(pairs)).toString(),
    });
  }

  // The server answers a refusal with a short plain-text Mongolian message; anything else gets the generic line.
  async function errorText(r) {
    const plain = (r.headers.get("Content-Type") || "").indexOf("text/plain") === 0;
    const text = plain ? (await r.text()).trim() : "";
    return text || FAILED_MSG;
  }

  // The same rule for an htmx error response (its XHR): a plain-text message is shown, an HTML error page is not.
  function xhrErrorText(xhr) {
    const type = (xhr && xhr.getResponseHeader && xhr.getResponseHeader("Content-Type")) || "";
    const text = type.indexOf("text/plain") === 0 ? String(xhr.responseText || "").trim() : "";
    return text || FAILED_MSG;
  }

  function saveFile(blob, name) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // The clipboard API needs a secure context; a hidden textarea and execCommand are the fallback.
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

  async function fetchAndSave(kind, url, pairs) {
    const r = await post(url, pairs);
    if (r.redirected) {  // the session ended: the login page came back instead of the file
      window.location.reload();
      return;
    }
    if (!r.ok) {
      showMessage(await errorText(r), true);
      return;
    }
    saveFile(await r.blob(), filenameFrom(r.headers.get("Content-Disposition"), kind === "csv" ? "report.csv" : "report.xlsx"));
  }

  async function fetchAndCopy(url, pairs) {
    const r = await post(url, pairs);
    if (r.redirected) {
      window.location.reload();
      return;
    }
    if (!r.ok) {
      showMessage(await errorText(r), true);
      return;
    }
    const data = await r.json();
    const ok = await writeClipboard(data.text);
    if (ok) showMessage(copyNote(data), false);
    else showMessage("Хуулж чадсангүй.", true);
  }

  // A form in a new tab: the print page opens there (a refusal shows as plain text in that tab).
  function printSelection(url) {
    const form = document.createElement("form");
    form.method = "post";
    form.action = url;
    form.target = "_blank";
    form.hidden = true;
    withCsrf(currentPairs()).forEach(([name, value]) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = value;
      form.appendChild(input);
    });
    document.body.appendChild(form);
    const finish = begin();
    setTimeout(finish, 2000);  // the new tab has no response we can read; the buttons come back after a moment
    form.submit();
    form.remove();
  }

  // The pop-up is an htmx request. Its success is the swap; its failure comes as htmx:responseError or htmx:sendError
  // (htmx does not swap an error response), handled below.
  function openChecklist(url) {
    if (!window.htmx) {
      showMessage("Жагсаалт нээгдсэнгүй. Хуудсаа дахин ачаална уу.", true);
      return;
    }
    const finish = begin();
    const request = { url, finish };
    pendingChecklist = request;
    let answer = null;
    try {
      answer = window.htmx.ajax("POST", url, { target: "body", swap: "beforeend", values: pairsToValues(currentPairs()) });
    } catch (err) {
      pendingChecklist = null;
      showMessage(NETWORK_MSG, true);
      finish();
      return;
    }
    Promise.resolve(answer)
      .catch(() => null)  // the failure is shown by the htmx error event, not here
      .finally(() => {
        if (pendingChecklist === request) pendingChecklist = null;
        finish();
      });
  }

  function runAction(button) {
    const url = button.dataset.url;
    const kind = button.dataset.action;
    if (!url) return;
    if (kind === "checklist") return openChecklist(url);
    if (kind === "print") return printSelection(url);
    if (pending > 0) return;
    const finish = begin();
    const job = kind === "copy" ? fetchAndCopy(url, currentPairs()) : fetchAndSave(kind, url, currentPairs());
    job
      .catch(() => showMessage(NETWORK_MSG, true))
      .finally(finish);
  }

  // The checklist request this event belongs to, if any (htmx reports the path it was sent to).
  function checklistEvent(evt) {
    const path = evt.detail && evt.detail.pathInfo && evt.detail.pathInfo.requestPath;
    return pendingChecklist && path === pendingChecklist.url ? pendingChecklist : null;
  }

  function failChecklist(request, text) {
    pendingChecklist = null;
    showMessage(text, true);
    request.finish();
  }

  // ---- Events ----

  // Capture phase: while selection is on, a click anywhere on a person's row toggles that row and does nothing else
  // (no link, no button, no pop-up). A click on the row's own checkbox keeps its native toggle and change event.
  document.addEventListener("click", (e) => {
    if (!isOn(state)) return;
    const row = closestOf(e.target, "tbody tr[data-person]");
    if (!row || !inReportPage(row) || !isPersonId(row.dataset.person)) return;
    if (closestOf(e.target, "input[data-select-row]")) return;
    e.preventDefault();
    e.stopPropagation();
    setRow(state, row.dataset.person, !isPicked(state, row.dataset.person), visibleIds());
    sync();
  }, true);

  // Selection off: a click anywhere on a report row opens its record (the row's first link), like the name link.
  // Controls in the row keep their own action; Ctrl/Cmd or middle click opens a new tab; a text selection is not a click.
  function openRowLink(e) {
    if (isOn(state) || e.defaultPrevented) return;
    const row = closestOf(e.target, "#report-page tbody tr");
    if (!row || closestOf(e.target, "a, button, input, select, textarea, label")) return;
    if (window.getSelection && String(window.getSelection())) return;
    const link = row.querySelector("td a[href]");
    if (!link) return;
    if (e.button === 1 || e.ctrlKey || e.metaKey) window.open(link.href, "_blank");
    else if (e.button === 0) location.href = link.href;
  }
  document.addEventListener("click", openRowLink);
  document.addEventListener("auxclick", openRowLink);

  document.addEventListener("change", (e) => {
    const target = e.target;
    if (!(target instanceof HTMLInputElement) || !inReportPage(target)) return;
    if (target.matches("[data-select-row]")) {
      const row = target.closest("tr[data-person]");
      if (!row || !isPersonId(row.dataset.person)) return;
      // The new value is the opposite of the state, not the box: the boxes always match the state (see sync).
      setRow(state, row.dataset.person, !isPicked(state, row.dataset.person), visibleIds());
    } else if (target.matches("[data-select-all]")) {
      const ids = visibleIds();
      setVisible(state, !headerMark(state, ids).checked, ids);
    } else {
      return;
    }
    sync();
  });

  // Escape clears the selection, unless a pop-up is open or the key was already used (a dropdown, a calendar).
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.defaultPrevented || !isOn(state)) return;
    if (document.querySelector(".fixed.inset-0.z-50:not([data-leaving])")) return;
    endMode(state);
    clearNote();
    sync();
  });

  // The «Сонгох» toolbar toggle: on with nothing picked, off (and cleared) when pressed again.
  document.addEventListener("click", (e) => {
    if (!closestOf(e.target, "[data-select-toggle]")) return;
    toggleMode(state);
    clearNote();
    sync();
  });

  document.addEventListener("click", (e) => {
    if (!closestOf(e.target, "#selection-bar")) return;
    if (closestOf(e.target, "[data-select-cancel]")) {
      endMode(state);
      clearNote();
      sync();
      return;
    }
    if (closestOf(e.target, "[data-select-matching]")) {
      selectAll(state);
      sync();
      return;
    }
    const action = closestOf(e.target, "[data-action]");
    if (action) runAction(action);
  });

  // The checklist endpoint refused (403 without the right, 404, 500) or the request never left.
  document.addEventListener("htmx:responseError", (evt) => {
    const request = checklistEvent(evt);
    if (request) failChecklist(request, xhrErrorText(evt.detail.xhr));
  });
  document.addEventListener("htmx:sendError", (evt) => {
    const request = checklistEvent(evt);
    if (request) failChecklist(request, NETWORK_MSG);
  });

  // Every htmx swap (a «Цааш харуулах» batch, a filter change, a view switch) re-paints the rows from the state.
  document.addEventListener("htmx:afterSettle", () => sync());

  // Back to a page saved mid-selection: the restored page must not show the old picks or the bar.
  document.addEventListener("htmx:historyRestore", () => {
    endMode(state);
    clearNote();
    sync();
  });

  // The browser restores form state (checkboxes) after the script has run, on a Back or reload. Re-paint after the
  // load and after every page show, so the boxes match the state again (the state itself is never read from the DOM).
  window.addEventListener("pageshow", () => sync());
  window.addEventListener("load", () => sync());

  sync();
})();
