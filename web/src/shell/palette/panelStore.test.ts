// Port of the open-flag cases of app/static/js/thread_store.test.mjs against panelStore.ts. The thread cases (items,
// ages, follow-ups, context) belong to step 6 and are not ported here. The storage key and value shape must match
// thread_store.js byte for byte: "assistant-thread-<userId>" holding {"open": boolean, "items": [...]}.
import { describe, expect, it } from "vitest";
import { createPanelStore } from "./panelStore";

// An in-memory stand-in for sessionStorage. `raw` lets a test write or inspect the stored string directly.
function memoryStorage() {
  const raw = new Map<string, string>();
  return {
    raw,
    getItem: (key: string) => (raw.has(key) ? (raw.get(key) as string) : null),
    setItem: (key: string, value: string) => {
      raw.set(key, String(value));
    },
    removeItem: (key: string) => {
      raw.delete(key);
    },
  } as unknown as Storage & { raw: Map<string, string> };
}

describe("panelStore (open flag, thread_store.js)", () => {
  it("corrupt_json_reads_empty", () => {
    const storage = memoryStorage();
    storage.raw.set("assistant-thread-1", "{bad");
    const store = createPanelStore(storage, 1);
    expect(store.isOpen()).toBe(false);
  });

  it("users_do_not_mix", () => {
    const storage = memoryStorage();
    const first = createPanelStore(storage, 1);
    const second = createPanelStore(storage, 2);
    first.setOpen(true);
    expect(first.isOpen()).toBe(true);
    expect(second.isOpen()).toBe(false);
    expect(storage.raw.has("assistant-thread-1")).toBe(true);
    expect(storage.raw.has("assistant-thread-2")).toBe(false);
  });

  it("throwing_storage_never_throws", () => {
    const broken = () => {
      throw new Error("storage blocked");
    };
    const storage = { getItem: broken, setItem: broken, removeItem: broken } as unknown as Storage;
    const store = createPanelStore(storage, 1);
    expect(store.isOpen()).toBe(false);
    expect(() => store.setOpen(true)).not.toThrow();
    expect(() => store.setOpen(false)).not.toThrow();
  });

  it("open flag is written in the thread_store value shape", () => {
    const storage = memoryStorage();
    const store = createPanelStore(storage, 7);
    store.setOpen(true);
    expect(storage.raw.get("assistant-thread-7")).toBe('{"open":true,"items":[]}');
  });

  // setOpen writes the stored items back exactly as they were. It does not clean them: the thread's cleaning (isItem,
  // the one-hour age, the cap of 10, cleanExtras) is step 6's job, and it must happen on read there.
  it("setOpen leaves stored items untouched", () => {
    const storage = memoryStorage();
    const store = createPanelStore(storage, 7);
    const items = [{ id: "1-1", q: "q", html: null, at: 5 }];
    storage.raw.set("assistant-thread-7", JSON.stringify({ open: true, items }));
    store.setOpen(false);
    expect(JSON.parse(storage.raw.get("assistant-thread-7") as string)).toEqual({ open: false, items });
  });

  it("only the literal true opens the flag", () => {
    const storage = memoryStorage();
    storage.raw.set("assistant-thread-1", JSON.stringify({ open: "true", items: [] }));
    expect(createPanelStore(storage, 1).isOpen()).toBe(false);
    storage.raw.set("assistant-thread-1", JSON.stringify([true]));
    expect(createPanelStore(storage, 1).isOpen()).toBe(false);
  });

  it("test_store_without_storage_keeps_state_in_memory", () => {
    const store = createPanelStore(null, 1);
    expect(store.isOpen()).toBe(false);
    store.setOpen(true);
    expect(store.isOpen()).toBe(true);
    store.setOpen(false);
    expect(store.isOpen()).toBe(false);
  });

  it("test_store_survives_throwing_storage", () => {
    const broken = () => {
      throw new Error("quota");
    };
    const storage = { getItem: broken, setItem: broken, removeItem: broken } as unknown as Storage;
    const store = createPanelStore(storage, 1);
    expect(() => store.setOpen(true)).not.toThrow();
    expect(store.isOpen()).toBe(false);
  });
});
