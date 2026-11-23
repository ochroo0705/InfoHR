import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AssistantMock } from "./AssistantMock";
import { DeviceFrame } from "./DeviceFrame";
import { LeaveMock } from "./LeaveMock";
import { TodayMock } from "./TodayMock";
import { OrdersMock } from "./OrdersMock";
import { assistantQa, attentionCards, leaveBars, orderRows, ordersMockLabels } from "./sampleData";

afterEach(() => {
  cleanup();
});

describe("DeviceFrame", () => {
  it("exposes its label as the name of the image", () => {
    render(
      <DeviceFrame label="Тестийн дэлгэц">
        <p>body</p>
      </DeviceFrame>,
    );
    expect(screen.getByRole("img", { name: "Тестийн дэлгэц" }).textContent).toContain("body");
  });
});

describe("OrdersMock", () => {
  it("renders one order row per sample row", () => {
    const { container } = render(<OrdersMock />);
    const rows = container.querySelectorAll('[data-anim="order-row"]');
    expect(rows.length).toBe(orderRows.length);
    expect(orderRows.length).toBe(5);
  });

  it("shows each sample row's number, person and type", () => {
    const { container } = render(<OrdersMock />);
    const rows = Array.from(container.querySelectorAll('[data-anim="order-row"]'));
    orderRows.forEach((row, index) => {
      expect(rows[index].textContent).toContain(row.no);
      expect(rows[index].textContent).toContain(row.person);
      expect(rows[index].textContent).toContain(row.type);
    });
  });

  it("renders a print-preview panel", () => {
    const { container } = render(<OrdersMock />);
    expect(container.querySelector('[data-anim="order-preview"]')).not.toBeNull();
  });

  it("is named by its frame label", () => {
    render(<OrdersMock />);
    expect(screen.getByRole("img", { name: ordersMockLabels.frame })).toBeTruthy();
  });
});

describe("LeaveMock", () => {
  it("renders one leave bar per leave entry", () => {
    const { container } = render(<LeaveMock />);
    const bars = container.querySelectorAll('[data-anim="leave-bar"]');
    expect(bars.length).toBe(leaveBars.length);
  });

  it("places and sizes the first and last bars from startDay and days over the 21-day window", () => {
    const { container } = render(<LeaveMock />);
    const bars = container.querySelectorAll<HTMLElement>('[data-anim="leave-bar"]');
    const indexes = [0, bars.length - 1];
    for (const index of indexes) {
      const bar = leaveBars[index];
      expect(bars[index].style.left).toBe(`${(bar.startDay / 21) * 100}%`);
      expect(bars[index].style.width).toBe(`${(bar.days / 21) * 100}%`);
    }
  });
});

describe("TodayMock", () => {
  it("renders one attention card per entry, each showing its count", () => {
    const { container } = render(<TodayMock />);
    const cards = Array.from(container.querySelectorAll('[data-anim="today-card"]'));
    expect(cards.length).toBe(attentionCards.length);
    attentionCards.forEach((card, index) => {
      const count = cards[index].querySelector(".mock-today-count");
      expect(count?.textContent).toBe(String(card.count));
      expect(cards[index].textContent).toContain(card.title);
    });
  });
});

describe("AssistantMock", () => {
  it("shows the full question text in the question line", () => {
    const { container } = render(<AssistantMock />);
    const question = container.querySelector('[data-anim="assistant-question"]');
    expect(question?.textContent).toBe(assistantQa.question);
  });

  it("renders one table row per answer row", () => {
    const { container } = render(<AssistantMock />);
    expect(container.querySelector('[data-anim="assistant-table"]')).not.toBeNull();
    const rows = container.querySelectorAll('[data-anim="assistant-row"]');
    expect(rows.length).toBe(assistantQa.rows.length);
  });
});

describe("sample data", () => {
  it("uses only invented names in the form initial, dot, surname", () => {
    const people = [
      ...orderRows.map((row) => row.person),
      ...leaveBars.map((bar) => bar.person),
      ...assistantQa.rows.map((row) => row[0]),
    ];
    for (const person of people) {
      expect(person).toMatch(/^\p{Lu}\.\s/u);
    }
  });

  it("has five order rows with four-digit numbers", () => {
    expect(orderRows).toHaveLength(5);
    for (const row of orderRows) {
      expect(row.no).toMatch(/^\d{4}$/);
    }
  });

  it("has six leave bars that fit a 21-day window", () => {
    expect(leaveBars).toHaveLength(6);
    for (const bar of leaveBars) {
      expect(bar.startDay).toBeGreaterThanOrEqual(0);
      expect(bar.days).toBeGreaterThanOrEqual(1);
      expect(bar.startDay + bar.days).toBeLessThanOrEqual(21);
    }
  });

  it("has four attention cards with positive counts", () => {
    expect(attentionCards).toHaveLength(4);
    for (const card of attentionCards) {
      expect(card.title.length).toBeGreaterThan(0);
      expect(Number.isInteger(card.count) && card.count > 0).toBe(true);
    }
  });

  it("has one question and a four-row answer whose rows match the columns", () => {
    expect(assistantQa.question.length).toBeGreaterThan(0);
    expect(assistantQa.rows).toHaveLength(4);
    for (const row of assistantQa.rows) {
      expect(row).toHaveLength(assistantQa.columns.length);
    }
  });
});
