import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { EmployeeHeadOut } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";
import { Header } from "./Header";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

// A header as the API sends it. Each test overrides only what it checks.
function head(overrides: Partial<EmployeeHeadOut> = {}): EmployeeHeadOut {
  return {
    activity_count: 12,
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
      employee_type: "Үндсэн ажилтан",
      first_hire_date: "2024-01-01",
      manager: "Сарнай Дорж",
      manager_label: "E-002 Сарнай Дорж",
      position: "Мэргэжилтэн",
      position_line: "Мэргэжилтэн · Хүний нөөц",
      work_phone: "7700-1234",
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
    pk: 7,
    setup: null,
    state: { key: "active", label: "Ажиллаж байгаа", tone: "state-active" },
    ...overrides,
  } as EmployeeHeadOut;
}

const MANAGE = { ...head().can, manage: true };

function renderHeader(h: EmployeeHeadOut, onOpenActivity = vi.fn()) {
  const utils = render(
    <MemoryRouter>
      <Header head={h} onOpenActivity={onOpenActivity} />
    </MemoryRouter>,
  );
  return { onOpen: onOpenActivity, ...utils };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Header", () => {
  it("shows the name, the position line, the state badge and the activity count", () => {
    const { container } = renderHeader(head());
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Бат Болд");
    expect(screen.getByText("Мэргэжилтэн · Хүний нөөц")).toBeTruthy();
    expect(screen.getByText("Ажиллаж байгаа").className).toBe("state-active");
    expect(container.querySelector("#activity-count")?.textContent).toBe("12");
  });

  it("renders the API's position line as sent, with nothing computed on the client", () => {
    renderHeader(head({ facts: { ...head().facts, position: "", department: "", position_line: "" } }));
    expect(screen.queryByText("Мэргэжилтэн")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).parentElement?.querySelector("p")?.textContent).toBe("");
  });

  it("the event menu item calls openLegacyEmployee with the pk", () => {
    renderHeader(head({ event_menu: [{ value: "transfer", label: "Албан тушаал солих" }] }));
    fireEvent.click(screen.getByText("Өөрчлөлт бүртгэх ▾"));
    fireEvent.click(screen.getByRole("button", { name: "Албан тушаал солих" }));
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });

  it("the event menu is not shown when the API sends no items", () => {
    renderHeader(head({ event_menu: [] }));
    expect(screen.queryByText("Өөрчлөлт бүртгэх ▾")).toBeNull();
  });

  it("the Түүх button and the latest-change line open the activity drawer", () => {
    const { onOpen } = renderHeader(
      head({
        latest_activity: { by: "Admin", at: "өнөөдөр 10:00", text: "Албан тушаал: A → B" },
      }),
    );
    fireEvent.click(screen.getByTitle("Үйл ажиллагааны түүх"));
    fireEvent.click(screen.getByTitle("Бүх өөрчлөлтийг харах"));
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("the latest-activity button shows the API's line", () => {
    renderHeader(
      head({
        latest_activity: { by: "Admin", at: "өнөөдөр 10:00", text: "Албан тушаал: A → B" },
      }),
    );
    expect(screen.getByTitle("Бүх өөрчлөлтийг харах").textContent).toBe(
      "Сүүлийн өөрчлөлт: Admin, өнөөдөр 10:00 — Албан тушаал: A → B",
    );
  });

  it("the next event is a link to the work section with the API's text", () => {
    renderHeader(head({ next_event: { text: "Шилжилт · 2026-12-01" } }));
    const link = screen.getByRole("link", { name: "Шилжилт · 2026-12-01" });
    expect(link.getAttribute("href")).toBe("#work");
  });

  it("the create-login button follows can.create_login and calls openLegacyEmployee", () => {
    renderHeader(head({ can: { ...head().can, create_login: true } }));
    fireEvent.click(screen.getByRole("button", { name: "Нэвтрэх эрх үүсгэх" }));
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
  });

  it("the create-login button is hidden without can.create_login", () => {
    renderHeader(head());
    expect(screen.queryByRole("button", { name: "Нэвтрэх эрх үүсгэх" })).toBeNull();
  });

  it("without a photo the given initial shows in the square", () => {
    const { container } = renderHeader(head({ photo_url: "" }));
    expect(container.querySelector("#photo-initial")?.textContent).toBe("Б");
    expect(container.querySelector("#photo-img")?.getAttribute("src")).toBeNull();
  });

  it("the photo change and remove buttons show only with the manager's right and open Django", () => {
    renderHeader(head({ photo_url: "/employees/photo/7.jpg", can: MANAGE }));
    fireEvent.click(screen.getByTitle("Зураг солих"));
    expect(openLegacyEmployee).toHaveBeenCalledWith(7);
    fireEvent.click(screen.getByTitle("Зураг устгах"));
    expect(openLegacyEmployee).toHaveBeenCalledTimes(2);
  });

  it("the photo buttons are not shown without the manager's right", () => {
    renderHeader(head({ photo_url: "/employees/photo/7.jpg" }));
    expect(screen.queryByTitle("Зураг солих")).toBeNull();
    expect(screen.queryByTitle("Зураг устгах")).toBeNull();
  });

  it("the add-photo button shows without a photo, and the photo-chosen line is kept for the manager", () => {
    const { container } = renderHeader(head({ can: MANAGE }));
    expect(screen.getByTitle("Зураг нэмэх")).toBeTruthy();
    expect(screen.queryByTitle("Зураг устгах")).toBeNull();
    expect(container.querySelector("#photo-chosen")?.textContent).toBe("");
  });

  it("with a manager's right the names are read-only boxes, and without it they are plain text", () => {
    const { rerender } = render(
      <MemoryRouter>
        <Header head={head({ can: MANAGE })} onOpenActivity={vi.fn()} />
      </MemoryRouter>,
    );
    const family = screen.getByLabelText("Эцэг/эхийн нэр") as HTMLInputElement;
    expect(family.readOnly).toBe(true);
    expect(family.value).toBe("Бат");
    expect(screen.getByLabelText("Нэр")).toBeTruthy();
    expect(screen.getByLabelText("Ажилтны код")).toBeTruthy();
    expect(screen.getByLabelText("Ажлын утас")).toBeTruthy();
    expect(screen.getByLabelText("И-мэйл")).toBeTruthy();

    rerender(
      <MemoryRouter>
        <Header head={head()} onOpenActivity={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.queryByLabelText("Эцэг/эхийн нэр")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Бат Болд");
  });

  it("the mobile fact strip shows the manager's label and a dash for a missing hire date", () => {
    const { container } = renderHeader(head({ facts: { ...head().facts, first_hire_date: "" } }));
    const strip = container.querySelector(".lg\\:hidden.grid") as HTMLElement;
    expect(strip.textContent).toContain("E-002 Сарнай Дорж");
    expect(strip.textContent).toContain("—");
  });
});
