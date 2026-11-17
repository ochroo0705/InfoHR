import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { EmployeeHeadOut } from "../../api/employee";
import { Rail } from "./Rail";

// A header as the API sends it. Only the fields the rail reads matter; the rest is filled so the shape is complete.
function head(overrides: Partial<EmployeeHeadOut> = {}): EmployeeHeadOut {
  return {
    activity_count: 0,
    can: {
      create_login: false,
      manage: false,
      manage_salary: false,
      record_leave: false,
      view_personal: true,
      view_salary: true,
    },
    code: "E-001",
    email: "",
    event_menu: [],
    facts: {
      contract_end: "",
      department: "Хүний нөөц",
      employee_type: "",
      first_hire_date: "2024-01-01",
      manager: "",
      manager_label: "",
      position: "Мэргэжилтэн",
      work_phone: "",
    },
    family_name: "Бат",
    full_name: "Бат Болд",
    given_initial: "Б",
    given_name: "Болд",
    latest_activity: null,
    leave_left: null,
    next_event: null,
    one_time_login: null,
    photo_srcset: "",
    photo_url: "",
    pk: 1,
    setup: null,
    state: {} as EmployeeHeadOut["state"],
    ...overrides,
  } as EmployeeHeadOut;
}

// The rail renders links through the router (AppLink), so every render needs a Router.
function renderRail(h: EmployeeHeadOut, active?: string) {
  return render(
    <MemoryRouter>
      <Rail head={h} active={active} />
    </MemoryRouter>,
  );
}

// The value (dd) that sits next to a fact's sr-only label (dt), found by its label, not by its position.
function factValue(label: string): HTMLElement {
  const dt = screen.getByText(label).parentElement as HTMLElement;
  return dt.nextElementSibling as HTMLElement;
}

beforeEach(() => {
  // No Django origin unless a test sets one, so paths are left as sent.
  vi.stubEnv("VITE_LEGACY_ORIGIN", "");
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("Rail", () => {
  it("shows the given initial when there is no photo", () => {
    const { container } = renderRail(head({ photo_url: "" }));
    const square = screen.getByText("Б");
    expect(square.className).toContain("bg-violet-50");
    expect(container.querySelector("#rail-who img")).toBeNull();
  });

  it("shows the photo when the API sends one", () => {
    const { container } = renderRail(head({ photo_url: "/media/photos/1.jpg" }));
    expect(container.querySelector("#rail-who img")?.getAttribute("src")).toBe("/media/photos/1.jpg");
  });

  it("prefixes a photo path with the Django origin when one is set", () => {
    vi.stubEnv("VITE_LEGACY_ORIGIN", "http://127.0.0.1:8000");
    const { container } = renderRail(head({ photo_url: "/media/photos/1.jpg" }));
    expect(container.querySelector("#rail-who img")?.getAttribute("src")).toBe(
      "http://127.0.0.1:8000/media/photos/1.jpg",
    );
  });

  it("leaves a photo path unprefixed when the origin is empty", () => {
    const { container } = renderRail(head({ photo_url: "/media/photos/1.jpg" }));
    expect(container.querySelector("#rail-who img")?.getAttribute("src")).toBe("/media/photos/1.jpg");
  });

  it("shows a dash for an empty manager", () => {
    renderRail(head());
    expect(factValue("Шууд удирдлага").textContent).toBe("—");
  });

  it("shows the position and department in their rows", () => {
    renderRail(head());
    expect(factValue("Албан тушаал").textContent).toBe("Мэргэжилтэн");
    expect(factValue("Хэлтэс").textContent).toBe("Хүний нөөц");
  });

  it("shows the hire date as sent", () => {
    renderRail(head());
    expect(factValue("Ажилд орсон").textContent).toBe("2024-01-01");
  });

  it("links the work phone with a tel: link", () => {
    renderRail(head({ facts: { ...head().facts, work_phone: "99112233" } }));
    const link = screen.getByText("99112233").closest("a");
    expect(link?.getAttribute("href")).toBe("tel:99112233");
  });

  it("shows a dash instead of a phone link when there is no phone", () => {
    renderRail(head());
    expect(factValue("Утас").textContent).toBe("—");
    expect(document.querySelector('#rail-facts a[href^="tel:"]')).toBeNull();
  });

  it("links the back link to the employee list", () => {
    renderRail(head());
    const link = screen.getByText("← Ажилтнууд").closest("a");
    expect(link?.getAttribute("href")).toBe("/employees/");
  });

  it("hides the salary link without the salary right", () => {
    renderRail(head({ can: { ...head().can, view_salary: false } }));
    expect(screen.queryByText("Цалин, даатгал")).toBeNull();
    expect(screen.getByText("Хувийн")).toBeTruthy();
  });

  it("hides the personal link without the personal right", () => {
    renderRail(head({ can: { ...head().can, view_personal: false } }));
    expect(screen.queryByText("Хувийн")).toBeNull();
    expect(screen.getByText("Цалин, даатгал")).toBeTruthy();
  });

  it("shows the days left of the current leave period", () => {
    renderRail(head({ leave_left: "12.5" }));
    expect(screen.getByText("12.5")).toBeTruthy();
    expect(screen.getByText("хоног")).toBeTruthy();
  });

  it("hides the leave box when leave_left is null", () => {
    renderRail(head({ leave_left: null }));
    expect(screen.queryByText("Үлдсэн амралт")).toBeNull();
  });

  it("marks the active section link like the scroll-spy does", () => {
    renderRail(head(), "salary");
    const link = screen.getByText("Цалин, даатгал").closest("a");
    expect(link?.getAttribute("aria-current")).toBe("page");
    expect(link?.className).toContain("bg-violet-50");
    const work = screen.getByText("Ажил").closest("a");
    expect(work?.getAttribute("aria-current")).toBeNull();
  });
});

describe("Rail with no position today", () => {
  it("shows a dash for the empty position, as _rail.html's default", () => {
    renderRail(head({ facts: { ...head().facts, position: "", department: "", position_line: "" } }));
    expect(factValue("Албан тушаал").textContent).toBe("—");
  });
});
