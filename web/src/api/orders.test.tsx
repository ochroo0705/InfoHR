// The harness is imported first: it stubs fetch before ./client (and so ./orders) load.
import {
  csrfFailure,
  fetchMock,
  invalidatedKeys,
  jsonResponse,
  metaBody,
  newClient,
  observe,
  rejectionOf,
  resetFetch,
  resetObservers,
  urlOf,
  wrapperFor,
} from "./testSupport";
import type { QueryClient } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "./client";
import type { ApiFailure } from "./mutate";
import { useOrderHistory, useOrderPopup, useSubmitOrderEdit, useSubmitOrderUpload } from "./orders";

const POPUP_OUT = {
  title: "Тушаал засах",
  hint: "",
  fields: [],
  submit_label: "Хадгалах",
  multipart: false,
};

const UPLOAD_OUT = { ...POPUP_OUT, title: "Скан оруулах", multipart: true };

const OK_RESULT = { ok: true, field_errors: {}, form_errors: [] };

const HISTORY_OUT = {
  title: "Түүх",
  entries: [
    {
      by: "Систем",
      at: "2026-11-02 10:15",
      message: "Үүсгэсэн",
      changes: [{ field: "number", old: "", new: "12" }],
    },
  ],
};

describe("order pop-up API", () => {
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
  });

  it("useOrderPopup edit reads the edit route of the order", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, POPUP_OUT));

    const { result } = renderHook(() => useOrderPopup(5, 12, "edit", true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("GET");
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/orders/12/edit");
    expect(result.current.data?.title).toBe("Тушаал засах");
  });

  it("useOrderPopup upload reads the upload route of the order", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, UPLOAD_OUT));

    const { result } = renderHook(() => useOrderPopup(5, 12, "upload", true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/orders/12/upload");
    expect(result.current.data?.multipart).toBe(true);
  });

  it("useOrderPopup does not run while disabled", async () => {
    const { result } = renderHook(() => useOrderPopup(5, 12, "edit", false), { wrapper: wrapperFor(client) });
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("useOrderPopup keeps a 404 as an error and does not retry it", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { field_errors: {}, form_errors: ["Олдсонгүй"] }));

    const { result } = renderHook(() => useOrderPopup(5, 12, "edit", true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as ApiFailure).status).toBe(404);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("useSubmitOrderEdit posts {values} to the edit route", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, OK_RESULT));
    const values = { number: "12", date: "2026-11-02", summary: "Ажлаас чөлөөлөх", issued_by: "Бат" };

    const { result } = renderHook(() => useSubmitOrderEdit(5, 12), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values });
    });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/orders/12/edit");
    expect(request.headers.get("X-CSRFToken")).toBe("tok");
    expect(JSON.parse(await request.text())).toEqual({ values });
  });

  it("a CSRF 403 on the order edit refetches meta and retries once", async () => {
    setCsrf("stale");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh")))
      .mockResolvedValueOnce(jsonResponse(200, OK_RESULT));

    const { result } = renderHook(() => useSubmitOrderEdit(5, 12), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: { number: "12" } });
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(urlOf(1).pathname).toBe("/api/v1/meta");
    expect((fetchMock.mock.calls[2][0] as Request).headers.get("X-CSRFToken")).toBe("fresh");
  });

  it("a successful order edit invalidates the same keys as an event write (header, work, salary, activity, today, attention)", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK_RESULT));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSubmitOrderEdit(5, 12), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: { number: "12" } });
    });

    expect(invalidatedKeys(spy)).toEqual([
      { queryKey: ["employee", 5], exact: true },
      { queryKey: ["employee", 5, "work"], exact: true },
      { queryKey: ["employee", 5, "salary"], exact: true },
      { queryKey: ["employee", 5, "activity"], exact: true },
      { queryKey: ["today"] },
      { queryKey: ["attention"] },
    ]);
  });

  it("a refused order edit (ok false) invalidates nothing", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { ok: false, field_errors: { number: ["Дугаар давхцсан"] }, form_errors: [] }),
    );
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSubmitOrderEdit(5, 12), { wrapper: wrapperFor(client) });
    let answer: unknown;
    await act(async () => {
      answer = await result.current.mutateAsync({ values: { number: "12" } });
    });

    expect((answer as { ok: boolean }).ok).toBe(false);
    expect(spy).not.toHaveBeenCalled();
  });

  it("useSubmitOrderUpload posts a multipart body with the file part and the CSRF token", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, OK_RESULT));
    // The file is checked where it is appended to the FormData (see employeeWrites.test.tsx for the reason).
    const append = vi.spyOn(FormData.prototype, "append");
    const file = new File(["pdf-bytes"], "order.pdf", { type: "application/pdf" });

    const { result } = renderHook(() => useSubmitOrderUpload(5, 12), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ file });
    });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/orders/12/upload");
    expect(request.headers.get("X-CSRFToken")).toBe("tok");
    expect(request.headers.get("content-type")).toMatch(/^multipart\/form-data/);
    expect(append).toHaveBeenCalledWith("file", file);
  });

  it("useSubmitOrderUpload with no file posts a multipart body with no file part; a refusal invalidates nothing", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { ok: false, field_errors: { file: ["Файл заавал хавсаргана."] }, form_errors: [] }),
    );
    const append = vi.spyOn(FormData.prototype, "append");
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSubmitOrderUpload(5, 12), { wrapper: wrapperFor(client) });
    let answer: unknown;
    await act(async () => {
      answer = await result.current.mutateAsync({ file: null });
    });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(request.headers.get("content-type")).toMatch(/^multipart\/form-data/);
    expect(append.mock.calls.filter((call) => call[0] === "file")).toHaveLength(0);
    expect((answer as { ok: boolean }).ok).toBe(false);
    expect(spy).not.toHaveBeenCalled();
  });

  it("a successful upload invalidates the same keys as an event write (header, work, salary, activity, today, attention)", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK_RESULT));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSubmitOrderUpload(5, 12), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ file: new File(["x"], "a.pdf", { type: "application/pdf" }) });
    });

    expect(invalidatedKeys(spy).map((k) => k.queryKey)).toEqual([
      ["employee", 5],
      ["employee", 5, "work"],
      ["employee", 5, "salary"],
      ["employee", 5, "activity"],
      ["today"],
      ["attention"],
    ]);
  });

  it("a refused upload (ok false, wrong type) invalidates nothing", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { ok: false, field_errors: { file: ["Зөвхөн PDF"] }, form_errors: [] }),
    );
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSubmitOrderUpload(5, 12), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ file: new File(["x"], "a.txt", { type: "text/plain" }) });
    });

    expect(spy).not.toHaveBeenCalled();
  });

  it("a CSRF 403 on the upload refetches meta and retries once", async () => {
    setCsrf("stale");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh")))
      .mockResolvedValueOnce(jsonResponse(200, OK_RESULT));

    const { result } = renderHook(() => useSubmitOrderUpload(5, 12), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ file: new File(["x"], "a.pdf", { type: "application/pdf" }) });
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(urlOf(1).pathname).toBe("/api/v1/meta");
    expect((fetchMock.mock.calls[2][0] as Request).headers.get("X-CSRFToken")).toBe("fresh");
  });

  it("two CSRF 403s in a row on the upload reject after a single retry", async () => {
    setCsrf("stale");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh")))
      .mockResolvedValueOnce(csrfFailure());

    const { result } = renderHook(() => useSubmitOrderUpload(5, 12), { wrapper: wrapperFor(client) });
    const caught = (await rejectionOf(() =>
      result.current.mutateAsync({ file: new File(["x"], "a.pdf", { type: "application/pdf" }) }),
    )) as ApiFailure;

    expect(caught.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("useOrderHistory reads the history route and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, HISTORY_OUT));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useOrderHistory(5, 12, true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/orders/12/history");
    expect(result.current.data?.entries[0].changes[0].new).toBe("12");
    expect(spy).not.toHaveBeenCalled();
  });

  it("useOrderHistory on a 404 (order of another employee) keeps the error and does not retry it", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { field_errors: {}, form_errors: ["Олдсонгүй"] }));

    const { result } = renderHook(() => useOrderHistory(5, 12, true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as ApiFailure).status).toBe(404);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("a successful order edit refetches an active work query", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK_RESULT));
    const work = observe(client, ["employee", 7, "work"]);
    const history = observe(client, ["employee", 7, "order-history", 12]);
    await vi.waitFor(() => expect(work).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(history).toHaveBeenCalledTimes(1));

    const { result } = renderHook(() => useSubmitOrderEdit(7, 12), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: { number: "12" } });
    });

    await vi.waitFor(() => expect(work).toHaveBeenCalledTimes(2));
    // History is read-only: it is not among the keys a write refreshes.
    expect(history).toHaveBeenCalledTimes(1);
  });
});
