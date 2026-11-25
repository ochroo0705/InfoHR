import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Modal } from "../../widgets/Modal";
import type { RecruitVacancyOptionsOut, RecruitWriteResultOut } from "../../api/recruitment";
import { VacancyModal } from "./VacancyModal";

// The API client is replaced by a stub that answers by path, so the real hooks run.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), confirm: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));
vi.mock("../../widgets/confirm", () => ({ confirm: (...args: unknown[]) => h.confirm(...args) }));

const OPTIONS: RecruitVacancyOptionsOut = {
  positions: [
    { id: 1, label: "Нягтлан" },
    { id: 2, label: "Жолооч" },
  ],
  departments: [{ id: 10, label: "Санхүү" }],
  branches: [
    { id: 20, label: "Төв салбар" },
    { id: 21, label: "Баянзүрх салбар" },
  ],
  managers: [{ id: 30, label: "Бат Болд" }],
  statuses: [],
};

const SLOT = { numbers: "2026 он · орон тоо 3 · ажиллаж буй 2 · сул 1", warning: "" };

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function refused(status: number) {
  return { data: undefined, error: {}, response: { ok: false, status } };
}

const SAVED: RecruitWriteResultOut & { id: number } = { ok: true, error: "", field_errors: {}, form_errors: [], id: 7 };
const REFUSED_TITLE: RecruitWriteResultOut = {
  ok: false,
  error: "",
  field_errors: { title: ["Энэ талбарыг бөглөнө үү."] },
  form_errors: [],
};

function renderModal(props: { onClose?: () => void; onSaved?: (id: number) => void; vacancyId?: number | null } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onClose = props.onClose ?? vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <VacancyModal vacancyId={props.vacancyId ?? null} onClose={onClose} onSaved={props.onSaved} />
    </QueryClientProvider>,
  );
  return { onClose, ...view };
}

// Picks an option of a click-list select the way a user does: a mousedown opens the list, a click on an item picks it.
// A native select opens its list on mousedown. A typing box (position, department, branch: as Django's addable boxes) opens
// its list on focus and click, and the hidden field of the same name sits beside it inside the label.
function pickOption(name: string, label: string) {
  const native = document.querySelector<HTMLSelectElement>(`form select[name='${name}']`);
  if (native) {
    fireEvent.mouseDown(native);
  } else {
    const hidden = document.querySelector<HTMLInputElement>(`form input[type=hidden][name='${name}']`) as HTMLInputElement;
    const box = hidden.closest("label")!.querySelector<HTMLInputElement>("input[role='combobox']") as HTMLInputElement;
    fireEvent.focus(box);
    fireEvent.click(box);
  }
  fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: label }));
}

function valueOf(name: string): string {
  const el = document.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(`[name="${name}"]`);
  return el?.value ?? "";
}

// The slot-line requests so far, by their query.
function slotQueries(): Record<string, string>[] {
  return h.get.mock.calls
    .filter((call) => call[0] === "/api/v1/recruitment/vacancies/slot-line")
    .map((call) => (call[1] as { params: { query: Record<string, string> } }).params.query);
}

async function waitForForm() {
  await screen.findByRole("button", { name: "Нээх" });
}

