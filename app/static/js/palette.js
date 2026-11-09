// The assistant panel (docs/superpowers/specs/2026-11-05-assistant-panel-design.md). base.html holds the panel
// (#assistant-panel, `hidden` at first) in the page: a docked side panel, not a pop-up, so the page is never locked and
// keeps scrolling. This script opens and closes it (Ctrl+K, the top bar's «Хайх» button, the floating «Асуух» button and
// its ×), runs the quick search in its box, and keeps the open flag in sessionStorage (thread_store.js) so the panel is
// open again after a page change. Pages without the panel (the login page) get nothing from this script.
(function () {
  "use strict";

  // The panel's exit state (plan 2026-11-08-selection-motion, task 9). A panel that is sliding out is still visible
  // (hidden is false) but no longer open: isPanelOpen is false from the moment the exit starts. Each exit has a token
  // (el.__closing): cancelExit (a reopen during the exit) clears it, so the pending done() does nothing, as nav.js does.
  // These helpers touch no DOM, so the Node tests load this file before any lookup (palette_panel.test.mjs).
  function isPanelOpen(el) {
    return !el.hidden && !el.hasAttribute("data-leaving");
  }

  // Starts the exit of el through hrLeaveFn (window.hrLeave). done() clears the leaving state and then calls hide(), and
  // only while its own token is still current. Without hrLeaveFn the element is hidden at once.
  function startExit(el, hrLeaveFn, hide) {
    if (typeof hrLeaveFn !== "function") {
      el.__closing = null;
      hide();
      return;
    }
    var token = el.__closing = {};
    hrLeaveFn(el, {
      done: function () {
        if (el.__closing !== token) return;  // cancelled by cancelExit, or a newer exit has taken over
        el.__closing = null;
        el.removeAttribute("data-leaving");
        el.inert = false;
        hide();
      },
    });
  }

  // Cancels an exit in flight: the element is shown and interactive again, and the pending done() does nothing.
  function cancelExit(el) {
    el.__closing = null;
    el.removeAttribute("data-leaving");
    el.inert = false;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { isPanelOpen: isPanelOpen, startExit: startExit, cancelExit: cancelExit };
    return;
  }

  var panel = document.querySelector("[data-assistant-panel]");
  var input = panel && panel.querySelector("[data-palette-input]");
  var results = panel && panel.querySelector("[data-palette-results]");
  var failed = panel && panel.querySelector("[data-palette-failed]");
  var thread = panel && panel.querySelector("[data-assistant-thread]");
  if (!panel || !input || !results || !failed || !thread) return;

  var url = panel.getAttribute("data-url");
  var userId = panel.getAttribute("data-user") || "";
  var askOn = panel.getAttribute("data-ask-on") === "1";  // the assistant is on for this user (the «Асуух» row and button)
  var fab = document.querySelector("[data-assistant-fab]");
  var chartPane = document.querySelector("[data-chart-pane]");  // the docked chart pane (base.html), may be absent
  var sendBtn = panel.querySelector("[data-assistant-send]");  // the round send button (only when the assistant is on)
  var DEBOUNCE_MS = 200;
  var RECENT_KEY = "palette-recent-" + userId;  // per user: shared PCs do not mix them
  var RECENT_MAX = 5;
  var REF_SHAPE = /^(p:[0-9]{1,12}|s:\/[!-~]{0,200})$/;  // `p:<pk>` a person, `s:<path>` a fixed page; nothing else

  // The open flag survives page changes (one sessionStorage key per user). Without a store (storage blocked, no
  // thread_store.js, no user) the panel works the same, it just is not remembered.
  var store = null;
  if (userId && window.createThreadStore) {
    try {
      store = window.createThreadStore(window.sessionStorage, userId, Date.now);
    } catch (err) {
      store = null;
    }
  }

  var opener = null;     // the element that had focus before the panel opened, given focus back on close
  var timer = null;      // the debounce timer while a typed query waits
  var controller = null; // AbortController of the latest request
  var loading = false;   // true while the latest request is still in flight
  var busyTimer = null;  // the wait before a slow answer dims the list (markBusy)
  var BUSY_MS = 150;
  var ASK_WAIT = "Хариулт хайж байна…";
  var ASK_FAIL = "Хариулт авч чадсангүй. Дахин оролдоно уу.";
  var RETRY_TEXT = "Дахин асуух";
  var UNANSWERED = "Хариулт ирсэнгүй.";
  var RETRIED_HTML = '<p class="px-1 text-sm text-slate-500">Дахин асуулаа.</p>';  // marks an item asked again
  // The context of the thread's last answer (thread_store.js); without that script no question carries a prev.
  var previousContext = window.lastAnswerContext || function () { return null; };
  var questionBody = window.typedQuestionBody || function (q) { return "q=" + encodeURIComponent(q); };
  var isRelative = window.isRelativePath || function () { return false; };  // no store script: no follow-up is posted

  // Remembered references (Сүүлд нээсэн): short ids only, newest first, no names. Every storage access is guarded: a
  // blocked or full storage, or a value that is not ours, just means nothing is remembered or shown.
  function readRecent() {
    try {
      var list = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
      if (!Array.isArray(list)) return [];
      return list.filter(function (ref) { return typeof ref === "string" && REF_SHAPE.test(ref); }).slice(0, RECENT_MAX);
    } catch (err) {
      return [];
    }
  }

  function remember(ref) {
    if (!ref || !REF_SHAPE.test(ref)) return;
    var list = readRecent().filter(function (r) { return r !== ref; });
    list.unshift(ref);
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, RECENT_MAX)));
    } catch (err) {
      // storage blocked or full: the box is simply not remembered
    }
  }

  // A person or a fixed page the user opened from the panel. Quick actions carry no data-palette-ref, so they are not kept.
  function noteOpened(item) {
    remember(item.getAttribute("data-palette-ref"));
  }

  function isOpen() {
    return isPanelOpen(panel);
  }

  function hidePanel() {
    panel.hidden = true;
  }

  // The floating button's aria-expanded follows the panel.
  function setFab(open) {
    if (fab) fab.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function saveOpen(open) {
    if (store) store.setOpen(open);
  }

  // The quick results always show (the recents with an empty box). The thread shows only with an empty box: a typed
  // query hides it. A hidden thread loses its scroll, so it goes back to the newest item when it shows again.
  function syncMode() {
    var hide = input.value.trim() !== "";
    thread.hidden = hide;
    // With a typed query the results take the room the thread had; with an empty box they keep their own cap.
    results.classList.toggle("flex-1", hide);
    results.style.maxHeight = hide ? "none" : "";
    if (sendBtn) sendBtn.disabled = !hide || !askOn;
    autosize();
    if (!hide) scrollThread();  // after the thread shows: a hidden element has no scroll to set
  }

  // The box grows with its text up to its CSS max-height (then it scrolls) and shrinks back when text is removed.
  function autosize() {
    if (panel.hidden) return;  // a hidden box measures 0; it is measured again when the panel opens
    input.style.height = "auto";
    input.style.height = input.scrollHeight + "px";
  }

  function clearBox() {
    input.value = "";
    autosize();
  }

  function scrollThread() {
    thread.scrollTop = thread.scrollHeight;
  }

  // Opens the panel with an empty box (the recents show). A click, Ctrl+K or the floating button takes focus into the
  // box and remembers the open flag; a page load with the stored flag opens the panel without taking focus.
  function openPanel(fromUser) {
    if (isOpen()) return;
    opener = fromUser ? document.activeElement : null;
    cancelExit(panel);  // a reopen during the exit takes the panel back: its pending hide does nothing
    // A page-load open (the stored flag) does not slide in: the panel is simply there, as before the motion. Only a user
    // open plays hr-slide-in (input.css skips data-no-enter).
    if (fromUser) panel.removeAttribute("data-no-enter");
    else panel.setAttribute("data-no-enter", "");
    panel.hidden = false;
    setFab(true);
    if (fromUser) saveOpen(true);
    clearTimeout(timer);
    timer = null;
    clearBox();
    syncMode();
    scrollThread();
    if (fromUser) input.focus();
    search("");
  }

  // Closes the panel and drops a quick search in flight. An assistant question is not dropped: its answer lands in the
  // thread even while the panel is closed. Focus goes back to the element that had it before opening; a navigation
  // does not ask for that.
  function closePanel(restoreFocus) {
    if (!isOpen()) return;
    clearTimeout(timer);
    timer = null;
    if (controller) controller.abort();
    controller = null;
    loading = false;
    clearBusy();
    var back = opener;
    opener = null;
    // An element is usable for focus when it is still in the page and drawn (a page-load open has no opener).
    var useBack = restoreFocus && back && document.contains(back) && back.focus && back.getClientRects().length > 0;
    // Focus is inside the panel and nothing else takes it: move it to the floating button, or to the top-bar button,
    // before the panel is hidden, so focus does not fall to the body.
    // Focus in the chart pane counts as inside too: the pane goes inert with the panel, so focus must leave it first.
    var inside = panel.contains(document.activeElement) || !!(chartPane && chartPane.contains(document.activeElement));
    if (inside && !useBack) {
      var alt = fab && fab.getClientRects().length > 0 ? fab : document.querySelector("[data-palette-open]");
      if (alt && alt.focus) alt.focus();
    }
    // The state changes at once (isOpen, the floating button, the open flag). The panel slides out and is hidden when the
    // exit ends (startExit); the focus moves above run before the exit starts, as before.
    setFab(false);
    saveOpen(false);
    startExit(panel, window.hrLeave, hidePanel);
    if (useBack) back.focus();
  }

  function togglePanel() {
    if (isOpen()) closePanel(true);
    else openPanel(true);
  }

  // Opens a result. A quick action with data-palette-modal (a pop-up form) closes the panel and is loaded over the page
  // with htmx, so the form appears where the user is. The «show all» row (data-palette-more) asks for the same query
  // again with more people and keeps the panel open. Every other result is a page: the stored flag is set to closed
  // before the navigation, so the next page starts with the panel closed.
  function activate(item) {
    // The «Асуух» row only asks the assistant, and only here (Enter or a click), never while typing.
    if (item.hasAttribute("data-palette-ask")) {
      if (!askOn || loading || timer) return;  // same rule as Enter: no question while a search is still in flight or waiting
      ask(item);
      return;
    }
    if (item.hasAttribute("data-palette-more")) {
      var at = Array.prototype.indexOf.call(items(), item);
      search(input.value, at);  // the first newly shown person takes the row's place
      input.focus();
      return;
    }
    var href = item.getAttribute("href");
    noteOpened(item);
    if (item.hasAttribute("data-palette-modal")) {
      closePanel(true);
      if (window.htmx) window.htmx.ajax("GET", href, { target: "body", swap: "beforeend" });
      else window.location.assign(href);
      return;
    }
    saveOpen(false);
    window.location.assign(href);
  }

  // A slow answer dims the old list: after BUSY_MS the list gets opacity-60 and aria-busy, so a quick answer never flashes.
  // clearBusy runs on the answer, an error or close; a new query keeps the dim until its own answer.
  function markBusy() {
    clearTimeout(busyTimer);
    busyTimer = setTimeout(function () {
      busyTimer = null;
      if (!loading) return;
      results.classList.add("opacity-60");
      results.setAttribute("aria-busy", "true");
    }, BUSY_MS);
  }

  function clearBusy() {
    clearTimeout(busyTimer);
    busyTimer = null;
    results.classList.remove("opacity-60");
    results.removeAttribute("aria-busy");
  }

  // CSRF token, read as select.js does: the cookie first, the hx-headers JSON on <body> as the fallback.
  function csrfToken() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    try {
      return JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRFToken"] || "";
    } catch (err) {
      return "";
    }
  }

  // Asking from the «Асуух» row (Enter or a click): the typed text becomes a question in the thread. Nothing is aborted
  // by it: typing, a new search or closing the panel leave the request going, and only leaving the page ends it (the
  // question then stays unanswered in the store). Each question has its own thread item, so two can be in flight.
  function ask(row) {
    var q = input.value.trim();
    if (!q) return;
    startAsk(q, row.getAttribute("data-ask-url") || panel.getAttribute("data-ask-url"), typedBody(q), false);
  }

  // The body of a typed question: the question, and the context of the thread's last answer as `prev` when it has one.
  // With a chart open beside the chat, the question is about that chart: its filters are the previous filters and its
  // kind and grouping go along, so «дугуй болго» or «зөвхөн ...» changes it.
  function typedBody(q) {
    var chart = window.openChartState ? window.openChartState() : null;
    if (chart) return "q=" + encodeURIComponent(q) + "&prev=" + encodeURIComponent(chart.query) + "&chart=" + encodeURIComponent(chart.kind + "|" + chart.by);
    return questionBody(q, previousContext(answerEntries()));
  }

  // The context of an answer slot (its data-assistant-context), or null.
  function contextOf(slot) {
    var ctx = slot.querySelector("[data-assistant-context]");
    return ctx ? ctx.getAttribute("data-assistant-context") : null;
  }

  // One {answered, context} per thread item, in thread order: what lastAnswerContext reads. The context is the answer's
  // own data-assistant-context (a list answer), read from the page, so a restored answer counts the same.
  function answerEntries() {
    return Array.prototype.map.call(thread.querySelectorAll("[data-assistant-item]"), function (li) {
      return { answered: li.hasAttribute("data-answered"), context: contextOf(slotOf(li)) };
    });
  }

  // The same flow for a new question, a follow-up button and «Дахин асуух»: a thread item at once, the box cleared, the
  // quick results back to the recents, the thread scrolled to its newest item, then the request. `followed` keeps the
  // url and body on the item, so «Дахин асуух» sends the same follow-up again.
  function startAsk(q, askUrl, body, followed) {
    var id = store ? store.addPending(q, followed ? { url: askUrl, body: body } : null) : null;
    var li = threadItem(q, id);
    if (followed) {
      li.setAttribute("data-retry-url", askUrl);
      li.setAttribute("data-retry-body", body);
    }
    thread.appendChild(li);
    clearBox();
    clearTimeout(timer);
    timer = null;
    syncMode();
    search("");
    scrollThread();
    sendAsk(li, askUrl, body);
  }

  // One thread item: the question (text only, right-aligned and muted), then an answer slot that starts with the waiting
  // line. `id` is the store's id for the question; it is kept on the item as data-id (none without a store).
  function threadItem(q, id) {
    var li = document.createElement("div");
    li.className = "mt-4 first:mt-0";
    li.setAttribute("data-assistant-item", "");
    if (id) li.setAttribute("data-id", id);
    var question = document.createElement("p");
    // A chat bubble on the right (the user's own words), the answer card stays on the left.
    question.className = "ml-auto w-fit max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-violet-600 px-3.5 py-2 text-white";
    question.setAttribute("data-assistant-question", "");
    question.textContent = q;
    var slot = document.createElement("div");
    slot.setAttribute("data-assistant-slot", "");
    slot.appendChild(waitingLine());
    li.appendChild(question);
    li.appendChild(slot);
    return li;
  }

  function slotOf(li) {
    return li.querySelector("[data-assistant-slot]");
  }

  // The answer slot takes the server's fragment (the server's own trusted markup, as search does).
  // The retried placeholder is not an answer, so a question after it does not take its context as `prev`.
  function setAnswer(li, html) {
    slotOf(li).innerHTML = html;
    if (html !== RETRIED_HTML) li.setAttribute("data-answered", "");
  }

  // A line of text and the «Дахин асуух» button, which asks this item's question again (text only).
  function setRetry(li, text) {
    var slot = slotOf(li);
    slot.textContent = "";
    slot.appendChild(statusLine(text));
    var btn = document.createElement("button");
    btn.type = "button";
    btn.setAttribute("data-assistant-retry", "");
    btn.className = "mt-1 rounded-lg px-2.5 py-1.5 text-sm text-violet-700 hover:bg-violet-50 max-sm:min-h-11";
    btn.textContent = RETRY_TEXT;
    slot.appendChild(btn);
  }

  // Posts `body` (form-encoded) to askUrl and fills the item's slot when the answer comes. The store keeps the answer
  // under the item's id. A failed request shows the error line with the retry button; the store keeps the question
  // unanswered.
  function sendAsk(li, askUrl, body) {
    fetch(askUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/x-www-form-urlencoded" },
      body: body,
    })
      .then(function (r) {
        // The session ended: the server sent the login page instead of the answer. Reload, as search does.
        if (r.redirected) {
          window.location.reload();
          return null;
        }
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.text();
      })
      .then(function (html) {
        if (html === null) return;
        setAnswer(li, html);
        // A chart question asked with a chart open: the chart in the pane is replaced by the new one.
        var auto = li.querySelector("a[data-chart-auto]");
        if (auto && window.openAssistantChart) window.openAssistantChart(auto.getAttribute("href"));
        var id = li.getAttribute("data-id");
        if (store && id) store.resolve(id, html, contextOf(slotOf(li)));
      })
      .catch(function () {
        setRetry(li, ASK_FAIL);
      });
  }

  // «Дахин асуух»: the question is asked again as a new item. A follow-up item sends its own url and body again; a typed
  // question is asked again with the current thread's prev. The old item is marked as asked again in the store and on
  // the page, so it stops offering the button.
  function retry(li) {
    var question = li.querySelector("[data-assistant-question]");
    var q = question ? question.textContent : "";
    if (!q) return;
    var oldId = li.getAttribute("data-id");
    var followUrl = li.getAttribute("data-retry-url");
    setAnswer(li, RETRIED_HTML);
    if (store && oldId) store.resolve(oldId, RETRIED_HTML);
    if (followUrl) startAsk(q, followUrl, li.getAttribute("data-retry-body") || "", true);
    else startAsk(q, panel.getAttribute("data-ask-url"), typedBody(q), false);
    input.focus();  // the retry button is gone with its slot: focus goes to the box, not to the body
  }

  // A follow-up button in an answer (data-follow-url, from the server's fragment): its label is asked as a new question
  // and its body goes to its url. Every follow-up button of that answer is disabled at once, so a double click cannot
  // ask twice.
  function follow(btn) {
    var url = btn.getAttribute("data-follow-url");
    if (btn.disabled || !isRelative(url)) return;  // only a same-site path is ever posted to
    var slot = btn.closest("[data-assistant-slot]");
    var buttons = slot ? slot.querySelectorAll("[data-follow-url]") : [btn];
    Array.prototype.forEach.call(buttons, function (b) {
      b.disabled = true;
      b.setAttribute("aria-disabled", "true");
      b.classList.add("opacity-50");
    });
    // The stored answer keeps the disabled buttons too, so a page change does not bring them back.
    var owner = slot && slot.closest("[data-assistant-item]");
    var ownerId = owner ? owner.getAttribute("data-id") : null;
    if (store && ownerId) store.resolve(ownerId, slot.innerHTML, contextOf(slot));
    startAsk(btn.getAttribute("data-follow-label") || "", url, btn.getAttribute("data-follow-body") || "", true);
  }

  // The thread on page load: answered items as stored, unanswered ones with the retry button. Nothing is asked again
  // by itself.
  function drawThread(list) {
    thread.textContent = "";
    list.forEach(function (item) {
      var li = threadItem(item.q, item.id);
      thread.appendChild(li);
      if (item.html === null) restoreUnanswered(li, item);
      else setAnswer(li, item.html);
    });
  }

  // An unanswered item from the store. A typed question gets the retry button (asked again as a typed question). A
  // follow-up (the item has a url) gets it only with a same-site url and a body, and then asks the same follow-up again.
  // Anything missing or wrong shows the plain text and no button: a follow-up is never retried as a typed question.
  function restoreUnanswered(li, item) {
    if (item.url === undefined) {
      setRetry(li, UNANSWERED);
      return;
    }
    if (!isRelative(item.url) || typeof item.body !== "string") {
      slotOf(li).textContent = "";
      slotOf(li).appendChild(statusLine(UNANSWERED));
      return;
    }
    li.setAttribute("data-retry-url", item.url);
    li.setAttribute("data-retry-body", item.body);
    setRetry(li, UNANSWERED);
  }

  // The waiting line of a question: three bouncing dots and the same words (read aloud as a status).
  function waitingLine() {
    var p = document.createElement("p");
    p.setAttribute("role", "status");
    p.className = "mt-2 flex items-center gap-2 px-1 py-2 text-sm text-slate-500";
    var dots = document.createElement("span");
    dots.className = "flex gap-1";
    dots.setAttribute("aria-hidden", "true");
    for (var i = 0; i < 3; i++) {
      var d = document.createElement("span");
      d.className = "h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400";
      d.style.animationDelay = i * 150 + "ms";
      dots.appendChild(d);
    }
    p.appendChild(dots);
    p.appendChild(document.createTextNode(ASK_WAIT));
    return p;
  }

  function statusLine(text) {
    var p = document.createElement("p");
    p.setAttribute("role", "status");
    p.className = "px-3 py-2 text-sm text-slate-500";
    p.textContent = text;
    return p;
  }

  // `moreAt`: given only for «show all» (the server sends up to PEOPLE_MORE_LIMIT people); the row at that index is
  // highlighted when the answer comes. Typing again searches without it, so the short list comes back.
  function search(q, moreAt) {
    var more = typeof moreAt === "number";
    if (controller) controller.abort();
    var mine = new AbortController();
    controller = mine;
    loading = true;
    markBusy();
    // The empty box also sends what the user opened last and the path of the page it was opened on (only the path,
    // no query or hash); the server re-checks every item, so these are only hints. A typed query sends neither.
    var extra = q.trim()
      ? (more ? "&more=1" : "")
      : "&recent=" + encodeURIComponent(readRecent().join(",")) + "&from=" + encodeURIComponent(window.location.pathname);
    fetch(url + "?q=" + encodeURIComponent(q) + extra, { credentials: "same-origin", signal: mine.signal })
      .then(function (r) {
        // The session ended: the server sent the login page instead of the fragment. Reload the real page instead, so
        // the login page gets the page as `next`; do not show the login page in the box.
        if (r.redirected) {
          window.location.reload();
          return null;
        }
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.text();
      })
      .then(function (html) {
        if (html === null || !isOpen() || mine !== controller) return;  // navigating away, closed, or superseded
        loading = false;
        clearBusy();
        results.innerHTML = html;  // the server's own fragment, trusted
        // An empty box shows the thread below the recents: the recents just changed the thread's height, so scroll again.
        if (!q.trim()) scrollThread();
        if (more) {
          var list = items();
          if (list.length) select(list[Math.min(moreAt, list.length - 1)], true);
        } else {
          results.scrollTop = 0;
          highlightFirst();
        }
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") return;  // a stale request, cancelled on purpose
        if (!isOpen() || mine !== controller) return;
        loading = false;
        clearBusy();
        results.innerHTML = "";
        failed.hidden = false;
        results.appendChild(failed);
      });
  }

  function items() {
    return results.querySelectorAll("[data-palette-item]");
  }

  // The «Асуух» row is not selected by default (Enter on a plain search must open a result, not ask the assistant),
  // unless the text reads as a question (data-palette-ask-first) or nothing matched (data-palette-empty). Then the first real result is selected.
  function highlightFirst() {
    var list = items();
    var pick = 0;
    if (list.length > 1 && list[0].hasAttribute("data-palette-ask") && !list[0].hasAttribute("data-palette-ask-first")
        && !results.querySelector("[data-palette-empty]")) {  // nothing matched: the question is the only real next step
      pick = 1;
    }
    for (var i = 0; i < list.length; i++) list[i].setAttribute("aria-selected", i === pick ? "true" : "false");
  }

  function clearSelection() {
    var list = items();
    for (var i = 0; i < list.length; i++) list[i].setAttribute("aria-selected", "false");
  }

  // scroll only for keyboard moves: a hover must not scroll the list under the pointer.
  function select(item, scroll) {
    var list = items();
    for (var i = 0; i < list.length; i++) {
      list[i].setAttribute("aria-selected", list[i] === item ? "true" : "false");
    }
    if (scroll) item.scrollIntoView({ block: "nearest" });
  }

  function move(step) {
    var list = items();
    if (!list.length) return;
    var cur = -1;
    for (var i = 0; i < list.length; i++) if (list[i].getAttribute("aria-selected") === "true") cur = i;
    var next;
    if (cur < 0) next = step > 0 ? 0 : list.length - 1;  // nothing highlighted yet
    else next = (cur + step + list.length) % list.length;  // wraps at both ends
    select(list[next], true);
  }

  // The box: typing starts a debounced search (the thread hides at once); a stale answer is dropped by search/ask.
  // Registered in the capture phase and with stopImmediatePropagation, so the page's own filter forms (htmx
  // `from:input` triggers bound to every input at page load) never see the panel's typing and do not reload their list.
  input.addEventListener("input", function (e) {
    e.stopImmediatePropagation();
    clearTimeout(timer);
    syncMode();
    clearSelection();  // the old answer must not be activated for the new query
    timer = setTimeout(function () {
      timer = null;
      search(input.value);
    }, DEBOUNCE_MS);
  }, true);

  // The send button asks the typed text at once (Enter may open a highlighted result instead).
  if (sendBtn) {
    sendBtn.addEventListener("click", function () {
      var q = input.value.trim();
      if (!q || !askOn || loading || timer) return;
      startAsk(q, panel.getAttribute("data-ask-url"), typedBody(q), false);
      input.focus();
    });
  }

  results.addEventListener("mousemove", function (e) {
    var item = e.target.closest && e.target.closest("[data-palette-item]");
    if (item && item.getAttribute("aria-selected") !== "true") select(item, false);
  });

  // A click on a pop-up action or the «show all» / «Асуух» rows is handled here; a click on any other result follows
  // its link as usual, and the stored flag is set to closed first so the next page starts closed. Ctrl, Shift or Alt
  // with the click opens a new tab and leaves this panel open, so the flag stays.
  results.addEventListener("click", function (e) {
    var item = e.target.closest && e.target.closest("[data-palette-item]");
    if (!item) return;
    if (item.hasAttribute("data-palette-modal") || item.hasAttribute("data-palette-more") || item.hasAttribute("data-palette-ask")) {
      e.preventDefault();
      activate(item);
      return;
    }
    noteOpened(item);
    if (!e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) saveOpen(false);
  });

  // Capture phase on document: runs before any field, the employee page's drawer handler and modal.js. It swallows only
  // the keys the panel really handles: Ctrl+K always; Escape only with focus inside the panel; the arrows and Enter only
  // with focus in the box. Everything else (Tab, the page's own shortcuts) passes through untouched.
  document.addEventListener(
    "keydown",
    function (e) {
      // e.code, not e.key: on a Cyrillic layout the key that gives K reports e.key as «к». No AltGr (e.altKey) combos.
      if (e.code === "KeyK" && (e.ctrlKey || e.metaKey) && !e.altKey) {
        e.preventDefault();
        e.stopPropagation();
        if (e.repeat) return;  // holding the keys must not flicker the panel open and shut
        togglePanel();
        return;
      }
      // Keys of an IME composition belong to the input method, not to the panel.
      if (e.isComposing || e.keyCode === 229) return;
      if (!isOpen()) return;
      if (e.key === "Escape") {
        if (!panel.contains(document.activeElement)) return;
        e.preventDefault();
        e.stopPropagation();
        // First Escape clears a typed query (the empty search comes back); with an empty box it closes the panel.
        if (input.value !== "") {
          clearTimeout(timer);
          timer = null;
          clearBox();
          syncMode();
          search("");
        } else {
          closePanel(true);
        }
        return;
      }
      if (document.activeElement !== input) return;
      // A box with several lines keeps its own caret keys; the arrows move through results only from a one-line box.
      var multiLine = input.value.indexOf("\n") !== -1;
      if ((e.key === "ArrowDown" || e.key === "ArrowUp") && multiLine) return;
      if (e.key === "Enter" && e.shiftKey) return;  // Shift+Enter: a new line
      if (e.key === "ArrowDown") {
        e.preventDefault();
        e.stopPropagation();
        move(1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        e.stopPropagation();
        move(-1);
      } else if (e.key === "Enter") {
        e.preventDefault();
        e.stopPropagation();
        // A query still waiting (debounce) or in flight: the highlighted row is not the answer yet, so do not
        // open it. A waiting query is sent now; the user presses Enter again once the new list is in.
        if (timer) {
          clearTimeout(timer);
          timer = null;
          search(input.value);
        }
        if (loading) return;
        var cur = results.querySelector('[data-palette-item][aria-selected="true"]');
        if (cur) activate(cur);
      }
    },
    true
  );

  // The top-bar «Хайх» button and the floating «Асуух» button toggle the panel; the panel's × closes it. Delegated, so
  // they work whatever the page does to the bar. A click outside the panel never closes it.
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!t || !t.closest) return;
    if (t.closest("[data-palette-open]") || t.closest("[data-assistant-fab]")) {
      e.preventDefault();
      togglePanel();
      return;
    }
    var closeBtn = t.closest("[data-assistant-close]");
    if (closeBtn && panel.contains(closeBtn)) closePanel(true);
    // «Шинэ яриа» empties the thread; the open flag stays as it is.
    var newBtn = t.closest("[data-assistant-new]");
    if (newBtn && panel.contains(newBtn)) {
      if (store) store.clear();
      thread.textContent = "";
    }
  });

  // Inside the thread: «Дахин асуух» asks again; a follow-up button (data-follow-url) asks its label; a pop-up link
  // (data-palette-modal) is loaded over the page and the panel stays open; any other link navigates as usual. Nothing
  // here touches the stored open flag. Delegated on the thread: the answers are redrawn from the store on page load.
  thread.addEventListener("click", function (e) {
    var t = e.target;
    if (!t || !t.closest) return;
    var retryBtn = t.closest("[data-assistant-retry]");
    if (retryBtn) {
      e.preventDefault();
      var item = retryBtn.closest("[data-assistant-item]");
      if (item) retry(item);
      return;
    }
    var followBtn = t.closest("[data-follow-url]");
    if (followBtn) {
      e.preventDefault();
      follow(followBtn);
      return;
    }
    var modal = t.closest("a[data-palette-modal]");
    if (modal) {
      e.preventDefault();
      var href = modal.getAttribute("href");
      if (window.htmx) window.htmx.ajax("GET", href, { target: "body", swap: "beforeend" });
      else window.location.assign(href);
    }
  });

  // Logging out forgets this user's thread. The submit itself is not touched.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (store && form && form.matches && form.matches('form[action$="/logout/"]')) store.clearAll();
  });

  // Page load: the thread comes back from the store (nothing is asked again), then the stored flag reopens the panel, so
  // it stays open across page changes. No focus is taken.
  syncMode();
  setFab(false);
  var saved = null;
  if (store) {
    try {
      saved = store.read();
    } catch (err) {
      saved = null;
    }
  }
  if (saved) drawThread(saved.items);
  if (saved && saved.open) openPanel(false);
})();
