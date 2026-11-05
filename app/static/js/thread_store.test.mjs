// Unit tests for thread_store.js (the assistant panel's sessionStorage thread). Run: node --test <this file>.
// The script is a classic browser script, so it is loaded through require; it exports createThreadStore under Node.
import { createRequire } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const { createThreadStore, lastAnswerContext, typedQuestionBody, isRelativePath } = require("./thread_store.js");

const MAX_HTML = 50000;

// An in-memory stand-in for sessionStorage. `raw` lets a test write or inspect the stored string directly.
function memoryStorage() {
  const raw = new Map();
  return {
    raw,
    getItem: (key) => (raw.has(key) ? raw.get(key) : null),
    setItem: (key, value) => raw.set(key, String(value)),
    removeItem: (key) => raw.delete(key),
  };
}

// A fake clock the test moves by hand.
function fakeClock(start = 1000000) {
  let t = start;
  return {
    now: () => t,
    advance: (ms) => {
      t += ms;
    },
  };
}

test("keeps_only_the_newest_ten", () => {
  const storage = memoryStorage();
  const clock = fakeClock();
  const store = createThreadStore(storage, "1", clock.now);
  for (let i = 0; i < 12; i += 1) {
    store.addPending("q" + i);
    clock.advance(1);
  }
  const items = store.read().items;
  assert.equal(items.length, 10);
  const questions = items.map((item) => item.q);
  assert.equal(questions.includes("q0"), false);
  assert.equal(questions.includes("q1"), false);
  assert.equal(questions[0], "q2");
  assert.equal(questions[9], "q11");
});

test("drops_items_older_than_one_hour", () => {
  const storage = memoryStorage();
  const clock = fakeClock();
  const store = createThreadStore(storage, "1", clock.now);
  store.addPending("old");
  clock.advance(3600001);
  assert.deepEqual(store.read().items, []);

  store.addPending("fresh");
  clock.advance(3600000 - 1000);
  const items = store.read().items;
  assert.equal(items.length, 1);
  assert.equal(items[0].q, "fresh");
});

test("corrupt_json_reads_empty", () => {
  const storage = memoryStorage();
  storage.raw.set("assistant-thread-1", "{bad");
  const store = createThreadStore(storage, "1", fakeClock().now);
  assert.deepEqual(store.read(), { open: false, items: [] });
});

test("wrong_shape_items_are_dropped", () => {
  const storage = memoryStorage();
  const at = 1000000;
  const good = { id: "a", q: "ok", html: null, at };
  const bad = [
    { id: "b", html: null, at },
    { id: 3, q: "x", html: null, at },
    { id: "d", q: "x", html: 5, at },
    { id: "e", q: "x", html: null, at: "1" },
    { id: "f", q: "x", at },
    null,
  ];
  storage.raw.set("assistant-thread-1", JSON.stringify({ open: true, items: [good, ...bad] }));
  const store = createThreadStore(storage, "1", () => at);
  assert.deepEqual(store.read(), { open: true, items: [good] });

  storage.raw.set("assistant-thread-1", JSON.stringify({ open: true, items: "nope" }));
  assert.deepEqual(store.read(), { open: true, items: [] });
});

test("users_do_not_mix", () => {
  const storage = memoryStorage();
  const clock = fakeClock();
  const first = createThreadStore(storage, "1", clock.now);
  const second = createThreadStore(storage, "2", clock.now);
  first.addPending("only for user 1");
  assert.equal(first.read().items.length, 1);
  assert.deepEqual(second.read().items, []);
  assert.equal(storage.raw.has("assistant-thread-1"), true);
});

test("resolve_sets_html_and_pending_stays_null", () => {
  const storage = memoryStorage();
  const clock = fakeClock();
  const store = createThreadStore(storage, "1", clock.now);
  const id = store.addPending("question");
  assert.equal(typeof id, "string");

  const reloaded = createThreadStore(storage, "1", clock.now);
  assert.equal(reloaded.read().items[0].html, null);

  reloaded.resolve(id, "<p>answer</p>");
  const again = createThreadStore(storage, "1", clock.now);
  assert.equal(again.read().items[0].html, "<p>answer</p>");
  assert.equal(again.read().items[0].q, "question");
});

