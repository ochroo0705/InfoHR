import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { copy } from "../copy";
import { Faq } from "./Faq";
import { Fit } from "./Fit";

afterEach(cleanup);

describe("Fit", () => {
  it("renders the title, every size item and the MACS paragraphs", () => {
    const { container } = render(<Fit />);

    expect(container.querySelector("section")?.id).toBe("fit");
    expect(screen.getByRole("heading", { level: 2, name: copy.fit.title })).toBeTruthy();
    for (const item of copy.fit.sizes) {
      expect(screen.getByRole("heading", { level: 3, name: item.title })).toBeTruthy();
    }
    for (const paragraph of copy.fit.macsParagraphs) {
      expect(screen.getByText(paragraph)).toBeTruthy();
    }
  });
});

describe("Faq", () => {
  it("renders one details item per question, closed by default", () => {
    const { container } = render(<Faq />);

    expect(container.querySelector("section")?.id).toBe("faq");
    const items = container.querySelectorAll("details");
    expect(items).toHaveLength(copy.faq.items.length);
    items.forEach((item, index) => {
      expect(item.open).toBe(false);
      expect(item.querySelector("summary")?.textContent).toBe(copy.faq.items[index].q);
      expect(item.textContent).toContain(copy.faq.items[index].a);
    });
  });
});
