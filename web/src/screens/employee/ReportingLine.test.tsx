import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReportingLineOut, ReportingPersonOut } from "../../api/employee";
import { photoSrc } from "../../lib/photo";
import { ReportingLine } from "./ReportingLine";
import { RL_TEXT, showLabel } from "./reportingText";

// fetch is stubbed before the api client is imported, as in WorkJobs.test.tsx.
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

// One person as the API sends it. Only the fields the tree reads matter; the rest is filled so the shape is complete.
function person(overrides: Partial<ReportingPersonOut> = {}): ReportingPersonOut {
  return {
    pk: 1,
    full_name: "Ж. Бат",
    given_initial: "Б",
    photo_url: "",
    photo_srcset: "",
    position: "Мэргэжилтэн",
    department: "Үйлдвэрлэл",
    work_phone: "",
    email: "",
    until: "",
    ...overrides,
  };
}

// The chain for one employee: `levels` is direct manager first.
function line(levels: ReportingPersonOut[]): ReportingLineOut {
  return { day: "", employee: person({ pk: 7, full_name: "Баяр С.", given_initial: "БС", position: "Шинжээч" }), levels };
}

// Answers the reporting-line request with `payload` (or an error status). Other paths are a test bug.
function stubLine(payload: unknown, status = 200) {
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (request.method === "GET" && path.endsWith("/reporting-line")) {
      return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
    }
    throw new Error(`unexpected request ${request.method} ${path}`);
  });
}

// The tree with a query client (its query is async, so the tests wait for it with findBy).
function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const DIRECT = person({ pk: 2, full_name: "О. Мөнх", given_initial: "ОМ", position: "Баг ахлагч" });
const HEAD = person({ pk: 3, full_name: "Б. Ганзориг", given_initial: "БГ", position: "Үйл ажиллагааны захирал" });
const CEO = person({ pk: 4, full_name: "Д. Туяа", given_initial: "ДТ", position: "Гүйцэтгэх захирал" });

