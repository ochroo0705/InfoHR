import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { ReportHeadCellOut } from "../../api/reports";
import { HeaderRow } from "./HeaderRow";

const NAME: ReportHeadCellOut = {
  label: "Нэр",
  href: "/reports/staff/?sort=name",
  append_href: "/reports/staff/?sort=name,-number",
  arrow: "↑",
  css: "sticky z-10",
  sticky_left: "left: 0rem",
};

const NUMBER: ReportHeadCellOut = {
  label: "Дугаар",
  href: "/reports/staff/?sort=-number",
  append_href: "/reports/staff/?sort=-number,name",
  arrow: "",
  css: "",
  sticky_left: "",
};

// Shows the address the router is on, so a test can read where a click led.
function Address() {
  const location = useLocation();
  return <p data-testid="address">{location.pathname + location.search}</p>;
}

function renderHeader(heads: ReportHeadCellOut[]) {
  return render(
    <MemoryRouter initialEntries={["/reports/staff/?sort=number"]}>
      <table>
        <thead>
          <HeaderRow heads={heads} />
        </thead>
      </table>
      <Routes>
        <Route path="*" element={<Address />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
});

describe("HeaderRow", () => {
  it("header_link_sorts_and_shift_click_appends", () => {
    const { getByText, getByTestId } = renderHeader([NAME, NUMBER]);

    const link = getByText("Нэр", { exact: false }).closest("a")!;
    expect(link.getAttribute("href")).toBe("/reports/staff/?sort=name");
    expect(link.getAttribute("data-append")).toBe("/reports/staff/?sort=name,-number");
    expect(link.getAttribute("title")).toBe("Shift+товшилт: нэмэлт эрэмбэ");

    // A plain click sorts in place: the page's address becomes the head's href.
    const plainNotPrevented = fireEvent.click(link);
    expect(plainNotPrevented).toBe(false);
    expect(getByTestId("address").textContent).toBe("/reports/staff/?sort=name");

    // A Shift click goes to the append address instead.
    const shiftNotPrevented = fireEvent.click(getByText("Дугаар", { exact: false }).closest("a")!, { shiftKey: true });
    expect(shiftNotPrevented).toBe(false);
    expect(getByTestId("address").textContent).toBe("/reports/staff/?sort=-number,name");
  });

  it("header_arrow_text", () => {
    const { container } = renderHeader([NAME, NUMBER]);

    const [nameArrow, numberArrow] = Array.from(container.querySelectorAll("th a span"));
    expect(nameArrow.textContent).toBe("↑");
    expect(nameArrow.getAttribute("aria-hidden")).toBe("true");
    expect((nameArrow as HTMLElement).style.visibility).toBe("");

    // No arrow: the mark keeps its place (hidden) and shows the default arrow.
    expect(numberArrow.textContent).toBe("↑");
    expect((numberArrow as HTMLElement).style.visibility).toBe("hidden");
    expect((numberArrow as HTMLElement).style.minWidth).toBe("2ch");
  });

  it("the head's css and pinned offset reach the th", () => {
    const { container } = renderHeader([NAME, NUMBER]);

    const [nameTh, numberTh] = Array.from(container.querySelectorAll("th"));
    expect(nameTh.className).toBe("sticky z-10");
    expect(nameTh.style.left).toBe("0rem");
    expect(numberTh.hasAttribute("class")).toBe(false);
    expect(numberTh.hasAttribute("style")).toBe(false);
  });
});
