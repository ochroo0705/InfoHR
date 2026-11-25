import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router";
import type { components } from "../../api/schema";
import { legacyOrigin } from "../../lib/AppLink";
import { ReportPopUp, ToolRibbon } from "./ToolRibbon";

type ReportHeadOut = components["schemas"]["ReportHeadOut"];

// The four pop-ups are stubbed: each stub shows which pop-up it is, the query or target it got, and a close button.
// Their own behaviour is tested in popups/*.test.tsx.
vi.mock("./popups/ColumnsModal", async () => {
  const { createElement } = await import("react");
  return {
    ColumnsModal: (props: { reportKey: string; query: string; onClose: () => void }) =>
      createElement(
        "div",
        { role: "dialog", "data-pop": "columns", "data-key": props.reportKey, "data-query": props.query },
        createElement("button", { type: "button", onClick: props.onClose }, "stub-close"),
      ),
  };
});
vi.mock("./popups/RulesModal", async () => {
  const { createElement } = await import("react");
  return {
    RulesModal: (props: { reportKey: string; query: string; onClose: () => void }) =>
      createElement(
        "div",
        { role: "dialog", "data-pop": "rules", "data-key": props.reportKey, "data-query": props.query },
        createElement("button", { type: "button", onClick: props.onClose }, "stub-close"),
      ),
  };
});
vi.mock("./popups/FormatModal", async () => {
  const { createElement } = await import("react");
  return {
    FormatModal: (props: { reportKey: string; query: string; onClose: () => void }) =>
      createElement(
        "div",
        { role: "dialog", "data-pop": "format", "data-key": props.reportKey, "data-query": props.query },
        createElement("button", { type: "button", onClick: props.onClose }, "stub-close"),
      ),
  };
});
vi.mock("./popups/SavedViewModal", async () => {
  const { createElement } = await import("react");
  return {
    SavedViewModal: (props: { target: unknown; onClose: () => void }) =>
      createElement(
        "div",
        { role: "dialog", "data-pop": "saved", "data-target": JSON.stringify(props.target) },
        createElement("button", { type: "button", onClick: props.onClose }, "stub-close"),
      ),
  };
});

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

const SAVED_OWN = {
  can_edit_view: true,
  current_view: 7,
  options: [],
  plain_url: "/reports/staff/?view=plain",
  template_current: false,
  templates: [],
};

// Shows the router's address, so a test can read where a click went.
function Probe() {
  const location = useLocation();
  return <div data-testid="loc">{location.pathname + location.search}</div>;
}

