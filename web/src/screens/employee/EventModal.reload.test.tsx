// Task 11b: the reload behaviours of the event pop-up (date change, kind change, summary refresh, race handling). The
// fixtures and the fake API are shared with EventModal.test.tsx (eventModalTestSupport.ts, which imports the api harness
// first, so fetch is stubbed before the event pop-up loads).
import type { QueryClient } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, newClient, resetFetch, resetObservers } from "../../api/testSupport";
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
const PROMOTION_SUBMIT = "/api/v1/employees/7/events/promotion";

let client: QueryClient;

const renderModal = (ui: ReactNode) => renderWithClient(client, ui);

// «Дэвшүүлэлт»: one box of its own (rank); the same date, reason, note and order block.
function promotionForm(overrides: Partial<EventForm> = {}): EventForm {
  return transferForm({
    title: "Дэвшүүлэлт",
    kinds: [
      { value: "transfer", label: "Шилжүүлэг", selected: false },
      { value: "promotion", label: "Дэвшүүлэлт", selected: true },
    ],
    fields: [
      field("effective", "Хүчинтэй огноо", "2026-01-05", { kind: "date", required: true }),
      field("reason", "Шалтгаан", "", { required: true }),
      field("rank", "Зэрэг", ""),
      field("note", "Тайлбар", ""),
    ],
    reload: true,
    ...overrides,
  });
}

// A form answer for a date change: the server shows the requested date as the effective value and keeps it as the base.
function dateAnswer(date: string, summary: string): EventForm {
  return transferForm({
    summary,
    prev_effective: date,
    fields: [
      field("effective", "Хүчинтэй огноо", date, { kind: "date", required: true }),
      field("reason", "Шалтгаан", "", { required: true }),
      field("note", "Тайлбар", ""),
    ],
  });
}

type FormBody = { values: Record<string, string>; prev_effective: string };
type Submit = { path: string; body: Record<string, unknown> };
type FormHandler = (path: string, body: FormBody) => Promise<Response>;

let formPosts: { path: string; body: FormBody }[] = [];
let submits: Submit[] = [];
let writeGate: Promise<void> | null = null;
let formHandler: FormHandler;

function defaultFormHandler(path: string): Promise<Response> {
  return Promise.resolve(jsonResponse(200, path.includes("/promotion/") ? promotionForm() : transferForm()));
}

const onForm = (path: string, body: Record<string, unknown>) => {
  const typed = body as FormBody;
  formPosts.push({ path, body: typed });
  return formHandler(path, typed);
};

// The answers of the next saves, in order; a save after the queue is empty is ok.
let submitAnswers: EventWrite[] = [];

const onSubmit = async (path: string, body: Record<string, unknown>) => {
  submits.push({ path, body });
  if (writeGate) await writeGate;
  return jsonResponse(200, submitAnswers.shift() ?? writeAnswer());
};

const kindOf = () => document.querySelector<HTMLSelectElement>("form select[name='kind']");
const dateCalls = (value: string) => formPosts.filter((post) => post.body.values.effective === value);


beforeEach(() => {
  client = newClient();
  resetFetch();
  formPosts = [];
  submits = [];
  writeGate = null;
  submitAnswers = [];
  formHandler = defaultFormHandler;
  installEventApi(onForm, onSubmit);
});

afterEach(() => {
  cleanup();
  resetObservers();
  vi.restoreAllMocks();
});

