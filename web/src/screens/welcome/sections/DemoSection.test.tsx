import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { submitDemoRequest } from "../../../api/welcome";
import { copy } from "../copy";
import { gsap } from "../motion";
import { DemoSection } from "./DemoSection";

vi.mock("../../../api/welcome", () => ({ submitDemoRequest: vi.fn() }));

const submitMock = vi.mocked(submitDemoRequest);

// Shaped like a MediaQueryList. `reduce` decides what prefers-reduced-motion reports.
function stubMatchMedia(reduce: boolean) {
  const stub = (query: string) => ({
    matches: reduce,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
  });
  vi.stubGlobal("matchMedia", vi.fn(stub));
}

function sectionOf(container: HTMLElement): HTMLElement {
  const section = container.querySelector<HTMLElement>("section");
  if (!section) throw new Error("no section rendered");
  return section;
}

function honeypotOf(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>('input[name="contact_ref"]');
  if (!input) throw new Error("no honeypot rendered");
  return input;
}

function fieldByLabel(label: string): HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement {
  return screen.getByLabelText(label) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
}

// Fills every field with valid values. Optional fields are left as they are unless given.
function fillValid(overrides: Partial<Record<"email" | "name" | "organisation", string>> = {}) {
  fireEvent.change(fieldByLabel(copy.form.labels.email), {
    target: { value: overrides.email ?? "bat@example.mn" },
  });
  fireEvent.change(fieldByLabel(copy.form.labels.name), { target: { value: overrides.name ?? "Бат" } });
  fireEvent.change(fieldByLabel(copy.form.labels.organisation), {
    target: { value: overrides.organisation ?? "Жишээ ХХК" },
  });
}

function submitButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: copy.form.submit }) as HTMLButtonElement;
}

function apiError(status: number, fieldErrors: Record<string, string[]>, formErrors: string[], code?: string) {
  return Object.assign(new Error("demo request failed"), { status, fieldErrors, formErrors, code });
}

beforeEach(() => {
  stubMatchMedia(true);
  submitMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete (window as { matchMedia?: unknown }).matchMedia;
});

