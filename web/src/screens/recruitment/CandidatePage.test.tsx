import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { nav } from "../../api/client";
import type { RecruitCandidateOut, RecruitWriteResultOut } from "../../api/recruitment";
import { endNavBar } from "../../lib/navBar";
import { CandidatePage } from "./CandidatePage";

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

const PROGRESS: RecruitCandidateOut["progress"] = [
  { key: "new", label: "Шинэ", state: "done" },
  { key: "screening", label: "Шалгаруулалт", state: "current" },
  { key: "interview", label: "Ярилцлага", state: "todo" },
  { key: "offer", label: "Санал", state: "todo" },
  { key: "hired", label: "Ажилд авсан", state: "todo" },
];

// A manager's open candidate, unless a test says otherwise.
function candidate(over: Partial<RecruitCandidateOut> = {}): RecruitCandidateOut {
  return {
    id: 11,
    name: "Бат Болд",
    vacancy_id: 5,
    vacancy_title: "Бухгалтер",
    stage: "screening",
    stage_label: "Шалгаруулалт",
    source: "Вэбсайт",
    phone: "99112233",
    email: "bat@example.com",
    notes: "",
    reject_reason: "",
    employee_id: null,
    progress: PROGRESS,
    move_to: ["new", "interview", "offer", "hired"],
    move_confirm: ["new", "offer", "hired"],
    can_manage: true,
    can_reject: true,
    can_reopen: false,
    can_convert: false,
    events: [],
    comments: [],
    files: [],
    max_mb: 10,
    extensions: "pdf, doc, docx",
    ...over,
  };
}

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function failure(status: number) {
  return { data: undefined, error: {}, response: { ok: false, status } };
}

const SAVED: RecruitWriteResultOut = { ok: true, error: "", field_errors: {}, form_errors: [] };

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

