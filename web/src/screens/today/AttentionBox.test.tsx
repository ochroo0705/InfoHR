import { cleanup, fireEvent, render as renderTree, screen, type RenderOptions } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AttentionBoxOut, GroupOut, ItemOut } from "../../api/today";
import { AttentionBox } from "./AttentionBox";
import { AttentionTile } from "./AttentionTile";

// The toggle mutation is replaced by a fake: `mutate` is a spy, and `setBox` lets a test play the answer the real
// hook would write into ["today"]. useAttentionMore is never reached (no group has more items).
// The tiles link to employee pages through the router (ported paths), so every render needs a Router. Any wrapper the
// test passes is kept inside the router.
function render(ui: ReactNode, options?: RenderOptions) {
  const Inner = options?.wrapper;
  return renderTree(ui, {
    ...options,
    wrapper: ({ children }: { children: ReactNode }) => (
      <MemoryRouter>{Inner ? <Inner>{children}</Inner> : children}</MemoryRouter>
    ),
  });
}

const h = vi.hoisted(() => ({
  mutate: vi.fn(),
  setBox: null as null | ((box: unknown) => void),
}));
vi.mock("../../api/today", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/today")>()),
  useAttentionToggle: () => ({ mutate: (body: unknown, opts?: { onSuccess?: () => void }) => h.mutate(body, opts) }),
  useAttentionMore: () => ({ data: undefined, isFetching: false, isError: false, refetch: vi.fn() }),
}));

const contract: ItemOut = {
  key: "contract:5",
  text: "Гэрээ дуусна",
  urgency: 0,
  employee: { id: 5, full_name: "Бат Болд", short_name: "Б. Болд", code: "E-005" },
  url: "/employees/5/",
  anchor: "#contract",
  clash: false,
  can_dismiss: true,
};

const hiddenItem: ItemOut = { ...contract, key: "contract:9", employee: { ...contract.employee!, id: 9, short_name: "Н. Нэр", full_name: "Нэр Нэрт", code: "E-009" } };

function grp(over: Partial<GroupOut>): GroupOut {
  return {
    kind: "contract",
    urgency: 0,
    label: "Гэрээ дуусах",
    count: 1,
    nearest: null,
    url: "",
    dated: false,
    open: false,
    shown: [],
    more: 0,
    keys: [],
    ...over,
  };
}

function box(over: Partial<AttentionBoxOut>): AttentionBoxOut {
  return {
    tone: "calm",
    urgent_count: 0,
    soon_count: 0,
    gap_count: 0,
    urgent: [],
    soon: [],
    gaps: [],
    hidden: [],
    ...over,
  };
}

const urgentGroup = grp({ urgency: 0, count: 1, open: true, keys: ["contract:5"], shown: [contract] });
const soonGroup = grp({
  kind: "contract_soon",
  urgency: 1,
  label: "Гэрээ дуусах удахгүй",
  count: 1,
  dated: true,
  nearest: "2026-11-20",
  keys: ["soon:1"],
  shown: [{ ...contract, key: "soon:1" }],
});

const urgentBox = box({ tone: "urgent", urgent_count: 1, urgent: [urgentGroup] });
const soonBox = box({ tone: "soon", soon_count: 1, soon: [soonGroup] });

function Harness({ initial, next }: { initial: AttentionBoxOut; next: AttentionBoxOut }) {
  const [current, setCurrent] = useState(initial);
  h.setBox = (b) => setCurrent(b as AttentionBoxOut);
  h.mutate.mockImplementation((_body: unknown, opts?: { onSuccess?: () => void }) => {
    h.setBox?.(next);
    opts?.onSuccess?.();
  });
  return (
    <>
      <AttentionBox box={current} />
      <AttentionTile box={current} />
    </>
  );
}

function boxEl(container: HTMLElement): HTMLDetailsElement {
  return container.querySelector("#attention-box") as HTMLDetailsElement;
}

