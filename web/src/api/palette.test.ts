// The harness is imported first: it stubs fetch before ./client (and so ./palette) load.
import { fetchMock, jsonResponse, resetFetch, urlOf } from "./testSupport";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fetchPalette, type PaletteOut } from "./palette";

const ANSWER: PaletteOut = {
  empty: false,
  empty_text: "Юу ч олдсонгүй",
  fallback: [],
  fallback_heading: "Эсвэл нээх:",
  groups: [],
};

describe("fetchPalette", () => {
  beforeEach(() => {
    resetFetch();
    fetchMock.mockResolvedValue(jsonResponse(200, ANSWER));
  });
  afterEach(() => resetFetch());

  it("sends a typed query with q only", async () => {
    await fetchPalette({ q: "Бат" });
    const url = urlOf(0);
    expect(url.pathname).toBe("/api/v1/palette");
    expect(url.searchParams.get("q")).toBe("Бат");
    expect(url.searchParams.has("more")).toBe(false);
    expect(url.searchParams.has("recent")).toBe(false);
    expect(url.searchParams.has("from")).toBe(false);
  });

  it("sends more=1 for show all", async () => {
    await fetchPalette({ q: "Бат", more: true });
    expect(urlOf(0).searchParams.get("more")).toBe("1");
  });

  it("sends recent and from for the empty box", async () => {
    await fetchPalette({ q: "", recent: "p:3,s:/employees/", from: "/leave/" });
    const url = urlOf(0);
    expect(url.searchParams.get("q")).toBe("");
    expect(url.searchParams.get("recent")).toBe("p:3,s:/employees/");
    expect(url.searchParams.get("from")).toBe("/leave/");
  });

  it("returns the answer as sent", async () => {
    await expect(fetchPalette({ q: "x" })).resolves.toEqual(ANSWER);
  });

  it("rejects when the request fails", async () => {
    fetchMock.mockResolvedValue(jsonResponse(500, { field_errors: {}, form_errors: [] }));
    await expect(fetchPalette({ q: "x" })).rejects.toThrow("palette request failed");
  });

  it("passes the abort signal to the request", async () => {
    const controller = new AbortController();
    await fetchPalette({ q: "x" }, controller.signal);
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.signal.aborted).toBe(false);
    controller.abort();
    expect(request.signal.aborted).toBe(true);
  });
});
