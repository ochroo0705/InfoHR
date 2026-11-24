// The harness is imported first: it stubs fetch before ./client (and so ./leaveSetup) load.
import {
  fetchMock,
  invalidatedKeys,
  jsonResponse,
  newClient,
  rejectionOf,
  resetFetch,
  resetObservers,
  urlOf,
  wrapperFor,
} from "./testSupport";
import type { QueryClient } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import { focusManager, onlineManager } from "@tanstack/react-query";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "./client";
import {
  useDeleteLeaveType,
  useHolidayAction,
  useLeaveHolidays,
  useLeaveSettings,
  useLeaveType,
  useSaveApproval,
  useSaveAutoGrant,
  useSaveLeaveType,
  type LeaveHolidaysOut,
  type LeaveSettingsOut,
  type LeaveTypeIn,
} from "./leaveSetup";
import type { ApiFailure } from "./mutate";

const HOLIDAYS: LeaveHolidaysOut = {
  empty_text: "",
  fixed_count: 12,
  holidays: [{ date: "2026-01-01", name: "Шинэ жил" }],
  year: 2026,
};

const TYPE = { id: 5, name: "Жирийн амралт", is_paid: true, uses_annual_balance: true, is_active: true, order: 0, staff_may_request: true };

const SETTINGS: LeaveSettingsOut = {
  approval: { step1: "manager", step2: "" },
  auto_annual_grant: false,
  step1_choices: [],
  step2_choices: [],
  types: [TYPE],
};

const TYPE_BODY: LeaveTypeIn = {
  name: "Жирийн амралт",
  is_paid: true,
  uses_annual_balance: true,
  is_active: true,
  order: 0,
  staff_may_request: true,
};

const OK = { ok: true, error: "", field_errors: {}, form_errors: [] };
const REFUSED = { ok: false, error: "Өөрчлөгдсөн", field_errors: {}, form_errors: ["Өөрчлөгдсөн"] };

// The keys a successful setup write must refresh: its own page key, the leave list, the attention box and the nav.
const SETUP_WRITE_KEYS = [{ queryKey: ["leave", "list"] }, { queryKey: ["attention"] }, { queryKey: ["nav"] }];

function bodyOf(index: number): Promise<unknown> {
  return (fetchMock.mock.calls[index][0] as Request).json();
}

