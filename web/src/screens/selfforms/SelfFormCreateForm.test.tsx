import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { SelfFormCreateFormOut } from "../../api/selfforms";
import { SelfFormCreateForm } from "./SelfFormCreateForm";

const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const FORM: SelfFormCreateFormOut = {
  branch_required: false,
  branches: [
    { value: 3, label: "Төв оффис" },
    { value: 4, label: "Салбар 2" },
  ],
  default_hours: 72,
  max_hours: 8760,
  labels: { label: "Нэр (зөвхөн HR-д харагдана)", branch: "Салбар", hours: "Хүчинтэй хугацаа (цаг)" },
  help: { label: "Ажилтны нэр эсвэл ямар ажлын байранд авахыг бичнэ.", hours: "Хоосон бол өгөгдмөл 72 цаг." },
};

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

const CREATED = {
  ok: true,
  id: 9,
  show_path: "/employees/self-forms/9/",
  field_errors: {},
  form_errors: [],
  notice: { text: "Холбоос үүсгэлээ. Энэ холбоосыг ажилтанд илгээнэ үү." },
};

// The show page stands in for Task 10's page: it shows the router state the form passed on.
function ShowStub() {
  const location = useLocation();
  return (
    <div>
      <div data-testid="loc">{location.pathname}</div>
      <div data-testid="state">{JSON.stringify(location.state)}</div>
    </div>
  );
}

function renderForm(form: SelfFormCreateFormOut = FORM) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/employees/self-forms/"]}>
        <Routes>
          <Route path="/employees/self-forms/" element={<SelfFormCreateForm form={form} />} />
          <Route path="/employees/self-forms/9/" element={<ShowStub />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// The body of the n-th POST, as it was sent.
function postBody(index = 0): unknown {
  return (h.post.mock.calls[index][1] as { body: unknown }).body;
}

describe("SelfFormCreateForm", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("sends label, branch and hours", async () => {
    h.post.mockResolvedValue(ok({ ...CREATED, ok: false, id: null, show_path: "", notice: null }));
    renderForm();

    fireEvent.change(screen.getByLabelText(/Нэр/), { target: { value: "Жолооч" } });
    fireEvent.change(document.querySelector<HTMLSelectElement>('select[name="branch"]')!, { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText(/Хүчинтэй хугацаа/), { target: { value: "48" } });
    fireEvent.click(screen.getByText("Холбоос үүсгэх"));

    await waitFor(() => expect(h.post).toHaveBeenCalledTimes(1));
    expect(postBody()).toEqual({ label: "Жолооч", branch: 4, hours: 48 });
  });

  it("blank hours sends null", async () => {
    h.post.mockResolvedValue(ok({ ...CREATED, ok: false, id: null, show_path: "", notice: null }));
    renderForm();

    fireEvent.change(screen.getByLabelText(/Нэр/), { target: { value: "Жолооч" } });
    fireEvent.click(screen.getByText("Холбоос үүсгэх"));

    await waitFor(() => expect(h.post).toHaveBeenCalledTimes(1));
    expect(postBody()).toEqual({ label: "Жолооч", branch: null, hours: null });
  });

  it("field errors show under their boxes", async () => {
    h.post.mockResolvedValue(
      ok({
        ok: false,
        id: null,
        show_path: "",
        field_errors: { label: ["Энэ талбарыг заавал бөглөнө."], hours: ["Утга 1-ээс бага байна."] },
        form_errors: [],
        notice: null,
      }),
    );
    renderForm();

    fireEvent.click(screen.getByText("Холбоос үүсгэх"));

    // The error sits in the same box as its input, and not in the other box.
    const boxOf = (id: string) => document.getElementById(id)!.closest("div")!;
    const labelError = await screen.findByText("Энэ талбарыг заавал бөглөнө.");
    expect(boxOf("selfform-label").contains(labelError)).toBe(true);
    expect(boxOf("selfform-hours").contains(labelError)).toBe(false);
    const hoursError = screen.getByText("Утга 1-ээс бага байна.");
    expect(boxOf("selfform-hours").contains(hoursError)).toBe(true);
    expect(boxOf("selfform-label").contains(hoursError)).toBe(false);
  });

  it("success navigates to show_path with a success notice in router state", async () => {
    h.post.mockResolvedValue(ok(CREATED));
    renderForm();

    fireEvent.change(screen.getByLabelText(/Нэр/), { target: { value: "Жолооч" } });
    fireEvent.click(screen.getByText("Холбоос үүсгэх"));

    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/self-forms/9/"));
    expect(JSON.parse(screen.getByTestId("state").textContent!)).toEqual({
      notice: { text: CREATED.notice.text, tone: "success" },
    });
  });

  it("the branch select always has a blank first entry, required or not", () => {
    renderForm({ ...FORM, branch_required: false });
    const optional = document.querySelector<HTMLSelectElement>('select[name="branch"]')!;
    expect(optional.required).toBe(false);
    expect(optional.options[0].value).toBe("");
    expect(optional.options[0].textContent).toBe("");
    cleanup();

    renderForm({ ...FORM, branch_required: true });
    const required = document.querySelector<HTMLSelectElement>('select[name="branch"]')!;
    expect(required.required).toBe(true);
    expect(required.options[0].value).toBe("");
    expect(required.options[0].textContent).toBe("");
    expect(screen.getByText("Салбар *")).toBeTruthy();
  });

  it("double click sends one request", async () => {
    h.post.mockImplementation(() => new Promise(() => {}));
    renderForm();

    const button = screen.getByText("Холбоос үүсгэх");
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(h.post).toHaveBeenCalledTimes(1));
    expect(h.post).toHaveBeenCalledTimes(1);
  });
});
