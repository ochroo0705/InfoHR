import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { components } from "../../api/schema";
import { isUnsaved } from "../../lib/unsaved";
import { ConfirmProvider } from "../../widgets/confirm";
import { DIRTY_CONFIRM_MESSAGE } from "../../widgets/modalLogic";
import { CorrectionModal, useCorrectionPopup } from "./CorrectionModal";

// fetch is stubbed before the api client is imported (openapi-fetch captures fetch when it is created), as in RowModal.test.
// The correction form and the correction writes answer through this stub.
const h = vi.hoisted(() => {
  const fetchMock = vi.fn();
  const NativeRequest = globalThis.Request;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => fetchMock(input, init));
  vi.stubGlobal(
    "Request",
    class extends NativeRequest {
      constructor(input: RequestInfo | URL, init?: RequestInit) {
        super(typeof input === "string" ? new URL(input, window.location.origin) : input, init);
      }
    },
  );
  return { fetchMock };
});
const fetchMock = h.fetchMock;

type FormOut = components["schemas"]["EmployeeFormOut"];
type FormField = FormOut["fields"][number];
type WriteOut = components["schemas"]["EmployeeWriteResultOut"];

const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";

let client: QueryClient;
function renderPopup(ui: ReactNode) {
  return render(
    <ConfirmProvider>
      <QueryClientProvider client={client}>{ui}</QueryClientProvider>
    </ConfirmProvider>,
  );
}

function field(name: string, label: string, value: string, extra: Partial<FormField> = {}): FormField {
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

// «Цалин тогтоох»: the first pay (the date the pay starts, and the amount in a money box).
function setForm(amount = "2500000"): FormOut {
  return {
    title: "Цалин тогтоох",
    fields: [
      field("effective", "Хүчинтэй огноо", "2026-01-05", { required: true }),
      field("amount", "Цалин", amount, { kind: "money", required: true }),
    ],
    hidden: {},
    empty_lists: [],
    can_delete: false,
  };
}

// «Ажлын түүх засварлах»: the job fields and the required reason.
function jobForm(): FormOut {
  return {
    title: "Ажлын түүх засварлах",
    fields: [
      field("position", "Албан тушаал", "Ахлах мэргэжилтэн"),
      field("department", "Хэлтэс", "Хүний нөөц"),
      field("reason", "Шалтгаан", "", { required: true }),
    ],
    hidden: {},
    empty_lists: [],
    can_delete: false,
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function writeAnswer(overrides: Partial<WriteOut> = {}): WriteOut {
  return { ok: true, field_errors: {}, form_errors: [], conflicts: {}, loaded: "", si_loaded: "", tab: "", ...overrides };
}

type Posted = { path: string; body: Record<string, string> };
let posted: Posted[] = [];
let gets: URL[] = [];
let writeAnswers: WriteOut[] = [];
let formOut: FormOut = setForm();
let formStatus = 200;
let writeGate: Promise<void> | null = null;

function route() {
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const url = new URL(request.url);
    const path = url.pathname;
    if (request.method === "GET" && path.endsWith("/form")) {
      gets.push(url);
      return jsonResponse(formStatus, formStatus === 200 ? formOut : {});
    }
    if (request.method === "POST" && (path.endsWith("/salary/set") || path.endsWith("/correct"))) {
      const body = (await request.json()) as { values: Record<string, string> };
      posted.push({ path, body: body.values });
      if (writeGate) await writeGate;
      return jsonResponse(200, writeAnswers.shift() ?? writeAnswer());
    }
    throw new Error(`unexpected request ${request.method} ${path}`);
  });
}

// The pop-up's own dialog is the last one in the document (the unsaved confirm opens above it).
const mainDialog = () => screen.getAllByRole("dialog")[0];
const boxOf = (name: string) => document.querySelector<HTMLInputElement>(`form input[name='${name}']`);
// The save button of the open pop-up (the one inside the dialog).
const saveNowButton = (): HTMLElement => within(mainDialog()).getByRole("button", { name: "Хадгалах" });

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  fetchMock.mockReset();
  posted = [];
  gets = [];
  writeAnswers = [];
  formOut = setForm();
  formStatus = 200;
  writeGate = null;
  route();
});

afterEach(() => {
  cleanup();
});

