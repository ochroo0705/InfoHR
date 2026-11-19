// Fixtures and the fake event API shared by the event pop-up tests (EventModal.test.tsx, EventModal.reload.test.tsx).
// Not a test file. It imports the api harness first: the harness stubs fetch when it loads, before any api module.
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import type { components } from "../../api/schema";
import { fetchMock, jsonResponse } from "../../api/testSupport";
import { ConfirmProvider } from "../../widgets/confirm";

export type EventForm = components["schemas"]["EventFormOut"];
export type EventField = EventForm["fields"][number];
export type EventWrite = components["schemas"]["EventWriteResultOut"];

export const STALE = "Хуудсыг дахин ачаалж, дахин оролдоно уу.";
export const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";

export function renderWithClient(client: QueryClient, ui: ReactNode) {
  return render(createElement(ConfirmProvider, null, createElement(QueryClientProvider, { client }, ui)));
}

export function field(name: string, label: string, value: string, extra: Partial<EventField> = {}): EventField {
  return {
    name,
    label,
    required: false,
    kind: "text",
    value,
    checked: false,
    placeholder: "",
    choice: "",
    combo: false,
    choices: [],
    help: "",
    max_length: null,
    errors: [],
    ...extra,
  };
}

// «Ажлын байр солих»: a placement with a kind list, the effective date first, a reason and a note, and the order block.
export function transferForm(overrides: Partial<EventForm> = {}): EventForm {
  return {
    title: "Ажлын байр солих",
    kinds: [
      { value: "transfer", label: "Шилжүүлэг", selected: true },
      { value: "promotion", label: "Дэвшүүлэлт", selected: false },
    ],
    fields: [
      field("effective", "Хүчинтэй огноо", "2026-01-05", { kind: "date", required: true }),
      field("reason", "Шалтгаан", "", { required: true }),
      field("note", "Тайлбар", ""),
    ],
    order_errors: [],
    order_note: "",
    order_fields: [
      field("order-number", "Тушаалын дугаар", "", { required: true }),
      field("order-date", "Тушаалын огноо", "2026-01-05", { kind: "date" }),
      field("order-summary", "Тушаалын агуулга", ""),
      field("order-issued_by", "Тушаал гаргасан", ""),
    ],
    summary: "",
    when: "",
    prev_effective: "2026-01-05",
    reload: false,
    death_unset: false,
    errors: {},
    form_errors: [],
    ...overrides,
  };
}

export function writeAnswer(overrides: Partial<EventWrite> = {}): EventWrite {
  return {
    ok: true,
    field_errors: {},
    form_errors: [],
    order_errors: [],
    summary: "",
    when: "",
    prev_effective: "2026-01-05",
    ...overrides,
  };
}

// The pop-up's own dialog is the first one in the document (the unsaved confirm opens above it).
export const mainDialog = () => screen.getAllByRole("dialog")[0];
export const boxOf = (name: string) => document.querySelector<HTMLInputElement>(`form [name='${name}']`);
export const saveButton = (): HTMLElement => within(mainDialog()).getByRole("button", { name: "Хадгалах" });

export type Responder = (path: string, body: Record<string, unknown>) => Promise<Response>;

// Routes the two event calls of the pop-up: the form route (POST .../events/{type}/form) and the save route
// (POST .../events/{type}). Anything else fails the test. Each test file says what each route answers.
export function installEventApi(onForm: Responder, onSubmit: Responder): void {
  const FORM = /^\/api\/v1\/employees\/7\/events\/\w+\/form$/;
  const SUBMIT = /^\/api\/v1\/employees\/7\/events\/\w+$/;
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (request.method === "POST" && FORM.test(path)) return onForm(path, (await request.json()) as Record<string, unknown>);
    if (request.method === "POST" && SUBMIT.test(path)) return onSubmit(path, (await request.json()) as Record<string, unknown>);
    throw new Error(`unexpected request ${request.method} ${path}`);
  });
}

