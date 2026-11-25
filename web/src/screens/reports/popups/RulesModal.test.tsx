import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReportRulesModelOut } from "../../../api/reports";
import { ConfirmProvider } from "../../../widgets/confirm";
import { RulesModal } from "./RulesModal";
import { COLUMNS_TEXT, RULES_TEXT } from "./popupTexts";

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
    { code: "between", label: "Хооронд …" },
    { code: "next_days", label: "ирэх … хоногт" },
    { code: "empty", label: "Хоосон" },
    { code: "filled", label: "Хоосон биш" },
  ],
};

function model(rules: unknown, keep: string[][] = [["add", "x"]], columns = COLUMNS): ReportRulesModelOut {
  return {
    columns,
    keep,
    ops: OPS,
    rules: rules === "" ? "" : JSON.stringify(rules),
  };
}

const FLAT_ONE = { op: "and", items: [{ c: "name", o: "contains", v: "ab" }] };

const NESTED = {
  op: "and",
  items: [
    { c: "name", o: "contains", v: "ab" },
    {
      op: "or",
      items: [
        { c: "salary", o: "gt", v: "5" },
        { c: "joined", o: "empty", v: "" },
      ],
    },
  ],
};

// Eight columns: the typing box (combo mode) instead of the click list.
const EIGHT_COLUMNS = [
  ...COLUMNS,
  ...Array.from({ length: 5 }, (_, i) => ({ key: `extra${i}`, kind: "text", label: `Нэмэлт ${i + 1}` })),
];

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function makeClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function renderPop(m: ReportRulesModelOut | "pending" | 403, onClose = vi.fn()) {
  h.get.mockImplementation(async (path: string) => {
    if (path !== "/api/v1/reports/{key}/rules") return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    if (m === "pending") return new Promise(() => {});
    if (m === 403) return { data: undefined, error: {}, response: { ok: false, status: 403 } };
    return ok(m);
  });
  render(
    <ConfirmProvider>
      <QueryClientProvider client={makeClient()}>
        <RulesModal reportKey="emp" query="?add=x" onClose={onClose} />
      </QueryClientProvider>
    </ConfirmProvider>,
  );
  return { onClose };
}

function applyButton(): HTMLButtonElement {
  return within(screen.getByRole("dialog")).getByRole("button", { name: RULES_TEXT.apply }) as HTMLButtonElement;
}

function addRuleButton(): HTMLButtonElement {
  return screen.getAllByRole("button", { name: RULES_TEXT.addRule })[0] as HTMLButtonElement;
}

function removeButtons(): HTMLElement[] {
  return screen.queryAllByRole("button", { name: RULES_TEXT.removeRule });
}

