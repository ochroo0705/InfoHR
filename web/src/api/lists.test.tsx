// The harness is imported first: it stubs fetch before ./client (and so ./lists) load.
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
import {
  listKeys,
  quickAddEntry,
  useDeleteEntry,
  useListForm,
  useListPage,
  useListsIndex,
  useMeaning,
  useSaveEntry,
  useSaveMeaning,
  type ListFormOut,
  type ListMeaningOut,
  type ListPageOut,
  type ListsIndexOut,
} from "./lists";
import type { ApiFailure } from "./mutate";

const INDEX: ListsIndexOut = {
  items: [{ slug: "bank", label: "Банк", count: 4, hits: 0 }],
  show_meanings: true,
  meanings_count: 2,
  q: "",
};

const MEANING: ListMeaningOut = {
  rows: [{ key: "a", label: "Банк", hint: "h", current: 3, options: [{ value: 3, label: "Хаан" }] }],
};

const PAGE: ListPageOut = {
  slug: "bank",
  label: "Банк",
  columns: [{ name: "name", label: "Нэр" }],
  rows: [{ id: 5, cells: ["Хаан"] }],
};

const FORM: ListFormOut = {
  title: "Банк: засах",
  fields: [
    { name: "name", label: "Нэр", kind: "text", required: true, max_length: 50, value: "Хаан", choices: [], errors: [] },
  ],
  can_delete: true,
};

const OK = { ok: true, form_errors: [], field_errors: {} };
const REFUSED = { ok: false, form_errors: ["Бүртгэлтэй"], field_errors: { name: ["Хоосон"] } };

// The JSON body of the request sent at call `index` of fetchMock.
async function bodyOf(index: number): Promise<unknown> {
  return JSON.parse(await (fetchMock.mock.calls[index][0] as Request).text());
}

