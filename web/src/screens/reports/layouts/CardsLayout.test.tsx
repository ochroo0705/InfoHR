// The harness is imported first: it stubs fetch before ../../../api/client (and so the reports api) load.
import { fetchMock, jsonResponse, newClient, resetFetch, resetObservers, urlOf } from "../../../api/testSupport";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";
import { setCsrf } from "../../../api/client";
import type { components } from "../../../api/schema";
import { CardsLayout } from "./CardsLayout";

type CardsOut = components["schemas"]["ReportCardsOut"];
type CardOut = components["schemas"]["ReportLayoutCardOut"];

function card(overrides: Partial<CardOut> = {}): CardOut {
  return {
    extras: [],
    href: "",
    mark: "",
    photo_initial: "",
    photo_srcset: "",
    photo_url: "",
    subtitle: "",
    title: "Карт",
    ...overrides,
  };
}

function batch(items: CardOut[], nextOffset: number | null, total = 3): CardsOut {
  return { items, next_offset: nextOffset, total };
}

let client: QueryClient;

beforeEach(() => {
  resetFetch();
  setCsrf("");
  client = newClient();
});

afterEach(() => {
  cleanup();
  resetObservers();
});

function renderCards(first: CardsOut, total = first.total) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CardsLayout reportKey="staff" query="q=a" first={first} total={total} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CardsLayout", () => {
  it("empty cards show «Өгөгдөл олдсонгүй» and no grid", () => {
    const { getByText, container } = renderCards(batch([], null, 0), 0);
    expect(getByText("Өгөгдөл олдсонгүй")).toBeTruthy();
    expect(container.querySelector(".grid")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("the grid uses the template classes", () => {
    const { container } = renderCards(batch([card({ title: "Бат" })], null, 1), 1);
    expect(container.querySelector(".mt-4.grid")!.className).toBe(
      "mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3",
    );
  });

  it("card title link stretches over the card", () => {
    const { getByText } = renderCards(
      batch([card({ title: "Бат", href: "/employees/1/", subtitle: "Санхүү" })], null, 1),
    );
    const link = getByText("Бат");
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBe("/employees/1/");
    expect(link.className).toContain("after:absolute after:inset-0");
    expect(link.closest("article")!.className).toContain("relative");
    expect(link.closest("article")!.className).toContain("hover:border-violet-300");
  });

  it("card without href has plain title and no link", () => {
    const { getByText } = renderCards(batch([card({ title: "Бат" })], null, 1), 1);
    expect(getByText("Бат").tagName).toBe("H2");
    expect(getByText("Бат").querySelector("a")).toBeNull();
  });

  it("extras show label: text and a contact link keeps its href", () => {
    const { getByText } = renderCards(
      batch(
        [
          card({
            title: "Бат",
            extras: [
              { label: "Утас", text: "99112233", href: "tel:99112233" },
              { label: "Тэмдэг", text: "Идэвхтэй", href: "" },
            ],
          }),
        ],
        null,
        1,
      ),
      1,
    );
    const phone = getByText("99112233");
    expect(phone.tagName).toBe("A");
    expect(phone.getAttribute("href")).toBe("tel:99112233");
    expect(phone.className).toContain("relative z-10");
    expect(getByText("Утас:").className).toBe("text-slate-500");
    expect(getByText("Идэвхтэй").tagName).toBe("P");
    expect(getByText("Тэмдэг:")).toBeTruthy();
  });

  it("a card photo uses the url or the first-letter tile", () => {
    const { container, getByText } = renderCards(
      batch(
        [
          card({ title: "Бат", photo_url: "/media/thumb/1.jpg", photo_srcset: "/media/thumb/1-144.jpg 2x, /media/thumb/1-216.jpg 3x" }),
          card({ title: "Сарнай", photo_initial: "С" }),
          card({ title: "Номин" }),
        ],
        null,
        3,
      ),
    );
    const img = container.querySelector("img")!;
    expect(img.getAttribute("src")).toBe("/media/thumb/1.jpg");
    expect(img.getAttribute("srcset")).toBe("/media/thumb/1-144.jpg 2x, /media/thumb/1-216.jpg 3x");
    expect(img.getAttribute("width")).toBe("72");
    expect(img.getAttribute("height")).toBe("72");
    expect(img.getAttribute("loading")).toBe("lazy");

    const tile = getByText("С");
    expect(tile.className).toBe(
      "flex h-18 w-18 shrink-0 items-center justify-center rounded-xl bg-violet-100 text-2xl text-violet-700",
    );
    expect(container.querySelectorAll("img")).toHaveLength(1);
    expect(getByText("Номин").closest("article")!.querySelector("img, .bg-violet-100")).toBeNull();
  });

  it("HTML in a title is text", () => {
    const { getByText, container } = renderCards(batch([card({ title: "<i>Бат</i>" })], null, 1), 1);
    expect(getByText("<i>Бат</i>")).toBeTruthy();
    expect(container.querySelector("i")).toBeNull();
  });

  it("cards pill loads the next batch and appends", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, batch([card({ title: "Номин" }), card({ title: "Дорж" })], null)));
    const { getByRole, getByText, queryByText } = renderCards(batch([card({ title: "Бат" })], 2));

    fireEvent.click(getByRole("button", { name: "Цааш харуулах" }));

    await waitFor(() => expect(getByText("Номин")).toBeTruthy());
    expect(urlOf(0).pathname).toBe("/api/v1/reports/staff/cards");
    expect(urlOf(0).searchParams.get("q")).toBe("a");
    expect(urlOf(0).searchParams.get("offset")).toBe("2");
    expect(getByText("Бат")).toBeTruthy();
    expect(getByText("Дорж")).toBeTruthy();
    // The last batch has no next offset: the pill is gone.
    expect(queryByText("Цааш харуулах")).toBeNull();
  });

  it("failed next batch shows the alert and keeps the pill", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: [], code: "forbidden" }));
    const { getByRole, getByText } = renderCards(batch([card({ title: "Бат" })], 2));

    fireEvent.click(getByRole("button", { name: "Цааш харуулах" }));

    await waitFor(() => expect(getByRole("alert").textContent).toBe("Мэдээлэл ачаалж чадсангүй."));
    expect(getByText("Бат")).toBeTruthy();
    expect(getByRole("button", { name: "Цааш харуулах" })).toBeTruthy();
  });
});
