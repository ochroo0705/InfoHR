import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReportColumnsModelOut } from "../../../api/reports";
import { ColumnsModal } from "./ColumnsModal";
import { COLUMNS_TEXT } from "./popupTexts";

// The API client is replaced by a stub that answers by path; the real hooks run. Navigation is a spy.
const h = vi.hoisted(() => ({ get: vi.fn(), navigate: vi.fn() }));

vi.mock("../../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: vi.fn() },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

vi.mock("react-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router")>()),
  useNavigate: () => h.navigate,
}));

const MODEL: ReportColumnsModelOut = {
  group: "",
  group_choices: [{ key: "dept", label: "Хэлтэс" }],
  group_text: "",
  groups: [
    {
      title: "Үндсэн",
      picks: [
        { key: "name", label: "Нэр", checked: true },
        { key: "salary", label: "Цалин", checked: false },
      ],
    },
    { title: "Бусад", picks: [{ key: "joined", label: "Элссэн", checked: true }] },
  ],
  keep: [["add", "x"]],
};

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function makeClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function renderPop(model: ReportColumnsModelOut | "pending" | 403, onClose = vi.fn()) {
  h.get.mockImplementation(async (path: string) => {
    if (path !== "/api/v1/reports/{key}/columns") return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    if (model === "pending") return new Promise(() => {});
    if (model === 403) return { data: undefined, error: {}, response: { ok: false, status: 403 } };
    return ok(model);
  });
  render(
    <QueryClientProvider client={makeClient()}>
      <ColumnsModal reportKey="emp" query="?add=x" onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

function groupSelect(): HTMLSelectElement {
  const el = document.querySelector<HTMLSelectElement>('select[name="group"]');
  if (!el) throw new Error("no group select");
  return el;
}

function applyButton(): HTMLButtonElement {
  return within(screen.getByRole("dialog")).getByRole("button", { name: COLUMNS_TEXT.apply }) as HTMLButtonElement;
}

beforeEach(() => {
  h.get.mockReset();
  h.navigate.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("ColumnsModal", () => {
  it("modal_ticks_shown_columns_and_lists_groups", async () => {
    renderPop(MODEL);
    expect(screen.getByRole("heading", { name: COLUMNS_TEXT.title })).toBeTruthy();
    await screen.findByLabelText("Нэр");
    const legends = Array.from(document.querySelectorAll("legend")).map((el) => el.textContent);
    expect(legends).toEqual(["Үндсэн", "Бусад"]);
    expect((screen.getByLabelText("Нэр") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText("Цалин") as HTMLInputElement).checked).toBe(false);
    expect((screen.getByLabelText("Элссэн") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByLabelText(COLUMNS_TEXT.group)).toBeTruthy();
  });

  it("apply_navigates_with_cols_group_and_keep", async () => {
    const { onClose } = renderPop(MODEL);
    await screen.findByLabelText("Нэр");
    fireEvent.click(screen.getByLabelText("Цалин"));
    fireEvent.change(groupSelect(), { target: { value: "dept" } });
    fireEvent.click(applyButton());
    expect(h.navigate).toHaveBeenCalledWith("/reports/emp/?add=x&cols=name&cols=salary&cols=joined&group=dept");
    expect(onClose).toHaveBeenCalled();
  });

  it("multi_key_group_shows_its_text_selected_and_sends_it", async () => {
    const multi: ReportColumnsModelOut = {
      ...MODEL,
      group: "a,b",
      group_text: "Хоёр",
      keep: [],
    };
    renderPop(multi);
    await screen.findByLabelText("Нэр");
    expect(groupSelect().value).toBe("a,b");
    const option = within(groupSelect()).getByRole("option", { name: "Хоёр" }) as HTMLOptionElement;
    expect(option.selected).toBe(true);
    fireEvent.click(applyButton());
    const sent = h.navigate.mock.calls[0]?.[0] as string;
    expect(new URLSearchParams(sent.split("?")[1]).get("group")).toBe("a,b");
  });

  it("no_group_option_sends_no_group", async () => {
    const withGroup: ReportColumnsModelOut = {
      ...MODEL,
      group: "dept",
      group_text: "",
      keep: [],
    };
    renderPop(withGroup);
    await screen.findByLabelText("Нэр");
    expect(groupSelect().value).toBe("dept");
    fireEvent.change(groupSelect(), { target: { value: "" } });
    fireEvent.click(applyButton());
    expect(h.navigate).toHaveBeenCalledWith("/reports/emp/?cols=name&cols=joined");
  });

  it("cancel_and_backdrop_close_without_navigating", async () => {
    const first = renderPop(MODEL);
    await screen.findByLabelText("Нэр");
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: COLUMNS_TEXT.cancel }));
    await waitFor(() => expect(first.onClose).toHaveBeenCalledTimes(1));
    expect(h.navigate).not.toHaveBeenCalled();

    cleanup();
    const second = renderPop(MODEL);
    await screen.findByLabelText("Нэр");
    const overlay = screen.getByRole("dialog").parentElement as HTMLElement;
    fireEvent.mouseDown(overlay);
    fireEvent.click(overlay);
    await waitFor(() => expect(second.onClose).toHaveBeenCalledTimes(1));
    expect(h.navigate).not.toHaveBeenCalled();
  });

  it("loading_and_403_states", async () => {
    renderPop("pending");
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.queryByLabelText("Нэр")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();

    cleanup();
    renderPop(403);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe(COLUMNS_TEXT.loadFailed));
    expect(screen.queryByRole("button", { name: COLUMNS_TEXT.apply })).toBeNull();
  });
});