describe("EventModal (Task 11b): date change", () => {
  it("a date change calls the form route with the typed values and the base, keeps the typed reason and refills an untouched box", async () => {
    formHandler = async (_path, body) =>
      body.values.effective === "2026-02-10"
        ? jsonResponse(
            200,
            transferForm({
              fields: [
                field("effective", "Хүчинтэй огноо", "2026-02-10", { kind: "date", required: true }),
                field("reason", "Шалтгаан", "Шилжүүлсэн", { required: true }),
                field("note", "Тайлбар", "Огнооны тэмдэглэл"),
              ],
              prev_effective: "2026-02-10",
              reload: true,
            }),
          )
        : jsonResponse(200, transferForm());
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Шилжүүлсэн" } });
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-02-10" } });

    await waitFor(() => expect(boxOf("note")?.value).toBe("Огнооны тэмдэглэл"));
    expect(boxOf("reason")?.value).toBe("Шилжүүлсэн");
    expect(boxOf("effective")?.value).toBe("2026-02-10");
    // The fake answers with a fixed reason «Шилжүүлсэн» (it does not echo what was typed); the posted body is the check.
    const calls = dateCalls("2026-02-10");
    expect(calls).toHaveLength(1);
    expect(calls[0].path).toBe("/api/v1/employees/7/events/transfer/form");
    expect(calls[0].body.prev_effective).toBe("2026-01-05");
    expect(calls[0].body.values.reason).toBe("Шилжүүлсэн");
    expect(document.querySelector(".no-anim")).not.toBeNull();
  });

  it("an unreal date keeps the typed text, shows only the date's error, keeps the other values and an empty summary", async () => {
    formHandler = async (_path, body) =>
      body.values.effective === "2026-13-45"
        ? jsonResponse(
            200,
            transferForm({
              fields: [
                field("effective", "Хүчинтэй огноо", "2026-13-45", { kind: "text", required: true }),
                field("reason", "Шалтгаан", "Шилжүүлсэн", { required: true }),
                field("note", "Тайлбар", ""),
              ],
              summary: "",
              prev_effective: "2026-01-05",
              errors: { effective: ["Огноо буруу байна."] },
              reload: true,
            }),
          )
        : jsonResponse(200, transferForm({ summary: "Шилжүүлэг: 2026-01-05" }));
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Шилжүүлсэн" } });
    await screen.findByText("Шилжүүлэг: 2026-01-05");
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-13-45" } });

    await screen.findByText("Огноо буруу байна.");
    expect(boxOf("effective")?.value).toBe("2026-13-45");
    expect(boxOf("effective")?.getAttribute("aria-invalid")).toBe("true");
    expect(boxOf("reason")?.value).toBe("Шилжүүлсэн");
    expect(boxOf("reason")?.closest("label")?.textContent).not.toContain("Огноо буруу байна.");
    expect(screen.queryByText("Шилжүүлэг: 2026-01-05")).toBeNull();
    expect(document.querySelector<HTMLInputElement>("input[name='prev_effective']")?.value).toBe("2026-01-05");
  });

  it("a date change answered with a failure keeps every value and shows the load message", async () => {
    formHandler = async (_path, body) =>
      body.values.effective === "2026-02-10" ? jsonResponse(500, {}) : jsonResponse(200, transferForm());
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Шилжүүлсэн" } });
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-02-10" } });

    await screen.findByText(LOAD_FAILED);
    expect(boxOf("effective")?.value).toBe("2026-02-10");
    expect(boxOf("reason")?.value).toBe("Шилжүүлсэн");
  });

  it("a stale date reload answer is ignored when a newer one finished first", async () => {
    let releaseFirst!: () => void;
    const firstGate = new Promise<void>((resolve) => {
      releaseFirst = resolve;
    });
    let releaseSecond!: () => void;
    const secondGate = new Promise<void>((resolve) => {
      releaseSecond = resolve;
    });
    formHandler = async (_path, body) => {
      if (body.values.effective === "2026-02-10") {
        await firstGate;
        return jsonResponse(200, dateAnswer("2026-02-10", "Шилжүүлэг: A"));
      }
      if (body.values.effective === "2026-03-10") {
        await secondGate;
        return jsonResponse(200, dateAnswer("2026-03-10", "Шилжүүлэг: B"));
      }
      return jsonResponse(200, transferForm());
    };
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-02-10" } });
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-03-10" } });
    await act(async () => {
      releaseSecond();
    });
    await screen.findByText("Шилжүүлэг: B");
    await act(async () => {
      releaseFirst();
    });

    expect(boxOf("effective")?.value).toBe("2026-03-10");
    expect(screen.queryByText("Шилжүүлэг: A")).toBeNull();
    expect(screen.getByText("Шилжүүлэг: B")).not.toBeNull();
  });

  it("a box typed while a date reload is in flight keeps its typed value", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    formHandler = async (_path, body) => {
      // The date request is the only one that sends an empty note: the note change below is sent after it.
      if (body.values.effective === "2026-02-10" && body.values.note === "") {
        await gate;
        return jsonResponse(
          200,
          transferForm({
            fields: [
              field("effective", "Хүчинтэй огноо", "2026-02-10", { kind: "date", required: true }),
              field("reason", "Шалтгаан", "", { required: true }),
              field("note", "Тайлбар", "Серверийн"),
            ],
            prev_effective: "2026-02-10",
            reload: true,
          }),
        );
      }
      return jsonResponse(200, transferForm());
    };
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-02-10" } });
    await waitFor(() => expect(dateCalls("2026-02-10")).toHaveLength(1));
    fireEvent.change(boxOf("note") as HTMLInputElement, { target: { value: "Жинхэнэ" } });
    await act(async () => {
      release();
    });

    await waitFor(() => expect(dateCalls("2026-02-10")[0]).toBeDefined());
    await waitFor(() => expect(boxOf("effective")?.value).toBe("2026-02-10"));
    expect(boxOf("note")?.value).toBe("Жинхэнэ");
  });
});

