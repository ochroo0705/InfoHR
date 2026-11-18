import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { confirm } from "../widgets/confirm";
import {
  anyUnsaved,
  confirmLeave,
  isUnsaved,
  LEAVE_MESSAGE,
  LEAVE_OK,
  setUnsaved,
  subscribeUnsaved,
  useUnsavedFlag,
  useUnsavedGuard,
} from "./unsaved";

vi.mock("../widgets/confirm", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../widgets/confirm")>();
  return { ...actual, confirm: vi.fn() };
});

// The registry is module state: every test clears the keys it set.
const KEYS = ["page", "section:identity", "list:family", "a", "b"];

beforeEach(() => {
  for (const key of KEYS) setUnsaved(key, false);
  vi.mocked(confirm).mockReset();
});

afterEach(() => {
  cleanup();
  for (const key of KEYS) setUnsaved(key, false);
});

describe("the unsaved registry", () => {
  it("is clean at first, and a set key makes it dirty until it is cleared", () => {
    expect(anyUnsaved()).toBe(false);
    setUnsaved("section:identity", true);
    expect(anyUnsaved()).toBe(true);
    expect(isUnsaved("section:identity")).toBe(true);
    expect(isUnsaved("page")).toBe(false);
    setUnsaved("section:identity", false);
    expect(anyUnsaved()).toBe(false);
  });

  it("two keys stay dirty independently: clearing one keeps the other", () => {
    setUnsaved("a", true);
    setUnsaved("b", true);
    setUnsaved("a", false);
    expect(anyUnsaved()).toBe(true);
    expect(isUnsaved("b")).toBe(true);
    setUnsaved("b", false);
    expect(anyUnsaved()).toBe(false);
  });

  it("subscribers hear real changes only, and an unsubscribed listener hears nothing", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeUnsaved(listener);
    setUnsaved("page", true);
    expect(listener).toHaveBeenCalledTimes(1);
    setUnsaved("page", true);
    expect(listener).toHaveBeenCalledTimes(1);
    setUnsaved("page", false);
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    setUnsaved("page", true);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("useUnsavedFlag registers while mounted and clears on unmount", () => {
    const { unmount, rerender } = renderHook(({ dirty }) => useUnsavedFlag("list:family", dirty), {
      initialProps: { dirty: true },
    });
    expect(isUnsaved("list:family")).toBe(true);
    rerender({ dirty: false });
    expect(isUnsaved("list:family")).toBe(false);
    rerender({ dirty: true });
    expect(anyUnsaved()).toBe(true);
    unmount();
    expect(anyUnsaved()).toBe(false);
  });

  it("useUnsavedFlag with dirty false never registers", () => {
    renderHook(() => useUnsavedFlag("page", false));
    expect(anyUnsaved()).toBe(false);
  });
});

describe("useUnsavedGuard (beforeunload)", () => {
  it("prevents the unload only while something is unsaved", () => {
    renderHook(() => useUnsavedGuard());

    const clean = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);

    act(() => setUnsaved("section:identity", true));
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
  });

  it("removes its listener on unmount", () => {
    const { unmount } = renderHook(() => useUnsavedGuard());
    unmount();
    setUnsaved("page", true);
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });
});

describe("confirmLeave", () => {
  it("resolves true without asking when nothing is unsaved", async () => {
    await expect(confirmLeave()).resolves.toBe(true);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("asks with the leave message and the continue button when something is unsaved", async () => {
    vi.mocked(confirm).mockResolvedValue(false);
    setUnsaved("page", true);
    await expect(confirmLeave()).resolves.toBe(false);
    expect(confirm).toHaveBeenCalledWith(LEAVE_MESSAGE, { ok: LEAVE_OK });
  });

  it("resolves true when the user accepts", async () => {
    vi.mocked(confirm).mockResolvedValue(true);
    setUnsaved("section:identity", true);
    await expect(confirmLeave()).resolves.toBe(true);
  });
});
