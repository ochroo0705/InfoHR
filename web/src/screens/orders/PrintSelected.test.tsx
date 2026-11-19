import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useStartPrintJob } from "../../api/orderRegister";
import { PrintSelected } from "./PrintSelected";

vi.mock("../../api/orderRegister", () => ({
  useStartPrintJob: vi.fn(),
  fetchPrintStatus: vi.fn(),
}));

function ids(n: number): number[] {
  return Array.from({ length: n }, (_, i) => i + 1);
}

describe("PrintSelected", () => {
  let mutateAsync: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    mutateAsync = vi.fn().mockReturnValue(new Promise(() => undefined));
    vi.mocked(useStartPrintJob).mockReturnValue({ mutateAsync } as unknown as ReturnType<typeof useStartPrintJob>);
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  function button(): HTMLButtonElement {
    return document.getElementById("order-print-selected") as HTMLButtonElement;
  }

  it("the button counts picks and is disabled at zero", () => {
    const { rerender } = render(<PrintSelected picked={[]} backgroundFrom={11} csrfToken="tok" />);
    expect(button().textContent).toBe("Сонгосныг хэвлэх");
    expect(button().disabled).toBe(true);
    expect(button().className).toContain("enabled:hover:bg-slate-50");

    rerender(<PrintSelected picked={[4, 9, 12]} backgroundFrom={11} csrfToken="tok" />);
    expect(button().textContent).toBe("Сонгосныг хэвлэх (3)");
    expect(button().disabled).toBe(false);
  });

  it("10 picked posts the form with ids and the token to a new tab", () => {
    render(<PrintSelected picked={ids(10)} backgroundFrom={11} csrfToken="tok" />);

    const form = document.getElementById("order-print-form") as HTMLFormElement;
    expect(form.getAttribute("method")).toBe("post");
    expect(form.getAttribute("action")).toBe("/api/v1/orders/print/selected");
    expect(form.getAttribute("target")).toBe("_blank");
    // The data the browser would post: the csrf field and one ids value per order.
    const data = new FormData(form);
    expect(data.get("csrfmiddlewaretoken")).toBe("tok");
    expect(data.getAll("ids")).toEqual(ids(10).map(String));

    // Not prevented: the browser posts the form itself, and no job starts. The badge stays hidden.
    const notCancelled = fireEvent.submit(form);
    expect(notCancelled).toBe(true);
    expect(mutateAsync).not.toHaveBeenCalled();
    expect(document.getElementById("print-job")?.hidden).toBe(true);
  });

  it("11 picked starts one job and a second click while running starts none", () => {
    render(<PrintSelected picked={ids(11)} backgroundFrom={11} csrfToken="tok" />);
    const form = document.getElementById("order-print-form") as HTMLFormElement;

    const first = fireEvent.submit(form);
    const second = fireEvent.submit(form);

    expect(first).toBe(false);
    expect(second).toBe(false);
    expect(mutateAsync).toHaveBeenCalledTimes(1);
    expect(mutateAsync).toHaveBeenCalledWith(ids(11));
    expect(document.getElementById("print-job")?.hidden).toBe(false);
    expect(document.getElementById("print-job")?.getAttribute("data-state")).toBe("running");
  });
});
