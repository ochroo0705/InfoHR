import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useUnsavedGuard } from "../../lib/unsaved";
import { PageFormProvider, SAVE_FAILED_TEXT, usePageField, usePageFormState } from "./PageForm";

// fetch is stubbed before the api client is imported (openapi-fetch captures fetch when it is created), as in
// api/employeeWrites.test.tsx. Each test sets the page form it serves and the save answers it queues.
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
let pageForm: unknown;
let saveAnswers: { status: number; body: unknown; gate?: Promise<void> }[];

const OK_RESULT = { ok: true, field_errors: {}, form_errors: [], conflicts: {}, loaded: "L2", si_loaded: "S2", tab: "" };

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

// The page form as the API sends it: a phone box (header) and a salary box (si- prefix).
function pageFormBody(overrides: Record<string, unknown> = {}) {
  return {
    loaded: "L1",
    si_loaded: "S1",
    fields: [
      field({ name: "phone", label: "Утас", value: "99112233" }),
      field({ name: "si-salary", label: "Цалин", kind: "number", value: "1000" }),
    ],
    ...overrides,
  };
}

function urlOf(input: unknown): string {
  return typeof input === "string" ? input : (input as Request).url;
}

function callsTo(suffix: string): number {
  return fetchMock.mock.calls.filter((call) => new URL(urlOf(call[0])).pathname.endsWith(suffix)).length;
}

// The values_json of every page save, as the form posted them.
function sentValues(): Record<string, string>[] {
  return appendSpy.mock.calls
    .filter(([key]) => key === "values_json")
    .map(([, value]) => JSON.parse(String(value)) as Record<string, string>);
}

function routeFetch() {
  fetchMock.mockImplementation(async (input: unknown) => {
    const path = new URL(urlOf(input)).pathname;
    if (path.endsWith("/page-form")) return jsonResponse(200, pageForm);
    if (path.endsWith("/save")) {
      const next = saveAnswers.shift();
      if (!next) throw new Error("no save answer queued");
      if (next.gate) await next.gate;
      return jsonResponse(next.status, next.body);
    }
    throw new Error(`unexpected request ${path}`);
  });
}

// A test box: the field named `name`, and the form-wide state. The buttons call the state directly.
function Probe({ name }: { name: string }) {
  const box = usePageField(name);
  const form = usePageFormState();
  return (
    <div>
      {box.editable ? (
        <>
          <input
            aria-label={box.label}
            value={box.value}
            aria-invalid={box.error ? "true" : undefined}
            onChange={(e) => box.set(e.target.value)}
          />
          <p data-testid="changed">{String(box.changed)}</p>
          <p data-testid="error">{box.error?.join("|") ?? ""}</p>
          <p data-testid="conflict">{box.conflict ?? ""}</p>
          <p data-testid="resolve">{box.resolve}</p>
          <button type="button" onClick={() => box.setResolve("theirs")}>
            theirs
          </button>
        </>
      ) : (
        <p data-testid="read-only">{name}</p>
      )}
      <p data-testid="dirty">{String(form.dirty)}</p>
      <p data-testid="form-errors">{form.formErrors.join("|")}</p>
      <button type="button" onClick={() => void form.save()}>
        save-now
      </button>
      <button type="button" onClick={form.cancel}>
        cancel-now
      </button>
    </div>
  );
}

function UnloadGuard() {
  useUnsavedGuard();
  return null;
}

function renderForm(
  ui: ReactNode,
  section = "work",
  enabled = true,
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  return render(
    <QueryClientProvider client={client}>
      <PageFormProvider pk={7} enabled={enabled} section={section}>
        {ui}
      </PageFormProvider>
    </QueryClientProvider>,
  );
}

async function editPhone(value: string) {
  fireEvent.change(await screen.findByLabelText("Утас"), { target: { value } });
}