beforeEach(() => {
  h.mutate.mockReset();
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("AttentionBox", () => {
  it("gives the urgent tone classes from box.tone", () => {
    const { container } = render(<AttentionBox box={urgentBox} />);
    const el = boxEl(container);
    expect(el.getAttribute("data-tone")).toBe("urgent");
    expect(el.classList.contains("border-red-200")).toBe(true);
    expect(el.classList.contains("bg-red-50/60")).toBe(true);
  });

  it("shows «Шинэ зүйл алга.» and «Нуусан (1)» when nothing is shown but one item is hidden", () => {
    const { container } = render(<AttentionBox box={box({ hidden: [hiddenItem] })} />);
    expect(screen.getByText("Шинэ зүйл алга.")).toBeTruthy();
    expect(screen.getByText("Нуусан (1)")).toBeTruthy();
    expect(container.querySelector("#attention")).not.toBeNull();
  });

  it("renders nothing when there are no shown and no hidden items", () => {
    const { container } = render(<AttentionBox box={box({})} />);
    expect(container.querySelector("#attention")).toBeNull();
    expect(container.querySelector("#attention-box")).toBeNull();
  });

  it("is open when the saved choice is '1' and nothing is urgent", () => {
    localStorage.setItem("hr.attentionOpen", "1");
    const { container } = render(<AttentionBox box={soonBox} />);
    expect(boxEl(container).open).toBe(true);
    expect(boxEl(container).hasAttribute("data-overdue")).toBe(false);
  });

  it("is closed when nothing is urgent and no choice is saved", () => {
    const { container } = render(<AttentionBox box={soonBox} />);
    expect(boxEl(container).open).toBe(false);
  });

  it("opens and sets data-overdue when forceOpen is true", () => {
    const { container } = render(<AttentionBox box={soonBox} forceOpen />);
    expect(boxEl(container).open).toBe(true);
    expect(boxEl(container).hasAttribute("data-overdue")).toBe(true);
  });

  it("opens by itself when an urgent group exists", () => {
    const { container } = render(<AttentionBox box={urgentBox} />);
    expect(boxEl(container).open).toBe(true);
    expect(boxEl(container).hasAttribute("data-overdue")).toBe(true);
  });

  it("still renders, closed, when localStorage.getItem throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    const { container } = render(<AttentionBox box={soonBox} />);
    expect(boxEl(container).open).toBe(false);
    expect(screen.getByText("Гэрээ дуусах удахгүй · 1")).toBeTruthy();
  });

  it("writes '0' when the user closes the box and '1' when they open it", () => {
    localStorage.setItem("hr.attentionOpen", "1");
    const { container } = render(<AttentionBox box={soonBox} />);
    const el = boxEl(container);
    expect(el.open).toBe(true);

    el.open = false;
    fireEvent(el, new Event("toggle"));
    expect(localStorage.getItem("hr.attentionOpen")).toBe("0");

    el.open = true;
    fireEvent(el, new Event("toggle"));
    expect(localStorage.getItem("hr.attentionOpen")).toBe("1");
  });

  it("does not overwrite the saved choice when it opens by itself for an urgent item", () => {
    localStorage.setItem("hr.attentionOpen", "0");
    render(<AttentionBox box={urgentBox} />);
    expect(localStorage.getItem("hr.attentionOpen")).toBe("0");
  });
});

describe("AttentionBox after a toggle", () => {
  it("folds a group the user closed back to its default open state, and keeps the box open", () => {
    const groupA = grp({ urgency: 0, count: 1, open: true, keys: ["contract:5"], shown: [contract] });
    const otherItem: ItemOut = { ...contract, key: "contract:7", text: "Бүрдүүлэлт", employee: { ...contract.employee!, id: 7, short_name: "Б. Сараа", full_name: "Бат Сараа", code: "E-007" } };
    const groupB = grp({ kind: "docs", label: "Бүрдүүлэлт дутуу", urgency: 0, count: 1, open: true, keys: ["contract:7"], shown: [otherItem] });
    const first = box({ tone: "urgent", urgent_count: 2, urgent: [groupA, groupB] });
    const next = box({ tone: "urgent", urgent_count: 1, urgent: [groupA] });

    const { container } = render(<Harness initial={first} next={next} />);
    const groupAEl = () => container.querySelector("details[data-attention-group][data-kind='contract']") as HTMLDetailsElement;
    const boxBefore = boxEl(container);

    // The user closes group A.
    groupAEl().open = false;
    fireEvent(groupAEl(), new Event("toggle"));
    expect(groupAEl().open).toBe(false);

    // The user dismisses the item in group B; the answer re-renders the box.
    fireEvent.click(screen.getByRole("button", { name: "Мэдлээ: Бат Сараа" }));

    expect(boxEl(container)).toBe(boxBefore);
    expect(boxEl(container).open).toBe(true);
    expect(groupAEl().open).toBe(true);
  });
});

describe("AttentionBox mounts", () => {
  it("opens an urgent box that mounts after an empty render, when forceOpen is set", () => {
    const { container, rerender } = render(<AttentionBox box={box({})} forceOpen />);
    expect(container.querySelector("#attention-box")).toBeNull();
    rerender(<AttentionBox box={urgentBox} forceOpen />);
    expect(boxEl(container).open).toBe(true);
    expect(boxEl(container).hasAttribute("data-overdue")).toBe(true);
  });

  it("opens a box that mounts after an empty render with a saved open choice", () => {
    localStorage.setItem("hr.attentionOpen", "1");
    const { container, rerender } = render(<AttentionBox box={box({})} />);
    rerender(<AttentionBox box={soonBox} />);
    expect(boxEl(container).open).toBe(true);
  });
});

describe("AttentionTile", () => {
  it("shows the urgent count, the muted line and an anchor to #attention", () => {
    const { container } = render(<AttentionTile box={box({ urgent_count: 2, soon_count: 1, gap_count: 3 })} />);
    const link = container.querySelector("a#attention-tile") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("#attention");
    expect(container.querySelector('[data-tile="attention"]')?.textContent).toBe("2");
    expect(link.textContent).toContain("+ 1 удахгүй · 3 дутуу");
  });

  it("after a toggle answer, the tile number equals the new urgent_count", () => {
    const next = box({ tone: "calm", urgent_count: 0, hidden: [contract] });
    const { container } = render(<Harness initial={urgentBox} next={next} />);
    expect(container.querySelector('[data-tile="attention"]')?.textContent).toBe("1");

    fireEvent.click(screen.getByRole("button", { name: "Мэдлээ: Бат Болд" }));

    expect(h.mutate).toHaveBeenCalledWith({ keys: ["contract:5"], action: "dismiss" }, expect.anything());
    expect(container.querySelector('[data-tile="attention"]')?.textContent).toBe("0");
  });
});
