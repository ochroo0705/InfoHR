import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { components } from "../../api/schema";
import { ColumnChips } from "./ColumnChips";

type ReportColumnChipOut = components["schemas"]["ReportColumnChipOut"];

const opt = (value: string, label: string) => ({ value, label });

const chips: ReportColumnChipOut[] = [
  {
    name: "position",
    params: ["position"],
    label: "Албан тушаал",
    kind: "code",
    options: [opt("1", "—"), opt("2", "Захирал")],
    values: ["2"],
    remove_href: "/reports/x/?q=a",
  },
  {
    name: "hired",
    params: ["hired_from", "hired_to"],
    label: "Ажилд орсон",
    kind: "date",
    options: [],
    values: ["2026-01-01", ""],
    remove_href: "/reports/x/?q=b",
  },
  {
    name: "months",
    params: ["months_from", "months_to"],
    label: "Туршлага",
    kind: "number",
    options: [],
    values: ["", "5"],
    remove_href: "/reports/x/?q=c",
  },
];

function renderChips(query: string, onChange = vi.fn(), list: ReportColumnChipOut[] = chips) {
  render(
    <MemoryRouter>
      <ColumnChips chips={list} query={query} onEdit={onChange} />
    </MemoryRouter>,
  );
  return onChange;
}

afterEach(() => {
  cleanup();
});

describe("ColumnChips", () => {
  it("column_chip_options_and_values", () => {
    renderChips("");
    expect(document.querySelectorAll("[data-column-chip]")).toHaveLength(3);
    expect(document.querySelector('[data-column-chip="position"]')).not.toBeNull();

    const position = screen.getByLabelText("Албан тушаал") as HTMLSelectElement;
    expect(Array.from(position.options).map((o) => o.textContent)).toEqual(["Бүгд", "—", "Захирал"]);
    expect(position.value).toBe("2");

    expect((screen.getByLabelText("Ажилд орсон: эхлэх") as HTMLInputElement).value).toBe("2026-01-01");
    expect((screen.getByLabelText("Ажилд орсон: дуусах") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Туршлага: доод") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Туршлага: дээд") as HTMLInputElement).value).toBe("5");
  });

  it("column_chip_remove_is_a_link_to_remove_href", () => {
    renderChips("");
    const removes = screen.getAllByLabelText("Шүүлтүүрийг арилгах");
    expect(removes).toHaveLength(3);
    expect(removes[0].tagName).toBe("A");
    expect(removes[0].getAttribute("href")).toBe("/reports/x/?q=a");
    expect(removes[2].getAttribute("href")).toBe("/reports/x/?q=c");
  });

  it("a choice change edits only its own parameter", () => {
    const onChange = renderChips("branch=5&position=2&sort=name");
    fireEvent.change(screen.getByLabelText("Албан тушаал"), { target: { value: "1" } });
    expect(onChange).toHaveBeenCalledWith("position", "1");
  });

  it("a chip writes the parameter names the API sends, not names built from the chip name", () => {
    const onChange = renderChips("h1=2026-01-01", vi.fn(), [
      {
        name: "hired",
        params: ["h1", "h2"],
        label: "Ажилд орсон",
        kind: "date",
        options: [],
        values: ["2026-01-01", ""],
        remove_href: "/reports/x/?q=b",
      },
    ]);
    const to = screen.getByLabelText("Ажилд орсон: дуусах");
    fireEvent.change(to, { target: { value: "2026-06-30" } });
    fireEvent.keyDown(to, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("h2", "2026-06-30");
  });

  it("a range chip commits its own bound on blur", () => {
    const onChange = renderChips("hired_from=2026-01-01&q=x");
    const from = screen.getByLabelText("Ажилд орсон: эхлэх");
    fireEvent.change(from, { target: { value: "2026-02-01" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(from);
    expect(onChange).toHaveBeenCalledWith("hired_from", "2026-02-01");
  });
});