describe("PageFormProvider", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    appendSpy = vi.spyOn(FormData.prototype, "append");
    pageForm = pageFormBody();
    saveAnswers = [];
    routeFetch();
  });

  afterEach(() => {
    appendSpy.mockRestore();
    cleanup();
  });

  it("a changed box is dirty, and setting it back to the stored value clears the change", async () => {
    renderForm(<Probe name="phone" />);
    await editPhone("55555555");
    expect(screen.getByTestId("changed").textContent).toBe("true");
    expect(screen.getByTestId("dirty").textContent).toBe("true");

    await editPhone("99112233");
    expect(screen.getByTestId("changed").textContent).toBe("false");
    expect(screen.getByTestId("dirty").textContent).toBe("false");
  });

  it("a name the page form does not have is read-only", async () => {
    renderForm(<Probe name="not-on-page" />);
    expect(screen.getByTestId("read-only").textContent).toBe("not-on-page");
  });

  it("a save posts only the edited names with loaded, si-loaded and the current section as tab", async () => {
    renderForm(<Probe name="phone" />, "salary");
    await editPhone("55555555");
    saveAnswers.push({ status: 200, body: OK_RESULT });

    fireEvent.click(screen.getByText("save-now"));

    await waitFor(() => expect(sentValues()).toHaveLength(1));
    expect(sentValues()[0]).toEqual({ phone: "55555555", loaded: "L1", "si-loaded": "S1" });
    expect(appendSpy.mock.calls.filter(([key]) => key === "tab")).toEqual([["tab", "salary"]]);
  });

  it("an ok result clears the edits; the refetched page form shows the saved value", async () => {
    renderForm(<Probe name="phone" />);
    await editPhone("55555555");
    pageForm = pageFormBody({ fields: [field({ name: "phone", label: "Утас", value: "55555555" })] });
    saveAnswers.push({ status: 200, body: OK_RESULT });

    fireEvent.click(screen.getByText("save-now"));

    await waitFor(() => expect(screen.getByTestId("dirty").textContent).toBe("false"));
    expect(screen.getByTestId("changed").textContent).toBe("false");
    expect((screen.getByLabelText("Утас") as HTMLInputElement).value).toBe("55555555");
  });

  it("a refused field error keeps the edit and shows the message on its box", async () => {
    renderForm(<Probe name="phone" />);
    await editPhone("55555555");
    saveAnswers.push({
      status: 200,
      body: { ok: false, field_errors: { phone: ["Буруу утас"] }, form_errors: [], conflicts: {}, loaded: "L1", si_loaded: "S1", tab: "work" },
    });

    fireEvent.click(screen.getByText("save-now"));

    await waitFor(() => expect(screen.getByTestId("error").textContent).toBe("Буруу утас"));
    expect(screen.getByTestId("dirty").textContent).toBe("true");
    expect((screen.getByLabelText("Утас") as HTMLInputElement).value).toBe("55555555");
  });

  it("a clash stores the conflict, and the re-save sends resolve-<name> with the fresh loaded snapshot", async () => {
    renderForm(<Probe name="phone" />);
    await editPhone("55555555");
    saveAnswers.push(
      {
        status: 200,
        body: { ok: false, field_errors: {}, form_errors: [], conflicts: { phone: "77000000" }, loaded: "L-FRESH", si_loaded: "", tab: "work" },
      },
      { status: 200, body: OK_RESULT },
    );

    fireEvent.click(screen.getByText("save-now"));
    await waitFor(() => expect(screen.getByTestId("conflict").textContent).toBe("77000000"));
    expect(screen.getByTestId("resolve").textContent).toBe("mine");
    expect(screen.getByTestId("dirty").textContent).toBe("true");

    fireEvent.click(screen.getByText("save-now"));
    await waitFor(() => expect(sentValues()).toHaveLength(2));
    // The fresh loaded replaces the page's one; si_loaded was empty in the clash, so the page's si-loaded stays.
    expect(sentValues()[1]).toEqual({
      phone: "55555555",
      loaded: "L-FRESH",
      "si-loaded": "S1",
      "resolve-phone": "mine",
    });
  });

  it("picking theirs on a clash changes the resolve choice without a request", async () => {
    renderForm(<Probe name="phone" />);
    await editPhone("55555555");
    saveAnswers.push({
      status: 200,
      body: { ok: false, field_errors: {}, form_errors: [], conflicts: { phone: "77000000" }, loaded: "L1", si_loaded: "S1", tab: "work" },
    });
    fireEvent.click(screen.getByText("save-now"));
    await waitFor(() => expect(screen.getByTestId("conflict").textContent).toBe("77000000"));
    const before = callsTo("/save");

    fireEvent.click(screen.getByText("theirs"));

    expect(screen.getByTestId("resolve").textContent).toBe("theirs");
    expect(callsTo("/save")).toBe(before);
  });

  it("a refused save with a 4xx shows the API's form errors, or Django's text when there are none", async () => {
    renderForm(<Probe name="phone" />);
    await editPhone("55555555");
    saveAnswers.push({ status: 400, body: { field_errors: {}, form_errors: ["Нэвтрэх эрхгүй"] } });

    fireEvent.click(screen.getByText("save-now"));
    await waitFor(() => expect(screen.getByTestId("form-errors").textContent).toBe("Нэвтрэх эрхгүй"));
    expect(screen.getByTestId("dirty").textContent).toBe("true");

    saveAnswers.push({ status: 400, body: { field_errors: {}, form_errors: [] } });
    fireEvent.click(screen.getByText("save-now"));
    await waitFor(() => expect(screen.getByTestId("form-errors").textContent).toBe(SAVE_FAILED_TEXT));
  });

  it("a second save while one is pending sends one request", async () => {
    renderForm(<Probe name="phone" />);
    await editPhone("55555555");
    saveAnswers.push({ status: 200, body: OK_RESULT });

    fireEvent.click(screen.getByText("save-now"));
    fireEvent.click(screen.getByText("save-now"));

    await waitFor(() => expect(screen.getByTestId("dirty").textContent).toBe("false"));
    expect(callsTo("/save")).toBe(1);
  });

  it("cancel clears the edits and refetches the page form", async () => {
    renderForm(<Probe name="phone" />);
    await editPhone("55555555");
    const before = callsTo("/page-form");

    fireEvent.click(screen.getByText("cancel-now"));

    expect(screen.getByTestId("dirty").textContent).toBe("false");
    expect((screen.getByLabelText("Утас") as HTMLInputElement).value).toBe("99112233");
    await waitFor(() => expect(callsTo("/page-form")).toBe(before + 1));
  });

  it("the unload guard is prevented only while something is unsaved", async () => {
    // PageForm no longer adds its own listener: the page-level guard (unsaved.ts useUnsavedGuard, used by EmployeePage)
    // is mounted here so the registry's beforeunload behaviour is still checked through the form.
    renderForm(
      <>
        <UnloadGuard />
        <Probe name="phone" />
      </>,
    );
    await screen.findByLabelText("Утас");

    const clean = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);

    await editPhone("55555555");
    const unsaved = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unsaved);
    expect(unsaved.defaultPrevented).toBe(true);
  });

  it("a user with only the salary right sends si-loaded and no loaded when the header snapshot is empty", async () => {
    pageForm = pageFormBody({ loaded: "", fields: [field({ name: "si-salary", label: "Цалин", kind: "number", value: "1000" })] });
    renderForm(<Probe name="si-salary" />);
    fireEvent.change(await screen.findByLabelText("Цалин"), { target: { value: "1200" } });
    saveAnswers.push({ status: 200, body: OK_RESULT });

    fireEvent.click(screen.getByText("save-now"));

    await waitFor(() => expect(sentValues()).toHaveLength(1));
    expect(sentValues()[0]).toEqual({ "si-salary": "1200", "si-loaded": "S1" });
    expect("loaded" in sentValues()[0]).toBe(false);
  });

  it("a second save right after an ok save uses the refreshed snapshot of the page form", async () => {
    renderForm(<Probe name="phone" />);
    await editPhone("55555555");
    // The ok save invalidates the page form; the refetch answers with a new snapshot (L2).
    pageForm = pageFormBody({ loaded: "L2", fields: [field({ name: "phone", label: "Утас", value: "55555555" })] });
    saveAnswers.push({ status: 200, body: OK_RESULT });
    fireEvent.click(screen.getByText("save-now"));
    await waitFor(() => expect(screen.getByTestId("dirty").textContent).toBe("false"));
    await waitFor(() => expect(callsTo("/page-form")).toBe(2));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    await editPhone("66666666");
    saveAnswers.push({ status: 200, body: OK_RESULT });
    fireEvent.click(screen.getByText("save-now"));

    await waitFor(() => expect(sentValues()).toHaveLength(2));
    expect(sentValues()[0].loaded).toBe("L1");
    expect(sentValues()[1].loaded).toBe("L2");
  });

  it("a refetch while a plain edit is pending: the save keeps the edit's base and the others' refetched values", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    pageForm = pageFormBody({ loaded: JSON.stringify({ phone: "99112233", other: "O1" }) });
    renderForm(<Probe name="phone" />, "work", true, client);
    await editPhone("55555555");
    // A colleague saved in the meantime: the refetch brings a newer phone (Z) and a newer other (O2).
    pageForm = pageFormBody({
      loaded: JSON.stringify({ phone: "77000000", other: "O2" }),
      fields: [field({ name: "phone", label: "Утас", value: "77000000" })],
    });
    await act(async () => {
      await client.invalidateQueries({ queryKey: ["employee", 7, "page-form"], exact: true });
    });
    // React Query batches the observers' notification on a timer: one tick lets the provider render the refetched form.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    saveAnswers.push({ status: 200, body: OK_RESULT });

    fireEvent.click(screen.getByText("save-now"));

    await waitFor(() => expect(sentValues()).toHaveLength(1));
    expect(JSON.parse(sentValues()[0].loaded)).toEqual({ phone: "99112233", other: "O2" });
  });

  it("a refetch while an si- edit is pending: the si-loaded sent keeps the edit's base", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    pageForm = pageFormBody({ si_loaded: JSON.stringify({ salary: "1000", bonus: "S1" }) });
    renderForm(<Probe name="si-salary" />, "work", true, client);
    fireEvent.change(await screen.findByLabelText("Цалин"), { target: { value: "1200" } });
    pageForm = pageFormBody({
      si_loaded: JSON.stringify({ salary: "2000", bonus: "S2" }),
      fields: [field({ name: "si-salary", label: "Цалин", kind: "number", value: "2000" })],
    });
    await act(async () => {
      await client.invalidateQueries({ queryKey: ["employee", 7, "page-form"], exact: true });
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    saveAnswers.push({ status: 200, body: OK_RESULT });

    fireEvent.click(screen.getByText("save-now"));

    await waitFor(() => expect(sentValues()).toHaveLength(1));
    expect(JSON.parse(sentValues()[0]["si-loaded"])).toEqual({ salary: "1000", bonus: "S2" });
  });

  it("an edit made while a save is in flight survives the ok", async () => {
    renderForm(<Probe name="phone" />);
    await editPhone("55555555");
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    saveAnswers.push({ status: 200, body: OK_RESULT, gate });

    fireEvent.click(screen.getByText("save-now"));
    await waitFor(() => expect(sentValues()).toHaveLength(1));
    await editPhone("66666666");
    const before = callsTo("/page-form");
    release();
    await waitFor(() => expect(callsTo("/page-form")).toBe(before + 1));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(screen.getByTestId("dirty").textContent).toBe("true");
    expect((screen.getByLabelText("Утас") as HTMLInputElement).value).toBe("66666666");
  });

  describe("per-name bases from the displayed snapshot (real JSON snapshots)", () => {
    // A second box, without the form-level widgets of Probe.
    function Box({ name }: { name: string }) {
      const box = usePageField(name);
      if (!box.editable) return null;
      return <input aria-label={box.label} value={box.value} onChange={(e) => box.set(e.target.value)} />;
    }

    // Lets the provider render the refetched page form (React Query notifies observers on a timer).
    async function flush() {
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    }

    function snapshotPage(loaded: Record<string, string>, values: Record<string, string>) {
      return {
        loaded: JSON.stringify(loaded),
        si_loaded: "",
        fields: [
          field({ name: "phone", label: "Утас", value: values.phone ?? "" }),
          field({ name: "other", label: "Бусад", value: values.other ?? "" }),
        ],
      };
    }

    function sentLoaded(index: number): Record<string, string> {
      return JSON.parse(sentValues()[index].loaded) as Record<string, string>;
    }

    it("the base of a name is the DISPLAYED value, not a refused save's fresh snapshot", async () => {
      pageForm = snapshotPage({ phone: "99112233", other: "S1" }, { phone: "99112233", other: "S1" });
      renderForm(
        <>
          <Probe name="phone" />
          <Box name="other" />
        </>,
      );
      await editPhone("55555555");
      // The phone save is refused; the server's snapshot shows a colleague changed `other` to S2. The boxes still show S1.
      saveAnswers.push({
        status: 200,
        body: { ok: false, field_errors: { phone: ["Буруу утас"] }, form_errors: [], conflicts: {}, loaded: JSON.stringify({ phone: "99112233", other: "S2" }), si_loaded: "", tab: "work" },
      });
      fireEvent.click(screen.getByText("save-now"));
      await waitFor(() => expect(screen.getByTestId("error").textContent).toBe("Буруу утас"));

      fireEvent.change(await screen.findByLabelText("Бусад"), { target: { value: "V" } });
      saveAnswers.push({ status: 200, body: OK_RESULT });
      fireEvent.click(screen.getByText("save-now"));

      await waitFor(() => expect(sentValues()).toHaveLength(2));
      expect(sentLoaded(1)).toEqual({ phone: "99112233", other: "S1" });
    });

    it("a base is retained across a refused save for a name that did not conflict", async () => {
      pageForm = snapshotPage({ phone: "99112233", other: "O1" }, { phone: "99112233", other: "O1" });
      renderForm(<Probe name="phone" />);
      await editPhone("55555555");
      saveAnswers.push({
        status: 200,
        body: { ok: false, field_errors: { phone: ["Буруу утас"] }, form_errors: [], conflicts: {}, loaded: JSON.stringify({ phone: "99112233", other: "O2" }), si_loaded: "", tab: "work" },
      });
      fireEvent.click(screen.getByText("save-now"));
      await waitFor(() => expect(screen.getByTestId("error").textContent).toBe("Буруу утас"));

      saveAnswers.push({ status: 200, body: OK_RESULT });
      fireEvent.click(screen.getByText("save-now"));

      await waitFor(() => expect(sentValues()).toHaveLength(2));
      // phone keeps its base (what the user saw); other is not edited, so it carries the server's newest value.
      expect(sentLoaded(1)).toEqual({ phone: "99112233", other: "O2" });
    });

    it("a base is dropped for a conflicted name: the fresh value is sent and the re-save carries resolve-<name>", async () => {
      pageForm = snapshotPage({ phone: "99112233" }, { phone: "99112233" });
      renderForm(<Probe name="phone" />);
      await editPhone("55555555");
      saveAnswers.push(
        {
          status: 200,
          body: { ok: false, field_errors: {}, form_errors: [], conflicts: { phone: "77000000" }, loaded: JSON.stringify({ phone: "77000000" }), si_loaded: "", tab: "work" },
        },
        { status: 200, body: OK_RESULT },
      );
      fireEvent.click(screen.getByText("save-now"));
      await waitFor(() => expect(screen.getByTestId("conflict").textContent).toBe("77000000"));

      fireEvent.click(screen.getByText("save-now"));

      await waitFor(() => expect(sentValues()).toHaveLength(2));
      expect(sentLoaded(1)).toEqual({ phone: "77000000" });
      expect(sentValues()[1]["resolve-phone"]).toBe("mine");
    });

    it("an edit set back to the stored value, then edited after a refetch, captures a NEW base from the new snapshot", async () => {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      pageForm = snapshotPage({ phone: "A" }, { phone: "A" });
      renderForm(<Probe name="phone" />, "work", true, client);
      await editPhone("B");
      await editPhone("A");
      pageForm = snapshotPage({ phone: "C" }, { phone: "C" });
      await act(async () => {
        await client.invalidateQueries({ queryKey: ["employee", 7, "page-form"], exact: true });
      });
      await flush();
      await editPhone("D");
      saveAnswers.push({ status: 200, body: OK_RESULT });

      fireEvent.click(screen.getByText("save-now"));

      await waitFor(() => expect(sentValues()).toHaveLength(1));
      expect(sentLoaded(0)).toEqual({ phone: "C" });
    });

    it("a kept in-flight edit of the saved name drops its base: the next save uses the refreshed snapshot", async () => {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      pageForm = snapshotPage({ phone: "99112233" }, { phone: "99112233" });
      renderForm(<Probe name="phone" />, "work", true, client);
      await editPhone("55555555");
      // The server will hold V1 after the save: the refetch answers with that snapshot.
      pageForm = snapshotPage({ phone: "55555555" }, { phone: "55555555" });
      let release: () => void = () => undefined;
      const gate = new Promise<void>((resolve) => {
        release = resolve;
      });
      saveAnswers.push({ status: 200, body: OK_RESULT, gate });
      fireEvent.click(screen.getByText("save-now"));
      await waitFor(() => expect(sentValues()).toHaveLength(1));
      await editPhone("66666666");
      const before = callsTo("/page-form");

      release();
      await waitFor(() => expect(callsTo("/page-form")).toBe(before + 1));
      await flush();
      saveAnswers.push({ status: 200, body: OK_RESULT });
      fireEvent.click(screen.getByText("save-now"));

      await waitFor(() => expect(sentValues()).toHaveLength(2));
      expect(sentLoaded(1)).toEqual({ phone: "55555555" });
      expect(sentValues()[1].phone).toBe("66666666");
    });

    it("a kept edit after an ok save sends the ok result's snapshot, even before the refetch shows it", async () => {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      pageForm = snapshotPage({ phone: "99112233" }, { phone: "99112233" });
      renderForm(<Probe name="phone" />, "work", true, client);
      await editPhone("55555555");
      let release: () => void = () => undefined;
      const gate = new Promise<void>((resolve) => {
        release = resolve;
      });
      // The ok result carries the server's fresh snapshot (the saved value). The page form still answers the old one,
      // so the refetch that follows the ok does not move the page's snapshot yet.
      saveAnswers.push({ status: 200, body: { ...OK_RESULT, loaded: JSON.stringify({ phone: "55555555" }) }, gate });
      fireEvent.click(screen.getByText("save-now"));
      await waitFor(() => expect(sentValues()).toHaveLength(1));
      await editPhone("66666666");
      const before = callsTo("/page-form");

      release();
      await waitFor(() => expect(callsTo("/page-form")).toBe(before + 1));
      await flush();
      saveAnswers.push({ status: 200, body: OK_RESULT });
      fireEvent.click(screen.getByText("save-now"));

      await waitFor(() => expect(sentValues()).toHaveLength(2));
      expect(sentLoaded(1)).toEqual({ phone: "55555555" });
      expect(sentValues()[1].phone).toBe("66666666");
    });
  });
});
