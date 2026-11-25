import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter, useLocation } from "react-router";
import type { components } from "../../api/schema";
import { ReportHeader } from "./ReportHeader";

type ReportLayoutOut = components["schemas"]["ReportLayoutOut"];

const LAYOUTS: ReportLayoutOut[] = [
  { current: true, label: "Хүснэгт", name: "table", url: "/reports/staff/?view=plain" },
  { current: false, label: "Карт", name: "cards", url: "/reports/staff/?layout=cards" },
];

function Probe() {
  const location = useLocation();
  return <div data-testid="loc">{location.pathname + location.search}</div>;
}

function renderHeader(layouts: ReportLayoutOut[]) {
  return render(
    <MemoryRouter initialEntries={["/reports/staff/"]}>
      <ReportHeader title="Ажилчдын жагсаалт" layouts={layouts} />
      <Probe />
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
});

describe("ReportHeader", () => {
  it("switcher_marks_current_layout", () => {
    renderHeader(LAYOUTS);

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Ажилчдын жагсаалт");
    const group = screen.getByRole("group", { name: "Харагдац" });
    const current = screen.getByText("Хүснэгт");
    expect(current.getAttribute("aria-current")).toBe("page");
    expect(current.className).toContain("is-picked");
    expect(current.className).toContain("font-semibold");

    const other = screen.getByText("Карт");
    expect(other.getAttribute("aria-current")).toBeNull();
    expect(other.className).not.toContain("is-picked");
    expect(group.contains(other)).toBe(true);

    fireEvent.click(other);
    expect(screen.getByTestId("loc").textContent).toBe("/reports/staff/?layout=cards");
  });

  it("no switcher when the report offers one layout", () => {
    renderHeader([LAYOUTS[0]]);
    expect(screen.queryByRole("group", { name: "Харагдац" })).toBeNull();
    expect(screen.getByRole("heading", { level: 1 })).toBeTruthy();
  });
});
