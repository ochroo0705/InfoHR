// The harness is imported first: it stubs fetch before ./client (and so ./selfforms) load.
import {
  fetchMock,
  invalidatedKeys,
  jsonResponse,
  newClient,
  observe,
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
  createSelfForm,
  extendSelfForm,
  revokeSelfForm,
  selfFormListKey,
  selfFormShowKey,
  useSelfFormList,
  useSelfFormShow,
  type SelfFormActionOut,
  type SelfFormCreateOut,
  type SelfFormListOut,
  type SelfFormShowOut,
} from "./selfforms";

const SHOW: SelfFormShowOut = {
  id: 5,
  label: "Нэр",
  state: "Нээлттэй",
  badge: "bg-sky-50 text-sky-800",
  state_key: "open",
  branch: "—",
  created_label: "2026-11-20 09:15",
  when_label: "2026-12-01 00:00",
  when_title: "Дуусах",
  purged: false,
  link: "https://hr.example.test/apply/x",
  qr_svg: null,
  can_extend: true,
  can_revoke: true,
  default_hours: 72,
  hire_path: null,
  decision: null,
};

const ACTION_OK: SelfFormActionOut = {
  ok: true,
  notice: { text: "Холбоосыг цуцаллаа.", tone: "success" },
  show: { ...SHOW, state_key: "revoked", can_extend: false, can_revoke: false },
};

const FORM = {
  branch_required: false,
  branches: [{ value: 3, label: "Төв оффис" }],
  default_hours: 72,
  max_hours: 8760,
  labels: { label: "Нэр", branch: "Салбар", hours: "Хугацаа" },
  help: { label: "Нэр тайлбар", hours: "Хоосон бол өгөгдмөл" },
};

const LIST: SelfFormListOut = { rows: [], waiting: 2, form: FORM, intro: "Танилцуулга" };

const CREATED: SelfFormCreateOut = {
  ok: true,
  id: 9,
  show_path: "/employees/self-forms/9/",
  field_errors: {},
  form_errors: [],
  notice: { text: "Холбоос үүсгэлээ." },
};

const REFUSED: SelfFormCreateOut = {
  ok: false,
  id: null,
  show_path: "",
  field_errors: { label: ["Энэ талбарыг заавал бөглөнө."] },
  form_errors: [],
  notice: null,
};

describe("self-form API", () => {
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

  it("keys: the list is ['selfforms'], one form is ['selfform', pk]", () => {
    expect(selfFormListKey).toEqual(["selfforms"]);
    expect(selfFormShowKey(7)).toEqual(["selfform", 7]);
  });

  it("useSelfFormList GETs the list and returns its answer", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, LIST));

    const { result } = renderHook(() => useSelfFormList(), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/selfforms");
    expect(result.current.data).toEqual(LIST);
  });

  it("createSelfForm posts the body and refreshes the list and the nav on success", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, CREATED));
    observe(client, ["selfforms"]);
    observe(client, ["nav", "/employees/self-forms/"]);
    const spy = vi.spyOn(client, "invalidateQueries");

    const answer = await act(() => createSelfForm(client, { label: "Нэр", branch: 3, hours: null }));

    expect(answer).toEqual(CREATED);
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(await request.clone().json()).toEqual({ label: "Нэр", branch: 3, hours: null });
    const keys = invalidatedKeys(spy).map((filter) => filter.queryKey);
    expect(keys).toContainEqual(["selfforms"]);
    expect(keys).toContainEqual(["nav"]);
  });

  it("createSelfForm refreshes nothing when the answer is a refusal", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, REFUSED));
    const spy = vi.spyOn(client, "invalidateQueries");

    const answer = await act(() => createSelfForm(client, { label: null, branch: null, hours: null }));

    expect(answer.ok).toBe(false);
    expect(spy).not.toHaveBeenCalled();
  });

  it("useSelfFormShow: the link is not kept after the page leaves (gcTime 0) and no refetch on focus", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, SHOW));

    const { result } = renderHook(() => useSelfFormShow(5), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/selfforms/5");
    const query = client.getQueryCache().find({ queryKey: selfFormShowKey(5) });
    expect(query?.options.gcTime).toBe(0);
    expect((query?.options as { refetchOnWindowFocus?: unknown } | undefined)?.refetchOnWindowFocus).toBe(false);
  });

  it("extendSelfForm posts the hours, null for an empty box", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, ACTION_OK));

    await act(() => extendSelfForm(client, 5, null));

    expect(urlOf(0).pathname).toBe("/api/v1/selfforms/5/extend");
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(await request.clone().json()).toEqual({ hours: null });
  });

  it("an action result does not create a cache entry when the page has already left", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, ACTION_OK));

    const answer = await act(() => revokeSelfForm(client, 5));

    expect(answer.ok).toBe(true);
    expect(client.getQueryState(selfFormShowKey(5))).toBeUndefined();
  });

  it("an action result replaces the cached page data while the page is mounted", async () => {
    client.setQueryData(selfFormShowKey(5), { ...SHOW, state: "old" });
    fetchMock.mockResolvedValueOnce(jsonResponse(200, ACTION_OK));

    await act(() => revokeSelfForm(client, 5));

    expect(client.getQueryData(selfFormShowKey(5))).toEqual(ACTION_OK.show);
  });
});