describe("EventModal (Task 11b): kind change", () => {
  it("choosing another kind keeps date, reason and order values, shows the new boxes without the open animation, and a later save posts to the new type", async () => {
    const onKindChange = vi.fn();
    const onClose = vi.fn();
    formHandler = async (path, body) =>
      path.includes("/promotion/")
        ? jsonResponse(
            200,
            promotionForm({
              fields: [
                field("effective", "Хүчинтэй огноо", body.values.effective, { kind: "date", required: true }),
                field("reason", "Шалтгаан", body.values.reason ?? "", { required: true }),
                field("rank", "Зэрэг", ""),
                field("note", "Тайлбар", ""),
              ],
              order_fields: [
                field("order-number", "Тушаалын дугаар", "", { required: true }),
                field("order-date", "Тушаалын огноо", "2026-01-05", { kind: "date" }),
                field("order-summary", "Тушаалын агуулга", ""),
                field("order-issued_by", "Тушаал гаргасан", body.values["order-issued_by"] ?? ""),
              ],
            }),
          )
        : jsonResponse(200, transferForm());
    renderModal(<EventModal pk={7} type="transfer" open onClose={onClose} onKindChange={onKindChange} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Шилжүүлсэн" } });
    fireEvent.change(boxOf("order-issued_by") as HTMLInputElement, { target: { value: "Захирал" } });
    fireEvent.change(kindOf() as HTMLSelectElement, { target: { value: "promotion" } });

    await waitFor(() => expect(boxOf("rank")).not.toBeNull());
    const call = formPosts.find((post) => post.path.includes("/promotion/"));
    expect(call?.body.values).not.toHaveProperty("kind");
    expect(call?.body.values.reason).toBe("Шилжүүлсэн");
    expect(call?.body.prev_effective).toBe("2026-01-05");
    expect(kindOf()?.value).toBe("promotion");
    expect(boxOf("effective")?.value).toBe("2026-01-05");
    expect(boxOf("reason")?.value).toBe("Шилжүүлсэн");
    expect(boxOf("order-issued_by")?.value).toBe("Захирал");
    expect(document.querySelector(".no-anim")).not.toBeNull();
    expect(onKindChange).toHaveBeenCalledWith("promotion");

    fireEvent.click(saveButton());
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(submits).toHaveLength(1);
    expect(submits[0].path).toBe(PROMOTION_SUBMIT);
  });

  it("a kind change answered 404 shows the reload text, keeps every value and does not switch the type", async () => {
    const onKindChange = vi.fn();
    formHandler = async (path) =>
      path.includes("/promotion/") ? jsonResponse(404, {}) : jsonResponse(200, transferForm());
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} onKindChange={onKindChange} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Шилжүүлсэн" } });
    fireEvent.change(kindOf() as HTMLSelectElement, { target: { value: "promotion" } });

    await screen.findByText(STALE);
    expect(kindOf()?.value).toBe("transfer");
    expect(boxOf("reason")?.value).toBe("Шилжүүлсэн");
    expect(boxOf("rank")).toBeNull();
    expect(onKindChange).not.toHaveBeenCalled();
  });
});

