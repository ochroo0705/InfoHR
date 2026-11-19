import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { EmployeeHeadOut } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";
import { photoSrc } from "../../lib/photo";
import { Header } from "./Header";
import { PageFormElement, PageFormProvider } from "./PageForm";
import { SaveBar } from "./SaveBar";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

// The header calls the pop-up openers from the provider. The test renders the header alone, so the hook returns stubs.
const popups = vi.hoisted(() => ({
  openEvent: vi.fn(),
  openEventCancel: vi.fn(),
  openOrderEdit: vi.fn(),
  openOrderUpload: vi.fn(),
  openOrderHistory: vi.fn(),
}));
vi.mock("./EmployeePopups", () => ({ useEmployeePopups: () => popups }));

// fetch and Request are stubbed before the api client is imported (openapi-fetch captures fetch when it is created), as in
// PageForm.test.tsx. createImageBitmap is not in jsdom: it is a mock that rejects unless a test sets it to resolve.
const h = vi.hoisted(() => {
  const fetchMock = vi.fn();
  const bitmapMock = vi.fn((_file: unknown): Promise<unknown> => Promise.reject(new Error("no decoder")));
  const NativeRequest = globalThis.Request;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => fetchMock(input, init));
  vi.stubGlobal("createImageBitmap", (file: unknown) => bitmapMock(file));
  vi.stubGlobal(
    "Request",
    class extends NativeRequest {
      constructor(input: RequestInfo | URL, init?: RequestInit) {
        super(typeof input === "string" ? new URL(input, window.location.origin) : input, init);
      }
    },
  );
  return { fetchMock, bitmapMock };
});
const fetchMock = h.fetchMock;
const bitmapMock = h.bitmapMock;

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

function field(overrides: Record<string, unknown>) {
  return {
    checked: false,
    choice: "",
    choices: [],
    combo: false,
    errors: [],
    help: "",
    kind: "text",
    label: "",
    max_length: null,
    name: "",
    placeholder: "—",
    required: false,
    value: "",
    ...overrides,
  };
}

// The header's boxes as the page form sends them (the names and labels of EmployeeForm).
const PAGE_FORM = {
  loaded: "L1",
  si_loaded: "",
  fields: [
    field({ name: "family_name", label: "Эцэг/эхийн нэр", value: "Бат", required: true }),
    field({ name: "given_name", label: "Нэр", value: "Болд", required: true }),
    field({ name: "code", label: "Ажилтны код", value: "E-001" }),
    field({ name: "work_phone", label: "Ажлын утас", value: "7700-1234", required: true }),
    field({ name: "email", label: "И-мэйл", value: "" }),
  ],
};

const OK_RESULT = { ok: true, field_errors: {}, form_errors: [], conflicts: {}, loaded: "L2", si_loaded: "", tab: "" };

let appendSpy: { mock: { calls: unknown[][] }; mockRestore: () => void };
let saveAnswers: { status: number; body: unknown }[];

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function urlOf(input: unknown): string {
  return typeof input === "string" ? input : (input as Request).url;
}

function callsTo(suffix: string): number {
  return fetchMock.mock.calls.filter((call) => new URL(urlOf(call[0])).pathname.endsWith(suffix)).length;
}

function routeFetch() {
  fetchMock.mockImplementation(async (input: unknown) => {
    const path = new URL(urlOf(input)).pathname;
    if (path.endsWith("/page-form")) return jsonResponse(200, PAGE_FORM);
    if (path.endsWith("/save")) {
      const next = saveAnswers.shift();
      if (!next) throw new Error("no save answer queued");
      return jsonResponse(next.status, next.body);
    }
    throw new Error(`unexpected request ${path}`);
  });
}

// The header, the save bar and the page form element, as EmployeePage renders them. `pk` is the employee's.
function renderHeader(h: EmployeeHeadOut, onOpenActivity = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PageFormProvider pk={7} enabled={h.can.manage} section="work">
          <PageFormElement />
          <Header head={h} onOpenActivity={onOpenActivity} />
          <SaveBar />
        </PageFormProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { onOpen: onOpenActivity, ...utils };
}

function box(label: string): HTMLInputElement {
  return screen.getByLabelText(label) as HTMLInputElement;
}

// Waits until the page form has loaded and the header's boxes are editable.
async function loaded() {
  await waitFor(() => expect(box("Ажлын утас").readOnly).toBe(false));
}

// «Хадгалах» submits #emp-form with form="emp-form" (a browser does this). jsdom does not follow that attribute for a
// submit button, so the test submits the form the same way the button would.
function saveNow() {
  fireEvent.submit(document.getElementById("emp-form") as HTMLFormElement);
}

function bar(): HTMLElement {
  return document.getElementById("save-bar") as HTMLElement;
}

