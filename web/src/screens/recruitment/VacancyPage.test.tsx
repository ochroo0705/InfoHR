import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { RecruitCandidateRowOut, RecruitStageItemOut, RecruitVacancyOut } from "../../api/recruitment";
import { endNavBar } from "../../lib/navBar";
import { VacancyPage } from "./VacancyPage";

// The API client is replaced by a stub that answers by path, so the real hooks run.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

const STAGE_BAR: RecruitStageItemOut[] = [
  { key: "open", label: "Идэвхтэй", count: 3 },
  { key: "new", label: "Шинэ", count: 2 },
  { key: "screening", label: "Шалгаруулалт", count: 1 },
  { key: "interview", label: "Ярилцлага", count: 0 },
  { key: "offer", label: "Санал", count: 0 },
  { key: "hired", label: "Ажилд авсан", count: 0 },
  { key: "rejected", label: "Татгалзсан", count: 0 },
  { key: "withdrawn", label: "Өөрөө татгалзсан", count: 0 },
  { key: "all", label: "Бүгд", count: 3 },
];

const BAT: RecruitCandidateRowOut = {
  id: 11,
  name: "Бат Болд",
  stage: "new",
  stage_label: "Шинэ",
  phone: "99112233",
  source: "Вэбсайт",
  created: "2026-11-20",
};
const AH: RecruitCandidateRowOut = {
  id: 12,
  name: "Ахмад Сүх",
  stage: "rejected",
  stage_label: "Татгалзсан",
  phone: "",
  source: "",
  created: "2026-11-18",
};

function vacancy(over: Partial<RecruitVacancyOut> = {}): RecruitVacancyOut {
  return {
    id: 5,
    title: "Бухгалтер",
    status: "open",
    status_label: "Нээлттэй",
    position: "Нягтлан",
    department: "Санхүү",
    branch: "",
    headcount: 2,
    deadline: "2026-12-31",
    desired_start: null,
    description: "",
    can_manage: true,
    is_open: true,
    slot_line: null,
    stage_key: "open",
    stage_bar: STAGE_BAR,
    candidates: [BAT],
    next_offset: null,
    ...over,
  };
}

const NOT_OPEN_PAGE =
  "Энэ ажлын байр нээлттэй биш тул ажил хүсэгч нэмэх боломжгүй. «Засах» дарж төлөвийг «Нээлттэй» болгоно уу.";

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function failure(status: number) {
  return { data: undefined, error: {}, response: { ok: false, status } };
}

// The query of a request on the wire.
function queryOf(call: unknown[]): Record<string, string> {
  const init = call[1] as { params?: { query?: Record<string, string> } } | undefined;
  return init?.params?.query ?? {};
}

// The vacancy-page requests made so far, by their query (stage and offset).
function pageQueries(): Record<string, string>[] {
  return h.get.mock.calls.filter((call) => call[0] === "/api/v1/recruitment/vacancies/{pk}").map((call) => queryOf(call));
}

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

function renderPage(url = "/recruitment/vacancies/5/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/recruitment/vacancies/:id/" element={<VacancyPage />} />
          <Route path="*" element={<Where />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// The address the router shows now (the last Where element is the one outside the routes).
function where(): string {
  return screen.getAllByTestId("where").at(-1)?.textContent ?? "";
}

// The stage bar's button for a stage label.
function stageButton(label: RegExp) {
  return within(screen.getByRole("navigation", { name: "Шат" })).getByRole("button", { name: label });
}

// The stages the server knows; any other value it answers as open (as the server does).
const KNOWN_STAGES = ["open", "all", "new", "screening", "interview", "offer", "hired", "rejected", "withdrawn"];

beforeEach(() => {
  h.get.mockReset();
  h.post.mockReset();
  h.get.mockImplementation(async (path: string, init: unknown) => {
    if (path === "/api/v1/recruitment/vacancies/{pk}") {
      const requested = queryOf([path, init]).stage ?? "open";
      return ok(vacancy({ stage_key: KNOWN_STAGES.includes(requested) ? requested : "open" }));
    }
    return failure(404);
  });
});

afterEach(() => {
  // A row opened through the router starts the top bar's safety timer; end it before the environment goes.
  endNavBar();
  cleanup();
  vi.restoreAllMocks();
});

describe("VacancyPage facts", () => {
  it("draws the facts, a dash for the empty optional ones, and no description when none is set", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Бухгалтер" })).toBeTruthy();
    expect(screen.getByText("Нягтлан")).toBeTruthy();
    expect(screen.getByText("Санхүү")).toBeTruthy();
    expect(screen.getByText("Авах хүний тоо").parentElement?.textContent).toBe("Авах хүний тоо2");
    expect(screen.getByText("Авах эцсийн хугацаа").parentElement?.textContent).toBe("Авах эцсийн хугацаа2026-12-31");
    expect(screen.getByText("Салбар").parentElement?.textContent).toBe("Салбар—");
    expect(screen.getByText("Ажил эхлэх огноо").parentElement?.textContent).toBe("Ажил эхлэх огноо—");
    expect(screen.queryByText("Тайлбар")).toBeNull();
  });

  it("keeps the line breaks of a description when one is set", async () => {
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/recruitment/vacancies/{pk}") return ok(vacancy({ description: "Мөр нэг\nМөр хоёр", branch: "Төв салбар" }));
      return failure(404);
    });
    renderPage();

    await screen.findByRole("heading", { name: "Бухгалтер" });
    expect(screen.getByText("Тайлбар")).toBeTruthy();
    expect(document.querySelector(".whitespace-pre-line")?.textContent).toBe("Мөр нэг\nМөр хоёр");
    expect(screen.getByText("Салбар").parentElement?.textContent).toContain("Төв салбар");
  });
});