describe("EventModal (Task 11b): a kind pick and a later date change", () => {
  it("a kind pick is not dropped by a date change made while its answer is held: the date goes to the picked type", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let promotionCalls = 0;
    const onKindChange = vi.fn();
    const onClose = vi.fn();
    formHandler = async (path, body) => {
      if (path.includes("/promotion/")) {
        promotionCalls += 1;
        // Only the first promotion request (the kind pick) is held; the date change's request is answered at once.
        if (promotionCalls === 1) await gate;
        return jsonResponse(
          200,
          promotionForm({
            fields: [
              field("effective", "Хүчинтэй огноо", body.values.effective, { kind: "date", required: true }),
              field("reason", "Шалтгаан", body.values.reason ?? "", { required: true }),
              field("rank", "Зэрэг", ""),
              field("note", "Тайлбар", ""),
            ],
            prev_effective: body.values.effective,
          }),
        );
      }
      return jsonResponse(200, transferForm());
    };
    renderModal(<EventModal pk={7} type="transfer" open onClose={onClose} onKindChange={onKindChange} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(kindOf() as HTMLSelectElement, { target: { value: "promotion" } });
    await waitFor(() => expect(promotionCalls).toBe(1));
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-02-10" } });

    await waitFor(() => expect(boxOf("rank")).not.toBeNull());
    await act(async () => {
      release();
    });

    expect(kindOf()?.value).toBe("promotion");
    expect(boxOf("effective")?.value).toBe("2026-02-10");
    expect(onKindChange).toHaveBeenCalledTimes(1);
    expect(onKindChange).toHaveBeenCalledWith("promotion");
    expect(formPosts.some((post) => post.path.includes("/promotion/") && post.body.values.effective === "2026-02-10")).toBe(
      true,
    );

    fireEvent.click(saveButton());
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(submits[0].path).toBe(PROMOTION_SUBMIT);
    expect(submits[0].body.values).toMatchObject({ effective: "2026-02-10" });
  });
});

describe("EventModal (Task 11b): a held reload and a newer summary", () => {
  it("picking back the shown type cancels a kind pick whose answer is still held", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const onKindChange = vi.fn();
    formHandler = async (path) => {
      if (path.includes("/promotion/")) {
        await gate;
        return jsonResponse(200, promotionForm());
      }
      return jsonResponse(200, transferForm());
    };
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} onKindChange={onKindChange} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(kindOf() as HTMLSelectElement, { target: { value: "promotion" } });
    await waitFor(() => expect(formPosts.some((post) => post.path.includes("/promotion/"))).toBe(true));
    fireEvent.change(kindOf() as HTMLSelectElement, { target: { value: "transfer" } });
    await act(async () => {
      release();
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });

    expect(kindOf()?.value).toBe("transfer");
    expect(boxOf("rank")).toBeNull();
    expect(onKindChange).not.toHaveBeenCalled();
  });

  it("a date reload answer does not replace a summary that was asked after the reload was sent", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    formHandler = async (_path, body) => {
      if (body.values.effective === "2026-02-10" && body.values.reason === "") {
        await gate;
        return jsonResponse(
          200,
          transferForm({
            summary: "Шилжүүлэг: RELOAD",
            prev_effective: "2026-02-10",
            fields: [
              field("effective", "Хүчинтэй огноо", "2026-02-10", { kind: "date", required: true }),
              field("reason", "Шалтгаан", "", { required: true }),
              field("note", "Тайлбар", "Серверийн"),
            ],
            reload: true,
          }),
        );
      }
      if (body.values.reason === "Жинхэнэ шалтгаан") {
        return jsonResponse(200, transferForm({ summary: "Шилжүүлэг: SUMMARY" }));
      }
      return jsonResponse(200, transferForm());
    };
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-02-10" } });
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Жинхэнэ шалтгаан" } });
    await screen.findByText("Шилжүүлэг: SUMMARY");

    await act(async () => {
      release();
    });
    await waitFor(() => expect(boxOf("note")?.value).toBe("Серверийн"));
    expect(screen.getByText("Шилжүүлэг: SUMMARY")).not.toBeNull();
    expect(screen.queryByText("Шилжүүлэг: RELOAD")).toBeNull();
    expect(boxOf("reason")?.value).toBe("Жинхэнэ шалтгаан");
  });
});

