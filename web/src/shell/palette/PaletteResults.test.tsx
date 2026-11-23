// PaletteResults draws the answer the API sent: group order, counts and totals, highlights, the empty block, the note, the
// failure line, the busy dim on the rows only, the scroll reset and the href rule. No test expects the component to sort or
// filter anything.
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PaletteOut, PaletteRowOut } from "../../api/palette";
import { PaletteResults } from "./PaletteResults";

function row(over: Partial<PaletteRowOut> & { key: string }): PaletteRowOut {
  return {
    code: [],
    day: "",
    initials: "",
    kind: "page",
    left: false,
    lines: [],
    open: { employee: null, event_type: null, kind: "page", order: null, path: "/x/", popup: null, year: null },
    ref: null,
    title: [{ text: "Тайлан", hit: false }],
    ...over,
  };
}

const PEOPLE = row({
  key: "person:1",
  kind: "person",
  ref: "p:1",
  initials: "БА",
  title: [{ text: "Бат", hit: true }, { text: "-Очир", hit: false }],
  code: [{ text: "E001", hit: false }],
  lines: [[{ text: "Нягтлан", hit: true }], [{ text: "Санхүү", hit: false }]],
  open: { employee: 1, event_type: null, kind: "page", order: null, path: "/employees/1/", popup: null, year: null },
});
const PAGE = row({ key: "page:leave", title: [{ text: "Чөлөө", hit: false }] });
const MORE = row({
  key: "people:more",
  kind: "more",
  open: null,
  title: [{ text: "Бүх 40 хүнийг харуулах", hit: false }],
});

function answer(over: Partial<PaletteOut> = {}): PaletteOut {
  return {
    empty: false,
    empty_text: "Юу ч олдсонгүй",
    fallback: [],
    fallback_heading: "Эсвэл нээх:",
    groups: [
      { key: "people", title: "Хүмүүс", count: 2, total: 40, rows: [PEOPLE, MORE], note: "" },
      { key: "screens", title: "Хуудас", count: 1, total: null, rows: [PAGE], note: "" },
    ],
    ...over,
  };
}

function renderResults(props: Partial<Parameters<typeof PaletteResults>[0]> = {}) {
  const handlers = { onSelect: vi.fn(), onActivate: vi.fn() };
  const view = render(
    <PaletteResults answer={answer()} busy={false} failed={false} selectedKey={null} {...handlers} {...props} />,
  );
  return { ...view, ...handlers };
}