// The ribbon with a spy in place of the page's pop-up state: a test reads which pop-up a button asked for.
function renderRibbon(head: ReportHeadOut, onOpen = vi.fn()) {
  render(
    <MemoryRouter initialEntries={["/reports/staff/?q=a"]}>
      <ToolRibbon reportKey="staff" head={head} clearUrl="/reports/staff/?view=plain" onOpen={onOpen} />
      <Probe />
    </MemoryRouter>,
  );
  return onOpen;
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

  it("columns_button_opens_columns_modal", () => {
    const onOpen = renderRibbon(headFixture({ tools: { columns: true, rules: false, format: false } }));

    const columns = screen.getByText("Багана", { selector: "button" });
    expect(columns.getAttribute("data-tool")).toBe("columns");
    expect(columns.getAttribute("type")).toBe("button");
    expect(columns.getAttribute("title")).toBeNull();

    fireEvent.click(columns);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledWith("columns");
  });

  it("rules_and_format_buttons_open_theirs", () => {
    const onOpen = renderRibbon(headFixture({ tools: { columns: false, rules: true, format: true } }));

    fireEvent.click(screen.getByText("Шүүлтүүр", { selector: "button" }));
    expect(onOpen).toHaveBeenLastCalledWith("rules");
    fireEvent.click(screen.getByText("Хэлбэр", { selector: "button" }));
    expect(onOpen).toHaveBeenLastCalledWith("format");
  });

  it("tools_the_api_hides_stay_hidden", () => {
    renderRibbon(headFixture({ tools: { columns: false, rules: false, format: false }, saved: { ...SAVED_OWN } }));

    expect(screen.queryByText("Багана")).toBeNull();
    expect(screen.queryByText("Шүүлтүүр")).toBeNull();
    expect(screen.queryByText("Хэлбэр")).toBeNull();
    expect(document.querySelector("[data-tool]")).toBeNull();
    // The saved-view buttons are still there: only the settings tools were hidden.
    expect(screen.getByText("Хадгалах", { selector: "button" })).toBeTruthy();
  });

  it("save_opens_new_with_cleaned_query", () => {
    const onOpen = renderRibbon(headFixture({ saved: { ...SAVED_OWN, can_edit_view: false, current_view: null } }));

    fireEvent.click(screen.getByText("Хадгалах", { selector: "button" }));
    expect(onOpen).toHaveBeenCalledWith("save");
  });

  it("edit_button_only_when_can_edit_view", () => {
    // Not allowed to change the view: no «Засах».
    renderRibbon(headFixture({ saved: { ...SAVED_OWN, can_edit_view: false } }));
    expect(screen.queryByText("Засах")).toBeNull();
    cleanup();

    // Allowed, but the page shows no saved view: no «Засах».
    renderRibbon(headFixture({ saved: { ...SAVED_OWN, current_view: null } }));
    expect(screen.queryByText("Засах")).toBeNull();
    cleanup();

    // Allowed and a view is shown: «Засах» asks for the edit.
    const onOpen = renderRibbon(headFixture({ saved: { ...SAVED_OWN } }));
    fireEvent.click(screen.getByText("Засах", { selector: "button" }));
    expect(onOpen).toHaveBeenCalledWith("edit");
  });

  it("print_and_excel_stay_legacy_links", () => {
    renderRibbon(headFixture({ excel_url: "/reports/staff/excel/?q=a", print_url: "/reports/staff/print/?q=a" }));

    const excel = screen.getByText("Excel").closest("a");
    expect(excel?.getAttribute("href")).toBe(legacyOrigin() + "/reports/staff/excel/?q=a");
    expect(screen.queryByText("Excel", { selector: "button" })).toBeNull();

    const print = screen.getByText("Хэвлэх").closest("a");
    expect(print?.getAttribute("href")).toBe(legacyOrigin() + "/reports/staff/print/?q=a");
    expect(print?.getAttribute("target")).toBe("_blank");
    expect(print?.getAttribute("rel")).toBe("noopener");
    expect(print?.getAttribute("title")).toBe("Хуучин хуудсанд нээгдэнэ, тэндээс товчийг дахин дарна уу");
    expect(screen.queryByText("Хэвлэх", { selector: "button" })).toBeNull();
  });

  it("export_link_absent_when_url_empty", () => {
    renderRibbon(headFixture());
    expect(screen.queryByText("Excel")).toBeNull();
    expect(screen.queryByText("Хэвлэх")).toBeNull();
    expect(screen.queryByText("Гаргах, сонгох")).toBeNull();
  });

  it("saved_select_changes_address", () => {
    renderRibbon(
      headFixture({
        saved: {
          can_edit_view: false,
          current_view: null,
          options: [{ name: "Миний харагдац", selected: false, url: "/reports/staff/?view=5" }],
          plain_url: "/reports/staff/?view=plain",
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

// The pop-up the page has open: which stub it shows, what address or target it gets, and that its close reports back.
describe("ReportPopUp", () => {
  it("settings_pop_ups_get_the_address_and_close", () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <ReportPopUp reportKey="staff" open="columns" query="q=a" savedQuery="q=a" editPk={null} onClose={onClose} />,
    );
    expect(document.querySelector('[role="dialog"]')?.getAttribute("data-pop")).toBe("columns");
    expect(document.querySelector('[role="dialog"]')?.getAttribute("data-query")).toBe("q=a");
    expect(document.querySelector('[role="dialog"]')?.getAttribute("data-key")).toBe("staff");

    rerender(<ReportPopUp reportKey="staff" open="rules" query="q=b" savedQuery="q=a" editPk={null} onClose={onClose} />);
    expect(document.querySelectorAll('[role="dialog"]').length).toBe(1);
    expect(document.querySelector('[role="dialog"]')?.getAttribute("data-pop")).toBe("rules");
    expect(document.querySelector('[role="dialog"]')?.getAttribute("data-query")).toBe("q=b");

    fireEvent.click(screen.getByText("stub-close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("save_gets_the_cleaned_query_and_edit_the_view_pk", () => {
    const { rerender } = render(
      <ReportPopUp
        reportKey="staff"
        open="save"
        query="q=x"
        savedQuery="q=%D0%91%D0%B0%D1%82"
        editPk={null}
        onClose={vi.fn()}
      />,
    );
    expect(JSON.parse(document.querySelector('[role="dialog"]')?.getAttribute("data-target") ?? "null")).toEqual({
      mode: "new",
      query: "q=%D0%91%D0%B0%D1%82",
    });

    rerender(<ReportPopUp reportKey="staff" open="edit" query="q=x" savedQuery="q=a" editPk={7} onClose={vi.fn()} />);
    expect(JSON.parse(document.querySelector('[role="dialog"]')?.getAttribute("data-target") ?? "null")).toEqual({
      mode: "edit",
      pk: 7,
    });

    // No view to edit: nothing opens.
    rerender(<ReportPopUp reportKey="staff" open="edit" query="q=x" savedQuery="q=a" editPk={null} onClose={vi.fn()} />);
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });
});
