import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { ReportCatalogueOut } from "../../api/reports";
import { legacyOrigin } from "../../lib/AppLink";
import { CataloguePage } from "./CataloguePage";

// The API client is replaced by a stub that answers by path, so the real hooks run (as ListsIndexPage.test.tsx).
const h = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const BUILT = {
  key: "leave-balance",
  title: "Чөлөөний үлдэгдэл",
  description: "Ажилтан бүрийн чөлөөний үлдэгдэл",
  empty: false,
  link: true,
  path: "/reports/leave-balance/",
  search: "Чөлөөний үлдэгдэл Ажилтан бүрийн чөлөөний үлдэгдэл",
};

const BUILT_EMPTY = {
  key: "payroll-log",
  title: "Цалингийн бүртгэл",
  description: "Цалингийн өөрчлөлтийн түүх",
  empty: true,
  link: true,
  path: "/reports/payroll-log/",
  search: "Цалингийн бүртгэл Цалингийн өөрчлөлтийн түүх",
};

const UNBUILT = {
  key: "future",
  title: "Ирээдүйн тайлан",
  description: "Удахгүй нэмэгдэх тайлан",
  empty: false,
  link: false,
  path: "/reports/future/",
  search: "Ирээдүйн тайлан Удахгүй нэмэгдэх тайлан",
};

function catalogueAnswer(): ReportCatalogueOut {
  return {
    sections: [
      { title: "Ажилтан", rows: [BUILT, UNBUILT] },
      { title: "Цалин", rows: [BUILT_EMPTY] },
    ],
  };
}

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function failure(status: number) {
  return { data: undefined, error: {}, response: { ok: false, status } };
}

// Shows the router's address, so a test can read what the URL became.
function Probe() {
  const location = useLocation();
  return <div data-testid="loc">{location.pathname + location.search}</div>;
}

