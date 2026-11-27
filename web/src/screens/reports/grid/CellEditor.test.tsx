import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  EditFailed,
  saveEdit,
  SessionLost,
  SESSION_LOST_TEXT,
  type ReportEditor,
  type ReportEditTarget,
} from "../../../api/reportsEdit";
import { CellEditor, isPanelEditor } from "./CellEditor";

vi.mock("../../../api/reportsEdit", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/reportsEdit")>();
  return { ...actual, saveEdit: vi.fn() };
});

const mockSave = vi.mocked(saveEdit);

const TARGET: ReportEditTarget = { route: "cell", person: 7, field: "job_title", kind: "", key: 0, record: 0, salary: false };

function editor(over: Partial<ReportEditor> = {}): ReportEditor {
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

function renderEditor(ed: ReportEditor) {
  const onSaved = vi.fn();
  const onCancel = vi.fn();
  const onMove = vi.fn();
  const view = render(
    <CellEditor target={TARGET} editor={ed} onSaved={onSaved} onCancel={onCancel} onMove={onMove} />,
  );
  return { ...view, onSaved, onCancel, onMove, input: () => view.container.querySelector("input") as HTMLInputElement };
}

beforeEach(() => {
  mockSave.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("CellEditor", () => {
  it("choice_saves_the_picked_value", async () => {
    mockSave.mockResolvedValue({ ok: true, text: "Бусад", editor: null, error: "" });
    const ed = editor({
      kind: "choice",
      name: "dept",
      label: "Хэлтэс",
      value: "a",
      choices: [
        { value: "a", label: "Алба" },
        { value: "b", label: "Бусад" },
      ],
    });
    const { onSaved, onMove, container } = renderEditor(ed);

    const select = screen.getByLabelText("Хэлтэс") as HTMLSelectElement;
    fireEvent.mouseDown(select, { button: 0 });
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "Бусад" }));
    fireEvent.keyDown(select, { key: "Enter" });

    await waitFor(() => expect(onMove).toHaveBeenCalledWith("down"));
    expect(mockSave).toHaveBeenCalledTimes(1);
    expect(mockSave.mock.calls[0][1]).toMatchObject({ value: "b", loaded: "tok1" });
    expect(onSaved).toHaveBeenCalledWith("Бусад");
    expect(container.querySelector("[data-cell-error]")).toBeNull();
  });

  it("enter_twice_sends_one_save", async () => {
    mockSave.mockReturnValue(new Promise(() => {}));
    const { input } = renderEditor(editor());

    fireEvent.keyDown(input(), { key: "Enter" });
    fireEvent.keyDown(input(), { key: "Enter" });

    expect(mockSave).toHaveBeenCalledTimes(1);
  });

  it("tab_saves_and_reports_right", async () => {
    mockSave.mockResolvedValue({ ok: true, text: "Шинэ", editor: null, error: "" });
    const { input, onSaved, onMove } = renderEditor(editor());

    fireEvent.change(input(), { target: { value: "Шинэ" } });
    fireEvent.keyDown(input(), { key: "Tab" });

    await waitFor(() => expect(onMove).toHaveBeenCalledWith("right"));
    expect(mockSave.mock.calls[0][1]).toMatchObject({ value: "Шинэ" });
    expect(onSaved).toHaveBeenCalledWith("Шинэ");
  });

  it("failed_save_keeps_the_typed_text_and_shows_the_message", async () => {
    const failure = new EditFailed();
    mockSave.mockRejectedValue(failure);
    const { input, onSaved, onMove, container } = renderEditor(editor());

    fireEvent.change(input(), { target: { value: "Шинэ" } });
    fireEvent.keyDown(input(), { key: "Enter" });

    await waitFor(() => expect(container.querySelector("[data-cell-error]")?.textContent).toBe(failure.message));
    expect(input().value).toBe("Шинэ");
    expect(onSaved).not.toHaveBeenCalled();
    expect(onMove).not.toHaveBeenCalled();
  });

  it("clash_replaces_the_value_and_keeps_the_editor_open", async () => {
    mockSave.mockResolvedValueOnce({
      ok: false,
      text: "",
      error: "Өөрчлөгдсөн байна",
      editor: editor({ value: "Фреш", loaded: "tok2", old: "Фреш" }),
    });
    mockSave.mockResolvedValueOnce({ ok: true, text: "Фреш2", editor: null, error: "" });
    const { input, onSaved, onMove, container } = renderEditor(editor());

    fireEvent.change(input(), { target: { value: "Шинэ" } });
    fireEvent.keyDown(input(), { key: "Enter" });

    await waitFor(() => expect(container.querySelector("[data-cell-error]")?.textContent).toBe("Өөрчлөгдсөн байна"));
    expect(input().value).toBe("Фреш");
    expect(onSaved).not.toHaveBeenCalled();
    expect(onMove).not.toHaveBeenCalled();

    // The retry sends the fresh loaded token, and a second save succeeds.
    fireEvent.keyDown(input(), { key: "Enter" });
    await waitFor(() => expect(onMove).toHaveBeenCalledWith("down"));
    expect(mockSave.mock.calls[1][1]).toMatchObject({ value: "Фреш", loaded: "tok2" });
  });

  it("choice_value_missing_from_choices_renders_without_crashing", () => {
    const ed = editor({
      kind: "choice",
      name: "dept",
      label: "Хэлтэс",
      value: "zz",
      choices: [{ value: "a", label: "Алба" }],
    });
    renderEditor(ed);

    const select = screen.getByLabelText("Хэлтэс") as HTMLSelectElement;
    expect(select.value).toBe("zz");
  });

  it("escape_cancels_with_no_request", () => {
    const { input, onCancel } = renderEditor(editor());

    fireEvent.keyDown(input(), { key: "Escape" });

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(mockSave).not.toHaveBeenCalled();
  });

  it("session_lost_text_stays_in_the_editor", async () => {
    mockSave.mockRejectedValue(new SessionLost());
    const { input, onSaved, container } = renderEditor(editor());

    fireEvent.change(input(), { target: { value: "Шинэ" } });
    fireEvent.keyDown(input(), { key: "Enter" });

    await waitFor(() => expect(container.querySelector("[data-cell-error]")?.textContent).toBe(SESSION_LOST_TEXT));
    expect(input().value).toBe("Шинэ");
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("blocked_editor_has_no_input_and_no_save", () => {
    const { container } = renderEditor(editor({ blocked: "Энэ мөрийг одоо засах боломжгүй." }));

    expect(container.querySelector("input")).toBeNull();
    expect(container.querySelector("[data-cell-error]")?.textContent).toBe("Энэ мөрийг одоо засах боломжгүй.");
    expect(mockSave).not.toHaveBeenCalled();
  });
});

describe("CellEditor correction and buffered keys", () => {
  const CORRECT: ReportEditTarget = { route: "correct", person: 7, field: "dept", kind: "", key: 0, record: 3, salary: false };
  const correction = (over: Partial<ReportEditor> = {}) =>
    editor({ reason: true, reason_text: "", note: "Анхны утгыг засна.", old: "Хуучин", value: "Хуучин", ...over });

  function renderWith(ed: ReportEditor, extra: Partial<Parameters<typeof CellEditor>[0]> = {}) {
    const onSaved = vi.fn();
    const onCancel = vi.fn();
    const onMove = vi.fn();
    const view = render(
      <CellEditor target={TARGET} editor={ed} onSaved={onSaved} onCancel={onCancel} onMove={onMove} {...extra} />,
    );
    return { ...view, onSaved, onCancel, onMove };
  }

  it("empty_reason_sends_nothing", async () => {
    const { container, onMove } = renderWith(correction());
    fireEvent.keyDown(container.querySelector("input")!, { key: "Enter" });
    expect(mockSave).not.toHaveBeenCalled();
    expect(container.querySelector("[data-cell-error]")?.textContent).toBe("Засварын шалтгааныг заавал бичнэ үү.");
    expect(onMove).not.toHaveBeenCalled();
  });

  it("correction_save_sends_reason_and_old", async () => {
    mockSave.mockResolvedValue({ ok: true, text: "Шинэ", editor: null, error: "" });
    const { container, onMove } = renderWith({ ...correction(), kind: "text" }, {
      target: CORRECT,
    });
    const reason = container.querySelector('input[name="reason"]') as HTMLInputElement;
    expect(reason.maxLength).toBe(200);
    fireEvent.change(container.querySelector("input:not([name=reason])")!, { target: { value: "Шинэ" } });
    fireEvent.change(reason, { target: { value: "Засвар" } });
    fireEvent.keyDown(reason, { key: "Enter" });

    await waitFor(() => expect(onMove).toHaveBeenCalledWith("down"));
    expect(mockSave.mock.calls[0][0]).toEqual(CORRECT);
    expect(mockSave.mock.calls[0][1]).toMatchObject({ value: "Шинэ", old: "Хуучин", reason: "Засвар" });
  });

  it("failed_save_keeps_the_reason", async () => {
    mockSave.mockRejectedValue(new EditFailed());
    const { container } = renderWith(correction({ reason_text: "" }));
    const reason = container.querySelector('input[name="reason"]') as HTMLInputElement;
    fireEvent.change(reason, { target: { value: "Засвар" } });
    fireEvent.keyDown(reason, { key: "Enter" });
    await waitFor(() => expect(container.querySelector("[data-cell-error]")).not.toBeNull());
    expect((container.querySelector('input[name="reason"]') as HTMLInputElement).value).toBe("Засвар");
  });

  it("blocked_enter_and_tab_only_cancel", () => {
    const { container, onCancel } = renderWith(editor({ blocked: "Засах боломжгүй." }));
    fireEvent.keyDown(container.querySelector("form")!, { key: "Enter" });
    fireEvent.keyDown(container.querySelector("form")!, { key: "Tab" });
    expect(onCancel).toHaveBeenCalledTimes(2);
    expect(mockSave).not.toHaveBeenCalled();
  });

  it("panel_opens_left_near_the_right_edge", () => {
    const table = document.createElement("table");
    table.className = "ptable";
    const td = document.createElement("td");
    table.appendChild(td);
    document.body.appendChild(table);
    const rect = (l: number, t: number, r: number, b: number) =>
      ({ left: l, top: t, right: r, bottom: b, width: r - l, height: b - t, x: l, y: t, toJSON() {} }) as DOMRect;
    const spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      if (this === table) return rect(0, 0, 620, 800);
      if (this === td) return rect(450, 100, 600, 130);
      if (this.tagName === "FORM") return rect(450, 130, 800, 170);
      return rect(0, 0, 0, 0);
    });
    try {
      const { container } = renderWith(correction(), { anchor: td });
      const form = container.querySelector("form")!;
      expect(form.classList.contains("cell-pop")).toBe(true);
      expect(form.classList.contains("pop-left")).toBe(true);
      expect(form.classList.contains("pop-up")).toBe(false);
    } finally {
      spy.mockRestore();
      table.remove();
    }
  });

  it("initial_text_is_applied", () => {
    const { container } = renderWith(editor({ value: "Бат" }), { initialText: "Б" });
    expect((container.querySelector("input") as HTMLInputElement).value).toBe("Б");
  });

  it("buffered_text_keys_are_applied_and_enter_saves_once", async () => {
    mockSave.mockResolvedValue({ ok: true, text: "Бат", editor: null, error: "" });
    const { container, onMove } = renderWith(editor({ value: "" }), { initialText: "Б", buffered: ["а", "т", "Enter"] });
    expect((container.querySelector("input") as HTMLInputElement).value).toBe("Бат");
    await waitFor(() => expect(onMove).toHaveBeenCalledWith("down"));
    expect(mockSave).toHaveBeenCalledTimes(1);
    expect(mockSave.mock.calls[0][1]).toMatchObject({ value: "Бат" });
  });
});