describe("list API", () => {
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

  it("listKeys prefix every list key with lists, the page and the forms with their slug", () => {
    expect(listKeys.index("x")).toEqual(["lists", "index", "x"]);
    expect(listKeys.meaning()).toEqual(["lists", "meaning"]);
    expect(listKeys.page("bank")).toEqual(["lists", "page", "bank"]);
    expect(listKeys.form("bank", undefined)).toEqual(["lists", "form", "bank", "add"]);
    expect(listKeys.form("bank", 5)).toEqual(["lists", "form", "bank", 5]);
  });

  it("useListsIndex sends the search text as q", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, INDEX));

    const { result } = renderHook(() => useListsIndex("банк"), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/lists");
    expect(urlOf(0).searchParams.get("q")).toBe("банк");
    expect(result.current.data?.items[0].slug).toBe("bank");
  });

  it("useMeaning gets /api/v1/lists/meaning", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, MEANING));

    const { result } = renderHook(() => useMeaning(), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/lists/meaning");
    expect(result.current.data?.rows[0].current).toBe(3);
  });

  it("useListPage gets the page of one list by its slug", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, PAGE));

    const { result } = renderHook(() => useListPage("bank"), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/lists/bank");
    expect(result.current.data?.rows[0].cells).toEqual(["Хаан"]);
  });

  it("useListForm waits until the pop-up is open (enabled)", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, FORM));

    const { result, rerender } = renderHook(({ on }: { on: boolean }) => useListForm("bank", 5, on), {
      wrapper: wrapperFor(client),
      initialProps: { on: false },
    });
    await act(async () => undefined);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");

    rerender({ on: true });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("useListForm sends no pk for the add form and the pk for the edit form", async () => {
    // A fresh Response per call: one Response body can be read only once.
    fetchMock.mockImplementation(async () => jsonResponse(200, FORM));

    const add = renderHook(() => useListForm("bank", undefined, true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(add.result.current.isSuccess).toBe(true));
    expect(urlOf(0).pathname).toBe("/api/v1/lists/bank/form");
    expect(urlOf(0).searchParams.has("pk")).toBe(false);

    const edit = renderHook(() => useListForm("bank", -5, true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(edit.result.current.isSuccess).toBe(true));
    expect(urlOf(1).pathname).toBe("/api/v1/lists/bank/form");
    expect(urlOf(1).searchParams.get("pk")).toBe("-5");
  });

  it("useSaveMeaning posts the values to /api/v1/lists/meaning and refreshes the meaning", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSaveMeaning(), { wrapper: wrapperFor(client) });

    await act(async () => {
      await result.current.mutateAsync({ a: "", b: "7" });
    });

    expect(urlOf(0).pathname).toBe("/api/v1/lists/meaning");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(await bodyOf(0)).toEqual({ values: { a: "", b: "7" } });
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["lists", "meaning"] });
  });

  it("useSaveEntry adds an entry (no pk) to /api/v1/lists/{slug} and refreshes the index, the page, the forms and the meaning", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSaveEntry("bank"), { wrapper: wrapperFor(client) });

    let reply: unknown;
    await act(async () => {
      reply = await result.current.mutateAsync({ name: "Хаан" });
    });

    expect(reply).toEqual(OK);
    expect(urlOf(0).pathname).toBe("/api/v1/lists/bank");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(await bodyOf(0)).toEqual({ values: { name: "Хаан" } });
    const keys = invalidatedKeys(spy);
    expect(keys).toContainEqual({ queryKey: ["lists", "index"] });
    expect(keys).toContainEqual({ queryKey: ["lists", "page", "bank"] });
    expect(keys).toContainEqual({ queryKey: ["lists", "form", "bank"] });
    expect(keys).toContainEqual({ queryKey: ["lists", "meaning"] });
  });

  it("useSaveEntry changes entry 5 at /api/v1/lists/{slug}/{pk}", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const { result } = renderHook(() => useSaveEntry("bank", 5), { wrapper: wrapperFor(client) });

    await act(async () => {
      await result.current.mutateAsync({ name: "Голомт" });
    });

    expect(urlOf(0).pathname).toBe("/api/v1/lists/bank/5");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(await bodyOf(0)).toEqual({ values: { name: "Голомт" } });
  });

  it("useSaveEntry invalidates nothing when the write is refused (ok false)", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, REFUSED));
    const spy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSaveEntry("bank", 5), { wrapper: wrapperFor(client) });

    let reply: { ok: boolean; field_errors: Record<string, string[]> } | undefined;
    await act(async () => {
      reply = await result.current.mutateAsync({ name: "" });
    });

    expect(reply?.ok).toBe(false);
    expect(reply?.field_errors.name).toEqual(["Хоосон"]);
    expect(spy).not.toHaveBeenCalled();
  });

  it("useDeleteEntry posts to /api/v1/lists/{slug}/{pk}/delete and refreshes the list", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useDeleteEntry("bank", 5), { wrapper: wrapperFor(client) });

    await act(async () => {
      await result.current.mutateAsync(undefined);
    });

    expect(urlOf(0).pathname).toBe("/api/v1/lists/bank/5/delete");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["lists", "page", "bank"] });
  });

  it("useDeleteEntry keeps the entry and invalidates nothing when the entry is in use (ok false)", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { ok: false, form_errors: ["Энэ бичлэгийг 2 газарт ашигласан тул устгах боломжгүй."], field_errors: {} }),
    );
    const spy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useDeleteEntry("bank", 5), { wrapper: wrapperFor(client) });

    let reply: { ok: boolean; form_errors: string[] } | undefined;
    await act(async () => {
      reply = await result.current.mutateAsync(undefined);
    });

    expect(reply?.ok).toBe(false);
    expect(reply?.form_errors[0]).toContain("2 газарт");
    expect(spy).not.toHaveBeenCalled();
  });

  it("a 403 from a list read is an ApiFailure with status 403 and code forbidden, and is not retried", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: [], code: "forbidden" }));

    const { result } = renderHook(() => useListsIndex(""), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    const failure = result.current.error as ApiFailure;
    expect(failure.status).toBe(403);
    expect(failure.code).toBe("forbidden");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("a 403 from a save is an ApiFailure with status 403, with no CSRF retry", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(
      jsonResponse(403, { field_errors: {}, form_errors: ["Эрх байхгүй"], code: "forbidden" }),
    );
    const { result } = renderHook(() => useSaveEntry("bank"), { wrapper: wrapperFor(client) });

    let caught: unknown;
    await act(async () => {
      try {
        await result.current.mutateAsync({ name: "x" });
      } catch (error) {
        caught = error;
      }
    });

    const failure = caught as ApiFailure;
    expect(failure.status).toBe(403);
    expect(failure.code).toBe("forbidden");
    expect(failure.formErrors).toEqual(["Эрх байхгүй"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("the write sends the CSRF token in X-CSRFToken", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const { result } = renderHook(() => useDeleteEntry("bank", 5), { wrapper: wrapperFor(client) });

    await act(async () => {
      await result.current.mutateAsync(undefined);
    });

    expect((fetchMock.mock.calls[0][0] as Request).headers.get("X-CSRFToken")).toBe("tok");
  });

  it("quickAddEntry posts {values} to /api/v1/lists/{slug}/quick and returns the picked entry", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { value: 9, label: "Хаан", existed: true }));

    const reply = await quickAddEntry("bank", { name: "Хаан" });

    expect(reply).toEqual({ value: 9, label: "Хаан", existed: true });
    expect(urlOf(0).pathname).toBe("/api/v1/lists/bank/quick");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(await bodyOf(0)).toEqual({ values: { name: "Хаан" } });
  });

  it("quickAddEntry returns the refusal (error and field_errors) on 400", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(400, { error: "Нэр хоосон байна", field_errors: { name: ["Нэр хоосон байна"] } }),
    );

    const reply = await quickAddEntry("bank", { name: "" });

    expect("error" in reply && reply.error).toBe("Нэр хоосон байна");
    expect("field_errors" in reply && reply.field_errors.name).toEqual(["Нэр хоосон байна"]);
  });

  it("quickAddEntry throws an ApiFailure with status 403 when the user has no right", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: [], code: "forbidden" }));

    let caught: unknown;
    try {
      await quickAddEntry("bank", { name: "x" });
    } catch (error) {
      caught = error;
    }

    expect((caught as ApiFailure).status).toBe(403);
    expect((caught as ApiFailure).code).toBe("forbidden");
  });
});
