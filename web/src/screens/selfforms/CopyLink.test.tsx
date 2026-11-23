import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CopyLink } from "./CopyLink";

const LINK = "https://hr.example.test/apply/abc123";

function renderCopy() {
  return render(
    <>
      <input id="box" type="text" readOnly value={LINK} />
      <CopyLink targetId="box" />
    </>,
  );
}

function setClipboard(value: unknown) {
  Object.defineProperty(navigator, "clipboard", { configurable: true, value });
}

function setExecCommand(value: unknown) {
  Object.defineProperty(document, "execCommand", { configurable: true, value });
}

describe("CopyLink", () => {
  afterEach(() => {
    cleanup();
    setClipboard(undefined);
    delete (document as { execCommand?: unknown }).execCommand;
  });

  it("copies the box text and changes the label", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    setClipboard({ writeText });
    renderCopy();

    fireEvent.click(screen.getByRole("button", { name: "Холбоос хуулах" }));

    expect(await screen.findByRole("button", { name: "Хуулсан" })).toBeTruthy();
    expect(writeText).toHaveBeenCalledWith(LINK);
  });

  it("falls back to execCommand when the clipboard API is missing", async () => {
    setClipboard(undefined);
    const execCommand = vi.fn(() => true);
    setExecCommand(execCommand);
    renderCopy();

    fireEvent.click(screen.getByRole("button", { name: "Холбоос хуулах" }));

    expect(await screen.findByRole("button", { name: "Хуулсан" })).toBeTruthy();
    expect(execCommand).toHaveBeenCalledWith("copy");
  });

  it("falls back to execCommand when writeText refuses", async () => {
    setClipboard({ writeText: vi.fn(() => Promise.reject(new Error("denied"))) });
    const execCommand = vi.fn(() => true);
    setExecCommand(execCommand);
    renderCopy();

    fireEvent.click(screen.getByRole("button", { name: "Холбоос хуулах" }));

    expect(await screen.findByRole("button", { name: "Хуулсан" })).toBeTruthy();
    expect(execCommand).toHaveBeenCalledWith("copy");
  });

  it("does not throw and keeps the label when both the clipboard API and execCommand fail", async () => {
    setClipboard(undefined);
    setExecCommand(() => {
      throw new Error("no copy");
    });
    renderCopy();

    fireEvent.click(screen.getByRole("button", { name: "Холбоос хуулах" }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.getByRole("button", { name: "Холбоос хуулах" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Хуулсан" })).toBeNull();
  });

  it("keeps the label when execCommand reports failure and the clipboard API is missing", async () => {
    setClipboard(undefined);
    setExecCommand(vi.fn(() => false));
    renderCopy();

    fireEvent.click(screen.getByRole("button", { name: "Холбоос хуулах" }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.getByRole("button", { name: "Холбоос хуулах" })).toBeTruthy();
  });

  it("keeps the label when writeText refuses and execCommand also fails", async () => {
    setClipboard({ writeText: vi.fn(() => Promise.reject(new Error("denied"))) });
    setExecCommand(vi.fn(() => false));
    renderCopy();

    fireEvent.click(screen.getByRole("button", { name: "Холбоос хуулах" }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.getByRole("button", { name: "Холбоос хуулах" })).toBeTruthy();
  });
});
