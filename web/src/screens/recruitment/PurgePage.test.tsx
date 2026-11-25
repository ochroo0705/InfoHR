import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import type { RecruitPurgeOut, RecruitPurgeRowOut } from "../../api/recruitment";
import { endNavBar } from "../../lib/navBar";
import { PurgePage } from "./PurgePage";

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

const ROW_ONE: RecruitPurgeRowOut = {
  id: 11,
  name: "Бат Болд",
  vacancy_title: "Бухгалтер",
  stage_label: "Татгалзсан",
  closed: "2026-01-05",
};
const ROW_TWO: RecruitPurgeRowOut = {
  id: 12,
  name: "Ахмад Сүх",
  vacancy_title: "Нягтлан",
  stage_label: "Өөрөө татгалзсан",
  closed: "2026-02-10",
};

function purgeData(over: Partial<RecruitPurgeOut> = {}): RecruitPurgeOut {
  return { rows: [ROW_ONE, ROW_TWO], months: 12, is_admin: false, ...over };
}

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function failure(status: number) {
  return { data: undefined, error: {}, response: { ok: false, status } };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/recruitment/purge/"]}>
        <Routes>
          <Route path="/recruitment/purge/" element={<PurgePage />} />
          <Route path="/recruitment/" element={<p>vacancy list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function setPurge(data: RecruitPurgeOut) {
  h.get.mockImplementation(async () => ok(data));
}

beforeEach(() => {
  h.get.mockReset();
  h.post.mockReset();
  h.confirm.mockReset();
  h.confirm.mockResolvedValue(true);
  h.post.mockImplementation(async () => ok({ ok: true, deleted: 2 }));
});

afterEach(() => {
  cleanup();
  endNavBar();
  vi.restoreAllMocks();
  document.title = "";
});

describe("PurgePage: the list", () => {
  it("lists each old rejected candidate with vacancy, stage and closed date", async () => {
    setPurge(purgeData());
    renderPage();

    const table = await screen.findByRole("table");
    const text = table.textContent ?? "";
    expect(text).toContain("Бат Болд");
    expect(text).toContain("Бухгалтер");
    expect(text).toContain("Татгалзсан");
    expect(text).toContain("2026-01-05");
    expect(text).toContain("Ахмад Сүх");
    expect(text).toContain("Өөрөө татгалзсан");
    expect(screen.getByText("2 ажил хүсэгч")).toBeTruthy();
  });

  it("shows the empty text and no delete button when no candidate is old enough", async () => {
    setPurge(purgeData({ rows: [] }));
    renderPage();

    expect(await screen.findByText("Цэвэрлэх ажил хүсэгч олдсонгүй")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Устгах" })).toBeNull();
  });
});

describe("PurgePage: the retention sentence", () => {
  it("gives an admin the link to the retention setting", async () => {
    setPurge(purgeData({ is_admin: true, months: 6 }));
    renderPage();

    const link = await screen.findByRole("link", { name: "Хадгалах хугацаа өөрчлөх" });
    expect(link.getAttribute("href")).toBe("/admin/recruitment/recruitmentsettings/");
    expect(screen.queryByText("Хугацааг админ өөрчилнө.")).toBeNull();
    expect(screen.getByText(/6 сарын дараа устгана/)).toBeTruthy();
  });

  it("tells a non-admin that the admin changes the period, with no link", async () => {
    setPurge(purgeData({ is_admin: false, months: 12 }));
    renderPage();

    expect(await screen.findByText(/Хугацааг админ өөрчилнө\./)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Хадгалах хугацаа өөрчлөх" })).toBeNull();
    expect(screen.getByText(/12 сарын дараа устгана/)).toBeTruthy();
  });
});

describe("PurgePage: the purge", () => {
  it("asks first, and cancelling posts nothing", async () => {
    h.confirm.mockResolvedValue(false);
    setPurge(purgeData());
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Устгах" }));

    await waitFor(() => expect(h.confirm).toHaveBeenCalledTimes(1));
    expect(h.confirm.mock.calls[0][0]).toBe("2 ажил хүсэгчийг бүрмөсөн устгах уу?");
    expect(h.confirm.mock.calls[0][1]).toEqual({ ok: "Устгах" });
    expect(h.post).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("posts once on a double click and shows the count", async () => {
    setPurge(purgeData());
    renderPage();
    const button = await screen.findByRole("button", { name: "Устгах" });

    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Устгасан: 2 ажил хүсэгч."));
    expect(h.post).toHaveBeenCalledTimes(1);
    expect(String(h.post.mock.calls[0][0])).toBe("/api/v1/recruitment/purge");
  });

  it("shows 0 when the purge removes nothing", async () => {
    h.post.mockImplementation(async () => ok({ ok: true, deleted: 0 }));
    setPurge(purgeData());
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Устгах" }));

    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Устгасан: 0 ажил хүсэгч."));
  });

  it("shows the general save text when the purge request fails with a 500", async () => {
    h.post.mockImplementation(async () => failure(500));
    setPurge(purgeData());
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Устгах" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Мэдээллийг хадгалж чадсангүй."));
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("PurgePage: the list after a purge, the links and the title", () => {
  it("fetches the list again after a successful purge", async () => {
    setPurge(purgeData());
    renderPage();
    await screen.findByRole("table");
    const purgeGets = () => h.get.mock.calls.filter((call) => String(call[0]).endsWith("/api/v1/recruitment/purge")).length;
    const before = purgeGets();

    fireEvent.click(await screen.findByRole("button", { name: "Устгах" }));

    await waitFor(() => expect(screen.getByRole("status")).toBeTruthy());
    await waitFor(() => expect(purgeGets()).toBeGreaterThan(before));
  });

  it("names the count of rows in the confirm text", async () => {
    setPurge(purgeData({ rows: [ROW_ONE] }));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Устгах" }));

    await waitFor(() => expect(h.confirm).toHaveBeenCalledTimes(1));
    expect(h.confirm.mock.calls[0][0]).toBe("1 ажил хүсэгчийг бүрмөсөн устгах уу?");
  });

  it("links the back link to the vacancy list and sets the page title", async () => {
    setPurge(purgeData());
    renderPage();

    const back = await screen.findByRole("link", { name: "← Ажилд авах" });
    expect(back.getAttribute("href")).toBe("/recruitment/");
    await waitFor(() =>
      expect(document.title).toBe("Татгалзсан ажил хүсэгч цэвэрлэх · MACS Human Capital"),
    );
  });
});

describe("PurgePage: rights", () => {
  it("shows the forbidden page to a user without the manage right", async () => {
    h.get.mockImplementation(async () => failure(403));
    renderPage();

    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: "Устгах" })).toBeNull();
  });
});
