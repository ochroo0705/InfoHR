import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useBarTip } from "./useBarTip";

// A bar wired to the hook the way TimelineLayout wires it. The title and tip are passed in as data.
function Harness({ title, tip }: { title: string; tip: string }) {
  const { bind, tip: box } = useBarTip();
  return (
    <div>
      <div data-bar role="img" tabIndex={0} aria-label={title} {...bind({ title, tip })} />
      {box}
    </div>
  );
}

afterEach(() => {
  cleanup();
});

describe("useBarTip", () => {
  it("a bar tip shows title, dates and days and leaves on blur and Escape", () => {
    render(<Harness title="Ажил" tip="2026-03-01 – 2026-03-10 · 10 өдөр" />);
    const bar = screen.getByRole("img", { name: "Ажил" });
    expect(screen.queryByRole("tooltip")).toBeNull();

    // Keyboard focus shows the tip with the title and the dates with their days.
    fireEvent.focus(bar);
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip.textContent).toContain("Ажил");
    expect(tooltip.textContent).toContain("2026-03-01 – 2026-03-10 · 10 өдөр");

    // Blur hides it.
    fireEvent.blur(bar);
    expect(screen.queryByRole("tooltip")).toBeNull();

    // Pointer hover shows it again; Escape anywhere hides it.
    fireEvent.mouseEnter(bar);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    fireEvent.keyDown(bar, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();

    // Pointer out hides it.
    fireEvent.mouseEnter(bar);
    fireEvent.mouseLeave(bar);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("HTML in a title is text", () => {
    const html = "<img src=x onerror=alert(1)><b>Ажил</b>";
    const { container } = render(<Harness title={html} tip={html} />);
    fireEvent.focus(screen.getByRole("img", { name: html }));
    const tooltip = screen.getByRole("tooltip");
    // The markup is shown as written, and no element is created from it.
    expect(tooltip.textContent).toContain("<b>Ажил</b>");
    expect(tooltip.querySelector("img")).toBeNull();
    expect(tooltip.querySelector("b")).toBeNull();
    expect(container.querySelector("img[src='x']")).toBeNull();
  });
});
