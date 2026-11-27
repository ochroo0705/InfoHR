import { StrictMode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReportSelection } from "../useReportSelection";
import { createState } from "../selectionState";
import { SelectionChecklistModal } from "./SelectionChecklistModal";

// The API client is replaced by a stub that answers by path; the real api/reports functions run.
const h = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn() }));

vi.mock("../../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const KEY = "staff";
const FORM_PATH = "/api/v1/reports/{key}/selected/checklist/form";
const START_PATH = "/api/v1/reports/{key}/selected/checklist";
const PICKED = { query: "q=a", ids: ["1", "2", "3"], all: false };
const ALL = { query: "q=a", ids: [], all: true };

const FORM_PICKED = {
  all: false,
  anchor_max: "2026-12-31",
  anchor_min: "2020-01-01",
  count: 3,
  reasons: [
    { value: "Гэрээ дууссан", label: "Гэрээ дууссан" },
    { value: "Өөрийн хүсэлт", label: "Өөрийн хүсэлтээр" },
  ],
  template_missing: false,
  today: "2026-11-27",
};

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}
function refused(status: number, formErrors: string[]) {
  return { data: undefined, error: { form_errors: formErrors, field_errors: {} }, response: { ok: false, status } };
}

function makeClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

// A selection whose body is the given picked/all body (the real hook is not needed for the pop-up).
function selectionOf(body: { query: string; ids: string[]; all: boolean }): ReportSelection {
  return {
    state: { ...createState(), all: body.all },
    setVisibleIds: vi.fn(),
    toggle: vi.fn(),
    pickRow: vi.fn(),
    pickVisible: vi.fn(),
    pickAll: vi.fn(),
    cancel: vi.fn(),
    body: vi.fn(() => body),
  };
}

// Answers the form read and the start by path; `form` and `start` are the answers (or a function of the call).
function answerPaths(form: unknown, start: unknown = ok({ counts: {}, dropped: 0, rows: [] })) {
  h.post.mockImplementation(async (path: string) => {
    if (path === FORM_PATH) return form;
    if (path === START_PATH) return start;
    return refused(404, []);
  });
}

function renderPop(
  body: { query: string; ids: string[]; all: boolean },
  form: unknown = ok(FORM_PICKED),
  start?: unknown,
) {
  answerPaths(form, start);
  const client = makeClient();
  const onClose = vi.fn();
  const onRefused = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <SelectionChecklistModal
        reportKey={KEY}
        query="?q=a"
        selection={selectionOf(body)}
        onClose={onClose}
        onRefused={onRefused}
      />
    </QueryClientProvider>,
  );
  return { onClose, onRefused, client };
}

function dialog(): HTMLElement {
  return screen.getByRole("dialog");
}

function reasonSelect(): HTMLSelectElement {
  return screen.getByLabelText("Шалтгаан") as HTMLSelectElement;
}

function dateBox(): HTMLInputElement {
  return screen.getByLabelText(/Хугацааны эхлэл/) as HTMLInputElement;
}

function startButton(): HTMLButtonElement {
  return within(dialog()).getByRole("button", { name: "Эхлүүлэх" }) as HTMLButtonElement;
}

async function waitForForm() {
  await screen.findByRole("button", { name: "Эхлүүлэх" });
}

function startCalls() {
  return h.post.mock.calls.filter(([path]) => path === START_PATH);
}

