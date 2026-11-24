// The harness is imported first: it stubs fetch before ./client (and so ./checklists) load.
import {
  fetchMock,
  jsonResponse,
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
import { focusManager, onlineManager } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "./client";
import {
  checklistMineKey,
  useCancelChecklist,
  useChecklistMine,
  useStartOffboarding,
  useTickTask,
  useUntickTask,
  type ChecklistMineOut,
} from "./checklists";
import { useTick } from "./me";
import type { ApiFailure } from "./mutate";
import { formErrorText } from "../screens/me/formErrorText";

const NO_CONTENT = () => new Response(null, { status: 204 });

const MINE: ChecklistMineOut = {
  items: [
    {
      id: 3,
      title: "Лаборатори",
      employee: "Бат Болд",
      kind_label: "Ажилд орох",
      due: "2026-11-20",
      overdue: true,
    },
  ],
};

// The JSON body of the request sent at call `index` of fetchMock.
async function bodyOf(index: number): Promise<unknown> {
  const text = await (fetchMock.mock.calls[index][0] as Request).text();
  return text === "" ? undefined : JSON.parse(text);
}

function methodOf(index: number): string {
  return (fetchMock.mock.calls[index][0] as Request).method;
}

describe("checklist API", () => {
  let client: QueryClient;

  beforeEach(() => {
    resetFetch();
    setCsrf("tok");
    client = newClient();
    focusManager.setFocused(true);
    onlineManager.setOnline(true);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    resetObservers();
  });

  it("checklistMineKey is ['checklists', 'mine']", () => {
    expect(checklistMineKey).toEqual(["checklists", "mine"]);
  });

  it("useTickTask posts to /api/v1/checklists/tasks/{pk}/tick", async () => {
    fetchMock.mockImplementation(async () => NO_CONTENT());
    const { result } = renderHook(() => useTickTask(), { wrapper: wrapperFor(client) });

    await act(async () => {
      await result.current.mutateAsync(3);
    });

    expect(methodOf(0)).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/checklists/tasks/3/tick");
  });

  it("useUntickTask posts to /api/v1/checklists/tasks/{pk}/untick", async () => {
    fetchMock.mockImplementation(async () => NO_CONTENT());
    const { result } = renderHook(() => useUntickTask(), { wrapper: wrapperFor(client) });

    await act(async () => {
      await result.current.mutateAsync(4);
    });

    expect(methodOf(0)).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/checklists/tasks/4/untick");
  });

  it("useCancelChecklist posts to /api/v1/checklists/{pk}/cancel", async () => {
    fetchMock.mockImplementation(async () => NO_CONTENT());
    const { result } = renderHook(() => useCancelChecklist(), { wrapper: wrapperFor(client) });

    await act(async () => {
      await result.current.mutateAsync(9);
    });

    expect(methodOf(0)).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/checklists/9/cancel");
  });

  it("useStartOffboarding posts {anchor_day} to /api/v1/checklists/employees/{employee_id}/start", async () => {
    fetchMock.mockImplementation(async () => NO_CONTENT());
    const { result } = renderHook(() => useStartOffboarding(7), { wrapper: wrapperFor(client) });

    await act(async () => {
      await result.current.mutateAsync("2026-12-31");
    });

    expect(methodOf(0)).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/checklists/employees/7/start");
    expect(await bodyOf(0)).toEqual({ anchor_day: "2026-12-31" });
  });

  it("useChecklistMine gets /api/v1/checklists/mine", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(200, MINE));
    const { result } = renderHook(() => useChecklistMine(), { wrapper: wrapperFor(client) });

    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(methodOf(0)).toBe("GET");
    expect(urlOf(0).pathname).toBe("/api/v1/checklists/mine");
    expect(result.current.data?.items[0].overdue).toBe(true);
    expect(result.current.data?.items[0].due).toBe("2026-11-20");
  });

  // Keeps the queries a checklist write refreshes active, then returns their fetch spies.
  async function watchRefreshedKeys() {
    const spies = {
      workSeven: observe(client, ["employee", 7, "work"]),
      workEight: observe(client, ["employee", 8, "work"]),
      header: observe(client, ["employee", 7]),
      mine: observe(client, ["checklists", "mine"]),
      me: observe(client, ["me"]),
      today: observe(client, ["today"]),
    };
    await vi.waitFor(() => {
      for (const spy of Object.values(spies)) expect(spy).toHaveBeenCalledTimes(1);
    });
    return spies;
  }

  it("a successful tick refetches every employee's work data, mine, me and today, not the employee header", async () => {
    fetchMock.mockImplementation(async () => NO_CONTENT());
    const spies = await watchRefreshedKeys();

    const { result } = renderHook(() => useTickTask(), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync(3);
    });

    expect(spies.workSeven).toHaveBeenCalledTimes(2);
    expect(spies.workEight).toHaveBeenCalledTimes(2);
    expect(spies.mine).toHaveBeenCalledTimes(2);
    expect(spies.me).toHaveBeenCalledTimes(2);
    expect(spies.today).toHaveBeenCalledTimes(2);
    // The employee header is not a work key: it is not refetched (its one-time login would be lost).
    expect(spies.header).toHaveBeenCalledTimes(1);
  });

  it("a successful untick refetches the same keys", async () => {
    fetchMock.mockImplementation(async () => NO_CONTENT());
    const spies = await watchRefreshedKeys();

    const { result } = renderHook(() => useUntickTask(), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync(3);
    });

    expect(spies.workSeven).toHaveBeenCalledTimes(2);
    expect(spies.workEight).toHaveBeenCalledTimes(2);
    expect(spies.mine).toHaveBeenCalledTimes(2);
    expect(spies.me).toHaveBeenCalledTimes(2);
    expect(spies.today).toHaveBeenCalledTimes(2);
    expect(spies.header).toHaveBeenCalledTimes(1);
  });

  it("a successful cancel refetches the same keys", async () => {
    fetchMock.mockImplementation(async () => NO_CONTENT());
    const spies = await watchRefreshedKeys();

    const { result } = renderHook(() => useCancelChecklist(), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync(9);
    });

    expect(spies.workSeven).toHaveBeenCalledTimes(2);
    expect(spies.workEight).toHaveBeenCalledTimes(2);
    expect(spies.mine).toHaveBeenCalledTimes(2);
    expect(spies.me).toHaveBeenCalledTimes(2);
    expect(spies.today).toHaveBeenCalledTimes(2);
    expect(spies.header).toHaveBeenCalledTimes(1);
  });

  it("useStartOffboarding refreshes the same keys after success", async () => {
    fetchMock.mockImplementation(async () => NO_CONTENT());
    const work = observe(client, ["employee", 7, "work"]);
    const mine = observe(client, ["checklists", "mine"]);
    const me = observe(client, ["me"]);
    const today = observe(client, ["today"]);
    await vi.waitFor(() => {
      for (const spy of [work, mine, me, today]) expect(spy).toHaveBeenCalledTimes(1);
    });

    const { result } = renderHook(() => useStartOffboarding(7), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync("2026-12-31");
    });

    expect(work).toHaveBeenCalledTimes(2);
    expect(mine).toHaveBeenCalledTimes(2);
    expect(me).toHaveBeenCalledTimes(2);
    expect(today).toHaveBeenCalledTimes(2);
  });

  // Watches the keys a refused write refreshes, and waits until each has its first fetch.
  async function watchWriteKeys() {
    const spies = {
      work: observe(client, ["employee", 7, "work"]),
      mine: observe(client, ["checklists", "mine"]),
      me: observe(client, ["me"]),
      today: observe(client, ["today"]),
    };
    await vi.waitFor(() => {
      for (const spy of Object.values(spies)) expect(spy).toHaveBeenCalledTimes(1);
    });
    return spies;
  }

  it("a 409 refused tick refreshes the work, mine, me and today keys, then rejects with its text", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(409, { field_errors: {}, form_errors: ["Хаагдсан"] }));
    const spies = await watchWriteKeys();

    const { result } = renderHook(() => useTickTask(), { wrapper: wrapperFor(client) });
    const error = (await rejectionOf(() => result.current.mutateAsync(3))) as ApiFailure;

    expect(formErrorText(error)).toBe("Хаагдсан");
    expect(spies.work).toHaveBeenCalledTimes(2);
    expect(spies.mine).toHaveBeenCalledTimes(2);
    expect(spies.me).toHaveBeenCalledTimes(2);
    expect(spies.today).toHaveBeenCalledTimes(2);
  });

  it("a 404 refused untick refreshes the same keys", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(404, { field_errors: {}, form_errors: ["Олдсонгүй"] }));
    const spies = await watchWriteKeys();

    const { result } = renderHook(() => useUntickTask(), { wrapper: wrapperFor(client) });
    await rejectionOf(() => result.current.mutateAsync(3));

    expect(spies.work).toHaveBeenCalledTimes(2);
    expect(spies.mine).toHaveBeenCalledTimes(2);
    expect(spies.me).toHaveBeenCalledTimes(2);
    expect(spies.today).toHaveBeenCalledTimes(2);
  });

  it("a 409 refused cancel refreshes the same keys", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(409, { field_errors: {}, form_errors: ["Хаагдсан"] }));
    const spies = await watchWriteKeys();

    const { result } = renderHook(() => useCancelChecklist(), { wrapper: wrapperFor(client) });
    await rejectionOf(() => result.current.mutateAsync(9));

    expect(spies.work).toHaveBeenCalledTimes(2);
    expect(spies.mine).toHaveBeenCalledTimes(2);
    expect(spies.me).toHaveBeenCalledTimes(2);
    expect(spies.today).toHaveBeenCalledTimes(2);
  });

  it("a 409 refused start refreshes the same keys", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(409, { field_errors: {}, form_errors: ["Хаагдсан"] }));
    const spies = await watchWriteKeys();

    const { result } = renderHook(() => useStartOffboarding(7), { wrapper: wrapperFor(client) });
    await rejectionOf(() => result.current.mutateAsync("2026-12-31"));

    expect(spies.work).toHaveBeenCalledTimes(2);
    expect(spies.mine).toHaveBeenCalledTimes(2);
    expect(spies.me).toHaveBeenCalledTimes(2);
    expect(spies.today).toHaveBeenCalledTimes(2);
  });

  it("a 400 refused start (bad date) refreshes nothing", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(400, { field_errors: {}, form_errors: ["Сүүлийн ажлын өдрийг оруулна уу."] }),
    );
    const spies = await watchWriteKeys();

    const { result } = renderHook(() => useStartOffboarding(7), { wrapper: wrapperFor(client) });
    await rejectionOf(() => result.current.mutateAsync("bad"));

    expect(spies.work).toHaveBeenCalledTimes(1);
    expect(spies.mine).toHaveBeenCalledTimes(1);
    expect(spies.me).toHaveBeenCalledTimes(1);
    expect(spies.today).toHaveBeenCalledTimes(1);
  });

  it("useTick also refreshes ['checklists', 'mine'] and the employee work keys, and keeps its URL", async () => {
    fetchMock.mockImplementation(async () => NO_CONTENT());
    const spies = await watchWriteKeys();

    const { result } = renderHook(() => useTick(), { wrapper: wrapperFor(client) });
    await act(async () => {
      await result.current.mutateAsync(3);
    });

    expect(urlOf(0).pathname).toBe("/api/v1/checklists/tasks/3/tick");
    expect(spies.mine).toHaveBeenCalledTimes(2);
    expect(spies.work).toHaveBeenCalledTimes(2);
    expect(spies.me).toHaveBeenCalledTimes(2);
    expect(spies.today).toHaveBeenCalledTimes(2);
  });

  it("useTick refreshes the same keys on a 409 and rejects with its text", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(409, { field_errors: {}, form_errors: ["Хаагдсан"] }));
    const spies = await watchWriteKeys();

    const { result } = renderHook(() => useTick(), { wrapper: wrapperFor(client) });
    const error = (await rejectionOf(() => result.current.mutateAsync(3))) as ApiFailure;

    expect(formErrorText(error)).toBe("Хаагдсан");
    expect(spies.work).toHaveBeenCalledTimes(2);
    expect(spies.mine).toHaveBeenCalledTimes(2);
  });

  it("maps a 404 (no right, nothing changed) to an ApiFailure with status 404 and its text", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(404, { field_errors: {}, form_errors: ["Хуудас олдсонгүй"] }));
    const { result } = renderHook(() => useUntickTask(), { wrapper: wrapperFor(client) });

    const error = (await rejectionOf(() => result.current.mutateAsync(3))) as ApiFailure;

    expect(error.status).toBe(404);
    expect(formErrorText(error)).toBe("Хуудас олдсонгүй");
  });

  it("maps a 409 (refused change) to an ApiFailure whose text the panel shows", async () => {
    fetchMock.mockImplementation(async () => jsonResponse(409, { field_errors: {}, form_errors: ["Хаагдсан"] }));
    const { result } = renderHook(() => useCancelChecklist(), { wrapper: wrapperFor(client) });

    const error = (await rejectionOf(() => result.current.mutateAsync(9))) as ApiFailure;

    expect(error.status).toBe(409);
    expect(formErrorText(error)).toBe("Хаагдсан");
  });

  it("maps a 400 (bad date) to an ApiFailure whose text the panel shows", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse(400, { field_errors: {}, form_errors: ["Сүүлийн ажлын өдрийг оруулна уу."] }),
    );
    const { result } = renderHook(() => useStartOffboarding(7), { wrapper: wrapperFor(client) });

    const error = (await rejectionOf(() => result.current.mutateAsync("bad"))) as ApiFailure;

    expect(error.status).toBe(400);
    expect(formErrorText(error)).toBe("Сүүлийн ажлын өдрийг оруулна уу.");
  });
});
