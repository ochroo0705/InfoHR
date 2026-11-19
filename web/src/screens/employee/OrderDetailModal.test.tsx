// The api harness is imported first: it stubs fetch before the api modules (../../api/orderDetail) load, as HrPopup.test.tsx does.
import { fetchMock, invalidatedKeys, jsonResponse, newClient, resetFetch, resetObservers } from "../../api/testSupport";
import type { OrderDetailOut } from "../../api/orderDetail";
import type { QueryClient } from "@tanstack/react-query";
import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConfirmProvider } from "../../widgets/confirm";
import { OrderDetailModal, type OrderDetailOpeners } from "./OrderDetailModal";
import { STALE_TEXT } from "./popupGuards";

const DETAIL_PATH = "/api/v1/employees/7/orders/12/detail";
const HIRE_TITLE = "Ажилд авсан";
const CHANGE_TITLE = "Албан тушаал өөрчлөлт · 2026-03-01";
const WORD_URL = "/api/v1/employees/7/orders/12/document";
const PDF_URL = "/api/v1/employees/7/orders/12/document/pdf";
const SCAN_URL = "/api/v1/employees/7/orders/12/file";
const SIGN_IMAGE_URL = "/api/v1/employees/7/orders/12/signing-image";
const NO_ACTIONS: OrderDetailOut["actions"] = {
  word_url: "",
  pdf_url: "",
  upload: false,
  edit: false,
  cancel_event_id: null,
  cancel_order: false,
  sign: false,
};

// A registered hire order with no scan and no buttons: each test changes only what it checks.
function detail(overrides: Partial<OrderDetailOut> = {}): OrderDetailOut {
  return {
    title: HIRE_TITLE,
    employee_pk: 7,
    employee_name: "Бат Болд",
    employee_code: "E-007",
    status_chip: null,
    awaiting_note: "",
    change_rows: [
      { label: "Хүчинтэй огноо", value: "2026-01-05", before: "", after: "", arrow: false },
      { label: "Хэлтэс, албан тушаал", value: "Хүний нөөц · Мэргэжилтэн", before: "", after: "", arrow: false },
    ],
    order_heading: "Тушаал № 2026-01 / 2026",
    state_chip: { label: "Бүртгэгдсэн", tone: "rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-900" },
    order_rows: [
      { label: "Төрөл", value: "Ажилд авах", before: "", after: "", arrow: false },
      { label: "Огноо", value: "2026-01-05", before: "", after: "", arrow: false },
      { label: "Агуулга", value: "Ажилд авах тушаал", before: "", after: "", arrow: false },
      { label: "Гаргасан", value: "Захирал", before: "", after: "", arrow: false },
    ],
    scan: { note: "хавсаргаагүй", url: "" },
    signing: null,
    cancel_rows: [],
    entries: [],
    actions: NO_ACTIONS,
    ...overrides,
  };
}

let client: QueryClient;
let loadStatus = 200;
let loadOut: OrderDetailOut = detail();
let loadError: unknown = {};
let opened: OrderDetailOpeners;

function route() {
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (request.method === "GET" && path === DETAIL_PATH) {
      return loadStatus === 200 ? jsonResponse(200, loadOut) : jsonResponse(loadStatus, loadError);
    }
    throw new Error(`unexpected request ${request.method} ${path}`);
  });
}

// The parent remounts the pop-up for each open (a new key), as the sections do.
function renderModal(onClose = vi.fn()) {
  render(
    <ConfirmProvider>
      <MemoryRouter>
        <QueryClientProvider client={client}>
          <OrderDetailModal key="open-1" pk={7} orderId={12} open onClose={onClose} actions={opened} />
        </QueryClientProvider>
      </MemoryRouter>
    </ConfirmProvider>,
  );
  return onClose;
}

const mainDialog = () => screen.getAllByRole("dialog")[0];
const inDialog = () => within(mainDialog());
// The value of a row of a list: the <dd> that follows the <dt> with this label.
const valueOf = (label: string) => inDialog().getByText(label, { selector: "dt" }).nextElementSibling as HTMLElement;

