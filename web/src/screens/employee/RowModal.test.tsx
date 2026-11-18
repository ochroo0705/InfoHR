import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { components } from "../../api/schema";
import { ConfirmProvider } from "../../widgets/confirm";
import { isUnsaved } from "../../lib/unsaved";
import { DIRTY_CONFIRM_MESSAGE } from "../../widgets/modalLogic";
import { RowModal } from "./RowModal";

// fetch is stubbed before the api client is imported (openapi-fetch captures fetch when it is created), as in
// InlineRow.test.tsx. The row form and the row writes answer through this stub.
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

const DELETE_TEXT = "Энэ бичлэгийг устгах уу? Устгасны дараа буцаах боломжгүй.";
const SAVE_FAILED = "Мэдээллийг хадгалж чадсангүй.";
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";
const STALE = "Өөр хэрэглэгч өөрчилсөн байна. Дахин оролцоно уу.";

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

// The family row form: three visible fields and «phone», which the pop-up shows as well.
function familyForm(overrides: Partial<FormOut> = {}, edit = true): FormOut {
  return {
    title: edit ? "Гэр бүл: засах" : "Гэр бүл: нэмэх",
    fields: [
      field("relation", "Хамаарал", edit ? "Хүү" : ""),
      field("given_name", "Нэр", edit ? "Бат" : ""),
      field("phone", "Утас", ""),
      field("birth_date", "Төрсөн он", edit ? "2015" : ""),
    ],
    hidden: edit ? { loaded_given_name: "Бат", loaded_relation: "Хүү" } : {},
    empty_lists: [],
    can_delete: edit,
    ...overrides,
  };
}

// The address row form: a city select, a district select and a street box (the three fields the city change refetches).
function addressForm(city: string, district: string, street: string, edit = false): FormOut {
  return {
    title: edit ? "Оршин суугаа хаяг: засах" : "Оршин суугаа хаяг: нэмэх",
    fields: [
      field("city", "Хот", city, {
        kind: "select",
        choices: [
          { value: "", label: "---------" },
          { value: "UB", label: "Улаанбаатар" },
          { value: "DA", label: "Дархан" },
        ],
      }),
      field("district", "Дүүрэг", district, {
        kind: "select",
        choices: [
          { value: "", label: "---------" },
          { value: "BZ", label: "Баянзүрх" },
        ],
      }),
      field("street", "Гудамж", street),
    ],
    hidden: edit ? { loaded_city: "UB" } : {},
    empty_lists: [],
    can_delete: edit,
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
let formOut: FormOut = familyForm();
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
    if (request.method === "POST" && path.includes("/personal/")) {
      const body = (await request.json()) as { values: Record<string, string> };
      posted.push({ path, body: body.values });
      if (writeGate) await writeGate;
      return jsonResponse(200, writeAnswers.shift() ?? writeAnswer());
    }
    throw new Error(`unexpected request ${request.method} ${path}`);
  });
}

// The pop-up's own dialog is the last one in the document (the delete confirm opens above it).
const dialogs = () => screen.getAllByRole("dialog");
const mainDialog = () => dialogs()[0];
const confirmDialog = () => dialogs().at(-1) as HTMLElement;
const boxOf = (name: string) => document.querySelector<HTMLInputElement>(`form input[name='${name}']`);

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  fetchMock.mockReset();
  posted = [];
  gets = [];
  writeAnswers = [];
  formOut = familyForm();
  formStatus = 200;
  writeGate = null;
  route();
});

afterEach(() => {
  cleanup();
});

