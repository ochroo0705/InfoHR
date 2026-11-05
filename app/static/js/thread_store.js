// The assistant panel's thread (spec 2026-11-05-assistant-panel). The conversation lives in sessionStorage, one key per
// user, so a page change keeps it and closing the tab drops it. Every storage call is guarded: a blocked or full storage
// just means the thread is not kept, and nothing here throws. Runs as a browser script (window.createThreadStore) and
// under Node for the unit tests (thread_store.test.mjs).
(function () {
  "use strict";

  var MAX_ITEMS = 10;
  var MAX_AGE_MS = 60 * 60 * 1000; // an item older than an hour is dropped when the thread is read
  var MAX_HTML = 50000;            // a longer answer is stored as a placeholder (the live page still shows it in full)
  var MAX_FIELD = 2000;            // a follow-up url or body, or an answer's context, is kept only up to this length
  var TOO_LONG_HTML = '<p class="px-1 text-sm text-slate-500">Хариулт хадгалагдсангүй.</p>';

  // Shared by every store on the page, so two stores never hand out the same id in the same millisecond.
  var counter = 0;

  function isItem(item) {
    return !!item && typeof item === "object" &&
      typeof item.id === "string" &&
      typeof item.q === "string" &&
      (item.html === null || typeof item.html === "string") &&
      typeof item.at === "number";
  }

  // A url the panel may post to on its own site: a path that starts with one "/" (not "//" or "/\", which a browser reads
  // as another host), with no spaces or control characters, at most MAX_FIELD long.
  function isRelativePath(url) {
    return typeof url === "string" && url.length > 0 && url.length <= MAX_FIELD &&
      /^\/(?![\/\\])[^\x00-\x20\x7f]*$/.test(url);
  }

  function validContext(ctx) {
    return typeof ctx === "string" && ctx.length > 0 && ctx.length <= MAX_FIELD;
  }

  // The optional fields of an item: url and body (a follow-up), context (the answer's data-assistant-context). A wrong-typed
  // or too long field is dropped; a url is set to "" instead, which never gets a retry button. An old item has none of
  // these fields and is left as it is.
  function cleanExtras(item) {
    if ("url" in item && (typeof item.url !== "string" || item.url.length > MAX_FIELD)) item.url = "";
    if ("body" in item && (typeof item.body !== "string" || item.body.length > MAX_FIELD)) delete item.body;
    if ("context" in item && !validContext(item.context)) delete item.context;
    return item;
  }

  function escapeAttr(text) {
    return text.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // The stored html of an answer too long to keep. With a context it still carries the answer's data-assistant-context,
  // so a typed question after a reload sends the same prev.
  function placeholderFor(ctx) {
    if (!ctx) return TOO_LONG_HTML;
    return '<p class="px-1 text-sm text-slate-500" data-assistant-context="' + escapeAttr(ctx) +
      '">Хариулт хадгалагдсангүй.</p>';
  }

  function createThreadStore(storage, userId, now) {
    var key = "assistant-thread-" + userId;

    // The stored thread, cleaned up. Missing, corrupt or wrong-shaped data reads as empty, and a storage that throws
    // reads as empty too: the panel then simply shows nothing from before.
    function load() {
      var data = null;
      try {
        var raw = storage.getItem(key);
        data = raw == null ? null : JSON.parse(raw);
      } catch (err) {
        data = null;
      }
      if (!data || typeof data !== "object" || Array.isArray(data)) return { open: false, items: [] };
      var cutoff = now() - MAX_AGE_MS;
      var items = Array.isArray(data.items) ? data.items : [];
      items = items.filter(function (item) { return isItem(item) && item.at >= cutoff; }).map(cleanExtras);
      return { open: data.open === true, items: items.slice(-MAX_ITEMS) };
    }

    function save(data) {
      try {
        storage.setItem(key, JSON.stringify(data));
      } catch (err) {
        // storage blocked or full: the thread is not kept this time
      }
    }

    return {
      read: load,

      setOpen: function (open) {
        var data = load();
        data.open = !!open;
        save(data);
      },

      // A question waiting for its answer (html null). `follow` is {url, body} for a follow-up button's question, so the
      // item can ask the same follow-up again after a page change; none for a typed question. Returns the item's id.
      addPending: function (q, follow) {
        counter += 1;
        var at = now();
        var item = { id: at + "-" + counter, q: String(q), html: null, at: at };
        if (follow) {
          item.url = follow.url;
          item.body = follow.body;
          cleanExtras(item);
        }
        var data = load();
        data.items = data.items.concat([item]).slice(-MAX_ITEMS);
        save(data);
        return item.id;
      },

      // The answer's html. `context` is the answer's data-assistant-context (or null): kept on the item, and carried by the
      // placeholder when the html is too long to keep.
      resolve: function (id, html, context) {
        if (typeof html !== "string") return;
        var ctx = validContext(context) ? context : null;
        if (html.length > MAX_HTML) html = placeholderFor(ctx);
        var data = load();
        data.items.forEach(function (item) {
          if (item.id !== id) return;
          item.html = html;
          if (ctx) item.context = ctx;
          else delete item.context;
        });
        save(data);
      },

      // Empties the thread but keeps whether the panel was open.
      clear: function () {
        save({ open: load().open, items: [] });
      },

      clearAll: function () {
        try {
          storage.removeItem(key);
        } catch (err) {
          // storage blocked: nothing to remove
        }
      }
    };
  }

  // The context of the thread's last answer, for the next typed question's `prev`. `entries` is the thread in order, one
  // {answered, context} per item (the panel reads them from the page). Only the newest answered item counts: when it has
  // no context, the answer is null, even if an older answer had one. An unanswered question after it does not hide it.
  function lastAnswerContext(entries) {
    for (var i = entries.length - 1; i >= 0; i -= 1) {
      if (entries[i].answered) return entries[i].context || null;
    }
    return null;
  }

  // The form body of a typed question: the question, and the previous answer's context as `prev` when there is one.
  function typedQuestionBody(q, context) {
    var body = "q=" + encodeURIComponent(q);
    if (validContext(context)) body += "&prev=" + encodeURIComponent(context);
    return body;
  }

  if (typeof window !== "undefined") {
    window.createThreadStore = createThreadStore;
    window.lastAnswerContext = lastAnswerContext;
    window.typedQuestionBody = typedQuestionBody;
    window.isRelativePath = isRelativePath;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      createThreadStore: createThreadStore,
      lastAnswerContext: lastAnswerContext,
      typedQuestionBody: typedQuestionBody,
      isRelativePath: isRelativePath,
    };
  }
})();