describe("DemoSection", () => {
  it("renders the light demo section with the demo id", () => {
    const { container } = render(<DemoSection />);

    const section = sectionOf(container);
    expect(section.id).toBe("demo");
    expect(section.getAttribute("data-tone")).toBe("light");
  });

  it("shows the required messages for blank fields and calls nothing", () => {
    render(<DemoSection />);

    fireEvent.click(submitButton());

    expect(screen.getByText(copy.form.errors.emailRequired)).toBeTruthy();
    expect(screen.getByText(copy.form.errors.nameRequired)).toBeTruthy();
    expect(screen.getByText(copy.form.errors.organisationRequired)).toBeTruthy();
    expect(submitMock).not.toHaveBeenCalled();
  });

  it("treats a whitespace-only name as blank", () => {
    render(<DemoSection />);
    fillValid({ name: "   " });

    fireEvent.click(submitButton());

    expect(screen.getByText(copy.form.errors.nameRequired)).toBeTruthy();
    expect(submitMock).not.toHaveBeenCalled();
  });

  it("shows the email message for a malformed email and calls nothing", () => {
    render(<DemoSection />);
    fillValid({ email: "not-an-email" });

    fireEvent.click(submitButton());

    expect(screen.getByText(copy.form.errors.emailInvalid)).toBeTruthy();
    expect(submitMock).not.toHaveBeenCalled();
  });

  it("sends once with an empty contact_ref and shows the thank-you in place of the form", async () => {
    submitMock.mockResolvedValue(undefined);
    const { container } = render(<DemoSection />);
    fillValid();

    fireEvent.click(submitButton());

    const status = await screen.findByRole("status");
    expect(status.textContent).toContain(copy.form.thanksTitle);
    expect(status.textContent).toContain(copy.form.thanksText);
    expect(submitMock).toHaveBeenCalledTimes(1);
    expect(submitMock.mock.calls[0][0]).toMatchObject({ contact_ref: "", email: "bat@example.mn" });
    expect(container.querySelector("form")).toBeNull();
  });

  it("calls once when the form is submitted twice before the answer comes (bypassing the disabled button)", async () => {
    // fireEvent.submit goes straight to the form, so the disabled button cannot stop it: only the ref guard can.
    submitMock.mockReturnValue(new Promise<void>(() => {}));
    const { container } = render(<DemoSection />);
    fillValid();
    const form = container.querySelector("form") as HTMLFormElement;

    fireEvent.submit(form);
    fireEvent.submit(form);

    await waitFor(() => expect(submitButton().disabled).toBe(true));
    expect(submitButton().getAttribute("aria-busy")).toBe("true");
    expect(submitMock).toHaveBeenCalledTimes(1);
  });

  it("moves focus to the thank-you container after a successful submit", async () => {
    submitMock.mockResolvedValue(undefined);
    render(<DemoSection />);
    fillValid();

    fireEvent.click(submitButton());

    const status = await screen.findByRole("status");
    await waitFor(() => expect(document.activeElement).toBe(status));
    expect(status.getAttribute("tabindex")).toBe("-1");
  });

  it("renders the alert region before any error, and it is empty", () => {
    render(<DemoSection />);

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toBe("");
  });

  it("clears a form-level alert as soon as the user edits a field", async () => {
    submitMock.mockRejectedValue(apiError(429, {}, ["Хэт олон удаа оролдлоо."], "rate_limited"));
    render(<DemoSection />);
    fillValid();

    fireEvent.click(submitButton());
    await screen.findByText("Хэт олон удаа оролдлоо.");
    fireEvent.change(fieldByLabel(copy.form.labels.note), { target: { value: "x" } });

    expect(screen.getByRole("alert").textContent).toBe("");
  });

  it("pins the card's measured height as an inline min-height on success", async () => {
    submitMock.mockResolvedValue(undefined);
    const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetHeight");
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, get: () => 640 });
    try {
      render(<DemoSection />);
      fillValid();

      fireEvent.click(submitButton());

      const status = await screen.findByRole("status");
      const card = status.parentElement as HTMLElement;
      expect(card.classList.contains("w-demo-card")).toBe(true);
      expect(card.style.minHeight).toBe("640px");
    } finally {
      if (original) {
        Object.defineProperty(HTMLElement.prototype, "offsetHeight", original);
      }
    }
  });

  it("shows a server field error next to its field and keeps what was typed", async () => {
    submitMock.mockRejectedValue(apiError(400, { email: ["Имэйл буруу байна (сервер)."] }, []));
    render(<DemoSection />);
    fillValid();

    fireEvent.click(submitButton());

    const message = await screen.findByText("Имэйл буруу байна (сервер).");
    const email = fieldByLabel(copy.form.labels.email);
    expect(email.value).toBe("bat@example.mn");
    expect(email.getAttribute("aria-invalid")).toBe("true");
    expect(email.getAttribute("aria-describedby")?.split(" ")).toContain(message.id);
    expect(fieldByLabel(copy.form.labels.name).value).toBe("Бат");
  });

  it("shows rate-limit form errors in the alert region above the button", async () => {
    submitMock.mockRejectedValue(apiError(429, {}, ["Хэт олон удаа оролдлоо."], "rate_limited"));
    render(<DemoSection />);
    fillValid();

    fireEvent.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Хэт олон удаа оролдлоо.");
    expect(alert.textContent).toContain(copy.form.errors.submitFailed);
    expect(submitButton().disabled).toBe(false);
  });

  it("gives every visible control an associated label", () => {
    const { container } = render(<DemoSection />);

    const controls = container.querySelectorAll<HTMLElement>("input:not([name='contact_ref']), select, textarea");
    expect(controls.length).toBeGreaterThan(0);
    controls.forEach((control) => {
      expect((control as HTMLInputElement).labels?.length ?? 0, control.outerHTML).toBeGreaterThan(0);
    });
  });

  it("renders the honeypot aria-hidden, out of the tab order and empty", () => {
    const { container } = render(<DemoSection />);

    const honeypot = honeypotOf(container);
    expect(honeypot.getAttribute("aria-hidden")).toBe("true");
    expect(honeypot.tabIndex).toBe(-1);
    expect(honeypot.getAttribute("autocomplete")).toBe("off");
    expect(honeypot.value).toBe("");
  });

  it("does not match the XE4 denylist anywhere in the section text", () => {
    const { container } = render(<DemoSection />);

    expect(sectionOf(container).textContent ?? "").not.toMatch(/хуучин|\bold\b|\blegacy\b|\boutdated\b|\breplaced\b/i);
  });
});

describe("DemoSection (animated thank-you)", () => {
  it("runs the fade once, and when fromTo throws after hiding the thank-you, the catch makes it visible again", async () => {
    stubMatchMedia(false);
    submitMock.mockResolvedValue(undefined);
    const fromTo = vi.spyOn(gsap, "fromTo").mockImplementation(((target: HTMLElement) => {
      // Hide the element first, as a real tween's start state would, then fail: the catch must clean up.
      target.style.opacity = "0";
      target.style.transform = "translate(0px, 12px)";
      throw new Error("fromTo failed");
    }) as unknown as typeof gsap.fromTo);
    render(<DemoSection />);
    fillValid();

    fireEvent.click(submitButton());

    const status = await screen.findByRole("status");
    expect(fromTo).toHaveBeenCalledTimes(1);
    expect(fromTo.mock.calls[0][0]).toBe(status);
    expect(status.style.opacity).toBe("");
    expect(status.style.transform).toBe("");
  });
});