describe("EventModal (Task 11b): race guards: save, summary and reload", () => {
  it("a summary asked after an unreal-date reload was sent does not hide the date's error", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    formHandler = async (_path, body) => {
      if (body.values.effective === "2026-13-45" && body.values.reason === "") {
        await gate;
        return jsonResponse(
          200,
          transferForm({
            fields: [
              field("effective", "Хүчинтэй огноо", "2026-13-45", { kind: "text", required: true }),
              field("reason", "Шалтгаан", "", { required: true }),
              field("note", "Тайлбар", ""),
            ],
            errors: { effective: ["Огноо буруу байна."] },
            prev_effective: "2026-01-05",
            reload: true,
          }),
        );
      }
      if (body.values.reason === "Жинхэнэ шалтгаан") {
        return jsonResponse(200, transferForm({ summary: "Шилжүүлэг: S" }));
      }
      return jsonResponse(200, transferForm());
    };
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-13-45" } });
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Жинхэнэ шалтгаан" } });
    await screen.findByText("Шилжүүлэг: S");

    await act(async () => {
      release();
    });
    await screen.findByText("Огноо буруу байна.");
    expect(boxOf("effective")?.value).toBe("2026-13-45");
    expect(boxOf("reason")?.value).toBe("Жинхэнэ шалтгаан");
  });

  it("a reload sent before a save does not overwrite the base that the save's refusal reported", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const onClose = vi.fn();
    formHandler = async (_path, body) => {
      if (body.values.effective === "2026-02-10") {
        await gate;
        return jsonResponse(200, dateAnswer("2026-02-10", ""));
      }
      return jsonResponse(200, transferForm());
    };
    submitAnswers = [
      writeAnswer({ ok: false, field_errors: { reason: ["Шалтгаан заавал бөглөнө."] }, prev_effective: "2025-12-31" }),
    ];
    renderModal(<EventModal pk={7} type="transfer" open onClose={onClose} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-02-10" } });
    await waitFor(() => expect(dateCalls("2026-02-10")).toHaveLength(1));
    fireEvent.click(saveButton());
    await screen.findByText("Шалтгаан заавал бөглөнө.");

    await act(async () => {
      release();
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });
    fireEvent.click(saveButton());
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(submits[0].body.values).toMatchObject({ prev_effective: "2026-01-05" });
    expect(submits[1].body.values).toMatchObject({ prev_effective: "2025-12-31" });
  });

  it("picking back the shown type does not cancel a date change that is still in flight", async () => {
    let releaseKind!: () => void;
    const kindGate = new Promise<void>((resolve) => {
      releaseKind = resolve;
    });
    let releaseDate!: () => void;
    const dateGate = new Promise<void>((resolve) => {
      releaseDate = resolve;
    });
    formHandler = async (path, body) => {
      if (path.includes("/promotion/") && body.values.effective === "2026-02-10") {
        await dateGate;
        return jsonResponse(
          200,
          promotionForm({
            prev_effective: "2026-02-10",
            fields: [
              field("effective", "Хүчинтэй огноо", "2026-02-10", { kind: "date", required: true }),
              field("reason", "Шалтгаан", "", { required: true }),
              field("rank", "Зэрэг", ""),
              field("note", "Тайлбар", ""),
            ],
          }),
        );
      }
      if (path.includes("/promotion/")) {
        await kindGate;
        return jsonResponse(200, promotionForm());
      }
      return jsonResponse(200, transferForm());
    };
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(kindOf() as HTMLSelectElement, { target: { value: "promotion" } });
    await waitFor(() => expect(formPosts.some((post) => post.path.includes("/promotion/"))).toBe(true));
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-02-10" } });
    await waitFor(() => expect(dateCalls("2026-02-10")).toHaveLength(1));
    fireEvent.change(kindOf() as HTMLSelectElement, { target: { value: "transfer" } });

    await act(async () => {
      releaseDate();
    });
    await waitFor(() => expect(boxOf("rank")).not.toBeNull());
    await act(async () => {
      releaseKind();
    });
    expect(kindOf()?.value).toBe("promotion");
    expect(boxOf("effective")?.value).toBe("2026-02-10");
  });

  it("a change of a control with no field name sends no summary request", async () => {
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    const before = formPosts.length;
    const stray = document.createElement("input");
    (boxOf("reason") as HTMLInputElement).form?.appendChild(stray);
    fireEvent.change(stray, { target: { value: "x" } });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });
    expect(formPosts.length).toBe(before);
  });
});

