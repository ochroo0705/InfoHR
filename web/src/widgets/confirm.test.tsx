import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ConfirmProvider, confirm } from "./confirm";

function renderProvider() {
  return render(
    <ConfirmProvider>
      <button type="button">page</button>
    </ConfirmProvider>,
  );
}

// Opens a question and returns its promise. act() flushes the state update that shows the dialog.
function ask(message: string, opts?: Parameters<typeof confirm>[1]): Promise<boolean> {
  let result: Promise<boolean> = Promise.resolve(false);
  act(() => {
    result = confirm(message, opts);
  });
  return result;
}

function dialog(): HTMLElement {
  return screen.getByRole("alertdialog");
}

describe("confirm", () => {
  // Vitest here has no globals, so Testing Library does not clean up by itself.
  afterEach(() => cleanup());

  it("focus starts on Cancel", () => {
    renderProvider();
    ask("Устгах уу?");
    expect(document.activeElement).toBe(within(dialog()).getByRole("button", { name: "Болих" }));
  });

  it("Tab from OK goes to Cancel, and Tab from Cancel goes to OK", () => {
    renderProvider();
    ask("Устгах уу?");
    const cancel = within(dialog()).getByRole("button", { name: "Болих" });
    const ok = within(dialog()).getByRole("button", { name: "Тийм" });
    ok.focus();
    fireEvent.keyDown(ok, { key: "Tab" });
    expect(document.activeElement).toBe(cancel);
    fireEvent.keyDown(cancel, { key: "Tab" });
    expect(document.activeElement).toBe(ok);
  });

  it("Escape resolves false", async () => {
    renderProvider();
    const answer = ask("Устгах уу?");
    fireEvent.keyDown(document.body, { key: "Escape" });
    await expect(answer).resolves.toBe(false);
  });

  it("an outside click resolves false", async () => {
    renderProvider();
    const answer = ask("Устгах уу?");
    const overlay = dialog();
    fireEvent.mouseDown(overlay);
    fireEvent.click(overlay);
    await expect(answer).resolves.toBe(false);
  });

  it("OK resolves true", async () => {
    renderProvider();
    const answer = ask("Хадгалах уу?", { ok: "Хадгалах" });
    fireEvent.click(within(dialog()).getByRole("button", { name: "Хадгалах" }));
    await expect(answer).resolves.toBe(true);
  });

  it("danger has no visual effect: its OK button has the same class as a normal confirm", () => {
    renderProvider();
    ask("Устгах уу?", { ok: "Устгах", danger: true });
    const withDanger = within(dialog()).getByRole("button", { name: "Устгах" }).className;
    // A second question replaces the first (answered no), so the same dialog now shows a normal confirm.
    ask("Устгах уу?", { ok: "Устгах" });
    const normal = within(dialog()).getByRole("button", { name: "Устгах" }).className;
    expect(withDanger).toBe(normal);
    expect(normal).not.toContain("hr-confirm-danger");
  });

  it("a replaced question starts focus on Cancel", () => {
    renderProvider();
    ask("Эхний асуулт");
    within(dialog()).getByRole("button", { name: "Тийм" }).focus();
    ask("Хоёр дахь асуулт");
    expect(document.activeElement).toBe(within(dialog()).getByRole("button", { name: "Болих" }));
  });

  it("clearing the bridge only clears this provider's own (a newer provider keeps working)", async () => {
    const older = renderProvider();
    renderProvider();
    older.unmount();
    const answer = ask("Хадгалах уу?");
    fireEvent.click(within(dialog()).getByRole("button", { name: "Тийм" }));
    await expect(answer).resolves.toBe(true);
  });

  it("the default OK button is not red", () => {
    renderProvider();
    ask("Хадгалах уу?");
    expect(within(dialog()).getByRole("button", { name: "Тийм" }).classList.contains("hr-confirm-danger")).toBe(false);
  });

  it("plays the exit (data-leaving) and then goes", async () => {
    renderProvider();
    const answer = ask("Устгах уу?");
    const shown = dialog();
    fireEvent.click(within(shown).getByRole("button", { name: "Болих" }));
    await answer;
    expect(shown.getAttribute("data-leaving")).toBe("");
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });
});
