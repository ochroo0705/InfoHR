// The harness is imported first: it stubs fetch before ./client (and so ./orderDetail) load.
import {
  csrfFailure,
  fetchMock,
  invalidatedKeys,
  jsonResponse,
  metaBody,
  newClient,
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
import { useDeleteSavedSignature, useOrderDetail, useOrderSignState, useSubmitOrderSign } from "./orderDetail";

const DETAIL_OUT = {
  actions: {},
  awaiting_note: "",
  cancel_rows: [],
  change_rows: [],
  employee_code: "E-1",
  employee_name: "Бат",
  employee_pk: 5,
  entries: [],
  order_heading: "Тушаал",
  order_rows: [],
  scan: {},
  signing: null,
};

const SIGN_OUT = { has_saved: true, saved_url: "/api/v1/me/signature", title: "Гарын үсэг зурах" };

const SIGN_OK = { ok: true, errors: [] };

describe("order detail, sign and signature API", () => {
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

  it("useOrderDetail requests the detail path and is kept only while open", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, DETAIL_OUT));

    const { result } = renderHook(() => useOrderDetail(5, 12, true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("GET");
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/orders/12/detail");
    expect(result.current.data?.employee_name).toBe("Бат");
    expect(client.getQueryCache().find({ queryKey: ["employee", 5, "order-detail", 12] })?.options.gcTime).toBe(0);
  });

  it("useOrderDetail does not run while disabled", async () => {
    const { result } = renderHook(() => useOrderDetail(5, 12, false), { wrapper: wrapperFor(client) });
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("useOrderDetail keeps a 404 as an error and does not retry it", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { field_errors: {}, form_errors: ["Олдсонгүй"] }));

    const { result } = renderHook(() => useOrderDetail(5, 12, true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as ApiFailure).status).toBe(404);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("useOrderSignState reads the sign route and is kept only while open", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, SIGN_OUT));

    const { result } = renderHook(() => useOrderSignState(5, 12, true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("GET");
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/orders/12/sign");
    expect(result.current.data?.has_saved).toBe(true);
    expect(client.getQueryCache().find({ queryKey: ["employee", 5, "order-sign", 12] })?.options.gcTime).toBe(0);
  });

  it("useSubmitOrderSign posts the sign body with the CSRF token", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, SIGN_OK));
    const body = { mode: "saved", signature: "", remember: false };

    const { result } = renderHook(() => useSubmitOrderSign(5, 12), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync(body);
    });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/employees/5/orders/12/sign");
    expect(request.headers.get("X-CSRFToken")).toBe("tok");
    expect(JSON.parse(await request.text())).toEqual(body);
  });

  it("a successful sign invalidates the same keys as an event write", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, SIGN_OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSubmitOrderSign(5, 12), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ mode: "saved", signature: "", remember: false });
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

  it("a refused sign (ok false) invalidates nothing and returns the messages", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: false, errors: ["Гарын үсэг хоосон байна"] }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSubmitOrderSign(5, 12), { wrapper: wrapperFor(client) });
    let answer: unknown;
    await act(async () => {
      answer = await result.current.mutateAsync({ mode: "drawn", signature: "", remember: false });
    });

    expect((answer as { ok: boolean; errors: string[] }).errors).toEqual(["Гарын үсэг хоосон байна"]);
    expect(spy).not.toHaveBeenCalled();
  });

  it("a CSRF 403 on the sign refetches meta and retries once", async () => {
    setCsrf("stale");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh")))
      .mockResolvedValueOnce(jsonResponse(200, SIGN_OK));

    const { result } = renderHook(() => useSubmitOrderSign(5, 12), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync({ mode: "saved", signature: "", remember: false });
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(urlOf(1).pathname).toBe("/api/v1/meta");
    expect((fetchMock.mock.calls[2][0] as Request).headers.get("X-CSRFToken")).toBe("fresh");
  });

  it("useDeleteSavedSignature posts to the delete route with the CSRF token", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));

    const { result } = renderHook(() => useDeleteSavedSignature(), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync();
    });

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/me/signature/delete");
    expect(request.headers.get("X-CSRFToken")).toBe("tok");
  });

  it("a successful delete invalidates only the signature query of the user", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useDeleteSavedSignature(), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync();
    });

    expect(invalidatedKeys(spy)).toEqual([{ queryKey: ["me", "signature"] }]);
  });

  it("a delete that fails invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { field_errors: {}, form_errors: [] }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useDeleteSavedSignature(), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync().catch(() => undefined);
    });

    expect(spy).not.toHaveBeenCalled();
  });
});
