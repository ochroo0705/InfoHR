import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { SelfFormListOut, SelfFormListRowOut } from "../../api/selfforms";
import { SelfFormListPage } from "./SelfFormListPage";

// The API client is replaced by a stub that answers by path, so the real hooks run (as SlotsPage.test.tsx).
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const SUBMITTED: SelfFormListRowOut = {
  id: 5,
  label: "Нягтлан бодогч",
  branch: "Төв оффис",
  state: "Илгээсэн",
  badge: "bg-emerald-50 text-emerald-800",
  when_label: "2026-11-20 09:15",
  when_kind: "sent",
  show_path: "/employees/self-forms/5/",
  hire_path: "/employees/new/?selfform=5",
};

const OPEN: SelfFormListRowOut = {
  id: 6,
  label: "Жолооч",
  branch: "—",
  state: "Нээлттэй",
  badge: "bg-sky-50 text-sky-800",
  when_label: "2026-12-01 00:00",
  when_kind: "expires",
  show_path: "/employees/self-forms/6/",
  hire_path: "",
};

// A submitted form whose «Хугацаа» is the expiry, not the submission (the API's when_kind decides the prefix).
const SUBMITTED_EXPIRES: SelfFormListRowOut = {
  ...SUBMITTED,
  id: 7,
  label: "Хүргэгч",
  when_label: "2026-12-05 10:00",
  when_kind: "expires",
  show_path: "/employees/self-forms/7/",
  hire_path: "/employees/new/?selfform=7",
};

const FORM: SelfFormListOut["form"] = {
  branch_required: false,
  branches: [{ value: 3, label: "Төв оффис" }],
  default_hours: 72,
  max_hours: 8760,
  labels: { label: "Нэр (зөвхөн HR-д харагдана)", branch: "Салбар", hours: "Хүчинтэй хугацаа (цаг)" },
  help: { label: "Ажилтны нэр эсвэл ямар ажлын байранд авахыг бичнэ.", hours: "Хоосон бол өгөгдмөл 72 цаг." },
};

function listAnswer(rows: SelfFormListRowOut[], waiting = 3): SelfFormListOut {
  return { rows, waiting, form: FORM, intro: "Танилцуулга" };
}

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function Probe() {
  const location = useLocation();
  return (
    <>
      <div data-testid="loc">{location.pathname + location.search}</div>
      <div data-testid="state">{JSON.stringify(location.state)}</div>
    </>
  );
}

type Entry = string | { pathname: string; state?: unknown };

function renderPage(list: SelfFormListOut, entry: Entry = "/employees/self-forms/") {
  h.get.mockImplementation(async (path: string) => {
    if (path === "/api/v1/selfforms") return ok(list);
    return { data: undefined, error: {}, response: { ok: false, status: 404 } };
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/employees/self-forms/" element={<SelfFormListPage />} />
          <Route path="*" element={<div>other page</div>} />
        </Routes>
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SelfFormListPage", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    document.title = "Info HR";
  });

  afterEach(() => {
    cleanup();
  });

  it("renders rows with badge classes from the API", async () => {
    renderPage(listAnswer([SUBMITTED, OPEN]));

    const state = await screen.findByText("Илгээсэн");
    expect(state.className).toContain("bg-emerald-50 text-emerald-800");
    expect(screen.getByText("Нээлттэй").className).toContain("bg-sky-50 text-sky-800");
    expect(screen.getByText("Нягтлан бодогч")).toBeTruthy();
    expect(screen.getByText("2026-11-20 09:15")).toBeTruthy();
  });

  it("the mobile date prefix follows when_kind, not hire_path", async () => {
    // SUBMITTED_EXPIRES has a hire_path (so it is submitted) but its when_kind is "expires": the prefix is «Дуусах: ».
    renderPage(listAnswer([SUBMITTED_EXPIRES, SUBMITTED, OPEN]));

    await screen.findByText("Хүргэгч");
    const expiring = screen.getByText("2026-12-05 10:00").closest("td")!;
    expect(expiring.textContent).toContain("Дуусах:");
    expect(expiring.textContent).not.toContain("Илгээсэн:");
    const sent = screen.getByText("2026-11-20 09:15").closest("td")!;
    expect(sent.textContent).toContain("Илгээсэн:");
    const open = screen.getByText("2026-12-01 00:00").closest("td")!;
    expect(open.textContent).toContain("Дуусах:");
  });

  it("shows waiting count", async () => {
    renderPage(listAnswer([], 4));

    expect(await screen.findByText("Хянах хүлээж буй: 4")).toBeTruthy();
  });

  it("empty state text", async () => {
    renderPage(listAnswer([]));

    expect(await screen.findByText("Анкет бүртгэгдээгүй байна.")).toBeTruthy();
  });

  it("row click goes to the show page", async () => {
    renderPage(listAnswer([SUBMITTED]));

    fireEvent.click(await screen.findByText("Нягтлан бодогч"));

    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/self-forms/5/"));
  });

  it("Нээх link goes to the hire path and does not open the row", async () => {
    renderPage(listAnswer([SUBMITTED]));

    fireEvent.click(await screen.findByText("Нээх"));

    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/employees/new/?selfform=5"));
    expect(screen.getByTestId("loc").textContent).not.toBe("/employees/self-forms/5/");
  });

  it("shows the form-level error from the API", async () => {
    renderPage(listAnswer([]));
    await screen.findByText("Хянах хүлээж буй: 3");
    h.post.mockResolvedValue(
      ok({ ok: false, id: null, show_path: "", field_errors: {}, form_errors: ["Холбоос үүсгэх эрх алга."], notice: null }),
    );

    fireEvent.click(screen.getByText("Холбоос үүсгэх"));

    expect(await screen.findByText("Холбоос үүсгэх эрх алга.")).toBeTruthy();
  });

  it("a success notice from router state renders green and is cleared from the URL", async () => {
    renderPage(listAnswer([SUBMITTED]), {
      pathname: "/employees/self-forms/",
      state: { notice: { text: "Холбоос үүсгэлээ.", tone: "success" } },
    });

    const box = await screen.findByText("Холбоос үүсгэлээ.");
    expect(box.className).toContain("bg-emerald-50");
    expect(box.className).toContain("text-emerald-800");
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("null"));
    // The text stays on screen after the state is cleared; a reload of the URL shows nothing.
    expect(screen.getByText("Холбоос үүсгэлээ.")).toBeTruthy();
  });

  it("an error notice from router state renders red", async () => {
    renderPage(listAnswer([SUBMITTED]), {
      pathname: "/employees/self-forms/",
      state: { notice: { text: "Холбоосыг цуцлаж чадсангүй.", tone: "error" } },
    });

    const box = await screen.findByText("Холбоосыг цуцлаж чадсангүй.");
    expect(box.className).toContain("bg-red-50");
    expect(box.className).toContain("text-red-700");
    expect(box.className).not.toContain("emerald");
  });
});
