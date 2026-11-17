import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "../api/client";
import { ConfirmProvider } from "./confirm";
import { DIRTY_CONFIRM_MESSAGE } from "./modalLogic";
import { Modal } from "./Modal";
import { Select, type SelectOption } from "./Select";

// Seven options: the click list (task 15).
const SEVEN: SelectOption[] = [
  "Хүний нөөц",
  "Санхүү",
  "Худалдаа",
  "Үйлдвэрлэл",
  "Маркетинг",
  "Инноваци",
  "Бусад",
].map((label, i) => ({ value: String(i + 1), label }));

// Eight options: the typing box (task 16).
const EIGHT: SelectOption[] = [
  "Багш",
  "Баатар",
  "Анги",
  "Администратор",
  "Бараа",
  "Гүйцэтгэх",
  "Дизайн",
  "Ерөнхий",
].map((label, i) => ({ value: String(i + 1), label }));

const DUP_NOTE = "Ийм бичлэг аль хэдийн бүртгэлтэй байсан тул түүнийг сонголоо.";

function stubMatchMedia(coarse: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: coarse && query === "(pointer: coarse)",
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

// Keeps the value in state, so a pick shows in the box as it would in a real form.
function Host(props: {
  options: SelectOption[];
  initial?: string;
  onChange?: (v: string) => void;
  addUrl?: string;
  canAdd?: boolean;
  search?: boolean;
  required?: boolean;
}) {
  const [value, setValue] = useState(props.initial ?? "");
  return (
    <>
      <label htmlFor="dept">Хэлтэс</label>
      <Select
        id="dept"
        name="dept"
        value={value}
        options={props.options}
        addUrl={props.addUrl}
        canAdd={props.canAdd}
        search={props.search}
        required={props.required}
        onChange={(v) => {
          setValue(v);
          props.onChange?.(v);
        }}
      />
    </>
  );
}

function trigger(): HTMLElement {
  const el = document.getElementById("dept");
  if (!el) throw new Error("no #dept");
  return el;
}

describe("Select: a pick counts as typed input for Modal", () => {
  beforeEach(() => stubMatchMedia(false));
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    delete (window as { matchMedia?: unknown }).matchMedia;
  });

  it("picking an option inside a Modal makes it dirty: Escape then asks first", async () => {
    const onClose = vi.fn();
    render(
      <ConfirmProvider>
        <Modal open title="Форм" onClose={onClose}>
          <Host options={SEVEN} initial="1" />
        </Modal>
      </ConfirmProvider>,
    );
    fireEvent.mouseDown(trigger());
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "Санхүү" }));
    expect((trigger() as HTMLSelectElement).value).toBe("2");
    fireEvent.keyDown(trigger(), { key: "Escape" });
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain(DIRTY_CONFIRM_MESSAGE);
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("Select: click-list mode (task 15)", () => {
  beforeEach(() => stubMatchMedia(false));
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    delete (window as { matchMedia?: unknown }).matchMedia;
  });

  it("7 options give the click list: a real select with the options, no typing box", () => {
    render(<Host options={SEVEN} initial="1" />);
    const select = screen.getByLabelText("Хэлтэс") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    expect(select.getAttribute("name")).toBe("dept");
    expect(select.value).toBe("1");
    expect(select.options).toHaveLength(7);
    expect(document.querySelector("input[role=combobox]")).toBeNull();
    expect(document.querySelectorAll("input[type=hidden][name=dept]")).toHaveLength(0);
  });

  it("the click-list select carries native required when required", () => {
    render(<Host options={SEVEN} required />);
    expect((screen.getByLabelText("Хэлтэс") as HTMLSelectElement).required).toBe(true);
  });

  it("mousedown on the select opens the list and cancels the native menu", () => {
    render(<Host options={SEVEN} initial="1" />);
    const notCancelled = fireEvent.mouseDown(trigger());
    expect(notCancelled).toBe(false);
    expect(screen.getByRole("listbox")).toBeTruthy();
  });

  it("picking an option sets select.value and fires change", async () => {
    const onChange = vi.fn();
    render(<Host options={SEVEN} initial="1" onChange={onChange} />);
    fireEvent.mouseDown(trigger());
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "Санхүү" }));
    expect(onChange).toHaveBeenCalledWith("2");
    expect((trigger() as HTMLSelectElement).value).toBe("2");
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
  });

  it("ArrowDown then Enter picks the second option", () => {
    const onChange = vi.fn();
    render(<Host options={SEVEN} initial="1" onChange={onChange} />);
    fireEvent.mouseDown(trigger());
    const list = screen.getByRole("listbox");
    fireEvent.keyDown(list, { key: "ArrowDown" });
    fireEvent.keyDown(list, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("2");
  });

  it("ArrowDown on the closed select opens the list", () => {
    render(<Host options={SEVEN} initial="1" />);
    fireEvent.keyDown(trigger(), { key: "ArrowDown" });
    expect(screen.getByRole("listbox")).toBeTruthy();
  });

  it("Escape closes the list and focuses the select", async () => {
    const onChange = vi.fn();
    render(<Host options={SEVEN} initial="1" onChange={onChange} />);
    fireEvent.mouseDown(trigger());
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "Escape" });
    expect(document.activeElement).toBe(trigger());
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
    expect(onChange).not.toHaveBeenCalled();
  });

  it("addModal alone does not give the typing box", () => {
    function ModalOnly() {
      const [v, setV] = useState("");
      return <Select id="dept" name="dept" value={v} onChange={setV} options={SEVEN} addModal onAddModal={() => {}} />;
    }
    render(<ModalOnly />);
    expect(document.querySelector("select#dept")).not.toBeNull();
    expect(document.querySelector("input[role=combobox]")).toBeNull();
  });

  it("search off never gives the typing box, even with 8 options", () => {
    render(<Host options={EIGHT} search={false} />);
    expect(document.querySelector("select#dept")).not.toBeNull();
    expect(document.querySelector("input[role=combobox]")).toBeNull();
  });

  it("a coarse pointer gives a native select", () => {
    stubMatchMedia(true);
    render(<Host options={SEVEN} initial="1" />);
    expect(document.querySelector("select#dept")).not.toBeNull();
    expect(document.querySelector("button#dept")).toBeNull();
  });

  it("Escape with the list open inside a Modal closes only the list", async () => {
    const onModalClose = vi.fn();
    render(
      <Modal open title="T" onClose={onModalClose}>
        <Host options={SEVEN} initial="1" />
      </Modal>,
    );
    fireEvent.mouseDown(trigger());
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "Escape" });
    expect(onModalClose).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onModalClose).toHaveBeenCalledTimes(1);
  });
});

