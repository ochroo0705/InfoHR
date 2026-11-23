import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { SelfFormShowOut } from "../../api/selfforms";
import { SelfFormShowPage } from "./SelfFormShowPage";

// The API client is replaced by a stub that answers by path, so the real hooks run (as SelfFormListPage.test.tsx).
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const OPEN: SelfFormShowOut = {
  id: 5,
  label: "Нягтлан бодогч",
  state: "Нээлттэй",
  badge: "bg-sky-50 text-sky-800",
  state_key: "open",
  branch: "Төв оффис",
  created_label: "2026-11-20 09:15",
  when_label: "2026-12-01 00:00",
  when_title: "Дуусах",
  purged: false,
  link: "https://hr.example.test/apply/abc123",
  qr_svg: '<svg data-test="qr"></svg>',
  can_extend: true,
  can_revoke: true,
  default_hours: 72,
  hire_path: null,
  decision: null,
};

const EXPIRED: SelfFormShowOut = {
  ...OPEN,
  state: "Хугацаа дууссан",
  badge: "bg-amber-50 text-amber-800",
  state_key: "expired",
  can_revoke: false,
};

const REVOKED: SelfFormShowOut = {
  ...OPEN,
  state: "Цуцлагдсан",
  badge: "bg-slate-100 text-slate-700",
  state_key: "revoked",
  when_label: "",
  when_title: "",
  can_extend: false,
  can_revoke: false,
  decision: {
    reviewed_label: "2026-11-22 10:00",
    reviewed_by: "Бат",
    reject_reason: "",
    hr_note: "",
    employee_path: null,
  },
};

const PURGED: SelfFormShowOut = { ...OPEN, purged: true, can_extend: false, can_revoke: false };

const SUBMITTED: SelfFormShowOut = {
  ...OPEN,
  state: "Илгээсэн",
  badge: "bg-emerald-50 text-emerald-800",
  state_key: "submitted",
  when_label: "2026-11-20 09:15",
  when_title: "Илгээсэн",
  can_extend: false,
  can_revoke: false,
  hire_path: "/employees/new/?selfform=5",
};

const CONFIRMED: SelfFormShowOut = {
  ...OPEN,
  state: "Баталгаажсан",
  badge: "bg-emerald-50 text-emerald-800",
  state_key: "confirmed",
  when_label: "",
  when_title: "",
  can_extend: false,
  can_revoke: false,
  decision: {
    reviewed_label: "2026-11-22 10:00",
    reviewed_by: "Бат",
    reject_reason: "",
    hr_note: "Сайн",
    employee_path: "/employees/12/",
  },
};

const REJECTED: SelfFormShowOut = {
  ...OPEN,
  state: "Татгалзсан",
  badge: "bg-red-50 text-red-700",
  state_key: "rejected",
  when_label: "",
  when_title: "",
  can_extend: false,
  can_revoke: false,
  decision: {
    reviewed_label: "2026-11-22 10:00",
    reviewed_by: "Бат",
    reject_reason: "Бүрдүүлэлт дутуу\nБаримт ирээгүй",
    hr_note: "",
    employee_path: null,
  },
};

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