test("clear_keeps_open_flag_clearAll_removes_all", () => {
  const storage = memoryStorage();
  const store = createThreadStore(storage, "1", fakeClock().now);
  store.setOpen(true);
  store.addPending("q");
  store.clear();
  assert.deepEqual(store.read(), { open: true, items: [] });

  store.addPending("again");
  store.clearAll();
  assert.equal(storage.raw.has("assistant-thread-1"), false);
  assert.deepEqual(store.read(), { open: false, items: [] });
});

test("throwing_storage_never_throws", () => {
  const broken = () => {
    throw new Error("storage blocked");
  };
  const storage = { getItem: broken, setItem: broken, removeItem: broken };
  const store = createThreadStore(storage, "1", fakeClock().now);
  assert.deepEqual(store.read(), { open: false, items: [] });
  assert.doesNotThrow(() => store.setOpen(true));
  let id = null;
  assert.doesNotThrow(() => {
    id = store.addPending("q");
  });
  assert.equal(typeof id, "string");
  assert.doesNotThrow(() => store.resolve(id, "<p>x</p>"));
  assert.doesNotThrow(() => store.clear());
  assert.doesNotThrow(() => store.clearAll());
});

test("oversized_html_is_stored_as_placeholder", () => {
  const storage = memoryStorage();
  const clock = fakeClock();
  const store = createThreadStore(storage, "1", clock.now);
  const big = store.addPending("big");
  store.resolve(big, "а".repeat(MAX_HTML + 1));
  assert.equal(store.read().items[0].html, '<p class="px-1 text-sm text-slate-500">Хариулт хадгалагдсангүй.</p>');

  const edge = store.addPending("edge");
  store.resolve(edge, "x".repeat(MAX_HTML));
  assert.equal(store.read().items[1].html.length, MAX_HTML);
  assert.equal(store.read().items[1].html, "x".repeat(MAX_HTML));
});

test("previous_context_is_the_last_answer_only", () => {
  assert.equal(lastAnswerContext([]), null);
  assert.equal(lastAnswerContext([{ answered: false, context: null }]), null);
  assert.equal(lastAnswerContext([{ answered: true, context: "a=1" }]), "a=1");
  // the newest answer decides: an older context is not used when the last answer has none
  assert.equal(lastAnswerContext([{ answered: true, context: "a=1" }, { answered: true, context: null }]), null);
  // an unanswered question after the answer does not hide it
  assert.equal(lastAnswerContext([{ answered: true, context: "a=1" }, { answered: false, context: null }]), "a=1");
  assert.equal(
    lastAnswerContext([
      { answered: true, context: "a=1" },
      { answered: true, context: "b=2" },
      { answered: false, context: null },
    ]),
    "b=2"
  );
  assert.equal(lastAnswerContext([{ answered: true, context: "" }]), null);
});

test("follow_up_fields_round_trip_and_old_items_have_none", () => {
  const storage = memoryStorage();
  const clock = fakeClock();
  const store = createThreadStore(storage, "1", clock.now);
  const id = store.addPending("Санхүү", { url: "/assistant/pick/", body: "query=&id=1" });
  const again = createThreadStore(storage, "1", clock.now).read().items[0];
  assert.equal(again.id, id);
  assert.equal(again.url, "/assistant/pick/");
  assert.equal(again.body, "query=&id=1");

  // a typed question has no url or body keys at all
  store.addPending("typed");
  const typed = createThreadStore(storage, "1", clock.now).read().items[1];
  assert.equal("url" in typed, false);
  assert.equal("body" in typed, false);

  // an item written before these fields existed reads as before
  const at = clock.now();
  storage.raw.set("assistant-thread-1", JSON.stringify({ open: false, items: [{ id: "old", q: "old", html: null, at }] }));
  assert.deepEqual(createThreadStore(storage, "1", clock.now).read().items, [{ id: "old", q: "old", html: null, at }]);
});

