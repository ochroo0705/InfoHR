import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PageFormElement, PageFormProvider, usePageField, usePageFormState } from "./PageForm";
import { SaveBar } from "./SaveBar";

// fetch is stubbed before the api client is imported (openapi-fetch captures fetch when it is created), as in
// api/employeeWrites.test.tsx. The save answers are queued per test; a save can be held until the test releases it.
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

let appendSpy: { mock: { calls: unknown[][] }; mockRestore: () => void };
let saveAnswers: { status: number; body: unknown; gate?: Promise<void> }[];

const OK_RESULT = { ok: true, field_errors: {}, form_errors: [], conflicts: {}, loaded: "L2", si_loaded: "", tab: "" };

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

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
    placeholder: "",
    required: false,
    value: "",
    ...overrides,
  };
}

const PAGE_FORM = {
  loaded: "L1",
  si_loaded: "",
  fields: [field({ name: "phone", label: "Утас", value: "99112233" })],
};

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
      if (next.gate) await next.gate;
      return jsonResponse(next.status, next.body);
    }
    throw new Error(`unexpected request ${path}`);
  });
}

// The phone box, read through the page form, with the bar and its buttons next to it.
function Phone() {
  const box = usePageField("phone");
  if (!box.editable) return null;
  return (
    <input
      aria-label={box.label}
      value={box.value}
      aria-invalid={box.error ? "true" : undefined}
      onChange={(e) => box.set(e.target.value)}
    />
  );
}

function ErrorLine() {
  const box = usePageField("phone");
  if (!box.editable || !box.error) return null;
  return <p data-testid="box-error">{box.error.join("|")}</p>;
}

function Dirty() {
  const form = usePageFormState();
  return <p data-testid="dirty">{String(form.dirty)}</p>;
}

function renderBar(enabled = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PageFormProvider pk={7} enabled={enabled} section="work">
        <PageFormElement />
        <Phone />
        <ErrorLine />
        <Dirty />
        <SaveBar />
      </PageFormProvider>
    </QueryClientProvider>,
  );
}

// «Хадгалах» submits #emp-form with form="emp-form". jsdom does not follow that attribute for a submit button, so the
// test submits the form the way the button would.
function saveNow() {
  fireEvent.submit(document.getElementById("emp-form") as HTMLFormElement);
}

function bar(): HTMLElement {
  return document.getElementById("save-bar") as HTMLElement;
}

function isShown(): boolean {
  return bar().classList.contains("flex") && !bar().classList.contains("hidden");
}

async function editPhone(value: string) {
  fireEvent.change(await screen.findByLabelText("Утас"), { target: { value } });
}

describe("SaveBar", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    appendSpy = vi.spyOn(FormData.prototype, "append");
    saveAnswers = [];
    routeFetch();
  });

  afterEach(() => {
    appendSpy.mockRestore();
    cleanup();
  });

  it("is hidden until a box changes, shows the Django markup, and hides again when the change is undone", async () => {
    renderBar();
    await screen.findByLabelText("Утас");
    expect(bar().classList.contains("hidden")).toBe(true);
    expect(bar().className).toContain("sticky bottom-0 z-40 mt-6");

    await editPhone("55555555");
    expect(isShown()).toBe(true);
    expect(screen.getByText("Хадгалаагүй өөрчлөлт байна")).toBeTruthy();
    expect(screen.getByText("Болих").id).toBe("save-cancel");

    await editPhone("99112233");
    expect(isShown()).toBe(false);
  });

  it("Болих clears the edit, hides the bar and refetches the page form", async () => {
    renderBar();
    await editPhone("55555555");
    const before = callsTo("/page-form");

    fireEvent.click(screen.getByText("Болих"));

    expect(isShown()).toBe(false);
    expect((screen.getByLabelText("Утас") as HTMLInputElement).value).toBe("99112233");
    await waitFor(() => expect(callsTo("/page-form")).toBe(before + 1));
  });

  it("Хадгалах posts only the edited name with loaded, and an ok result hides the bar", async () => {
    renderBar();
    await editPhone("55555555");
    saveAnswers.push({ status: 200, body: OK_RESULT });

    saveNow();

    await waitFor(() => expect(isShown()).toBe(false));
    const values = appendSpy.mock.calls.filter(([key]) => key === "values_json");
    expect(values).toHaveLength(1);
    expect(JSON.parse(String(values[0][1]))).toEqual({ phone: "55555555", loaded: "L1" });
  });

  it("a field error shows under its box and keeps the bar visible with the edit", async () => {
    renderBar();
    await editPhone("55555555");
    saveAnswers.push({
      status: 200,
      body: { ok: false, field_errors: { phone: ["Буруу утас"] }, form_errors: [], conflicts: {}, loaded: "L1", si_loaded: "", tab: "work" },
    });

    saveNow();

    await waitFor(() => expect(screen.getByTestId("box-error").textContent).toBe("Буруу утас"));
    expect(isShown()).toBe(true);
    expect((screen.getByLabelText("Утас") as HTMLInputElement).getAttribute("aria-invalid")).toBe("true");
  });

  it("a form-wide error sits inside the bar in the red box", async () => {
    renderBar();
    await editPhone("55555555");
    saveAnswers.push({ status: 400, body: { field_errors: {}, form_errors: ["Нэвтрэх эрхгүй"] } });

    saveNow();

    const message = await screen.findByText("Нэвтрэх эрхгүй");
    expect(bar().contains(message)).toBe(true);
    expect(message.parentElement?.className).toBe("mb-3 rounded bg-red-50 p-2 text-sm text-red-700");
    expect(isShown()).toBe(true);
  });

  it("Хадгалах is disabled while a save is pending, and a double click sends one request", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    renderBar();
    await editPhone("55555555");
    saveAnswers.push({ status: 200, body: OK_RESULT, gate });

    const save = screen.getByText("Хадгалах") as HTMLButtonElement;
    saveNow();
    saveNow();

    await waitFor(() => expect(save.disabled).toBe(true));
    expect((screen.getByText("Болих") as HTMLButtonElement).disabled).toBe(true);
    release();
    await waitFor(() => expect(save.disabled).toBe(false));
    expect(callsTo("/save")).toBe(1);
  });
});
