import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { components } from "../../api/schema";
import { isUnsaved } from "../../lib/unsaved";
import { PersonalList } from "./PersonalList";

// fetch is stubbed before the api client is imported (openapi-fetch captures fetch when it is created), as in
// PersonalSection.test.tsx. The row form and the row writes answer through this stub.
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

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

type PersonalListOut = components["schemas"]["EmployeePersonalListOut"];
type FormOut = components["schemas"]["EmployeeFormOut"];
type FormField = FormOut["fields"][number];
type WriteOut = components["schemas"]["EmployeeWriteResultOut"];

let client: QueryClient;
// The wrapper is the same on every render, so `rerender` keeps the query client (a refetch is a new list prop).
function Wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
function renderList(ui: ReactNode) {
  return render(ui, { wrapper: Wrapper });
}

// The real stale-check message of a row write (app/employees/services/personal_writes.py, STALE).
const STALE = "Өөр хэрэглэгч өөрчилсөн байна, дахин ачаална уу";
const SAVE_FAILED = "Мэдээллийг хадгалж чадсангүй.";
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";

// The family list: three columns that name their form fields; the row keys are the URL keys.
function familyList(overrides: Partial<PersonalListOut> = {}): PersonalListOut {
  return {
    kind: "family",
    title: "Гэр бүл",
    group: "basic",
    parent: null,
    inline: true,
    editable: true,
    count: 2,
    empty_label: "",
    columns: [
      { header: "Нэр", field: "given_name", head_class: "", cell_class: "" },
      { header: "Хамаатан", field: "relation", head_class: "", cell_class: "" },
      { header: "Төрсөн он", field: "birth_date", head_class: "", cell_class: "" },
    ],
    rows: [
      { key: "11", cells: ["Бат", "Хүү", "2015"] },
      { key: "12", cells: ["Сара", "—", "—"] },
    ],
    ...overrides,
  };
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

// The row form: the three column fields, and «phone», which no column names (it must not be shown or posted).
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

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function writeAnswer(overrides: Partial<WriteOut> = {}): WriteOut {
  return { ok: true, field_errors: {}, form_errors: [], conflicts: {}, loaded: "", si_loaded: "", tab: "", ...overrides };
}

// Every POST to the family list, with its path and JSON body, in order.
type Posted = { path: string; body: Record<string, string> };
let posted: Posted[] = [];
let writeAnswers: WriteOut[] = [];
let formOut: FormOut = familyForm();
let formStatus = 200;
// When set, a write waits for this promise before it is answered (a response that arrives late).
let writeGate: Promise<void> | null = null;

function route() {
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (request.method === "GET" && path.endsWith("/personal/family/form")) {
      return jsonResponse(formStatus, formOut);
    }
    if (request.method === "POST" && path.includes("/personal/family")) {
      const body = (await request.json()) as { values: Record<string, string> };
      posted.push({ path, body: body.values });
      if (writeGate) await writeGate;
      const next = writeAnswers.shift() ?? writeAnswer();
      return jsonResponse(200, next);
    }
    throw new Error(`unexpected request ${request.method} ${path}`);
  });
}

const inputOf = (container: HTMLElement, name: string) =>
  container.querySelector<HTMLInputElement>(`[data-inline-row] input[name='${name}']`);

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  fetchMock.mockReset();
  posted = [];
  writeAnswers = [];
  formOut = familyForm();
  formStatus = 200;
  writeGate = null;
  route();
});

afterEach(() => {
  cleanup();
});