function openers(): OrderDetailOpeners {
  return {
    openOrder: vi.fn(),
    edit: vi.fn(),
    upload: vi.fn(),
    cancelOrder: vi.fn(),
    cancelEvent: vi.fn(),
    sign: vi.fn(),
  };
}

beforeEach(() => {
  client = newClient();
  resetFetch();
  loadStatus = 200;
  loadOut = detail();
  loadError = {};
  opened = openers();
  route();
});

afterEach(() => {
  cleanup();
  resetObservers();
});

describe("OrderDetailModal: drawing", () => {
  it("draws a hire order", async () => {
    renderModal();

    await screen.findByRole("heading", { name: HIRE_TITLE });
    expect(inDialog().getByRole("link", { name: "Бат Болд" })).not.toBeNull();
    expect(inDialog().getByText("E-007")).not.toBeNull();
    expect(inDialog().getByRole("heading", { name: /Тушаал № 2026-01 \/ 2026/ })).not.toBeNull();
    expect(inDialog().getByText("Бүртгэгдсэн")).not.toBeNull();
    expect(valueOf("Хэлтэс, албан тушаал").textContent).toBe("Хүний нөөц · Мэргэжилтэн");
    expect(valueOf("Төрөл").textContent).toBe("Ажилд авах");
    expect(valueOf("Гаргасан").textContent).toBe("Захирал");
    expect(valueOf("Гарын үсэгтэй файл").textContent).toBe("хавсаргаагүй");
    expect(inDialog().getByRole("heading", { name: "Түүх" })).not.toBeNull();
    expect(inDialog().getByText("Бүртгэл алга")).not.toBeNull();
  });

  it("draws a change order with before/after rows", async () => {
    loadOut = detail({
      title: CHANGE_TITLE,
      status_chip: null,
      change_rows: [
        { label: "Хүчинтэй огноо", value: "2026-03-01", before: "", after: "", arrow: false },
        { label: "Албан тушаал", value: "", before: "Нярав", after: "Ахлах нярав", arrow: true },
        { label: "Шалтгаан", value: "Дэвшсэн", before: "", after: "", arrow: false },
      ],
    });
    renderModal();

    await screen.findByRole("heading", { name: CHANGE_TITLE });
    expect(valueOf("Албан тушаал").textContent).toBe("Нярав → Ахлах нярав");
    expect(valueOf("Шалтгаан").textContent).toBe("Дэвшсэн");
    expect(valueOf("Хүчинтэй огноо").textContent).toBe("2026-03-01");
  });

  it("awaiting chip and note", async () => {
    loadOut = detail({
      title: CHANGE_TITLE,
      status_chip: {
        label: "Гарын үсэг хүлээж байна",
        tone: "whitespace-nowrap rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-900 no-underline",
      },
      awaiting_note: "Тушаал гарын үсэгтэй болмогц хүчин төгөлдөр болно",
    });
    renderModal();

    await screen.findByRole("heading", { name: CHANGE_TITLE });
    expect(inDialog().getByText("Гарын үсэг хүлээж байна").className).toContain("border-amber-200");
    expect(inDialog().getByText("Тушаал гарын үсэгтэй болмогц хүчин төгөлдөр болно")).not.toBeNull();
  });

  it("cancelled order shows reason and cancelling-order link which opens that order", async () => {
    loadOut = detail({
      cancel_rows: [
        {
          label: "Цуцалсан",
          reason: "Буруу бичсэн",
          text_prefix: " · цуцлах тушаал: ",
          order_pk: 15,
          link_text: "№ 2026-09",
          suffix: "",
        },
        {
          label: "Цуцалсан тушаал",
          reason: "",
          text_prefix: "",
          order_pk: 16,
          link_text: "№ 2026-02",
          suffix: " тушаалыг цуцалсан",
        },
      ],
    });
    renderModal();

    await screen.findByRole("heading", { name: HIRE_TITLE });
    expect(valueOf("Цуцалсан").textContent).toBe("Буруу бичсэн · цуцлах тушаал: № 2026-09");
    expect(valueOf("Цуцалсан тушаал").textContent).toBe("№ 2026-02 тушаалыг цуцалсан");

    fireEvent.click(inDialog().getByRole("link", { name: "№ 2026-09" }));
    expect(opened.openOrder).toHaveBeenLastCalledWith(15, 7);
    fireEvent.click(inDialog().getByRole("link", { name: "№ 2026-02" }));
    expect(opened.openOrder).toHaveBeenLastCalledWith(16, 7);
  });

  it("name link goes to detail.employee_pk even when the pk prop differs", async () => {
    loadOut = detail({ employee_pk: 9 });
    renderModal(); // the pk prop is 7

    await screen.findByRole("heading", { name: HIRE_TITLE });
    expect(inDialog().getByRole("link", { name: "Бат Болд" }).getAttribute("href")).toBe("/employees/9/");
  });

  it("the other-order link opens that order with detail.employee_pk, not the pk prop", async () => {
    loadOut = detail({
      employee_pk: 9,
      cancel_rows: [
        { label: "Цуцалсан тушаал", reason: "", text_prefix: "", order_pk: 16, link_text: "№ 2026-02", suffix: "" },
      ],
    });
    renderModal(); // the pk prop is 7

    await screen.findByRole("heading", { name: HIRE_TITLE });
    fireEvent.click(inDialog().getByRole("link", { name: "№ 2026-02" }));
    expect(opened.openOrder).toHaveBeenLastCalledWith(16, 9);
  });

  it("scan note when the server says so", async () => {
    loadOut = detail({ scan: { note: "Зөвхөн цалингийн эрхтэй хэрэглэгч харна", url: "" } });
    const { unmount } = render(
      <ConfirmProvider>
        <MemoryRouter>
          <QueryClientProvider client={client}>
            <OrderDetailModal key="a" pk={7} orderId={12} open onClose={vi.fn()} actions={opened} />
          </QueryClientProvider>
        </MemoryRouter>
      </ConfirmProvider>,
    );
    await screen.findByRole("heading", { name: HIRE_TITLE });
    expect(valueOf("Гарын үсэгтэй файл").textContent).toBe("Зөвхөн цалингийн эрхтэй хэрэглэгч харна");
    expect(inDialog().queryByRole("link", { name: "Файл харах" })).toBeNull();
    unmount();
    cleanup();

    client = newClient();
    loadOut = detail({ scan: { note: "Файл харах", url: SCAN_URL } });
    renderModal();
    await screen.findByRole("heading", { name: HIRE_TITLE });
    const link = inDialog().getByRole("link", { name: "Файл харах" });
    expect(link.getAttribute("href")).toBe(SCAN_URL);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener");
  });

  it("signing block with picture", async () => {
    loadOut = detail({
      signing: { text: "Бат Болд · 2026-01-05 10:00 · Зурсан", image_url: SIGN_IMAGE_URL },
    });
    renderModal();

    await screen.findByRole("heading", { name: HIRE_TITLE });
    expect(valueOf("Гарын үсэг зурсан").textContent).toContain("Бат Болд · 2026-01-05 10:00 · Зурсан");
    const picture = inDialog().getByAltText("Гарын үсэг") as HTMLImageElement;
    expect(picture.getAttribute("src")).toBe(SIGN_IMAGE_URL);
    expect(picture.getAttribute("loading")).toBe("lazy");
  });

  it("the timeline draws each entry with its changes", async () => {
    loadOut = detail({
      entries: [
        {
          by: "Бат Болд",
          at: "2026-11-18 10:30",
          message: "Тушаал засагдсан",
          changes: [{ field: "Хэлтэс", old: "Хуучин", new: "Шинэ" }],
        },
      ],
    });
    renderModal();

    await screen.findByRole("heading", { name: HIRE_TITLE });
    expect(inDialog().getByText("Тушаал засагдсан")).not.toBeNull();
    expect(inDialog().getByText("2026-11-18 10:30")).not.toBeNull();
    expect(valueOf("Хэлтэс").textContent).toBe("Хуучин → Шинэ");
  });
});

