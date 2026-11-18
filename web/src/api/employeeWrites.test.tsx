import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "./client";
import type { ApiFailure } from "./mutate";
import {
  fieldErrorsFor,
  useAddNote,
  useAddRow,
  useCorrectionForm,
  useCreateLogin,
  useDeleteRow,
  useEditRow,
  usePageForm,
  useRowForm,
  useSavePage,
  useSaveSection,
  useSubmitCorrection,
} from "./employeeWrites";

// fetch is stubbed before the api client is imported (openapi-fetch captures fetch when it is created), and it
// delegates to a mock that each test sets up. Relative URLs are resolved against the page, as in screens.test.tsx.
const h = vi.hoisted(() => {
  const fetchMock = vi.fn();
  const NativeRequest = globalThis.Request;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => fetchMock(input, init));
  vi.stubGlobal(
    "Request",
    class extends NativeRequest {
      constructor(input: RequestInfo | URL, init?: RequestInit) {
        super(typeof input === "string" ? new URL(input, window.location.origin) : input, init);
      }
    },
  );
  return { fetchMock };
});
const fetchMock = h.fetchMock;

const OK_RESULT = {
  ok: true,
  field_errors: {},
  form_errors: [],
  conflicts: {},
  loaded: "L2",
  si_loaded: "S2",
  tab: "",
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// The API's CSRF failure, as api/main.py answers it: a JSON 403 with code "csrf_failed".
function csrfFailure(): Response {
  return jsonResponse(403, {
    field_errors: {},
    form_errors: ["CSRF check Failed"],
    code: "csrf_failed",
  });
}

function metaBody(csrf: string) {
  return {
    backend_version: "dev",
    api_version: 1,
    company: { name: "", logo_url: null },
    modules: {},
    csrf,
    user: null,
  };
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

// Runs a mutation that is expected to fail and returns what it rejected with.
async function rejectionOf(run: () => Promise<unknown>): Promise<unknown> {
  let caught: unknown;
  await act(async () => {
    try {
      await run();
    } catch (error) {
      caught = error;
    }
  });
  return caught;
}

// Observers that keep a query active, so an invalidation refetches it. Each one is unsubscribed in afterEach.
const unsubscribes: (() => void)[] = [];

function observe(client: QueryClient, queryKey: unknown[]) {
  const queryFn = vi.fn(async () => ({ at: Date.now() }));
  const observer = new QueryObserver(client, { queryKey, queryFn });
  unsubscribes.push(observer.subscribe(() => undefined));
  return queryFn;
}

function urlOf(index: number): URL {
  return new URL((fetchMock.mock.calls[index][0] as Request).url);
}

// The invalidations a spy saw, as query keys with their exact flag.
function invalidatedKeys(spy: { mock: { calls: unknown[][] } }) {
  return spy.mock.calls.map((call) => call[0] as { queryKey: unknown[]; exact?: boolean });
}

describe("employee write hooks", () => {
  let client: QueryClient;

  beforeEach(() => {
    fetchMock.mockReset();
    setCsrf("");
    client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
  });

  afterEach(() => {
    cleanup();
    // Spies (the FormData append check) and query observers are undone after every test, pass or fail.
    vi.restoreAllMocks();
    while (unsubscribes.length > 0) unsubscribes.pop()?.();
  });

  it("a successful page save invalidates exactly the listed keys", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, OK_RESULT));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSavePage(5), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: { loaded: "L1", "first-name": "Анна" } });
    });

    expect(invalidatedKeys(spy)).toEqual([
      { queryKey: ["employee", 5], exact: true },
      { queryKey: ["employee", 5, "work"], exact: true },
      { queryKey: ["employee", 5, "salary"], exact: true },
      { queryKey: ["employee", 5, "personal"], exact: true },
      { queryKey: ["employee", 5, "activity"], exact: true },
      { queryKey: ["employee", 5, "page-form"], exact: true },
    ]);
  });

  it("a refused page save (ok false) invalidates nothing", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { ...OK_RESULT, ok: false, field_errors: { "first-name": ["Хоосон"] } }),
    );
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSavePage(5), { wrapper: wrapperFor(client) });
    let answer: unknown;
    await act(async () => {
      answer = await result.current.mutateAsync({ values: { loaded: "L1" } });
    });

    expect((answer as { ok: boolean }).ok).toBe(false);
    expect(spy).not.toHaveBeenCalled();
  });

  it("a successful section save invalidates the employee, personal, activity and page-form keys", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK_RESULT));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSaveSection(5, "contact"), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: { phone: "99" }, loaded: "L1" });
    });

    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/personal/sections/contact");
    expect(invalidatedKeys(spy).map((k) => k.queryKey)).toEqual([
      ["employee", 5],
      ["employee", 5, "personal"],
      ["employee", 5, "activity"],
      ["employee", 5, "page-form"],
    ]);
  });

  it("the multipart page save carries values_json, the photo and photo_clear", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, OK_RESULT));
    // The fields are checked where they are appended to the FormData: reading the request body back in jsdom does not
    // finish when it holds a file, so the request is checked for its method, token and multipart type only.
    const append = vi.spyOn(FormData.prototype, "append");

    const { result } = renderHook(() => useSavePage(5), { wrapper: wrapperFor(client) });
    const photo = new File(["png-bytes"], "photo.png", { type: "image/png" });
    await act(async () => {
      await result.current.mutateAsync({ values: { loaded: "L1", "si-loaded": "S1" }, photo, photoClear: false });
    });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(request.headers.get("X-CSRFToken")).toBe("tok");
    expect(request.headers.get("content-type")).toMatch(/^multipart\/form-data/);
    expect(append).toHaveBeenCalledWith("values_json", JSON.stringify({ loaded: "L1", "si-loaded": "S1" }));
    expect(append).toHaveBeenCalledWith("photo", photo);
    expect(append).toHaveBeenCalledWith("photo_clear", "false");
  });

  it("a CSRF 403 on the page save refetches meta and retries once", async () => {
    setCsrf("stale");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh")))
      .mockResolvedValueOnce(jsonResponse(200, OK_RESULT));

    const { result } = renderHook(() => useSavePage(5), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: { loaded: "L1" } });
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(urlOf(1).pathname).toBe("/api/v1/meta");
    expect((fetchMock.mock.calls[2][0] as Request).headers.get("X-CSRFToken")).toBe("fresh");
  });

  it("fieldErrorsFor merges the messages and the conflicts by field name", () => {
    const merged = fieldErrorsFor({
      field_errors: { "first-name": ["Хоосон"], phone: ["Буруу"] },
      conflicts: { phone: "Өөр хүн өөрчилсөн", email: "Өөр хүн өөрчилсөн" },
    });

    expect(merged).toEqual({
      "first-name": { errors: ["Хоосон"] },
      phone: { errors: ["Буруу"], conflict: "Өөр хүн өөрчилсөн" },
      email: { errors: [], conflict: "Өөр хүн өөрчилсөн" },
    });
  });

  it("useAddRow sends the hidden loaded values it is given, as they are", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, OK_RESULT));
    const values = { loaded_bank: "B1", loaded_account: "A1", bank: "Голомт" };

    const { result } = renderHook(() => useAddRow(5, "bank"), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values });
    });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/personal/bank");
    expect(JSON.parse(await request.text())).toEqual({ values });
  });

  it("useEditRow posts to the row key with the hidden loaded values", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK_RESULT));
    const values = { loaded_bank: "B1", bank: "Хаан" };

    const { result } = renderHook(() => useEditRow(5, "bank", 42), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values });
    });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/personal/bank/42");
    expect(JSON.parse(await request.text())).toEqual({ values });
  });

  it("useCreateLogin returns the password and invalidates nothing", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, { username: "anna.b", password: "Temp-7x" }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateLogin(5), { wrapper: wrapperFor(client) });
    let answer: unknown;
    await act(async () => {
      answer = await result.current.mutateAsync("anna.b");
    });

    expect(answer).toEqual({ username: "anna.b", password: "Temp-7x" });
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/login");
    expect(spy).not.toHaveBeenCalled();
  });

  it("a 400 rejects with an ApiFailure carrying the field and form errors", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(400, { field_errors: { username: ["Буруу нэр"] }, form_errors: ["Логин байна"] }),
    );

    const { result } = renderHook(() => useCreateLogin(5), { wrapper: wrapperFor(client) });
    const caught = (await rejectionOf(() => result.current.mutateAsync("bad name"))) as ApiFailure;

    expect(caught.status).toBe(400);
    expect(caught.fieldErrors).toEqual({ username: ["Буруу нэр"] });
    expect(caught.formErrors).toEqual(["Логин байна"]);
  });

  it("useCorrectionForm and useSubmitCorrection use the job correction route for a job path", async () => {
    setCsrf("tok");
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { title: "", fields: [], hidden: {}, empty_lists: [], can_delete: false }))
      .mockResolvedValueOnce(jsonResponse(200, OK_RESULT));

    const form = renderHook(() => useCorrectionForm(5, "job/9/correct", true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(form.result.current.isSuccess).toBe(true));
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/job/9/correct/form");

    const submit = renderHook(() => useSubmitCorrection(5, "job/9/correct"), { wrapper: wrapperFor(client) });
    await act(async () => {
      await submit.result.current.mutateAsync({ values: { reason: "Алдаа засав" } });
    });
    expect(urlOf(1).pathname).toBe("/api/v1/employees/5/job/9/correct");
  });

  it("an ok:true page save refetches the active personal and work queries", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK_RESULT));
    const personal = observe(client, ["employee", 7, "personal"]);
    const work = observe(client, ["employee", 7, "work"]);
    await vi.waitFor(() => expect(personal).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(work).toHaveBeenCalledTimes(1));

    const { result } = renderHook(() => useSavePage(7), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: { loaded: "L1" } });
    });

    await vi.waitFor(() => expect(personal).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(work).toHaveBeenCalledTimes(2));
  });

  it("an ok:false page save refetches neither the personal nor the work query", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ...OK_RESULT, ok: false }));
    const personal = observe(client, ["employee", 7, "personal"]);
    const work = observe(client, ["employee", 7, "work"]);
    await vi.waitFor(() => expect(personal).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(work).toHaveBeenCalledTimes(1));

    const { result } = renderHook(() => useSavePage(7), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: { loaded: "L1" } });
    });
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(personal).toHaveBeenCalledTimes(1);
    expect(work).toHaveBeenCalledTimes(1);
  });

  it("useSaveSection sends values, resolve and loaded in the JSON body", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, OK_RESULT));
    const body = { values: { phone: "99" }, resolve: { phone: "mine" }, loaded: "L1" };

    const { result } = renderHook(() => useSaveSection(5, "contact"), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync(body);
    });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(JSON.parse(await request.text())).toEqual(body);
  });

  it("useRowForm sends only the presets that are given, and no key for an add form", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { title: "", fields: [], hidden: {}, empty_lists: [], can_delete: false }),
    );

    const { result } = renderHook(
      () => useRowForm(5, "address", null, { city: "Улаанбаатар", district: "Баянзүрх" }, true),
      { wrapper: wrapperFor(client) },
    );
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = urlOf(0);
    expect(url.pathname).toBe("/api/v1/employees/5/personal/address/form");
    expect(url.searchParams.has("key")).toBe(false);
    expect(url.searchParams.get("city")).toBe("Улаанбаатар");
    expect(url.searchParams.get("district")).toBe("Баянзүрх");
    expect(url.searchParams.has("street")).toBe(false);
  });

  it("a 403 from a POST surfaces as ApiFailure with status 403 and code forbidden, without a CSRF retry", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(
      jsonResponse(403, { field_errors: {}, form_errors: ["Эрх байхгүй"], code: "forbidden" }),
    );

    const { result } = renderHook(() => useAddNote(5), { wrapper: wrapperFor(client) });
    const caught = (await rejectionOf(() => result.current.mutateAsync("тэмдэглэл"))) as ApiFailure;

    expect(caught.status).toBe(403);
    expect(caught.code).toBe("forbidden");
    expect(caught.formErrors).toEqual(["Эрх байхгүй"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("useEditRow and useDeleteRow invalidate the header, personal and activity keys", async () => {
    // A fresh Response per call: one Response body can be read only once.
    fetchMock.mockImplementation(async () => jsonResponse(200, OK_RESULT));
    const spy = vi.spyOn(client, "invalidateQueries");
    const expected = [
      { queryKey: ["employee", 5], exact: true },
      { queryKey: ["employee", 5, "personal"], exact: true },
      { queryKey: ["employee", 5, "activity"], exact: true },
    ];

    const edit = renderHook(() => useEditRow(5, "bank", 42), { wrapper: wrapperFor(client) });
    await act(async () => {
      await edit.result.current.mutateAsync({ values: { loaded_bank: "B1" } });
    });
    expect(invalidatedKeys(spy)).toEqual(expected);

    spy.mockClear();
    const remove = renderHook(() => useDeleteRow(5, "bank", 42), { wrapper: wrapperFor(client) });
    await act(async () => {
      await remove.result.current.mutateAsync({ values: { loaded_bank: "B1" } });
    });
    expect(urlOf(1).pathname).toBe("/api/v1/employees/5/personal/bank/42/delete");
    expect(invalidatedKeys(spy)).toEqual(expected);
  });

  it("an ok:false correction invalidates nothing", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, { ...OK_RESULT, ok: false, form_errors: ["Шалтгаан хоосон"] }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSubmitCorrection(5, "salary/3/correct"), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: { reason: "" } });
    });

    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/salary/3/correct");
    expect(spy).not.toHaveBeenCalled();
  });

  it("the stale-check forms do not refetch on reconnect (a refetch would replace their snapshot silently)", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { title: "", fields: [], hidden: {}, empty_lists: [], can_delete: false, loaded: "", si_loaded: "" }),
    );

    renderHook(() => useRowForm(5, "bank", null, {}, true), { wrapper: wrapperFor(client) });
    renderHook(() => usePageForm(5, true), { wrapper: wrapperFor(client) });
    renderHook(() => useCorrectionForm(5, "salary/set", true), { wrapper: wrapperFor(client) });

    const keys = [
      ["employee", 5, "row-form", "bank", null, null, null, null],
      ["employee", 5, "page-form"],
      ["employee", 5, "correction-form", "salary/set"],
    ];
    for (const queryKey of keys) {
      const options = client.getQueryCache().find({ queryKey })?.options as { refetchOnReconnect?: boolean } | undefined;
      expect(options?.refetchOnReconnect).toBe(false);
    }
  });

  it("a refused row write (ok false) invalidates the personal list only", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(200, { ...OK_RESULT, ok: false, form_errors: ["Өөр хэрэглэгч өөрчилсөн байна, дахин ачаална уу"] }),
    );
    const spy = vi.spyOn(client, "invalidateQueries");

    const edit = renderHook(() => useEditRow(5, "bank", 42), { wrapper: wrapperFor(client) });
    await act(async () => {
      await edit.result.current.mutateAsync({ values: { loaded_bank: "B1" } });
    });
    expect(invalidatedKeys(spy)).toEqual([{ queryKey: ["employee", 5, "personal"], exact: true }]);
  });
});
