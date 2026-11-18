import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "./client";
import {
  checkRegister,
  fetchDistricts,
  hireSubmit,
  rejectSubmission,
  sendBack,
  suggestOrderNumber,
  useHireForm,
  useHireSubmit,
} from "./hire";
import type { ApiFailure } from "./mutate";

// fetch is stubbed before the api client is imported (openapi-fetch captures fetch when it is created), and it
// delegates to a mock that each test sets up. Relative URLs are resolved against the page, as in employeeWrites.test.tsx.
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

const OK_HIRE = {
  ok: true,
  pk: 41,
  redirect: "/employees/41/",
  field_errors: {},
  form_errors: [],
  candidate: null,
  submission: null,
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function urlOf(index: number): URL {
  return new URL((fetchMock.mock.calls[index][0] as Request).url);
}

// Runs a call that is expected to fail and returns what it rejected with.
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

describe("hire API", () => {
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
    vi.restoreAllMocks();
  });

  it("useHireForm reads /api/v1/employees/new with the candidate and submission in the query", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { title: "Ажилтан нэмэх", tabs: [], fields: [] }));

    const { result } = renderHook(() => useHireForm("a b&c", "12"), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = urlOf(0);
    expect(url.pathname).toBe("/api/v1/employees/new");
    expect(url.searchParams.get("candidate")).toBe("a b&c");
    expect(url.searchParams.get("submission")).toBe("12");
    expect(result.current.data?.title).toBe("Ажилтан нэмэх");
  });

  it("useHireForm keeps a 403 as an error with status 403 and does not retry it", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(403, { field_errors: {}, form_errors: ["Эрх байхгүй"], code: "forbidden" }),
    );

    const { result } = renderHook(() => useHireForm("", ""), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    const error = result.current.error as ApiFailure;
    expect(error.status).toBe(403);
    expect(error.code).toBe("forbidden");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("hireSubmit sends a multipart body with the values JSON and the candidate and submission ids", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, OK_HIRE));
    // The fields are checked where they are appended to the FormData (see employeeWrites.test.tsx for the reason).
    const append = vi.spyOn(FormData.prototype, "append");
    const values = { "family_name": "Бат", "addr-city": "Улаанбаатар" };

    const result = await hireSubmit(client, { values, candidate: "7", submission: "3", photo: null });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/employees");
    expect(request.headers.get("X-CSRFToken")).toBe("tok");
    expect(request.headers.get("content-type")).toMatch(/^multipart\/form-data/);
    expect(append).toHaveBeenCalledWith("values", JSON.stringify(values));
    expect(append).toHaveBeenCalledWith("candidate", "7");
    expect(append).toHaveBeenCalledWith("submission", "3");
    expect(result.ok).toBe(true);
    expect(result.pk).toBe(41);
  });

  it("hireSubmit omits the photo part when no photo is given", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK_HIRE));
    const append = vi.spyOn(FormData.prototype, "append");

    await hireSubmit(client, { values: { "family_name": "Бат" }, candidate: "", submission: "", photo: null });

    const names = append.mock.calls.map((call) => call[0]);
    expect(names).toContain("values");
    expect(names).not.toContain("photo");
  });

  it("hireSubmit includes the photo part when a photo is given", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK_HIRE));
    const append = vi.spyOn(FormData.prototype, "append");
    const photo = new File(["png-bytes"], "photo.png", { type: "image/png" });

    await hireSubmit(client, { values: {}, candidate: "", submission: "", photo });

    expect(append).toHaveBeenCalledWith("photo", photo);
  });

  it("hireSubmit rejects a 403 with an ApiFailure carrying status 403, without a CSRF retry", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(
      jsonResponse(403, { field_errors: {}, form_errors: ["Эрх байхгүй"], code: "forbidden" }),
    );

    const caught = (await rejectionOf(() =>
      hireSubmit(client, { values: {}, candidate: "", submission: "", photo: null }),
    )) as ApiFailure;

    expect(caught.status).toBe(403);
    expect(caught.code).toBe("forbidden");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("checkRegister returns null without a request for an empty or blank value", async () => {
    expect(await checkRegister("")).toBeNull();
    expect(await checkRegister("   ")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("checkRegister asks the check-register route with the value encoded and returns the match", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { match: { pk: 9, code: "E-009", full_name: "Бат Дорж" } }));

    const match = await checkRegister("УК88010122");

    expect(urlOf(0).pathname).toBe("/api/v1/employees/check-register");
    expect(urlOf(0).searchParams.get("register_no")).toBe("УК88010122");
    expect(match).toEqual({ pk: 9, code: "E-009", full_name: "Бат Дорж" });
  });

  it("checkRegister returns null when no visible employee has the number", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { match: null }));

    expect(await checkRegister("УК88010122")).toBeNull();
  });

  it("fetchDistricts asks the districts route for the city", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, [{ value: "1", label: "Баянзүрх" }]));

    const districts = await fetchDistricts("Улаанбаатар");

    expect(urlOf(0).pathname).toBe("/api/v1/employees/districts");
    expect(urlOf(0).searchParams.get("city")).toBe("Улаанбаатар");
    expect(districts).toEqual([{ value: "1", label: "Баянзүрх" }]);
  });

  it("suggestOrderNumber asks the order-suggest route for the date", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { number: "А-12", date: "2026-11-18" }));

    const suggestion = await suggestOrderNumber("2026-11-18");

    expect(urlOf(0).pathname).toBe("/api/v1/employees/order-suggest");
    expect(urlOf(0).searchParams.get("date")).toBe("2026-11-18");
    expect(suggestion).toEqual({ number: "А-12", date: "2026-11-18" });
  });

  it("suggestOrderNumber sends no date parameter for an empty date", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { number: "А-12", date: "2026-11-18" }));

    await suggestOrderNumber("");

    expect(urlOf(0).pathname).toBe("/api/v1/employees/order-suggest");
    expect(urlOf(0).searchParams.has("date")).toBe(false);
  });

  it("sendBack posts {note} as JSON with the CSRF token", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true, form_errors: [], redirect: "/employees/selfforms/" }));

    const decision = await sendBack(client, 5, "Төрсөн огноо дутуу");

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/selfforms/5/send-back");
    expect(request.headers.get("X-CSRFToken")).toBe("tok");
    expect(JSON.parse(await request.text())).toEqual({ note: "Төрсөн огноо дутуу" });
    expect(decision.ok).toBe(true);
  });

  it("rejectSubmission posts {reason} as JSON with the CSRF token", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: false, form_errors: ["Шалтгаан хоосон"], redirect: "" }));

    const decision = await rejectSubmission(client, 5, "Давхардсан анкет");

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/selfforms/5/reject");
    expect(request.headers.get("X-CSRFToken")).toBe("tok");
    expect(JSON.parse(await request.text())).toEqual({ reason: "Давхардсан анкет" });
    expect(decision.ok).toBe(false);
  });

  it("useHireSubmit invalidates today, attention and me on an ok result", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ...OK_HIRE, pk: 5, redirect: "/employees/5/" }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useHireSubmit(), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: {}, candidate: "", submission: "", photo: null });
    });

    expect(spy.mock.calls.map((call) => (call[0] as { queryKey: unknown[] }).queryKey)).toEqual([
      ["today"],
      ["attention"],
      ["me"],
    ]);
  });

  it("useHireSubmit invalidates nothing on an ok:false result", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, {
        ...OK_HIRE,
        ok: false,
        pk: null,
        redirect: "",
        field_errors: { "family_name": ["Хоосон"] },
      }),
    );
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useHireSubmit(), { wrapper: wrapperFor(client) });
    let answer: unknown;
    await act(async () => {
      answer = await result.current.mutateAsync({ values: {}, candidate: "", submission: "", photo: null });
    });

    expect((answer as { ok: boolean; field_errors: Record<string, string[]> }).ok).toBe(false);
    expect((answer as { field_errors: Record<string, string[]> }).field_errors).toEqual({ "family_name": ["Хоосон"] });
    expect(spy).not.toHaveBeenCalled();
  });

  it("useHireSubmit rejects on 403 and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(403, { field_errors: {}, form_errors: ["Эрх байхгүй"], code: "forbidden" }),
    );
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useHireSubmit(), { wrapper: wrapperFor(client) });
    const caught = (await rejectionOf(() =>
      result.current.mutateAsync({ values: {}, candidate: "", submission: "", photo: null }),
    )) as ApiFailure;

    expect(caught.status).toBe(403);
    expect(spy).not.toHaveBeenCalled();
  });
});
