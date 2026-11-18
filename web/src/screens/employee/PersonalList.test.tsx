import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { components } from "../../api/schema";
import { openLegacyEmployee } from "../../lib/AppLink";
import { ConfirmProvider } from "../../widgets/confirm";
import { PersonalList } from "./PersonalList";

// The pop-up lists open a RowModal, which loads its form through fetch (stubbed before the api client is imported, as in
// InlineRow.test.tsx). The inline list tests need the same provider.
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

let client: QueryClient;
function Wrapper({ children }: { children: ReactNode }) {
  return (
    <ConfirmProvider>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ConfirmProvider>
  );
}
function renderList(ui: ReactNode) {
  return render(ui, { wrapper: Wrapper });
}

// An inline list (the family list) as the API sends it: headers without classes, cells already as display text.
function familyList(overrides: Partial<PersonalListOut> = {}): PersonalListOut {
  return {
    kind: "family",
    title: "Гэр бүл",
    group: "basic",
    parent: null,
    inline: true,
    editable: false,
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

// A pop-up table list (the education list) as the API sends it: classes on the last columns, a cell class on «Голч».
function educationList(overrides: Partial<PersonalListOut> = {}): PersonalListOut {
  return {
    kind: "education",
    title: "Сурсан сургууль",
    group: "edu",
    parent: null,
    inline: false,
    editable: true,
    count: 1,
    empty_label: "",
    columns: [
      { header: "Сургууль", field: "", head_class: "", cell_class: "" },
      { header: "Он", field: "", head_class: "", cell_class: "whitespace-nowrap" },
      { header: "Голч", field: "", head_class: "text-right", cell_class: "text-right" },
      { header: "Диплом №", field: "", head_class: "pl-6", cell_class: "pl-6" },
    ],
    rows: [{ key: "7", cells: ["ХИС", "2010–2014", "3.2", "D-0001"] }],
    ...overrides,
  };
}

// The education row form: the school box and the year box, loaded for the edit of row 7.
function educationForm(edit: boolean): FormOut {
  return {
    title: edit ? "Сурсан сургууль: засах" : "Сурсан сургууль: нэмэх",
    fields: [
      {
        name: "school",
        label: "Сургууль",
        required: false,
        kind: "text",
        value: edit ? "ХИС" : "",
        checked: false,
        placeholder: "",
        choice: "",
        combo: false,
        choices: [],
        help: "",
        max_length: null,
        errors: [],
      },
    ],
    hidden: edit ? { loaded_school: "ХИС" } : {},
    empty_lists: [],
    can_delete: edit,
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

// A write waits for this promise before it is answered (a late answer), when set.
let writeGate: Promise<void> | null = null;

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(openLegacyEmployee).mockClear();
  writeGate = null;
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname.endsWith("/personal/education/form")) {
      return jsonResponse(200, educationForm(url.searchParams.has("key")));
    }
    if (request.method === "POST" && url.pathname.includes("/personal/education")) {
      if (writeGate) await writeGate;
      return jsonResponse(200, { ok: true, field_errors: {}, form_errors: [], conflicts: {}, loaded: "", si_loaded: "", tab: "" });
    }
    throw new Error(`unexpected request ${request.method} ${url.pathname}`);
  });
});

afterEach(() => {
  cleanup();
});

