// The api harness is imported first: it stubs fetch before the api modules (./client, ../../api/orders, ../../api/events)
// load, as EventModal.test.tsx does.
import { fetchMock, invalidatedKeys, jsonResponse, newClient, resetFetch, resetObservers } from "../../api/testSupport";
import type { QueryClient } from "@tanstack/react-query";
import { QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { components } from "../../api/schema";
import { isUnsaved } from "../../lib/unsaved";
import { ConfirmProvider } from "../../widgets/confirm";
import { DIRTY_CONFIRM_MESSAGE } from "../../widgets/modalLogic";
import { HrPopup, type HrPopupTarget } from "./HrPopup";

type PopupOut = components["schemas"]["HrPopupOut"];
type PopupField = PopupOut["fields"][number];
type ResultOut = components["schemas"]["HrPopupResultOut"];

const STALE = "Хуудсыг дахин ачаалж, дахин оролдоно уу.";
const FORBIDDEN = "Хандах эрх байхгүй.";
const EDIT_PATH = "/api/v1/employees/7/orders/12/edit";
const UPLOAD_PATH = "/api/v1/employees/7/orders/12/upload";
const CANCEL_PATH = "/api/v1/employees/7/events/30/cancel";
const ORDER_CANCEL_PATH = "/api/v1/employees/7/orders/12/cancel";

function field(name: string, label: string, value: string, extra: Partial<PopupField> = {}): PopupField {
  return {
    name,
    label,
    required: false,
    kind: "text",
    value,
    checked: false,
    placeholder: "",
    choice: "",
    combo: false,
    choices: [],
    help: "",
    max_length: null,
    errors: [],
    ...extra,
  };
}

// «Тушаал засах»: the number is the server's suggestion, the date, the summary and the issuer.
function editForm(number = "2026-06"): PopupOut {
  return {
    title: "Тушаал: Ажилд авах",
    hint: "Дугаарыг автоматаар санал болгосон, шаардлагатай бол өөрчилнө үү.",
    submit_label: "Хадгалах",
    multipart: false,
    fields: [
      field("number", "Тушаалын дугаар", number, { required: true }),
      field("date", "Тушаалын огноо", "2026-11-19", { kind: "date", required: true }),
      field("summary", "Агуулга", ""),
      field("issued_by", "Тушаал гаргасан", ""),
    ],
  };
}

// «Скан оруулах»: one file box, multipart.
function uploadForm(): PopupOut {
  return {
    title: "Скан оруулах",
    hint: "",
    submit_label: "Хадгалах",
    multipart: true,
    fields: [field("file", "Гарын үсэгтэй файл", "", { kind: "file" })],
  };
}

// «Цуцлах»: the reason, and the cancel order number only for a signed order.
function cancelForm(signed = false): PopupOut {
  return {
    title: "Цуцлах: Ажилд авах (2026-01-05)",
    hint: "Өөрчлөлт цуцлагдсан гэж түүхэнд үлдэнэ.",
    submit_label: "Цуцлах",
    multipart: false,
    fields: [
      field("reason", "Шалтгаан", "", { kind: "textarea", required: true }),
      ...(signed ? [field("cancel_order_no", "Цуцлах тушаалын дугаар", "", { required: true })] : []),
    ],
  };
}

function result(overrides: Partial<ResultOut> = {}): ResultOut {
  return { ok: true, field_errors: {}, form_errors: [], ...overrides };
}

let client: QueryClient;
let loadStatus = 200;
let loadOut: PopupOut = editForm();
let loadError: unknown = {};
let saveStatus = 200;
let saveAnswers: ResultOut[] = [];
let writeGate: Promise<void> | null = null;
let suggestOut = { number: "2026-07", date: "2026-11-19" };
let posted: { path: string; body: unknown }[] = [];

// The multipart body is not read back: a jsdom File does not stream through a Request, so the request never resolves.
// The file part is checked where it is appended to the FormData (the check orders.test.tsx makes). The spy records the
// appends of the current test; it still calls through.
const appendSpy = vi.spyOn(FormData.prototype, "append");
function uploadBody() {
  const parts = appendSpy.mock.calls.filter((call) => call[0] === "file");
  const file = parts[0]?.[1] as File | undefined;
  return { hasFile: parts.length > 0, name: file?.name ?? null };
}

function route() {
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (request.method === "GET" && path.endsWith("/order-suggest")) return jsonResponse(200, suggestOut);
    if (request.method === "GET") {
      return loadStatus === 200 ? jsonResponse(200, loadOut) : jsonResponse(loadStatus, loadError);
    }
    if (request.method === "POST") {
      // The upload sends a multipart body (its file part is read back), the others JSON.
      const body = path.endsWith("/upload") ? uploadBody() : await request.json();
      posted.push({ path, body });
      if (writeGate) await writeGate;
      if (saveStatus !== 200) return jsonResponse(saveStatus, { field_errors: {}, form_errors: [] });
      return jsonResponse(200, saveAnswers.shift() ?? result());
    }
    throw new Error(`unexpected request ${request.method} ${path}`);
  });
}

