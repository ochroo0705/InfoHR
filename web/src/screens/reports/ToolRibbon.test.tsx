import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter, useLocation } from "react-router";
import type { components } from "../../api/schema";
import { legacyOrigin } from "../../lib/AppLink";
import { ToolRibbon } from "./ToolRibbon";

type ReportHeadOut = components["schemas"]["ReportHeadOut"];

// The head as the API sends it, with no tool drawn unless a test turns it on.
function headFixture(overrides: Partial<ReportHeadOut> = {}): ReportHeadOut {
  return {
    excel_url: "",
    layouts: [],
    print_url: "",
    saved: null,
    selectable: false,
    selection_urls: {},
    staff_actions: false,
    title: "Тест тайлан",
    tools: { columns: false, rules: false, format: false },
    ...overrides,
  } as ReportHeadOut;
}

// Shows the router's address, so a test can read where a click went.
function Probe() {
  const location = useLocation();
  return <div data-testid="loc">{location.pathname + location.search}</div>;
}

function renderRibbon(head: ReportHeadOut) {
  return render(
    <MemoryRouter initialEntries={["/reports/staff/?q=a"]}>
      <ToolRibbon reportKey="staff" head={head} columnsQuery="cols=name" clearUrl="/reports/staff/?view=plain" search="?q=a" />
      <Probe />
    </MemoryRouter>,
  );
}

function where(): string {
  return screen.getByTestId("loc").textContent ?? "";
}

afterEach(() => {
  cleanup();
});

describe("ToolRibbon", () => {
  it("ribbon_shows_only_tools_the_api_allows", () => {
    renderRibbon(headFixture({ tools: { columns: true, rules: false, format: false } }));

    expect(screen.getByText("Багана")).toBeTruthy();
    expect(screen.queryByText("Шүүлтүүр")).toBeNull();
    expect(screen.queryByText("Хэлбэр")).toBeNull();
    expect(screen.queryByLabelText("Хадгалсан харагдац")).toBeNull();
    expect(screen.queryByLabelText("Ажилтан импортлох")).toBeNull();
    expect(screen.queryByLabelText("Ажилтан нэмэх")).toBeNull();
  });

  it("export_link_absent_when_url_empty", () => {
    const { unmount } = renderRibbon(headFixture());
    expect(screen.queryByText("Excel")).toBeNull();
    expect(screen.queryByText("Хэвлэх")).toBeNull();
    expect(screen.queryByText("Гаргах, сонгох")).toBeNull();
    unmount();

    renderRibbon(headFixture({ excel_url: "/reports/staff/excel/?q=a", print_url: "/reports/staff/print/?q=a" }));
    expect(screen.getByText("Excel").closest("a")?.getAttribute("href")).toBe(
      legacyOrigin() + "/reports/staff/excel/?q=a",
    );
    const print = screen.getByText("Хэвлэх").closest("a");
    expect(print?.getAttribute("href")).toBe(legacyOrigin() + "/reports/staff/print/?q=a");
    expect(print?.getAttribute("target")).toBe("_blank");
    expect(print?.getAttribute("rel")).toBe("noopener");
  });

  it("saved_select_changes_address", () => {
    renderRibbon(
      headFixture({
        saved: {
          can_edit_view: false,
          current_view: null,
          options: [{ name: "Миний харагдац", selected: false, url: "/reports/staff/?view=5" }],
          plain_url: "/reports/staff/?view=plain",
          save_url: "/reports/staff/views/new/?q=a",
          template_current: false,
          templates: [],
        },
      }),
    );

    const select = screen.getByLabelText("Хадгалсан харагдац") as HTMLSelectElement;
    expect(select.value).toBe("/reports/staff/?view=plain");
    fireEvent.change(select, { target: { value: "/reports/staff/?view=5" } });
    expect(where()).toBe("/reports/staff/?view=5");
  });

  it("tool_links_open_the_django_pop_ups", () => {
    renderRibbon(
      headFixture({
        saved: {
          can_edit_view: true,
          current_view: 7,
          options: [],
          plain_url: "/reports/staff/?view=plain",
          save_url: "/reports/staff/views/new/?q=a",
          template_current: false,
          templates: [],
        },
        tools: { columns: true, rules: true, format: true },
      }),
    );

    const href = (label: string) => screen.getByText(label, { selector: "a" }).getAttribute("href");
    // Every pop-up link opens the full Django report page with the cleaned address; «Засах» opens the page at the
    // address the page shows. None of them is a Django htmx fragment address.
    expect(href("Хадгалах")).toBe(legacyOrigin() + "/reports/staff/?cols=name");
    expect(href("Засах")).toBe(legacyOrigin() + "/reports/staff/?q=a");
    expect(href("Багана")).toBe(legacyOrigin() + "/reports/staff/?cols=name");
    expect(href("Шүүлтүүр")).toBe(legacyOrigin() + "/reports/staff/?cols=name");
    expect(href("Хэлбэр")).toBe(legacyOrigin() + "/reports/staff/?cols=name");
    const title = screen.getByText("Багана", { selector: "a" }).getAttribute("title");
    expect(title).toBe("Хуучин хуудсанд нээгдэнэ, тэндээс товчийг дахин дарна уу");
  });

  it("the reset link and the staff buttons follow their rules", () => {
    renderRibbon(headFixture({ staff_actions: true }));

    const reset = screen.getByLabelText("Бүгдийг арилгах");
    expect(reset.getAttribute("href")).toBe("/reports/staff/?view=plain");
    expect(screen.getByLabelText("Ажилтан импортлох").getAttribute("href")).toBe(
      legacyOrigin() + "/employees/import/",
    );
    // The add button is an in-app link: a plain click moves the router to the hire page.
    fireEvent.click(screen.getByLabelText("Ажилтан нэмэх"));
    expect(where()).toBe("/employees/new/");
  });
});