describe("leave setup API", () => {
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

  it("useLeaveHolidays asks for the year given, and for none when the year is not given", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, HOLIDAYS));

    const { result } = renderHook(() => useLeaveHolidays("2026"), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/leave/holidays");
    expect(urlOf(0).searchParams.get("year")).toBe("2026");
    expect(client.getQueryCache().find({ queryKey: ["leave", "holidays", "2026"] })).toBeDefined();
  });

  it("useLeaveHolidays sends no year and keys the query with an empty year when none is given", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, HOLIDAYS));

    const { result } = renderHook(() => useLeaveHolidays(), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).searchParams.has("year")).toBe(false);
    expect(client.getQueryCache().find({ queryKey: ["leave", "holidays", ""] })).toBeDefined();
  });

  it("useLeaveHolidays fails with the status 403 when the user may not manage settings", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: ["no"], code: "forbidden" }));

    const { result } = renderHook(() => useLeaveHolidays("2026"), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as ApiFailure).status).toBe(403);
  });

  it("useHolidayAction add posts the date and name to /holidays/add and refreshes its page, the list, attention and nav", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useHolidayAction(), { wrapper: wrapperFor(client) });
    const saved = await act(() =>
      result.current.mutateAsync({ action: "add", year: 2026, date: "2026-03-08", name: "Эмэгтэйчүүдийн баяр" }),
    );

    expect(saved).toEqual(OK);
    expect(urlOf(0).pathname).toBe("/api/v1/leave/holidays/add");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(await bodyOf(0)).toEqual({ year: 2026, date: "2026-03-08", name: "Эмэгтэйчүүдийн баяр" });
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["leave", "holidays"] });
    for (const key of SETUP_WRITE_KEYS) expect(invalidatedKeys(spy)).toContainEqual(key);
  });

  it("useHolidayAction delete posts the date to /holidays/delete", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));

    const { result } = renderHook(() => useHolidayAction(), { wrapper: wrapperFor(client) });
    await act(() => result.current.mutateAsync({ action: "delete", year: 2026, date: "2026-03-08" }));

    expect(urlOf(0).pathname).toBe("/api/v1/leave/holidays/delete");
    expect(await bodyOf(0)).toEqual({ year: 2026, date: "2026-03-08" });
  });

  it("useHolidayAction prefill posts the year to /holidays/prefill", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));

    const { result } = renderHook(() => useHolidayAction(), { wrapper: wrapperFor(client) });
    await act(() => result.current.mutateAsync({ action: "prefill", year: 2026 }));

    expect(urlOf(0).pathname).toBe("/api/v1/leave/holidays/prefill");
    expect(await bodyOf(0)).toEqual({ year: 2026 });
  });

  it("a holiday action that answers ok false invalidates nothing and returns the refusal", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, REFUSED));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useHolidayAction(), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync({ action: "add", year: 2026, date: "2025-01-01", name: "x" }));

    expect(saved.ok).toBe(false);
    expect(saved.error).toBe("Өөрчлөгдсөн");
    expect(spy).not.toHaveBeenCalled();
  });

  it("a holiday action refused with 403 rejects with the status and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: ["no"] }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useHolidayAction(), { wrapper: wrapperFor(client) });
    const caught = await rejectionOf(() => result.current.mutateAsync({ action: "prefill", year: 2026 }));

    expect((caught as ApiFailure).status).toBe(403);
    expect(spy).not.toHaveBeenCalled();
  });

  it("useLeaveSettings asks for the settings at /api/v1/leave/settings", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, SETTINGS));

    const { result } = renderHook(() => useLeaveSettings(), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/leave/settings");
    expect(client.getQueryCache().find({ queryKey: ["leave", "settings"] })).toBeDefined();
  });

  it("useSaveApproval posts both steps to /settings/approval and refreshes the settings, the list, attention and nav on ok true", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSaveApproval(), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync({ step1: "manager", step2: "group:3" }));

    expect(saved).toEqual(OK);
    expect(urlOf(0).pathname).toBe("/api/v1/leave/settings/approval");
    expect(await bodyOf(0)).toEqual({ step1: "manager", step2: "group:3" });
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["leave", "settings"] });
    for (const key of SETUP_WRITE_KEYS) expect(invalidatedKeys(spy)).toContainEqual(key);
  });

  it("an approval refused by a field error invalidates nothing", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { ...REFUSED, field_errors: { step1: ["Жагсаалтаас сонгоно уу."] } }),
    );
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSaveApproval(), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync({ step1: "nope", step2: "" }));

    expect(saved.field_errors).toEqual({ step1: ["Жагсаалтаас сонгоно уу."] });
    expect(spy).not.toHaveBeenCalled();
  });

  it("useSaveAutoGrant posts the flag to /settings/auto and refreshes on ok true", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSaveAutoGrant(), { wrapper: wrapperFor(client) });
    await act(() => result.current.mutateAsync({ auto_annual_grant: true }));

    expect(urlOf(0).pathname).toBe("/api/v1/leave/settings/auto");
    expect(await bodyOf(0)).toEqual({ auto_annual_grant: true });
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["leave", "settings"] });
    for (const key of SETUP_WRITE_KEYS) expect(invalidatedKeys(spy)).toContainEqual(key);
  });

  it("useLeaveType makes no request while the id is null", async () => {
    const { result } = renderHook(() => useLeaveType(null), { wrapper: wrapperFor(client) });

    expect(result.current.fetchStatus).toBe("idle");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("useLeaveType asks for one type at its path", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, TYPE));

    const { result } = renderHook(() => useLeaveType(5), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/leave/settings/types/5");
    expect(result.current.data).toEqual(TYPE);
  });

  it("useLeaveType fails with 404 for an unknown type and does not retry", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { field_errors: {}, form_errors: ["no"] }));

    const { result } = renderHook(() => useLeaveType(99), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as ApiFailure).status).toBe(404);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("useSaveLeaveType with no id creates a type at /settings/types", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSaveLeaveType(null), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync(TYPE_BODY));

    expect(saved).toEqual(OK);
    expect(urlOf(0).pathname).toBe("/api/v1/leave/settings/types");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(await bodyOf(0)).toEqual(TYPE_BODY);
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["leave", "settings"] });
    for (const key of SETUP_WRITE_KEYS) expect(invalidatedKeys(spy)).toContainEqual(key);
  });

  it("useSaveLeaveType with an id updates that type at /settings/types/{pk}", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));

    const { result } = renderHook(() => useSaveLeaveType(5), { wrapper: wrapperFor(client) });
    await act(() => result.current.mutateAsync({ ...TYPE_BODY, name: "Өөрчилсөн" }));

    expect(urlOf(0).pathname).toBe("/api/v1/leave/settings/types/5");
    expect(await bodyOf(0)).toEqual({ ...TYPE_BODY, name: "Өөрчилсөн" });
  });

  it("a type save that answers ok false invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ...REFUSED, field_errors: { order: ["Буруу"] } }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSaveLeaveType(5), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync({ ...TYPE_BODY, order: 40000 }));

    expect(saved.field_errors).toEqual({ order: ["Буруу"] });
    expect(spy).not.toHaveBeenCalled();
  });

  it("useDeleteLeaveType posts to /settings/types/{pk}/delete and refreshes on ok true", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useDeleteLeaveType(5), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync());

    expect(saved).toEqual(OK);
    expect(urlOf(0).pathname).toBe("/api/v1/leave/settings/types/5/delete");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["leave", "settings"] });
    for (const key of SETUP_WRITE_KEYS) expect(invalidatedKeys(spy)).toContainEqual(key);
  });

  it("a delete refused because the type is in use (ok false) keeps the type and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { ok: false, error: "Энэ төрлийг ашигласан байна.", field_errors: {}, form_errors: [] }),
    );
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useDeleteLeaveType(5), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync());

    expect(saved.error).toBe("Энэ төрлийг ашигласан байна.");
    expect(spy).not.toHaveBeenCalled();
  });

  it("a delete of an unknown type rejects with 404 and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { field_errors: {}, form_errors: ["no"] }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useDeleteLeaveType(99), { wrapper: wrapperFor(client) });
    const caught = await rejectionOf(() => result.current.mutateAsync());

    expect((caught as ApiFailure).status).toBe(404);
    expect(spy).not.toHaveBeenCalled();
  });

  it("the attention and nav keys that the setup writes invalidate are the ones the Today box and the nav use", () => {
    const today = readFileSync(resolve(process.cwd(), "src/api/today.ts"), "utf8");
    const topBar = readFileSync(resolve(process.cwd(), "src/shell/TopBar.tsx"), "utf8");

    expect(today).toContain('queryKey: ["attention"');
    expect(topBar).toContain('queryKey: ["nav", pathname]');
  });
});