describe("VacancyPage stage bar", () => {
  it("shows every stage with its count and marks the open one as the default", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Бухгалтер" });

    expect(stageButton(/Шинэ/).textContent).toBe("Шинэ2");
    expect(stageButton(/Бүгд/).textContent).toBe("Бүгд3");
    expect(stageButton(/Идэвхтэй/).getAttribute("aria-current")).toBe("true");
    expect(stageButton(/Шинэ/).getAttribute("aria-current")).toBeNull();
  });

  it("picking a stage asks the page for that stage and writes it to the address", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Бухгалтер" });

    fireEvent.click(stageButton(/Шинэ/));

    await waitFor(() => expect(pageQueries().some((query) => query.stage === "new")).toBe(true));
    expect(where()).toBe("/recruitment/vacancies/5/?stage=new");
    await waitFor(() => expect(stageButton(/Шинэ/).getAttribute("aria-current")).toBe("true"));
  });

  it("picking the open stage leaves stage out of the address", async () => {
    renderPage("/recruitment/vacancies/5/?stage=new");
    await screen.findByRole("heading", { name: "Бухгалтер" });

    fireEvent.click(stageButton(/Идэвхтэй/));

    await waitFor(() => expect(where()).toBe("/recruitment/vacancies/5/"));
    await waitFor(() => expect(stageButton(/Идэвхтэй/).getAttribute("aria-current")).toBe("true"));
  });

  it("a junk stage in the address is sent as typed and the open stage is marked from the server's answer", async () => {
    renderPage("/recruitment/vacancies/5/?stage=garbage");
    await screen.findByRole("heading", { name: "Бухгалтер" });

    expect(pageQueries().at(-1)?.stage).toBe("garbage");
    expect(stageButton(/Идэвхтэй/).getAttribute("aria-current")).toBe("true");
    expect(stageButton(/Шинэ/).getAttribute("aria-current")).toBeNull();
  });
});

describe("VacancyPage for a manager", () => {
  it("shows Засах, the add button and the budget line on an open vacancy", async () => {
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/recruitment/vacancies/{pk}")
        return ok(vacancy({ slot_line: { numbers: "2026 он · орон тоо 3", warning: "" } }));
      return failure(404);
    });
    renderPage();

    await screen.findByRole("heading", { name: "Бухгалтер" });
    expect(screen.getByRole("button", { name: "Засах" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ажил хүсэгч нэмэх" })).toBeTruthy();
    expect(screen.getByText("Орон тоо: 2026 он · орон тоо 3")).toBeTruthy();
    expect(screen.queryByText(NOT_OPEN_PAGE)).toBeNull();
  });

  it("a closed vacancy shows the amber line and no add button, but still Засах", async () => {
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/recruitment/vacancies/{pk}")
        return ok(vacancy({ status: "closed", status_label: "Хаагдсан", is_open: false }));
      return failure(404);
    });
    renderPage();

    await screen.findByRole("heading", { name: "Бухгалтер" });
    expect(screen.getByText(NOT_OPEN_PAGE).className).toContain("text-amber-800");
    expect(screen.queryByRole("button", { name: "Ажил хүсэгч нэмэх" })).toBeNull();
    expect(screen.getByRole("button", { name: "Засах" })).toBeTruthy();
  });

  it("Засах opens the edit pop-up of this vacancy", async () => {
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/recruitment/vacancies/{pk}") return ok(vacancy());
      if (path === "/api/v1/recruitment/vacancies/{pk}/form")
        return ok({
          title: "Бухгалтер",
          position: 1,
          department: 10,
          branch: null,
          headcount: 2,
          hiring_manager: null,
          deadline: null,
          desired_start: null,
          status: "open",
          description: "",
        });
      if (path === "/api/v1/recruitment/vacancies/options")
        return ok({ positions: [], departments: [], branches: [], managers: [], statuses: [] });
      return failure(404);
    });
    renderPage();

    await screen.findByRole("heading", { name: "Бухгалтер" });
    fireEvent.click(screen.getByRole("button", { name: "Засах" }));

    expect(await screen.findByRole("heading", { name: "Ажлын байр засах" })).toBeTruthy();
  });

  it("the add button opens the add-candidate pop-up", async () => {
    renderPage();

    await screen.findByRole("heading", { name: "Бухгалтер" });
    fireEvent.click(screen.getByRole("button", { name: "Ажил хүсэгч нэмэх" }));

    expect(await screen.findByRole("heading", { name: "Ажил хүсэгч нэмэх" })).toBeTruthy();
  });
});

