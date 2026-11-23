import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { LogSystemRowOut } from "../../api/logs";
import { SystemLogTable, type SystemLogTableProps } from "./SystemLogTable";

function entry(over: Partial<LogSystemRowOut> = {}): LogSystemRowOut {
  return {
    action_label: "Нэвтрэх",
    actor_name: "Бат Болд",
    category_label: "Нэвтрэлт",
    changes: [],
    date: "2026-11-20",
    id: 1,
    ip: "10.0.0.5",
    message: "Системд нэвтэрлээ",
    target_label: "",
    target_type: "",
    time: "10:15",
    ...over,
  };
}

let observerCallback: IntersectionObserverCallback | null = null;

beforeEach(() => {
  observerCallback = null;
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(callback: IntersectionObserverCallback) {
        observerCallback = callback;
      }
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    },
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderTable(overrides: Partial<SystemLogTableProps> = {}) {
  const props: SystemLogTableProps = {
    rows: [],
    hasMore: false,
    loadingMore: false,
    onMore: vi.fn(),
    ...overrides,
  };
  const view = render(
    <MemoryRouter>
      <SystemLogTable {...props} />
    </MemoryRouter>,
  );
  return { ...view, props };
}

function rowOf(container: HTMLElement, index = 0): HTMLTableRowElement {
  return container.querySelectorAll("tbody tr")[index] as HTMLTableRowElement;
}

function cellOf(container: HTMLElement, index: number, cell: number): HTMLTableCellElement {
  return rowOf(container, index).querySelectorAll("td")[cell] as HTMLTableCellElement;
}

describe("SystemLogTable", () => {
  it("seven heads, with the Зорилт and Дэлгэрэнгүй classes of the template", () => {
    const { container } = renderTable();
    const heads = Array.from(container.querySelectorAll("thead th"));
    expect(heads.map((th) => th.textContent?.replace(/\s*Нэвтрэх.*$/, "").trim())).toEqual([
      "Огноо",
      "Хэн",
      "Ангилал",
      "Үйлдэл",
      "Зорилт",
      "Дэлгэрэнгүй",
      "IP",
    ]);
    expect(heads[4].className).toContain("min-w-40");
    expect(heads[5].className).toContain("w-full");
    expect(container.querySelector(".ptable.ptable-fit.card-soft")).not.toBeNull();
  });

  it("the who head carries the hint line", () => {
    const { container } = renderTable();
    const hint = container.querySelector("thead th span") as HTMLElement;
    expect(hint.textContent).toBe("Нэвтрэх нэр (буруу оруулсан байж болно)");
    expect(hint.className).toContain("w-36");
    expect(hint.className).toContain("text-xs");
    expect(hint.className).toContain("text-slate-400");
  });

  it("rows have no click handler and no hover class", () => {
    const { container } = renderTable({ rows: [entry()] });
    const tr = rowOf(container);
    expect(tr.className).toBe("align-top");
    expect(tr.className).not.toContain("cursor-pointer");
    expect(tr.className).not.toContain("hover:bg-violet-50");
    expect(tr.querySelector("button")).toBeNull();
    expect(tr.querySelector("a")).toBeNull();
    expect(tr.getAttribute("role")).toBeNull();

    // React's own props of the DOM node: no onClick (or any other handler) is attached to the row.
    const reactPropsKey = Object.keys(tr).find((key) => key.startsWith("__reactProps$"));
    expect(reactPropsKey).toBeDefined();
    const reactProps = (tr as unknown as Record<string, Record<string, unknown>>)[reactPropsKey!];
    expect(reactProps.onClick).toBeUndefined();
    expect(Object.keys(reactProps).filter((key) => key.startsWith("on"))).toEqual([]);

    // Clicking the row changes nothing in the DOM.
    const before = container.innerHTML;
    fireEvent.click(tr);
    expect(container.innerHTML).toBe(before);

    // Nothing in the row can take focus or act as a control.
    expect(tr.querySelectorAll('[tabindex], [role], button, a, input, select, textarea')).toHaveLength(0);
  });

  it("row draws target type above the label only when present", () => {
    const { container } = renderTable({
      rows: [
        entry({ target_type: "Ажилтан", target_label: "Бат Болд" }),
        entry({ id: 2, target_type: "", target_label: "Хэрэглэгч" }),
      ],
    });
    const withType = cellOf(container, 0, 4);
    const typeLine = withType.querySelector("span") as HTMLElement;
    expect(typeLine.textContent).toBe("Ажилтан");
    expect(typeLine.className).toContain("block");
    expect(typeLine.className).toContain("text-xs");
    expect(typeLine.className).toContain("text-slate-500");
    expect(withType.textContent).toBe("АжилтанБат Болд");

    const withoutType = cellOf(container, 1, 4);
    expect(withoutType.querySelector("span")).toBeNull();
    expect(withoutType.textContent).toBe("Хэрэглэгч");
  });

  it("actor is drawn as the API gives it, with no client text of its own", () => {
    const { container } = renderTable({
      rows: [entry({ actor_name: "Систем" }), entry({ id: 2, actor_name: "" })],
    });
    expect(cellOf(container, 0, 1).textContent).toBe("Систем");
    expect(cellOf(container, 0, 1).className).toContain("whitespace-nowrap");
    expect(cellOf(container, 1, 1).textContent).toBe("");
  });

  it("date cell shows the date and the time, category and action come as given", () => {
    const { container } = renderTable({ rows: [entry({ category_label: "Өгөгдөл", action_label: "Засах" })] });
    expect(cellOf(container, 0, 0).textContent).toBe("2026-11-20 10:15");
    expect(cellOf(container, 0, 2).textContent).toBe("Өгөгдөл");
    expect(cellOf(container, 0, 3).textContent).toBe("Засах");
  });

  it("ip cell is nowrap and slate-600, and empty when there is no ip", () => {
    const { container } = renderTable({ rows: [entry(), entry({ id: 2, ip: "" })] });
    const ip = cellOf(container, 0, 6);
    expect(ip.textContent).toBe("10.0.0.5");
    expect(ip.className).toContain("whitespace-nowrap");
    expect(ip.className).toContain("text-slate-600");
    expect(cellOf(container, 1, 6).textContent).toBe("");
  });

  it("message is drawn as slate text and changes use the change list", () => {
    const { container } = renderTable({
      rows: [entry({ message: "<b>эхний</b>", changes: [{ field: "Статус", old: "", new: "" }] })],
    });
    const msg = cellOf(container, 0, 5).querySelector("p") as HTMLElement;
    expect(msg.className).toContain("text-slate-700");
    expect(msg.textContent).toBe("<b>эхний</b>");
    expect(msg.querySelector("b")).toBeNull();
    expect(cellOf(container, 0, 5).querySelector("dl")?.textContent).toContain("(хоосон)");
  });

  it("empty state", () => {
    const { container } = renderTable({ rows: [] });
    const cell = screen.getByText("Бүртгэл олдсонгүй");
    expect(cell.tagName).toBe("TD");
    expect(cell.getAttribute("colspan")).toBe("7");
    expect(container.querySelector("tbody")?.textContent).toContain("Бүртгэл олдсонгүй");
  });

  it("settling draws no empty-state row", () => {
    renderTable({ rows: [], settling: true });
    expect(screen.queryByText("Бүртгэл олдсонгүй")).toBeNull();
  });

  it("the pill calls onMore once when it scrolls into view and again on click", () => {
    const { props } = renderTable({ rows: [entry()], hasMore: true });
    expect(observerCallback).not.toBeNull();
    observerCallback!([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
    expect(props.onMore).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));
    expect(props.onMore).toHaveBeenCalledTimes(2);
  });

  it("the pill spans all seven columns", () => {
    const { container } = renderTable({ rows: [entry()], hasMore: true });
    const more = container.querySelector("tr[data-more-row] td") as HTMLTableCellElement;
    expect(more.getAttribute("colspan")).toBe("7");
  });

  it("autoLoad false keeps the pill from loading by scrolling, and its click still loads", () => {
    const { props } = renderTable({ rows: [entry()], hasMore: true, autoLoad: false });
    expect(observerCallback).toBeNull();
    expect(props.onMore).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));
    expect(props.onMore).toHaveBeenCalledTimes(1);
  });

  it("while a batch loads the pill neither observes nor calls onMore on click", () => {
    const { container, props } = renderTable({ rows: [entry()], hasMore: true, loadingMore: true });
    expect(observerCallback).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Цааш харуулах" }));
    expect(props.onMore).not.toHaveBeenCalled();
    expect(container.querySelector("svg")?.getAttribute("class")).toContain("htmx-request");
  });
});
