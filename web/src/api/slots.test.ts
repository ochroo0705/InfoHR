// The harness is imported first: it stubs fetch before ./client (and so ./slots) load.
import {
  fetchMock,
  invalidatedKeys,
  jsonResponse,
  newClient,
  resetFetch,
  resetObservers,
  urlOf,
  wrapperFor,
} from "./testSupport";
import type { QueryClient } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import { focusManager, onlineManager } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "./client";
import { deleteSlot, saveSlot, slotListKey, useSlotList, useSlotOptions, type SlotListOut } from "./slots";

const TOTALS = { posts: 3, used: 2, free: 1 };

const LIST_PAGE_1: SlotListOut = {
  year: 2026,
  rows: [
    {
      id: 1,
      position: "Нягтлан",
      position_id: 1,
      branch: "Төв",
      branch_id: 2,
      kind: "Main",
      kind_label: "Үндсэн",
      posts: 2,
      used: 1,
      free: 1,
      free_class: "",
    },
  ],
  next_offset: 60,
  totals: TOTALS,
  enforce: false,
  settings_url: "/admin/employees/companysettings/",
  empty_text: "2026 оны орон тоо бүртгэгдээгүй",
};

const LIST_PAGE_2: SlotListOut = { ...LIST_PAGE_1, next_offset: null, rows: [] };

describe("slot API", () => {
  let client: QueryClient;

  beforeEach(() => {
    resetFetch();
    setCsrf("");
    client = newClient();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    resetObservers();
    focusManager.setFocused(true);
    onlineManager.setOnline(true);
  });

  it("slotListKey is the slots key with the year", () => {
    expect(slotListKey(2026)).toEqual(["slots", 2026]);
    expect(slotListKey(null)).toEqual(["slots", null]);
  });

  it("useSlotList sends the year and offset, then loads the next batch at next_offset", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, LIST_PAGE_1))
      .mockResolvedValueOnce(jsonResponse(200, LIST_PAGE_2));

    const { result } = renderHook(() => useSlotList(2026), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/slots");
    expect(urlOf(0).searchParams.get("year")).toBe("2026");
    expect(urlOf(0).searchParams.get("offset")).toBe("0");
    expect(result.current.hasNextPage).toBe(true);

    await act(async () => {
      await result.current.fetchNextPage();
    });

    expect(urlOf(1).searchParams.get("offset")).toBe("60");
    await vi.waitFor(() => expect(result.current.data?.pages.length).toBe(2));
    expect(result.current.hasNextPage).toBe(false);
  });

  it("useSlotList sends no year when the year is null (the server picks the current year)", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, LIST_PAGE_2));

    const { result } = renderHook(() => useSlotList(null), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).searchParams.has("year")).toBe(false);
    expect(urlOf(0).searchParams.get("offset")).toBe("0");
  });

  it("useSlotList starts again at offset 0 when the year changes and keeps no old rows", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, LIST_PAGE_2));

    const { result, rerender } = renderHook((year: number) => useSlotList(year), {
      wrapper: wrapperFor(client),
      initialProps: 2026,
    });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    rerender(2027);
    expect(result.current.data).toBeUndefined();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    expect(urlOf(1).searchParams.get("year")).toBe("2027");
    expect(urlOf(1).searchParams.get("offset")).toBe("0");
  });

  it("useSlotOptions asks for the options of the year", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, {
        positions: [],
        branches: [],
        kinds: [],
        year: 2026,
        min_year: 2020,
        max_year: 2030,
        hint: "h",
      }),
    );

    const { result } = renderHook(() => useSlotOptions(2026), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/slots/options");
    expect(urlOf(0).searchParams.get("year")).toBe("2026");
  });

  it("saveSlot posts a new row to /api/v1/slots and invalidates the slots keys when it is saved", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true, id: 5, field_errors: {}, form_errors: [] }));
    const spy = vi.spyOn(client, "invalidateQueries");
    const body = { position: 1, branch: 2, kind: "Main", qty: 3, year: 2026 };

    const result = await saveSlot(client, null, body);

    expect(result.ok).toBe(true);
    expect(urlOf(0).pathname).toBe("/api/v1/slots");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["slots"] });
  });

  it("saveSlot posts a change to /api/v1/slots/{pk}", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true, id: 7, field_errors: {}, form_errors: [] }));
    const body = { position: 1, branch: 2, kind: "Main", qty: 4, year: 2026 };

    await saveSlot(client, 7, body);

    expect(urlOf(0).pathname).toBe("/api/v1/slots/7");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
  });

  it("saveSlot invalidates nothing when the write is refused (ok false)", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { ok: false, id: null, field_errors: { qty: ["bad"] }, form_errors: [] }),
    );
    const spy = vi.spyOn(client, "invalidateQueries");

    const result = await saveSlot(client, null, { position: 1, branch: 2, kind: "Main", qty: 0, year: 2026 });

    expect(result.ok).toBe(false);
    expect(spy).not.toHaveBeenCalled();
  });

  it("deleteSlot posts to /api/v1/slots/{pk}/delete and invalidates the slots keys", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true, id: 7, field_errors: {}, form_errors: [] }));
    const spy = vi.spyOn(client, "invalidateQueries");

    await deleteSlot(client, 7);

    expect(urlOf(0).pathname).toBe("/api/v1/slots/7/delete");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["slots"] });
  });
});
