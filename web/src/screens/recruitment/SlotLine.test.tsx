import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SlotLine } from "./SlotLine";

afterEach(cleanup);

describe("SlotLine (_slot_line.html)", () => {
  it("draws nothing for null", () => {
    const { container } = render(<SlotLine line={null} />);
    expect(container.innerHTML).toBe("");
  });

  it("shows the numbers in the slate box when there is no warning", () => {
    const { getByText } = render(<SlotLine line={{ numbers: "2026 он · орон тоо 3 · ажиллаж буй 2 · сул 1", warning: "" }} />);
    const box = getByText("Орон тоо: 2026 он · орон тоо 3 · ажиллаж буй 2 · сул 1");
    expect(box.className).toContain("bg-slate-50");
    expect(box.className).toContain("text-slate-700");
  });

  it("joins the numbers and the warning with a dash, in the amber box", () => {
    const { getByText } = render(<SlotLine line={{ numbers: "2026 он · орон тоо 3", warning: "Сул орон алга" }} />);
    const box = getByText(/Орон тоо:/);
    expect(box.className).toContain("bg-amber-50");
    expect(box.className).toContain("text-amber-800");
    expect(box.textContent).toBe("Орон тоо: 2026 он · орон тоо 3 — Сул орон алга");
  });

  it("shows only the warning when there are no numbers", () => {
    const { getByText, queryByText } = render(<SlotLine line={{ numbers: "", warning: "Салбар сонгоогүй" }} />);
    expect(getByText("Салбар сонгоогүй").className).toContain("bg-amber-50");
    expect(queryByText(/Орон тоо:/)).toBeNull();
  });
});