test("follow_up_bad_fields_are_cleaned_on_read", () => {
  const storage = memoryStorage();
  const at = 1000000;
  const longBody = "a".repeat(2001);
  storage.raw.set(
    "assistant-thread-1",
    JSON.stringify({
      open: false,
      items: [
        { id: "a", q: "x", html: null, at, url: 5, body: "b" },
        { id: "b", q: "x", html: null, at, url: "/ok/", body: longBody },
        { id: "c", q: "x", html: null, at, url: "/ok/", body: 7 },
      ],
    })
  );
  const items = createThreadStore(storage, "1", () => at).read().items;
  assert.equal(items[0].url, "");
  assert.equal(items[1].url, "/ok/");
  assert.equal("body" in items[1], false);
  assert.equal("body" in items[2], false);
});

test("is_relative_path_accepts_only_same_site_paths", () => {
  assert.equal(isRelativePath("/assistant/pick/"), true);
  assert.equal(isRelativePath("/"), true);
  assert.equal(isRelativePath("/reports/staff-list/?x=1"), true);
  assert.equal(isRelativePath("//evil.example/x"), false);
  assert.equal(isRelativePath("/\\evil.example/x"), false);
  assert.equal(isRelativePath("https://evil.example/"), false);
  assert.equal(isRelativePath("assistant/pick/"), false);
  assert.equal(isRelativePath("/a b"), false);
  assert.equal(isRelativePath("/a\nb"), false);
  assert.equal(isRelativePath(""), false);
  assert.equal(isRelativePath(null), false);
  assert.equal(isRelativePath("/" + "a".repeat(2000)), false);
});

test("oversize_answer_keeps_its_context_after_reload", () => {
  const storage = memoryStorage();
  const clock = fakeClock();
  const store = createThreadStore(storage, "1", clock.now);
  const id = store.addPending("refine");
  const ctx = 'department=3&q="x"&y=<1>';
  store.resolve(id, "а".repeat(MAX_HTML + 1), ctx);

  const reloaded = createThreadStore(storage, "1", clock.now).read().items[0];
  assert.equal(reloaded.context, ctx);
  // the stored placeholder carries the attribute, escaped, and decodes back to the context
  const attr = reloaded.html.match(/data-assistant-context="([^"]*)"/);
  assert.ok(attr);
  const decoded = attr[1]
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
  assert.equal(decoded, ctx);
  // the lookup the panel uses over the restored thread finds the context
  const entries = [{ answered: reloaded.html !== null, context: reloaded.context || null }];
  assert.equal(lastAnswerContext(entries), ctx);
});

test("oversize_answer_without_context_has_none", () => {
  const storage = memoryStorage();
  const clock = fakeClock();
  const store = createThreadStore(storage, "1", clock.now);
  const id = store.addPending("plain");
  store.resolve(id, "а".repeat(MAX_HTML + 1));
  const item = createThreadStore(storage, "1", clock.now).read().items[0];
  assert.equal("context" in item, false);
  assert.equal(item.html.includes("data-assistant-context"), false);
  assert.equal(lastAnswerContext([{ answered: true, context: item.context || null }]), null);
});

test("oversize_answer_with_too_long_context_stores_no_context", () => {
  const storage = memoryStorage();
  const clock = fakeClock();
  const store = createThreadStore(storage, "1", clock.now);
  const id = store.addPending("long");
  store.resolve(id, "а".repeat(MAX_HTML + 1), "x".repeat(2001));
  const item = createThreadStore(storage, "1", clock.now).read().items[0];
  assert.equal("context" in item, false);
  assert.equal(item.html.includes("data-assistant-context"), false);
});

test("typed_question_body_adds_prev_only_with_a_context", () => {
  assert.equal(typedQuestionBody("санхүү", null), "q=" + encodeURIComponent("санхүү"));
  assert.equal(typedQuestionBody("a", ""), "q=a");
  assert.equal(typedQuestionBody("a", "department=1&state=working"), "q=a&prev=department%3D1%26state%3Dworking");
});