function renderPage(url = "/recruitment/candidates/11/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/recruitment/candidates/:id/" element={<CandidatePage />} />
          <Route path="/employees/new/" element={<Where />} />
          <Route path="*" element={<Where />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { client, ...view };
}

// The address the router shows now (the last Where element is the one outside the routes).
function where(): string {
  return screen.getAllByTestId("where").at(-1)?.textContent ?? "";
}

// The body of the n-th POST of a given path ending.
function postBody(ending: string, n = 0): Record<string, unknown> {
  const calls = h.post.mock.calls.filter((call) => String(call[0]).endsWith(ending));
  return (calls[n][1] as { body: Record<string, unknown> }).body;
}

function postedPaths(): string[] {
  return h.post.mock.calls.map((call) => String(call[0]));
}

function setCandidate(data: RecruitCandidateOut) {
  h.get.mockImplementation(async () => ok(data));
}

beforeEach(() => {
  h.get.mockReset();
  h.post.mockReset();
  h.confirm.mockReset();
  h.confirm.mockResolvedValue(true);
  h.post.mockImplementation(async () => ok(SAVED));
  vi.mocked(nav.assign).mockReset();
});

afterEach(() => {
  cleanup();
  endNavBar();
  vi.restoreAllMocks();
  document.title = "";
});

describe("CandidatePage: the buttons by the user's rights", () => {
  it("shows reject and convert to a manager with an open candidate who may convert", async () => {
    setCandidate(candidate({ can_convert: true }));
    renderPage();

    expect(await screen.findByRole("heading", { name: "Бат Болд" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Татгалзах" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ажилд авах" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Дахин нээх" })).toBeNull();
  });

  it("gives a hiring manager no action buttons and no upload box, but keeps the comment box and the file links", async () => {
    setCandidate(
      candidate({
        can_manage: false,
        can_reject: false,
        can_convert: false,
        move_to: [],
        move_confirm: [],
        files: [{ id: 3, name: "cv.pdf", uploaded: "2026-11-20", by: "Болд Бат" }],
      }),
    );
    renderPage();

    await screen.findByRole("heading", { name: "Бат Болд" });
    expect(screen.queryByRole("button", { name: "Татгалзах" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ажилд авах" })).toBeNull();
    expect(screen.queryByLabelText("Файл")).toBeNull();
    expect(screen.getByRole("link", { name: "cv.pdf" })).toBeTruthy();
    expect(screen.getByLabelText("Сэтгэгдэл")).toBeTruthy();
  });

  it("shows the chip and reopen, and no stage row, for a rejected candidate", async () => {
    setCandidate(
      candidate({
        stage: "rejected",
        stage_label: "Татгалзсан",
        can_reject: false,
        can_reopen: true,
        move_to: [],
        move_confirm: [],
        reject_reason: "Туршлага хүрэлцэхгүй",
      }),
    );
    renderPage();

    await screen.findByRole("heading", { name: "Бат Болд" });
    expect(screen.getByText("Татгалзсан")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Дахин нээх" })).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Шат" })).toBeNull();
    expect(screen.getByText("Туршлага хүрэлцэхгүй")).toBeTruthy();
  });

  it("shows no reject button for a hired candidate, and the stage row stays", async () => {
    setCandidate(
      candidate({ stage: "hired", stage_label: "Ажилд авсан", can_reject: false, move_to: [], move_confirm: [] }),
    );
    renderPage();

    await screen.findByRole("heading", { name: "Бат Болд" });
    expect(screen.queryByRole("button", { name: "Татгалзах" })).toBeNull();
    expect(screen.getByRole("list", { name: "Шат" })).toBeTruthy();
  });
});

describe("CandidatePage: the stage row", () => {
  it("posts a next-step move at once", async () => {
    setCandidate(candidate());
    renderPage();
    await screen.findByRole("heading", { name: "Бат Болд" });

    fireEvent.click(screen.getByTitle("Ярилцлага шат руу шилжүүлэх"));

    await waitFor(() => expect(postedPaths().some((path) => path.endsWith("/move"))).toBe(true));
    expect(postBody("/move")).toEqual({ to: "interview", note: "" });
    expect(h.confirm).not.toHaveBeenCalled();
  });

  it("asks first for a back-move, and posts nothing when declined", async () => {
    h.confirm.mockResolvedValue(false);
    setCandidate(candidate());
    renderPage();
    await screen.findByRole("heading", { name: "Бат Болд" });

    fireEvent.click(screen.getByTitle("Шинэ шат руу шилжүүлэх"));

    await waitFor(() => expect(h.confirm).toHaveBeenCalledWith("«Шинэ» шат руу шилжүүлэх үү?"));
    expect(postedPaths().some((path) => path.endsWith("/move"))).toBe(false);
  });

  it("shows a refused move's text under the row, and the stage stays", async () => {
    h.post.mockImplementation(async () => ok({ ok: false, error: "Шилжүүлэх боломжгүй.", field_errors: {}, form_errors: [] }));
    setCandidate(candidate());
    renderPage();
    await screen.findByRole("heading", { name: "Бат Болд" });

    fireEvent.click(screen.getByTitle("Ярилцлага шат руу шилжүүлэх"));

    await waitFor(() => expect(screen.getByText("Шилжүүлэх боломжгүй.")).toBeTruthy());
    expect(screen.getByText("Шалгаруулалт").getAttribute("aria-current")).toBe("step");
  });
});

describe("CandidatePage: reject and reopen", () => {
  it("closes the reject pop-up on a saved rejection and refreshes the recruitment data", async () => {
    setCandidate(candidate());
    const { client } = renderPage();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await screen.findByRole("heading", { name: "Бат Болд" });

    fireEvent.click(screen.getByRole("button", { name: "Татгалзах" }));
    const reason = document.querySelector<HTMLTextAreaElement>('textarea[name="reason"]') as HTMLTextAreaElement;
    fireEvent.change(reason, { target: { value: "Туршлага хүрэлцэхгүй" } });
    const buttons = screen.getAllByRole("button", { name: "Татгалзах" });
    fireEvent.click(buttons[buttons.length - 1]);

    await waitFor(() => expect(document.querySelector('textarea[name="reason"]')).toBeNull());
    expect(postBody("/reject")).toEqual({ reason: "Туршлага хүрэлцэхгүй", withdrawn: false });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["recruitment"] });
  });

  it("reopens a rejected candidate and shows a refusal in the red box", async () => {
    h.post.mockImplementation(async () => ok({ ok: false, error: "Энэ ажил хүсэгч аль хэдийн нээлттэй байна.", field_errors: {}, form_errors: [] }));
    setCandidate(candidate({ stage: "rejected", stage_label: "Татгалзсан", can_reject: false, can_reopen: true, move_to: [], move_confirm: [] }));
    renderPage();
    await screen.findByRole("heading", { name: "Бат Болд" });

    fireEvent.click(screen.getByRole("button", { name: "Дахин нээх" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("аль хэдийн нээлттэй байна"));
    expect(postedPaths().some((path) => path.endsWith("/reopen"))).toBe(true);
  });
});

describe("CandidatePage: convert", () => {
  it("navigates to the hire form on a saved conversion", async () => {
    h.post.mockImplementation(async () => ok({ ok: true, path: "/employees/new/?candidate=11", error: "" }));
    setCandidate(candidate({ can_convert: true }));
    renderPage();
    await screen.findByRole("heading", { name: "Бат Болд" });

    fireEvent.click(screen.getByRole("button", { name: "Ажилд авах" }));

    await waitFor(() => expect(where()).toBe("/employees/new/?candidate=11"));
  });

  it("shows the refusal in place and stays on the page", async () => {
    h.post.mockImplementation(async () => ok({ ok: false, path: "", error: "Ажил хүсэгч аль хэдийн ажилтан болсон." }));
    setCandidate(candidate({ can_convert: true }));
    renderPage();
    await screen.findByRole("heading", { name: "Бат Болд" });

    fireEvent.click(screen.getByRole("button", { name: "Ажилд авах" }));

    await waitFor(() => expect(screen.getByText("Ажил хүсэгч аль хэдийн ажилтан болсон.").getAttribute("role")).toBe("alert"));
    expect(where()).toBe("/recruitment/candidates/11/");
  });

  it("hands a path the React app does not serve to a full page load", async () => {
    h.post.mockImplementation(async () => ok({ ok: true, path: "/recruitment/vacancies/5/edit/", error: "" }));
    setCandidate(candidate({ can_convert: true }));
    renderPage();
    await screen.findByRole("heading", { name: "Бат Болд" });

    fireEvent.click(screen.getByRole("button", { name: "Ажилд авах" }));

    await waitFor(() => expect(nav.assign).toHaveBeenCalledWith("/recruitment/vacancies/5/edit/"));
  });
});

describe("CandidatePage: the page itself", () => {
  it("sets the title to the candidate's name", async () => {
    setCandidate(candidate());
    renderPage();

    await screen.findByRole("heading", { name: "Бат Болд" });
    expect(document.title).toBe("Бат Болд · MACS Human Capital");
  });

  it("links the employee page only when the employee is visible", async () => {
    setCandidate(candidate({ employee_id: 7 }));
    renderPage();
    await screen.findByRole("heading", { name: "Бат Болд" });

    expect(screen.getByRole("link", { name: "Ажилтны хуудас нээх" }).getAttribute("href")).toBe("/employees/7/");
  });

  it("omits the employee link when there is no visible employee", async () => {
    setCandidate(candidate({ employee_id: null }));
    renderPage();
    await screen.findByRole("heading", { name: "Бат Болд" });

    expect(screen.queryByRole("link", { name: "Ажилтны хуудас нээх" })).toBeNull();
  });

  it("draws the phone and mail as tel and mailto links", async () => {
    setCandidate(candidate());
    renderPage();
    await screen.findByRole("heading", { name: "Бат Болд" });

    expect(screen.getByRole("link", { name: "99112233" }).getAttribute("href")).toBe("tel:99112233");
    expect(screen.getByRole("link", { name: "bat@example.com" }).getAttribute("href")).toBe("mailto:bat@example.com");
  });

  it("folds the history's note and person under the date and stage below md", async () => {
    setCandidate(
      candidate({
        events: [{ at: "2026-11-20 10:30", from_label: "Шинэ", to_label: "Шалгаруулалт", note: "CV үнэлсэн", by: "Болд Бат" }],
      }),
    );
    renderPage();
    await screen.findByRole("heading", { name: "Бат Болд" });

    const headers = Array.from(document.querySelectorAll("table th"));
    expect(headers.find((th) => th.textContent === "Тайлбар")?.className).toContain("hidden");
    expect(headers.find((th) => th.textContent === "Тайлбар")?.className).toContain("md:table-cell");
    expect(headers.find((th) => th.textContent === "Хэн")?.className).toContain("md:table-cell");
    expect(screen.getByText("Шинэ → Шалгаруулалт")).toBeTruthy();
    const folded = Array.from(document.querySelectorAll("div.md\\:hidden")).map((el) => el.textContent);
    expect(folded).toContain("Болд Бат");
    expect(folded).toContain("CV үнэлсэн");
  });

  it("says so when there is no history", async () => {
    setCandidate(candidate({ events: [] }));
    renderPage();

    await screen.findByRole("heading", { name: "Бат Болд" });
    expect(screen.getByText("Түүх бүртгэгдээгүй")).toBeTruthy();
  });

  it("shows the not-found page when the candidate is not visible", async () => {
    h.get.mockImplementation(async () => failure(404));
    renderPage();

    expect(await screen.findByText("Хуудас олдсонгүй")).toBeTruthy();
  });

  it("shows the forbidden page when the load answers 403", async () => {
    h.get.mockImplementation(async () => failure(403));
    renderPage();

    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
  });

  // A 500 is retried three times by the hook (retryMe), with backoff of about 7 seconds, so this test waits longer.
  it("shows the Mongolian load-failure line for any other failed load", async () => {
    h.get.mockImplementation(async () => failure(500));
    renderPage();

    expect(await screen.findByText("Мэдээлэл ачаалж чадсангүй.", undefined, { timeout: 12000 })).toBeTruthy();
  }, 15000);

  it("replaces a failed move's English request text with the save text under the row", async () => {
    h.post.mockImplementation(async () => failure(403));
    setCandidate(candidate());
    renderPage();
    await screen.findByRole("heading", { name: "Бат Болд" });

    fireEvent.click(screen.getByTitle("Ярилцлага шат руу шилжүүлэх"));

    await waitFor(() => expect(screen.getByText("Мэдээллийг хадгалж чадсангүй.")).toBeTruthy());
    expect(screen.queryByText("request failed")).toBeNull();
  });
});