describe("PersonalList", () => {
  it("renders an inline list's values in the API column order", () => {
    const { container } = renderList(<PersonalList list={familyList()} pk={7} editable={false} />);

    const headers = Array.from(container.querySelectorAll("thead th")).map((th) => th.textContent);
    expect(headers).toEqual(["Нэр", "Хамаатан", "Төрсөн он"]);

    const rows = Array.from(container.querySelectorAll("tbody tr"));
    expect(rows.map((tr) => tr.getAttribute("data-row-key"))).toEqual(["11", "12"]);
    expect(Array.from(rows[0].querySelectorAll("td")).map((td) => td.textContent)).toEqual(["Бат", "Хүү", "2015"]);
    expect(Array.from(rows[1].querySelectorAll("td")).map((td) => td.textContent)).toEqual(["Сара", "—", "—"]);
  });

  it("wraps an inline list in its data-inline-list block and a pop-up list in none", () => {
    const { container: inline } = renderList(<PersonalList list={familyList()} pk={7} editable={false} />);
    const block = inline.querySelector("#list-family");
    expect(block?.hasAttribute("data-inline-list")).toBe(true);
    cleanup();

    const { container: popup } = renderList(<PersonalList list={educationList()} pk={7} editable={false} />);
    expect(popup.querySelector("[data-inline-list]")).toBeNull();
    expect(popup.querySelector("[id^='list-']")).toBeNull();
    expect(popup.querySelector("tbody tr")?.hasAttribute("data-row-key")).toBe(false);
  });

  it("applies the API's head and cell classes, and none for the empty ones", () => {
    const { container } = renderList(<PersonalList list={educationList()} pk={7} editable={false} />);

    const ths = Array.from(container.querySelectorAll("thead th"));
    expect(ths.map((th) => th.getAttribute("class"))).toEqual([null, null, "text-right", "pl-6"]);

    const tds = Array.from(container.querySelectorAll("tbody td"));
    expect(tds.map((td) => td.getAttribute("class"))).toEqual([null, "whitespace-nowrap", "text-right", "pl-6"]);
  });

  it("shows the empty label beside the title when the list has no rows", () => {
    const list = familyList({ count: 0, empty_label: "бүртгэгдээгүй", rows: [] });
    const { container } = renderList(<PersonalList list={list} pk={7} editable={false} />);

    expect(screen.getByText("бүртгэгдээгүй").className).toBe("ml-1 text-sm font-normal text-slate-400");
    expect(container.querySelector("h3.sec-title")?.textContent).toBe("Гэр бүл бүртгэгдээгүй");
    expect(container.querySelector("table")).toBeNull();
  });

  it("shows no empty label and no table for a filled list's title", () => {
    const { container } = renderList(<PersonalList list={educationList()} pk={7} editable={false} />);

    expect(container.querySelector("h3.sec-title")?.textContent).toBe("Сурсан сургууль");
    expect(container.querySelector(".ptable table")).not.toBeNull();
  });

  it("«+ нэмэх» on a pop-up list opens the add pop-up, not the Django page", async () => {
    renderList(<PersonalList list={educationList()} pk={7} editable={true} />);

    fireEvent.click(screen.getByRole("button", { name: "+ нэмэх" }));
    await screen.findByRole("heading", { name: "Сурсан сургууль: нэмэх" });
    expect(fetchMock.mock.calls.map(([input]) => new URL((input as Request).url).pathname)).toEqual([
      "/api/v1/employees/7/personal/education/form",
    ]);
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("a pop-up row click opens the edit pop-up with the row's key, and not the Django page", async () => {
    const { container } = renderList(<PersonalList list={educationList()} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr") as HTMLElement);
    await screen.findByRole("heading", { name: "Сурсан сургууль: засах" });
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(new URL(request.url).searchParams.get("key")).toBe("7");
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("shows no «+ нэмэх» and opens no row on a click when the inline list is not editable", () => {
    const { container } = renderList(<PersonalList list={familyList({ editable: false })} pk={7} editable={false} />);

    expect(screen.queryByRole("button", { name: "+ нэмэх" })).toBeNull();
    const row = container.querySelector("tbody tr[data-row-key='12']") as HTMLElement;
    expect(row.getAttribute("class")).toBe("");
    fireEvent.click(row);
    expect(container.querySelector("[data-inline-row]")).toBeNull();
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("adds the action column to an editable inline list only", () => {
    const { container: editable } = renderList(
      <PersonalList list={familyList({ editable: true })} pk={7} editable={true} />,
    );
    expect(editable.querySelectorAll("thead th")).toHaveLength(4);
    expect(editable.querySelector("tbody tr")?.querySelectorAll("td")).toHaveLength(4);
    cleanup();

    const { container: readonly } = renderList(<PersonalList list={familyList()} pk={7} editable={false} />);
    expect(readonly.querySelectorAll("thead th")).toHaveLength(3);
    expect(readonly.querySelector("tbody tr")?.querySelectorAll("td")).toHaveLength(3);
  });

  it("a read-only user gets no add button and no pop-up on a row click", () => {
    const { container } = renderList(<PersonalList list={educationList({ editable: false })} pk={7} editable={false} />);

    expect(screen.queryByRole("button", { name: "+ нэмэх" })).toBeNull();
    const row = container.querySelector("tbody tr") as HTMLElement;
    expect(row.getAttribute("class")).toBe("");
    fireEvent.click(row);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(openLegacyEmployee).not.toHaveBeenCalled();
  });

  it("a late answer for a closed pop-up does not close or change the pop-up opened after it", async () => {
    let release!: () => void;
    writeGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const list = educationList({
      count: 2,
      rows: [
        { key: "3", cells: ["Гурав", "2010", "3.0", "D-3"] },
        { key: "5", cells: ["Тав", "2011", "3.1", "D-5"] },
      ],
    });
    const { container } = renderList(<PersonalList list={list} pk={7} editable={true} />);

    fireEvent.click(container.querySelector("tbody tr") as HTMLElement);
    await screen.findByRole("heading", { name: "Сурсан сургууль: засах" });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([r]) => (r as Request).method === "POST")).toBe(true));

    // The pop-up of row 3 closes while its save is still in flight, and row 5's pop-up opens with typed text.
    fireEvent.click(screen.getByRole("button", { name: "Болих" }));
    const rows = container.querySelectorAll("tbody tr");
    fireEvent.click(rows[1] as HTMLElement);
    await waitFor(() => expect((document.querySelector("form input[name='school']") as HTMLInputElement)?.value).toBe("ХИС"));
    fireEvent.change(document.querySelector("form input[name='school']") as HTMLInputElement, {
      target: { value: "Шинэ" },
    });

    await act(async () => {
      release();
    });
    // Longer than the pop-up exit (250 ms fallback), so a wrongly closed pop-up would be gone by now.
    await new Promise((resolve) => setTimeout(resolve, 400));

    expect(document.querySelector("[data-leaving]")).toBeNull();
    expect(screen.getByRole("heading", { name: "Сурсан сургууль: засах" })).not.toBeNull();
    expect((document.querySelector("form input[name='school']") as HTMLInputElement).value).toBe("Шинэ");
    expect(document.querySelector(".bg-red-50")).toBeNull();
  });

  it("a pop-up list's add pop-up closes through its own «Болих» and leaves no dialog behind", async () => {
    renderList(<PersonalList list={educationList()} pk={7} editable={true} />);

    fireEvent.click(screen.getByRole("button", { name: "+ нэмэх" }));
    await screen.findByRole("heading", { name: "Сурсан сургууль: нэмэх" });
    fireEvent.click(screen.getByRole("button", { name: "Болих" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Сурсан сургууль: нэмэх" })).toBeNull());
  });
});
