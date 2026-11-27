// The harness is imported first: it stubs fetch before ../../../api/client (and so the reports API) load.
import { newClient, resetFetch, resetObservers } from "../../../api/testSupport";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import { setCsrf } from "../../../api/client";
import { fetchEditor, saveEdit, type ReportEditor, type ReportEditTarget } from "../../../api/reportsEdit";
import type { ReportCellOut, ReportTableOut } from "../../../api/reports";
import { ReportTable, type ReportTableProps } from "../ReportTable";
import { EditLegend, EditMarks, columnMarks, markClass, readMarksOn, useEditMarks, writeMarksOn } from "./EditMarks";

vi.mock("../../../api/reportsEdit", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/reportsEdit")>();
  return { ...actual, fetchEditor: vi.fn(), saveEdit: vi.fn(), bulkCells: vi.fn() };
});

const KEY = "hr.editMarks";
const LEGEND_EDIT = "Шууд засна (F2, давхар товших, бичих)";
const LEGEND_CORRECT = "Засвар — шалтгаантай";
const TOGGLE_TEXT = "Засварлах боломжтой баганыг өнгөөр харуулах";

const PLAIN: ReportEditTarget = { route: "cell", person: 7, field: "job_title", kind: "", key: 0, record: 0, salary: false };
const CORRECT: ReportEditTarget = { route: "correct", person: 7, field: "job_title", kind: "", key: 0, record: 0, salary: false };

function cell(value: string, edit: ReportEditTarget | null = null): ReportCellOut {
  return { value, text: value, money: false, href: "", css: "", style: "", person: 0, edit };
}

const HEAD = { label: "", href: "", append_href: "", arrow: "", css: "", sticky_left: "" };

// Two columns: the name (plain edit) and the position (correction). Row 2 has no edit targets.
function markedTable(): ReportTableOut {
  return {
    address: "/reports/staff/",
    check_css: "",
    check_style: "",
    clear_rules_url: "",
    count: 2,
    footer: null,
    groups: [
      {
        label: "",
        count: 2,
        rows: [
          [cell("Бат", PLAIN), cell("Захирал", CORRECT)],
          [cell("Сарнай"), cell("Нярав")],
        ],
      },
    ],
    heads: [
      { ...HEAD, label: "Нэр" },
      { ...HEAD, label: "Албан тушаал" },
    ],
    next_offset: null,
    note: "",
    pin: 0,
    query: "",
    rules_text: "",
    selectable: false,
    shows_count: true,
    table_span: 2,
  } as ReportTableOut;
}

// No editable cell at all.
function plainTable(): ReportTableOut {
  return {
    ...markedTable(),
    count: 1,
    groups: [{ label: "", count: 1, rows: [[cell("Бат"), cell("Захирал")]] }],
  };
}

function editorOf(over: Partial<ReportEditor> = {}): ReportEditor {
  return {
    blocked: "",
    choices: [],
    error: "",
    hidden: {},
    kind: "text",
    label: "Албан тушаал",
    loaded: "tok1",
    maxlength: 50,
    name: "job_title",
    note: "",
    old: "Бат",
    reason: false,
    reason_text: "",
    required: false,
    value: "Бат",
    ...over,
  };
}

const mockEditor = vi.mocked(fetchEditor);
const mockSave = vi.mocked(saveEdit);
const gridOf = (container: HTMLElement) => container.querySelector("table[data-grid]") as HTMLTableElement;

let client: QueryClient;

beforeEach(() => {
  resetFetch();
  setCsrf("");
  client = newClient();
  window.localStorage.clear();
  mockEditor.mockReset();
  mockSave.mockReset();
});