describe("VacancyPage for a hiring manager", () => {
  it("sees no Засах, no add button, no budget line even when the answer carries one, and no amber line", async () => {
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/recruitment/vacancies/{pk}")
        return ok(vacancy({ can_manage: false, slot_line: { numbers: "2026 он · орон тоо 3", warning: "" } }));
      return failure(404);
    });
    renderPage();

    await screen.findByRole("heading", { name: "Бухгалтер" });
    expect(screen.queryByRole("button", { name: "Засах" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Ажил хүсэгч нэмэх" })).toBeNull();
    expect(screen.queryByText("Орон тоо: 2026 он · орон тоо 3")).toBeNull();
    expect(screen.queryByText(NOT_OPEN_PAGE)).toBeNull();
  });
});

describe("VacancyPage candidates", () => {
  it("names each candidate as a link, shows a dash for no phone and the stage chip", async () => {
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/recruitment/vacancies/{pk}") return ok(vacancy({ candidates: [BAT, AH] }));
      return failure(404);
    });
    renderPage();

    const link = await screen.findByRole("link", { name: "Бат Болд" });
    expect(link.getAttribute("href")).toBe("/recruitment/candidates/11/");
    const row = link.closest("tr") as HTMLTableRowElement;
    expect(row.textContent).toContain("99112233");
    expect(row.textContent).toContain("Вэбсайт");
    expect(row.textContent).toContain("2026-11-20");
    expect(screen.getByRole("link", { name: "Ахмад Сүх" }).closest("tr")?.textContent).toContain("—");
  });

  it("an empty list says so in a full-width row", async () => {
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/recruitment/vacancies/{pk}") return ok(vacancy({ candidates: [] }));
      return failure(404);
    });
    renderPage();

    expect(await screen.findByText("Ажил хүсэгч олдсонгүй")).toBeTruthy();
  });

  it("a candidate row is a tab stop with no button role, and Enter opens the candidate", async () => {
    renderPage();

    const link = await screen.findByRole("link", { name: "Бат Болд" });
    const row = link.closest("tr") as HTMLTableRowElement;
    expect(row.getAttribute("tabindex")).toBe("0");
    expect(row.getAttribute("role")).toBeNull();
    fireEvent.keyDown(row, { key: "Enter" });
    await waitFor(() => expect(where()).toBe("/recruitment/candidates/11/"));
  });

  it("the more batch loads the next batch and adds its rows", async () => {
    h.get.mockImplementation(async (path: string, init: unknown) => {
      if (path !== "/api/v1/recruitment/vacancies/{pk}") return failure(404);
      const query = queryOf([path, init]);
      if (query.offset === "60") return ok(vacancy({ candidates: [AH], next_offset: null }));
      return ok(vacancy({ candidates: [BAT], next_offset: 60 }));
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Цааш харуулах" }));

    expect(await screen.findByRole("link", { name: "Ахмад Сүх" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Бат Болд" })).toBeTruthy();
    expect(pageQueries().some((query) => query.offset === "60")).toBe(true);
  });
});

describe("VacancyPage failures", () => {
  it("a vacancy the user may not see shows the not-found page", async () => {
    h.get.mockImplementation(async () => failure(404));
    renderPage();

    expect(await screen.findByRole("heading", { name: "Хуудас олдсонгүй" })).toBeTruthy();
  });

  it("a refused read shows the forbidden page", async () => {
    h.get.mockImplementation(async () => failure(403));
    renderPage();

    expect(await screen.findByText("Хандах эрх байхгүй")).toBeTruthy();
  });
});
