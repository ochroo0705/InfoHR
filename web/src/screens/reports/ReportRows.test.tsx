import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";
import type { ReportCellOut, ReportGroupOut } from "../../api/reports";
import { ReportRows } from "./ReportRows";

function text(value: string): ReportCellOut {
  return { value, text: value, money: false, href: "", css: "", style: "", person: 0 };
}

const GROUPED: ReportGroupOut[] = [
  { label: "Санхүү", count: 2, rows: [[text("Бат")], [text("Сарнай")]] },
  { label: "Хүний нөөц", count: 1, rows: [[text("Номин")]] },
];

function renderRows(groups: ReportGroupOut[], grouped: boolean) {
  return render(
    <MemoryRouter>
      <table>
        <tbody>
          <ReportRows groups={groups} grouped={grouped} tableSpan={2} />
        </tbody>
      </table>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
});

describe("ReportRows", () => {
  it("rows_render_groups_with_headings_and_counts", () => {
    const { container } = renderRows(GROUPED, true);

    const rows = Array.from(container.querySelectorAll("tbody > tr"));
    // Two headings and three rows, in order: heading, its rows, heading, its rows.
    expect(rows).toHaveLength(5);
    const heading = rows[0].querySelector("td")!;
    expect(heading.textContent).toBe("Санхүү · 2");
    expect(heading.getAttribute("colspan")).toBe("2");
    expect(heading.className).toBe("font-semibold text-slate-900");
    expect(rows[1].textContent).toBe("Бат");
    expect(rows[3].querySelector("td")!.textContent).toBe("Хүний нөөц · 1");
    expect(rows[4].textContent).toBe("Номин");
  });

  it("an ungrouped table draws its rows only, with no heading", () => {
    const { container } = renderRows([{ label: "", count: 2, rows: [[text("Бат")], [text("Сарнай")]] }], false);

    const rows = Array.from(container.querySelectorAll("tbody > tr"));
    expect(rows.map((row) => row.textContent)).toEqual(["Бат", "Сарнай"]);
    expect(container.querySelector("td[colspan]")).toBeNull();
  });
});
