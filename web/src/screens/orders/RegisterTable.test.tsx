import { act, cleanup, fireEvent, render } from "@testing-library/react";
import type { ComponentProps, ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import type { OrderRegisterOut, OrderRegisterRowOut } from "../../api/orderRegister";
import { RegisterTable } from "./RegisterTable";

const REGISTERED: OrderRegisterRowOut = {
  key: "o1",
  order_id: 1,
  employee_id: 7,
  number_label: "№ 12 / 2026",
  number_muted: false,
  date_label: "2026-03-01",
  employee_name: "Бат Эрдэнэ",
  department: "Санхүү",
  summary: "Ажилд авах",
  state: "registered",
  state_label: "Бүртгэгдсэн",
  chip_class: "chip-registered",
  awaiting: false,
  awaiting_chip: null,
  cancelled: false,
  pickable: true,
  opens: "detail",
};

const SIGNED: OrderRegisterRowOut = {
  ...REGISTERED,
  key: "o2",
  order_id: 2,
  number_label: "№ 13 / 2026",
  employee_name: "Сарнай",
  summary: "Цалин нэмэх",
  state: "signed",
  state_label: "Гарын үсэгтэй",
  chip_class: "seal",
};

// A cancelled order still has its number, so the number is not muted (muted only when the number is empty).
const CANCELLED: OrderRegisterRowOut = {
  ...REGISTERED,
  key: "o3",
  order_id: 3,
  number_label: "№ 14 / 2026",
  number_muted: false,
  employee_name: "Номин",
  summary: "Цуцалсан тушаал",
  state: "cancelled",
  state_label: "Цуцлагдсан",
  chip_class: "chip-cancelled",
  cancelled: true,
  pickable: false,
};

// A legacy row has no order, so its number is empty: the server mutes it.
const LEGACY: OrderRegisterRowOut = {
  key: "legacy:5",
  order_id: null,
  employee_id: 9,
  number_label: "—",
  number_muted: true,
  date_label: "—",
  employee_name: "Дорж",
  department: "Бусад",
  summary: "Хуучин бүртгэл",
  state: "legacy",
  state_label: "Хуучин",
  chip_class: "chip-legacy",
  awaiting: false,
  awaiting_chip: null,
  cancelled: false,
  pickable: false,
  opens: "employee",
};

const AWAITING: OrderRegisterRowOut = {
  ...REGISTERED,
  key: "c1",
  order_id: 20,
  employee_name: "Оюун",
  summary: "Гэрээ өөрчлөх",
  awaiting: true,
  awaiting_chip: { label: "Гарын үсэг хүлээж байна", class_name: "awaiting-chip" },
};

// The server's contract: `next` is the sort value a click sends (a leading "-" for descending); `arrow` is the mark
// of the current direction ("" when the column is not sorted); `aria` is "ascending", "descending" or "".
const SORT_HEADS: OrderRegisterOut["sort_heads"] = {
  number: { next: "number", arrow: "↑", aria: "ascending" },
  date: { next: "-date", arrow: "", aria: "" },
  employee: { next: "employee", arrow: "", aria: "" },
};

// The address the page is on: the filters must survive in the sort href.
const ADDRESS = "/employees/orders/?year=2026&state=signed&sort=-number";

let observerCallback: IntersectionObserverCallback | null = null;
let observerCount = 0;
const disconnectSpy = vi.fn();

beforeEach(() => {
  observerCallback = null;
  observerCount = 0;
  disconnectSpy.mockClear();
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(callback: IntersectionObserverCallback) {
        observerCallback = callback;
        observerCount += 1;
      }
      observe() {}
      unobserve() {}
      disconnect() {
        disconnectSpy();
      }
      takeRecords() {
        return [];
      }
    },
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

type Overrides = Partial<ComponentProps<typeof RegisterTable>>;

function table(overrides: Overrides = {}) {
  const props = {
    rows: [REGISTERED, SIGNED, CANCELLED, LEGACY, AWAITING],
    sort: "-number",
    sortHeads: SORT_HEADS,
    canManage: true,
    picked: new Set<string>(),
    onPick: vi.fn(),
    onPickAll: vi.fn(),
    onOpen: vi.fn(),
    onSort: vi.fn(),
    hasMore: false,
    loadingMore: false,
    onMore: vi.fn(),
    ...overrides,
  };
  return { props, element: <RegisterTable {...props} /> };
}

function renderTable(overrides: Overrides = {}, address = ADDRESS) {
  const { props, element } = table(overrides);
  const result = render(<MemoryRouter initialEntries={[address]}>{element}</MemoryRouter>);
  return { ...result, props };
}

// Re-renders the same table under the same router (keeps the address), with new props.
function rerenderTable(
  rerender: (ui: ReactElement) => void,
  props: ComponentProps<typeof RegisterTable>,
  next: Partial<ComponentProps<typeof RegisterTable>>,
) {
  rerender(
    <MemoryRouter initialEntries={[ADDRESS]}>
      <RegisterTable {...props} {...next} />
    </MemoryRouter>,
  );
}

function fireObserver(intersecting: boolean) {
  act(() => {
    observerCallback!([{ isIntersecting: intersecting } as IntersectionObserverEntry], {} as IntersectionObserver);
  });
}

describe("RegisterTable", () => {
  it("renders a registered, signed, cancelled, legacy and awaiting row with the server's classes", () => {
    const { getByText, getAllByText, container } = renderTable();

    expect(getByText("Гарын үсэгтэй").className).toBe("seal");
    expect(getAllByText("Бүртгэгдсэн")[0].className).toBe("chip-registered");
    expect(getByText("Хуучин").className).toBe("chip-legacy");
    expect(getByText("Гарын үсэг хүлээж байна").className).toBe("awaiting-chip");

    const cancelledRow = getByText("Цуцалсан тушаал").closest("tr")!;
    expect(cancelledRow.className).toContain("text-slate-400 line-through");
    // The number of a cancelled order is plain text (not muted).
    expect(getByText("№ 14 / 2026").closest("span")).toBeNull();
    // The legacy row's empty number is muted by the server.
    expect(getAllByText("—")[0].className).toBe("text-slate-400");
    expect(container.querySelector("table")!.getAttribute("data-sort")).toBe("-number");
  });

  it("row click opens the detail only for opens=detail", () => {
    const { getByText, props } = renderTable();

    fireEvent.click(getByText("Ажилд авах"));
    expect(props.onOpen).toHaveBeenCalledWith(REGISTERED);
    expect(props.onOpen).toHaveBeenCalledTimes(1);

    fireEvent.click(getByText("Хуучин бүртгэл"));
    expect(props.onOpen).toHaveBeenCalledTimes(1);
  });

  it("row click on an employee row navigates to the employee page", () => {
    const { props, element } = table();
    const { getByText } = render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={element} />
          <Route path="/employees/:id/" element={<div>EMPLOYEE PAGE</div>} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(getByText("Хуучин бүртгэл"));
    expect(getByText("EMPLOYEE PAGE")).toBeTruthy();
    expect(props.onOpen).not.toHaveBeenCalled();
  });

  it("checkbox click does not open the row", () => {
    const { getAllByLabelText, props } = renderTable();

    const boxes = getAllByLabelText("Тушаал сонгох") as HTMLInputElement[];
    fireEvent.click(boxes[0]);

    expect(props.onPick).toHaveBeenCalledWith("o1", true);
    expect(props.onOpen).not.toHaveBeenCalled();
  });

  it("select-all checks only pickable rows", () => {
    const pickableKeys = new Set(["o1", "o2", "c1"]);
    const { getAllByLabelText, getByLabelText, props, rerender } = renderTable();

    expect(getAllByLabelText("Тушаал сонгох")).toHaveLength(3);
    const all = getByLabelText("Бүгдийг сонгох") as HTMLInputElement;
    expect(all.checked).toBe(false);

    fireEvent.click(all);
    expect(props.onPickAll).toHaveBeenCalledWith(true);

    rerenderTable(rerender, props, { picked: pickableKeys });
    expect((getByLabelText("Бүгдийг сонгох") as HTMLInputElement).checked).toBe(true);
  });

  it("select-all leaves an unpickable row unchecked when another is picked", () => {
    const { getAllByLabelText, getByLabelText, props, rerender } = renderTable();

    // Only the first pickable row is picked: the header stays unchecked, and the cancelled row (not pickable) has no box.
    rerenderTable(rerender, props, { picked: new Set(["o1"]) });
    expect((getByLabelText("Бүгдийг сонгох") as HTMLInputElement).checked).toBe(false);
    const boxes = getAllByLabelText("Тушаал сонгох") as HTMLInputElement[];
    expect(boxes).toHaveLength(3);
    expect(boxes.map((box) => box.checked)).toEqual([true, false, false]);
  });

  it("has no checkbox column without canManage", () => {
    const { queryByLabelText, queryAllByLabelText } = renderTable({ canManage: false });
    expect(queryByLabelText("Бүгдийг сонгох")).toBeNull();
    expect(queryAllByLabelText("Тушаал сонгох")).toHaveLength(0);
  });

  it("plain click on a sort head prevents the link and calls onSort with head.next", () => {
    const { getByText, props } = renderTable();

    // fireEvent returns false when the default was prevented.
    const notPrevented = fireEvent.click(getByText("Дугаар"));
    expect(notPrevented).toBe(false);
    expect(props.onSort).toHaveBeenCalledWith("number");
    expect(props.onSort).toHaveBeenCalledTimes(1);
  });

  it("ctrl or meta click on a sort head is left to the browser and does not call onSort", () => {
    const { getByText, props } = renderTable();

    const ctrlNotPrevented = fireEvent.click(getByText("Дугаар"), { ctrlKey: true });
    const metaNotPrevented = fireEvent.click(getByText("Дугаар"), { metaKey: true });

    expect(ctrlNotPrevented).toBe(true);
    expect(metaNotPrevented).toBe(true);
    expect(props.onSort).not.toHaveBeenCalled();
  });

  it("the sort href is the router address with the sort replaced and the filters kept", () => {
    const { getByText } = renderTable();

    expect(getByText("Дугаар").getAttribute("href")).toBe("/employees/orders/?year=2026&state=signed&sort=number");
    expect(getByText("Тушаалын огноо").getAttribute("href")).toBe(
      "/employees/orders/?year=2026&state=signed&sort=-date",
    );
  });

  it("aria-sort and arrow come from sortHeads", () => {
    const { getByText } = renderTable();

    expect(getByText("Дугаар").closest("th")!.getAttribute("aria-sort")).toBe("ascending");
    const arrow = getByText("↑");
    expect(arrow.getAttribute("aria-hidden")).toBe("true");
    expect(getByText("Тушаалын огноо").closest("th")!.hasAttribute("aria-sort")).toBe(false);
  });

  it("the more pill calls onMore once when it scrolls into view and again on click, with no arguments", () => {
    const { getByText, props } = renderTable({ hasMore: true });

    fireObserver(true);
    expect(props.onMore).toHaveBeenCalledTimes(1);
    expect(props.onMore).toHaveBeenLastCalledWith();

    fireObserver(true);
    expect(props.onMore).toHaveBeenCalledTimes(1);

    fireEvent.click(getByText("Цааш харуулах"));
    expect(props.onMore).toHaveBeenCalledTimes(2);
    expect(props.onMore).toHaveBeenLastCalledWith();
  });

  it("a click on the pill while a batch loads does not call onMore", () => {
    const { getByText, props } = renderTable({ hasMore: true, loadingMore: true });

    fireEvent.click(getByText("Цааш харуулах"));
    expect(props.onMore).not.toHaveBeenCalled();
  });

  it("re-arms across batches: the sentinel calls onMore again once the next batch is idle", () => {
    const { props, rerender } = renderTable({ hasMore: true, loadingMore: false });

    fireObserver(true);
    expect(props.onMore).toHaveBeenCalledTimes(1);

    // The batch is requested: the sentinel stops observing and the old observer is disconnected.
    rerenderTable(rerender, props, { loadingMore: true });
    expect(disconnectSpy).toHaveBeenCalled();

    // The batch lands (still more to load): observing starts again, and the pill is still in view.
    rerenderTable(rerender, props, { loadingMore: false });
    fireObserver(true);
    expect(props.onMore).toHaveBeenCalledTimes(2);
  });

  it("the more pill does not observe while a batch is loading", () => {
    renderTable({ hasMore: true, loadingMore: true });
    expect(observerCount).toBe(0);
  });

  it("with autoLoad off the pill does not observe, and its click still calls onMore", () => {
    const { props, getByRole } = renderTable({ hasMore: true, loadingMore: false, autoLoad: false });
    expect(observerCount).toBe(0);

    fireEvent.click(getByRole("button", { name: "Цааш харуулах" }));
    expect(props.onMore).toHaveBeenCalledTimes(1);
  });

  it("empty state", () => {
    const { getByText, props } = renderTable({ rows: [] });
    const cell = getByText("Тушаал олдсонгүй");
    expect(cell.closest("td")!.getAttribute("colspan")).toBe("7");
    expect(props.onMore).not.toHaveBeenCalled();
  });
});
