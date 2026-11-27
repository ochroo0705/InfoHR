import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { ReportCellOut, ReportGroupOut } from "../../api/reports";
import { ReportRows } from "./ReportRows";
import { createState, type SelState } from "./selectionState";
import type { ReportSelection } from "./useReportSelection";

function text(value: string): ReportCellOut {
  return { value, text: value, money: false, href: "", css: "", style: "", person: 0 };
}

const GROUPED: ReportGroupOut[] = [
  { label: "Санхүү", count: 2, rows: [[text("Бат")], [text("Сарнай")]] },
  { label: "Хүний нөөц", count: 1, rows: [[text("Номин")]] },
];

function renderRows(groups: ReportGroupOut[], grouped: boolean) {
  return render(
    <MemoryRouter>
      <table>
        <tbody>
          <ReportRows groups={groups} grouped={grouped} tableSpan={2} />
        </tbody>
      </table>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ReportRows", () => {
  it("rows_render_groups_with_headings_and_counts", () => {
    const { container } = renderRows(GROUPED, true);

    const rows = Array.from(container.querySelectorAll("tbody > tr"));
    // Two headings and three rows, in order: heading, its rows, heading, its rows.
    expect(rows).toHaveLength(5);
    const heading = rows[0].querySelector("td")!;
    expect(heading.textContent).toBe("Санхүү · 2");
    expect(heading.getAttribute("colspan")).toBe("2");
    expect(heading.className).toBe("font-semibold text-slate-900");
    expect(rows[1].textContent).toBe("Бат");
    expect(rows[3].querySelector("td")!.textContent).toBe("Хүний нөөц · 1");
    expect(rows[4].textContent).toBe("Номин");
  });

  it("an ungrouped table draws its rows only, with no heading", () => {
    const { container } = renderRows([{ label: "", count: 2, rows: [[text("Бат")], [text("Сарнай")]] }], false);

    const rows = Array.from(container.querySelectorAll("tbody > tr"));
    expect(rows.map((row) => row.textContent)).toEqual(["Бат", "Сарнай"]);
    expect(container.querySelector("td[colspan]")).toBeNull();
  });
});

// Selection: the checkbox column, the picked class and the row click rules (report_select.js).

function personCell(value: string, person: number, href: string): ReportCellOut {
  return { value, text: value, money: false, href, css: "", style: "", person };
}

const PEOPLE: ReportGroupOut[] = [
  {
    label: "",
    count: 3,
    rows: [
      [personCell("Бат", 7, "/employees/7/"), text("Алба")],
      [personCell("Сарнай", 8, "/employees/8/"), text("Алба")],
      [personCell("Гадаад", 0, "/employees/9/")],
    ],
  },
];

// Shows the address the router is on, so a test can read where a click led.
function Address() {
  const location = useLocation();
  return <p data-testid="address">{location.pathname + location.search}</p>;
}

function fakeSelection(state: SelState): ReportSelection {
  return {
    state,
    setVisibleIds: vi.fn(),
    toggle: vi.fn(),
    pickRow: vi.fn(),
    pickVisible: vi.fn(),
    pickAll: vi.fn(),
    cancel: vi.fn(),
    body: vi.fn(),
  } as unknown as ReportSelection;
}

function renderPeople(selection: ReportSelection | null, groups: ReportGroupOut[] = PEOPLE) {
  return render(
    <MemoryRouter initialEntries={["/reports/staff/"]}>
      <table>
        <tbody>
          <ReportRows
            groups={groups}
            grouped={false}
            tableSpan={2}
            check={{ css: "", style: "" }}
            selection={selection}
          />
        </tbody>
      </table>
      <Routes>
        <Route path="*" element={<Address />} />
      </Routes>
    </MemoryRouter>,
  );
}

function picked(ids: string[]): SelState {
  return { ids: new Set(ids), all: false, held: false };
}

