import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Soft, SOFT } from "./Soft";

afterEach(() => {
  cleanup();
});

describe("Soft", () => {
  it("a select draws its one current option, keeps the soft look, and does not open on mousedown or keydown", () => {
    render(<Soft label="Алба" kind="select" value="4" choice="Удирдлагын алба" />);
    const select = screen.getByLabelText("Алба") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    expect(select.options).toHaveLength(1);
    expect(select.options[0].textContent).toBe("Удирдлагын алба");
    expect(select.value).toBe("4");
    expect(select.className).toBe(`w-full ${SOFT}`);
    expect(select.disabled).toBe(false);
    expect(fireEvent.mouseDown(select)).toBe(false);
    expect(fireEvent.keyDown(select, { key: "ArrowDown" })).toBe(false);
  });

  it("a combo select is a read-only combo text box showing its current text, with the select's classes and sel-combo", () => {
    render(<Soft label="Салбар" kind="select" value="78" choice="Төв салбар" combo />);
    const box = screen.getByLabelText("Салбар") as HTMLInputElement;
    expect(box.tagName).toBe("INPUT");
    expect(box.type).toBe("text");
    expect(box.value).toBe("Төв салбар");
    expect(box.readOnly).toBe(true);
    expect(box.getAttribute("role")).toBe("combobox");
    expect(box.getAttribute("aria-autocomplete")).toBe("list");
    expect(box.className).toBe(`w-full ${SOFT} sel-combo`);
  });

  it("an empty combo select shows an empty text box", () => {
    render(<Soft label="Алба" kind="select" value="" choice="" combo />);
    expect((screen.getByLabelText("Алба") as HTMLInputElement).value).toBe("");
  });

  it("an empty select keeps Django's empty option", () => {
    render(<Soft label="Ажлын төрөл" kind="select" value="" choice="" />);
    const select = screen.getByLabelText("Ажлын төрөл") as HTMLSelectElement;
    expect(select.options[0].textContent).toBe("");
  });

  it("a text, date or number box is a read-only input of its type with the placeholder", () => {
    render(<Soft label="НДД-ийн дугаар" kind="text" value="" />);
    const input = screen.getByLabelText("НДД-ийн дугаар") as HTMLInputElement;
    expect(input.type).toBe("text");
    expect(input.readOnly).toBe(true);
    expect(input.placeholder).toBe("—");
    expect(input.autocomplete).toBe("off");
    expect(input.className).toBe(`w-full ${SOFT}`);
  });

  it("a textarea is a read-only one-line box that grows with its text, with the placeholder", () => {
    render(<Soft label="Дүгнэлт" kind="textarea" value="Сайн" placeholder="Тодруулга" />);
    const box = screen.getByLabelText("Дүгнэлт") as HTMLTextAreaElement;
    expect(box.tagName).toBe("TEXTAREA");
    expect(box.readOnly).toBe(true);
    expect(box.rows).toBe(1);
    expect(box.value).toBe("Сайн");
    expect(box.placeholder).toBe("Тодруулга");
    expect(box.className).toBe(`w-full ${SOFT} resize-none [field-sizing:content]`);
  });

  it("date and number boxes take their type and the width given", () => {
    render(<Soft label="Салбарт ажилласан жил" kind="number" value="3" width="w-20" />);
    const years = screen.getByLabelText("Салбарт ажилласан жил") as HTMLInputElement;
    expect(years.type).toBe("number");
    expect(years.value).toBe("3");
    expect(years.className).toBe(`w-20 ${SOFT}`);
    cleanup();
    cleanup();
    render(<Soft label="Анх ажилд орсон огноо" kind="date" value="2026-01-05" />);
    const date = screen.getByLabelText("Анх ажилд орсон огноо") as HTMLInputElement;
    expect(date.type).toBe("text");
    expect(date.getAttribute("data-dp")).toBe("1");
    expect(date.maxLength).toBe(10);
    expect(date.parentElement?.className).toBe("dp-wrap");
    expect(date.parentElement?.querySelector("button.dp-icon")?.getAttribute("aria-label")).toBe("Хуанли нээх");
  });

  it("a checkbox is a read-only checkbox with the flag's class and no width", () => {
    render(<Soft label="Хөгжлийн бэрхшээлтэй" kind="checkbox" value="" checked />);
    const box = screen.getByLabelText("Хөгжлийн бэрхшээлтэй") as HTMLInputElement;
    expect(box.type).toBe("checkbox");
    expect(box.checked).toBe(true);
    expect(box.readOnly).toBe(true);
    expect(box.className).toBe("h-4 w-4 accent-violet-600");
  });
});