beforeEach(() => {
  h.get.mockReset();
  h.navigate.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("RulesModal", () => {
  it("opens_with_one_blank_rule_when_no_rules", async () => {
    renderPop(model(""));
    expect(screen.getByRole("heading", { name: RULES_TEXT.title })).toBeTruthy();
    await screen.findByLabelText(RULES_TEXT.column);
    expect(removeButtons()).toHaveLength(1);
    expect((screen.getByLabelText(RULES_TEXT.column) as HTMLSelectElement).value).toBe("name");
    expect((screen.getByLabelText(RULES_TEXT.operator) as HTMLSelectElement).value).toBe("eq");
    expect((screen.getByLabelText("Нарийвчилсан") as HTMLInputElement).checked).toBe(false);
  });

  it("current_rules_are_drawn_and_nested_opens_advanced", async () => {
    renderPop(model(NESTED));
    await screen.findAllByLabelText(RULES_TEXT.column);
    expect((screen.getByLabelText(RULES_TEXT.advanced) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(RULES_TEXT.rootLabel)).toBeTruthy();
    expect(screen.getByText(RULES_TEXT.groupLabel)).toBeTruthy();
    expect(document.querySelectorAll('select[aria-label="Бүлгийн нөхцөл"]')).toHaveLength(2);
    expect(removeButtons()).toHaveLength(3);
    const values = screen.getAllByLabelText(RULES_TEXT.value).map((el) => (el as HTMLInputElement).value);
    expect(values).toEqual(["ab", "5"]);
  });

  it("column_change_resets_operator_and_value_and_keeps_focus", async () => {
    renderPop(model(FLAT_ONE));
    await screen.findByLabelText(RULES_TEXT.column);
    expect((screen.getByLabelText(RULES_TEXT.value) as HTMLInputElement).value).toBe("ab");
    fireEvent.change(screen.getByLabelText(RULES_TEXT.column), { target: { value: "salary" } });
    await waitFor(() => expect((screen.getByLabelText(RULES_TEXT.operator) as HTMLSelectElement).value).toBe("gt"));
    expect((screen.getByLabelText(RULES_TEXT.value) as HTMLInputElement).value).toBe("");
    expect(document.activeElement).toBe(screen.getByLabelText(RULES_TEXT.column));
  });

  it("between_draws_two_boxes", async () => {
    renderPop(model({ op: "and", items: [{ c: "salary", o: "between", v: "1..5" }] }));
    await screen.findByLabelText(RULES_TEXT.from);
    expect((screen.getByLabelText(RULES_TEXT.from) as HTMLInputElement).value).toBe("1");
    expect((screen.getByLabelText(RULES_TEXT.to) as HTMLInputElement).value).toBe("5");
    expect(screen.queryByLabelText(RULES_TEXT.value)).toBeNull();
  });

  it("days_operator_shows_xonog", async () => {
    renderPop(model({ op: "and", items: [{ c: "joined", o: "next_days", v: "7" }] }));
    await screen.findByLabelText(RULES_TEXT.value);
    expect((screen.getByLabelText(RULES_TEXT.value) as HTMLInputElement).value).toBe("7");
    expect(screen.getByText(RULES_TEXT.days)).toBeTruthy();
  });

  it("empty_and_filled_have_no_value_box", async () => {
    renderPop(
      model({
        op: "and",
        items: [
          { c: "name", o: "empty", v: "" },
          { c: "name", o: "filled", v: "" },
        ],
      }),
    );
    await screen.findAllByLabelText(RULES_TEXT.column);
    expect(screen.queryByLabelText(RULES_TEXT.value)).toBeNull();
    expect(screen.queryByLabelText(RULES_TEXT.from)).toBeNull();
    expect(screen.queryByText(RULES_TEXT.days)).toBeNull();
  });

  it("add_limit_disables_button_at_20_rules", async () => {
    const twenty = { op: "and", items: Array.from({ length: 20 }, () => ({ c: "name", o: "contains", v: "a" })) };
    renderPop(model(twenty));
    await screen.findAllByLabelText(RULES_TEXT.column);
    expect(removeButtons()).toHaveLength(20);
    expect(addRuleButton().disabled).toBe(true);
  });

  it("group_depth_limit_hides_add_group", async () => {
    const deep = {
      op: "and",
      items: [
        { c: "name", o: "contains", v: "a" },
        {
          op: "and",
          items: [
            { c: "name", o: "contains", v: "b" },
            { op: "and", items: [{ c: "name", o: "contains", v: "c" }] },
          ],
        },
      ],
    };
    renderPop(model(deep));
    await screen.findAllByLabelText(RULES_TEXT.column);
    expect((screen.getByLabelText(RULES_TEXT.advanced) as HTMLInputElement).checked).toBe(true);
    expect(screen.getAllByRole("button", { name: RULES_TEXT.addGroup })).toHaveLength(2);
  });

  it("advanced_off_with_nested_asks_then_flattens", async () => {
    renderPop(model(NESTED));
    await screen.findAllByLabelText(RULES_TEXT.column);
    const box = screen.getByLabelText(RULES_TEXT.advanced) as HTMLInputElement;
    fireEvent.click(box);
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain(RULES_TEXT.advancedOffConfirm);
    fireEvent.click(within(dialog).getByRole("button", { name: RULES_TEXT.advancedOffOk }));
    await waitFor(() => expect(box.checked).toBe(false));
    expect(screen.queryByText(RULES_TEXT.groupLabel)).toBeNull();
    expect(removeButtons()).toHaveLength(3);
  });

  it("advanced_off_cancel_keeps_advanced", async () => {
    renderPop(model(NESTED));
    await screen.findAllByLabelText(RULES_TEXT.column);
    const box = screen.getByLabelText(RULES_TEXT.advanced) as HTMLInputElement;
    fireEvent.click(box);
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: COLUMNS_TEXT.cancel }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(box.checked).toBe(true);
    expect(screen.getByText(RULES_TEXT.groupLabel)).toBeTruthy();
  });

  it("group_drop_asks_when_two_or_more_rules", async () => {
    renderPop(model(NESTED));
    await screen.findAllByLabelText(RULES_TEXT.column);
    fireEvent.click(screen.getByLabelText(RULES_TEXT.advanced));
    fireEvent.click(screen.getByRole("button", { name: RULES_TEXT.dropGroup }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain(RULES_TEXT.dropGroupConfirm);
    fireEvent.click(within(dialog).getByRole("button", { name: RULES_TEXT.dropGroupOk }));
    await waitFor(() => expect(screen.queryByText(RULES_TEXT.groupLabel)).toBeNull());
    expect(removeButtons()).toHaveLength(1);
  });

  it("too_long_value_shows_error_and_does_not_navigate", async () => {
    const onClose = vi.fn();
    renderPop(model({ op: "and", items: [{ c: "name", o: "contains", v: "a".repeat(101) }] }), onClose);
    await screen.findByLabelText(RULES_TEXT.value);
    fireEvent.click(applyButton());
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(RULES_TEXT.tooLong);
    expect(h.navigate).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("rules_text_over_2000_characters_shows_error_and_does_not_navigate", async () => {
    const twenty = {
      op: "and",
      items: Array.from({ length: 20 }, () => ({ c: "name", o: "contains", v: "a".repeat(100) })),
    };
    renderPop(model(twenty));
    await screen.findAllByLabelText(RULES_TEXT.column);
    fireEvent.click(applyButton());
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(RULES_TEXT.ruleTooLong);
    expect(h.navigate).not.toHaveBeenCalled();
  });

  it("apply_navigates_with_rules_and_keep", async () => {
    const { onClose } = renderPop(model(FLAT_ONE));
    await screen.findByLabelText(RULES_TEXT.value);
    fireEvent.click(applyButton());
    const text = JSON.stringify({ op: "and", items: [{ c: "name", o: "contains", v: "ab" }] });
    expect(h.navigate).toHaveBeenCalledWith(`/reports/emp/?add=x&rules=${encodeURIComponent(text)}`);
    expect(onClose).toHaveBeenCalled();
  });

  it("apply_without_rules_omits_parameter", async () => {
    const { onClose } = renderPop(model(""));
    await screen.findByLabelText(RULES_TEXT.column);
    fireEvent.click(applyButton());
    expect(h.navigate).toHaveBeenCalledWith("/reports/emp/?add=x");
    expect(onClose).toHaveBeenCalled();
  });

  it("remove_moves_focus_to_row_above", async () => {
    renderPop(
      model({
        op: "and",
        items: [
          { c: "name", o: "contains", v: "a" },
          { c: "name", o: "contains", v: "b" },
        ],
      }),
    );
    await screen.findAllByLabelText(RULES_TEXT.column);
    fireEvent.click(removeButtons()[1] as HTMLElement);
    await waitFor(() => expect(removeButtons()).toHaveLength(1));
    expect(document.activeElement).toBe(removeButtons()[0]);
  });

  it("remove_first_row_moves_focus_to_add_button", async () => {
    renderPop(
      model({
        op: "and",
        items: [
          { c: "name", o: "contains", v: "a" },
          { c: "name", o: "contains", v: "b" },
        ],
      }),
    );
    await screen.findAllByLabelText(RULES_TEXT.column);
    fireEvent.click(removeButtons()[0] as HTMLElement);
    await waitFor(() => expect(removeButtons()).toHaveLength(1));
    expect(document.activeElement).toBe(addRuleButton());
  });

  it("add_rule_focuses_the_new_rule_column", async () => {
    renderPop(model(FLAT_ONE));
    await screen.findByLabelText(RULES_TEXT.value);
    fireEvent.click(addRuleButton());
    await waitFor(() => expect(removeButtons()).toHaveLength(2));
    const columns = screen.getAllByLabelText(RULES_TEXT.column);
    expect(document.activeElement).toBe(columns[1]);
  });

  it("edit_clears_the_error_line", async () => {
    renderPop(model({ op: "and", items: [{ c: "name", o: "contains", v: "a".repeat(101) }] }));
    await screen.findByLabelText(RULES_TEXT.value);
    fireEvent.click(applyButton());
    await screen.findByRole("alert");
    fireEvent.change(screen.getByLabelText(RULES_TEXT.value), { target: { value: "short" } });
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("combo_mode_column_box_is_named_by_aria_label", async () => {
    renderPop(model(FLAT_ONE, [["add", "x"]], EIGHT_COLUMNS));
    await screen.findByRole("combobox", { name: RULES_TEXT.column });
    const box = screen.getByRole("combobox", { name: RULES_TEXT.column });
    expect(box.tagName).toBe("INPUT");
    expect(screen.getByRole("combobox", { name: RULES_TEXT.operator })).toBeTruthy();
  });

  it("date_value_from_datepicker_is_sent_in_rules", async () => {
    renderPop(model({ op: "and", items: [{ c: "joined", o: "eq", v: "2026-01-02" }] }));
    const box = (await screen.findByLabelText(RULES_TEXT.value)) as HTMLInputElement;
    expect(box.value).toBe("2026-01-02");
    fireEvent.change(box, { target: { value: "2026-03-05" } });
    fireEvent.click(applyButton());
    const text = JSON.stringify({ op: "and", items: [{ c: "joined", o: "eq", v: "2026-03-05" }] });
    expect(h.navigate).toHaveBeenCalledWith(`/reports/emp/?add=x&rules=${encodeURIComponent(text)}`);
  });

  it("group_drop_cancel_keeps_the_group", async () => {
    const { onClose } = renderPop(model(NESTED));
    await screen.findAllByLabelText(RULES_TEXT.column);
    fireEvent.click(screen.getByLabelText(RULES_TEXT.advanced));
    fireEvent.click(screen.getByRole("button", { name: RULES_TEXT.dropGroup }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: COLUMNS_TEXT.cancel }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(screen.getByText(RULES_TEXT.groupLabel)).toBeTruthy();
    expect(removeButtons()).toHaveLength(3);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("group_with_one_subgroup_of_many_rules_asks_before_removal", async () => {
    const outer = {
      op: "and",
      items: [
        {
          op: "and",
          items: [{ op: "or", items: [{ c: "name", o: "contains", v: "a" }, { c: "name", o: "contains", v: "b" }] }],
        },
        { c: "salary", o: "gt", v: "1" },
      ],
    };
    renderPop(model(outer));
    await screen.findAllByLabelText(RULES_TEXT.column);
    fireEvent.click(screen.getByLabelText(RULES_TEXT.advanced));
    fireEvent.click(screen.getAllByRole("button", { name: RULES_TEXT.dropGroup })[0] as HTMLElement);
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain(RULES_TEXT.dropGroupConfirm);
    fireEvent.click(within(dialog).getByRole("button", { name: COLUMNS_TEXT.cancel }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(removeButtons()).toHaveLength(3);
  });

  it("loading_and_403_states", async () => {
    renderPop("pending");
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.queryByLabelText(RULES_TEXT.column)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();

    cleanup();
    renderPop(403);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe(COLUMNS_TEXT.loadFailed));
    expect(screen.queryByRole("button", { name: RULES_TEXT.apply })).toBeNull();
  });
});
