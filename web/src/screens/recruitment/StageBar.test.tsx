import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RecruitStageItemOut } from "../../api/recruitment";
import { StageBar } from "./StageBar";

const ITEMS: RecruitStageItemOut[] = [
  { key: "open", label: "Идэвхтэй", count: 4 },
  { key: "new", label: "Шинэ", count: 2 },
  { key: "screening", label: "Шалгаруулалт", count: 1 },
  { key: "all", label: "Бүгд", count: 9 },
];

afterEach(() => {
  cleanup();
});

describe("StageBar", () => {
  it("draws one button per stage inside the «Шат» navigation, with its count", () => {
    render(<StageBar items={ITEMS} active="open" onPick={vi.fn()} />);

    const nav = screen.getByRole("navigation", { name: "Шат" });
    const buttons = within(nav).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual(["Идэвхтэй4", "Шинэ2", "Шалгаруулалт1", "Бүгд9"]);
  });

  it("marks only the active stage with aria-current", () => {
    render(<StageBar items={ITEMS} active="new" onPick={vi.fn()} />);

    expect(screen.getByRole("button", { name: /Шинэ/ }).getAttribute("aria-current")).toBe("true");
    expect(screen.getByRole("button", { name: /Идэвхтэй/ }).getAttribute("aria-current")).toBeNull();
    expect(screen.getByRole("button", { name: /Бүгд/ }).getAttribute("aria-current")).toBeNull();
  });

  it("calls onPick with the key of the stage the user picks", () => {
    const onPick = vi.fn();
    render(<StageBar items={ITEMS} active="open" onPick={onPick} />);

    fireEvent.click(screen.getByRole("button", { name: /Шалгаруулалт/ }));

    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith("screening");
  });
});