beforeEach(() => {
  h.post.mockReset();
  h.get.mockReset();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("SelectionChecklistModal", () => {
  it("form text counts the picked people from the form answer", async () => {
    renderPop(PICKED);
    await waitForForm();

    expect(screen.getByRole("heading", { name: "Ажлаас гарах жагсаалт эхлүүлэх" })).toBeTruthy();
    expect(
      screen.getByText(
        "Сонгосон 3 хүнд «Ажлаас гарах» жагсаалт нэмнэ. Ажлаас аль хэдийн гарсан хүнд, эсвэл нээлттэй жагсаалттай хүнд шинээр жагсаалт нэмэгдэхгүй. Хүн бүрт тусад нь шалгана; нэг нь алдаа гарсан ч бусад нь эхэлнэ.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("Хугацааны эхлэл *")).toBeTruthy();
    expect(screen.getByText("Шалтгаан")).toBeTruthy();
  });

  it("all-mode takes its count from the form answer, not the selection", async () => {
    renderPop(ALL, ok({ ...FORM_PICKED, all: true, count: 57 }));
    await waitForForm();

    expect(
      screen.getByText(
        "Тайлангийн бүх 57 хүнд «Ажлаас гарах» жагсаалт нэмнэ. Ажлаас аль хэдийн гарсан хүнд, эсвэл нээлттэй жагсаалттай хүнд шинээр жагсаалт нэмэгдэхгүй. Хүн бүрт тусад нь шалгана; нэг нь алдаа гарсан ч бусад нь эхэлнэ.",
      ),
    ).toBeTruthy();
  });

  it("the reason select lists the empty reason first, then the template reasons", async () => {
    renderPop(PICKED);
    await waitForForm();

    const labels = Array.from(reasonSelect().options).map((o) => [o.value, o.textContent]);
    expect(labels).toEqual([
      ["", "Шалтгаангүй (үндсэн загвар)"],
      ["Гэрээ дууссан", "Гэрээ дууссан"],
      ["Өөрийн хүсэлт", "Өөрийн хүсэлтээр"],
    ]);
    expect(dateBox().value).toBe("2026-11-27");
  });

  it("a picked reason fills the select", async () => {
    renderPop(PICKED);
    await waitForForm();

    fireEvent.change(reasonSelect(), { target: { value: "Өөрийн хүсэлт" } });
    expect(reasonSelect().value).toBe("Өөрийн хүсэлт");
  });

  it("shows the amber note only when the template is missing", async () => {
    renderPop(PICKED);
    await waitForForm();
    expect(screen.queryByText("Энэ төрөлд идэвхтэй загвар алга. Жагсаалт эхлэхгүй.")).toBeNull();
    cleanup();

    renderPop(PICKED, ok({ ...FORM_PICKED, template_missing: true }));
    await waitForForm();
    expect(screen.getByText("Энэ төрөлд идэвхтэй загвар алга. Жагсаалт эхлэхгүй.")).toBeTruthy();
  });

  it("submit posts the picked body with the reason and the anchor day", async () => {
    const { onClose } = renderPop(PICKED, ok(FORM_PICKED), ok({ counts: { started: 3 }, dropped: 0, rows: [] }));
    await waitForForm();

    fireEvent.change(reasonSelect(), { target: { value: "Гэрээ дууссан" } });
    fireEvent.change(dateBox(), { target: { value: "2026-11-20" } });
    fireEvent.click(startButton());

    await waitFor(() => expect(startCalls()).toHaveLength(1));
    expect(startCalls()[0][1]).toEqual({
      params: { path: { key: KEY } },
      body: { query: "q=a", ids: ["1", "2", "3"], all: false, reason: "Гэрээ дууссан", anchor_day: "2026-11-20" },
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a double submit posts once", async () => {
    // The button is disabled after the first click, so the second submit reaches the form directly and the ref guard
    // is what stops it.
    renderPop(PICKED, ok(FORM_PICKED), ok({ counts: { started: 3 }, dropped: 0, rows: [] }));
    await waitForForm();

    const form = dialog().querySelector("form") as HTMLFormElement;
    fireEvent.submit(form);
    fireEvent.submit(form);

    await screen.findByText(/^Эхэлсэн 3 /);
    expect(startCalls()).toHaveLength(1);
  });

  it("a successful start does not re-read the form, so a refusal afterwards cannot take the result away", async () => {
    const onRefused = vi.fn();
    let formReads = 0;
    h.post.mockImplementation(async (path: string) => {
      if (path === FORM_PATH) {
        formReads += 1;
        // The first read is answered; any later read would be refused.
        return formReads === 1 ? ok(FORM_PICKED) : refused(400, ["Сонгосон хүн алга."]);
      }
      if (path === START_PATH) return ok({ counts: { started: 3 }, dropped: 0, rows: [] });
      return refused(404, []);
    });
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <SelectionChecklistModal
          reportKey={KEY}
          query="?q=a"
          selection={selectionOf(PICKED)}
          onClose={vi.fn()}
          onRefused={onRefused}
        />
      </QueryClientProvider>,
    );
    await waitForForm();

    fireEvent.click(startButton());

    expect(await screen.findByRole("heading", { name: "Ажлаас гарах жагсаалт эхлүүлэх: үр дүн" })).toBeTruthy();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(formReads).toBe(1);
    expect(onRefused).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Ажлаас гарах жагсаалт эхлүүлэх: үр дүн" })).toBeTruthy();
  });

  it("reads the form once after a successful start (no re-read on invalidation)", async () => {
    renderPop(PICKED, ok(FORM_PICKED), ok({ counts: { started: 3 }, dropped: 0, rows: [] }));
    await waitForForm();

    fireEvent.click(startButton());

    await screen.findByRole("heading", { name: "Ажлаас гарах жагсаалт эхлүүлэх: үр дүн" });
    expect(h.post.mock.calls.filter(([path]) => path === FORM_PATH)).toHaveLength(1);
  });

  it("the form is read once under StrictMode", async () => {
    answerPaths(ok(FORM_PICKED));
    render(
      <StrictMode>
        <QueryClientProvider client={makeClient()}>
          <SelectionChecklistModal
            reportKey={KEY}
            query="?q=a"
            selection={selectionOf(PICKED)}
            onClose={vi.fn()}
            onRefused={vi.fn()}
          />
        </QueryClientProvider>
      </StrictMode>,
    );
    await waitForForm();

    expect(h.post.mock.calls.filter(([path]) => path === FORM_PATH)).toHaveLength(1);
  });

  it("Escape closes a pop-up with nothing typed, as the shared Modal does", async () => {
    const { onClose } = renderPop(PICKED);
    await waitForForm();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("the red error box and the amber note carry their live-region roles", async () => {
    renderPop(PICKED, ok({ ...FORM_PICKED, template_missing: true }), refused(400, ["Огноо буруу байна."]));
    await waitForForm();
    expect(screen.getByRole("status").textContent).toBe("Энэ төрөлд идэвхтэй загвар алга. Жагсаалт эхлэхгүй.");

    fireEvent.click(startButton());

    expect((await screen.findByRole("alert")).textContent).toBe("Огноо буруу байна.");
  });

  it("the reason and the anchor day are reached by their labels", async () => {
    renderPop(PICKED);
    await waitForForm();

    expect(screen.getByLabelText("Шалтгаан").tagName).toBe("SELECT");
    expect((screen.getByLabelText(/Хугацааны эхлэл/) as HTMLInputElement).value).toBe("2026-11-27");
  });

  it("a refused start keeps the form and shows every form error", async () => {
    const { onClose } = renderPop(
      PICKED,
      ok(FORM_PICKED),
      refused(400, ["Огноо буруу байна.", "Хугацаа хэт урт байна."]),
    );
    await waitForForm();

    fireEvent.click(startButton());

    expect(await screen.findByText("Огноо буруу байна.")).toBeTruthy();
    expect(screen.getByText("Хугацаа хэт урт байна.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Эхлүүлэх" })).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a refused start with no form error shows the fallback text", async () => {
    renderPop(PICKED, ok(FORM_PICKED), refused(400, []));
    await waitForForm();

    fireEvent.click(startButton());

    expect(await screen.findByText("Татаж чадсангүй. Дахин оролдоно уу.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Эхлүүлэх" })).toBeTruthy();
  });

  it("success shows the counts line and one row per person, and «Хаах» closes", async () => {
    const { onClose } = renderPop(
      PICKED,
      ok(FORM_PICKED),
      ok({
        counts: { started: 2, already_open: 1, no_template: 0 },
        dropped: 0,
        rows: [
          { code: "E001", name: "Бат Дорж", outcome: "Эхэлсэн" },
          { code: "E002", name: "Сараа", outcome: "Нээлттэй байсан" },
        ],
      }),
    );
    await waitForForm();

    fireEvent.click(startButton());

    expect(await screen.findByRole("heading", { name: "Ажлаас гарах жагсаалт эхлүүлэх: үр дүн" })).toBeTruthy();
    expect(screen.getByText("Эхэлсэн 2 · Нээлттэй байсан 1 · Загвар алга 0")).toBeTruthy();
    expect(screen.getByText("E001 Бат Дорж")).toBeTruthy();
    expect(screen.getByText("Нээлттэй байсан")).toBeTruthy();
    expect(screen.queryByText(/Харах эрх алга/)).toBeNull();
    expect(screen.queryByText(/Ажлаас гарсан/)).toBeNull();
    expect(screen.queryByText(/Алдаа гарлаа/)).toBeNull();
    expect(screen.queryByText(/харагдахгүй тул орсонгүй/)).toBeNull();

    // The shared Modal's ✕ is also named «Хаах», so the button is found by its text.
    fireEvent.click(screen.getByText("Хаах"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("result shows the non-zero counts only, and the empty list text", async () => {
    renderPop(
      PICKED,
      ok(FORM_PICKED),
      ok({
        counts: { started: 0, already_open: 0, no_template: 0, not_allowed: 1, left: 2, error: 1 },
        dropped: 0,
        rows: [],
      }),
    );
    await waitForForm();

    fireEvent.click(startButton());

    expect(
      await screen.findByText("Эхэлсэн 0 · Нээлттэй байсан 0 · Загвар алга 0 · Харах эрх алга 1 · Ажлаас гарсан 2 · Алдаа гарлаа 1"),
    ).toBeTruthy();
    expect(screen.getByText("Хүн алга.")).toBeTruthy();
  });

  it("dropped people get the amber note", async () => {
    renderPop(
      PICKED,
      ok(FORM_PICKED),
      ok({ counts: { started: 1 }, dropped: 2, rows: [{ code: "E003", name: "Номин", outcome: "Эхэлсэн" }] }),
    );
    await waitForForm();

    fireEvent.click(startButton());

    expect(await screen.findByText("2 хүн энэ тайланд харагдахгүй тул орсонгүй.")).toBeTruthy();
  });

  it("a successful start invalidates the report queries once", async () => {
    const { client } = renderPop(
      PICKED,
      ok(FORM_PICKED),
      ok({ counts: { started: 3 }, dropped: 0, rows: [] }),
    );
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await waitForForm();

    fireEvent.click(startButton());

    await screen.findByRole("heading", { name: "Ажлаас гарах жагсаалт эхлүүлэх: үр дүн" });
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["reports"] });
  });

  it("«Болих» closes at once", async () => {
    const { onClose } = renderPop(PICKED);
    await waitForForm();

    fireEvent.click(within(dialog()).getByRole("button", { name: "Болих" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(h.post).not.toHaveBeenCalledWith(START_PATH, expect.anything());
  });

  it("a refused form read calls onRefused with the message and shows no pop-up", async () => {
    const { onClose, onRefused } = renderPop(PICKED, refused(400, ["Сонгосон хүн алга."]));

    await waitFor(() => expect(onRefused).toHaveBeenCalledWith("Сонгосон хүн алга."));
    expect(onRefused).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("the form is read once on mount", async () => {
    renderPop(PICKED);
    await waitForForm();

    const formCalls = h.post.mock.calls.filter(([path]) => path === FORM_PATH);
    expect(formCalls).toHaveLength(1);
    expect(formCalls[0][1]).toEqual({
      params: { path: { key: KEY } },
      body: PICKED,
    });
  });
});
