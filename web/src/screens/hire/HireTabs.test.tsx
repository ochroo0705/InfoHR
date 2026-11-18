import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HireTabs } from "./HireTabs";

const ACTIVE = "flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-100 bg-violet-50 text-violet-700 font-medium";
const INACTIVE = "flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-100 text-slate-600";

const tabs = [
  { key: "basic", label: "Үндсэн" },
  { key: "personal", label: "Хувийн" },
  { key: "salary", label: "Цалин, даатгал" },
  { key: "login", label: "Нэвтрэх эрх" },
];

afterEach(() => cleanup());

describe("HireTabs", () => {
  it("gives the active button exactly the active classes and aria-selected true, the others false", () => {
    render(<HireTabs tabs={tabs} active="personal" badges={{}} onSelect={() => {}} />);
    const personal = screen.getByRole("tab", { name: /Хувийн/ });
    expect(personal.className).toBe(ACTIVE);
    expect(personal.getAttribute("aria-selected")).toBe("true");
    const basic = screen.getByRole("tab", { name: /Үндсэн/ });
    expect(basic.className).toBe(INACTIVE);
    expect(basic.getAttribute("aria-selected")).toBe("false");
  });

  it("renders the tablist with its label and strip classes", () => {
    render(<HireTabs tabs={tabs} active="basic" badges={{}} onSelect={() => {}} />);
    const nav = screen.getByRole("tablist");
    expect(nav.getAttribute("aria-label")).toBe("Табууд");
    expect(nav.className).toBe("flex gap-1 overflow-x-auto md:w-52 md:shrink-0 md:flex-col md:overflow-visible");
  });

  it("shows the badge text with its tone classes", () => {
    render(
      <HireTabs
        tabs={tabs}
        active="basic"
        badges={{ basic: { text: "2", tone: "error" }, personal: { text: "✓", tone: "done" } }}
        onSelect={() => {}}
      />,
    );
    const errorBadge = document.querySelector('[data-badge="basic"]') as HTMLElement;
    expect(errorBadge.textContent).toBe("2");
    expect(errorBadge.className).toBe("ml-auto rounded-full px-1.5 text-xs font-semibold bg-red-600 text-white");
    const doneBadge = document.querySelector('[data-badge="personal"]') as HTMLElement;
    expect(doneBadge.textContent).toBe("✓");
    expect(doneBadge.className).toBe("ml-auto rounded-full px-1.5 text-xs font-semibold text-emerald-700");
    const blank = document.querySelector('[data-badge="login"]') as HTMLElement;
    expect(blank.textContent).toBe("");
    expect(blank.className).toBe("ml-auto rounded-full px-1.5 text-xs font-semibold");
  });

  it("calls onSelect with the tab key when a tab is clicked", () => {
    const onSelect = vi.fn();
    render(<HireTabs tabs={tabs} active="basic" badges={{}} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("tab", { name: /Нэвтрэх эрх/ }));
    expect(onSelect).toHaveBeenCalledWith("login");
  });

  it("draws no salary tab when the tabs array has no salary entry", () => {
    render(<HireTabs tabs={tabs.filter((t) => t.key !== "salary")} active="basic" badges={{}} onSelect={() => {}} />);
    expect(screen.queryByRole("tab", { name: /Цалин/ })).toBeNull();
    expect(screen.getAllByRole("tab")).toHaveLength(3);
  });
});