beforeEach(() => {
  fetchMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("ReportingLine", () => {
  it("collapsed with 3 levels: the subject and the direct manager show, the toggle is closed, the upper stack is inert", async () => {
    stubLine(line([DIRECT, HEAD, CEO]));
    const { container } = renderWithClient(<ReportingLine pk={7} />);

    await screen.findByText("Баяр С.");
    expect(screen.getByText("О. Мөнх")).toBeTruthy();

    const toggle = screen.getByRole("button", { name: showLabel(2) });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.textContent).toBe("Бүх шатыг харуулах · 2");

    const upper = container.querySelector(".rl-up");
    expect(upper).not.toBeNull();
    expect(upper?.hasAttribute("inert")).toBe(true);
    expect(toggle.getAttribute("aria-controls")).toBe(upper?.id);
  });

  it("clicking the toggle opens the stack and clicking again collapses it", async () => {
    stubLine(line([DIRECT, HEAD, CEO]));
    const { container } = renderWithClient(<ReportingLine pk={7} />);

    fireEvent.click(await screen.findByRole("button", { name: showLabel(2) }));

    const open = screen.getByRole("button", { name: RL_TEXT.hide });
    expect(open.getAttribute("aria-expanded")).toBe("true");
    expect(open.textContent).toBe("Нуух");
    const upper = container.querySelector(".rl-up");
    expect(upper?.hasAttribute("inert")).toBe(false);
    expect(upper?.hasAttribute("data-open")).toBe(true);

    fireEvent.click(open);

    const closed = screen.getByRole("button", { name: showLabel(2) });
    expect(closed.getAttribute("aria-expanded")).toBe("false");
    expect(container.querySelector(".rl-up")?.hasAttribute("inert")).toBe(true);
    expect(container.querySelector(".rl-up")?.hasAttribute("data-open")).toBe(false);
  });

  it("the hidden levels are drawn farthest first, with the nearest level's stagger step 0", async () => {
    stubLine(line([DIRECT, HEAD, CEO]));
    const { container } = renderWithClient(<ReportingLine pk={7} />);
    await screen.findByText("Баяр С.");

    const items = Array.from(container.querySelectorAll<HTMLElement>(".rl-up .rl-item"));
    expect(items.map((item) => item.textContent?.includes("Д. Туяа"))).toEqual([true, false]);
    expect(items.map((item) => item.textContent?.includes("Б. Ганзориг"))).toEqual([false, true]);
    expect(items[0].style.getPropertyValue("--rl-delay")).toBe("70ms");
    expect(items[1].style.getPropertyValue("--rl-delay")).toBe("0ms");
  });

  it("exactly 1 level: no toggle button and the direct manager is the only manager", async () => {
    stubLine(line([DIRECT]));
    const { container } = renderWithClient(<ReportingLine pk={7} />);

    await screen.findByText("О. Мөнх");
    expect(screen.queryByRole("button", { name: /Бүх шатыг/ })).toBeNull();
    expect(container.querySelector(".rl-up")).toBeNull();
  });

  it("0 levels: the line «Удирдлага байхгүй» and no toggle", async () => {
    stubLine(line([]));
    renderWithClient(<ReportingLine pk={7} />);

    await screen.findByText(RL_TEXT.none);
    expect(screen.queryByRole("button", { name: /Бүх шатыг/ })).toBeNull();
  });

  it("no photo: the avatar shows given_initial", async () => {
    stubLine(line([DIRECT]));
    renderWithClient(<ReportingLine pk={7} />);

    await screen.findByText("ОМ");
    expect(screen.getByText("БС")).toBeTruthy();
  });

  it("with a photo the avatar renders an img with the photo source", async () => {
    const withPhoto = person({ pk: 2, full_name: "О. Мөнх", photo_url: "/media/photos/munkh.jpg", photo_srcset: "" });
    stubLine(line([withPhoto]));
    const { container } = renderWithClient(<ReportingLine pk={7} />);

    await screen.findByText("О. Мөнх");
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("src")).toBe(photoSrc("/media/photos/munkh.jpg"));
  });

  it("a name of 120 characters renders in a truncating line", async () => {
    const longName = "А".repeat(120);
    stubLine(line([person({ pk: 2, full_name: longName })]));
    renderWithClient(<ReportingLine pk={7} />);

    const name = await screen.findByText(longName);
    expect(name.classList.contains("truncate")).toBe(true);
  });

  it("a failed request shows the load error", async () => {
    stubLine({ detail: "not found" }, 404);
    renderWithClient(<ReportingLine pk={7} />);

    await screen.findByText("Удирдлагын шатыг ачаалж чадсангүй.");
  });

  it("the section is labelled by its heading", async () => {
    stubLine(line([DIRECT]));
    renderWithClient(<ReportingLine pk={7} />);

    await screen.findByText("О. Мөнх");
    expect(screen.getByRole("region", { name: RL_TEXT.heading })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 3, name: RL_TEXT.heading })).toBeTruthy();
  });

  it("a 4-level chain draws top to bottom: the hidden stack farthest first, the direct manager, the employee, then the toggle", async () => {
    const TOP = person({ pk: 5, full_name: "Т. Оюун", given_initial: "ТО", position: "Ерөнхийлөгч" });
    stubLine(line([DIRECT, HEAD, CEO, TOP]));
    const { container } = renderWithClient(<ReportingLine pk={7} />);
    await screen.findByText("Баяр С.");

    // Document order of every box and the toggle inside the tree (querySelectorAll returns document order).
    const order = Array.from(container.querySelectorAll<HTMLElement>(".rl-tree .rl-box, .rl-tree .rl-toggle")).map((el) =>
      el.classList.contains("rl-toggle") ? "toggle" : el.querySelector(".truncate")?.textContent,
    );
    expect(order).toEqual(["Т. Оюун", "Д. Туяа", "Б. Ганзориг", "О. Мөнх", "Баяр С.", "toggle"]);
  });

  it("the toggle comes after the employee box in document order", async () => {
    stubLine(line([DIRECT, HEAD, CEO]));
    const { container } = renderWithClient(<ReportingLine pk={7} />);
    await screen.findByText("Баяр С.");

    const toggle = screen.getByRole("button", { name: showLabel(2) });
    const employeeBox = container.querySelector(".rl-box-me") as HTMLElement;
    expect(employeeBox).not.toBeNull();
    expect(employeeBox.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("clicking a manager's box opens its card with the department, phone and email", async () => {
    stubLine(
      line([
        person({ pk: 2, full_name: "О. Мөнх", position: "Баг ахлагч", department: "Борлуулалт", work_phone: "77001122", email: "munkh@example.mn" }),
      ]),
    );
    renderWithClient(<ReportingLine pk={7} />);

    const box = await screen.findByRole("button", { name: /О\. Мөнх/ });
    expect(box.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(box);

    expect(box.getAttribute("aria-expanded")).toBe("true");
    const card = screen.getByRole("group", { name: "О. Мөнх" });
    expect(card.hasAttribute("inert")).toBe(false);
    expect(within(card).getByText(RL_TEXT.department)).toBeTruthy();
    expect(within(card).getByText("Борлуулалт")).toBeTruthy();
    expect(within(card).getByText(RL_TEXT.phone)).toBeTruthy();
    expect(within(card).getByText("77001122")).toBeTruthy();
    expect(within(card).getByText(RL_TEXT.email)).toBeTruthy();
    expect(within(card).getByText("munkh@example.mn")).toBeTruthy();
  });

  it("clicking another box closes the card that was open", async () => {
    stubLine(line([DIRECT, HEAD, CEO]));
    renderWithClient(<ReportingLine pk={7} />);

    fireEvent.click(await screen.findByRole("button", { name: showLabel(2) }));
    const directBox = screen.getByRole("button", { name: /О\. Мөнх/ });
    const headBox = screen.getByRole("button", { name: /Б\. Ганзориг/ });

    fireEvent.click(directBox);
    expect(directBox.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(headBox);
    expect(headBox.getAttribute("aria-expanded")).toBe("true");
    expect(directBox.getAttribute("aria-expanded")).toBe("false");
  });

  it("pressing an open box a second time closes its card", async () => {
    stubLine(line([DIRECT]));
    renderWithClient(<ReportingLine pk={7} />);

    const box = await screen.findByRole("button", { name: /О\. Мөнх/ });
    fireEvent.click(box);
    expect(box.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(box);
    expect(box.getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByRole("group", { name: "О. Мөнх" }).hasAttribute("inert")).toBe(true);
  });

  it("the open card contains no links", async () => {
    stubLine(line([person({ pk: 2, full_name: "О. Мөнх", position: "Баг ахлагч", work_phone: "77001122", email: "munkh@example.mn" })]));
    renderWithClient(<ReportingLine pk={7} />);

    fireEvent.click(await screen.findByRole("button", { name: /О\. Мөнх/ }));
    const card = screen.getByRole("group", { name: "О. Мөнх" });
    expect(card.querySelectorAll("a").length).toBe(0);
  });

  it("collapsing the hidden stack closes a card that was open in it", async () => {
    stubLine(line([DIRECT, HEAD]));
    const { container } = renderWithClient(<ReportingLine pk={7} />);

    fireEvent.click(await screen.findByRole("button", { name: showLabel(1) }));
    const hidden = screen.getByRole("button", { name: /Б\. Ганзориг/ });
    fireEvent.click(hidden);
    expect(hidden.getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: RL_TEXT.hide }));
    expect(container.querySelectorAll('[data-rl-box][aria-expanded="true"]').length).toBe(0);
    expect(container.querySelectorAll("[data-rl-card][data-open]").length).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: showLabel(1) }));
    expect(screen.getByRole("button", { name: /Б\. Ганзориг/ }).getAttribute("aria-expanded")).toBe("false");
  });

  it("Escape closes the open card and returns focus to its box", async () => {
    stubLine(line([DIRECT]));
    renderWithClient(<ReportingLine pk={7} />);

    const box = await screen.findByRole("button", { name: /О\. Мөнх/ });
    fireEvent.click(box);
    expect(box.getAttribute("aria-expanded")).toBe("true");

    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(box.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(box);
  });

  it("a click outside the open card closes it", async () => {
    stubLine(line([DIRECT]));
    renderWithClient(<ReportingLine pk={7} />);

    const box = await screen.findByRole("button", { name: /О\. Мөнх/ });
    fireEvent.click(box);
    expect(box.getAttribute("aria-expanded")).toBe("true");

    fireEvent.mouseDown(document.body);
    expect(box.getAttribute("aria-expanded")).toBe("false");
  });

  it("an empty phone shows an em dash in the card", async () => {
    stubLine(line([person({ pk: 2, full_name: "О. Мөнх", position: "Баг ахлагч", work_phone: "", email: "munkh@example.mn" })]));
    renderWithClient(<ReportingLine pk={7} />);

    fireEvent.click(await screen.findByRole("button", { name: /О\. Мөнх/ }));
    const card = screen.getByRole("group", { name: "О. Мөнх" });
    expect(within(card).getByText("—")).toBeTruthy();
    expect(within(card).getByText("munkh@example.mn")).toBeTruthy();
  });

  it("picking a day asks for that day and shows that answer's levels", async () => {
    const PAST = person({ pk: 9, full_name: "Х. Сарнай", given_initial: "ХС", position: "Ахлах" });
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (input: unknown) => {
      const request = input as Request;
      const url = new URL(request.url);
      if (request.method !== "GET" || !url.pathname.endsWith("/reporting-line")) throw new Error(`unexpected ${url.pathname}`);
      const day = url.searchParams.get("day");
      const payload = day === "2026-03-01" ? line([PAST]) : line([DIRECT]);
      return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    renderWithClient(<ReportingLine pk={7} />);

    await screen.findByText("О. Мөнх");
    const box = screen.getByRole("textbox", { name: RL_TEXT.date });
    fireEvent.change(box, { target: { value: "2026-03-01" } });

    await screen.findByText("Х. Сарнай");
    expect(screen.queryByText("О. Мөнх")).toBeNull();
    const urls = fetchMock.mock.calls.map((call) => new URL((call[0] as Request).url));
    expect(urls[urls.length - 1].searchParams.get("day")).toBe("2026-03-01");
  });

  it("clearing the day box asks again without a day parameter", async () => {
    stubLine(line([DIRECT]));
    renderWithClient(<ReportingLine pk={7} />);
    await screen.findByText("О. Мөнх");

    const box = screen.getByRole("textbox", { name: RL_TEXT.date });
    fireEvent.change(box, { target: { value: "2026-03-01" } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    fireEvent.change(box, { target: { value: "" } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));

    const last = new URL((fetchMock.mock.calls[2][0] as Request).url);
    expect(last.searchParams.has("day")).toBe(false);
  });

  it("changing the day closes an open card", async () => {
    stubLine(line([DIRECT]));
    renderWithClient(<ReportingLine pk={7} />);

    const box = await screen.findByRole("button", { name: /О\. Мөнх/ });
    fireEvent.click(box);
    expect(box.getAttribute("aria-expanded")).toBe("true");

    fireEvent.change(screen.getByRole("textbox", { name: RL_TEXT.date }), { target: { value: "2026-03-01" } });
    expect(screen.getByRole("button", { name: /О\. Мөнх/ }).getAttribute("aria-expanded")).toBe("false");
  });

  it("a box inside the collapsed stack cannot be opened", async () => {
    stubLine(line([DIRECT, HEAD]));
    renderWithClient(<ReportingLine pk={7} />);

    await screen.findByRole("button", { name: /О\. Мөнх/ });
    const hidden = screen.getByRole("button", { name: /Б\. Ганзориг/ });
    fireEvent.click(hidden);
    expect(hidden.getAttribute("aria-expanded")).toBe("false");
  });
});
