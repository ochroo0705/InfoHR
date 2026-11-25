import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReportFormatModelOut } from "../../../api/reports";
import { ConfirmProvider } from "../../../widgets/confirm";
import { FormatModal } from "./FormatModal";
import { FORMAT_TEXT } from "./popupTexts";

// The API client is replaced by a stub that answers by path; the real hooks run. Navigation is a spy.
const h = vi.hoisted(() => ({ get: vi.fn(), navigate: vi.fn() }));

vi.mock("../../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

vi.mock("react-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router")>()),
  useNavigate: () => h.navigate,
}));

const COLUMNS = [
  { key: "name", kind: "text", label: "Нэр" },
  { key: "salary", kind: "number", label: "Цалин" },
  { key: "joined", kind: "date", label: "Элссэн" },
];

const OPS = {
  text: [
    { code: "eq", label: "Тэнцүү" },
    { code: "contains", label: "Агуулсан" },
    { code: "empty", label: "Хоосон" },
    { code: "filled", label: "Хоосон биш" },
  ],
  number: [
    { code: "gt", label: "Их" },
    { code: "between", label: "Хооронд …" },
  ],
  date: [
    { code: "eq", label: "Тэнцүү" },
    { code: "next_days", label: "ирэх … хоногт" },
  ],
};

const AGGS = { text: ["count"], number: ["sum", "avg"], date: ["count"] };
const AGG_LABELS = { count: "Тоо", sum: "Нийлбэр", avg: "Дундаж" };

const COLOURS = [
  { key: "red", label: "Улаан", classes: "bg-red-100 text-red-800" },
  { key: "green", label: "Ногоон", classes: "bg-green-100 text-green-800" },
];

function model(over: Partial<ReportFormatModelOut> = {}): ReportFormatModelOut {
  return {
    columns: COLUMNS,
    shown: ["name", "salary"],
    ops: OPS,
    aggs: AGGS,
    agg_labels: AGG_LABELS,
    colours: COLOURS,
    totals: [],
    marks: [],
    pin: 0,
    keep: [["add", "x"]],
    ...over,
  };
}

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function makeClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function renderPop(m: ReportFormatModelOut | "pending" | 403, onClose = vi.fn()) {
  h.get.mockImplementation(async (path: string) => {
    if (path !== "/api/v1/reports/{key}/format") return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    if (m === "pending") return new Promise(() => {});
    if (m === 403) return { data: undefined, error: {}, response: { ok: false, status: 403 } };
    return ok(m);
  });
  render(
    <ConfirmProvider>
      <QueryClientProvider client={makeClient()}>
        <FormatModal reportKey="emp" query="?add=x" onClose={onClose} />
      </QueryClientProvider>
    </ConfirmProvider>,
  );
  return { onClose };
}

function applyButton(): HTMLButtonElement {
  return within(screen.getByRole("dialog")).getByRole("button", { name: FORMAT_TEXT.apply }) as HTMLButtonElement;
}

function addMarkButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: FORMAT_TEXT.addMark }) as HTMLButtonElement;
}

function removeButtons(): HTMLElement[] {
  return screen.queryAllByRole("button", { name: FORMAT_TEXT.removeMark });
}

function selectOf(label: string): HTMLSelectElement {
  const el = screen.getByLabelText(label);
  if (!(el instanceof HTMLSelectElement)) throw new Error(`no select for ${label}`);
  return el;
}

