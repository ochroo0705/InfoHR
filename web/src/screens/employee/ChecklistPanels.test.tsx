// The harness is imported first: it stubs fetch before ../../api/client (and so ../../api/checklists) load.
import { fetchMock, jsonResponse, observe, resetFetch, resetObservers, urlOf } from "../../api/testSupport";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "../../api/client";
import type { EmployeeWorkOut } from "../../api/employee";
import { openLegacyEmployee } from "../../lib/AppLink";
import { ChecklistPanels } from "./ChecklistPanels";

vi.mock("../../lib/AppLink", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/AppLink")>();
  return { ...actual, openLegacyEmployee: vi.fn() };
});

const NO_CONTENT = () => new Response(null, { status: 204 });

function row(overrides: Record<string, unknown> = {}) {
  return {
    id: 12,
    title: "Гэрээ баталгаажуулах",
    required: true,
    owner_label: "HR",
    due_on: "2026-01-10",
    overdue: false,
    done: false,
    done_label: "",
    done_rest: "—",
    title_class: "",
    due_class: "whitespace-nowrap",
    can_tick: false,
    can_untick: false,
    ...overrides,
  };
}

function panel(overrides: Record<string, unknown> = {}) {
  return {
    kind: "onboarding",
    heading: "Ажилд орох жагсаалт",
    caption: "Ажилд орох · эхлэх огноо 2026-01-05",
    checklist: true,
    checklist_id: 55,
    completed: false,
    progress: "1 / 2",
    today: "2026-11-17",
    can_start: false,
    can_cancel: false,
    rows: [],
    ...overrides,
  };
}

function work(panels: unknown[]): EmployeeWorkOut {
  return { checklist_visible: true, checklists: panels } as unknown as EmployeeWorkOut;
}

// The JSON body of the request sent at call `index` of fetchMock.
async function bodyOf(index: number): Promise<unknown> {
  const text = await (fetchMock.mock.calls[index][0] as Request).text();
  return text === "" ? undefined : JSON.parse(text);
}

function methodOf(index: number): string {
  return (fetchMock.mock.calls[index][0] as Request).method;
}

let client: QueryClient;

function panelsUi(data: EmployeeWorkOut) {
  return (
    <QueryClientProvider client={client}>
      <ChecklistPanels work={data} pk={7} />
    </QueryClientProvider>
  );
}

function renderPanels(data: EmployeeWorkOut) {
  return render(panelsUi(data));
}

beforeEach(() => {
  resetFetch();
  setCsrf("tok");
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  fetchMock.mockImplementation(async () => NO_CONTENT());
  vi.mocked(openLegacyEmployee).mockClear();
});

afterEach(() => {
  cleanup();
  resetObservers();
  expect(openLegacyEmployee).not.toHaveBeenCalled();
});

