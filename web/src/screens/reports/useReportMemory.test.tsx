import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Link, MemoryRouter, useLocation, useNavigate, useNavigationType, type NavigateFunction } from "react-router";
import { useReportMemory } from "./useReportMemory";

// The signed-in user the mocked meta answers with (null: nobody).
const session = vi.hoisted(() => ({ userId: 7 as number | null }));
vi.mock("../../shell/useMeta", () => ({
  useMeta: () => ({ data: { user: session.userId === null ? null : { id: session.userId } } }),
}));

const KEY = "hr.reportQuery.u7.staff";
const ARRIVAL_FLAG = "__hrReportMemoryArrival";

let navigateTo: NavigateFunction | null = null;
// Every address the router moved to, with how it got there ("PUSH /reports/staff/?x" and so on).
const events: string[] = [];

// Shows the address and how the router got there, and hosts the memory hook for the «staff» report.
function Harness({ answered = true, redirected = false }: { answered?: boolean; redirected?: boolean }) {
  const pending = useReportMemory("staff", answered, redirected);
  navigateTo = useNavigate();
  const location = useLocation();
  const type = useNavigationType();
  useEffect(() => {
    events.push(`${type} ${location.pathname}${location.search}`);
  }, [location.key]);
  return (
    <>
      <div data-testid="loc">{location.pathname + location.search}</div>
      <div data-testid="nav">{type}</div>
      <div data-testid="pending">{String(pending)}</div>
      <Link to="/reports/staff/" data-reset-all>
        Эхнээс
      </Link>
    </>
  );
}

function tree(entries: string[], index?: number, answered = true, redirected = false) {
  return (
    <MemoryRouter initialEntries={entries} initialIndex={index}>
      <Harness answered={answered} redirected={redirected} />
    </MemoryRouter>
  );
}

function renderAt(entries: string[], index?: number, answered = true) {
  return render(tree(entries, index, answered));
}

function where(): string {
  return screen.getByTestId("loc").textContent ?? "";
}

function pendingText(): string {
  return screen.getByTestId("pending").textContent ?? "";
}

function go(to: string) {
  act(() => navigateTo?.(to));
}

// A plain navigation as the browser reports it for the document's first load.
function stubNavigationType(type: string) {
  vi.spyOn(performance, "getEntriesByType").mockImplementation((name: string) =>
    name === "navigation" ? ([{ type }] as unknown as PerformanceEntryList) : [],
  );
}

