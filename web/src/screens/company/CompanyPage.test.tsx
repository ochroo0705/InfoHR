import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CompanyPageOut } from "../../api/company";
import { CompanyPage } from "./CompanyPage";

// The API client is replaced by a stub that answers by path, so the real hook runs.
const h = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => ""),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const line = (over: Partial<CompanyPageOut["headcount"]> = {}): CompanyPageOut["headcount"] => ({
  title: "Ажилтны тоо, 12 сар",
  head: "48",
  label: "Ажилтны тоо, 12 сар: 40 → 48",
  polylines: ["0,60 100,30 200,0"],
  last_dot: { cx: "200", cy: "0" },
  view_box: "-4 -4 208 68",
  first_label: "2025-12",
  last_label: "2026-11",
  no_data: false,
  no_data_text: "Мэдээлэл алга",
  ...over,
});

// A full company answer: one headcount line with data, the rest with data too (the no-data case is set per test).
function makeCompany(over: Partial<CompanyPageOut> = {}): CompanyPageOut {
  return {
    title: "Компанийн байдал",
    today: "2026-11-17",
    partial_scope: false,
    scope_label: "",
    partial_history: false,
    history_note: "",
    hires_text: "Энэ сард орсон 2",
    leavers_text: "Гарсан 1",
    headcount: line(),
    turnover: line({
      title: "Сарын эргэлт",
      head: "2.5%",
      label: "Сарын эргэлт: 1%→2.5%",
      polylines: [],
      last_dot: null,
      no_data: true,
      no_data_text: "Мэдээлэл алга",
      first_label: "",
      last_label: "",
    }),
    turnover_note: "Сарын эргэлт = гарсан ÷ сарын дундаж ажилтны тоо",
    departments: {
      title: "Хэлтсээр",
      summary: "Хэлтсээр: Инженер 3",
      no_data: false,
      no_data_text: "Мэдээлэл алга",
      bars: [{ label: "Инженер", value: "3", width: "42%" }],
    },
    tenure: {
      title: "Ажилласан хугацаа",
      summary: "",
      no_data: true,
      no_data_text: "Мэдээлэл алга",
      bars: [],
    },
    ...over,
  };
}

function stubApi({ company, status = 200 }: { company?: CompanyPageOut; status?: number }) {
  h.get.mockImplementation(async (path: string) => {
    if (path === "/api/v1/company" && status === 200) {
      return { data: company, response: { ok: true, status: 200 } };
    }
    if (path === "/api/v1/company") {
      return { error: {}, response: { ok: false, status } };
    }
    return { error: {}, response: { ok: false, status: 500 } };
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CompanyPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CompanyPage", () => {
  beforeEach(() => {
    h.get.mockReset();
  });

  afterEach(() => {
    cleanup();
    document.title = "";
  });

  it("renders the headcount from the mocked API", async () => {
    stubApi({ company: makeCompany() });
    const { container } = renderPage();
    await waitFor(() => expect(container.querySelector("[data-company]")).not.toBeNull());

    const heading = container.querySelector("[data-company] h3");
    expect(heading?.textContent).toBe("Ажилтны тоо, 12 сар48");
    expect(screen.getByText("Энэ сард орсон 2")).toBeTruthy();
    expect(screen.getByText("Гарсан 1")).toBeTruthy();
  });

  it("renders the Forbidden screen on a 403", async () => {
    stubApi({ status: 403 });
    renderPage();
    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
    expect(document.querySelector("[data-company]")).toBeNull();
  });

  it("sets the document title from the API title", async () => {
    stubApi({ company: makeCompany() });
    const { container } = renderPage();
    await waitFor(() => expect(container.querySelector("[data-company]")).not.toBeNull());
    expect(document.title).toBe("Компанийн байдал · MACS Human Capital");
  });

  it("shows the no-data text the API sends", async () => {
    const company = makeCompany({
      tenure: { title: "Ажилласан хугацаа", summary: "", no_data: true, no_data_text: "Өгөгдөл байхгүй", bars: [] },
    });
    stubApi({ company });
    const { container } = renderPage();
    await waitFor(() => expect(container.querySelector("[data-company]")).not.toBeNull());

    const bars = container.querySelectorAll("[data-company] p.text-xs.text-slate-400");
    const texts = Array.from(bars).map((p) => p.textContent);
    expect(texts).toContain("Өгөгдөл байхгүй");
    expect(container.querySelectorAll("[data-bar-chart]").length).toBe(1);
  });

  it("draws the polylines and the last dot with the points from the API verbatim", async () => {
    const company = makeCompany({
      headcount: line({ polylines: ["0,60 100,30", "150,20 200,0"], last_dot: { cx: "200", cy: "0" } }),
    });
    stubApi({ company });
    const { container } = renderPage();
    await waitFor(() => expect(container.querySelector("[data-line-chart]")).not.toBeNull());

    const svg = container.querySelector("[data-line-chart]");
    expect(svg?.getAttribute("viewBox")).toBe("-4 -4 208 68");
    const polylines = Array.from(svg?.querySelectorAll("polyline") ?? []);
    expect(polylines.map((p) => p.getAttribute("points"))).toEqual(["0,60 100,30", "150,20 200,0"]);
    const dot = svg?.querySelector("circle");
    expect(dot?.getAttribute("cx")).toBe("200");
    expect(dot?.getAttribute("cy")).toBe("0");
  });
});