describe("EventModal (Task 11b): summary refresh", () => {
  it("a change of another box updates only the summary and the when note, never a value or an error", async () => {
    formHandler = async (_path, body) =>
      body.values.reason === "Жинхэнэ шалтгаан"
        ? jsonResponse(
            200,
            transferForm({
              summary: "Шилжүүлэг: 2026-01-05",
              when: "future",
              fields: [
                field("effective", "Хүчинтэй огноо", "2026-01-05", { kind: "date", required: true }),
                field("reason", "Шалтгаан", "Серверийн", { required: true }),
                field("note", "Тайлбар", "Сервер"),
              ],
              errors: { note: ["Алдаа"] },
            }),
          )
        : jsonResponse(200, transferForm());
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(boxOf("note") as HTMLInputElement, { target: { value: "Тэмдэглэл" } });
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Жинхэнэ шалтгаан" } });

    await screen.findByText("Шилжүүлэг: 2026-01-05");
    expect(screen.getByText("Төлөвлөсөн")).not.toBeNull();
    expect(boxOf("note")?.value).toBe("Тэмдэглэл");
    expect(boxOf("reason")?.value).toBe("Жинхэнэ шалтгаан");
    expect(screen.queryByText("Алдаа")).toBeNull();
    expect(formPosts.every((post) => post.path.endsWith("/transfer/form"))).toBe(true);
    // The summary request carries the typed reason and the date box as it stood.
    const summaryCall = formPosts.find((post) => post.body.values.reason === "Жинхэнэ шалтгаан");
    expect(summaryCall?.body.values.effective).toBe("2026-01-05");
    expect(summaryCall?.body.prev_effective).toBe("2026-01-05");
  });

  it("the summary is asked on the commit of a box, not on each keystroke; an order box commit asks nothing", async () => {
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);
    await screen.findByRole("heading", { name: TITLE });
    const before = formPosts.length;
    const reason = boxOf("reason") as HTMLInputElement;

    fireEvent.input(reason, { target: { value: "А" } });
    fireEvent.input(reason, { target: { value: "Ав" } });
    fireEvent.input(reason, { target: { value: "Авт" } });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });
    expect(formPosts.length).toBe(before);

    fireEvent.change(reason, { target: { value: "Авто" } });
    await waitFor(() => expect(formPosts.length).toBe(before + 1));
    expect(formPosts[before].body.values.reason).toBe("Авто");
    expect(formPosts[before].body.values.effective).toBe("2026-01-05");

    fireEvent.change(boxOf("order-issued_by") as HTMLInputElement, { target: { value: "Захирал" } });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });
    expect(formPosts.length).toBe(before + 1);
  });
});

describe("EventModal (Task 11b): unmount", () => {
  it("an answer that arrives after unmount changes nothing and is not reported", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const onKindChange = vi.fn();
    formHandler = async (path) => {
      if (path.includes("/promotion/")) {
        await gate;
        return jsonResponse(200, promotionForm());
      }
      return jsonResponse(200, transferForm());
    };
    const { unmount } = renderModal(
      <EventModal pk={7} type="transfer" open onClose={vi.fn()} onKindChange={onKindChange} />,
    );

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(kindOf() as HTMLSelectElement, { target: { value: "promotion" } });
    await waitFor(() => expect(formPosts.some((post) => post.path.includes("/promotion/"))).toBe(true));
    unmount();
    await act(async () => {
      release();
    });

    expect(onKindChange).not.toHaveBeenCalled();
    expect(errorSpy).not.toHaveBeenCalled();
  });
});

// Task 16b: the order-level messages follow the same rules as the other errors of the answer.
const orderMessages = () => Array.from(mainDialog().querySelectorAll("h3 ~ p.bg-red-50")).map((p) => p.textContent);

describe("EventModal (Task 16b): order errors and reloads", () => {
  it("a later successful date reload clears the order errors of a refused save", async () => {
    formHandler = async (_path, body) =>
      jsonResponse(200, body.values.effective === "2026-02-10" ? dateAnswer("2026-02-10", "") : transferForm());
    submitAnswers = [
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
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-02-10" } });

    await waitFor(() => expect(dateCalls("2026-02-10")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByText("Тушаал хүчингүй.")).toBeNull());
    expect(orderMessages()).toEqual([]);
  });

  it("a late date reload answer does not overwrite the order errors of a newer refused save", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    formHandler = async (_path, body) => {
      if (body.values.effective === "2026-02-10") {
        await gate;
        return jsonResponse(200, { ...dateAnswer("2026-02-10", ""), order_errors: ["Тушаал: хуучин."] });
      }
      return jsonResponse(200, transferForm());
    };
    submitAnswers = [
      writeAnswer({
        ok: false,
        field_errors: { reason: ["Шалтгаан заавал бөглөнө."] },
        order_errors: ["Тушаал: шинэ."],
      }),
    ];
    renderModal(<EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    fireEvent.change(boxOf("effective") as HTMLInputElement, { target: { value: "2026-02-10" } });
    await waitFor(() => expect(dateCalls("2026-02-10")).toHaveLength(1));
    fireEvent.click(saveButton());
    await screen.findByText("Тушаал: шинэ.");

    await act(async () => {
      release();
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });
    expect(orderMessages()).toEqual(["Тушаал: шинэ."]);
    expect(screen.queryByText("Тушаал: хуучин.")).toBeNull();
  });
});