describe("PaletteResults", () => {
  afterEach(() => cleanup());

  it("renders groups in the API order with counts and totals", () => {
    const { container } = renderResults();
    const heads = Array.from(container.querySelectorAll("p.sticky")).map((p) => p.textContent);
    expect(heads).toEqual(["Хүмүүс2 / 40", "Хуудас1"]);
    const list = container.querySelector("[data-palette-results]");
    expect(list?.getAttribute("role")).toBe("listbox");
    expect(list?.id).toBe("palette-results");
  });

  it("shows the total exactly as the API sends it", () => {
    const { container } = renderResults({
      answer: answer({
        groups: [{ key: "people", title: "Хүмүүс", count: 3, total: null, rows: [], note: "" }],
      }),
    });
    expect(container.querySelector("p.sticky")?.textContent).toBe("Хүмүүс3");
  });

  it("highlights the hit pieces", () => {
    const { container } = renderResults();
    const marks = Array.from(container.querySelectorAll("mark")).map((m) => m.textContent);
    expect(marks).toEqual(["Бат", "Нягтлан"]);
    expect(container.querySelector("mark")?.className).toContain("bg-violet-200/60");
  });

  it("draws a person's lines as the API sent them", () => {
    const { container } = renderResults();
    const person = container.querySelector('[data-palette-ref="p:1"]') as HTMLElement;
    const lines = Array.from(person.querySelectorAll("span.block.truncate")).map((s) => s.textContent);
    expect(lines).toEqual(["Нягтлан", "Санхүү"]);
  });

  it("draws an order row as the order template does: title, then the day line", () => {
    const order = row({
      key: "order:12",
      kind: "order",
      day: "2026-11-20",
      title: [{ text: "Тушаал №12", hit: true }],
      open: { employee: null, event_type: null, kind: "popup", order: 12, path: "/orders/12/", popup: "order_detail", year: null },
    });
    const { container } = renderResults({
      answer: answer({ groups: [{ key: "orders", title: "Тушаал", count: 1, total: null, rows: [order], note: "" }] }),
    });
    const option = container.querySelector('[role="option"]') as HTMLElement;
    expect(option.getAttribute("data-palette-modal")).toBe("");
    const wrap = option.querySelector("span.min-w-0") as HTMLElement;
    expect(wrap.children[0].className).toBe("block truncate");
    expect(wrap.children[0].querySelector("mark")?.textContent).toBe("Тушаал №12");
    expect(wrap.children[1].className).toBe("block text-xs text-slate-500");
    expect(wrap.children[1].textContent).toBe("2026-11-20");
  });

  it("selected row has aria-selected", () => {
    const { container } = renderResults({ selectedKey: "page:leave" });
    const options = Array.from(container.querySelectorAll('[role="option"]'));
    const selected = options.filter((o) => o.getAttribute("aria-selected") === "true");
    expect(selected).toHaveLength(1);
    expect(selected[0].textContent).toContain("Чөлөө");
    expect(options.find((o) => o.textContent?.includes("Бат"))?.getAttribute("aria-selected")).toBe("false");
  });

  it("shows the empty block with fallback rows", () => {
    const fallback = [row({ key: "fallback:list", title: [{ text: "Ажилтнууд", hit: false }] })];
    const { container } = renderResults({
      answer: { empty: true, empty_text: "Юу ч олдсонгүй", fallback, fallback_heading: "Эсвэл нээх:", groups: [] },
    });
    expect(container.querySelector("[data-palette-empty]")?.textContent).toBe("Юу ч олдсонгүй");
    expect(container.textContent).toContain("Эсвэл нээх:");
    expect(container.querySelectorAll('[role="option"]')).toHaveLength(1);
    expect(container.textContent).toContain("Ажилтнууд");
  });

  it("shows the group note paragraph", () => {
    const { container } = renderResults({
      answer: answer({
        groups: [
          {
            key: "people",
            title: "Хүмүүс",
            count: 50,
            total: 80,
            rows: [PEOPLE],
            note: "Эхний 50 хүн харагдаж байна. Хайлтаа нарийсгана уу.",
          },
        ],
      }),
    });
    const note = container.querySelector("[data-palette-cut]");
    expect(note?.tagName).toBe("P");
    expect(note?.textContent).toBe("Эхний 50 хүн харагдаж байна. Хайлтаа нарийсгана уу.");
  });

  it("dims only the rows while busy, and marks aria-busy on the listbox", () => {
    const { container, rerender } = renderResults({ busy: true });
    const list = container.querySelector("[data-palette-results]") as HTMLElement;
    expect(list.getAttribute("aria-busy")).toBe("true");
    expect(list.classList.contains("opacity-60")).toBe(false);
    const rows = Array.from(container.querySelectorAll('[role="option"]'));
    expect(rows.length).toBeGreaterThan(0);
    rows.forEach((r) => expect(r.classList.contains("opacity-60")).toBe(true));
    const head = container.querySelector("p.sticky") as HTMLElement;
    expect(head.classList.contains("opacity-60")).toBe(false);
    expect(container.querySelector("[data-palette-cut]")).toBeNull();

    rerender(
      <PaletteResults answer={answer()} busy={false} failed={false} selectedKey={null} onSelect={vi.fn()} onActivate={vi.fn()} />,
    );
    expect(list.hasAttribute("aria-busy")).toBe(false);
    Array.from(container.querySelectorAll('[role="option"]')).forEach((r) =>
      expect(r.classList.contains("opacity-60")).toBe(false),
    );
  });

  it("keeps the empty text bright while busy", () => {
    const { container } = renderResults({
      busy: true,
      answer: { empty: true, empty_text: "Юу ч олдсонгүй", fallback: [], fallback_heading: "Эсвэл нээх:", groups: [] },
    });
    expect(container.querySelector("[data-palette-empty]")?.classList.contains("opacity-60")).toBe(false);
  });

  it("shows the failure line", () => {
    const { container } = renderResults({ answer: null, failed: true });
    const line = container.querySelector("[data-palette-failed]");
    expect(line?.textContent).toBe("Хайлт амжилтгүй боллоо");
    expect(container.querySelectorAll('[role="option"]')).toHaveLength(0);
  });

  it("shows the show-all row as an option without a link, and activates it", () => {
    const { container, onActivate } = renderResults();
    const more = container.querySelector("[data-palette-more]") as HTMLElement;
    expect(more.getAttribute("role")).toBe("option");
    expect(more.tagName).toBe("DIV");
    fireEvent.click(more);
    expect(onActivate).toHaveBeenCalledWith(MORE);
  });

  it("reports a row click to onActivate and a pointer move to onSelect", () => {
    const { container, onActivate, onSelect } = renderResults({ selectedKey: "page:leave" });
    const person = container.querySelector('[data-palette-ref="p:1"]') as HTMLElement;
    fireEvent.mouseMove(person);
    expect(onSelect).toHaveBeenCalledWith("person:1");
    fireEvent.click(person);
    expect(onActivate).toHaveBeenCalledWith(PEOPLE);
  });

  it("renders the href only for a same-site relative path", () => {
    const { container } = renderResults();
    const person = container.querySelector('[data-palette-ref="p:1"]') as HTMLAnchorElement;
    expect(person.tagName).toBe("A");
    expect(person.getAttribute("href")).toBe("/employees/1/");
  });

  it("renders a javascript: path without an href and still selectable", () => {
    const unsafe = row({
      key: "page:bad",
      title: [{ text: "Бүдүүлэг", hit: false }],
      open: { employee: null, event_type: null, kind: "page", order: null, path: "javascript:alert(1)", popup: null, year: null },
    });
    const { container, onActivate, onSelect } = renderResults({
      answer: answer({ groups: [{ key: "screens", title: "Хуудас", count: 1, total: null, rows: [unsafe], note: "" }] }),
    });
    const option = container.querySelector('[role="option"]') as HTMLElement;
    expect(option.tagName).toBe("DIV");
    expect(option.hasAttribute("href")).toBe(false);
    fireEvent.mouseMove(option);
    expect(onSelect).toHaveBeenCalledWith("page:bad");
    fireEvent.click(option);
    expect(onActivate).toHaveBeenCalledWith(unsafe);
  });

  it("scrolls the list back to the top on a new answer", () => {
    const { container, rerender } = renderResults();
    const list = container.querySelector("[data-palette-results]") as HTMLElement;
    list.scrollTop = 80;
    rerender(
      <PaletteResults answer={answer()} busy={false} failed={false} selectedKey={null} onSelect={vi.fn()} onActivate={vi.fn()} />,
    );
    expect(list.scrollTop).toBe(0);
  });

  it("the empty box is capped at 40vh and scrolls inside it, with overscroll contained and a float rail", () => {
    const { container } = renderResults();
    const list = container.querySelector("[data-palette-results]") as HTMLElement;
    expect(list.classList.contains("max-h-[40vh]")).toBe(true);
    expect(list.classList.contains("overflow-y-auto")).toBe(true);
    expect(list.classList.contains("overscroll-contain")).toBe(true);
    // palette.js: scrollbars.js gives every overflow-y-auto box a rail, so the list gets the float rail (in body).
    expect(list.classList.contains("sbar-on")).toBe(true);
    expect(document.body.querySelector(".sbar-y")).not.toBeNull();
  });

  it("keeps the scroll position for a show-all answer", () => {
    const { container, rerender } = renderResults();
    const list = container.querySelector("[data-palette-results]") as HTMLElement;
    list.scrollTop = 80;
    rerender(
      <PaletteResults
        answer={answer({ groups: [{ key: "people", title: "Хүмүүс", count: 9, total: 40, rows: [PEOPLE], note: "" }] })}
        busy={false}
        failed={false}
        keepScroll
        selectedKey={null}
        onSelect={vi.fn()}
        onActivate={vi.fn()}
      />,
    );
    expect(list.scrollTop).toBe(80);
  });
});