describe("CellEditor kinds, keys, panel and accessibility", () => {
  const correction = (over: Partial<ReportEditor> = {}) =>
    editor({ reason: true, reason_text: "", note: "Анхны утгыг засна.", old: "Хуучин", value: "Хуучин", ...over });

  function renderWith(ed: ReportEditor, extra: Partial<Parameters<typeof CellEditor>[0]> = {}) {
    const onSaved = vi.fn();
    const onCancel = vi.fn();
    const onMove = vi.fn();
    const view = render(
      <CellEditor target={TARGET} editor={ed} onSaved={onSaved} onCancel={onCancel} onMove={onMove} {...extra} />,
    );
    return { ...view, onSaved, onCancel, onMove, input: () => view.container.querySelector("input") as HTMLInputElement };
  }

  it("date_kind_renders_the_date_box_and_enter_saves_its_value", async () => {
    mockSave.mockResolvedValue({ ok: true, text: "2026-01-02", editor: null, error: "" });
    const { container, onMove } = renderWith(editor({ kind: "date", name: "hired", value: "2026-01-02", label: "Ажилд орсон" }));
    const box = container.querySelector('input[name="hired"]') as HTMLInputElement;
    expect(box.value).toBe("2026-01-02");
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(onMove).toHaveBeenCalledWith("down"));
    expect(mockSave.mock.calls[0][1]).toMatchObject({ value: "2026-01-02" });
  });

  it("number_kind_is_a_decimal_input_and_saves_the_typed_number", async () => {
    mockSave.mockResolvedValue({ ok: true, text: "1500.5", editor: null, error: "" });
    const { container, onMove } = renderWith(editor({ kind: "number", name: "amount", value: "1200", label: "Дүн" }));
    const box = container.querySelector('input[name="amount"]') as HTMLInputElement;
    expect(box.getAttribute("inputmode")).toBe("decimal");
    fireEvent.change(box, { target: { value: "1500.5" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(onMove).toHaveBeenCalledWith("down"));
    expect(mockSave.mock.calls[0][1]).toMatchObject({ value: "1500.5" });
  });

  it("shift_tab_saves_and_reports_left", async () => {
    mockSave.mockResolvedValue({ ok: true, text: "Бат", editor: null, error: "" });
    const { input, onMove } = renderWith(editor());
    fireEvent.keyDown(input(), { key: "Tab", shiftKey: true });
    await waitFor(() => expect(onMove).toHaveBeenCalledWith("left"));
    expect(mockSave).toHaveBeenCalledTimes(1);
  });

  it("tab_during_a_save_sends_nothing", () => {
    mockSave.mockReturnValue(new Promise(() => {}));
    const { input } = renderWith(editor());
    fireEvent.keyDown(input(), { key: "Enter" });
    fireEvent.keyDown(input(), { key: "Tab" });
    expect(mockSave).toHaveBeenCalledTimes(1);
  });

  it("panel_opens_up_near_the_bottom_edge", () => {
    const table = document.createElement("table");
    table.className = "ptable";
    const td = document.createElement("td");
    table.appendChild(td);
    document.body.appendChild(table);
    const rect = (l: number, t: number, r: number, b: number) =>
      ({ left: l, top: t, right: r, bottom: b, width: r - l, height: b - t, x: l, y: t, toJSON() {} }) as DOMRect;
    const spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      if (this === table) return rect(0, 0, 900, 800);
      if (this === td) return rect(450, 700, 600, 730);
      if (this.tagName === "FORM") return rect(450, 760, 800, 820);
      return rect(0, 0, 0, 0);
    });
    try {
      const { container } = renderWith(correction(), { anchor: td });
      const form = container.querySelector("form")!;
      expect(form.classList.contains("pop-up")).toBe(true);
      expect(form.classList.contains("pop-left")).toBe(false);
      expect(isPanelEditor(correction())).toBe(true);
    } finally {
      spy.mockRestore();
      table.remove();
    }
  });

  it("error_is_an_alert_tied_to_the_field", async () => {
    mockSave.mockRejectedValue(new EditFailed());
    const { input, container } = renderWith(editor());
    fireEvent.change(input(), { target: { value: "Шинэ" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    const alert = await screen.findByRole("alert");
    expect(alert.hasAttribute("data-cell-error")).toBe(true);
    expect(input().getAttribute("aria-invalid")).toBe("true");
    expect(input().getAttribute("aria-describedby")).toBe(alert.id);
    expect(container.querySelector("[data-cell-error]")).toBe(alert);
  });

  it("open_choice_list_picks_then_saves_once", async () => {
    mockSave.mockResolvedValue({ ok: true, text: "x", editor: null, error: "" });
    const choices = Array.from({ length: 9 }, (_, i) => ({ value: `v${i}`, label: `Сонголт ${i}` }));
    const { container, onMove } = renderWith(editor({ kind: "choice", name: "dept", label: "Хэлтэс", value: "v2", choices }));
    const combo = container.querySelector('input[role="combobox"]') as HTMLInputElement;
    // The box takes the focus on open, but its list stays closed until a key or a click opens it (Django's cell editor).
    expect(screen.queryByRole("listbox")).toBeNull();
    act(() => combo.focus());
    // The first ArrowDown opens the closed list; the second moves to the next choice; Enter picks it.
    fireEvent.keyDown(combo, { key: "ArrowDown" });
    expect(screen.getByRole("listbox")).toBeTruthy();
    fireEvent.keyDown(combo, { key: "ArrowDown" });
    fireEvent.keyDown(combo, { key: "Enter" });
    await waitFor(() => expect(onMove).toHaveBeenCalledWith("down"));
    expect(mockSave).toHaveBeenCalledTimes(1);
    expect(mockSave.mock.calls[0][1]).toMatchObject({ value: "v3" });
  });

  it("repeated_empty_reason_refocuses_the_reason_box", () => {
    const { container } = renderWith(correction());
    const main = container.querySelector("input:not([name=reason])") as HTMLInputElement;
    const reason = container.querySelector('input[name="reason"]') as HTMLInputElement;
    main.focus();
    fireEvent.keyDown(main, { key: "Enter" });
    expect(document.activeElement).toBe(reason);
    main.focus();
    fireEvent.keyDown(main, { key: "Enter" });
    expect(document.activeElement).toBe(reason);
    expect(mockSave).not.toHaveBeenCalled();
  });

  it("missing_choice_shows_its_label", () => {
    const { container } = renderWith(
      editor({ kind: "choice", name: "dept", label: "Хэлтэс", value: "zz", choices: [{ value: "a", label: "Алба" }] }),
    );
    const option = container.querySelector('option[value="zz"]');
    expect(option?.textContent).toBe("Хэлтэс");
  });
});

describe("CellEditor typed text a choice or date box cannot take", () => {
  it.each(["choice", "date"] as const)(
    "a typed key and Enter during the load on a %s box do not save the stored value",
    (kind) => {
      const ed =
        kind === "choice"
          ? editor({ kind, name: "dept", label: "Хэлтэс", value: "a", choices: [{ value: "a", label: "Алба" }] })
          : editor({ kind, name: "hire_date", label: "Огноо", value: "2026-11-01" });
      const onMove = vi.fn();
      render(
        <CellEditor
          target={TARGET}
          editor={ed}
          onSaved={vi.fn()}
          onCancel={vi.fn()}
          onMove={onMove}
          initialText="б"
          buffered={["Enter"]}
        />,
      );
      expect(mockSave).not.toHaveBeenCalled();
      expect(onMove).not.toHaveBeenCalled();
    },
  );
});
