// The api harness is imported first: it stubs fetch before the api modules (../../api/orderDetail) load.
import { fetchMock, invalidatedKeys, jsonResponse, newClient, resetFetch, resetObservers } from "../../api/testSupport";
import type { QueryClient } from "@tanstack/react-query";
import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "../../api/client";
import type { OrderSignOut } from "../../api/orderDetail";
import { ConfirmProvider } from "../../widgets/confirm";
import { OrderSignModal } from "./OrderSignModal";

const SIGN_PATH = "/api/v1/employees/7/orders/12/sign";
const DELETE_PATH = "/api/v1/me/signature/delete";
const TITLE = "Гарын үсэг зурах · № 2026-06";
const PNG = "data:image/png;base64,AAAA";
const SUBMIT_SAVED = "Баталгаажуулж гарын үсэг зурах";
const SUBMIT_DRAW = "Гарын үсэг зурах";
const STALE = "Хуудсыг дахин ачаалж, дахин оролдоно уу.";

let client: QueryClient;
let signOut: OrderSignOut;
let signed: { ok: boolean; errors: string[] };
let signStatus = 200;
let deleted = false;

function route() {
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (request.method === "GET" && path === SIGN_PATH) {
      return jsonResponse(200, signOut);
    }
    if (request.method === "POST" && path === SIGN_PATH) {
      return signStatus === 200 ? jsonResponse(200, signed) : jsonResponse(signStatus, { field_errors: {}, form_errors: [] });
    }
    if (request.method === "POST" && path === DELETE_PATH) {
      deleted = true;
      return jsonResponse(200, { ok: true });
    }
    throw new Error(`unexpected request ${request.method} ${path}`);
  });
}

// The parent remounts the pop-up for each open (a new key), as the sections do.
function renderModal(onClose = vi.fn()) {
  render(
    <ConfirmProvider>
      <QueryClientProvider client={client}>
        <OrderSignModal key="open-1" pk={7} orderId={12} open onClose={onClose} />
      </QueryClientProvider>
    </ConfirmProvider>,
  );
  return onClose;
}

// A finished stroke on the pad: a pointer down and up on the canvas (jsdom has no canvas, so getContext is stubbed).
function drawStroke() {
  const canvas = document.querySelector("canvas") as HTMLCanvasElement;
  fireEvent(canvas, new PointerEvent("pointerdown", { bubbles: true, cancelable: true, button: 0, clientX: 10, clientY: 10, pointerId: 1 } as PointerEventInit));
  fireEvent(canvas, new PointerEvent("pointerup", { bubbles: true, cancelable: true, button: 0, clientX: 20, clientY: 20, pointerId: 1 } as PointerEventInit));
}

const submitButton = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;

// The POST bodies sent so far, in order.
async function postBodies(path: string) {
  const bodies: Record<string, unknown>[] = [];
  for (const call of fetchMock.mock.calls) {
    const request = call[0] as Request;
    if (request.method === "POST" && new URL(request.url).pathname === path) {
      bodies.push((await request.clone().json()) as Record<string, unknown>);
    }
  }
  return bodies;
}

beforeEach(() => {
  client = newClient();
  resetFetch();
  setCsrf("");
  signOut = { has_saved: true, saved_url: "/api/v1/me/signature/image", title: TITLE };
  signed = { ok: true, errors: [] };
  signStatus = 200;
  deleted = false;
  route();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    () => ({ beginPath() {}, arc() {}, fill() {}, moveTo() {}, lineTo() {}, stroke() {}, clearRect() {} }) as unknown as CanvasRenderingContext2D,
  );
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockImplementation(() => PNG);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  resetObservers();
});

