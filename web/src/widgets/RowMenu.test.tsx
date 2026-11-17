import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { RowMenu } from "./RowMenu";

// Two menus, each with one item. The closed details hides its panel natively; in jsdom the panel stays in the DOM.
function setup() {
  const { container } = render(
    <>
      <RowMenu>
        <a href="#one">Нэг</a>
      </RowMenu>
      <RowMenu>
        <a href="#two">Хоёр</a>
      </RowMenu>
    </>,
  );
  const details = container.querySelectorAll("details");
  const panels = container.querySelectorAll<HTMLElement>("[data-row-menu-panel]");
  const summaries = container.querySelectorAll("summary");
  return { details, panels, summaries };
}

afterEach(() => {
  cleanup();
});

describe("RowMenu", () => {
  it("is closed at first, with the template's summary and panel classes", () => {
    const { details, panels, summaries } = setup();
    expect(details[0].open).toBe(false);
    expect(summaries[0].textContent).toBe("Үйлдэл ▾");
    expect(summaries[0].className).toBe(
      "flex h-8 cursor-pointer list-none items-center rounded-lg border border-slate-300 bg-surface px-3 text-sm hover:bg-slate-50",
    );
    expect(panels[0].className).toBe(
      "absolute right-0 z-20 mt-1 w-48 rounded-lg border border-slate-200 bg-surface py-1 text-left shadow-lg",
    );
    expect(panels[0].hasAttribute("data-nav-panel")).toBe(true);
  });

  it("opens on a summary click and pins its panel fixed, above the frame", () => {
    const { details, panels, summaries } = setup();
    fireEvent.click(summaries[0]);
    expect(details[0].open).toBe(true);
    expect(panels[0].style.position).toBe("fixed");
    expect(panels[0].style.zIndex).toBe("40");
    expect(panels[0].hasAttribute("data-leaving")).toBe(false);
  });

  it("closes an open menu with the exit when a second menu opens", async () => {
    const { details, panels, summaries } = setup();
    fireEvent.click(summaries[0]);
    fireEvent.click(summaries[1]);
    expect(panels[0].hasAttribute("data-leaving")).toBe(true);
    expect(panels[0].hasAttribute("inert")).toBe(true);
    await waitFor(() => expect(details[0].open).toBe(false));
    expect(details[1].open).toBe(true);
  });

  it("starts the exit on a second summary click, and does not close at once", async () => {
    const { details, panels, summaries } = setup();
    fireEvent.click(summaries[0]);
    fireEvent.click(summaries[0]);
    expect(panels[0].hasAttribute("data-leaving")).toBe(true);
    expect(details[0].open).toBe(true);
    await waitFor(() => expect(details[0].open).toBe(false));
  });

  it("closes on an item click", () => {
    const { panels, summaries } = setup();
    fireEvent.click(summaries[0]);
    fireEvent.click(screen.getByText("Нэг"));
    expect(panels[0].hasAttribute("data-leaving")).toBe(true);
  });

  it("closes on an outside click", () => {
    const { panels, summaries } = setup();
    fireEvent.click(summaries[0]);
    fireEvent.click(document.body);
    expect(panels[0].hasAttribute("data-leaving")).toBe(true);
  });

  it("closes on Escape and gives the focus back to the summary", async () => {
    const { details, panels, summaries } = setup();
    fireEvent.click(summaries[0]);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(panels[0].hasAttribute("data-leaving")).toBe(true);
    expect(document.activeElement).toBe(summaries[0]);
    await waitFor(() => expect(details[0].open).toBe(false));
  });

  it("keeps the panel open on a scroll inside it, and closes it on any other scroll", () => {
    const { panels, summaries } = setup();
    fireEvent.click(summaries[0]);
    fireEvent.scroll(panels[0]);
    expect(panels[0].hasAttribute("data-leaving")).toBe(false);
    fireEvent.scroll(document.body);
    expect(panels[0].hasAttribute("data-leaving")).toBe(true);
  });

  it("closes on a window resize", () => {
    const { panels, summaries } = setup();
    fireEvent.click(summaries[0]);
    fireEvent(window, new Event("resize"));
    expect(panels[0].hasAttribute("data-leaving")).toBe(true);
  });
});
