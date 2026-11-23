import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BackToTop } from "./BackToTop";
import { copy } from "./copy";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  Object.defineProperty(window, "scrollY", { value: 0, configurable: true });
});

function scrollTo(y: number) {
  Object.defineProperty(window, "scrollY", { value: y, configurable: true });
  fireEvent.scroll(window);
}

describe("BackToTop", () => {
  it("is hidden at the top of the page and shows after scrolling down", () => {
    render(<BackToTop />);
    expect(screen.queryByRole("button", { name: copy.backToTop })).toBeNull();

    scrollTo(1000);
    expect(screen.getByRole("button", { name: copy.backToTop })).toBeTruthy();

    scrollTo(0);
    expect(screen.queryByRole("button", { name: copy.backToTop })).toBeNull();
  });

  it("scrolls to the top when clicked", () => {
    const spy = vi.fn();
    window.scrollTo = spy as unknown as typeof window.scrollTo;
    render(<BackToTop />);
    scrollTo(1000);

    fireEvent.click(screen.getByRole("button", { name: copy.backToTop }));

    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy.mock.calls[0][0]).toMatchObject({ top: 0 });
  });
});