beforeEach(() => {
  localStorage.clear();
  session.userId = 7;
  navigateTo = null;
  events.length = 0;
  // A new document: no arrival has been seen yet.
  delete (window as unknown as Record<string, unknown>)[ARRIVAL_FLAG];
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("useReportMemory", () => {
  it("remembers_report_address_per_user", () => {
    renderAt(["/reports/staff/?state=all&as_of=2026-10-31&sort=name"]);
    expect(localStorage.getItem(KEY)).toBe("?state=all&sort=name");

    cleanup();
    session.userId = 8;
    renderAt(["/reports/staff/?state=x"]);
    expect(localStorage.getItem("hr.reportQuery.u8.staff")).toBe("?state=x");
    expect(localStorage.getItem(KEY)).toBe("?state=all&sort=name");
  });

  it("no_user_no_storage", () => {
    session.userId = null;
    localStorage.setItem(KEY, "?order=1");
    localStorage.setItem("hr.reportQuery.orders", "?old=1");
    renderAt(["/reports/staff/?state=all"]);
    expect(localStorage.getItem(KEY)).toBe("?order=1");
    // Nothing is cleared without a user either.
    expect(localStorage.getItem("hr.reportQuery.orders")).toBe("?old=1");

    // Nothing is restored without a user.
    go("/reports/staff/");
    expect(where()).toBe("/reports/staff/");
    expect(pendingText()).toBe("false");
  });

  it("bare_address_restores_saved_on_push_navigation_once", () => {
    renderAt(["/reports/staff/?state=all"]);
    localStorage.setItem(KEY, "?order=1");

    go("/reports/staff/");
    expect(where()).toBe("/reports/staff/?order=1");
    expect(screen.getByTestId("nav").textContent).toBe("REPLACE");
    // The restored address is not restored again: it has a query now.
    expect(where()).toBe("/reports/staff/?order=1");
  });

  it("answer_then_restore_once", () => {
    // The bare address arrives before its answer: the restore waits for the answer (pending, no navigation yet).
    const view = renderAt(["/reports/staff/?q=a"], undefined, false);
    localStorage.setItem(KEY, "?order=1");
    go("/reports/staff/");
    expect(where()).toBe("/reports/staff/");
    expect(pendingText()).toBe("true");

    // The answer comes in: exactly one replace to the remembered address.
    view.rerender(tree(["/reports/staff/?q=a"], undefined, true));
    expect(where()).toBe("/reports/staff/?order=1");
    expect(pendingText()).toBe("false");

    // Further renders with the same answer do not navigate again.
    view.rerender(tree(["/reports/staff/?q=a"], undefined, true));
    view.rerender(tree(["/reports/staff/?q=a"], undefined, true));
    expect(events.filter((e) => e.startsWith("REPLACE"))).toEqual(["REPLACE /reports/staff/?order=1"]);
    expect(where()).toBe("/reports/staff/?order=1");
  });

  it("redirected_answer_clears_pending_and_does_not_restore", () => {
    const view = renderAt(["/reports/staff/?q=a"], undefined, false);
    localStorage.setItem(KEY, "?order=1");
    go("/reports/staff/");
    expect(pendingText()).toBe("true");

    // The server answers with a redirect: the restore is not due any more, and nothing replaces the address here.
    view.rerender(tree(["/reports/staff/?q=a"], undefined, false, true));
    expect(pendingText()).toBe("false");
    expect(where()).toBe("/reports/staff/");
    expect(events.filter((e) => e.startsWith("REPLACE"))).toEqual([]);
  });

  it("no_saved_query_is_not_pending", () => {
    renderAt(["/reports/staff/?q=a"]);
    go("/reports/staff/");
    expect(pendingText()).toBe("false");
    expect(where()).toBe("/reports/staff/");
  });

  it("back_forward_does_not_restore", () => {
    stubNavigationType("navigate");
    renderAt(["/reports/staff/", "/reports/staff/?q=a"], 1);
    localStorage.setItem(KEY, "?order=1");

    // Back to the bare entry is a POP: the address stays as the browser has it.
    act(() => navigateTo?.(-1));
    expect(screen.getByTestId("nav").textContent).toBe("POP");
    expect(where()).toBe("/reports/staff/");
    expect(pendingText()).toBe("false");
  });

  it("reload_does_not_restore", () => {
    stubNavigationType("reload");
    localStorage.setItem(KEY, "?order=1");
    renderAt(["/reports/staff/"]);
    expect(where()).toBe("/reports/staff/");
  });

  it("first_load_navigation_restores_saved", () => {
    stubNavigationType("navigate");
    localStorage.setItem(KEY, "?order=1");
    renderAt(["/reports/staff/"]);
    expect(where()).toBe("/reports/staff/?order=1");
  });

  it("reset_link_forgets_key_before_navigation", () => {
    renderAt(["/reports/staff/?state=all"]);
    expect(localStorage.getItem(KEY)).toBe("?state=all");

    // The «Эхнээс» link goes to the bare address. The setup is forgotten first, so the bare address is not restored.
    fireEvent.click(screen.getByText("Эхнээс"));
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(where()).toBe("/reports/staff/");
  });

  it("q_and_dates_not_remembered", () => {
    renderAt(["/reports/staff/?q=abc"]);
    expect(localStorage.getItem(KEY)).toBeNull();

    go("/reports/staff/?as_of=2026-01-01&state=all");
    expect(localStorage.getItem(KEY)).toBe("?state=all");

    // An address with only a search left removes the saved key (an empty result removes it).
    go("/reports/staff/?q=b");
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("old_keys_removed", () => {
    localStorage.setItem("hr.reportQuery.orders", "?x=1");
    localStorage.setItem("hr.reportQuery.u7.orders", "?y=1");
    renderAt(["/reports/staff/?state=all"]);
    expect(localStorage.getItem("hr.reportQuery.orders")).toBeNull();
    expect(localStorage.getItem("hr.reportQuery.u7.orders")).toBe("?y=1");
  });

  it("storage_blocked_is_safe", () => {
    const blocked = () => {
      throw new Error("blocked");
    };
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(blocked);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(blocked);
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(blocked);
    vi.spyOn(Storage.prototype, "key").mockImplementation(blocked);

    expect(() => renderAt(["/reports/staff/?state=all"])).not.toThrow();
    expect(() => go("/reports/staff/")).not.toThrow();
    expect(where()).toBe("/reports/staff/");
  });

  it("not_answered_yet_no_restore", () => {
    localStorage.setItem(KEY, "?order=1");
    renderAt(["/reports/staff/?state=all"], undefined, false);
    go("/reports/staff/");
    // The page has no answer yet (the server may redirect this address): memory waits.
    expect(where()).toBe("/reports/staff/");
  });
});
