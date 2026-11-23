import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { TodayOut } from "../../api/today";
import { PalettePanelContext, type PalettePanelApi } from "../../shell/palette/PalettePanelContext";
import { Tiles } from "./Tiles";
import { TodayHeader } from "./TodayHeader";

// TodayHeader reads the assistant panel from its context; these tests only need a stand-in for it.
const palette: PalettePanelApi = {
  open: vi.fn(),
  close: vi.fn(),
  toggle: vi.fn(),
  isOpen: false,
  openedByUser: false,
  session: 0,
};

vi.mock("./AttentionTile", () => ({
  AttentionTile: () => <a id="attention-tile" href="#attention" />,
}));

function makeData(overrides: Partial<TodayOut> = {}): TodayOut {
  return {
    today: "2026-11-17",
    headcount: 12,
    away_today: 3,
    has_own_page: true,
    shortcuts: { add_employee: true, record_leave: true, orders: true },
    box: { urgent_count: 0, soon_count: 0, gap_count: 0 },
    show_views: false,
    company: null,
    strip: {} as TodayOut["strip"],
    upcoming: {} as TodayOut["upcoming"],
    ...overrides,
  } as TodayOut;
}

function renderHeader(data: TodayOut) {
  return render(
    <PalettePanelContext.Provider value={palette}>
      <MemoryRouter>
        <TodayHeader data={data} />
      </MemoryRouter>
    </PalettePanelContext.Provider>,
  );
}

describe("TodayHeader", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.stubEnv("VITE_LEGACY_ORIGIN", "http://dj");
    Object.defineProperty(window, "location", {
      value: { href: "" },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
    Object.defineProperty(window, "location", {
      value: originalLocation,
      writable: true,
      configurable: true,
    });
  });

  it("hides «Ажилтан нэмэх» without shortcuts.add_employee", () => {
    renderHeader(makeData({ shortcuts: { add_employee: false, record_leave: true, orders: true } }));
    expect(screen.queryByText("Ажилтан нэмэх")).toBeNull();
  });

  it("always shows «Хайх» and toggles the assistant panel on click", () => {
    renderHeader(makeData({ shortcuts: { add_employee: false, record_leave: false, orders: false } }));
    const button = screen.getByRole("button", { name: /Хайх/ });
    fireEvent.click(button);
    expect(palette.toggle).toHaveBeenCalledTimes(1);
  });

  it("hides «Миний хуудас →» when has_own_page is false", () => {
    renderHeader(makeData({ has_own_page: false }));
    expect(screen.queryByText("Миний хуудас →")).toBeNull();
  });

  it("shows «Миний хуудас →» when has_own_page is true", () => {
    renderHeader(makeData({ has_own_page: true }));
    expect(screen.getByRole("link", { name: "Миний хуудас →" }).getAttribute("href")).toBe("/me/");
  });
});

describe("Tiles", () => {
  it('shows the headcount in data-tile="headcount"', () => {
    const { container } = render(
      <MemoryRouter>
        <Tiles data={makeData({ headcount: 42 })} />
      </MemoryRouter>,
    );
    expect(container.querySelector('[data-tile="headcount"]')?.textContent).toBe("42");
  });

  it('shows away_today in data-tile="away"', () => {
    const { container } = render(
      <MemoryRouter>
        <Tiles data={makeData({ away_today: 5 })} />
      </MemoryRouter>,
    );
    expect(container.querySelector('[data-tile="away"]')?.textContent).toBe("5");
  });
});