describe("RowModal (Task 15c)", () => {
  it("add opens the pop-up with its title and every visible field, and no delete button", async () => {
    formOut = familyForm({}, false);
    renderPopup(<RowModal pk={7} kind="family" rowKey={null} open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: "Гэр бүл: нэмэх" });
    expect(gets[0].pathname).toBe("/api/v1/employees/7/personal/family/form");
    expect(gets[0].searchParams.has("key")).toBe(false);
    expect(boxOf("relation")).not.toBeNull();
    expect(boxOf("given_name")).not.toBeNull();
    expect(boxOf("phone")).not.toBeNull();
    expect(boxOf("birth_date")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Устгах" })).toBeNull();
  });

  it("save posts the boxes without a loaded snapshot, and closes on ok", async () => {
    formOut = familyForm({}, false);
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="family" rowKey={null} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Гэр бүл: нэмэх" });
    fireEvent.change(boxOf("given_name") as HTMLInputElement, { target: { value: "Бат" } });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(posted).toHaveLength(1);
    expect(posted[0].path).toBe("/api/v1/employees/7/personal/family");
    expect(posted[0].body).toEqual({ relation: "", given_name: "Бат", phone: "", birth_date: "" });
  });

  it("a field error keeps the pop-up open with the typed values and the error under the box", async () => {
    formOut = familyForm({}, false);
    writeAnswers = [writeAnswer({ ok: false, field_errors: { given_name: ["Нэр заавал бөглөнө."] } })];
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="family" rowKey={null} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Гэр бүл: нэмэх" });
    fireEvent.change(boxOf("given_name") as HTMLInputElement, { target: { value: "Бат" } });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await screen.findByText("Нэр заавал бөглөнө.");
    expect(boxOf("given_name")?.getAttribute("aria-invalid")).toBe("true");
    expect(boxOf("given_name")?.value).toBe("Бат");
    expect(onClose).not.toHaveBeenCalled();
    expect(mainDialog()).not.toBeNull();
  });

  it("a refused write with form errors shows them in the red box and keeps the pop-up open", async () => {
    formOut = familyForm({}, false);
    writeAnswers = [writeAnswer({ ok: false, form_errors: [STALE] })];
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="family" rowKey={null} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Гэр бүл: нэмэх" });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await screen.findByText(STALE);
    expect(mainDialog().querySelector(".bg-red-50")?.textContent).toBe(STALE);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("edit loads the stored values and posts them with the hidden loaded_* snapshot", async () => {
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="family" rowKey={11} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Гэр бүл: засах" });
    expect(gets[0].searchParams.get("key")).toBe("11");
    expect(boxOf("given_name")?.value).toBe("Бат");

    fireEvent.change(boxOf("given_name") as HTMLInputElement, { target: { value: "Петр" } });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(posted[0].path).toBe("/api/v1/employees/7/personal/family/11");
    expect(posted[0].body).toEqual({
      relation: "Хүү",
      given_name: "Петр",
      phone: "",
      birth_date: "2015",
      loaded_given_name: "Бат",
      loaded_relation: "Хүү",
    });
  });

  it("the delete confirm asks in its own pop-up, posts once with the loaded values, and closes both on ok", async () => {
    let release!: () => void;
    writeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="family" rowKey={11} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Гэр бүл: засах" });
    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));
    await screen.findByText(DELETE_TEXT);
    expect(confirmDialog().querySelector("h2")?.textContent).toBe("Гэр бүл: устгах");

    const yes = within(confirmDialog()).getByRole("button", { name: "Устгах" });
    fireEvent.click(yes);
    fireEvent.submit(yes.closest("form") as HTMLFormElement);
    await waitFor(() => expect(posted).toHaveLength(1));

    expect(posted[0].path).toBe("/api/v1/employees/7/personal/family/11/delete");
    expect(posted[0].body).toEqual({ loaded_given_name: "Бат", loaded_relation: "Хүү" });
    await act(async () => {
      release();
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByText(DELETE_TEXT)).toBeNull());
    expect(posted).toHaveLength(1);
  });

  it("a refused delete keeps both pop-ups open and shows its message in the confirm", async () => {
    writeAnswers = [writeAnswer({ ok: false, form_errors: [STALE] })];
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="family" rowKey={11} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Гэр бүл: засах" });
    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));
    fireEvent.click(within(confirmDialog()).getByRole("button", { name: "Устгах" }));

    await screen.findByText(STALE);
    expect(within(confirmDialog()).getByText(STALE)).not.toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText(DELETE_TEXT)).not.toBeNull();
  });

  it("a failed delete request shows the save message in the confirm", async () => {
    fetchMock.mockImplementation(async (input: unknown) => {
      const request = input as Request;
      const path = new URL(request.url).pathname;
      if (request.method === "GET" && path.endsWith("/form")) return jsonResponse(200, familyForm());
      if (path.endsWith("/delete")) return jsonResponse(500, {});
      throw new Error(`unexpected request ${request.method} ${path}`);
    });
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="family" rowKey={11} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Гэр бүл: засах" });
    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));
    fireEvent.click(within(confirmDialog()).getByRole("button", { name: "Устгах" }));

    await screen.findByText(SAVE_FAILED);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a city change refetches the form with the new city, keeps the typed street and clears the typed district", async () => {
    formOut = addressForm("UB", "", "", true);
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="address" rowKey={3} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Оршин суугаа хаяг: засах" });
    fireEvent.change(boxOf("street") as HTMLInputElement, { target: { value: "Гудамж 5" } });
    fireEvent.change(document.querySelector("select[name='district']") as HTMLSelectElement, {
      target: { value: "BZ" },
    });
    expect(isUnsaved("list:address")).toBe(true);

    formOut = addressForm("DA", "", "Гудамж 5", true);
    fireEvent.change(document.querySelector("select[name='city']") as HTMLSelectElement, {
      target: { value: "DA" },
    });

    await waitFor(() => expect(gets.at(-1)?.searchParams.get("city")).toBe("DA"));
    const last = gets.at(-1) as URL;
    expect(last.searchParams.get("district")).toBe("");
    expect(last.searchParams.get("street")).toBe("Гудамж 5");
    await waitFor(() =>
      expect((document.querySelector("select[name='district']") as HTMLSelectElement).value).toBe(""),
    );
    expect((document.querySelector("select[name='city']") as HTMLSelectElement).value).toBe("DA");
    expect(boxOf("street")?.value).toBe("Гудамж 5");
  });

  it("an empty list the form needs shows its amber note with a link to the list", async () => {
    formOut = familyForm({ empty_lists: [{ slug: "relation", label: "Хамаатан" }] }, false);
    renderPopup(<RowModal pk={7} kind="family" rowKey={null} open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: "Гэр бүл: нэмэх" });
    expect(screen.getByText(/Хамаатан жагсаалт хоосон байна\./)).not.toBeNull();
    expect(screen.getByRole("link", { name: "Жагсаалт" }).getAttribute("href")).toBe("/lists/relation/");
  });

  it("closing a dirty pop-up asks first: cancel keeps it open, ok closes it", async () => {
    formOut = familyForm({}, false);
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="family" rowKey={null} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Гэр бүл: нэмэх" });
    fireEvent.change(boxOf("given_name") as HTMLInputElement, { target: { value: "Бат" } });
    expect(isUnsaved("list:family")).toBe(true);

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

  it("a failed form load shows the load message in a pop-up with a «Хаах» button", async () => {
    formStatus = 404;
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="family" rowKey={11} open onClose={onClose} />);

    await screen.findByText(LOAD_FAILED);
    fireEvent.click(screen.getByText("Хаах", { selector: "button:not([data-modal-x])" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull();
  });

  it("an open pop-up without a loaded form shows nothing, so no half-drawn form appears", () => {
    renderPopup(<RowModal pk={7} kind="family" rowKey={null} open onClose={vi.fn()} />);

    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a refused edit shows the real stale text in the pop-up and refetches the personal list", async () => {
    writeAnswers = [writeAnswer({ ok: false, form_errors: [STALE] })];
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="family" rowKey={11} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Гэр бүл: засах" });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await screen.findByText(STALE);
    expect(posted).toHaveLength(1);
    expect(posted[0].path).toBe("/api/v1/employees/7/personal/family/11");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7, "personal"], exact: true });
    expect(onClose).not.toHaveBeenCalled();
    expect(mainDialog().querySelector(".bg-red-50")?.textContent).toBe(STALE);
  });

  it("an edit whose loaded values are missing is not posted, and the pop-up says so", async () => {
    formOut = familyForm({ hidden: {} });
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="family" rowKey={11} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Гэр бүл: засах" });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await screen.findByText(SAVE_FAILED);
    expect(posted).toHaveLength(0);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("two Save submits in one tick send one request with the typed values", async () => {
    let release!: () => void;
    writeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="family" rowKey={11} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Гэр бүл: засах" });
    fireEvent.change(boxOf("given_name") as HTMLInputElement, { target: { value: "Петр" } });
    const form = boxOf("given_name")?.form as HTMLFormElement;
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));
    fireEvent.submit(form);
    await waitFor(() => expect(posted).toHaveLength(1));

    await act(async () => {
      release();
    });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(posted).toHaveLength(1);
    expect(posted[0].body.given_name).toBe("Петр");
  });

  it("a submit from a box (Enter) posts the typed values once and closes on ok", async () => {
    formOut = familyForm({}, false);
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="family" rowKey={null} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Гэр бүл: нэмэх" });
    fireEvent.change(boxOf("given_name") as HTMLInputElement, { target: { value: "Бат" } });
    (boxOf("given_name")?.form as HTMLFormElement).requestSubmit();

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(posted).toHaveLength(1);
    expect(posted[0].body).toEqual({ relation: "", given_name: "Бат", phone: "", birth_date: "" });
  });

  it("after a city change the pop-up is still unsaved: «Болих» asks, and the flag clears when it closes", async () => {
    formOut = addressForm("UB", "", "", true);
    const onClose = vi.fn();
    const tree = (open: boolean) => (
      <ConfirmProvider>
        <QueryClientProvider client={client}>
          <RowModal pk={7} kind="address" rowKey={3} open={open} onClose={onClose} />
        </QueryClientProvider>
      </ConfirmProvider>
    );
    const view = renderPopup(tree(true));

    await screen.findByRole("heading", { name: "Оршин суугаа хаяг: засах" });
    formOut = addressForm("DA", "", "", true);
    fireEvent.change(document.querySelector("select[name='city']") as HTMLSelectElement, { target: { value: "DA" } });
    await waitFor(() => expect(gets.at(-1)?.searchParams.get("city")).toBe("DA"));
    await waitFor(() =>
      expect((document.querySelector("select[name='city']") as HTMLSelectElement).value).toBe("DA"),
    );
    expect(isUnsaved("list:address")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Болих" }));
    const ask = await screen.findByRole("alertdialog");
    expect(ask.textContent).toContain(DIRTY_CONFIRM_MESSAGE);
    fireEvent.click(within(ask).getByRole("button", { name: "Болих" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(onClose).not.toHaveBeenCalled();

    view.rerender(tree(false));
    expect(isUnsaved("list:address")).toBe(false);
  });

  it("Escape closes the delete confirm first, then the pop-up under it", async () => {
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="family" rowKey={11} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Гэр бүл: засах" });
    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));
    await screen.findByText(DELETE_TEXT);

    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText(DELETE_TEXT)).toBeNull());
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Гэр бүл: засах" })).not.toBeNull();

    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("the delete confirm starts with its «Болих» focused", async () => {
    renderPopup(<RowModal pk={7} kind="family" rowKey={11} open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: "Гэр бүл: засах" });
    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));
    await screen.findByText(DELETE_TEXT);
    expect(document.activeElement).toBe(within(confirmDialog()).getByRole("button", { name: "Болих" }));
  });

  it("a city change keeps the typed district cleared even when the server's new form stores one", async () => {
    formOut = addressForm("UB", "", "", true);
    renderPopup(<RowModal pk={7} kind="address" rowKey={3} open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: "Оршин суугаа хаяг: засах" });
    const stored = addressForm("DA", "STORED", "", true);
    stored.fields[1] = field("district", "Дүүрэг", "STORED", {
      kind: "select",
      choices: [
        { value: "", label: "---------" },
        { value: "STORED", label: "Стор" },
      ],
    });
    formOut = stored;
    fireEvent.change(document.querySelector("select[name='city']") as HTMLSelectElement, { target: { value: "DA" } });

    await waitFor(() => expect(gets.at(-1)?.searchParams.get("city")).toBe("DA"));
    expect(gets.at(-1)?.searchParams.get("district")).toBe("");
    await waitFor(() =>
      expect((document.querySelector("select[name='district']") as HTMLSelectElement).value).toBe(""),
    );
  });

  it("a city refetch with a newer loaded_* snapshot still posts the snapshot from the first load", async () => {
    formOut = addressForm("UB", "", "", true);
    const onClose = vi.fn();
    renderPopup(<RowModal pk={7} kind="address" rowKey={3} open onClose={onClose} />);

    await screen.findByRole("heading", { name: "Оршин суугаа хаяг: засах" });
    // A colleague changed the row meanwhile: the refetch returns loaded_city "B" where the pop-up opened with "UB".
    formOut = { ...addressForm("DA", "", "", true), hidden: { loaded_city: "B" } };
    fireEvent.change(document.querySelector("select[name='city']") as HTMLSelectElement, { target: { value: "DA" } });
    await waitFor(() => expect(gets.at(-1)?.searchParams.get("city")).toBe("DA"));
    await waitFor(() =>
      expect((document.querySelector("select[name='city']") as HTMLSelectElement).value).toBe("DA"),
    );

    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(posted[0].path).toBe("/api/v1/employees/7/personal/address/3");
    expect(posted[0].body.loaded_city).toBe("UB");
  });
});
