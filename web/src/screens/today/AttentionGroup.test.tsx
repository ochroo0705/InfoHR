import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GroupOut, ItemOut } from "../../api/today";
import { AttentionGaps } from "./AttentionGaps";
import { AttentionGroup } from "./AttentionGroup";

// useAttentionMore is replaced by a fake (no network): null params give nothing, otherwise a fixed page of people.
const h = vi.hoisted(() => ({ useAttentionMore: vi.fn() }));
vi.mock("../../api/today", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/today")>()),
  useAttentionMore: (params: unknown) => h.useAttentionMore(params),
}));

const person = (id: number, short: string, full: string): ItemOut => ({
  key: `gap:${id}`,
  text: "Банкны мэдээлэл дутуу",
  urgency: 2,
  employee: { id, full_name: full, short_name: short, code: `E-00${id}` },
  url: `/employees/${id}/`,
  anchor: "#bank",
  clash: false,
  can_dismiss: true,
});

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

function group(overrides: Partial<GroupOut>): GroupOut {
  return {
    kind: "contract",
    urgency: 0,
    label: "Гэрээ дуусах",
    count: 2,
    nearest: null,
    url: "",
    dated: false,
    open: false,
    shown: [],
    more: 0,
    keys: [],
    ...overrides,
  };
}

beforeEach(() => {
  h.useAttentionMore.mockReset();
  h.useAttentionMore.mockImplementation((params: Record<string, string> | null) => ({
    data:
      params === null
        ? undefined
        : { dated: false, items: [person(7, "Д. Сараа", "Дорж Сараа")], more: 0, next_offset: 0 },
    isError: false,
    refetch: vi.fn(),
  }));
});

afterEach(() => {
  cleanup();
});

describe("AttentionGroup", () => {
  it("renders open for urgency 0 and closed for urgency 1 (open flag from the answer)", () => {
    const onToggle = vi.fn();
    const { container, unmount } = render(
      <AttentionGroup group={group({ urgency: 0, open: true, shown: [contract] })} onToggle={onToggle} />,
    );
    expect(container.querySelector("details[data-attention-group]")?.hasAttribute("open")).toBe(true);
    unmount();

    const second = render(
      <AttentionGroup group={group({ urgency: 1, open: false, shown: [contract] })} onToggle={onToggle} />,
    );
    expect(second.container.querySelector("details[data-attention-group]")?.hasAttribute("open")).toBe(false);
  });

  it("shows no date span for an undated group and the nearest date for a dated one", () => {
    const onToggle = vi.fn();
    const { container, unmount } = render(
      <AttentionGroup group={group({ dated: false, nearest: null, shown: [contract] })} onToggle={onToggle} />,
    );
    expect(container.querySelector("span.whitespace-nowrap")).toBeNull();
    unmount();

    render(
      <AttentionGroup
        group={group({ dated: true, nearest: "2026-11-20", shown: [contract] })}
        onToggle={onToggle}
      />,
    );
    expect(screen.getByText("2026-11-20")).toBeTruthy();
  });

  it("sends every group key with dismiss_all from «Бүгдийг мэдлээ»", () => {
    const onToggle = vi.fn();
    render(
      <AttentionGroup
        group={group({ count: 2, keys: ["gap:1", "gap:2"], shown: [contract] })}
        onToggle={onToggle}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Бүгдийг мэдлээ" }));
    expect(onToggle).toHaveBeenCalledWith(["gap:1", "gap:2"], "dismiss_all");
  });

  it("hides «Бүгдийг мэдлээ» when the group has one item", () => {
    render(<AttentionGroup group={group({ count: 1, keys: ["contract:5"], shown: [contract] })} onToggle={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Бүгдийг мэдлээ" })).toBeNull();
  });

  it("shows «Бүгдийг нээх →» as a link only when the group has a url", () => {
    const { unmount } = render(
      <AttentionGroup group={group({ url: "/employees/?gap=1", shown: [contract] })} onToggle={vi.fn()} />,
    );
    expect(screen.getByRole("link", { name: /Бүгдийг нээх/ }).getAttribute("href")).toBe("/employees/?gap=1");
    unmount();

    render(<AttentionGroup group={group({ url: "", shown: [contract] })} onToggle={vi.fn()} />);
    expect(screen.queryByRole("link", { name: /Бүгдийг нээх/ })).toBeNull();
  });
});

describe("AttentionGaps", () => {
  it("renders nothing when there are no gap groups", () => {
    const { container } = render(<AttentionGaps groups={[]} total={0} onToggle={vi.fn()} />);
    expect(container.querySelector("[data-attention-gaps]")).toBeNull();
  });

  it("fetches the people of a gap row only once, on its first open", () => {
    const gap = group({
      kind: "bank",
      urgency: 2,
      label: "Банкны мэдээлэл дутуу",
      count: 1,
      shown: [person(7, "Д. Сараа", "Дорж Сараа")],
    });
    const { container } = render(<AttentionGaps groups={[gap]} total={1} onToggle={vi.fn()} />);
    const details = container.querySelector("[data-attention-gap] details") as HTMLDetailsElement;
    expect(details).not.toBeNull();
    expect(h.useAttentionMore).toHaveBeenCalledWith(null);

    details.open = true;
    fireEvent(details, new Event("toggle"));
    details.open = false;
    fireEvent(details, new Event("toggle"));
    details.open = true;
    fireEvent(details, new Event("toggle"));

    const requested = h.useAttentionMore.mock.calls.map((c) => c[0]).filter((p) => p !== null);
    expect(requested.length).toBeGreaterThan(0);
    expect(new Set(requested.map((p) => JSON.stringify(p))).size).toBe(1);
    expect(requested[0]).toEqual({ kind: "bank", urgency: "2", all: "1", offset: "0" });
    // After open → close → reopen, GapPeople is still enabled on its last render (no reset, no second request).
    const lastCall = h.useAttentionMore.mock.calls[h.useAttentionMore.mock.calls.length - 1];
    expect(lastCall[0]).toEqual({ kind: "bank", urgency: "2", all: "1", offset: "0" });
    expect(container.querySelector("[data-gap-people]")?.textContent).toContain("Д. Сараа");
  });

  it("renders a gap row without an employee as inline chips with no details", () => {
    const listItem: ItemOut = { ...person(9, "Н. Нэр", "Нэр Нэрт"), employee: null, url: "/employees/?gap=2" };
    const gap = group({ kind: "list", urgency: 2, label: "Жагсаалт", count: 1, shown: [listItem] });
    const { container } = render(<AttentionGaps groups={[gap]} total={1} onToggle={vi.fn()} />);
    expect(container.querySelector("[data-attention-gap]")).not.toBeNull();
    expect(container.querySelector("[data-attention-gap] details")).toBeNull();
    expect(container.querySelector("[data-attention-gap] [data-chip]")).not.toBeNull();
    expect(screen.getByText("Жагсаалт · 1")).toBeTruthy();
  });
});
