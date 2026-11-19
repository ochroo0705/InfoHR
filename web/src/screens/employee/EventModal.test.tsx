// The api harness stubs fetch when it loads, so it is imported before the event pop-up (which imports the api client).
// The fixtures and the fake API are in eventModalTestSupport.ts, which imports the harness first.
import type { QueryClient } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchMock, jsonResponse, newClient, resetFetch, resetObservers } from "../../api/testSupport";
import { isUnsaved } from "../../lib/unsaved";
import { DIRTY_CONFIRM_MESSAGE } from "../../widgets/modalLogic";
import {
  boxOf,
  field,
  installEventApi,
  LOAD_FAILED,
  mainDialog,
  renderWithClient,
  saveButton,
  STALE,
  transferForm,
  writeAnswer,
  type EventForm,
  type EventWrite,
} from "./eventModalTestSupport";
import { EventModal } from "./EventModal";

const TITLE = "Ажлын байр солих";

// Task 16b: the order block's heading and order-level messages, and the red box on top.
const ORDER_NOTE = "дугаар заавал, огноо хоосон бол өөрчлөлтийн огноо";
const orderHeading = () => mainDialog().querySelector("h3") as HTMLElement | null;
const orderBlock = () => orderHeading()?.parentElement as HTMLElement;
const topMessages = () =>
  Array.from(mainDialog().querySelectorAll("form > p.bg-red-50")).map((p) => p.textContent);

let client: QueryClient;

const renderModal = (ui: ReactNode) => renderWithClient(client, ui);

type Posted = { path: string; body: Record<string, unknown> };
let posted: Posted[] = [];
let formGets: string[] = [];
let writeAnswers: EventWrite[] = [];
let formStatus = 200;
let formBody: unknown = null;
let submitStatus = 200;
let submitBody: unknown = null;
let writeGate: Promise<void> | null = null;
let eventForm: EventForm = transferForm();

const SUBMIT_PATH = "/api/v1/employees/7/events/transfer";

const onForm = async (path: string) => {
  formGets.push(path);
  if (formStatus !== 200) return jsonResponse(formStatus, formBody ?? {});
  return jsonResponse(200, eventForm);
};

const onSubmit = async (path: string, body: Record<string, unknown>) => {
  posted.push({ path, body });
  if (writeGate) await writeGate;
  if (submitStatus !== 200) return jsonResponse(submitStatus, submitBody ?? {});
  return jsonResponse(200, writeAnswers.shift() ?? writeAnswer());
};


beforeEach(() => {
  client = newClient();
  resetFetch();
  posted = [];
  formGets = [];
  writeAnswers = [];
  formStatus = 200;
  formBody = null;
  submitStatus = 200;
  submitBody = null;
  writeGate = null;
  eventForm = transferForm();
  installEventApi(onForm, onSubmit);
});

afterEach(() => {
  cleanup();
  resetObservers();
});