beforeEach(() => {
  h.get.mockReset();
  h.navigate.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("FormatModal", () => {
  it("totals_rows_only_for_shown_columns", async () => {
    renderPop(model({ shown: ["name", "salary"] }));
    await screen.findByLabelText("Цалин");
    expect(screen.queryByLabelText("Нэр")).not.toBeNull();
    expect(screen.queryByLabelText("Элссэн")).toBeNull();
  });

  it("aggregates_follow_column_kind", async () => {
    renderPop(model());
    await screen.findByLabelText("Цалин");
    const numberOptions = Array.from(selectOf("Цалин").options).map((o) => o.textContent);
    expect(numberOptions).toEqual([FORMAT_TEXT.noAggregate, "Нийлбэр", "Дундаж"]);
    const textOptions = Array.from(selectOf("Нэр").options).map((o) => o.textContent);
    expect(textOptions).toEqual([FORMAT_TEXT.noAggregate, "Тоо"]);
  });

  it("current_totals_marks_pin_are_prefilled", async () => {
    renderPop(
      model({
        // «sum» is not offered for a text column: it shows «—».
        totals: [
          ["salary", "avg"],
          ["name", "sum"],
        ],
        marks: [{ c: "salary", o: "gt", v: "5", k: "green" }],
        pin: 2,
      }),
    );
    await screen.findByLabelText("Цалин");
    expect(selectOf("Цалин").value).toBe("avg");
    expect(selectOf("Нэр").value).toBe("");
    expect(selectOf(FORMAT_TEXT.pin).value).toBe("2");
    expect(selectOf(FORMAT_TEXT.colour).value).toBe("green");
    expect((screen.getByLabelText("Утга") as HTMLInputElement).value).toBe("5");
    expect(selectOf("Багана").value).toBe("salary");
  });

  it("add_mark_disabled_at_five", async () => {
    const marks = Array.from({ length: 5 }, (_, i) => ({ c: "name", o: "eq", v: `v${i}`, k: "red" }));
    renderPop(model({ marks }));
    await screen.findByLabelText("Цалин");
    expect(addMarkButton().disabled).toBe(true);
    expect(addMarkButton().className).toContain("opacity-50");
    expect(removeButtons()).toHaveLength(5);
  });

  it("mark_swatch_uses_colour_classes_from_api", async () => {
    renderPop(model({ marks: [{ c: "name", o: "eq", v: "a", k: "red" }] }));
    await screen.findByLabelText("Цалин");
    const swatch = screen.getByText("Улаан", { selector: "span" });
    expect(swatch.className).toContain("bg-red-100");
    expect(swatch.className).toContain("text-red-800");
  });

  it("apply_omits_empty_totals_marks_and_zero_pin", async () => {
    renderPop(model());
    await screen.findByLabelText("Цалин");
    fireEvent.click(applyButton());
    expect(h.navigate).toHaveBeenCalledWith("/reports/emp/?add=x");
  });

  it("apply_sends_all_three", async () => {
    const { onClose } = renderPop(model());
    await screen.findByLabelText("Цалин");
    fireEvent.change(selectOf("Цалин"), { target: { value: "sum" } });
    fireEvent.change(selectOf(FORMAT_TEXT.pin), { target: { value: "2" } });
    fireEvent.click(addMarkButton());
    fireEvent.change(screen.getByLabelText("Утга"), { target: { value: "x" } });
    fireEvent.click(applyButton());

    const sent = h.navigate.mock.calls[0]?.[0] as string;
    expect(sent.startsWith("/reports/emp/?add=x&")).toBe(true);
    const params = new URLSearchParams(sent.split("?")[1]);
    expect(params.get("totals")).toBe("salary:sum");
    expect(params.get("pin")).toBe("2");
    expect(JSON.parse(params.get("marks") ?? "")).toEqual([{ c: "name", o: "eq", v: "x", k: "red" }]);
    expect(onClose).toHaveBeenCalled();
  });

  it("too_long_mark_shows_error", async () => {
    renderPop(model({ marks: [{ c: "name", o: "contains", v: "a".repeat(101), k: "red" }] }));
    await screen.findByLabelText("Цалин");
    fireEvent.click(applyButton());
    expect(screen.getByRole("alert").textContent).toBe(FORMAT_TEXT.tooLong);
    expect(h.navigate).not.toHaveBeenCalled();
  });

  it("marks_text_over_2000_shows_error", async () => {
    // Five ready rules whose column key alone is long: the text passes 2000 characters while each value stays short.
    const longKey = "k".repeat(420);
    const columns = [...COLUMNS, { key: longKey, kind: "text", label: "Урт" }];
    const marks = Array.from({ length: 5 }, () => ({ c: longKey, o: "eq", v: "a", k: "red" }));
    renderPop(model({ columns, shown: ["name"], marks }));
    await waitFor(() => expect(removeButtons()).toHaveLength(5));
    fireEvent.click(applyButton());
    expect(screen.getByRole("alert").textContent).toBe(FORMAT_TEXT.marksTooLong);
    expect(h.navigate).not.toHaveBeenCalled();
  });

  it("remove_mark_moves_focus_to_row_above", async () => {
    renderPop(
      model({
        marks: [
          { c: "name", o: "eq", v: "a", k: "red" },
          { c: "name", o: "eq", v: "b", k: "green" },
        ],
      }),
    );
    await screen.findByLabelText("Цалин");
    const [firstRemove, secondRemove] = removeButtons();
    expect(firstRemove).toBeDefined();
    expect(secondRemove).toBeDefined();
    fireEvent.click(secondRemove as HTMLElement);
    await waitFor(() => expect(removeButtons()).toHaveLength(1));
    expect(document.activeElement).toBe(firstRemove);
    // The first row's removal goes to the add button.
    fireEvent.click(firstRemove as HTMLElement);
    await waitFor(() => expect(removeButtons()).toHaveLength(0));
    expect(document.activeElement).toBe(addMarkButton());
  });
});