// `show` answers the GET; `action` answers a POST (extend or revoke). `missing` answers the GET with a 404.
function renderPage(
  options: {
    show?: SelfFormShowOut;
    missing?: boolean;
    forbidden?: boolean;
    action?: unknown;
    entry?: Entry;
    client?: QueryClient;
  } = {},
) {
  const entry = options.entry ?? "/employees/self-forms/5/";
  h.get.mockImplementation(async (path: string) => {
    if (options.forbidden) return { data: undefined, error: { code: "forbidden" }, response: { ok: false, status: 403 } };
    if (path === "/api/v1/selfforms/{pk}" && !options.missing) return ok(options.show ?? OPEN);
    return { data: undefined, error: { code: "not_found" }, response: { ok: false, status: 404 } };
  });
  h.post.mockImplementation(async () => ok(options.action));
  const client = options.client ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/employees/self-forms/:pk/" element={<SelfFormShowPage />} />
          <Route path="*" element={<div>other page</div>} />
        </Routes>
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SelfFormShowPage", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    document.title = "Info HR";
  });

  afterEach(() => {
    cleanup();
  });

  it("renders label, badge, dates and link", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { level: 1, name: "Нягтлан бодогч" })).toBeTruthy();
    expect(screen.getByText("Нээлттэй").className).toContain("bg-sky-50 text-sky-800");
    expect(screen.getByText("Төв оффис")).toBeTruthy();
    expect(screen.getByText("2026-11-20 09:15")).toBeTruthy();
    expect(screen.getByText("2026-12-01 00:00")).toBeTruthy();
    expect((screen.getByDisplayValue("https://hr.example.test/apply/abc123") as HTMLInputElement).readOnly).toBe(true);
    expect(document.title).toBe("Нягтлан бодогч · Өөрөө бөглөх анкет · MACS Human Capital");
  });

  it("open: shows extend and revoke", async () => {
    renderPage();

    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByRole("button", { name: "Сунгах" })).toBeTruthy();
    expect(screen.getByText("Холбоос цуцлах")).toBeTruthy();
  });

  it("expired: extend only", async () => {
    renderPage({ show: EXPIRED });

    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByRole("button", { name: "Сунгах" })).toBeTruthy();
    expect(screen.queryByText("Холбоос цуцлах")).toBeNull();
  });

  it("revoked: shows the decision block and no actions", async () => {
    renderPage({ show: REVOKED });

    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByText("Шийдвэр")).toBeTruthy();
    expect(screen.getByText(/2026-11-22 10:00, Бат/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Сунгах" })).toBeNull();
    expect(screen.queryByText("Холбоос цуцлах")).toBeNull();
  });

  it("purged: shows the note and no actions", async () => {
    renderPage({ show: PURGED });

    expect(await screen.findByText(/Хариулт устгагдсан\./)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Сунгах" })).toBeNull();
    expect(screen.queryByText("Холбоос цуцлах")).toBeNull();
  });

  it("submitted: shows the Нээх link to the hire page", async () => {
    renderPage({ show: SUBMITTED });

    const link = await screen.findByRole("link", { name: "Нээх" });
    expect(link.getAttribute("href")).toBe("/employees/new/?selfform=5");
  });

  it("confirmed: links to the employee", async () => {
    renderPage({ show: CONFIRMED });

    const link = await screen.findByRole("link", { name: "Ажилтны бүртгэл рүү" });
    expect(link.getAttribute("href")).toBe("/employees/12/");
  });

  it("extend posts the typed hours and redraws from the response", async () => {
    renderPage({
      action: {
        ok: true,
        notice: { text: "Холбоосын хугацааг сунгалаа.", tone: "success" },
        show: { ...OPEN, when_label: "2026-12-04 00:00" },
      },
    });

    await screen.findByRole("heading", { level: 1 });
    fireEvent.change(screen.getByLabelText("Хүчинтэй хугацаа (цаг)"), { target: { value: "48" } });
    fireEvent.click(screen.getByRole("button", { name: "Сунгах" }));

    await screen.findByText("2026-12-04 00:00");
    expect(h.post.mock.calls[0][0]).toBe("/api/v1/selfforms/{pk}/extend");
    expect(h.post.mock.calls[0][1]).toMatchObject({ params: { path: { pk: 5 } }, body: { hours: "48" } });
    expect(screen.getByText("Холбоосын хугацааг сунгалаа.").className).toContain("bg-emerald-50");
  });

  it("refused extend shows the service text", async () => {
    renderPage({
      action: {
        ok: false,
        notice: { text: "Хугацаа буруу байна.", tone: "error" },
        show: OPEN,
      },
    });

    await screen.findByRole("heading", { level: 1 });
    fireEvent.change(screen.getByLabelText("Хүчинтэй хугацаа (цаг)"), { target: { value: "48" } });
    fireEvent.click(screen.getByRole("button", { name: "Сунгах" }));

    const notice = await screen.findByText("Хугацаа буруу байна.");
    expect(notice.className).toContain("bg-red-50");
  });

  it("revoke needs the second click on the red button", async () => {
    renderPage({
      action: {
        ok: true,
        notice: { text: "Холбоосыг цуцаллаа.", tone: "success" },
        show: REVOKED,
      },
    });

    await screen.findByRole("heading", { level: 1 });
    fireEvent.click(screen.getByText("Холбоос цуцлах"));
    expect(h.post).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Тийм, цуцлах"));
    await screen.findByText("Шийдвэр");
    expect(h.post.mock.calls[0][0]).toBe("/api/v1/selfforms/{pk}/revoke");
  });

  it("QR missing shows the fallback text", async () => {
    renderPage({ show: { ...OPEN, qr_svg: null } });

    expect(
      await screen.findByText("QR код харуулах боломжгүй байна. Холбоосыг дээрээс хуулж илгээнэ үү."),
    ).toBeTruthy();
    expect(screen.queryByRole("img", { name: "QR код" })).toBeNull();
  });

  it("QR present is drawn in the labelled box", async () => {
    renderPage();

    const qr = await screen.findByRole("img", { name: "QR код" });
    expect(qr.querySelector("svg")).not.toBeNull();
  });

  it("unknown pk shows the not-found screen", async () => {
    renderPage({ missing: true });

    expect(await screen.findByRole("heading", { level: 1, name: "Хуудас олдсонгүй" })).toBeTruthy();
  });

  it("a success notice from router state shows once and is cleared from the URL", async () => {
    renderPage({
      entry: {
        pathname: "/employees/self-forms/5/",
        state: { notice: { text: "Холбоос үүсгэлээ. Энэ холбоосыг ажилтанд илгээнэ үү.", tone: "success" } },
      },
    });

    const notice = await screen.findByText("Холбоос үүсгэлээ. Энэ холбоосыг ажилтанд илгээнэ үү.");
    expect(notice.className).toContain("bg-emerald-50");
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("null"));
  });

  it("403 shows the forbidden screen", async () => {
    renderPage({ forbidden: true });

    expect(await screen.findByRole("heading", { level: 1, name: "Хандах эрх байхгүй" })).toBeTruthy();
  });

  it("rejected: shows the reject reason in a pre-line block and no date row", async () => {
    renderPage({ show: REJECTED });

    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByText("Татгалзсан шалтгаан")).toBeTruthy();
    expect(screen.getByText(/Бүрдүүлэлт дутуу/).className).toContain("whitespace-pre-line");
    expect(screen.queryByText("Дуусах")).toBeNull();
    expect(screen.queryByText("Илгээсэн")).toBeNull();
  });

  it("revoked: shows no date row", async () => {
    renderPage({ show: REVOKED });

    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByText("Дуусах")).toBeNull();
    expect(screen.queryByText("Илгээсэн")).toBeNull();
  });

  it("a double click on Сунгах sends one request", async () => {
    renderPage({
      action: { ok: true, notice: { text: "Холбоосын хугацааг сунгалаа.", tone: "success" }, show: OPEN },
    });

    await screen.findByRole("heading", { level: 1 });
    fireEvent.change(screen.getByLabelText("Хүчинтэй хугацаа (цаг)"), { target: { value: "48" } });
    const button = screen.getByRole("button", { name: "Сунгах" });
    fireEvent.click(button);
    fireEvent.click(button);

    await screen.findByText("Холбоосын хугацааг сунгалаа.");
    expect(h.post).toHaveBeenCalledTimes(1);
  });

  it("typed hours stay in the box after a refused extend", async () => {
    renderPage({ action: { ok: false, notice: { text: "Хугацаа буруу байна.", tone: "error" }, show: OPEN } });

    await screen.findByRole("heading", { level: 1 });
    const input = screen.getByLabelText("Хүчинтэй хугацаа (цаг)") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "48" } });
    fireEvent.click(screen.getByRole("button", { name: "Сунгах" }));

    await screen.findByText("Хугацаа буруу байна.");
    expect(input.value).toBe("48");
  });

  it("extend refreshes the list and the nav prefixes", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const spy = vi.spyOn(client, "invalidateQueries");
    renderPage({
      client,
      action: { ok: true, notice: { text: "Холбоосын хугацааг сунгалаа.", tone: "success" }, show: OPEN },
    });

    await screen.findByRole("heading", { level: 1 });
    fireEvent.click(screen.getByRole("button", { name: "Сунгах" }));

    await screen.findByText("Холбоосын хугацааг сунгалаа.");
    expect(spy).toHaveBeenCalledWith({ queryKey: ["selfforms"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["nav"] });
  });

  it("revoke: the details starts closed and the post happens only after the red button", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const spy = vi.spyOn(client, "invalidateQueries");
    renderPage({
      client,
      action: { ok: true, notice: { text: "Холбоосыг цуцаллаа.", tone: "success" }, show: REVOKED },
    });

    await screen.findByRole("heading", { level: 1 });
    const details = screen.getByText("Холбоос цуцлах").closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(h.post).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Холбоос цуцлах"));
    expect(details.open).toBe(true);
    expect(h.post).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Тийм, цуцлах"));
    await screen.findByText("Шийдвэр");
    expect(h.post).toHaveBeenCalledTimes(1);
    expect(h.post.mock.calls[0][0]).toBe("/api/v1/selfforms/{pk}/revoke");
    expect(spy).toHaveBeenCalledWith({ queryKey: ["selfforms"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["nav"] });
  });
});
