import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import { checkRegister, type HireRegisterMatchOut } from "../../api/hire";
import { RegisterCheck } from "./RegisterCheck";

vi.mock("../../api/hire", () => ({
  checkRegister: vi.fn(),
}));

const checkMock = vi.mocked(checkRegister);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function renderCheck(value: string) {
  return render(
    <MemoryRouter>
      <RegisterCheck value={value} />
    </MemoryRouter>,
  );
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

const MATCH: HireRegisterMatchOut = { pk: 7, code: "ABC-001", full_name: "Бат Дорж" };

beforeEach(() => {
  vi.useFakeTimers();
  checkMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("RegisterCheck", () => {
  it("waits 400 ms after the value before it asks the server", async () => {
    checkMock.mockResolvedValue(null);
    renderCheck("УА12345678");
    await advance(399);
    expect(checkMock).not.toHaveBeenCalled();
    await advance(1);
    expect(checkMock).toHaveBeenCalledWith("УА12345678");
  });

  it("shows the link to the employee for a match", async () => {
    checkMock.mockResolvedValue(MATCH);
    renderCheck("УА12345678");
    await advance(400);

    expect(screen.getByText(/аль хэдийн бүртгэлтэй:/)).toBeTruthy();
    const link = screen.getByRole("link", { name: "ABC-001 Бат Дорж" });
    expect(link.getAttribute("href")).toBe("/employees/7/");
    expect(link.className).toContain("underline");
    expect(link.closest("span")?.className).toContain("text-red-600");
  });

  it("shows nothing for no match", async () => {
    checkMock.mockResolvedValue(null);
    const { container } = renderCheck("УА12345678");
    await advance(400);
    expect(screen.queryByRole("link")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("clears the match when the value is emptied, with no request", async () => {
    checkMock.mockResolvedValue(MATCH);
    const { rerender, container } = renderCheck("УА12345678");
    await advance(400);
    expect(screen.getByRole("link")).toBeTruthy();

    rerender(
      <MemoryRouter>
        <RegisterCheck value="" />
      </MemoryRouter>,
    );
    await advance(400);
    expect(screen.queryByRole("link")).toBeNull();
    expect(container.textContent).toBe("");
    expect(checkMock).toHaveBeenCalledTimes(1);
  });

  it("drops an answer that arrives after the value changed again", async () => {
    const first = deferred<HireRegisterMatchOut | null>();
    checkMock.mockReturnValueOnce(first.promise).mockResolvedValueOnce(null);
    const { rerender } = renderCheck("УА11111111");
    await advance(400);
    expect(checkMock).toHaveBeenCalledWith("УА11111111");

    rerender(
      <MemoryRouter>
        <RegisterCheck value="УА22222222" />
      </MemoryRouter>,
    );
    await advance(400);
    expect(checkMock).toHaveBeenLastCalledWith("УА22222222");

    await act(async () => {
      first.resolve(MATCH);
      await Promise.resolve();
    });
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows nothing when the request fails", async () => {
    checkMock.mockRejectedValue(new Error("network"));
    const { container } = renderCheck("УА12345678");
    await advance(400);
    expect(screen.queryByRole("link")).toBeNull();
    expect(container.textContent).toBe("");
  });
});