describe("CorrectionModal (Task 16a)", () => {
  it("the set-salary pop-up loads its form from the set path and shows the form's title", async () => {
    renderPopup(<CorrectionModal pk={7} path="salary/set" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: "Цалин тогтоох" });
    expect(gets[0].pathname).toBe("/api/v1/employees/7/salary/set/form");
    expect(boxOf("effective")).not.toBeNull();
    expect(boxOf("amount")).not.toBeNull();
  });

  it("a save posts the plain amount, closes on ok, and refreshes the header, work, salary and activity", async () => {
    const onClose = vi.fn();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    renderPopup(<CorrectionModal pk={7} path="salary/set" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Цалин тогтоох" });
    fireEvent.change(boxOf("amount") as HTMLInputElement, { target: { value: "2600000" } });
    fireEvent.click(saveNowButton());

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(posted).toEqual([
      { path: "/api/v1/employees/7/salary/set", body: { effective: "2026-01-05", amount: "2600000" } },
    ]);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7], exact: true });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7, "work"], exact: true });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7, "salary"], exact: true });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7, "activity"], exact: true });
  });

  it("a refused save keeps the pop-up open, shows the reason error under its box with aria-invalid, and keeps the typed values", async () => {
    formOut = jobForm();
    writeAnswers = [writeAnswer({ ok: false, field_errors: { reason: ["Шалтгаан заавал бөглөнө."] } })];
    const onClose = vi.fn();
    renderPopup(<CorrectionModal pk={7} path="job/9/correct" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Ажлын түүх засварлах" });
    fireEvent.change(boxOf("position") as HTMLInputElement, { target: { value: "Мэргэжилтэн" } });
    fireEvent.click(saveNowButton());

    await screen.findByText("Шалтгаан заавал бөглөнө.");
    expect(boxOf("reason")?.getAttribute("aria-invalid")).toBe("true");
    expect(boxOf("position")?.value).toBe("Мэргэжилтэн");
    expect(onClose).not.toHaveBeenCalled();
    expect(mainDialog()).not.toBeNull();
  });

  it("the job correction posts the job fields and the reason to its own path, then closes", async () => {
    formOut = jobForm();
    const onClose = vi.fn();
    renderPopup(<CorrectionModal pk={7} path="job/9/correct" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Ажлын түүх засварлах" });
    expect(gets[0].pathname).toBe("/api/v1/employees/7/job/9/correct/form");
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Шилжүүлсэн" } });
    fireEvent.click(saveNowButton());

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(posted).toEqual([
      {
        path: "/api/v1/employees/7/job/9/correct",
        body: { position: "Ахлах мэргэжилтэн", department: "Хүний нөөц", reason: "Шилжүүлсэн" },
      },
    ]);
  });

  it("the server sends a whole amount without \".00\" (2500000): the box shows 2,500,000 and the plain 2500000 is posted", async () => {
    const onClose = vi.fn();
    renderPopup(<CorrectionModal pk={7} path="salary/set" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Цалин тогтоох" });
    expect((boxOf("amount") as HTMLInputElement).value).toBe("2,500,000");
    fireEvent.click(saveNowButton());

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(posted[0].body.amount).toBe("2500000");
  });

  it("a double submit sends one request", async () => {
    let release!: () => void;
    writeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const onClose = vi.fn();
    renderPopup(<CorrectionModal pk={7} path="salary/set" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Цалин тогтоох" });
    const form = boxOf("amount")?.form as HTMLFormElement;
    fireEvent.click(saveNowButton());
    fireEvent.submit(form);
    await waitFor(() => expect(posted).toHaveLength(1));

    await act(async () => {
      release();
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(posted).toHaveLength(1);
  });

  it("Enter in a box submits the form once", async () => {
    const onClose = vi.fn();
    renderPopup(<CorrectionModal pk={7} path="salary/set" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Цалин тогтоох" });
    (boxOf("amount")?.form as HTMLFormElement).requestSubmit();

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(posted).toHaveLength(1);
  });

  it("a changed pop-up is unsaved; closing it asks first, cancel keeps it open, ok closes it", async () => {
    const onClose = vi.fn();
    renderPopup(<CorrectionModal pk={7} path="salary/set" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Цалин тогтоох" });
    fireEvent.change(boxOf("amount") as HTMLInputElement, { target: { value: "2600000" } });
    expect(isUnsaved("correction:salary/set")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Болих" }));
    const ask = await screen.findByRole("alertdialog");
    expect(ask.textContent).toContain(DIRTY_CONFIRM_MESSAGE);
    fireEvent.click(within(ask).getByRole("button", { name: "Болих" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(document.querySelector("[data-modal-x]") as HTMLElement);
    const again = await screen.findByRole("alertdialog");
    fireEvent.click(within(again).getByRole("button", { name: "Хаах" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("a 403 on the form load (a scheduled row is refused) shows the load message with «Хаах», and no form", async () => {
    formStatus = 403;
    const onClose = vi.fn();
    renderPopup(<CorrectionModal pk={7} path="salary/5/correct" open onClose={onClose} />);

    await screen.findByText(LOAD_FAILED);
    expect(gets[0].pathname).toBe("/api/v1/employees/7/salary/5/correct/form");
    expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull();
    fireEvent.click(screen.getByText("Хаах", { selector: "button:not([data-modal-x])" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("nothing is loaded or drawn while the pop-up is closed", () => {
    renderPopup(<CorrectionModal pk={7} path="salary/set" open={false} onClose={vi.fn()} />);

    expect(gets).toHaveLength(0);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

// A section that opens the pop-up through the same hook the sections use (the serial guard and the remount per open).
function Harness() {
  const { openCorrection, correctionModal } = useCorrectionPopup(7);
  return (
    <>
      <button type="button" onClick={() => openCorrection("salary/set")}>
        Open pop-up
      </button>
      {correctionModal}
    </>
  );
}

const STALE = "Өөр хэрэглэгч өөрчилсөн байна. Дахин оролцоно уу.";

describe("CorrectionModal: review fixes (fix round 1)", () => {
  it("an empty amount shows the required error under the money box, aria-invalid on it, and the typed reason stays", async () => {
    formOut = setForm("");
    writeAnswers = [writeAnswer({ ok: false, field_errors: { amount: ["Цалин заавал бөглөнө."] } })];
    renderPopup(<CorrectionModal pk={7} path="salary/set" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: "Цалин тогтоох" });
    fireEvent.click(saveNowButton());

    await screen.findByText("Цалин заавал бөглөнө.");
    expect(boxOf("amount")?.getAttribute("aria-invalid")).toBe("true");
    expect(posted[0].body.amount).toBe("");
  });

  it("Enter in the reason textarea does not submit the form", async () => {
    formOut = {
      ...jobForm(),
      fields: jobForm().fields.map((f) => (f.name === "reason" ? { ...f, kind: "textarea" } : f)),
    };
    const onClose = vi.fn();
    renderPopup(<CorrectionModal pk={7} path="job/9/correct" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Ажлын түүх засварлах" });
    const reason = document.querySelector("form textarea[name='reason']") as HTMLTextAreaElement;
    fireEvent.change(reason, { target: { value: "Шилжүүлсэн" } });
    fireEvent.keyDown(reason, { key: "Enter" });

    expect(posted).toHaveLength(0);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("the pop-up closes only after the refetch of the work tab has resolved", async () => {
    let finishRefetch!: () => void;
    const gate = new Promise<unknown>((resolve) => {
      finishRefetch = () => resolve({});
    });
    // An active observer on the work key: the save's invalidation has to wait for this refetch.
    const observer = new QueryObserver(client, { queryKey: ["employee", 7, "work"], queryFn: () => gate, retry: false });
    const unsubscribe = observer.subscribe(() => {});
    const onClose = vi.fn();
    renderPopup(<CorrectionModal pk={7} path="salary/set" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Цалин тогтоох" });
    fireEvent.click(saveNowButton());
    await waitFor(() => expect(posted).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(onClose).not.toHaveBeenCalled();

    finishRefetch();
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    unsubscribe();
  });

  it("a refused save's form error leaves the red box when the next save starts", async () => {
    writeAnswers = [writeAnswer({ ok: false, form_errors: [STALE] })];
    renderPopup(<CorrectionModal pk={7} path="salary/set" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: "Цалин тогтоох" });
    fireEvent.click(saveNowButton());
    await screen.findByText(STALE);

    let release!: () => void;
    writeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    fireEvent.click(saveNowButton());
    await waitFor(() => expect(posted).toHaveLength(2));
    expect(mainDialog().querySelector(".bg-red-50")).toBeNull();

    await act(async () => {
      release();
    });
  });

  it("a value typed and then changed back still counts as unsaved: «Болих» asks first", async () => {
    const onClose = vi.fn();
    renderPopup(<CorrectionModal pk={7} path="salary/set" open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Цалин тогтоох" });
    fireEvent.change(boxOf("amount") as HTMLInputElement, { target: { value: "2600000" } });
    fireEvent.change(boxOf("amount") as HTMLInputElement, { target: { value: "2500000" } });
    fireEvent.click(screen.getByRole("button", { name: "Болих" }));

    const ask = await screen.findByRole("alertdialog");
    expect(ask.textContent).toContain(DIRTY_CONFIRM_MESSAGE);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a save answer of a pop-up that was closed and replaced is ignored: the new pop-up keeps its typed text", async () => {
    let release!: () => void;
    writeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    writeAnswers = [writeAnswer({ ok: false, field_errors: { amount: ["Цалин буруу байна."] } })];
    renderPopup(<Harness />);

    fireEvent.click(screen.getByRole("button", { name: "Open pop-up" }));
    await screen.findByRole("heading", { name: "Цалин тогтоох" });
    fireEvent.click(saveNowButton());
    await waitFor(() => expect(posted).toHaveLength(1));

    // Close the first pop-up (nothing typed, so no ask), then open a second one and type into it.
    fireEvent.click(document.querySelector("[data-modal-x]") as HTMLElement);
    fireEvent.click(screen.getByRole("button", { name: "Open pop-up" }));
    await waitFor(() => expect(boxOf("amount")).not.toBeNull());
    fireEvent.change(boxOf("amount") as HTMLInputElement, { target: { value: "3000000" } });

    // The first pop-up's answer arrives now: refused, but it belongs to a pop-up that is no longer current.
    await act(async () => {
      release();
    });
    await waitFor(() => expect(posted).toHaveLength(1));

    expect(boxOf("amount")?.value).toBe("3,000,000");
    expect(boxOf("amount")?.getAttribute("aria-invalid")).toBeNull();
    expect(screen.queryByText("Цалин буруу байна.")).toBeNull();
  });
});
