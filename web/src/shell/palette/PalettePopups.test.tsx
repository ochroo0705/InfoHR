// PalettePopups: the palette's pop-up openers. EmployeePopups and SlotFormModal are stubbed here (their own tests cover
// the pop-ups). LeaveFormModal is the real pop-up, with the API client replaced by a stub that answers the leave options. The tests go through activateRow from a pop-up row, with a real router: the location probe reads the
// current location after each click, so a navigation would show. They check which opener each target calls, that the slot
// form is mounted only while open, that a malformed target opens nothing and does not throw, and that the hook throws
// outside the provider.
import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router";
import type { PaletteOpenOut, PaletteRowOut } from "../../api/palette";
import { activateRow, type ActivateDeps } from "./activate";
import { PalettePopups, usePalettePopups } from "./PalettePopups";

// The API client stub: the leave options answer (the add pop-up loads them); anything else answers empty.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const LEAVE_OPTIONS = {
  assisted: null,
  employees: [
    { value: 3, label: "Ажилтан Нэг" },
    { value: 4, label: "Ажилтан Хоёр" },
  ],
  initial: { employee: null, end_date: "", leave_type: null, start_date: "" },
  not_configured: "",
  types: [{ value: 2, label: "Ээлжийн амралт" }],
};

function leaveOk(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

const employeeApi = vi.hoisted(() => ({
  openEvent: vi.fn(),
  openEventCancel: vi.fn(),
  openOrderEdit: vi.fn(),
  openOrderUpload: vi.fn(),
  openOrderHistory: vi.fn(),
  openOrderDetail: vi.fn(),
  openOrderCancel: vi.fn(),
  openOrderSign: vi.fn(),
}));
const employeeProviderProps = vi.hoisted(() => ({ last: null as null | Record<string, unknown> }));

vi.mock("../../screens/employee/EmployeePopups", () => ({
  EmployeePopups: ({ children, ...rest }: { children: ReactNode }) => {
    employeeProviderProps.last = rest;
    return <>{children}</>;
  },
  useEmployeePopups: () => employeeApi,
}));

// The stub slot form: it shows the year it got and a button that closes it, as the real form does on save or cancel.
vi.mock("../../screens/slots/SlotFormModal", () => ({
  SlotFormModal: ({ year, onClose }: { year: number; onClose: () => void }) => (
    <div data-testid="slot-form">
      <span>{`year:${year}`}</span>
      <button type="button" onClick={onClose}>
        Хаах
      </button>
    </div>
  ),
}));

// Reads the current location on every render, so a click that navigated would be visible.
function LocationProbe() {
  return <span data-testid="location">{useLocation().pathname}</span>;
}

const base: PaletteOpenOut = {
  employee: null,
  event_type: null,
  kind: "popup",
  order: null,
  path: "/employees/3/",
  popup: null,
  year: null,
};

function popupRow(open: PaletteOpenOut): PaletteRowOut {
  return {
    code: [],
    day: "",
    initials: "",
    kind: "person",
    key: "row",
    left: false,
    lines: [],
    open,
    ref: null,
    title: [{ text: "Мөр", hit: false }],
  };
}

// A button that runs activateRow on the row, with the pop-up host's own api, as the panel does on Enter.
function ActivateButton({ row }: { row: PaletteRowOut }) {
  const popups = usePalettePopups();
  const deps: ActivateDeps = {
    closePanel: vi.fn(),
    goPorted: vi.fn(),
    legacy: vi.fn(),
    popups,
  };
  return (
    <button type="button" onClick={() => activateRow(row, deps)}>
      Нээх
    </button>
  );
}

function renderWith(open: PaletteOpenOut, path = "/employees/today/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <PalettePopups>
          <ActivateButton row={popupRow(open)} />
        </PalettePopups>
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PalettePopups", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    employeeProviderProps.last = null;
    h.get.mockImplementation(async (path: string) =>
      path === "/api/v1/leave/options" ? leaveOk(LEAVE_OPTIONS) : leaveOk({}),
    );
    h.post.mockImplementation(async () => leaveOk({}));
  });

  afterEach(() => {
    cleanup();
  });

  it("mounts EmployeePopups without a pk, since every open passes its own employee", () => {
    renderWith(base);
    expect(employeeProviderProps.last).toEqual({});
  });

  it("an order_detail target opens the order detail for that employee", () => {
    renderWith({ ...base, popup: "order_detail", order: 7, employee: 3 });
    fireEvent.click(screen.getByText("Нээх"));
    expect(employeeApi.openOrderDetail).toHaveBeenCalledWith(7, 3);
    expect(screen.queryByTestId("slot-form")).toBeNull();
  });

  it("an event target opens the contract event for that employee", () => {
    renderWith({ ...base, popup: "event", event_type: "contract", employee: 3 });
    fireEvent.click(screen.getByText("Нээх"));
    expect(employeeApi.openEvent).toHaveBeenCalledWith("contract", 3);
  });

  it("a slot_add target shows the slot form with the year", () => {
    renderWith({ ...base, popup: "slot_add", year: 2026 });
    expect(screen.queryByTestId("slot-form")).toBeNull();
    fireEvent.click(screen.getByText("Нээх"));
    expect(screen.getByTestId("slot-form").textContent).toContain("year:2026");
  });

  it("a pop-up opened through activateRow stays on the page: the host is mounted and the location is unchanged", () => {
    renderWith({ ...base, popup: "slot_add", year: 2026 }, "/employees/today/");
    fireEvent.click(screen.getByText("Нээх"));
    expect(screen.getByTestId("slot-form")).toBeTruthy();
    expect(screen.getByTestId("location").textContent).toBe("/employees/today/");
  });

  it("closing the pop-up it opened leaves the page where it was", () => {
    renderWith({ ...base, popup: "slot_add", year: 2026 }, "/employees/today/");
    fireEvent.click(screen.getByText("Нээх"));
    fireEvent.click(screen.getByText("Хаах"));
    expect(screen.queryByTestId("slot-form")).toBeNull();
    expect(screen.getByTestId("location").textContent).toBe("/employees/today/");
  });

  it("a slot_add target that carries its year opens the slot form with that year", () => {
    renderWith({ ...base, popup: "slot_add", year: 2031 });
    fireEvent.click(screen.getByText("Нээх"));
    expect(screen.getByTestId("slot-form").textContent).toContain("year:2031");
  });

  it("closing and reopening the slot form shows a fresh form for the new year", () => {
    renderWith({ ...base, popup: "slot_add", year: 2026 });
    fireEvent.click(screen.getByText("Нээх"));
    expect(screen.getByTestId("slot-form").textContent).toContain("year:2026");
    fireEvent.click(screen.getByText("Хаах"));
    expect(screen.queryByTestId("slot-form")).toBeNull();
    // The same row with a new year: the form is mounted again with that year, not the old one.
    cleanup();
    renderWith({ ...base, popup: "slot_add", year: 2027 });
    fireEvent.click(screen.getByText("Нээх"));
    expect(screen.getByTestId("slot-form").textContent).toContain("year:2027");
    expect(screen.getByTestId("slot-form").textContent).not.toContain("year:2026");
  });

  // A malformed target: the key is missing (undefined), null, or the wrong type. Nothing opens, nothing throws, and the
  // page does not change. activateRow still closes the panel first (checked in activate.test.ts).
  it.each([
    ["order_detail with no order", { popup: "order_detail", employee: 3 }],
    ["order_detail with a null order", { popup: "order_detail", order: null, employee: 3 }],
    ["order_detail with no employee", { popup: "order_detail", order: 7 }],
    ["order_detail with a null employee", { popup: "order_detail", order: 7, employee: null }],
    ["order_detail with a text order", { popup: "order_detail", order: "7", employee: 3 }],
    ["event with no event_type", { popup: "event", employee: 3 }],
    ["event with an empty event_type", { popup: "event", event_type: "", employee: 3 }],
    ["event with no employee", { popup: "event", event_type: "contract" }],
    ["event with a null employee", { popup: "event", event_type: "contract", employee: null }],
  ] as const)("a malformed target opens nothing: %s", (_name, fields) => {
    renderWith({ ...base, ...fields } as PaletteOpenOut);
    expect(() => fireEvent.click(screen.getByText("Нээх"))).not.toThrow();
    expect(employeeApi.openOrderDetail).not.toHaveBeenCalled();
    expect(employeeApi.openEvent).not.toHaveBeenCalled();
    expect(screen.queryByTestId("slot-form")).toBeNull();
    expect(screen.getByTestId("location").textContent).toBe("/employees/today/");
  });

  // The server always sends the year of a slot_add row now, so a null year is not listed here: the guard still rejects it.
  it.each([
    ["no year", { popup: "slot_add" }],
    ["a text year", { popup: "slot_add", year: "2026" }],
  ] as const)("a malformed slot_add target with %s does not open the slot form", (_name, fields) => {
    renderWith({ ...base, ...fields } as PaletteOpenOut);
    expect(() => fireEvent.click(screen.getByText("Нээх"))).not.toThrow();
    expect(screen.queryByTestId("slot-form")).toBeNull();
  });

  it("a leave_add row opens the leave pop-up on the page, with the employee preselected", async () => {
    renderWith({ ...base, popup: "leave_add", employee: 3 }, "/employees/today/");
    expect(screen.queryByText("Чөлөө бүртгэх")).toBeNull();
    fireEvent.click(screen.getByText("Нээх"));
    expect(await screen.findByText("Чөлөө бүртгэх")).toBeTruthy();
    // The options carry the employee, so the server decides the visibility rule.
    await waitFor(() =>
      expect(h.get).toHaveBeenCalledWith("/api/v1/leave/options", { params: { query: { employee: "3" } } }),
    );
    expect(screen.getByTestId("location").textContent).toBe("/employees/today/");
  });

  it("a leave_add row with no employee opens the form with nobody preselected", async () => {
    renderWith({ ...base, popup: "leave_add", employee: null });
    fireEvent.click(screen.getByText("Нээх"));
    expect(await screen.findByText("Чөлөө бүртгэх")).toBeTruthy();
    await waitFor(() => expect(h.get).toHaveBeenCalledWith("/api/v1/leave/options", { params: { query: {} } }));
  });

  it("Escape closes the leave pop-up and the page stays where it was", async () => {
    renderWith({ ...base, popup: "leave_add", employee: 3 }, "/employees/today/");
    fireEvent.click(screen.getByText("Нээх"));
    expect(await screen.findByText("Чөлөө бүртгэх")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("Чөлөө бүртгэх")).toBeNull());
    expect(screen.getByTestId("location").textContent).toBe("/employees/today/");
  });

  it("usePalettePopups throws a clear error outside the provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const Probe = () => {
      usePalettePopups();
      return null;
    };
    expect(() => render(<Probe />)).toThrow(/usePalettePopups must be used inside PalettePopups/);
    spy.mockRestore();
  });
});