describe("ChecklistPanels", () => {
  it("«Хийгдсэн» posts the tick of that task", async () => {
    renderPanels(work([panel({ rows: [row({ id: 12, can_tick: true })] })]));

    fireEvent.click(screen.getByRole("button", { name: "Хийгдсэн" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(methodOf(0)).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/checklists/tasks/12/tick");
  });

  it("«Буцаах» posts the untick of that task", async () => {
    renderPanels(work([panel({ rows: [row({ id: 13, done: true, done_label: "Хийгдсэн", can_untick: true })] })]));

    fireEvent.click(screen.getByRole("button", { name: "Буцаах" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(methodOf(0)).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/checklists/tasks/13/untick");
  });

  it("«Цуцлах» posts the cancel of the panel's checklist, with no confirm", async () => {
    renderPanels(work([panel({ checklist_id: 55, can_cancel: true })]));

    fireEvent.click(screen.getByRole("button", { name: "Цуцлах" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(methodOf(0)).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/checklists/55/cancel");
  });

  it("the start form posts the picked date as anchor_day", async () => {
    const { container } = renderPanels(
      work([
        panel({
          kind: "offboarding",
          heading: "Ажлаас гарах жагсаалт",
          checklist: false,
          checklist_id: null,
          progress: "",
          caption: "",
          can_start: true,
        }),
      ]),
    );
    const input = container.querySelector('input[name="anchor_day"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: "2026-12-31" } });

    fireEvent.click(screen.getByRole("button", { name: "Ажлаас гарах жагсаалт эхлүүлэх" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(methodOf(0)).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/checklists/employees/7/start");
    expect(await bodyOf(0)).toEqual({ anchor_day: "2026-12-31" });
  });

  it("a 409 refusal shows its message in a role=alert line, and the line clears on the next success", async () => {
    fetchMock.mockImplementationOnce(async () =>
      jsonResponse(409, { field_errors: {}, form_errors: ["Жагсаалт хаагдсан байна."] }),
    );
    renderPanels(work([panel({ rows: [row({ id: 12, can_tick: true, can_untick: true })] })]));

    fireEvent.click(screen.getByRole("button", { name: "Хийгдсэн" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Жагсаалт хаагдсан байна.");
    expect(alert.className).toContain("text-red-700");

    fireEvent.click(screen.getByRole("button", { name: "Буцаах" }));

    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("a 400 from the start form shows Django's text", async () => {
    fetchMock.mockImplementationOnce(async () =>
      jsonResponse(400, { field_errors: {}, form_errors: ["Сүүлийн ажлын өдрийг оруулна уу."] }),
    );
    const { container } = renderPanels(
      work([
        panel({
          kind: "offboarding",
          checklist: false,
          checklist_id: null,
          progress: "",
          caption: "",
          can_start: true,
        }),
      ]),
    );
    expect((container.querySelector('input[name="anchor_day"]') as HTMLInputElement).value).toBe("2026-11-17");

    fireEvent.click(screen.getByRole("button", { name: "Ажлаас гарах жагсаалт эхлүүлэх" }));

    expect((await screen.findByRole("alert")).textContent).toBe("Сүүлийн ажлын өдрийг оруулна уу.");
  });

  it("the clicked button is disabled while its request runs", async () => {
    let answer: (response: Response) => void = () => undefined;
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          answer = resolve;
        }),
    );
    renderPanels(work([panel({ rows: [row({ id: 12, can_tick: true })] })]));
    const button = screen.getByRole("button", { name: "Хийгдсэн" }) as HTMLButtonElement;

    fireEvent.click(button);

    await waitFor(() => expect(button.disabled).toBe(true));
    answer(NO_CONTENT());
    await waitFor(() => expect(button.disabled).toBe(false));
  });

  it("while one write of the panel runs, every row button and the cancel button are disabled", async () => {
    let answer: (response: Response) => void = () => undefined;
    fetchMock.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          answer = resolve;
        }),
    );
    renderPanels(
      work([
        panel({
          can_cancel: true,
          rows: [
            row({ id: 12, can_tick: true }),
            row({ id: 13, title: "Бусад даалгавар", can_tick: true, can_untick: true, done: true }),
          ],
        }),
      ]),
    );
    const [rowA, rowB] = screen.getAllByRole("button", { name: "Хийгдсэн" }) as HTMLButtonElement[];
    const cancel = screen.getByRole("button", { name: "Цуцлах" }) as HTMLButtonElement;

    fireEvent.click(rowA);
    await waitFor(() => expect(rowA.disabled).toBe(true));

    // Row B and the cancel button cannot start a second write while the first one is pending.
    expect(rowB.disabled).toBe(true);
    expect(cancel.disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Буцаах" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(rowB);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    answer(NO_CONTENT());
    await waitFor(() => expect(rowA.disabled).toBe(false));
    expect(rowB.disabled).toBe(false);
    expect(cancel.disabled).toBe(false);
  });

  it("a 409 on tick shows its text and refetches the employee work data", async () => {
    const workSpy = observe(client, ["employee", 7, "work"]);
    await vi.waitFor(() => expect(workSpy).toHaveBeenCalledTimes(1));
    fetchMock.mockImplementationOnce(async () =>
      jsonResponse(409, { field_errors: {}, form_errors: ["Жагсаалт хаагдсан байна."] }),
    );
    renderPanels(work([panel({ rows: [row({ id: 12, can_tick: true })] })]));

    fireEvent.click(screen.getByRole("button", { name: "Хийгдсэн" }));

    expect((await screen.findByRole("alert")).textContent).toBe("Жагсаалт хаагдсан байна.");
    await vi.waitFor(() => expect(workSpy).toHaveBeenCalledTimes(2));
    // The refused row is still there, with its button enabled again for the next try.
    expect((screen.getByRole("button", { name: "Хийгдсэн" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("a 400 on the start form shows its text and does NOT refetch the employee work data", async () => {
    const workSpy = observe(client, ["employee", 7, "work"]);
    await vi.waitFor(() => expect(workSpy).toHaveBeenCalledTimes(1));
    fetchMock.mockImplementationOnce(async () =>
      jsonResponse(400, { field_errors: {}, form_errors: ["Сүүлийн ажлын өдрийг оруулна уу."] }),
    );
    renderPanels(
      work([
        panel({
          kind: "offboarding",
          checklist: false,
          checklist_id: null,
          progress: "",
          caption: "",
          can_start: true,
        }),
      ]),
    );

    fireEvent.click(screen.getByRole("button", { name: "Ажлаас гарах жагсаалт эхлүүлэх" }));

    expect((await screen.findByRole("alert")).textContent).toBe("Сүүлийн ажлын өдрийг оруулна уу.");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(workSpy).toHaveBeenCalledTimes(1);
  });

  it("after a cancel the start form shows today again, not the date typed before the checklist existed", async () => {
    const offboarding = {
      kind: "offboarding",
      heading: "Ажлаас гарах жагсаалт",
      caption: "",
      progress: "",
      can_start: true,
      checklist: false,
      checklist_id: null,
    };
    const view = renderPanels(work([panel({ ...offboarding })]));
    const input = () => view.container.querySelector('input[name="anchor_day"]') as HTMLInputElement;
    fireEvent.change(input(), { target: { value: "2026-12-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Ажлаас гарах жагсаалт эхлүүлэх" }));

    // The start succeeds: the panel now shows the checklist with its cancel button.
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    view.rerender(panelsUi(work([panel({ ...offboarding, checklist: true, checklist_id: 55, can_cancel: true, rows: [] })])));
    const cancel = screen.getByRole("button", { name: "Цуцлах" }) as HTMLButtonElement;
    await waitFor(() => expect(cancel.disabled).toBe(false));
    fireEvent.click(cancel);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(cancel.disabled).toBe(false));

    // The cancel succeeds: the start form comes back and its box shows today.
    view.rerender(panelsUi(work([panel({ ...offboarding })])));
    expect(input().value).toBe("2026-11-17");
  });

  it("the start form's date follows a new today from the server", () => {
    const offboarding = {
      kind: "offboarding",
      heading: "Ажлаас гарах жагсаалт",
      caption: "",
      progress: "",
      can_start: true,
      checklist: false,
      checklist_id: null,
    };
    const view = renderPanels(work([panel({ ...offboarding })]));
    view.rerender(panelsUi(work([panel({ ...offboarding, today: "2026-11-18" })])));

    const input = view.container.querySelector('input[name="anchor_day"]') as HTMLInputElement;
    expect(input.value).toBe("2026-11-18");
  });
});
