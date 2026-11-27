// The harness is imported first: it stubs fetch before ../../../api/client (and so the reports api) load.
import "../../../api/testSupport";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";
import type { components } from "../../../api/schema";
import { BoardLayout } from "./BoardLayout";

type BoardOut = components["schemas"]["ReportBoardOut"];
type LaneOut = components["schemas"]["ReportLaneOut"];
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

function lane(overrides: Partial<LaneOut> = {}): LaneOut {
  return { cards: [], count: 0, figure: "", href: "", label: "Ажилтан", ...overrides };
}

function board(overrides: Partial<BoardOut> = {}): BoardOut {
  return { cap: 200, lanes: [], shown: 0, total: 0, value_label: "", ...overrides };
}

function renderBoard(value: BoardOut) {
  return render(
    <MemoryRouter>
      <BoardLayout board={value} />
    </MemoryRouter>,
  );
}

afterEach(() => cleanup());

describe("BoardLayout", () => {
  it("board draws lanes with label · count · figure and the cap note", () => {
    const { getByText, queryByText } = renderBoard(
      board({
        cap: 2,
        shown: 2,
        total: 3,
        value_label: "Цалин",
        lanes: [
          lane({
            label: "Санхүү",
            count: 2,
            figure: "2,000₮",
            href: "/reports/staff/?lby=dept&lby_v=fin",
            cards: [card({ title: "Бат" }), card({ title: "Сарнай" })],
          }),
          lane({ label: "Бусад", count: 1, figure: "1,000₮", cards: [card({ title: "Номин" })] }),
        ],
      }),
    );

    expect(getByText("Утга: Цалин")).toBeTruthy();
    expect(getByText("Санхүү · 2 · 2,000₮")).toBeTruthy();
    expect(getByText("Бусад · 1 · 1,000₮")).toBeTruthy();
    expect(getByText("Бат")).toBeTruthy();
    expect(getByText("Номин")).toBeTruthy();
    expect(getByText("Эхний 2-г харууллаа. Шүүлтүүрээр нарийвчилна уу.")).toBeTruthy();
    expect(queryByText("Өгөгдөл олдсонгүй")).toBeNull();
  });

  it("no cap note when every row is shown", () => {
    const { queryByText } = renderBoard(
      board({ shown: 1, total: 1, lanes: [lane({ count: 1, cards: [card()] })] }),
    );
    expect(queryByText(/Эхний/)).toBeNull();
  });

  it("a lane past the cap shows its count and «…» instead of cards", () => {
    const { getByText, getAllByText } = renderBoard(
      board({ shown: 0, total: 2, cap: 0, lanes: [lane({ label: "Хоосон", count: 2, cards: [] })] }),
    );
    expect(getByText("Хоосон · 2")).toBeTruthy();
    expect(getAllByText("…").length).toBe(1);
  });

  it("empty board shows «Өгөгдөл олдсонгүй»", () => {
    const { getByText, queryByRole } = renderBoard(board({ total: 0, lanes: [] }));
    expect(getByText("Өгөгдөл олдсонгүй")).toBeTruthy();
    expect(queryByRole("region")).toBeNull();
  });

  it("a lane without href is text", () => {
    const { getByText, container } = renderBoard(
      board({ shown: 1, total: 1, lanes: [lane({ label: "Хэлтэс", count: 1, href: "", cards: [card()] })] }),
    );
    const heading = getByText("Хэлтэс · 1");
    expect(heading.tagName).toBe("H2");
    expect(heading.querySelector("a")).toBeNull();
    expect(container.querySelector("section")!.className).toContain("min-w-[16rem] w-64");
  });

  it("a lane with href heading is a link", () => {
    const { getByText } = renderBoard(
      board({ shown: 1, total: 1, lanes: [lane({ label: "Хэлтэс", count: 1, href: "/reports/staff/?x=1", cards: [card()] })] }),
    );
    const link = getByText("Хэлтэс · 1").closest("a")!;
    expect(link.getAttribute("href")).toBe("/reports/staff/?x=1");
  });

  it("card title link stretches over the card", () => {
    const { getByText } = renderBoard(
      board({
        shown: 1,
        total: 1,
        lanes: [lane({ count: 1, cards: [card({ title: "Бат", href: "/employees/1/" })] })],
      }),
    );
    const link = getByText("Бат");
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBe("/employees/1/");
    expect(link.className).toContain("after:absolute after:inset-0");
    expect(link.closest("li")!.className).toContain("relative");
  });

  it("HTML in a title is text", () => {
    const { getByText, container } = renderBoard(
      board({ shown: 1, total: 1, lanes: [lane({ count: 1, cards: [card({ title: "<b>Бат</b>" })] })] }),
    );
    expect(getByText("<b>Бат</b>")).toBeTruthy();
    expect(container.querySelector("b")).toBeNull();
  });
});