describe("OrderDetailModal: footer", () => {
  it("footer buttons follow the actions flags: all off shows none", async () => {
    renderModal();

    await screen.findByRole("heading", { name: HIRE_TITLE });
    expect(inDialog().queryByRole("button", { name: "Файл хавсаргах" })).toBeNull();
    expect(inDialog().queryByRole("button", { name: "Засах" })).toBeNull();
    expect(inDialog().queryByRole("button", { name: "Цуцлах" })).toBeNull();
    expect(inDialog().queryByRole("button", { name: "Тушаал цуцлах" })).toBeNull();
    expect(inDialog().queryByRole("button", { name: "Гарын үсэг зурах" })).toBeNull();
    expect(inDialog().queryByRole("link", { name: "Word татах" })).toBeNull();
    expect(inDialog().queryByRole("link", { name: "PDF татах" })).toBeNull();
  });

  it("the attach button shows for the upload flag and calls upload with the order", async () => {
    loadOut = detail({ actions: { ...NO_ACTIONS, upload: true } });
    renderModal();

    await screen.findByRole("heading", { name: HIRE_TITLE });
    fireEvent.click(inDialog().getByRole("button", { name: "Файл хавсаргах" }));
    expect(opened.upload).toHaveBeenCalledWith(12);
  });

  it("the edit button shows for the edit flag and calls edit with the order", async () => {
    loadOut = detail({ actions: { ...NO_ACTIONS, edit: true } });
    renderModal();

    await screen.findByRole("heading", { name: HIRE_TITLE });
    fireEvent.click(inDialog().getByRole("button", { name: "Засах" }));
    expect(opened.edit).toHaveBeenCalledWith(12);
  });

  it("the cancel button shows for cancel_event_id and cancels that event", async () => {
    loadOut = detail({ actions: { ...NO_ACTIONS, cancel_event_id: 30 } });
    renderModal();

    await screen.findByRole("heading", { name: HIRE_TITLE });
    fireEvent.click(inDialog().getByRole("button", { name: "Цуцлах" }));
    expect(opened.cancelEvent).toHaveBeenCalledWith(30);
    expect(inDialog().queryByRole("button", { name: "Тушаал цуцлах" })).toBeNull();
  });

  it("the order cancel button shows for the cancel_order flag and cancels the order", async () => {
    loadOut = detail({ actions: { ...NO_ACTIONS, cancel_order: true } });
    renderModal();

    await screen.findByRole("heading", { name: HIRE_TITLE });
    fireEvent.click(inDialog().getByRole("button", { name: "Тушаал цуцлах" }));
    expect(opened.cancelOrder).toHaveBeenCalledWith(12);
  });

  it("the sign button shows for the sign flag and calls sign with the order", async () => {
    loadOut = detail({ actions: { ...NO_ACTIONS, sign: true } });
    renderModal();

    await screen.findByRole("heading", { name: HIRE_TITLE });
    fireEvent.click(inDialog().getByRole("button", { name: "Гарын үсэг зурах" }));
    expect(opened.sign).toHaveBeenCalledWith(12);
  });

  it("Word and PDF are links to the API paths", async () => {
    loadOut = detail({ actions: { ...NO_ACTIONS, word_url: WORD_URL, pdf_url: PDF_URL } });
    renderModal();

    await screen.findByRole("heading", { name: HIRE_TITLE });
    expect(inDialog().getByRole("link", { name: "Word татах" }).getAttribute("href")).toBe(WORD_URL);
    expect(inDialog().getByRole("link", { name: "PDF татах" }).getAttribute("href")).toBe(PDF_URL);
  });
});

describe("OrderDetailModal: links and failures", () => {
  it("employee name links to the employee page", async () => {
    renderModal();

    await screen.findByRole("heading", { name: HIRE_TITLE });
    expect(inDialog().getByRole("link", { name: "Бат Болд" }).getAttribute("href")).toBe("/employees/7/");
  });

  it("404 refreshes work and activity", async () => {
    loadStatus = 404;
    loadError = { field_errors: {}, form_errors: [] };
    const invalidate = vi.spyOn(client, "invalidateQueries");
    renderModal();

    await screen.findByText(STALE_TEXT);
    expect(inDialog().queryByRole("heading", { name: "Түүх" })).toBeNull();
    const keys = invalidatedKeys(invalidate);
    expect(keys).toContainEqual({ queryKey: ["employee", 7, "work"], exact: true });
    expect(keys).toContainEqual({ queryKey: ["employee", 7, "activity"], exact: true });
  });
});
