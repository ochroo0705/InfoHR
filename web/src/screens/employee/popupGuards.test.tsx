import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import "../../api/testSupport";
import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { vi } from "vitest";
import { newClient } from "../../api/testSupport";
import { SAVE_FAILED_TEXT } from "./PageForm";
import { splitRefusal, useStaleRefresh, usePopupGuards, type PopupGuards } from "./popupGuards";

// A probe renders a form with two boxes and hands the hook's guards to the test on every render.
let guards: PopupGuards | null = null;
function Probe({ open }: { open: boolean }) {
  const hook = usePopupGuards(open);
  guards = hook;
  return (
    <form ref={hook.formRef}>
      <input name="first" />
      <input name="second" aria-invalid="true" />
    </form>
  );
}

afterEach(() => {
  cleanup();
  guards = null;
});

describe("usePopupGuards", () => {
  it("a late answer is ignored once the pop-up is closed, and counts while it is open", () => {
    const view = render(<Probe open />);
    const current = guards as PopupGuards;
    expect(current.isCurrent()).toBe(true);

    view.rerender(<Probe open={false} />);
    expect((guards as PopupGuards).isCurrent()).toBe(false);
    expect(current.isMounted()).toBe(true);
  });

  it("after a refused save the focus goes to the first box with an error", () => {
    render(<Probe open />);

    act(() => {
      (guards as PopupGuards).bumpErrorTick();
    });

    const second = document.querySelector<HTMLInputElement>("input[name='second']");
    expect(document.activeElement).toBe(second);
  });

  it("nothing is current or mounted after unmount, so a late answer does nothing", () => {
    const view = render(<Probe open />);
    const current = guards as PopupGuards;

    view.unmount();

    expect(current.isMounted()).toBe(false);
    expect(current.isCurrent()).toBe(false);
  });
});

describe("splitRefusal (shared by EventModal and HrPopup)", () => {
  it("sends the errors of the named boxes under them and the rest to the form messages, messages first", () => {
    const split = splitRefusal(
      ["number", "summary"],
      { number: ["Дугаар давхцсан."], reason: ["Шалтгаан хоосон."] },
      ["Ерөнхий."],
    );
    expect(split.boxErrors).toEqual({ number: ["Дугаар давхцсан."] });
    expect(split.formMessages).toEqual(["Ерөнхий.", "Шалтгаан хоосон."]);
  });

  it("with a box named and no message, the form messages are empty", () => {
    const split = splitRefusal(["number"], { number: ["Дугаар давхцсан."] }, []);
    expect(split.boxErrors).toEqual({ number: ["Дугаар давхцсан."] });
    expect(split.formMessages).toEqual([]);
  });

  it("with no box named and no message, the general save message shows", () => {
    const split = splitRefusal(["number"], {}, []);
    expect(split.boxErrors).toEqual({});
    expect(split.formMessages).toEqual([SAVE_FAILED_TEXT]);
  });
});

describe("useStaleRefresh", () => {
  it("refreshes the named parts of the employee once the stale flag is set", () => {
    const client = newClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { rerender } = renderHook(
      ({ stale }: { stale: boolean }) => useStaleRefresh(stale, 7, client, ["work", "activity"]),
      {
        initialProps: { stale: false },
        wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
      },
    );
    expect(invalidate).not.toHaveBeenCalled();

    rerender({ stale: true });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7, "work"], exact: true });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["employee", 7, "activity"], exact: true });
  });
});
