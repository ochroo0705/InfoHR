// The «Санал болгох» (order-number suggest) button of the event pop-up next to other boxes: a department pick, a typed
// reason and position must keep their values through the suggest click, and a save after it posts them all.
// The api harness stubs fetch when it loads, so it is imported before the event pop-up (which imports the api client).
// The fixtures and the fake API are in eventModalTestSupport.ts, which imports the harness first.
import type { QueryClient } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchMock, jsonResponse, newClient, resetFetch, resetObservers } from "../../api/testSupport";
import { boxOf, field, mainDialog, renderWithClient, saveButton, transferForm, writeAnswer } from "./eventModalTestSupport";
import { EventModal } from "./EventModal";

const TITLE = "Ажлын байр солих";
const SUGGEST_ANSWER = { number: "209", date: "2026-11-19" };

let client: QueryClient;

// Every request the pop-up makes in these tests.
let suggestCalls: string[] = [];
let formPaths: string[] = [];
let submits: Record<string, unknown>[] = [];

// The event form: a department select (a click list, not a typing box) and a position text box, besides the transfer
// boxes. The order-date box starts empty, so the suggest answer may fill it.
function suggestForm() {
  return transferForm({
    fields: [
      field("effective", "Хүчинтэй огноо", "2026-01-05", { kind: "date", required: true }),
      field("department", "Хэлтэс", "1", {
        kind: "select",
        choices: [
          { value: "1", label: "Санхүү" },
          { value: "2", label: "Худалдаа" },
        ],
      }),
      field("position", "Албан тушаал", ""),
      field("reason", "Шалтгаан", "", { required: true }),
      field("note", "Тайлбар", ""),
    ],
    order_fields: [
      field("order-number", "Тушаалын дугаар", "", { required: true }),
      field("order-date", "Тушаалын огноо", "", { kind: "date" }),
      field("order-summary", "Тушаалын агуулга", ""),
      field("order-issued_by", "Тушаал гаргасан", ""),
    ],
  });
}

let eventForm = suggestForm();

beforeEach(() => {
  client = newClient();
  resetFetch();
  suggestCalls = [];
  formPaths = [];
  submits = [];
  eventForm = suggestForm();
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/v1/employees/order-suggest") {
      suggestCalls.push(url.search);
      return jsonResponse(200, SUGGEST_ANSWER);
    }
    if (request.method === "POST" && /^\/api\/v1\/employees\/7\/events\/\w+\/form$/.test(url.pathname)) {
      formPaths.push(url.pathname);
      return jsonResponse(200, eventForm);
    }
    if (request.method === "POST" && /^\/api\/v1\/employees\/7\/events\/\w+$/.test(url.pathname)) {
      const body = (await request.json()) as Record<string, unknown>;
      submits.push(body);
      return jsonResponse(200, writeAnswer());
    }
    throw new Error(`unexpected request ${request.method} ${url.pathname}`);
  });
});

afterEach(() => {
  cleanup();
  resetObservers();
});

const suggestButton = () => within(mainDialog()).getByRole("button", { name: "Санал болгох" });

// Picks an option of a click-list select the way a user does: a mousedown opens the list, a click on an item picks it.
function pickOption(name: string, label: string) {
  fireEvent.mouseDown(document.querySelector<HTMLSelectElement>(`form select[name='${name}']`) as HTMLSelectElement);
  // The open list is the listbox in the body; the native options of the select have the same names, so scope to it.
  fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: label }));
}

// Waits until the number of form requests reaches the given count and lets the answers settle.
async function formRequestsAre(count: number) {
  await waitFor(() => expect(formPaths).toHaveLength(count));
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("EventModal suggest (Task 15c): other boxes keep their values", () => {
  it("a department pick survives the suggest click, and the suggest fills the order boxes without a reload or a summary request", async () => {
    renderWithClient(client, <EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    pickOption("department", "Худалдаа");
    await formRequestsAre(1);
    expect(boxOf("department")?.value).toBe("2");

    const formsBefore = formPaths.length;
    fireEvent.click(suggestButton());

    await waitFor(() => expect(suggestCalls).toHaveLength(1));
    await waitFor(() => expect(boxOf("order-number")?.value).toBe("209"));
    await waitFor(() => expect(boxOf("order-date")?.value).toBe("2026-11-19"));
    await formRequestsAre(formsBefore);

    expect(boxOf("department")?.value).toBe("2");
    expect(formPaths).toHaveLength(formsBefore);
  });

  it("a typed reason and position survive the suggest click, with the picked department", async () => {
    renderWithClient(client, <EventModal pk={7} type="transfer" open onClose={vi.fn()} />);

    await screen.findByRole("heading", { name: TITLE });
    pickOption("department", "Худалдаа");
    await formRequestsAre(1);
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Шилжүүлсэн" } });
    await formRequestsAre(2);
    fireEvent.change(boxOf("position") as HTMLInputElement, { target: { value: "Ахлах мэргэжилтэн" } });
    await formRequestsAre(3);

    const formsBefore = formPaths.length;
    fireEvent.click(suggestButton());

    await waitFor(() => expect(boxOf("order-number")?.value).toBe("209"));
    await waitFor(() => expect(boxOf("order-date")?.value).toBe("2026-11-19"));
    await formRequestsAre(formsBefore);

    expect(boxOf("department")?.value).toBe("2");
    expect(boxOf("reason")?.value).toBe("Шилжүүлсэн");
    expect(boxOf("position")?.value).toBe("Ахлах мэргэжилтэн");
    expect(formPaths).toHaveLength(formsBefore);
  });

  it("a save after the suggest posts the picked department and the suggested order number and date", async () => {
    const onClose = vi.fn();
    renderWithClient(client, <EventModal pk={7} type="transfer" open onClose={onClose} />);

    await screen.findByRole("heading", { name: TITLE });
    pickOption("department", "Худалдаа");
    await formRequestsAre(1);
    fireEvent.change(boxOf("reason") as HTMLInputElement, { target: { value: "Шилжүүлсэн" } });
    await formRequestsAre(2);
    fireEvent.click(suggestButton());
    await waitFor(() => expect(boxOf("order-number")?.value).toBe("209"));
    await waitFor(() => expect(boxOf("order-date")?.value).toBe("2026-11-19"));

    fireEvent.click(saveButton());

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(submits).toHaveLength(1);
    expect(submits[0].values).toMatchObject({
      department: "2",
      reason: "Шилжүүлсэн",
      "order-number": "209",
      "order-date": "2026-11-19",
    });
  });
});