describe("ReportRows selection", () => {
  it("a row checkbox ticks its person and the picked row gets is-picked", () => {
    const selection = fakeSelection(picked(["7"]));
    const { container } = renderPeople(selection);

    const [first, second] = Array.from(container.querySelectorAll("tbody > tr"));
    expect(first.getAttribute("data-person")).toBe("7");
    expect(first.classList.contains("is-picked")).toBe(true);
    expect(first.getAttribute("aria-selected")).toBe("true");
    const firstBox = first.querySelector<HTMLInputElement>("td input[data-select-row]")!;
    expect(firstBox.checked).toBe(true);
    expect(firstBox.getAttribute("aria-label")).toBe("Мөр сонгох");

    expect(second.getAttribute("data-person")).toBe("8");
    expect(second.classList.contains("is-picked")).toBe(false);
    expect(second.querySelector<HTMLInputElement>("input[data-select-row]")!.checked).toBe(false);

    fireEvent.click(second.querySelector("input[data-select-row]")!);
    expect(selection.pickRow).toHaveBeenCalledTimes(1);
    expect(selection.pickRow).toHaveBeenCalledWith("8", true);
  });

  it("selection on: a checkbox click picks once and the row click does not toggle it again", () => {
    const selection = fakeSelection({ ids: new Set(), all: false, held: true });
    const { container, getByTestId } = renderPeople(selection);

    fireEvent.click(container.querySelector("tbody tr[data-person='8'] input[data-select-row]")!);
    expect(selection.pickRow).toHaveBeenCalledTimes(1);
    expect(selection.pickRow).toHaveBeenCalledWith("8", true);
    expect(getByTestId("address").textContent).toBe("/reports/staff/");
  });

  it("selection on: ctrl-click toggles the person and opens nothing", () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const selection = fakeSelection({ ids: new Set(), all: false, held: true });
    const { getByText, getByTestId } = renderPeople(selection);

    fireEvent.click(getByText("Бат").closest("td")!, { ctrlKey: true });
    expect(selection.pickRow).toHaveBeenCalledTimes(1);
    expect(selection.pickRow).toHaveBeenCalledWith("7", true);
    expect(open).not.toHaveBeenCalled();
    expect(getByTestId("address").textContent).toBe("/reports/staff/");
  });

  it("selection on: a click on a person-0 row does not toggle and falls through to its link", () => {
    const selection = fakeSelection({ ids: new Set(), all: false, held: true });
    const { getByText, getByTestId } = renderPeople(selection);

    fireEvent.click(getByText("Гадаад").closest("a")!);
    expect(selection.pickRow).not.toHaveBeenCalled();
    expect(getByTestId("address").textContent).toBe("/employees/9/");
  });

  it("a person-0 row has no checkbox and no data-person", () => {
    const { container } = renderPeople(fakeSelection(picked([])));
    const third = container.querySelectorAll("tbody > tr")[2];
    expect(third.hasAttribute("data-person")).toBe(false);
    expect(third.classList.contains("is-picked")).toBe(false);
    expect(third.querySelector("input")).toBeNull();
  });

  it("without selection there are no checkboxes and no picked marks", () => {
    const { container } = renderPeople(null);
    expect(container.querySelector("input")).toBeNull();
    expect(container.querySelector("tr[data-person]")).toBeNull();
    expect(container.querySelector(".is-picked")).toBeNull();
  });

  it("selection on: a row click toggles the person and does not open the link", () => {
    const selection = fakeSelection({ ids: new Set(), all: false, held: true });
    const { getByText, getByTestId } = renderPeople(selection);

    fireEvent.click(getByText("Бат").closest("td")!);
    expect(selection.pickRow).toHaveBeenCalledWith("7", true);
    expect(getByTestId("address").textContent).toBe("/reports/staff/");
  });

  it("selection on: a click on the row's link toggles the person and does not follow the link", () => {
    const selection = fakeSelection({ ids: new Set(), all: false, held: true });
    const { getByText, getByTestId } = renderPeople(selection);

    fireEvent.click(getByText("Бат").closest("a")!);
    expect(selection.pickRow).toHaveBeenCalledTimes(1);
    expect(selection.pickRow).toHaveBeenCalledWith("7", true);
    expect(getByTestId("address").textContent).toBe("/reports/staff/");
  });

  it("selection on: a click on a row with a picked person unticks it", () => {
    const selection = fakeSelection(picked(["7"]));
    const { getByText } = renderPeople(selection);

    fireEvent.click(getByText("Бат").closest("td")!);
    expect(selection.pickRow).toHaveBeenCalledWith("7", false);
  });

  it("selection off: a row click opens the row's first link in the app", () => {
    const selection = fakeSelection(createState());
    const { container, getByTestId } = renderPeople(selection);

    // The second cell of the first row: the row opens the first link of the row (Бат's), not the cell's own text.
    fireEvent.click(container.querySelectorAll("tbody > tr")[0].querySelectorAll("td")[2]);
    expect(getByTestId("address").textContent).toBe("/employees/7/");
    expect(selection.pickRow).not.toHaveBeenCalled();
  });

  it("selection off: a click on the row's link follows that link", () => {
    const { getByText, getByTestId } = renderPeople(fakeSelection(createState()));

    fireEvent.click(getByText("Бат").closest("a")!);
    expect(getByTestId("address").textContent).toBe("/employees/7/");
  });

  it("selection off: a plain click on a Django-only link loads that page", () => {
    const original = window.location;
    Object.defineProperty(window, "location", { value: { href: "" }, writable: true, configurable: true });
    try {
      const groups: ReportGroupOut[] = [{ label: "", count: 1, rows: [[personCell("Бат", 7, "/reports/staff/7/")]] }];
      const { getByText, getByTestId } = renderPeople(fakeSelection(createState()), groups);

      fireEvent.click(getByText("Бат").closest("td")!);
      expect(window.location.href).toBe("/reports/staff/7/");
      expect(getByTestId("address").textContent).toBe("/reports/staff/");
    } finally {
      Object.defineProperty(window, "location", { value: original, writable: true, configurable: true });
    }
  });

  it("selection off: ctrl-click opens the link in a new window and stays on the page", () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const { getByText, getByTestId } = renderPeople(fakeSelection(createState()));

    fireEvent.click(getByText("Бат").closest("td")!, { ctrlKey: true });
    expect(open).toHaveBeenCalledWith("/employees/7/", "_blank");
    expect(getByTestId("address").textContent).toBe("/reports/staff/");
  });

  it("selection off: a middle click opens the link in a new window", () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const { getByText } = renderPeople(fakeSelection(createState()));

    fireEvent(getByText("Бат").closest("td")!, new MouseEvent("auxclick", { bubbles: true, button: 1 }));
    expect(open).toHaveBeenCalledWith("/employees/7/", "_blank");
  });

  it("a text selection is not a click", () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    vi.spyOn(window, "getSelection").mockReturnValue({ toString: () => "Бат" } as unknown as Selection);
    const { getByText, getByTestId } = renderPeople(fakeSelection(createState()));

    fireEvent.click(getByText("Бат").closest("td")!, { ctrlKey: true });
    expect(open).not.toHaveBeenCalled();
    expect(getByTestId("address").textContent).toBe("/reports/staff/");
  });
});