describe("Select: combo-box mode (task 16)", () => {
  beforeEach(() => stubMatchMedia(false));
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    delete (window as { matchMedia?: unknown }).matchMedia;
  });

  it("8 options give the typing box, and the hint shows only on focus", () => {
    render(<Host options={EIGHT} />);
    const box = screen.getByRole("combobox");
    expect(box.tagName).toBe("INPUT");
    expect(box.getAttribute("placeholder")).toBeNull();
    act(() => box.focus());
    expect(box.getAttribute("placeholder")).toBe("Хайх…");
    act(() => box.blur());
    expect(box.getAttribute("placeholder")).toBeNull();
  });

  it("typing filters, case-insensitively and for Cyrillic capitals", () => {
    render(<Host options={EIGHT} />);
    const box = screen.getByRole("combobox");
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "ба" } });
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Багш", "Баатар", "Бараа"]);
    fireEvent.change(box, { target: { value: "БА" } });
    expect(screen.getAllByRole("option")).toHaveLength(3);
  });

  it("the add row appears for new text and not for an exact match", () => {
    render(<Host options={EIGHT} addUrl="/api/test/add" canAdd />);
    const box = screen.getByRole("combobox");
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "Шинэ" } });
    expect(screen.getByText('+ "Шинэ" нэмэх')).toBeTruthy();
    fireEvent.change(box, { target: { value: "багш" } });
    expect(screen.queryByText(/нэмэх/)).toBeNull();
  });

  it("with addUrl but no canAdd there is no add row", () => {
    render(<Host options={EIGHT} addUrl="/api/test/add" />);
    const box = screen.getByRole("combobox");
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "Шинэ" } });
    expect(screen.queryByText(/нэмэх/)).toBeNull();
  });

  it("typing resets the active row, so Enter picks the only match", () => {
    const onChange = vi.fn();
    render(<Host options={EIGHT} initial="8" onChange={onChange} />);
    const box = screen.getByRole("combobox");
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "Гүй" } });
    expect(screen.getAllByRole("option")).toHaveLength(1);
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("6");
  });

  it("typing an exact match shows no duplicate note", () => {
    render(<Host options={EIGHT} addUrl="/api/test/add" />);
    const box = screen.getByRole("combobox");
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "Багш" } });
    expect(screen.queryByText(DUP_NOTE)).toBeNull();
  });

  it("an add reply with existed: true shows the note and picks the existing option", async () => {
    setCsrf("tok-2");
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ value: "3", label: "Анги", existed: true }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );
    const onChange = vi.fn();
    render(<Host options={EIGHT} addUrl="/api/test/add" canAdd onChange={onChange} />);
    const box = screen.getByRole("combobox") as HTMLInputElement;
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "Шинэ" } });
    fireEvent.click(screen.getByText('+ "Шинэ" нэмэх'));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("3"));
    expect(screen.getByText(DUP_NOTE)).toBeTruthy();
    expect(box.value).toBe("Анги");
    expect(document.querySelector<HTMLInputElement>("input[name=dept]")?.value).toBe("3");
    setCsrf("");
  });

  it("the combo box carries native required when required", () => {
    render(<Host options={EIGHT} required />);
    expect((screen.getByRole("combobox") as HTMLInputElement).required).toBe(true);
  });

  it("the add POSTs the name through fetch and picks the returned entry", async () => {
    setCsrf("tok-1");
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ value: "99", label: "Шинэ" }), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const onChange = vi.fn();
    render(<Host options={EIGHT} addUrl="/api/test/add" canAdd onChange={onChange} />);
    const box = screen.getByRole("combobox") as HTMLInputElement;
    act(() => box.focus());
    fireEvent.change(box, { target: { value: "Шинэ" } });
    fireEvent.click(screen.getByText('+ "Шинэ" нэмэх'));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("99"));
    expect(fetchMock).toHaveBeenCalledWith("/api/test/add", {
      method: "POST",
      headers: { "X-CSRFToken": "tok-1", "Content-Type": "application/json" },
      body: JSON.stringify({ name: "Шинэ" }),
    });
    expect(box.value).toBe("Шинэ");
    expect(document.querySelector<HTMLInputElement>("input[name=dept]")?.value).toBe("99");
    setCsrf("");
  });

  it("a coarse pointer keeps the typing box when addUrl is set", () => {
    stubMatchMedia(true);
    render(<Host options={EIGHT} addUrl="/api/test/add" />);
    expect(screen.getByRole("combobox").tagName).toBe("INPUT");
  });
});