describe("OrderSignModal", () => {
  it("saved section shown first when has_saved", async () => {
    renderModal();

    await screen.findByText(TITLE);
    expect(screen.getByAltText("Хадгалсан гарын үсэг").getAttribute("src")).toBe("/api/v1/me/signature/image");
    expect(submitButton(SUBMIT_SAVED)).not.toBeNull();
    expect(screen.queryByRole("button", { name: SUBMIT_DRAW })).toBeNull();
  });

  it("draw section shown first without a saved signature", async () => {
    signOut = { ...signOut, has_saved: false };
    renderModal();

    await screen.findByText(TITLE);
    expect(submitButton(SUBMIT_DRAW)).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Буцах" })).toBeNull();
    expect(screen.queryByRole("button", { name: SUBMIT_SAVED })).toBeNull();
  });

  it("submit button disabled until a stroke", async () => {
    signOut = { ...signOut, has_saved: false };
    renderModal();

    await screen.findByText(TITLE);
    expect(submitButton(SUBMIT_DRAW).disabled).toBe(true);
    drawStroke();
    await waitFor(() => expect(submitButton(SUBMIT_DRAW).disabled).toBe(false));
  });

  it("drawn submit posts mode drawn with the data url and remember", async () => {
    signOut = { ...signOut, has_saved: false };
    const onClose = renderModal();

    await screen.findByText(TITLE);
    drawStroke();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(submitButton(SUBMIT_DRAW));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    const bodies = await postBodies(SIGN_PATH);
    expect(bodies).toEqual([{ mode: "drawn", signature: PNG, remember: true }]);
  });

  it("saved submit posts mode saved with an empty signature", async () => {
    const onClose = renderModal();

    await screen.findByText(TITLE);
    fireEvent.click(submitButton(SUBMIT_SAVED));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    const bodies = await postBodies(SIGN_PATH);
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({ mode: "saved", signature: "" });
  });

  it("delete asks then deletes then shows the draw section", async () => {
    renderModal();

    await screen.findByText(TITLE);
    fireEvent.click(screen.getByRole("button", { name: "Устгах" }));
    expect(screen.getByText("Хадгалсан гарын үсгийг устгах уу?")).not.toBeNull();
    expect(deleted).toBe(false);

    signOut = { ...signOut, has_saved: false };
    fireEvent.click(screen.getByRole("button", { name: "Тийм" }));

    await waitFor(() => expect(deleted).toBe(true));
    await screen.findByRole("button", { name: SUBMIT_DRAW });
    expect(screen.queryByRole("button", { name: "Буцах" })).toBeNull();
    expect(screen.queryByRole("button", { name: SUBMIT_SAVED })).toBeNull();
  });

  it("server errors show in the red list and keep the pad", async () => {
    signOut = { ...signOut, has_saved: false };
    signed = { ok: false, errors: ["Гарын үсэг хоосон байна.", "Дахин оролдоно уу."] };
    const onClose = renderModal();

    await screen.findByText(TITLE);
    drawStroke();
    fireEvent.click(submitButton(SUBMIT_DRAW));

    const items = await waitFor(() => {
      const list = document.querySelector("ul.list-disc");
      expect(list).not.toBeNull();
      return Array.from(list!.querySelectorAll("li")).map((li) => li.textContent);
    });
    expect(items).toEqual(["Гарын үсэг хоосон байна.", "Дахин оролдоно уу."]);
    expect(onClose).not.toHaveBeenCalled();
    expect(submitButton(SUBMIT_DRAW).disabled).toBe(false);
  });

  it("saved signature gone after a refused submit: the sign state is read again and the draw pad shows", async () => {
    const SAVED_MISSING = "Хадгалсан гарын үсэг алга. Шинээр зурна уу.";
    signed = { ok: false, errors: [SAVED_MISSING] };
    const onClose = renderModal();

    await screen.findByText(TITLE);
    expect(screen.getByAltText("Хадгалсан гарын үсэг")).not.toBeNull();
    const getsBefore = fetchMock.mock.calls.filter((call) => (call[0] as Request).method === "GET").length;

    // The saved signature was deleted meanwhile: the next sign-state answer has no saved signature.
    signOut = { ...signOut, has_saved: false };
    fireEvent.click(submitButton(SUBMIT_SAVED));

    const list = await waitFor(() => {
      const found = document.querySelector("ul.list-disc");
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(list.textContent).toBe(SAVED_MISSING);
    await screen.findByRole("button", { name: SUBMIT_DRAW });
    expect(screen.queryByAltText("Хадгалсан гарын үсэг")).toBeNull();
    expect((document.querySelector('[data-sign-section="draw"]') as HTMLElement).hidden).toBe(false);
    const getsAfter = fetchMock.mock.calls.filter((call) => (call[0] as Request).method === "GET").length;
    expect(getsAfter).toBeGreaterThan(getsBefore);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("404 on submit refreshes work and activity", async () => {
    signStatus = 404;
    const onClose = renderModal();
    const spy = vi.spyOn(client, "invalidateQueries");

    await screen.findByText(TITLE);
    fireEvent.click(submitButton(SUBMIT_SAVED));

    await screen.findByText(STALE);
    const keys = invalidatedKeys(spy).map((filter) => filter.queryKey);
    expect(keys).toContainEqual(["employee", 7, "work"]);
    expect(keys).toContainEqual(["employee", 7, "activity"]);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("double Enter sends one request", async () => {
    let release: (value: Response) => void = () => undefined;
    fetchMock.mockImplementation(async (input: unknown) => {
      const request = input as Request;
      const path = new URL(request.url).pathname;
      if (request.method === "GET" && path === SIGN_PATH) return jsonResponse(200, signOut);
      if (request.method === "POST" && path === SIGN_PATH) {
        return new Promise<Response>((resolve) => {
          release = resolve;
        });
      }
      throw new Error(`unexpected request ${request.method} ${path}`);
    });
    renderModal();

    await screen.findByText(TITLE);
    const form = submitButton(SUBMIT_SAVED).closest("form") as HTMLFormElement;
    fireEvent.submit(form);
    fireEvent.submit(form);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(await postBodies(SIGN_PATH)).toHaveLength(1);
    release(jsonResponse(200, signed));
  });

  it("success closes", async () => {
    const onClose = renderModal();

    await screen.findByText(TITLE);
    fireEvent.click(submitButton(SUBMIT_SAVED));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });
});