describe("EventModal (Task 11a): shell and form", () => {
  it("renders the title, the kind list, the boxes and the buttons", async () => {
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: "Ажлын байр солих" });
    expect(formGets).toHaveLength(1);
    const kind = document.querySelector<HTMLSelectElement>("form select[name='kind']");
    expect(kind).not.toBeNull();
    expect(kind?.value).toBe("transfer");
    expect(Array.from(kind?.options ?? []).map((option) => option.textContent)).toEqual(["Шилжүүлэг", "Дэвшүүлэлт"]);
    expect(boxOf("effective")).not.toBeNull();
    expect(boxOf("reason")).not.toBeNull();
    expect(boxOf("note")).not.toBeNull();
    expect(boxOf("order-number")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Болих" })).not.toBeNull();
    expect(saveButton()).not.toBeNull();
  });

  it("draws no kind list when the form has no kinds", async () => {
    eventForm = transferForm({ kinds: [] });
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: "Ажлын байр солих" });
    expect(document.querySelector("form select[name='kind']")).toBeNull();
  });

  it("draws the death notice and the past-date note from the server", async () => {
    eventForm = transferForm({ death_unset: true, when: "past" });
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: "Ажлын байр солих" });
    expect(screen.getByText("Өнгөрсөн огноо — түүх засагдана")).not.toBeNull();
    expect(screen.getByText(/«Нас барсан» шалтгаан/)).not.toBeNull();
  });

  it("the form starts with the reload animation off when the server says reload", async () => {
    eventForm = transferForm({ reload: true });
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: "Ажлын байр солих" });
    expect(document.querySelector(".no-anim")).not.toBeNull();
  });

  it("nothing is loaded while the pop-up is closed", () => {
    renderModal(<EventModal pk={7} type="transfer" open={false} onClose={vi.fn()} />);

    expect(formGets).toHaveLength(0);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a refused save moves the focus to the first box with an error", async () => {
    writeAnswers = [writeAnswer({ ok: false, field_errors: { reason: ["Шалтгаан заавал бөглөнө."] } })];
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: "Ажлын байр солих" });
    fireEvent.click(saveButton());

    await screen.findByText("Шалтгаан заавал бөглөнө.");
    expect(boxOf("reason")?.getAttribute("aria-invalid")).toBe("true");
    await waitFor(() => expect(document.activeElement).toBe(boxOf("reason")));
  });
});

