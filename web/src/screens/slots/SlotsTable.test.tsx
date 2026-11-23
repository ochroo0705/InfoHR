import type { ComponentProps } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SlotRowOut, SlotTotalsOut } from "../../api/slots";
import { SlotsTable } from "./SlotsTable";

const ROW_OK: SlotRowOut = {
  id: 1,
  position: "Нягтлан бодогч",
  position_id: 1,
  branch: "Төв оффис",
  branch_id: 10,
  kind: "Main",
  kind_label: "Үндсэн",
  posts: 3,
  used: 1,
  free: 2,
  // A class React never invents here: it can only come from the API answer.
  free_class: "text-slate-900",
};

const ROW_FULL: SlotRowOut = {
  id: 2,
  position: "Жолооч",
  position_id: 2,
  branch: "Салбар 2",
  branch_id: 11,
  kind: "Temporary",
  kind_label: "Түр",
  posts: 1,
  used: 1,
  free: 0,
  free_class: "text-amber-700",
};

const TOTALS: SlotTotalsOut = { posts: 40, used: 25, free: 15 };

type Props = Partial<ComponentProps<typeof SlotsTable>>;

function renderTable(props: Props = {}) {
  const onMore = vi.fn();
  const onOpen = vi.fn();
  const utils = render(
    <SlotsTable
      rows={[ROW_OK, ROW_FULL]}
      totals={TOTALS}
      emptyText="2026 оны орон тоо бүртгэгдээгүй"
      hasMore={false}
      onMore={onMore}
      onOpen={onOpen}
      {...props}
    />,
  );
  return { ...utils, onMore, onOpen };
}

// A stub IntersectionObserver that the test fires by hand. Each observer keeps its callback.
type Observer = { callback: IntersectionObserverCallback; disconnect: () => void };
let observers: Observer[] = [];

beforeEach(() => {
  observers = [];
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      callback: IntersectionObserverCallback;
      constructor(callback: IntersectionObserverCallback) {
        this.callback = callback;
        observers.push({ callback, disconnect: () => undefined });
      }
      observe() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SlotsTable", () => {
  it("draws the kind label and the free count with the class from the API", () => {
    const { container } = renderTable();

    const freeOk = within(rowOf("Нягтлан бодогч")).getByText("2");
    expect(freeOk.className).toContain("text-right");
    expect(freeOk.className).toContain("text-slate-900");

    const freeFull = within(rowOf("Жолооч")).getByText("0");
    expect(freeFull.className).toContain("text-amber-700");
    expect(within(rowOf("Жолооч")).getByText("Түр")).toBeTruthy();
    expect(container.querySelectorAll("tbody tr")).toHaveLength(2);
  });

  it("shows the footer totals from the API, not the sum of the loaded rows", () => {
    renderTable({ rows: [ROW_OK] });

    const footer = document.querySelector("tfoot") as HTMLElement;
    expect(within(footer).getByText("Нийт")).toBeTruthy();
    expect(within(footer).getByText("40")).toBeTruthy();
    expect(within(footer).getByText("25")).toBeTruthy();
    expect(within(footer).getByText("15")).toBeTruthy();
  });

  it("shows no footer and the empty text when there are no rows and no totals", () => {
    renderTable({ rows: [], totals: { posts: 0, used: 0, free: 0 } });

    expect(document.querySelector("tfoot")).toBeNull();
    expect(screen.getByText("2026 оны орон тоо бүртгэгдээгүй")).toBeTruthy();
  });

  it("a row click calls onOpen with the row id", () => {
    const { onOpen } = renderTable();

    fireEvent.click(rowOf("Жолооч"));

    expect(onOpen).toHaveBeenCalledWith(2);
  });

  it("Enter on a focused row calls onOpen", () => {
    const { onOpen } = renderTable();
    const row = rowOf("Нягтлан бодогч");

    expect(row.getAttribute("tabindex")).toBe("0");
    expect(row.getAttribute("role")).toBe("button");
    fireEvent.keyDown(row, { key: "Enter" });

    expect(onOpen).toHaveBeenCalledWith(1);
  });

  it("Space on a focused row calls onOpen", () => {
    const { onOpen } = renderTable();

    fireEvent.keyDown(rowOf("Жолооч"), { key: " " });

    expect(onOpen).toHaveBeenCalledWith(2);
  });

  it("loads the next batch when the sentinel shows", () => {
    const { onMore } = renderTable({ hasMore: true });
    expect(observers.length).toBeGreaterThan(0);

    const observer = observers[observers.length - 1];
    observer.callback([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);

    expect(onMore).toHaveBeenCalledTimes(1);
  });
});

function rowOf(position: string): HTMLElement {
  return screen.getByText(position).closest("tr") as HTMLElement;
}
