import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EmployeeHeadOut } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";
import { SetupCard } from "./SetupCard";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

type Setup = NonNullable<EmployeeHeadOut["setup"]>;

// A checklist as the API sends it: two items done or not, one system item, the texts and percent already computed.
function setup(overrides: Partial<Setup> = {}): Setup {
  return {
    items: [
      { key: "contract", label: "Гэрээ байгуулсан", done: true, auto: false, note: "Админ · 2026-01-05 10:00" },
      { key: "photo", label: "Зураг оруулсан", done: false, auto: false, note: "" },
      { key: "bank", label: "Банкны данс", done: false, auto: true, note: "" },
    ],
    done: 1,
    total: 3,
    complete: false,
    percent: 33,
    progress_text: "1/3 хийгдсэн",
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(openLegacyEmployee).mockClear();
});

afterEach(() => {
  cleanup();
});

describe("SetupCard", () => {
  it("renders nothing when setup is null", () => {
    const { container } = render(<SetupCard setup={null} pk={7} />);
    expect(container.innerHTML).toBe("");
  });

  it("shows the done count, the «done/total» text and the progress width while incomplete", () => {
    const { container } = render(<SetupCard setup={setup()} pk={7} />);
    expect(container.querySelector("#setup")?.className).toBe("mb-6");
    expect(screen.getByText("Бүрдүүлэлт")).toBeTruthy();
    expect(screen.getByText("1/3 хийгдсэн")).toBeTruthy();
    const details = container.querySelector("details");
    expect(details?.hasAttribute("open")).toBe(true);
    expect(details?.className).toContain("border-l-amber-500");
    const bar = container.querySelector(".transition-all") as HTMLElement;
    expect(bar.style.width).toBe("33%");
    expect(bar.className).toBe("block h-full rounded-full bg-amber-500 transition-all");
  });

  it("shows the completed title and a closed card when complete", () => {
    const { container } = render(
      <SetupCard setup={setup({ complete: true, done: 3, percent: 100, progress_text: "3/3 хийгдсэн" })} pk={7} />,
    );
    expect(screen.getByText("Бүрдүүлэлт дууссан")).toBeTruthy();
    expect(screen.queryByText("3/3 хийгдсэн")).toBeNull();
    const details = container.querySelector("details");
    expect(details?.hasAttribute("open")).toBe(false);
    expect(details?.className).toContain("border-l-emerald-500");
  });

  it("marks a system item as automatic with its disabled checkbox", () => {
    render(<SetupCard setup={setup()} pk={7} />);
    expect(screen.getByText("автоматаар").getAttribute("title")).toBe("Систем өөрөө тэмдэглэнэ");
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes[2].disabled).toBe(true);
    expect(boxes[1].disabled).toBe(false);
  });

  it("shows the note of a ticked item and no note on an open one", () => {
    render(<SetupCard setup={setup()} pk={7} />);
    expect(screen.getByText("Админ · 2026-01-05 10:00").className).toBe("ml-auto text-xs text-slate-400");
    expect(screen.getByText("Зураг оруулсан").className).toBe("font-medium text-slate-800");
    expect(screen.getByText("Гэрээ байгуулсан").className).toBe("text-slate-500");
  });

  it("opens the legacy page when a person ticks an item", () => {
    render(<SetupCard setup={setup()} pk={7} />);
    fireEvent.click(screen.getByText("Зураг оруулсан"));
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });
});
