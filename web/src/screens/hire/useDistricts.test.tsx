import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchDistricts, type HireChoiceOut } from "../../api/hire";
import { keepDistrict, useDistricts } from "./useDistricts";

vi.mock("../../api/hire", () => ({
  fetchDistricts: vi.fn(),
}));

const fetchMock = vi.mocked(fetchDistricts);

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const SBD: HireChoiceOut[] = [{ value: "3", label: "Сүхбаатар" }];
const BZD: HireChoiceOut[] = [{ value: "5", label: "Баянзүрх" }];

beforeEach(() => {
  fetchMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("useDistricts", () => {
  it("makes no request for an empty city and offers no districts", () => {
    const { result } = renderHook(() => useDistricts(""));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current).toEqual({ choices: [], loading: false, failed: false });
  });

  it("loads the districts of the city", async () => {
    fetchMock.mockResolvedValue(SBD);
    const { result } = renderHook(() => useDistricts("1"));
    expect(result.current.loading).toBe(true);
    await act(async () => {});
    expect(fetchMock).toHaveBeenCalledWith("1");
    expect(result.current).toEqual({ choices: SBD, loading: false, failed: false });
  });

  it("follows the city and ignores a stale answer", async () => {
    const slow = deferred<HireChoiceOut[]>();
    fetchMock.mockReturnValueOnce(slow.promise).mockResolvedValueOnce(BZD);
    const { result, rerender } = renderHook(({ city }) => useDistricts(city), {
      initialProps: { city: "1" },
    });
    rerender({ city: "2" });
    await act(async () => {});
    expect(result.current).toEqual({ choices: BZD, loading: false, failed: false });

    await act(async () => {
      slow.resolve(SBD);
    });
    expect(result.current).toEqual({ choices: BZD, loading: false, failed: false });
  });

  it("loading is true while a city is being fetched and false after the answer", async () => {
    const pending = deferred<HireChoiceOut[]>();
    fetchMock.mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useDistricts("1"));
    expect(result.current.loading).toBe(true);
    await act(async () => {
      pending.resolve(SBD);
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.choices).toEqual(SBD);
  });

  it("returns the same empty array identity across renders", async () => {
    const pending = deferred<HireChoiceOut[]>();
    fetchMock.mockReturnValueOnce(pending.promise);
    const { result, rerender } = renderHook(({ city }) => useDistricts(city), {
      initialProps: { city: "" },
    });
    const first = result.current.choices;
    rerender({ city: "" });
    expect(result.current.choices).toBe(first);

    rerender({ city: "9" });
    const loadingChoices = result.current.choices;
    expect(loadingChoices).toHaveLength(0);
    rerender({ city: "9" });
    expect(result.current.choices).toBe(loadingChoices);
    expect(result.current.choices).toBe(first);
    await act(async () => {
      pending.resolve([]);
    });
  });

  it("gives an empty list when the city is cleared", async () => {
    fetchMock.mockResolvedValue(SBD);
    const { result, rerender } = renderHook(({ city }) => useDistricts(city), {
      initialProps: { city: "1" },
    });
    await act(async () => {});
    rerender({ city: "" });
    expect(result.current).toEqual({ choices: [], loading: false, failed: false });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("keepDistrict", () => {
  it("returns the current district when the new city offers it", () => {
    expect(keepDistrict("5", BZD)).toBe("5");
  });

  it("returns an empty string when the new city does not offer it", () => {
    expect(keepDistrict("3", BZD)).toBe("");
    expect(keepDistrict("3", [])).toBe("");
  });
});

describe("useDistricts failure", () => {
  it("failed is true after a rejected request and false after a later successful one", async () => {
    fetchMock.mockRejectedValueOnce(new Error("down")).mockResolvedValueOnce(SBD);
    const { result, rerender } = renderHook(({ city }) => useDistricts(city), {
      initialProps: { city: "1" },
    });
    await act(async () => {});
    expect(result.current).toEqual({ choices: [], loading: false, failed: true });
    rerender({ city: "2" });
    expect(result.current.failed).toBe(false);
    await act(async () => {});
    expect(result.current).toEqual({ choices: SBD, loading: false, failed: false });
  });
});