function photoInput(container: HTMLElement): HTMLInputElement {
  return container.querySelector('input[type="file"][name="photo"]') as HTMLInputElement;
}

function clearBox(container: HTMLElement): HTMLInputElement {
  return container.querySelector('input[name="photo_clear"]') as HTMLInputElement;
}

beforeEach(() => {
  fetchMock.mockReset();
  bitmapMock.mockClear();
  appendSpy = vi.spyOn(FormData.prototype, "append");
  saveAnswers = [];
  URL.revokeObjectURL = vi.fn(() => undefined);
  routeFetch();
});

afterEach(() => {
  cleanup();
  appendSpy.mockRestore();
  vi.clearAllMocks();
  delete (URL as { createObjectURL?: unknown }).createObjectURL;
  delete (URL as { revokeObjectURL?: unknown }).revokeObjectURL;
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

  it("the event menu item opens the event pop-up for its type, not the legacy page", () => {
    renderHeader(head({ event_menu: [{ value: "transfer", label: "Албан тушаал солих" }] }));
    fireEvent.click(screen.getByText("Өөрчлөлт бүртгэх ▾"));
    fireEvent.click(screen.getByRole("button", { name: "Албан тушаал солих" }));
    expect(popups.openEvent).toHaveBeenCalledWith("transfer");
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("the event menu closes after a pick, as the Django menu does", () => {
    const { container } = renderHeader(head({ event_menu: [{ value: "transfer", label: "Албан тушаал солих" }] }));
    const details = container.querySelector("details");
    if (!details) throw new Error("no event menu");
    details.setAttribute("open", "");
    fireEvent.click(screen.getByRole("button", { name: "Албан тушаал солих" }));
    expect(details.hasAttribute("open")).toBe(false);
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

  it("the create-login button follows can.create_login and opens the create-login pop-up, not the legacy page", () => {
    renderHeader(head({ can: { ...head().can, create_login: true } }));
    fireEvent.click(screen.getByRole("button", { name: "Нэвтрэх эрх үүсгэх" }));
    expect(screen.getByRole("dialog").textContent).toContain("Нэвтрэх эрх үүсгэх");
    expect(screen.getByText("Нэвтрэх нэр", { exact: false })).toBeTruthy();
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("the create-login pop-up closes with Болих and posts nothing", async () => {
    renderHeader(head({ can: { ...head().can, create_login: true } }));
    fireEvent.click(screen.getByRole("button", { name: "Нэвтрэх эрх үүсгэх" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Болих" }));
    // The shell plays its exit first; the dialog is removed when that ends.
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(fetchMock).not.toHaveBeenCalled();
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

  it("the add-photo control shows without a photo for the manager, and the photo-chosen line is empty", () => {
    const { container } = renderHeader(head({ can: MANAGE }));
    expect(screen.getByTitle("Зураг нэмэх")).toBeTruthy();
    expect(screen.queryByTitle("Зураг устгах")).toBeNull();
    expect(container.querySelector("#photo-chosen")?.textContent).toBe("");
  });

  it("the photo controls are not shown without the manager's right", () => {
    renderHeader(head({ photo_url: "/employees/photo/7.jpg" }));
    expect(screen.queryByTitle("Зураг солих")).toBeNull();
    expect(screen.queryByTitle("Зураг устгах")).toBeNull();
    expect(document.getElementById("photo-chosen")).toBeNull();
  });

  it("without a manager's right the names are plain text and no page form is requested", () => {
    renderHeader(head());
    expect(screen.queryByLabelText("Эцэг/эхийн нэр")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Бат Болд");
    expect(callsTo("/page-form")).toBe(0);
  });

  it("with a manager's right the names and the contact line are boxes holding the page form's values", async () => {
    renderHeader(head({ can: MANAGE }));
    expect(box("Эцэг/эхийн нэр").value).toBe("Бат");
    await loaded();
    expect(box("Эцэг/эхийн нэр").readOnly).toBe(false);
    expect(box("Эцэг/эхийн нэр").value).toBe("Бат");
    expect(box("Нэр").value).toBe("Болд");
    expect(box("Ажилтны код").value).toBe("E-001");
    expect(box("Ажлын утас").value).toBe("7700-1234");
    expect(box("И-мэйл").value).toBe("");
    expect(callsTo("/page-form")).toBe(1);
    // The boxes join the empty page form by attribute (Django's form="emp-form"); the form has no children.
    expect(box("Ажлын утас").getAttribute("form")).toBe("emp-form");
    expect(document.getElementById("emp-form")?.childElementCount).toBe(0);
  });

  it("typing in the work phone box shows the save bar", async () => {
    renderHeader(head({ can: MANAGE }));
    await loaded();
    expect(bar().classList.contains("hidden")).toBe(true);
    fireEvent.change(box("Ажлын утас"), { target: { value: "7700-5555" } });
    expect(bar().classList.contains("flex")).toBe(true);
    expect(box("Ажлын утас").value).toBe("7700-5555");
  });

  it("a save error shows under its box, and the box is marked aria-invalid", async () => {
    renderHeader(head({ can: MANAGE }));
    await loaded();
    fireEvent.change(box("Ажлын утас"), { target: { value: "bad" } });
    saveAnswers.push({
      status: 200,
      body: { ok: false, field_errors: { work_phone: ["Утасны дугаар буруу"] }, form_errors: [], conflicts: {}, loaded: "L1", si_loaded: "", tab: "work" },
    });

    saveNow();

    expect(await screen.findByText("Утасны дугаар буруу")).toBeTruthy();
    expect(box("Ажлын утас").getAttribute("aria-invalid")).toBe("true");
    expect(bar().classList.contains("flex")).toBe(true);
  });

  it("a clash shows the two choices under the box, with the saved value as theirs", async () => {
    const { container } = renderHeader(head({ can: MANAGE }));
    await loaded();
    fireEvent.change(box("Ажлын утас"), { target: { value: "7700-5555" } });
    saveAnswers.push({
      status: 200,
      body: { ok: false, field_errors: {}, form_errors: [], conflicts: { work_phone: "7700-9999" }, loaded: "L1", si_loaded: "", tab: "work" },
    });

    saveNow();

    await waitFor(() => expect(container.querySelector('input[name="resolve-work_phone"]')).not.toBeNull());
    const mine = container.querySelector('input[name="resolve-work_phone"][value="mine"]') as HTMLInputElement;
    const theirs = container.querySelector('input[name="resolve-work_phone"][value="theirs"]') as HTMLInputElement;
    expect(mine.checked).toBe(true);
    expect(theirs.parentElement?.textContent).toContain("7700-9999");
    fireEvent.click(theirs);
    expect(theirs.checked).toBe(true);
  });

  it("choosing a file shows the save note, previews the picture and sets the photo for the save", async () => {
    const { container } = renderHeader(head({ can: MANAGE, photo_url: "/employees/photo/7.jpg" }));
    await loaded();
    const file = new File(["x"], "face.jpg", { type: "image/jpeg" });
    URL.createObjectURL = vi.fn(() => "blob:face");

    fireEvent.change(photoInput(container), { target: { files: [file] } });

    expect(container.querySelector("#photo-chosen")?.textContent).toBe("Хадгалахад солигдоно");
    await waitFor(() => expect(container.querySelector("#photo-img")?.getAttribute("src")).toBe("blob:face"));
    expect(container.querySelector("#photo-img")?.hasAttribute("srcset")).toBe(false);
    expect(bar().classList.contains("flex")).toBe(true);

    saveAnswers.push({ status: 200, body: OK_RESULT });
    saveNow();
    await waitFor(() => expect(bar().classList.contains("hidden")).toBe(true));
    expect(appendSpy.mock.calls.some(([key, value]) => key === "photo" && value === file)).toBe(true);
    // The ok save takes the picked file away: the preview resets to the stored photo, and its object URL is revoked.
    await waitFor(() => expect(container.querySelector("#photo-img")?.getAttribute("src")).toBe(photoSrc("/employees/photo/7.jpg")));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:face");
  });

  it("the required boxes carry the page form's required flag, and the e-mail box is an e-mail input", async () => {
    renderHeader(head({ can: MANAGE }));
    await loaded();
    expect(box("Эцэг/эхийн нэр").required).toBe(true);
    expect(box("Нэр").required).toBe(true);
    expect(box("Ажлын утас").required).toBe(true);
    expect(box("Ажилтны код").required).toBe(false);
    expect(box("И-мэйл").type).toBe("email");
  });

  it("a second pick replaces the shown preview, and the first pick's object URL is revoked", async () => {
    const { container } = renderHeader(head({ can: MANAGE }));
    await loaded();
    URL.createObjectURL = vi.fn((file: File) => `blob:${file.name}`);

    fireEvent.change(photoInput(container), { target: { files: [new File(["1"], "one.png", { type: "image/png" })] } });
    await waitFor(() => expect(container.querySelector("#photo-img")?.getAttribute("src")).toBe("blob:one.png"));
    fireEvent.change(photoInput(container), { target: { files: [new File(["2"], "two.png", { type: "image/png" })] } });

    await waitFor(() => expect(container.querySelector("#photo-img")?.getAttribute("src")).toBe("blob:two.png"));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:one.png");
    expect(URL.revokeObjectURL).not.toHaveBeenCalledWith("blob:two.png");
  });

  it("two quick picks: the older pick's late preview does not show over the newer one, and its object URL is revoked", async () => {
    const { container } = renderHeader(head({ can: MANAGE }));
    await loaded();
    URL.createObjectURL = vi.fn((file: File) => `blob:${file.name}`);
    // The first pick's decoder answers late (a rejection: its preview is the object URL fallback).
    let failFirst: (reason: Error) => void = () => undefined;
    bitmapMock.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          failFirst = reject;
        }),
    );

    fireEvent.change(photoInput(container), { target: { files: [new File(["1"], "old.png", { type: "image/png" })] } });
    fireEvent.change(photoInput(container), { target: { files: [new File(["2"], "new.png", { type: "image/png" })] } });
    await waitFor(() => expect(container.querySelector("#photo-img")?.getAttribute("src")).toBe("blob:new.png"));

    failFirst(new Error("late"));

    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:old.png"));
    expect(container.querySelector("#photo-img")?.getAttribute("src")).toBe("blob:new.png");
  });

  it("the shown object URL is revoked when the header unmounts", async () => {
    const { container, unmount } = renderHeader(head({ can: MANAGE }));
    await loaded();
    URL.createObjectURL = vi.fn(() => "blob:kept");

    fireEvent.change(photoInput(container), { target: { files: [new File(["x"], "k.png", { type: "image/png" })] } });
    await waitFor(() => expect(container.querySelector("#photo-img")?.getAttribute("src")).toBe("blob:kept"));
    unmount();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:kept");
  });

  it("a picked file with no decoder shows its object URL and drops the initial", async () => {
    const { container } = renderHeader(head({ can: MANAGE }));
    await loaded();
    URL.createObjectURL = vi.fn(() => "blob:new");
    fireEvent.change(photoInput(container), { target: { files: [new File(["x"], "a.png", { type: "image/png" })] } });
    await waitFor(() => expect(container.querySelector("#photo-img")?.getAttribute("src")).toBe("blob:new"));
    expect(container.querySelector("#photo-initial")).toBeNull();
    expect(bitmapMock).toHaveBeenCalledTimes(1);
  });

  it("the × box dims the photo and shows the removal note, and unticking undoes both", async () => {
    const { container } = renderHeader(head({ can: MANAGE, photo_url: "/employees/photo/7.jpg" }));
    await loaded();
    const img = () => container.querySelector("#photo-img") as HTMLImageElement;

    fireEvent.click(clearBox(container));

    expect(img().className).toContain("opacity-30");
    expect(container.querySelector("#photo-chosen")?.textContent).toBe("Хадгалахад устгагдана");
    expect(bar().classList.contains("flex")).toBe(true);

    fireEvent.click(clearBox(container));

    expect(img().className).not.toContain("opacity-30");
    expect(container.querySelector("#photo-chosen")?.textContent).toBe("");
  });

  it("a photo error from the save sits under the photo control", async () => {
    const { container } = renderHeader(head({ can: MANAGE }));
    await loaded();
    fireEvent.change(box("Ажлын утас"), { target: { value: "7700-5555" } });
    saveAnswers.push({
      status: 200,
      body: { ok: false, field_errors: { photo: ["Зургийн хэмжээ хэт том байна"] }, form_errors: [], conflicts: {}, loaded: "L1", si_loaded: "", tab: "work" },
    });

    saveNow();

    const message = await screen.findByText("Зургийн хэмжээ хэт том байна");
    expect(message.className).toBe("text-xs text-red-600");
    expect(message.previousElementSibling?.id).toBe("photo-chosen");
    expect(container.querySelector("#photo-chosen")?.parentElement?.contains(message)).toBe(true);
  });

  it("a form submit saves once, even when it is sent twice", async () => {
    renderHeader(head({ can: MANAGE }));
    await loaded();
    fireEvent.change(box("Ажлын утас"), { target: { value: "7700-5555" } });
    saveAnswers.push({ status: 200, body: OK_RESULT });
    const form = document.getElementById("emp-form") as HTMLFormElement;

    fireEvent.submit(form);
    fireEvent.submit(form);

    await waitFor(() => expect(bar().classList.contains("hidden")).toBe(true));
    expect(callsTo("/save")).toBe(1);
  });

  it("a header button that is not a submit does not save the page", async () => {
    const { onOpen } = renderHeader(head({ can: MANAGE }));
    await loaded();
    fireEvent.change(box("Ажлын утас"), { target: { value: "7700-5555" } });

    fireEvent.click(screen.getByTitle("Үйл ажиллагааны түүх"));

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(callsTo("/save")).toBe(0);
  });

  it("the mobile fact strip shows the manager's label and a dash for a missing hire date", () => {
    const { container } = renderHeader(head({ facts: { ...head().facts, first_hire_date: "" } }));
    const strip = container.querySelector(".lg\\:hidden.grid") as HTMLElement;
    expect(strip.textContent).toContain("E-002 Сарнай Дорж");
    expect(strip.textContent).toContain("—");
  });
});
