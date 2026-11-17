import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MoneyInput } from "./MoneyInput";

afterEach(cleanup);

// Keeps the value in state, as a form would.
function Field({ initial = "", onValue }: { initial?: string; onValue?: (v: string) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <label htmlFor="salary">Цалин</label>
      <MoneyInput
        id="salary"
        name="salary"
        value={value}
        onChange={(v) => {
          setValue(v);
          onValue?.(v);
        }}
      />
    </>
  );
}

const box = () => screen.getByLabelText("Цалин") as HTMLInputElement;

// Sets the box text the way a keystroke does: through the native setter, so React's value tracker sees a change.
function typeText(el: HTMLInputElement, text: string) {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(el, text);
}

describe("MoneyInput", () => {
  it("groups digits with commas as the user types", () => {
    render(<Field />);
    fireEvent.change(box(), { target: { value: "2500000" } });
    expect(box().value).toBe("2,500,000");
  });

  it("renders as a text box with the decimal keypad and the data-money marker", () => {
    render(<Field />);
    expect(box().type).toBe("text");
    expect(box().inputMode).toBe("decimal");
    expect(box().hasAttribute("data-money")).toBe(true);
    expect(box().name).toBe("salary");
  });

  it("reports the formatted value to onChange", () => {
    const onValue = vi.fn();
    render(<Field onValue={onValue} />);
    fireEvent.change(box(), { target: { value: "0012.345" } });
    expect(onValue).toHaveBeenLastCalledWith("12.34");
    expect(box().value).toBe("12.34");
  });

  it("shows an initial value grouped", () => {
    render(<Field initial="1500000" />);
    expect(box().value).toBe("1,500,000");
  });

  it("keeps the caret after the same digit when typing in the middle", () => {
    render(<Field initial="2500000" />);
    const el = box();
    el.focus();
    // A keystroke: the typed "1" makes "2,5100,000" with the caret after it (index 4), then the browser fires input.
    typeText(el, "2,5100,000");
    el.setSelectionRange(4, 4);
    fireEvent.input(el);
    expect(el.value).toBe("25,100,000");
    expect(el.selectionStart).toBe(4);
    expect(el.selectionEnd).toBe(4);
  });

  it("leaves the caret alone when the formatted value equals the current value (money.js line 20)", () => {
    render(<Field />);
    const el = box();
    el.focus();
    // The text "2,500" is already formatted, and the caret sits right after the comma (index 2).
    // A caret rule run anyway would move it to index 1; the early return keeps it at 2.
    typeText(el, "2,500");
    el.setSelectionRange(2, 2);
    fireEvent.input(el);
    expect(el.value).toBe("2,500");
    expect(el.selectionStart).toBe(2);
    expect(el.selectionEnd).toBe(2);
  });

  it("fires a native input event that a parent listener sees", () => {
    const seen = vi.fn();
    document.addEventListener("input", seen);
    try {
      render(<Field />);
      fireEvent.input(box(), { target: { value: "1000" } });
      expect(seen).toHaveBeenCalled();
      expect(box().value).toBe("1,000");
    } finally {
      document.removeEventListener("input", seen);
    }
  });

  it("removes the digit beyond a comma on Backspace", () => {
    render(<Field initial="2500000" />);
    const el = box();
    el.focus();
    // "2,500,000" with the caret right after the comma at index 5 ("2,500,|000").
    el.setSelectionRange(6, 6);
    fireEvent.keyDown(el, { key: "Backspace" });
    // The handler moves the caret before the comma. The browser's own Backspace then removes the char before it.
    expect(el.selectionStart).toBe(5);
    const at = el.selectionStart ?? 0;
    const v = el.value;
    typeText(el, v.slice(0, at - 1) + v.slice(at)); // "2,50,000": the "0" beyond the comma is gone
    el.setSelectionRange(at - 1, at - 1);
    fireEvent.input(el);
    expect(el.value).toBe("250,000");
  });

  it("removes the digit beyond a comma on Delete", () => {
    render(<Field initial="2500000" />);
    const el = box();
    el.focus();
    // "2,500,000" with the caret right before the comma at index 1 ("2|,500,000").
    el.setSelectionRange(1, 1);
    fireEvent.keyDown(el, { key: "Delete" });
    // The handler moves the caret past the comma. The browser's own Delete then removes the char after it.
    expect(el.selectionStart).toBe(2);
    const at = el.selectionStart ?? 0;
    const v = el.value;
    typeText(el, v.slice(0, at) + v.slice(at + 1)); // "2,00,000": the "5" beyond the comma is gone
    el.setSelectionRange(at, at);
    fireEvent.input(el);
    expect(el.value).toBe("200,000");
  });
});
