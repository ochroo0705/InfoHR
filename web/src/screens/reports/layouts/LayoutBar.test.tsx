import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReportLayoutBarOut } from "../../../api/reports";
import { LayoutBar } from "./LayoutBar";

const BAR = {
  layout: "board",
  keep: [["q", "a"]],
  selects: [
    {
      name: "lby",
      label: "Ангилал",
      selected: "branch",
      options: [
        { label: "Салбар", value: "branch" },
        { label: "Албан тушаал", value: "position" },
      ],
    },
    {
      name: "lorder",
      label: "Эрэмбэ",
      selected: "",
      options: [
        { label: "Анхны дараалал", value: "" },
        { label: "Тоогоор", value: "count" },
      ],
    },
  ],
} as unknown as ReportLayoutBarOut;

describe("LayoutBar", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders one select per model entry in order with the label text", () => {
    const { container } = render(<LayoutBar bar={BAR} query="" onChange={vi.fn()} />);

    expect(container.querySelector('form[aria-label="Харагдацын багана"]')).not.toBeNull();
    const selects = Array.from(container.querySelectorAll("select"));
    expect(selects.map((el) => el.getAttribute("name"))).toEqual(["lby", "lorder"]);
    // Each select sits inside a label that carries the entry's text, and names itself with it.
    expect(selects[0].closest("label")?.textContent?.startsWith("Ангилал")).toBe(true);
    expect(selects[0].closest("label")?.querySelector("span")?.textContent).toBe("Ангилал");
    expect(selects[1].closest("label")?.querySelector("span")?.textContent).toBe("Эрэмбэ");
    expect(selects[0].getAttribute("aria-label")).toBe("Ангилал");
    expect(selects[1].getAttribute("aria-label")).toBe("Эрэмбэ");
    expect(selects[0].value).toBe("branch");
  });

  it("a change calls onChange once with the address where only that parameter changed", () => {
    const onChange = vi.fn();
    const query = "?q=a%20b&add=branch&add=position&cols=name&lby=branch&lorder=count&sort=-name";
    const { container } = render(<LayoutBar bar={BAR} query={query} onChange={onChange} />);

    fireEvent.change(container.querySelector('select[name="lby"]') as HTMLSelectElement, {
      target: { value: "position" },
    });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("?q=a%20b&add=branch&add=position&cols=name&lby=position&lorder=count&sort=-name");
  });

  it("renders nothing for an empty selects list", () => {
    const { container } = render(<LayoutBar bar={{ ...BAR, selects: [] }} query="" onChange={vi.fn()} />);

    expect(container.innerHTML).toBe("");
  });

  it("option texts are text, not markup", () => {
    const markup = { ...BAR, selects: [{ ...BAR.selects[0], options: [{ label: "<b>x</b>", value: "x" }], selected: "x" }] };
    const { container } = render(<LayoutBar bar={markup as unknown as ReportLayoutBarOut} query="" onChange={vi.fn()} />);

    expect(container.querySelector("option")?.textContent).toBe("<b>x</b>");
    expect(container.querySelector("b")).toBeNull();
  });
});
