// Recents («Сүүлд нээсэн») of palette.js: readRecent, remember and the `recent` parameter sent to /employees/palette/.
import { describe, expect, it } from "vitest";
import { RECENT_KEY_PREFIX, RECENT_MAX, readRecent, recentKey, recentParam, remember } from "./recents";

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

describe("recents", () => {
  it("keeps the palette.js key prefix and cap", () => {
    expect(RECENT_KEY_PREFIX).toBe("palette-recent-");
    expect(RECENT_MAX).toBe(5);
  });

  it("the key is \"palette-recent-\" + the panel's data-user", () => {
    const storage = memoryStorage();
    remember(storage, "p:1", "42");
    expect(storage.raw.has("palette-recent-42")).toBe(true);
    expect(recentKey(42)).toBe("palette-recent-42");
    expect(recentKey("42")).toBe("palette-recent-42");
  });

  it("a stored value that is not a string in the ref shape is dropped on read", () => {
    const storage = memoryStorage();
    storage.raw.set(RECENT_KEY_PREFIX + "1", JSON.stringify([7, null, "p:x", "s:relative", "p:9"]));
    expect(readRecent(storage, "1")).toEqual(["p:9"]);
  });

  it("readRecent drops values that are not references and caps the list", () => {
    const storage = memoryStorage();
    storage.raw.set(
      RECENT_KEY_PREFIX + "1",
      JSON.stringify(["p:1", "bad", 5, "s:/a/", "p:2", "p:3", "p:4", "p:5"])
    );
    expect(readRecent(storage, "1")).toEqual(["p:1", "s:/a/", "p:2", "p:3", "p:4"]);
  });

  it("readRecent reads a corrupt or non-array value as empty", () => {
    const storage = memoryStorage();
    storage.raw.set(RECENT_KEY_PREFIX + "1", "{bad");
    expect(readRecent(storage, "1")).toEqual([]);
    storage.raw.set(RECENT_KEY_PREFIX + "1", JSON.stringify({ a: 1 }));
    expect(readRecent(storage, "1")).toEqual([]);
  });

  it("recents are per user", () => {
    const storage = memoryStorage();
    remember(storage, "p:1", "1");
    expect(readRecent(storage, "2")).toEqual([]);
    expect(readRecent(storage, "1")).toEqual(["p:1"]);
  });

  it("test_remember_drops_duplicates_and_cuts", () => {
    const storage = memoryStorage();
    remember(storage, "p:1", "1");
    remember(storage, "p:2", "1");
    remember(storage, "p:3", "1");
    remember(storage, "p:1", "1");
    expect(readRecent(storage, "1")).toEqual(["p:1", "p:3", "p:2"]);

    remember(storage, "p:4", "1");
    remember(storage, "p:5", "1");
    remember(storage, "p:6", "1");
    expect(readRecent(storage, "1")).toEqual(["p:6", "p:5", "p:4", "p:1", "p:3"]);
  });

  it("remember ignores an empty or malformed reference", () => {
    const storage = memoryStorage();
    remember(storage, "", "1");
    remember(storage, "x:9", "1");
    remember(storage, "p:abc", "1");
    expect(storage.raw.has(RECENT_KEY_PREFIX + "1")).toBe(false);
  });

  it("recentParam is the comma list of the recents", () => {
    const storage = memoryStorage();
    remember(storage, "p:1", "1");
    remember(storage, "s:/reports/", "1");
    expect(recentParam(storage, "1")).toBe("s:/reports/,p:1");
    expect(recentParam(storage, "2")).toBe("");
  });

  it("test_recentParam_never_splits_a_ref", () => {
    const storage = memoryStorage();
    const long = (n: number) => "s:/" + "a".repeat(n) + "/";
    const refs = [long(190), long(190), long(190)];
    storage.raw.set(RECENT_KEY_PREFIX + "1", JSON.stringify(refs));
    const param = recentParam(storage, "1");
    expect(param.length).toBeLessThanOrEqual(400);
    const parts = param === "" ? [] : param.split(",");
    expect(parts.every((part) => refs.includes(part))).toBe(true);
    expect(parts).toEqual(refs.slice(0, parts.length));
    expect(parts.length).toBe(2);
  });

  it("without storage nothing is remembered and the param is empty", () => {
    expect(readRecent(null, "1")).toEqual([]);
    expect(() => remember(null, "p:1", "1")).not.toThrow();
    expect(recentParam(null, "1")).toBe("");
  });

  it("an empty user id reads nothing and writes nothing (no shared bare key)", () => {
    const storage = memoryStorage();
    storage.raw.set(RECENT_KEY_PREFIX, JSON.stringify(["p:1"]));
    expect(readRecent(storage, "")).toEqual([]);
    expect(() => remember(storage, "p:2", "")).not.toThrow();
    expect(storage.raw.get(RECENT_KEY_PREFIX)).toBe(JSON.stringify(["p:1"]));
    expect([...storage.raw.keys()]).toEqual([RECENT_KEY_PREFIX]);
  });

  it("an empty user id gives an empty recentParam even when the bare key holds refs", () => {
    const storage = memoryStorage();
    storage.raw.set(RECENT_KEY_PREFIX, JSON.stringify(["p:1", "s:/reports/"]));
    expect(recentParam(storage, "")).toBe("");
  });

  it("remember with an empty user id does not write a key", () => {
    const storage = memoryStorage();
    remember(storage, "p:1", "");
    expect(storage.raw.size).toBe(0);
  });

  it("a throwing storage never throws", () => {
    const broken = () => {
      throw new Error("blocked");
    };
    const storage = { getItem: broken, setItem: broken, removeItem: broken } as unknown as Storage;
    expect(readRecent(storage, "1")).toEqual([]);
    expect(() => remember(storage, "p:1", "1")).not.toThrow();
    expect(recentParam(storage, "1")).toBe("");
  });
});