function renderPopup(target: HrPopupTarget, onClose = vi.fn()) {
  render(
    <ConfirmProvider>
      <QueryClientProvider client={client}>
        {/* The parent remounts the pop-up for each open (a new key), as the sections do. */}
        <HrPopup key="open-1" pk={7} target={target} open onClose={onClose} />
      </QueryClientProvider>
    </ConfirmProvider>,
  );
  return onClose;
}

const mainDialog = () => screen.getAllByRole("dialog")[0];
const boxOf = (name: string) => document.querySelector<HTMLInputElement>(`form [name='${name}']`);
// The file input is named by its box's label (the server's field label), inside the pop-up.
const fileInput = () => within(mainDialog()).getByLabelText(/Гарын үсэгтэй файл/) as HTMLInputElement;
const button = (label: string) => within(mainDialog()).getByRole("button", { name: label });
const EDIT: HrPopupTarget = { kind: "order-edit", orderId: 12 };
const UPLOAD: HrPopupTarget = { kind: "order-upload", orderId: 12 };
const CANCEL: HrPopupTarget = { kind: "event-cancel", eventId: 30 };
const ORDER_CANCEL: HrPopupTarget = { kind: "order-cancel", orderId: 12 };

beforeEach(() => {
  client = newClient();
  resetFetch();
  appendSpy.mockClear();
  loadStatus = 200;
  loadOut = editForm();
  loadError = {};
  saveStatus = 200;
  saveAnswers = [];
  writeGate = null;
  suggestOut = { number: "2026-07", date: "2026-11-19" };
  posted = [];
  route();
});

afterEach(() => {
  cleanup();
  resetObservers();
});

