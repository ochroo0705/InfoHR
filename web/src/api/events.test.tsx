// The harness is imported first: it stubs fetch before ./client (and so ./events) load.
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
import { QueryClient } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "./client";
import { loadEventForm, useEventCancelForm, useEventForm, useSubmitEvent, useSubmitEventCancel } from "./events";
import type { ApiFailure } from "./mutate";

const FORM_OUT = {
  title: "Ажил хэрэг",
  hint: "",
  fields: [],
  kinds: [],
  order_fields: [],
  summary: "",
  when: "",
  prev_effective: "",
  reload: false,
  death_unset: false,
  errors: {},
  form_errors: [],
};

const OK_WRITE = {
  ok: true,
  field_errors: {},
  form_errors: [],
  summary: "",
  prev_effective: "",
  when: "",
};

const OK_POPUP = { ok: true, field_errors: {}, form_errors: [] };

describe("event API", () => {
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

  it("useEventForm opens the first form: POST to the type's form route with empty values and an empty prev_effective", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, FORM_OUT));

    const { result } = renderHook(() => useEventForm(5, "hire", true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/events/hire/form");
    // The server's first open is an empty values object with an empty prev_effective (events.py _open_state).
    expect(JSON.parse(await request.text())).toEqual({ values: {}, prev_effective: "" });
    expect(result.current.data?.title).toBe("Ажил хэрэг");
  });

  it("useEventForm does not run while disabled", async () => {
    const { result } = renderHook(() => useEventForm(5, "hire", false), { wrapper: wrapperFor(client) });
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("useEventForm keeps a 403 as an error and does not retry it", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: [], code: "forbidden" }));

    const { result } = renderHook(() => useEventForm(5, "hire", true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as ApiFailure).status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("loadEventForm posts the typed values and the prev_effective with the CSRF token", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, FORM_OUT));
    const values = { type: "promotion", effective: "2026-13-45" };

    const form = await loadEventForm(client, 5, "promotion", { values, prev_effective: "2026-11-01" });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/events/promotion/form");
    expect(request.headers.get("X-CSRFToken")).toBe("tok");
    expect(JSON.parse(await request.text())).toEqual({ values, prev_effective: "2026-11-01" });
    expect(form.title).toBe("Ажил хэрэг");
  });

  it("a CSRF 403 on loadEventForm refetches meta and retries once", async () => {
    setCsrf("stale");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh")))
      .mockResolvedValueOnce(jsonResponse(200, FORM_OUT));

    await loadEventForm(client, 5, "hire", { values: {}, prev_effective: "" });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(urlOf(1).pathname).toBe("/api/v1/meta");
    expect((fetchMock.mock.calls[2][0] as Request).headers.get("X-CSRFToken")).toBe("fresh");
  });

  it("useSubmitEvent posts {values} to the type's route", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, OK_WRITE));
    const values = { type: "promotion", effective: "2026-11-01", prev_effective: "2026-11-01" };

    const { result } = renderHook(() => useSubmitEvent(5, "promotion"), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values });
    });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/events/promotion");
    expect(JSON.parse(await request.text())).toEqual({ values });
  });

  it("a CSRF 403 on the event save refetches meta and retries once", async () => {
    setCsrf("stale");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh")))
      .mockResolvedValueOnce(jsonResponse(200, OK_WRITE));

    const { result } = renderHook(() => useSubmitEvent(5, "promotion"), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: { type: "promotion" } });
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(urlOf(1).pathname).toBe("/api/v1/meta");
    expect((fetchMock.mock.calls[2][0] as Request).headers.get("X-CSRFToken")).toBe("fresh");
  });

  it("two CSRF 403s in a row reject after a single retry", async () => {
    setCsrf("stale");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh")))
      .mockResolvedValueOnce(csrfFailure());

    const { result } = renderHook(() => useSubmitEvent(5, "promotion"), { wrapper: wrapperFor(client) });
    const caught = (await rejectionOf(() =>
      result.current.mutateAsync({ values: { type: "promotion" } }),
    )) as ApiFailure;

    expect(caught.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("a 403 on the event save rejects with code forbidden, without a CSRF retry or invalidation", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(
      jsonResponse(403, { field_errors: {}, form_errors: ["Эрх байхгүй"], code: "forbidden" }),
    );
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSubmitEvent(5, "promotion"), { wrapper: wrapperFor(client) });
    const caught = (await rejectionOf(() =>
      result.current.mutateAsync({ values: { type: "promotion" } }),
    )) as ApiFailure;

    expect(caught.status).toBe(403);
    expect(caught.code).toBe("forbidden");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(spy).not.toHaveBeenCalled();
  });

  it("a successful event save invalidates the employee parts, today (prefix) and attention", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK_WRITE));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSubmitEvent(5, "promotion"), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: { type: "promotion" } });
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

  it("a refused event save (ok false) invalidates nothing", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { ...OK_WRITE, ok: false, field_errors: { effective: ["Огноо буруу"] } }),
    );
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSubmitEvent(5, "promotion"), { wrapper: wrapperFor(client) });
    let answer: unknown;
    await act(async () => {
      answer = await result.current.mutateAsync({ values: { type: "promotion" } });
    });

    expect((answer as { ok: boolean }).ok).toBe(false);
    expect(spy).not.toHaveBeenCalled();
  });

  it("an ok:true event save refetches the active work query and the today query", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK_WRITE));
    const work = observe(client, ["employee", 7, "work"]);
    const today = observe(client, ["today", "hires"]);
    await vi.waitFor(() => expect(work).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(today).toHaveBeenCalledTimes(1));

    const { result } = renderHook(() => useSubmitEvent(7, "promotion"), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: { type: "promotion" } });
    });

    await vi.waitFor(() => expect(work).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(today).toHaveBeenCalledTimes(2));
  });

  it("useEventCancelForm reads the cancel pop-up of one event", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { title: "Цуцлах", hint: "", fields: [], submit_label: "Цуцлах", multipart: false }),
    );

    const { result } = renderHook(() => useEventCancelForm(5, 31, true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/events/31/cancel");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("GET");
    expect(result.current.data?.title).toBe("Цуцлах");
  });

  it("useEventCancelForm on a 404 (event applied or cancelled) keeps the error and does not retry it", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { field_errors: {}, form_errors: ["Олдсонгүй"] }));

    const { result } = renderHook(() => useEventCancelForm(5, 31, true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as ApiFailure).status).toBe(404);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("useSubmitEventCancel posts {values} to the cancel route and invalidates like an event save on ok:true", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, OK_POPUP));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSubmitEventCancel(5, 31), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: { reason: "Алдаа" } });
    });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/events/31/cancel");
    expect(JSON.parse(await request.text())).toEqual({ values: { reason: "Алдаа" } });
    expect(invalidatedKeys(spy).map((k) => k.queryKey)).toEqual([
      ["employee", 5],
      ["employee", 5, "work"],
      ["employee", 5, "salary"],
      ["employee", 5, "activity"],
      ["today"],
      ["attention"],
    ]);
  });

  it("a CSRF 403 on the event cancel refetches meta and retries once", async () => {
    setCsrf("stale");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh")))
      .mockResolvedValueOnce(jsonResponse(200, OK_POPUP));

    const { result } = renderHook(() => useSubmitEventCancel(5, 31), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: { reason: "Алдаа" } });
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(urlOf(1).pathname).toBe("/api/v1/meta");
    expect((fetchMock.mock.calls[2][0] as Request).headers.get("X-CSRFToken")).toBe("fresh");
  });

  it("a refused event cancel (ok false) invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ...OK_POPUP, ok: false, form_errors: ["Шалтгаан хоосон"] }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSubmitEventCancel(5, 31), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ values: {} });
    });

    expect(spy).not.toHaveBeenCalled();
  });

  it("a 404 on a cancel rejects with an ApiFailure and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { field_errors: {}, form_errors: ["Олдсонгүй"] }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSubmitEventCancel(5, 31), { wrapper: wrapperFor(client) });
    const caught = (await rejectionOf(() => result.current.mutateAsync({ values: {} }))) as ApiFailure;

    expect(caught.status).toBe(404);
    expect(spy).not.toHaveBeenCalled();
  });
});