function renderPage(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/reports/" element={<CataloguePage />} />
        </Routes>
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// The project has no jest-dom matchers, so classes and attributes are read from the DOM.
function hasClass(element: Element, name: string): boolean {
  return element.classList.contains(name);
}

// The card element that holds a title.
function cardOf(title: string): HTMLElement {
  const card = screen.getByText(title).closest("[data-report-card]");
  if (!(card instanceof HTMLElement)) throw new Error(`no card for ${title}`);
  return card;
}

// The section element of a section heading.
function sectionOf(title: string): HTMLElement {
  const section = screen.getByRole("heading", { name: title }).closest("[data-report-section]");
  if (!(section instanceof HTMLElement)) throw new Error(`no section for ${title}`);
  return section;
}

describe("CataloguePage", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/reports/catalogue") return ok(catalogueAnswer());
      return failure(404);
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("renders_sections_and_cards", async () => {
    renderPage("/reports/");

    await screen.findByText("Чөлөөний үлдэгдэл");
    expect(screen.getByRole("heading", { name: "MACS-ийн бүх тайлан" })).not.toBeNull();
    expect(screen.getByText("MACS-д байсан тайлангууд, шинэ системд хэвээр")).not.toBeNull();
    expect(screen.getByPlaceholderText("Тайлан хайх").getAttribute("id")).toBe("report-search");

    const headings = screen.getAllByRole("heading", { level: 2 });
    expect(headings.map((heading) => heading.textContent)).toEqual(["Ажилтан", "Цалин"]);
    expect(hasClass(headings[0], "sec-title")).toBe(true);

    expect(document.querySelectorAll("[data-report-card]")).toHaveLength(3);
    expect(hasClass(cardOf("Чөлөөний үлдэгдэл"), "hover:border-violet-300")).toBe(true);
    expect(hasClass(cardOf("Ирээдүйн тайлан"), "hover:border-violet-300")).toBe(false);
  });

  it("unbuilt_card_is_grey_with_udakhgui", async () => {
    renderPage("/reports/");
    await screen.findByText("Ирээдүйн тайлан");

    const title = screen.getByText("Ирээдүйн тайлан");
    expect(title.tagName).toBe("SPAN");
    expect(hasClass(title, "text-slate-400")).toBe(true);
    expect(cardOf("Ирээдүйн тайлан").querySelector("a")).toBeNull();
    expect(cardOf("Ирээдүйн тайлан").textContent).toContain("удахгүй");
  });

  it("empty_report_note", async () => {
    renderPage("/reports/");
    await screen.findByText("Цалингийн бүртгэл");

    expect(cardOf("Цалингийн бүртгэл").textContent).toContain("бүртгэл алга");
    expect(cardOf("Чөлөөний үлдэгдэл").textContent).not.toContain("бүртгэл алга");
  });

  it("search_hides_cards_and_sections_and_shows_none_note", async () => {
    renderPage("/reports/");
    await screen.findByText("Цалингийн бүртгэл");
    const input = screen.getByPlaceholderText("Тайлан хайх");

    // A word from the second section only: the first section has no visible card, so it hides.
    fireEvent.change(input, { target: { value: "  ЦАЛИН " } });
    expect(hasClass(cardOf("Чөлөөний үлдэгдэл"), "hidden")).toBe(true);
    expect(hasClass(cardOf("Ирээдүйн тайлан"), "hidden")).toBe(true);
    expect(hasClass(cardOf("Цалингийн бүртгэл"), "hidden")).toBe(false);
    expect(hasClass(sectionOf("Ажилтан"), "hidden")).toBe(true);
    expect(hasClass(sectionOf("Цалин"), "hidden")).toBe(false);
    expect(screen.queryByText("Хайлтад тохирох тайлан олдсонгүй.")).toBeNull();

    // Nothing matches: the none note shows, every card and section is hidden.
    fireEvent.change(input, { target: { value: "xyz-нет" } });
    expect(screen.getByText("Хайлтад тохирох тайлан олдсонгүй.")).not.toBeNull();
    expect(hasClass(sectionOf("Ажилтан"), "hidden")).toBe(true);
    expect(hasClass(sectionOf("Цалин"), "hidden")).toBe(true);

    // Cleared: everything shows again and the note goes.
    fireEvent.change(input, { target: { value: "" } });
    expect(hasClass(cardOf("Чөлөөний үлдэгдэл"), "hidden")).toBe(false);
    expect(hasClass(sectionOf("Ажилтан"), "hidden")).toBe(false);
    expect(screen.queryByText("Хайлтад тохирох тайлан олдсонгүй.")).toBeNull();
  });

  it("q_in_address_prefills_and_applies", async () => {
    renderPage("/reports/?q=цалин");

    await screen.findByText("Цалингийн бүртгэл");
    expect((screen.getByPlaceholderText("Тайлан хайх") as HTMLInputElement).value).toBe("цалин");
    expect(hasClass(cardOf("Чөлөөний үлдэгдэл"), "hidden")).toBe(true);
    expect(hasClass(cardOf("Цалингийн бүртгэл"), "hidden")).toBe(false);
  });

  it("typing_writes_the_address_with_replace_and_no_new_history", async () => {
    renderPage("/reports/");
    await screen.findByText("Цалингийн бүртгэл");

    fireEvent.change(screen.getByPlaceholderText("Тайлан хайх"), { target: { value: "цалин" } });
    expect(screen.getByTestId("loc").textContent).toBe("/reports/?q=%D1%86%D0%B0%D0%BB%D0%B8%D0%BD");

    fireEvent.change(screen.getByPlaceholderText("Тайлан хайх"), { target: { value: "" } });
    expect(screen.getByTestId("loc").textContent).toBe("/reports/");
  });

  it("built_card_links_through_applink_to_the_django_report_page", async () => {
    renderPage("/reports/");
    await screen.findByText("Чөлөөний үлдэгдэл");

    // /reports/<key>/ is not PORTED yet: the link is a full page load to Django.
    const link = screen.getByRole("link", { name: "Чөлөөний үлдэгдэл" });
    expect(link.getAttribute("href")).toBe(legacyOrigin() + "/reports/leave-balance/");
    expect(hasClass(link, "after:absolute") && hasClass(link, "after:inset-0")).toBe(true);
  });

  it("forbidden_screen_on_403", async () => {
    h.get.mockImplementation(async () => failure(403));
    renderPage("/reports/");

    await waitFor(() => expect(screen.getByText("Хандах эрх байхгүй")).not.toBeNull());
    expect(screen.queryByText("MACS-ийн бүх тайлан")).toBeNull();
  });

  it("error_state_shows_alert_and_no_none_note", async () => {
    // A 500 is retried by the query (retryMe), so the answer comes after the retry delays.
    h.get.mockImplementation(async () => failure(500));
    renderPage("/reports/");

    const alert = await screen.findByRole("alert", undefined, { timeout: 12000 });
    expect(alert.textContent).toBe("Мэдээлэл ачаалж чадсангүй.");
    expect(screen.queryByText("Хайлтад тохирох тайлан олдсонгүй.")).toBeNull();
  }, 15000);

  it("q_in_address_is_trimmed_and_cut_to_200_in_the_box", async () => {
    renderPage(`/reports/?q=${encodeURIComponent("  " + "a".repeat(300))}`);

    await screen.findByText("Чөлөөний үлдэгдэл");
    const value = (screen.getByPlaceholderText("Тайлан хайх") as HTMLInputElement).value;
    expect(value).toBe("a".repeat(200));
  });

  it("html_in_description_is_drawn_as_text", async () => {
    const withHtml = { ...BUILT, description: "<b>x</b>" };
    h.get.mockImplementation(async () => ok({ sections: [{ title: "Ажилтан", rows: [withHtml] }] }));
    renderPage("/reports/");

    await screen.findByText("Чөлөөний үлдэгдэл");
    const card = cardOf("Чөлөөний үлдэгдэл");
    expect(card.querySelector("b")).toBeNull();
    expect(card.textContent).toContain("<b>x</b>");
  });
});
