// The api harness is imported first: it stubs fetch before the api modules (../../api/orders) load, as HrPopup.test.tsx does.
import { fetchMock, invalidatedKeys, jsonResponse, newClient, resetFetch, resetObservers } from "../../api/testSupport";
import type { OrderHistoryOut } from "../../api/orders";
import type { QueryClient } from "@tanstack/react-query";
import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConfirmProvider } from "../../widgets/confirm";
import { OrderHistoryModal } from "./OrderHistoryModal";
import { LOAD_FAILED_TEXT, STALE_TEXT } from "./popupGuards";

const HISTORY_PATH = "/api/v1/employees/7/orders/12/history";
const TITLE = "Тушаалын түүх: Ажилд авах · № 2026-06";
const EMPTY_TEXT = "Бүртгэл алга";

function history(entries: OrderHistoryOut["entries"] = [], title = TITLE): OrderHistoryOut {
  return { title, entries };
}

// Two entries, newest first: the first has an old → new change and an empty new value; the second has no changes.
function sampleEntries(): OrderHistoryOut["entries"] {
  return [
    {
      by: "Бат Болд",
      at: "2026-11-18 10:30",
      message: "Тушаал засагдсан",
      changes: [
        { field: "Огноо", old: "2026-11-01", new: "2026-11-19" },
        { field: "Тайлбар", old: "Хуучин тайлбар", new: "" },
      ],
    },
    { by: "Систем", at: "2026-11-17 09:00", message: "Тушаал үүсгэсэн", changes: [] },
  ];
}

let client: QueryClient;
let loadStatus = 200;
let loadOut: OrderHistoryOut = history();
let loadError: unknown = {};

function route() {
  fetchMock.mockImplementation(async (input: unknown) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (request.method === "GET" && path === HISTORY_PATH) {
      return loadStatus === 200 ? jsonResponse(200, loadOut) : jsonResponse(loadStatus, loadError);
    }
    throw new Error(`unexpected request ${request.method} ${path}`);
  });
}

// The parent remounts the pop-up for each open (a new key), as the sections do.
function renderModal(open = true, onClose = vi.fn()) {
  render(
    <ConfirmProvider>
      <QueryClientProvider client={client}>
        <OrderHistoryModal key="open-1" pk={7} orderId={12} open={open} onClose={onClose} />
      </QueryClientProvider>
    </ConfirmProvider>,
  );
  return onClose;
}

const mainDialog = () => screen.getAllByRole("dialog")[0];
// The changed row of the change list: the <dd> that follows the field's <dt>.
const valueOf = (field: string) => {
  const term = within(mainDialog()).getByText(field, { selector: "dt" });
  return term.nextElementSibling as HTMLElement;
};

beforeEach(() => {
  client = newClient();
  resetFetch();
  loadStatus = 200;
  loadOut = history(sampleEntries());
  loadError = {};
  route();
});

afterEach(() => {
  cleanup();
  resetObservers();
});

describe("OrderHistoryModal", () => {
  it("empty history shows «Бүртгэл алга» and no timeline", async () => {
    loadOut = history([]);
    renderModal();

    await screen.findByText(EMPTY_TEXT);
    expect(mainDialog().querySelector("ol")).toBeNull();
  });

  it("an entry shows the name, the time, the message and old → new with the old value struck through", async () => {
    renderModal();

    await screen.findByText("Бат Болд");
    expect(screen.getByText("2026-11-18 10:30")).not.toBeNull();
    expect(screen.getByText("Тушаал засагдсан")).not.toBeNull();
    const date = valueOf("Огноо");
    expect(date.querySelector("s")?.textContent).toBe("2026-11-01");
    expect(date.textContent).toBe("2026-11-01 → 2026-11-19");
  });

  it("an entry with an empty old value shows no strike-through and no arrow", async () => {
    loadOut = history([
      { by: "Бат Болд", at: "2026-11-18 10:30", message: "Тайлбар нэмсэн", changes: [{ field: "Тайлбар", old: "", new: "Шинэ" }] },
    ]);
    renderModal();

    await screen.findByText("Тайлбар нэмсэн");
    const note = valueOf("Тайлбар");
    expect(note.querySelector("s")).toBeNull();
    expect(note.textContent).toBe("Шинэ");
  });

  it("an empty new value shows (хоосон)", async () => {
    renderModal();

    await screen.findByText("Бат Болд");
    const note = valueOf("Тайлбар");
    expect(note.querySelector("s")?.textContent).toBe("Хуучин тайлбар");
    expect(note.textContent).toBe("Хуучин тайлбар → (хоосон)");
  });

  it("the title comes from the API", async () => {
    loadOut = history(sampleEntries(), "Тушаалын түүх: Ажилд авах · № 2026-99");
    renderModal();

    await screen.findByRole("heading", { name: "Тушаалын түүх: Ажилд авах · № 2026-99" });
  });

  it("«Хаах» calls onClose", async () => {
    const onClose = renderModal();

    await screen.findByText("Бат Болд");
    fireEvent.click(within(mainDialog()).getByText("Хаах", { selector: "button:not([data-modal-x])" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("a 404 on load shows the reload text, no timeline, and refreshes the page data", async () => {
    loadStatus = 404;
    loadError = { field_errors: {}, form_errors: [] };
    const invalidate = vi.spyOn(client, "invalidateQueries");
    renderModal();

    await screen.findByText(STALE_TEXT);
    expect(mainDialog().querySelector("ol")).toBeNull();
    expect(invalidatedKeys(invalidate)).toContainEqual({ queryKey: ["employee", 7, "work"], exact: true });
    expect(invalidatedKeys(invalidate)).toContainEqual({ queryKey: ["employee", 7, "activity"], exact: true });
  });

  // The query retries a 500 three times with the default back-off (about 7 s in all), so this test waits longer.
  it("a 500 on load shows the load message and no timeline", async () => {
    loadStatus = 500;
    loadError = {};
    renderModal();

    await screen.findByText(LOAD_FAILED_TEXT, {}, { timeout: 12000 });
    expect(mainDialog().querySelector("ol")).toBeNull();
  }, 15000);

  it("nothing is fetched while the pop-up is closed", () => {
    renderModal(false);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