beforeEach(() => {
  h.get.mockReset();
  h.post.mockReset();
  h.confirm.mockReset();
  h.get.mockImplementation(async (path: string) => {
    if (path === "/api/v1/recruitment/vacancies/options") return ok(OPTIONS);
    if (path === "/api/v1/recruitment/vacancies/slot-line") return ok(SLOT);
    return refused(404);
  });
  h.post.mockImplementation(async () => ok(SAVED));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("VacancyModal (add)", () => {
  it("draws the fields in the form's order with the required marks and help texts", async () => {
    renderModal();
    await waitForForm();

    expect(screen.getByRole("heading", { name: "Ажлын байр нээх" })).toBeTruthy();
    const labels = Array.from(document.querySelectorAll("form label")).map((label) => label.textContent ?? "");
    const order = ["Ажлын байрны нэр", "Албан тушаал", "Хэлтэс", "Салбар", "Авах хүний тоо", "Ажилд авах удирдлага", "Авах эцсийн хугацаа", "Ажил эхлэх огноо", "Тайлбар"];
    const found = order.map((text) => labels.findIndex((label) => label.startsWith(text)));
    expect(found.every((index) => index >= 0)).toBe(true);
    expect([...found].sort((a, b) => a - b)).toEqual(found);

    expect(screen.getByText("Ажил хүсэгчийг харж, сэтгэгдэл бичих удирдлага.")).toBeTruthy();
    expect(screen.getByText("Орон тооны төлөвлөгөөг салбараар шалгана.")).toBeTruthy();
    expect(screen.getByText("Шинэ ажилтан ажилд орохыг хүсэж буй өдөр.")).toBeTruthy();
    expect(screen.queryByRole("combobox", { name: "Төлөв" })).toBeNull();
    expect(document.querySelector("select[name=status]")).toBeNull();
  });

  it("required-field errors sit under their field and the typed values stay", async () => {
    h.post.mockImplementation(async () => ok(REFUSED_TITLE));
    renderModal();
    await waitForForm();

    fireEvent.change(document.querySelector<HTMLTextAreaElement>("textarea[name=description]")!, {
      target: { value: "Тайлбар бичсэн" },
    });
    fireEvent.change(document.querySelector<HTMLInputElement>("input[name=headcount]")!, { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Нээх" }));

    const message = await screen.findByText("Энэ талбарыг бөглөнө үү.");
    // The message sits inside the title's own label, and the title names it through aria-describedby.
    const titleInput = document.querySelector<HTMLInputElement>("input[name=title]")!;
    const titleLabel = titleInput.closest("label");
    expect(titleLabel).not.toBeNull();
    expect(titleLabel!.contains(message)).toBe(true);
    const describedBy = titleInput.getAttribute("aria-describedby");
    expect(describedBy).not.toBeNull();
    expect(document.getElementById(describedBy!)?.contains(message)).toBe(true);
    expect(titleInput.getAttribute("aria-invalid")).toBe("true");
    // The other boxes keep what was typed.
    expect(valueOf("description")).toBe("Тайлбар бичсэн");
    expect(valueOf("headcount")).toBe("4");
  });

  it("a double click posts once", async () => {
    let finish: (value: unknown) => void = () => undefined;
    h.post.mockImplementation(() => new Promise((resolve) => (finish = resolve)));
    renderModal();
    await waitForForm();

    const button = screen.getByRole("button", { name: "Нээх" });
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.submit(button.closest("form") as HTMLFormElement);
    await waitFor(() => expect(h.post).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(h.post).toHaveBeenCalledTimes(1);
    finish(ok(SAVED));
  });

  it("a saved vacancy reports its id and closes", async () => {
    const onSaved = vi.fn();
    const { onClose } = renderModal({ onSaved });
    await waitForForm();

    fireEvent.click(screen.getByRole("button", { name: "Нээх" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(7));
    expect(onClose).toHaveBeenCalled();
  });

  it("the budget line is not asked before a position is chosen, and is asked again when the headcount changes", async () => {
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/recruitment/vacancies/options") return ok(OPTIONS);
      if (path === "/api/v1/recruitment/vacancies/slot-line") return ok(SLOT);
      return refused(404);
    });
    renderModal();
    await waitForForm();
    expect(slotQueries()).toHaveLength(0);

    pickOption("position", "Нягтлан");
    expect(await screen.findByText(/Орон тоо: 2026 он/)).toBeTruthy();
    expect(slotQueries().at(-1)?.position).toBe("1");

    const before = slotQueries().length;
    fireEvent.change(document.querySelector<HTMLInputElement>("input[name=headcount]")!, { target: { value: "5" } });
    await waitFor(() => expect(slotQueries().length).toBeGreaterThan(before));
    expect(slotQueries().at(-1)?.headcount).toBe("5");
  });

  it("the budget line is asked again when the branch changes", async () => {
    renderModal();
    await waitForForm();
    pickOption("position", "Нягтлан");
    await screen.findByText(/Орон тоо: 2026 он/);

    const before = slotQueries().length;
    pickOption("branch", "Төв салбар");
    await waitFor(() => expect(slotQueries().length).toBeGreaterThan(before));
    expect(slotQueries().at(-1)?.branch).toBe("20");
  });

  it("a 403 on the options shows the forbidden text", async () => {
    h.get.mockImplementation(async () => refused(403));
    renderModal();
    expect(await screen.findByText("Энэ хуудсыг үзэх эрх танд олгогдоогүй байна. Хэрэв хэрэгтэй бол системийн админд хандана уу.")).toBeTruthy();
  });

  it("Escape closes only the top pop-up", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const parentClose = vi.fn();
    const onClose = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <Modal open onClose={parentClose} title="Доод цонх">
          Доод
        </Modal>
        <VacancyModal vacancyId={null} onClose={onClose} />
      </QueryClientProvider>,
    );
    await waitForForm();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(parentClose).not.toHaveBeenCalled();
  });
});

// The saved values of vacancy 4: the manager 30 is current, the status is open.
const FORM = {
  title: "Бухгалтер",
  position: 1,
  department: 10,
  branch: 20,
  headcount: 2,
  hiring_manager: 30,
  deadline: "2026-12-31",
  desired_start: null,
  status: "open",
  description: "Тайлбар",
};

const EDIT_OPTIONS = {
  ...OPTIONS,
  statuses: [
    { value: "open", label: "Нээлттэй" },
    { value: "closed", label: "Хаагдсан" },
  ],
};

const DIRTY_TEXT = "Оруулсан мэдээлэл хадгалагдахгүй. Хаах уу?";

describe("VacancyModal (edit)", () => {
  beforeEach(() => {
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/recruitment/vacancies/{pk}/form") return ok(FORM);
      if (path === "/api/v1/recruitment/vacancies/options") return ok(EDIT_OPTIONS);
      if (path === "/api/v1/recruitment/vacancies/slot-line") return ok(SLOT);
      return refused(404);
    });
    h.post.mockImplementation(async () => ok({ ok: true, error: "", field_errors: {}, form_errors: [] }));
    h.confirm.mockResolvedValue(false);
  });

  it("shows the loading state until the saved values arrive, then the form with the saved values", async () => {
    let answer: (value: unknown) => void = () => undefined;
    h.get.mockImplementation((path: string) => {
      if (path === "/api/v1/recruitment/vacancies/{pk}/form") return new Promise((resolve) => (answer = resolve));
      return Promise.resolve(ok(EDIT_OPTIONS));
    });
    renderModal({ vacancyId: 4 });
    expect(await screen.findByRole("heading", { name: "Ажлын байр засах" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull();

    answer(ok(FORM));
    await screen.findByRole("button", { name: "Хадгалах" });
    expect(valueOf("title")).toBe("Бухгалтер");
    expect(valueOf("headcount")).toBe("2");
    expect(valueOf("deadline")).toBe("2026-12-31");
  });

  it("the status select is shown only when editing, with the saved status", async () => {
    renderModal({ vacancyId: 4 });
    await screen.findByRole("button", { name: "Хадгалах" });
    expect(valueOf("status")).toBe("open");
    expect(screen.getByText("Төлөв *")).toBeTruthy();
  });

  it("the current manager is preselected", async () => {
    renderModal({ vacancyId: 4 });
    await screen.findByRole("button", { name: "Хадгалах" });
    expect(valueOf("hiring_manager")).toBe("30");
  });

  it("a refused save keeps the typed values and shows the field message", async () => {
    h.post.mockImplementation(async () => ok({ ok: false, error: "", field_errors: { title: ["Энэ талбарыг бөглөнө үү."] }, form_errors: [] }));
    renderModal({ vacancyId: 4 });
    await screen.findByRole("button", { name: "Хадгалах" });

    fireEvent.change(document.querySelector<HTMLInputElement>("input[name=title]")!, { target: { value: "Шинэ нэр" } });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    expect(await screen.findByText("Энэ талбарыг бөглөнө үү.")).toBeTruthy();
    expect(valueOf("title")).toBe("Шинэ нэр");
  });

  it("the save posts the update to the vacancy's own path with the status", async () => {
    const onSaved = vi.fn();
    const { onClose } = renderModal({ vacancyId: 4, onSaved });
    await screen.findByRole("button", { name: "Хадгалах" });

    pickOption("status", "Хаагдсан");
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(h.post).toHaveBeenCalled());
    const [path, init] = h.post.mock.calls[0] as [string, { params: { path: { pk: number } }; body: Record<string, unknown> }];
    expect(path).toBe("/api/v1/recruitment/vacancies/{pk}");
    expect(init.params.path.pk).toBe(4);
    expect(init.body.status).toBe("closed");
    expect(init.body.hiring_manager).toBe(30);
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(4));
    expect(onClose).toHaveBeenCalled();
  });

  it("a vacancy the user may not see shows the not-found state", async () => {
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/recruitment/vacancies/{pk}/form") return refused(404);
      return ok(EDIT_OPTIONS);
    });
    renderModal({ vacancyId: 99 });
    expect(await screen.findByText("Хуудас олдсонгүй")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull();
  });

  it("Escape closes at once when nothing differs from the loaded values", async () => {
    const onClose = vi.fn();
    renderModal({ vacancyId: 4, onClose });
    await screen.findByRole("button", { name: "Хадгалах" });

    fireEvent.keyDown(document, { key: "Escape" });

    expect(h.confirm).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Escape asks the discard question once a box differs from the loaded values", async () => {
    const onClose = vi.fn();
    renderModal({ vacancyId: 4, onClose });
    await screen.findByRole("button", { name: "Хадгалах" });

    fireEvent.change(document.querySelector<HTMLInputElement>("input[name=title]")!, { target: { value: "Өөр нэр" } });
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(h.confirm).toHaveBeenCalledWith(DIRTY_TEXT, expect.anything()));
    expect(onClose).not.toHaveBeenCalled();
  });
});
