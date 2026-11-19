import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchPrintStatus, useStartPrintJob } from "../../api/orderRegister";
import { PrintJobBadge, usePrintJob } from "./PrintJobBadge";

vi.mock("../../api/orderRegister", () => ({
  useStartPrintJob: vi.fn(),
  fetchPrintStatus: vi.fn(),
}));

const START = { token: "t1", status: "/api/v1/orders/print/t1/status", file: "/api/v1/orders/print/t1/file" };

// A screen that owns the job the way PrintSelected does, so the badge and the hook are tested together.
function Harness({ ids }: { ids: number[] }) {
  const { job, start, retry, close } = usePrintJob();
  return (
    <>
      <button type="button" onClick={() => start(ids)}>
        старт
      </button>
      <PrintJobBadge job={job} onRetry={retry} onClose={close} />
    </>
  );
}

describe("PrintJobBadge", () => {
  let mutateAsync: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    mutateAsync = vi.fn().mockResolvedValue(START);
    vi.mocked(useStartPrintJob).mockReturnValue({ mutateAsync } as unknown as ReturnType<typeof useStartPrintJob>);
    vi.mocked(fetchPrintStatus).mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  async function advance(ms: number) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  function badge(): HTMLElement {
    return document.getElementById("print-job") as HTMLElement;
  }

  it("is hidden until a job starts", () => {
    render(<Harness ids={[1, 2]} />);
    expect(badge()).not.toBeNull();
    expect(badge().hidden).toBe(true);
  });

  it("status ready shows Нээх with the file path", async () => {
    vi.mocked(fetchPrintStatus).mockResolvedValue({ state: "ready", count: 12, message: "" });
    render(<Harness ids={[1, 2]} />);

    fireEvent.click(screen.getByText("старт"));
    await advance(0);

    expect(mutateAsync).toHaveBeenCalledWith([1, 2]);
    expect(fetchPrintStatus).toHaveBeenCalledWith("t1");
    const link = screen.getByRole("link", { name: "Нээх" });
    expect(link.getAttribute("href")).toBe("/api/v1/orders/print/t1/file");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(badge().getAttribute("data-state")).toBe("ready");
    expect(badge().hidden).toBe(false);

    // Ready stops the polling.
    await advance(3000);
    expect(fetchPrintStatus).toHaveBeenCalledTimes(1);
  });

  it("status 404 shows failed with the default message", async () => {
    vi.mocked(fetchPrintStatus).mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
    render(<Harness ids={[1]} />);

    fireEvent.click(screen.getByText("старт"));
    await advance(0);

    expect(screen.getByText("Бэлтгэж чадсангүй.")).toBeTruthy();
    expect(badge().getAttribute("data-state")).toBe("failed");
    expect(screen.getByRole("button", { name: "Дахин оролдох" })).toBeTruthy();

    await advance(3000);
    expect(fetchPrintStatus).toHaveBeenCalledTimes(1);
  });

  it("a stale job shows the server's own message", async () => {
    vi.mocked(fetchPrintStatus).mockResolvedValue({ state: "failed", count: 0, message: "Файл устсан." });
    render(<Harness ids={[1]} />);

    fireEvent.click(screen.getByText("старт"));
    await advance(0);

    expect(screen.getByText("Файл устсан.")).toBeTruthy();
  });

  it("retry starts again", async () => {
    vi.mocked(fetchPrintStatus).mockRejectedValueOnce(Object.assign(new Error("nf"), { status: 404 }));
    vi.mocked(fetchPrintStatus).mockResolvedValue({ state: "ready", count: 12, message: "" });
    render(<Harness ids={[7, 8]} />);

    fireEvent.click(screen.getByText("старт"));
    await advance(0);
    fireEvent.click(screen.getByRole("button", { name: "Дахин оролдох" }));
    await advance(0);

    expect(mutateAsync).toHaveBeenCalledTimes(2);
    expect(mutateAsync).toHaveBeenLastCalledWith([7, 8]);
    expect(screen.getByRole("link", { name: "Нээх" })).toBeTruthy();
  });

  it("close hides the badge and stops polling", async () => {
    vi.mocked(fetchPrintStatus).mockResolvedValue({ state: "running", count: 3, message: "" });
    render(<Harness ids={[1]} />);

    fireEvent.click(screen.getByText("старт"));
    await advance(0);
    expect(fetchPrintStatus).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Хаах" }));
    expect(badge().hidden).toBe(true);

    await advance(4500);
    expect(fetchPrintStatus).toHaveBeenCalledTimes(1);
  });

  it("running polls every 1500 ms, once at once", async () => {
    vi.mocked(fetchPrintStatus).mockResolvedValue({ state: "running", count: 3, message: "" });
    render(<Harness ids={[1]} />);

    fireEvent.click(screen.getByText("старт"));
    await advance(0);
    expect(fetchPrintStatus).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Бэлтгэж байна…")).toBeTruthy();

    await advance(1500);
    expect(fetchPrintStatus).toHaveBeenCalledTimes(2);
  });

  it("unmount stops the timer", async () => {
    vi.mocked(fetchPrintStatus).mockResolvedValue({ state: "running", count: 3, message: "" });
    const { unmount } = render(<Harness ids={[1]} />);

    fireEvent.click(screen.getByText("старт"));
    await advance(0);
    unmount();

    await advance(4500);
    expect(fetchPrintStatus).toHaveBeenCalledTimes(1);
  });

  it("a start rejection shows the API's form error", async () => {
    mutateAsync.mockRejectedValueOnce(Object.assign(new Error("x"), { formErrors: ["Хэвлэх тушаал алга."] }));
    render(<Harness ids={[1]} />);

    fireEvent.click(screen.getByText("старт"));
    await advance(0);

    expect(screen.getByText("Хэвлэх тушаал алга.")).toBeTruthy();
    expect(badge().getAttribute("data-state")).toBe("failed");
    expect(fetchPrintStatus).not.toHaveBeenCalled();
  });

  it("a start rejection without a form error shows the default message", async () => {
    mutateAsync.mockRejectedValueOnce(new Error("network"));
    render(<Harness ids={[1]} />);

    fireEvent.click(screen.getByText("старт"));
    await advance(0);

    expect(screen.getByText("Бэлтгэж чадсангүй.")).toBeTruthy();
  });

  it("a status error while running ends in failed", async () => {
    vi.mocked(fetchPrintStatus)
      .mockResolvedValueOnce({ state: "running", count: 3, message: "" })
      .mockRejectedValueOnce(Object.assign(new Error("boom"), { status: 500 }));
    render(<Harness ids={[1]} />);

    fireEvent.click(screen.getByText("старт"));
    await advance(0);
    expect(badge().getAttribute("data-state")).toBe("running");

    await advance(1500);
    expect(badge().getAttribute("data-state")).toBe("failed");
    expect(screen.getByText("Бэлтгэж чадсангүй.")).toBeTruthy();
  });

  it("a late rejected poll after ready keeps the ready link", async () => {
    let rejectFirst: (reason: unknown) => void = () => undefined;
    vi.mocked(fetchPrintStatus)
      .mockImplementationOnce(() => new Promise((_, reject) => {
        rejectFirst = reject;
      }))
      .mockResolvedValueOnce({ state: "ready", count: 12, message: "" });
    render(<Harness ids={[1]} />);

    fireEvent.click(screen.getByText("старт"));
    await advance(0);
    // The interval poll answers ready while the first poll is still in flight.
    await advance(1500);
    expect(badge().getAttribute("data-state")).toBe("ready");

    await act(async () => {
      rejectFirst(new Error("late"));
    });
    await advance(0);

    expect(badge().getAttribute("data-state")).toBe("ready");
    expect(screen.getByRole("link", { name: "Нээх" }).getAttribute("href")).toBe("/api/v1/orders/print/t1/file");
  });
});