describe("HrPopup: order edit", () => {
  it("edit shows the suggested number, and «Санал болгох» fills the number box from the server", async () => {
    renderPopup(EDIT);

    await screen.findByRole("heading", { name: "Тушаал: Ажилд авах" });
    expect(boxOf("number")?.value).toBe("2026-06");
    expect(screen.getByText(loadOut.hint)).not.toBeNull();

    fireEvent.click(within(mainDialog()).getByRole("button", { name: "Санал болгох" }));
    await waitFor(() => expect(boxOf("number")?.value).toBe("2026-07"));
  });

  it("edit refused shows field errors under their boxes and keeps the typed values", async () => {
    saveAnswers = [result({ ok: false, field_errors: { number: ["Дугаар давхцсан."] } })];
    renderPopup(EDIT);

    await screen.findByRole("heading", { name: "Тушаал: Ажилд авах" });
    fireEvent.change(boxOf("summary") as HTMLInputElement, { target: { value: "Шинэ агуулга" } });
    fireEvent.click(button("Хадгалах"));

    await screen.findByText("Дугаар давхцсан.");
    const numberLabel = boxOf("number")?.closest("label") as HTMLElement;
    expect(numberLabel.textContent).toContain("Дугаар давхцсан.");
    expect(boxOf("number")?.getAttribute("aria-invalid")).toBe("true");
    expect(boxOf("summary")?.value).toBe("Шинэ агуулга");
    expect(boxOf("number")?.value).toBe("2026-06");
    expect(mainDialog()).not.toBeNull();
  });

  it("a double submit sends one request", async () => {
    let release!: () => void;
    writeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const onClose = renderPopup(EDIT);

    await screen.findByRole("heading", { name: "Тушаал: Ажилд авах" });
    const form = boxOf("summary")?.form as HTMLFormElement;
    fireEvent.click(button("Хадгалах"));
    fireEvent.submit(form);
    await waitFor(() => expect(posted).toHaveLength(1));

    await act(async () => {
      release();
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(posted).toHaveLength(1);
    expect(posted[0].path).toBe(EDIT_PATH);
  });

  it("ok closes and refreshes the employee's header, work and activity", async () => {
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const onClose = renderPopup(EDIT);

    await screen.findByRole("heading", { name: "Тушаал: Ажилд авах" });
    fireEvent.click(button("Хадгалах"));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    const keys = invalidatedKeys(invalidate);
    expect(keys).toContainEqual({ queryKey: ["employee", 7], exact: true });
    expect(keys).toContainEqual({ queryKey: ["employee", 7, "work"], exact: true });
    expect(keys).toContainEqual({ queryKey: ["employee", 7, "activity"], exact: true });
  });

  it("404 on save shows the reload text, keeps the typed values and refreshes the page data", async () => {
    saveStatus = 404;
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const onClose = renderPopup(EDIT);

    await screen.findByRole("heading", { name: "Тушаал: Ажилд авах" });
    fireEvent.change(boxOf("summary") as HTMLInputElement, { target: { value: "Шинэ" } });
    fireEvent.click(button("Хадгалах"));

    await screen.findByText(STALE);
    expect(boxOf("summary")?.value).toBe("Шинэ");
    expect(onClose).not.toHaveBeenCalled();
    const keys = invalidatedKeys(invalidate);
    expect(keys).toContainEqual({ queryKey: ["employee", 7, "work"], exact: true });
    expect(keys).toContainEqual({ queryKey: ["employee", 7, "activity"], exact: true });
  });

  it("a changed pop-up is unsaved: Escape asks first, and cancel keeps it open", async () => {
    const onClose = renderPopup(EDIT);

    await screen.findByRole("heading", { name: "Тушаал: Ажилд авах" });
    fireEvent.change(boxOf("summary") as HTMLInputElement, { target: { value: "Шинэ" } });
    expect(isUnsaved("hrpopup:order-edit")).toBe(true);

    fireEvent.keyDown(document, { key: "Escape" });
    const ask = await screen.findByRole("alertdialog");
    expect(ask.textContent).toContain(DIRTY_CONFIRM_MESSAGE);
    fireEvent.click(within(ask).getByRole("button", { name: "Болих" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("HrPopup: order upload", () => {
  it("upload refused shows the server's message under the file box and stays open with the chosen file", async () => {
    loadOut = uploadForm();
    saveAnswers = [result({ ok: false, field_errors: { file: ["Файлын төрөл буруу."] } })];
    const onClose = renderPopup(UPLOAD);

    await screen.findByRole("heading", { name: "Скан оруулах" });
    const file = new File(["%PDF"], "scan.exe", { type: "application/x-msdownload" });
    fireEvent.change(fileInput(), { target: { files: [file] } });
    fireEvent.click(button("Хадгалах"));

    await screen.findByText("Файлын төрөл буруу.");
    expect(fileInput().closest("label")?.textContent).toContain("Файлын төрөл буруу.");
    expect(fileInput().getAttribute("aria-invalid")).toBe("true");
    expect(document.querySelector("[data-file-name]")?.textContent).toBe("scan.exe");
    expect(posted).toEqual([{ path: UPLOAD_PATH, body: { hasFile: true, name: "scan.exe" } }]);
    expect(onClose).not.toHaveBeenCalled();
    expect(mainDialog()).not.toBeNull();
  });
});

describe("HrPopup: upload with no file", () => {
  it("a click with no file posts without a file part and shows the server's required message under the file box", async () => {
    loadOut = uploadForm();
    saveAnswers = [result({ ok: false, field_errors: { file: ["Файл заавал хавсаргана."] } })];
    const onClose = renderPopup(UPLOAD);

    await screen.findByRole("heading", { name: "Скан оруулах" });
    fireEvent.click(button("Хадгалах"));

    await screen.findByText("Файл заавал хавсаргана.");
    expect(posted).toEqual([{ path: UPLOAD_PATH, body: { hasFile: false, name: null } }]);
    expect(onClose).not.toHaveBeenCalled();
    expect(mainDialog()).not.toBeNull();
  });
});

describe("HrPopup: event cancel", () => {
  it("event-cancel without a reason shows the server's error under the reason box", async () => {
    loadOut = cancelForm();
    saveAnswers = [result({ ok: false, field_errors: { reason: ["Шалтгаан заавал бөглөнө."] } })];
    renderPopup(CANCEL);

    await screen.findByRole("heading", { name: "Цуцлах: Ажилд авах (2026-01-05)" });
    fireEvent.click(button("Цуцлах"));

    await screen.findByText("Шалтгаан заавал бөглөнө.");
    expect(boxOf("reason")?.closest("label")?.textContent).toContain("Шалтгаан заавал бөглөнө.");
    expect(posted).toEqual([{ path: CANCEL_PATH, body: { values: { reason: "" } } }]);
  });

  it("a signed order's event shows the cancel_order_no box", async () => {
    loadOut = cancelForm(true);
    renderPopup(CANCEL);

    await screen.findByRole("heading", { name: "Цуцлах: Ажилд авах (2026-01-05)" });
    expect(boxOf("cancel_order_no")).not.toBeNull();
    expect(boxOf("reason")?.tagName).toBe("TEXTAREA");
  });

  it("an unsigned event shows no cancel_order_no box", async () => {
    loadOut = cancelForm(false);
    renderPopup(CANCEL);

    await screen.findByRole("heading", { name: "Цуцлах: Ажилд авах (2026-01-05)" });
    expect(boxOf("cancel_order_no")).toBeNull();
  });
});

describe("HrPopup: order cancel", () => {
  it("order-cancel loads the cancel form and posts reason", async () => {
    loadOut = cancelForm();
    renderPopup(ORDER_CANCEL);

    await screen.findByRole("heading", { name: "Цуцлах: Ажилд авах (2026-01-05)" });
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Буруу бичсэн" } });
    fireEvent.click(button("Цуцлах"));

    await waitFor(() =>
      expect(posted).toEqual([{ path: ORDER_CANCEL_PATH, body: { values: { reason: "Буруу бичсэн" } } }]),
    );
  });

  it("order-cancel refusal keeps the text and shows the error", async () => {
    loadOut = cancelForm();
    saveAnswers = [result({ ok: false, field_errors: { reason: ["Шалтгаан заавал бөглөнө."] } })];
    const onClose = renderPopup(ORDER_CANCEL);

    await screen.findByRole("heading", { name: "Цуцлах: Ажилд авах (2026-01-05)" });
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Хүнд" } });
    fireEvent.click(button("Цуцлах"));

    await screen.findByText("Шалтгаан заавал бөглөнө.");
    expect(boxOf("reason")?.closest("label")?.textContent).toContain("Шалтгаан заавал бөглөнө.");
    expect(boxOf("reason")?.value).toBe("Хүнд");
    expect(onClose).not.toHaveBeenCalled();
    expect(posted).toEqual([{ path: ORDER_CANCEL_PATH, body: { values: { reason: "Хүнд" } } }]);
  });
});

describe("HrPopup: load failures", () => {
  it("a 403 on load shows the server's message and no form", async () => {
    loadStatus = 403;
    loadError = { field_errors: {}, form_errors: [FORBIDDEN], code: "forbidden" };
    const onClose = renderPopup(EDIT);

    await screen.findByText(FORBIDDEN);
    expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull();
    fireEvent.click(screen.getByText("Хаах", { selector: "button:not([data-modal-x])" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("a 404 on load shows the reload text and refreshes the page data", async () => {
    loadStatus = 404;
    loadError = { field_errors: {}, form_errors: [] };
    const invalidate = vi.spyOn(client, "invalidateQueries");
    renderPopup(CANCEL);

    await screen.findByText(STALE);
    expect(screen.queryByRole("button", { name: "Цуцлах" })).toBeNull();
    await waitFor(() =>
      expect(invalidatedKeys(invalidate)).toContainEqual({ queryKey: ["employee", 7, "work"], exact: true }),
    );
  });
});
