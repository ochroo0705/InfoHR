import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { StageChip, VacancyStatusChip } from "./stageChip";

afterEach(cleanup);

describe("VacancyStatusChip (_vacancy_status.html)", () => {
  it("open is emerald, filled is sky, anything else slate", () => {
    const { unmount } = render(<VacancyStatusChip status="open" label="Нээлттэй" />);
    expect(screen.getByText("Нээлттэй").className).toContain("bg-emerald-100");
    unmount();
    const filled = render(<VacancyStatusChip status="filled" label="Бөглөгдсөн" />);
    expect(screen.getByText("Бөглөгдсөн").className).toContain("bg-sky-100");
    filled.unmount();
    render(<VacancyStatusChip status="closed" label="Хаагдсан" />);
    const chip = screen.getByText("Хаагдсан");
    expect(chip.className).toContain("bg-slate-200");
    expect(chip.className).toContain("rounded-full");
  });
});

describe("StageChip (_stage_chip.html)", () => {
  it.each([
    ["hired", "bg-emerald-100", "text-emerald-800"],
    ["rejected", "bg-red-100", "text-red-800"],
    ["withdrawn", "bg-slate-200", "text-slate-700"],
    ["new", "bg-sky-100", "text-sky-800"],
    ["screening", "bg-violet-100", "text-violet-800"],
  ])("%s uses its colours and never wraps", (stage, bg, text) => {
    render(<StageChip stage={stage} label="Шат" />);
    const chip = screen.getByText("Шат");
    expect(chip.className).toContain(bg);
    expect(chip.className).toContain(text);
    expect(chip.className).toContain("whitespace-nowrap");
  });
});