describe("EventModal (Task 11a): save and refusal", () => {
  it("a refused save keeps every typed value, shows order errors under the order boxes and form errors on top", async () => {
    writeAnswers = [
      writeAnswer({
        ok: false,
        field_errors: { "order-number": ["Тушаалын дугаар заавал бөглөнө."] },
        form_errors: ["Бүртгэл хадгалагдсангүй."],
        summary: "Шилжүүлэг: 2026-01-05",
        when: "past",
      }),
    ];
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: "Ажлын байр солих" });
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Шилжүүлсэн" } });
    fireEvent.change(boxOf("note") as HTMLInputElement, { target: { value: "Тэмдэглэл" } });
    fireEvent.change(boxOf("order-issued_by") as HTMLInputElement, { target: { value: "Захирал" } });
    fireEvent.click(saveButton());

    await screen.findByText("Бүртгэл хадгалагдсангүй.");
    const topError = mainDialog().querySelector(".bg-red-50");
    expect(topError?.textContent).toContain("Бүртгэл хадгалагдсангүй.");
    const orderLabel = boxOf("order-number")?.closest("label") as HTMLElement;
    expect(within(orderLabel).getByText("Тушаалын дугаар заавал бөглөнө.")).not.toBeNull();
    expect(boxOf("order-number")?.getAttribute("aria-invalid")).toBe("true");
    expect(boxOf("reason")?.value).toBe("Шилжүүлсэн");
    expect(boxOf("note")?.value).toBe("Тэмдэглэл");
    expect(boxOf("order-issued_by")?.value).toBe("Захирал");
    expect(boxOf("effective")?.value).toBe("2026-01-05");
    expect(screen.getByText("Шилжүүлэг: 2026-01-05")).not.toBeNull();
    expect(screen.getByText("Өнгөрсөн огноо — түүх засагдана")).not.toBeNull();
  });

  it("a save sends the typed values and the held prev_effective inside values, and closes on ok", async () => {
    const onClose = vi.fn();
    renderModal(<EventModal pk={7} type="transfer" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Ажлын байр солих" });
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Шилжүүлсэн" } });
    fireEvent.click(saveButton());

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(posted).toHaveLength(1);
    expect(posted[0].path).toBe(SUBMIT_PATH);
    expect(posted[0].body).toEqual({
      values: {
        effective: "2026-01-05",
        reason: "Шилжүүлсэн",
        note: "",
        "order-number": "",
        "order-date": "2026-01-05",
        "order-summary": "",
        "order-issued_by": "",
        prev_effective: "2026-01-05",
      },
    });
    expect(Object.keys(posted[0].body)).toEqual(["values"]);
  });

  it("the last real date the server reported is the prev_effective of the next save", async () => {
    writeAnswers = [writeAnswer({ ok: false, field_errors: { reason: ["Шалтгаан заавал бөглөнө."] }, prev_effective: "2025-12-31" })];
    const onClose = vi.fn();
    renderModal(<EventModal pk={7} type="transfer" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Ажлын байр солих" });
    fireEvent.click(saveButton());
    await screen.findByText("Шалтгаан заавал бөглөнө.");
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Шилжүүлсэн" } });
    fireEvent.click(saveButton());

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect((posted[1].body.values as Record<string, unknown>).prev_effective).toBe("2025-12-31");
  });

  it("a double click on Хадгалах sends one request", async () => {
    let release!: () => void;
    writeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const onClose = vi.fn();
    renderModal(<EventModal pk={7} type="transfer" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Ажлын байр солих" });
    const form = boxOf("reason")?.form as HTMLFormElement;
    fireEvent.click(saveButton());
    fireEvent.click(saveButton());
    fireEvent.submit(form);
    await waitFor(() => expect(posted).toHaveLength(1));

    await act(async () => {
      release();
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(posted).toHaveLength(1);
  });

  it("the save button is disabled while the request is pending", async () => {
    let release!: () => void;
    writeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: "Ажлын байр солих" });
    fireEvent.click(saveButton());
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(saveButton()).toHaveProperty("disabled", true);

    await act(async () => {
      release();
    });
  });
});

describe("EventModal (Task 11a): unsaved guard", () => {
  it("a dirty pop-up is unsaved and Escape asks before closing", async () => {
    const onClose = vi.fn();
    renderModal(<EventModal pk={7} type="transfer" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Ажлын байр солих" });
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Шилжүүлсэн" } });
    expect(isUnsaved("event:transfer")).toBe(true);

    fireEvent.keyDown(document, { key: "Escape" });
    const ask = await screen.findByRole("alertdialog");
    expect(ask.textContent).toContain(DIRTY_CONFIRM_MESSAGE);
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(within(ask).getByRole("button", { name: "Болих" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(onClose).not.toHaveBeenCalled();
  });

  it("«Болих» asks first when the pop-up is dirty", async () => {
    const onClose = vi.fn();
    renderModal(<EventModal pk={7} type="transfer" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Ажлын байр солих" });
    fireEvent.change(boxOf("note") as HTMLInputElement, { target: { value: "Тэмдэглэл" } });
    fireEvent.click(screen.getByRole("button", { name: "Болих" }));

    const ask = await screen.findByRole("alertdialog");
    expect(ask.textContent).toContain(DIRTY_CONFIRM_MESSAGE);
    fireEvent.click(within(ask).getByRole("button", { name: "Хаах" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });
});

describe("EventModal (Task 11a): stale page and refused rights", () => {
  it("404 on save shows the reload text, keeps the typed values and refreshes the work and activity data", async () => {
    submitStatus = 404;
    const onClose = vi.fn();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    renderModal(<EventModal pk={7} type="transfer" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Ажлын байр солих" });
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Шилжүүлсэн" } });
    fireEvent.click(saveButton());

    await screen.findByText(STALE);
    expect(onClose).not.toHaveBeenCalled();
    expect(boxOf("reason")?.value).toBe("Шилжүүлсэн");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7], exact: true });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7, "work"], exact: true });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7, "activity"], exact: true });
  });

  it("404 on load shows the reload text and refreshes the page data, with no form", async () => {
    formStatus = 404;
    const invalidate = vi.spyOn(client, "invalidateQueries");
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByText(STALE);
    expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7, "work"], exact: true });
  });

  it("403 on load shows the server's form errors and no form", async () => {
    formStatus = 403;
    formBody = { code: "forbidden", field_errors: {}, form_errors: ["Энэ төрлийн бүртгэл хийх эрх байхгүй."] };
    const onClose = vi.fn();
    renderModal(<EventModal pk={7} type="transfer" open onClose={onClose} />);

    await screen.findByText("Энэ төрлийн бүртгэл хийх эрх байхгүй.");
    expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull();
    expect(formGets).toHaveLength(1);
    fireEvent.click(screen.getByText("Хаах", { selector: "button:not([data-modal-x])" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("403 on load with no form errors shows the load message", async () => {
    formStatus = 403;
    formBody = { code: "forbidden", field_errors: {}, form_errors: [] };
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByText(LOAD_FAILED);
    expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull();
  });
});

describe("EventModal (Task 16b): order block heading and order errors", () => {
  it("draws the heading «Тушаал · <note>» when the form has order boxes", async () => {
    eventForm = transferForm({ order_note: ORDER_NOTE });
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    expect(orderHeading()?.textContent).toBe("Тушаал · " + ORDER_NOTE);
  });

  it("draws no order heading when the form has no order boxes", async () => {
    eventForm = transferForm({ order_fields: [], order_note: ORDER_NOTE });
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    expect(orderHeading()).toBeNull();
  });

  it("a loaded form's order errors are drawn inside the order block, not in the top box", async () => {
    eventForm = transferForm({ order_errors: ["Тушаал дутуу байна."] });
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByText("Тушаал дутуу байна.");
    expect(within(orderBlock()).getByText("Тушаал дутуу байна.")).not.toBeNull();
    expect(topMessages()).toEqual([]);
  });

  it("a refused save shows its order errors inside the order block and not in the top box", async () => {
    writeAnswers = [
      writeAnswer({
        ok: false,
        field_errors: { reason: ["Шалтгаан заавал бөглөнө."] },
        order_errors: ["Тушаал хүчингүй."],
      }),
    ];
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.click(saveButton());

    await screen.findByText("Тушаал хүчингүй.");
    expect(within(orderBlock()).getByText("Тушаал хүчингүй.")).not.toBeNull();
    expect(topMessages()).toEqual([]);
  });
});

// The «Санал болгох» request: it asks with the ORDER date box's value, as order_suggest.js does (never the effective date).
describe("EventModal (Task 16b fix): suggest reads the order date box", () => {
  const suggestUrls: string[] = [];
  const suggestSearch = () => suggestUrls;

  function installSuggestApi() {
    fetchMock.mockImplementation(async (input: unknown) => {
      const request = input as Request;
      const url = new URL(request.url);
      if (request.method === "GET" && url.pathname === "/api/v1/employees/order-suggest") {
        suggestUrls.push(url.search);
        return jsonResponse(200, { number: "А-1", date: "" });
      }
      if (request.method === "POST" && /\/form$/.test(url.pathname)) return jsonResponse(200, eventForm);
      throw new Error(`unexpected request ${request.method} ${url.pathname}`);
    });
  }

  beforeEach(() => {
    suggestUrls.length = 0;
  });

  it("with the order date box empty, the suggest request sends no date even when an effective date is typed", async () => {
    eventForm = transferForm({
      order_fields: [
        field("order-number", "Тушаалын дугаар", "", { required: true }),
        field("order-date", "Тушаалын огноо", "", { kind: "date" }),
        field("order-summary", "Тушаалын агуулга", ""),
        field("order-issued_by", "Тушаал гаргасан", ""),
      ],
    });
    installSuggestApi();
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-02-10" } });
    fireEvent.click(within(mainDialog()).getByRole("button", { name: "Санал болгох" }));

    await waitFor(() => expect(suggestSearch()).toHaveLength(1));
    expect(suggestSearch()[0]).toBe("");
  });

  it("with the order date box filled, the suggest request carries that order date, never the effective date", async () => {
    installSuggestApi();
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-02-10" } });
    fireEvent.change(boxOf("order-date") as HTMLInputElement, { target: { value: "2026-03-01" } });
    fireEvent.click(within(mainDialog()).getByRole("button", { name: "Санал болгох" }));

    await waitFor(() => expect(suggestSearch()).toHaveLength(1));
    expect(new URLSearchParams(suggestSearch()[0]).get("date")).toBe("2026-03-01");
  });
});