afterEach(() => {
  cleanup();
  resetObservers();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

function renderTable(overrides: Partial<ReportTableProps> = {}) {
  const props: ReportTableProps = {
    reportKey: "staff",
    query: "q=a",
    table: markedTable(),
    dataUpdatedAt: 1,
    marksOn: true,
    editKinds: ["plain", "correct"],
    ...overrides,
  };
  const ui = (current: ReportTableProps) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ReportTable {...current} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const result = render(ui(props));
  return { ...result, rerenderWith: (next: Partial<ReportTableProps>) => result.rerender(ui({ ...props, ...next })) };
}

describe("EditMarks toggle", () => {
  it("renders nothing when the table has no editable column", () => {
    const { container, queryByRole } = render(<EditMarks kinds={[]} on onToggle={() => {}} />);
    expect(container.innerHTML).toBe("");
    expect(queryByRole("button")).toBeNull();
  });

  it("shows the pencil toggle with the template's title and label, its pressed state, and calls onToggle", () => {
    const onToggle = vi.fn();
    const { getByRole, rerender } = render(<EditMarks kinds={["plain"]} on onToggle={onToggle} />);
    const button = getByRole("button", { name: TOGGLE_TEXT });
    expect(button.getAttribute("title")).toBe(TOGGLE_TEXT);
    expect(button.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(button);
    expect(onToggle).toHaveBeenCalledTimes(1);

    rerender(<EditMarks kinds={["plain"]} on={false} onToggle={onToggle} />);
    expect(getByRole("button", { name: TOGGLE_TEXT }).getAttribute("aria-pressed")).toBe("false");
  });
});

describe("EditLegend", () => {
  it("draws nothing when no editable kind is present", () => {
    const { container } = render(<EditLegend kinds={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("lists the editable item, and the correction item only when a correction column is present", () => {
    const plain = render(<EditLegend kinds={["plain", "row"]} />);
    expect(plain.getByText(LEGEND_EDIT)).toBeTruthy();
    expect(plain.queryByText(LEGEND_CORRECT)).toBeNull();
    plain.unmount();

    const correct = render(<EditLegend kinds={["correct"]} />);
    expect(correct.getByText(LEGEND_EDIT)).toBeTruthy();
    expect(correct.getByText(LEGEND_CORRECT)).toBeTruthy();
  });
});

describe("the remembered choice", () => {
  function Probe() {
    const marks = useEditMarks();
    return (
      <button type="button" onClick={marks.toggle}>
        {marks.on ? "on" : "off"}
      </button>
    );
  }

  it("defaults to on when nothing is stored", () => {
    expect(readMarksOn()).toBe(true);
  });

  it("writes 1 or 0 under the key grid_nav.js uses, and the choice survives a remount", () => {
    const first = render(<Probe />);
    fireEvent.click(first.getByRole("button"));
    expect(window.localStorage.getItem(KEY)).toBe("0");
    expect(first.getByRole("button").textContent).toBe("off");
    first.unmount();

    const second = render(<Probe />);
    expect(second.getByRole("button").textContent).toBe("off");
    fireEvent.click(second.getByRole("button"));
    expect(window.localStorage.getItem(KEY)).toBe("1");
  });

  it("a throwing localStorage still renders, defaults to on, and the toggle does not throw", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { getByRole } = render(<Probe />);
    expect(getByRole("button").textContent).toBe("on");
    expect(() => fireEvent.click(getByRole("button"))).not.toThrow();
    expect(() => writeMarksOn(false)).not.toThrow();
    expect(readMarksOn()).toBe(true);
  });
});

describe("columnMarks and markClass", () => {
  it("marks a column by its strongest kind (correction over editable), and none when no cell is editable", () => {
    const rows = [
      { heading: false, cells: [null, cell("a", PLAIN), cell("b", CORRECT), cell("c")] },
      { heading: false, cells: [null, cell("d"), cell("e", PLAIN), cell("f")] },
    ];
    expect(columnMarks(rows)).toEqual(["", "edit", "correct", ""]);
    expect(markClass("edit")).toBe("col-edit");
    expect(markClass("correct")).toBe("col-correct");
    expect(markClass("")).toBe("");
  });
});

describe("ReportTable edit marks", () => {
  it("marks the editable and correction columns, their headers and the table when on, and shows the legend", () => {
    const { container, getByText } = renderTable();
    expect(getByText("Бат").closest("td")!.classList.contains("col-edit")).toBe(true);
    expect(getByText("Захирал").closest("td")!.classList.contains("col-correct")).toBe(true);
    expect(getByText("Сарнай").closest("td")!.classList.contains("col-edit")).toBe(true);
    expect(container.querySelector("table")!.classList.contains("edit-marks")).toBe(true);
    const heads = container.querySelectorAll("thead th");
    expect(heads[0].classList.contains("col-edit")).toBe(true);
    expect(heads[1].classList.contains("col-correct")).toBe(true);
    expect(heads[1].getAttribute("title")).toBe("Засвар: шалтгаантай");
    expect(getByText(LEGEND_CORRECT)).toBeTruthy();
  });

  it("toggling off removes the marks and the legend, and editing still opens", async () => {
    mockEditor.mockResolvedValue(editorOf());
    const { container, getByText, queryByText, rerenderWith } = renderTable();
    rerenderWith({ marksOn: false });

    expect(getByText("Бат").closest("td")!.classList.contains("col-edit")).toBe(false);
    expect(getByText("Захирал").closest("td")!.classList.contains("col-correct")).toBe(false);
    expect(container.querySelector("table")!.classList.contains("edit-marks")).toBe(false);
    expect(queryByText(LEGEND_EDIT)).toBeNull();

    fireEvent.click(getByText("Бат").closest("td")!);
    fireEvent.keyDown(gridOf(container), { key: "F2" });
    await waitFor(() => expect(container.querySelector("input")).not.toBeNull());
    expect(container.querySelector<HTMLInputElement>("input")!.value).toBe("Бат");
  });

  it("a table with no editable cell shows no marks and no legend", () => {
    const { container, queryByText } = renderTable({ table: plainTable(), editKinds: [] });
    expect(container.querySelectorAll(".col-edit, .col-correct").length).toBe(0);
    expect(queryByText(LEGEND_EDIT)).toBeNull();
  });
});
