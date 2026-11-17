import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import { AppLink, openLegacyPopup } from "./AppLink";
import { isPorted } from "./ported";

describe("isPorted", () => {
  it("ignores the query string and hash", () => {
    expect(isPorted("/me/?x=1")).toBe(true);
    expect(isPorted("/me/#top")).toBe(true);
  });

  it("is false for a Django-only page", () => {
    expect(isPorted("/employees/5/")).toBe(false);
  });
});

describe("AppLink and openLegacyPopup", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.stubEnv("VITE_LEGACY_ORIGIN", "http://dj");
    Object.defineProperty(window, "location", {
      value: { href: "" },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
    Object.defineProperty(window, "location", {
      value: originalLocation,
      writable: true,
      configurable: true,
    });
  });

  it("renders a full-page link into the Django UI for a path that is not ported", () => {
    render(
      <MemoryRouter>
        <AppLink to="/employees/5/">Profile</AppLink>
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Profile" }).getAttribute("href")).toBe(
      "http://dj/employees/5/",
    );
  });

  it("renders a router link for a ported path", () => {
    render(
      <MemoryRouter>
        <AppLink to="/me/">Me</AppLink>
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Me" }).getAttribute("href")).toBe("/me/");
  });

  it("sets the Django popup URL with the open hash", () => {
    openLegacyPopup("palette", "/me/");
    expect(window.location.href).toBe("http://dj/me/#open=palette");
  });

  it("renders a plain href for a fragment without the origin prefix", () => {
    render(
      <MemoryRouter>
        <AppLink to="#attention">Диаграм</AppLink>
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Диаграм" }).getAttribute("href")).toBe("#attention");
  });

  it("renders a plain href for an absolute URL without the origin prefix", () => {
    render(
      <MemoryRouter>
        <AppLink to="https://x/y">Гадаад</AppLink>
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Гадаад" }).getAttribute("href")).toBe("https://x/y");
  });

  it("keeps the query string on a ported path", () => {
    render(
      <MemoryRouter>
        <AppLink to="/me/?x=1">Me</AppLink>
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Me" }).getAttribute("href")).toBe("/me/?x=1");
  });

  it("passes data-testid, title and onClick through a ported link", () => {
    const onClick = vi.fn();
    render(
      <MemoryRouter>
        <AppLink to="/me/" title="Миний хуудас" data-testid="nav-me" onClick={onClick}>
          Me
        </AppLink>
      </MemoryRouter>,
    );
    const link = screen.getByTestId("nav-me");
    expect(link.getAttribute("title")).toBe("Миний хуудас");
    fireEvent.click(link);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("leaves a ported link with a target to the browser", () => {
    const start = vi.fn();
    (document as unknown as { startViewTransition?: unknown }).startViewTransition = start;
    render(
      <MemoryRouter>
        <AppLink to="/me/" target="_blank">
          Me
        </AppLink>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("link", { name: "Me" }));
    expect(start).not.toHaveBeenCalled();
    delete (document as unknown as { startViewTransition?: unknown }).startViewTransition;
  });
});
