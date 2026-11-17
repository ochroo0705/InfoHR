import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConfirmProvider } from "./confirm";
import { DatePicker, type DatePickerProps } from "./DatePicker";
import { DIRTY_CONFIRM_MESSAGE } from "./modalLogic";
import { Modal } from "./Modal";

// Today is fixed for the whole file: 2026-11-17 (a Tuesday).
const LABEL = "Төрсөн өдөр";

type FieldProps = Omit<DatePickerProps, "value" | "onChange" | "name"> & {
  initial?: string;
  onValue?: (v: string) => void;
};

// A picker with its own state, as a form would hold it. onValue records every value it is given.
function Field({ initial = "", onValue, ...rest }: FieldProps) {
  const [value, setValue] = useState(initial);
  return (
    <div>
      <label htmlFor="dob">{LABEL}</label>
      <DatePicker
        id="dob"
        name="dob"
        {...rest}
        value={value}
        onChange={(v) => {
          setValue(v);
          onValue?.(v);
        }}
      />
    </div>
  );
}

const input = () => screen.getByLabelText(LABEL) as HTMLInputElement;
const popupOf = (name = "Огноо сонгох") => screen.queryByRole("dialog", { name });
const dayButton = (n: string) => screen.getByRole("button", { name: n }) as HTMLButtonElement;

describe("DatePicker", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 17, 12, 0, 0));
  });

  // Vitest here has no globals, so Testing Library does not clean up by itself.
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("ArrowDown opens the picker", () => {
    render(<Field />);
    expect(popupOf()).toBeNull();
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    expect(popupOf()).not.toBeNull();
  });

  it("clicking a day sets the value as YYYY-MM-DD", () => {
    const onValue = vi.fn();
    render(<Field onValue={onValue} />);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.click(dayButton("14"));
    expect(onValue).toHaveBeenLastCalledWith("2026-11-14");
    expect(input().value).toBe("2026-11-14");
  });

  it("Өнөөдөр sets today (fake date)", () => {
    const onValue = vi.fn();
    render(<Field onValue={onValue} />);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("button", { name: "Өнөөдөр" }));
    expect(onValue).toHaveBeenLastCalledWith("2026-11-17");
  });

  it("Цэвэрлэх clears the value", () => {
    const onValue = vi.fn();
    render(<Field initial="2026-11-14" onValue={onValue} />);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("button", { name: "Цэвэрлэх" }));
    expect(onValue).toHaveBeenLastCalledWith("");
  });

  it("month mode shows 12 month cells and «Энэ сар», and a pick gives YYYY-MM", () => {
    const onValue = vi.fn();
    render(<Field mode="month" onValue={onValue} />);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    expect(popupOf("Сар сонгох")).not.toBeNull();
    expect(document.querySelectorAll(".dp-month")).toHaveLength(12);
    expect(screen.getByRole("button", { name: "Энэ сар" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "3-р сар" }));
    expect(onValue).toHaveBeenLastCalledWith("2026-03");
  });

  it("«Энэ сар» in month mode sets the current month", () => {
    const onValue = vi.fn();
    render(<Field mode="month" onValue={onValue} />);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("button", { name: "Энэ сар" }));
    expect(onValue).toHaveBeenLastCalledWith("2026-11");
  });

  it("days before min and after max are disabled (struck through)", () => {
    render(<Field min="2026-11-10" max="2026-11-20" />);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    expect(dayButton("9").disabled).toBe(true);
    expect(dayButton("9").classList.contains("dp-day")).toBe(true);
    expect(dayButton("21").disabled).toBe(true);
    expect(dayButton("10").disabled).toBe(false);
    expect(dayButton("20").disabled).toBe(false);
  });

  it("a typed date is normalised on blur", () => {
    const onValue = vi.fn();
    render(<Field onValue={onValue} />);
    fireEvent.change(input(), { target: { value: "2026.11.14" } });
    fireEvent.blur(input());
    expect(input().value).toBe("2026-11-14");
    expect(onValue).toHaveBeenLastCalledWith("2026-11-14");
  });

  it("Tab closes the picker", async () => {
    render(<Field />);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.keyDown(input(), { key: "Tab" });
    await waitFor(() => expect(popupOf()).toBeNull());
  });

  it("Tab from inside the popup (after clicking an arrow) closes the picker", async () => {
    render(<Field />);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    const prev = screen.getByRole("button", { name: "Өмнөх сар" });
    fireEvent.click(prev);
    fireEvent.keyDown(prev, { key: "Tab" });
    await waitFor(() => expect(popupOf()).toBeNull());
  });

  it("Escape pressed inside the popup closes it and returns focus to the input", async () => {
    render(<Field />);
    input().focus();
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.keyDown(screen.getByRole("button", { name: "Өмнөх сар" }), { key: "Escape" });
    await waitFor(() => expect(popupOf()).toBeNull());
    expect(document.activeElement).toBe(input());
  });

  it("Escape closes the picker and returns focus to the input", async () => {
    render(<Field />);
    input().focus();
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.keyDown(input(), { key: "Escape" });
    await waitFor(() => expect(popupOf()).toBeNull());
    expect(document.activeElement).toBe(input());
  });

  it("Escape inside a Modal closes only the picker", async () => {
    const onClose = vi.fn();
    render(
      <ConfirmProvider>
        <Modal open title="Форм" onClose={onClose}>
          <Field />
        </Modal>
      </ConfirmProvider>,
    );
    input().focus();
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    expect(popupOf()).not.toBeNull();
    fireEvent.keyDown(input(), { key: "Escape" });
    await waitFor(() => expect(popupOf()).toBeNull());
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Форм" })).toBeTruthy();
  });

  it("Escape with the picker shut closes the Modal", () => {
    const onClose = vi.fn();
    render(
      <ConfirmProvider>
        <Modal open title="Форм" onClose={onClose}>
          <Field />
        </Modal>
      </ConfirmProvider>,
    );
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("picking a date inside a Modal makes it dirty: Escape then asks first", async () => {
    const onClose = vi.fn();
    render(
      <ConfirmProvider>
        <Modal open title="Форм" onClose={onClose}>
          <Field />
        </Modal>
      </ConfirmProvider>,
    );
    input().focus();
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.click(dayButton("14"));
    expect(input().value).toBe("2026-11-14");
    fireEvent.keyDown(input(), { key: "Escape" });
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain(DIRTY_CONFIRM_MESSAGE);
    expect(onClose).not.toHaveBeenCalled();
  });
});