describe("inline list rows (Task 15b)", () => {
  it("«+ нэмэх» opens an add row with the form's fields in column order, and not the fields no column names", async () => {
    const { container } = renderList(<PersonalList list={familyList({ rows: [] , count: 0, empty_label: "бүртгэгдээгүй" })} pk={7} editable={true} />);

    fireEvent.click(screen.getByRole("button", { name: "+ нэмэх" }));
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());

    const row = container.querySelector("[data-inline-row]") as HTMLElement;
    expect(row.getAttribute("data-row-key")).toBe("new");
    expect(Array.from(row.querySelectorAll<HTMLInputElement>("input[name]")).map((input) => input.name)).toEqual([
      "given_name",
      "relation",
      "birth_date",
    ]);
    expect(container.querySelector("#inline-family-given_name")).not.toBeNull();
    expect(container.querySelector("input[name='phone']")).toBeNull();
    // The head shows neither «+ нэмэх» nor the empty label while the add row is open.
    expect(screen.queryByRole("button", { name: "+ нэмэх" })).toBeNull();
    expect(container.querySelector("h3.sec-title")?.textContent).toBe("Гэр бүл");
  });

  it("the edit form's path names the row key and posts the form's hidden loaded values", async () => {
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    expect(inputOf(container, "given_name")?.value).toBe("Бат");

    fireEvent.change(inputOf(container, "given_name") as HTMLInputElement, { target: { value: "Петр" } });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));
    await waitFor(() => expect(posted).toHaveLength(1));

    expect(posted[0].path).toBe("/api/v1/employees/7/personal/family/11");
    expect(posted[0].body).toEqual({
      given_name: "Петр",
      relation: "Хүү",
      birth_date: "2015",
      loaded_given_name: "Бат",
      loaded_relation: "Хүү",
    });
  });

  it("two submits in one tick send one request, and a saved add row closes", async () => {
    formOut = familyForm({}, false);
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(screen.getByRole("button", { name: "+ нэмэх" }));
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());

    const form = container.querySelector("#inline-family-form") as HTMLFormElement;
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => expect(container.querySelector("[data-inline-row]")).toBeNull());

    expect(posted).toHaveLength(1);
    expect(posted[0].path).toBe("/api/v1/employees/7/personal/family");
    // The add body holds the boxes' values, and no loaded_* snapshot (an add has none).
    expect(posted[0].body).toEqual({ given_name: "", relation: "", birth_date: "" });
  });

  it("a refused save keeps the row open with the typed values, marks the box and shows nothing closed", async () => {
    writeAnswers = [writeAnswer({ ok: false, field_errors: { given_name: ["Нэр заавал бөглөнө."] } })];
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    fireEvent.change(inputOf(container, "given_name") as HTMLInputElement, { target: { value: "Петр" } });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await screen.findByText("Нэр заавал бөглөнө.");
    const box = inputOf(container, "given_name") as HTMLInputElement;
    expect(box.getAttribute("aria-invalid")).toBe("true");
    expect(box.value).toBe("Петр");
    expect(document.activeElement).toBe(box);
    expect(container.querySelector("[data-inline-row]")).not.toBeNull();
  });

  it("Esc closes the row without saving", async () => {
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    fireEvent.keyDown(inputOf(container, "given_name") as HTMLInputElement, { key: "Escape" });

    expect(container.querySelector("[data-inline-row]")).toBeNull();
    expect(posted).toHaveLength(0);
  });

  it("Esc with an open calendar or dropdown only closes that popup, not the row", async () => {
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    const popup = document.createElement("div");
    popup.className = "dp-popup";
    document.body.appendChild(popup);

    fireEvent.keyDown(inputOf(container, "given_name") as HTMLInputElement, { key: "Escape" });
    expect(container.querySelector("[data-inline-row]")).not.toBeNull();

    popup.remove();
    fireEvent.keyDown(inputOf(container, "given_name") as HTMLInputElement, { key: "Escape" });
    expect(container.querySelector("[data-inline-row]")).toBeNull();
  });

  it("«Устгах» asks in the row, «Тийм» posts one delete with the loaded values, and the row closes after it", async () => {
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));
    expect(screen.getByText("Устгах уу?")).not.toBeNull();

    const yes = screen.getByRole("button", { name: "Тийм" });
    fireEvent.click(yes);
    fireEvent.click(yes);
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0].path).toBe("/api/v1/employees/7/personal/family/11/delete");
    expect(posted[0].body).toEqual({
      given_name: "Бат",
      relation: "Хүү",
      birth_date: "2015",
      loaded_given_name: "Бат",
      loaded_relation: "Хүү",
    });
    await waitFor(() => expect(container.querySelector("[data-inline-row]")).toBeNull());
  });

  it("a refused delete keeps the row open and shows the message above the table", async () => {
    writeAnswers = [writeAnswer({ ok: false, form_errors: ["Өөр хэрэглэгч өөрчилсөн байна. Дахин оролцоно уу."] })];
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));
    fireEvent.click(screen.getByRole("button", { name: "Тийм" }));

    await screen.findByText("Өөр хэрэглэгч өөрчилсөн байна. Дахин оролцоно уу.");
    expect(container.querySelector("[data-inline-row]")).not.toBeNull();
    expect(container.querySelector("[data-inline-list] .bg-red-50")?.textContent).toContain("Өөр хэрэглэгч");
  });

  it("a conflict on save keeps the row open and shows its message", async () => {
    writeAnswers = [writeAnswer({ ok: false, form_errors: ["Өөр хэрэглэгч өөрчилсөн байна. Дахин оролцоно уу."] })];
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await screen.findByText("Өөр хэрэглэгч өөрчилсөн байна. Дахин оролцоно уу.");
    expect(container.querySelector("[data-inline-row]")).not.toBeNull();
  });

  it("a dirty open row holds the unsaved flag, and closing it clears the flag", async () => {
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    expect(isUnsaved("list:family")).toBe(false);

    fireEvent.change(inputOf(container, "given_name") as HTMLInputElement, { target: { value: "Петр" } });
    expect(isUnsaved("list:family")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Болих" }));
    await waitFor(() => expect(isUnsaved("list:family")).toBe(false));
  });

  it("an empty list the form needs shows its amber note with a link to the list", async () => {
    formOut = familyForm({ empty_lists: [{ slug: "relation", label: "Хамаатан" }] });
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());

    expect(screen.getByText(/Хамаатан жагсаалт хоосон байна\./)).not.toBeNull();
    expect(screen.getByRole("link", { name: "Жагсаалт" }).getAttribute("href")).toBe("/lists/relation/");
  });

  it("the empty-list note sits above the table, not inside the open row (_inline_list.html order)", async () => {
    formOut = familyForm({ empty_lists: [{ slug: "relation", label: "Хамаатан" }] });
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());

    const note = screen.getByText(/Хамаатан жагсаалт хоосон байна\./);
    const table = container.querySelector("table") as HTMLTableElement;
    expect(table.contains(note)).toBe(false);
    expect(note.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("while a row is open, the other rows and «+ нэмэх» are inactive", async () => {
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());

    expect(screen.queryByRole("button", { name: "+ нэмэх" })).toBeNull();
    fireEvent.click(container.querySelector("tbody tr[data-row-key='12']") as HTMLElement);
    expect(container.querySelector("[data-row-key='12'][data-inline-row]")).toBeNull();
    expect(container.querySelector("[data-inline-row]")?.getAttribute("data-row-key")).toBe("11");
  });

  it("a refused save leaves a red box, and a successful delete after it clears that box (no stale message)", async () => {
    writeAnswers = [writeAnswer({ ok: false, form_errors: ["Алдаа гарлаа."] }), writeAnswer()];
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));
    await screen.findByText("Алдаа гарлаа.");

    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));
    fireEvent.click(screen.getByRole("button", { name: "Тийм" }));
    await waitFor(() => expect(container.querySelector("[data-inline-row]")).toBeNull());

    expect(container.querySelector("[data-inline-list] .bg-red-50")).toBeNull();
    expect(screen.queryByText("Алдаа гарлаа.")).toBeNull();
  });

  it("«Тийм» fades the row at once, sends one delete on a double tap, and closes the row on success", async () => {
    let release!: () => void;
    writeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));
    const yes = screen.getByRole("button", { name: "Тийм" });
    fireEvent.click(yes);

    // The fade is set by the click itself, before the answer.
    const row = container.querySelector("[data-inline-row]") as HTMLElement;
    expect(row.hasAttribute("data-leaving")).toBe(true);
    expect(row.className).toContain("opacity-0");
    fireEvent.click(yes);
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(container.querySelector("[data-inline-row]")).not.toBeNull();

    await act(async () => {
      release();
    });
    await waitFor(() => expect(container.querySelector("[data-inline-row]")).toBeNull());
    expect(posted).toHaveLength(1);
  });

  it("a refused delete clears the fade and keeps the row open with its message", async () => {
    writeAnswers = [writeAnswer({ ok: false, form_errors: [STALE] })];
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));
    fireEvent.click(screen.getByRole("button", { name: "Тийм" }));

    await screen.findByText(STALE);
    const row = container.querySelector("[data-inline-row]") as HTMLElement;
    expect(row.hasAttribute("data-leaving")).toBe(false);
    expect(row.className).not.toContain("opacity-0");
  });

  it("a stale edit: the list refetched without the row closes it, the message stays, and the personal list is invalidated", async () => {
    writeAnswers = [writeAnswer({ ok: false, form_errors: [STALE] })];
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { container, rerender } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));
    await screen.findByText(STALE);

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7, "personal"], exact: true });

    // The refetch: row 11 is gone from the list.
    rerender(
      <PersonalList
        list={familyList({ count: 1, rows: [{ key: "12", cells: ["Сара", "—", "—"] }] })}
        pk={7}
        editable={true}
      />,
    );
    await waitFor(() => expect(container.querySelector("[data-inline-row]")).toBeNull());
    expect(screen.getByText(STALE)).not.toBeNull();
    expect(container.querySelector("tbody tr[data-row-key='12']")).not.toBeNull();
  });

  it("an empty hidden map sends nothing and shows the general save message", async () => {
    formOut = familyForm({ hidden: {} });
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await screen.findByText(SAVE_FAILED);
    expect(posted).toHaveLength(0);
  });

  it("a failed form load shows its message and sends nothing on ✓", async () => {
    formStatus = 403;
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await screen.findByText(LOAD_FAILED);
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));
    expect(posted).toHaveLength(0);
  });

  it("a field error that names no shown box shows the general save message", async () => {
    writeAnswers = [writeAnswer({ ok: false, field_errors: { phone: ["Утас буруу."] } })];
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await screen.findByText(SAVE_FAILED);
    expect(container.querySelector("[data-inline-row]")).not.toBeNull();
  });

  it("✓ is disabled and busy while its write is pending", async () => {
    let release!: () => void;
    writeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    const check = screen.getByRole("button", { name: "Хадгалах" }) as HTMLButtonElement;
    fireEvent.click(check);
    await waitFor(() => expect(check.disabled).toBe(true));
    expect(check.getAttribute("aria-busy")).toBe("true");
    await act(async () => {
      release();
    });
    await waitFor(() => expect(container.querySelector("[data-inline-row]")).toBeNull());
  });

  it("a refused answer for a row that is no longer open writes no message and closes nothing", async () => {
    let release!: () => void;
    writeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    writeAnswers = [writeAnswer({ ok: false, form_errors: ["Хуучин алдаа."] })];
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    fireEvent.change(inputOf(container, "given_name") as HTMLInputElement, { target: { value: "Петр" } });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));
    await waitFor(() => expect(posted).toHaveLength(1));

    // The user closes that row and opens the add row while the answer is still on its way.
    fireEvent.click(screen.getByRole("button", { name: "Болих" }));
    fireEvent.click(screen.getByRole("button", { name: "+ нэмэх" }));
    await waitFor(() => expect(container.querySelector("[data-row-key='new'][data-inline-row]")).not.toBeNull());

    await act(async () => {
      release();
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(container.querySelector("[data-row-key='new'][data-inline-row]")).not.toBeNull();
    expect(screen.queryByText("Хуучин алдаа.")).toBeNull();
  });

  it("an ok answer for a row that is no longer open does not close the row that replaced it", async () => {
    let release!: () => void;
    writeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr[data-row-key='11']") as HTMLElement);
    await waitFor(() => expect(inputOf(container, "given_name")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));
    await waitFor(() => expect(posted).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Болих" }));
    fireEvent.click(screen.getByRole("button", { name: "+ нэмэх" }));
    await waitFor(() => expect(container.querySelector("[data-row-key='new'][data-inline-row]")).not.toBeNull());

    await act(async () => {
      release();
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(container.querySelector("[data-row-key='new'][data-inline-row]")).not.toBeNull();
  });
});
