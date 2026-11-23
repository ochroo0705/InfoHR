import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDebouncedField } from "./useDebouncedField";

describe("useDebouncedField", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("commits once, 300 ms after the last keystroke", () => {
    const onCommit = vi.fn();
    const { result } = renderHook(() => useDebouncedField("", onCommit));

    act(() => result.current[1]("a"));
    act(() => vi.advanceTimersByTime(200));
    act(() => result.current[1]("ab"));
    act(() => vi.advanceTimersByTime(299));
    expect(onCommit).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1));
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith("ab");
  });

  it("shows what the user typed before the quiet time ends", () => {
    const { result } = renderHook(() => useDebouncedField("", vi.fn()));
    act(() => result.current[1]("typed"));
    expect(result.current[0]).toBe("typed");
  });

  it("resyncs when the address value changes from outside", () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedField(value, vi.fn()), {
      initialProps: { value: "one" },
    });
    expect(result.current[0]).toBe("one");

    rerender({ value: "two" });
    expect(result.current[0]).toBe("two");
  });

  it("a change from outside cancels the pending send and shows the new value", () => {
    const onCommit = vi.fn();
    const { result, rerender } = renderHook(({ value }) => useDebouncedField(value, onCommit), {
      initialProps: { value: "" },
    });
    act(() => result.current[1]("ab"));
    rerender({ value: "zz" });
    expect(result.current[0]).toBe("zz");

    act(() => vi.advanceTimersByTime(300));
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("the render of its own send leaves newer typing alone", () => {
    const onCommit = vi.fn();
    const { result, rerender } = renderHook(({ value }) => useDebouncedField(value, onCommit), {
      initialProps: { value: "" },
    });
    act(() => result.current[1]("a"));
    act(() => vi.advanceTimersByTime(300));
    expect(onCommit).toHaveBeenLastCalledWith("a");

    act(() => result.current[1]("ab"));
    rerender({ value: "a" });
    expect(result.current[0]).toBe("ab");

    act(() => vi.advanceTimersByTime(300));
    expect(onCommit).toHaveBeenLastCalledWith("ab");
    expect(onCommit).toHaveBeenCalledTimes(2);
  });

  it("flush sends the waiting text at once and nothing again later", () => {
    const onCommit = vi.fn();
    const { result } = renderHook(() => useDebouncedField("", onCommit));
    act(() => result.current[1]("ab"));
    act(() => result.current[2]());
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith("ab");

    act(() => vi.advanceTimersByTime(300));
    expect(onCommit).toHaveBeenCalledTimes(1);
  });

  it("flush with nothing waiting sends nothing", () => {
    const onCommit = vi.fn();
    const { result } = renderHook(() => useDebouncedField("x", onCommit));
    act(() => result.current[2]());
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("sends nothing after unmount", () => {
    const onCommit = vi.fn();
    const { result, unmount } = renderHook(() => useDebouncedField("", onCommit));
    act(() => result.current[1]("x"));
    unmount();
    act(() => vi.advanceTimersByTime(300));
    expect(onCommit).not.toHaveBeenCalled();
  });
});
