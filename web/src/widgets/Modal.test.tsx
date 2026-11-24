import { useState, type ReactNode } from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConfirmProvider } from "./confirm";
import { DatePicker } from "./DatePicker";
import { Modal } from "./Modal";
import { DIRTY_CONFIRM_MESSAGE } from "./modalLogic";

function renderWithConfirm(ui: ReactNode) {
  return render(<ConfirmProvider>{ui}</ConfirmProvider>);
}

function overlayOf(): HTMLElement {
  const overlay = document.querySelector<HTMLElement>(".fixed.inset-0.z-50");
  if (!overlay) throw new Error("no pop-up overlay in the document");
  return overlay;
}

describe("Modal", () => {
  // Vitest here has no globals, so Testing Library does not clean up by itself.
  afterEach(() => cleanup());

  it("Escape closes the top one of two stacked modals", () => {
    const onCloseA = vi.fn();
    const onCloseB = vi.fn();
    renderWithConfirm(
      <>
        <Modal open title="A" onClose={onCloseA}>
          a
        </Modal>
        <Modal open title="B" onClose={onCloseB}>
          b
        </Modal>
      </>,
    );
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onCloseB).toHaveBeenCalledTimes(1);
    expect(onCloseA).not.toHaveBeenCalled();
  });

  it("an inner popup that already used Escape (preventDefault) closes nothing", () => {
    const onClose = vi.fn();
    renderWithConfirm(
      <Modal open title="T" onClose={onClose}>
        <input onKeyDown={(e) => { if (e.key === "Escape") e.preventDefault(); }} aria-label="inner" />
      </Modal>,
    );
    fireEvent.keyDown(screen.getByLabelText("inner"), { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a dirty modal asks first, and Cancel keeps it open", async () => {
    const onClose = vi.fn();
    renderWithConfirm(
      <Modal open dirty title="T" onClose={onClose}>
        x
      </Modal>,
    );
    fireEvent.keyDown(document.body, { key: "Escape" });
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain(DIRTY_CONFIRM_MESSAGE);
    fireEvent.click(within(dialog).getByRole("button", { name: "Болих" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.keyDown(document.body, { key: "Escape" });
    const again = await screen.findByRole("alertdialog");
    fireEvent.click(within(again).getByRole("button", { name: "Хаах" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("a modal with server errors counts as dirty", async () => {
    const onClose = vi.fn();
    renderWithConfirm(
      <Modal open serverErrors={{ field_errors: { last_name: ["Заавал бөглөнө"] } }} title="T" onClose={onClose}>
        x
      </Modal>,
    );
    fireEvent.click(document.querySelector<HTMLElement>("[data-modal-x]")!);
    expect(await screen.findByRole("alertdialog")).not.toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("the ✕ closes a clean modal at once", () => {
    const onClose = vi.fn();
    renderWithConfirm(
      <Modal open title="T" onClose={onClose}>
        x
      </Modal>,
    );
    fireEvent.click(document.querySelector<HTMLElement>("[data-modal-x]")!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("an outside click closes, and a click inside the panel does not", () => {
    const onClose = vi.fn();
    renderWithConfirm(
      <Modal open title="T" onClose={onClose}>
        <p>inside</p>
      </Modal>,
    );
    const inside = screen.getByText("inside");
    fireEvent.mouseDown(inside);
    fireEvent.click(inside);
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.mouseDown(overlayOf());
    fireEvent.click(overlayOf());
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("checks that the body-lock CSS rule is present in motion.css (the rule, not the lock itself)", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles/motion.css"), "utf8");  // npm test runs from web/
    expect(css).toContain("body:has(.fixed.inset-0.z-50) { overflow: hidden; }");
  });

  it("typing inside the modal marks it dirty: Escape asks first", async () => {
    const onClose = vi.fn();
    renderWithConfirm(
      <Modal open title="T" onClose={onClose}>
        <input aria-label="name" />
      </Modal>,
    );
    fireEvent.change(screen.getByLabelText("name"), { target: { value: "Бат" } });
    fireEvent.keyDown(document.body, { key: "Escape" });
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain(DIRTY_CONFIRM_MESSAGE);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a stuck modal (onClose does not close it) does not block Escape on a top modal, and its ✕ works again", () => {
    const onCloseStuck = vi.fn();
    const onCloseTop = vi.fn();
    // A function, so each render builds new elements, as a real parent does (React skips an identical element).
    const tree = () => (
      <>
        <Modal open title="Stuck" onClose={onCloseStuck}>
          s
        </Modal>
        <Modal open title="Top" onClose={onCloseTop}>
          t
        </Modal>
      </>
    );
    const { rerender } = renderWithConfirm(tree());
    const stuckX = () => document.querySelectorAll<HTMLElement>("[data-modal-x]")[0];

    fireEvent.click(stuckX());
    expect(onCloseStuck).toHaveBeenCalledTimes(1);

    // The stuck pop-up is still open, but its close mark is set. Escape must still reach the top pop-up.
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onCloseTop).toHaveBeenCalledTimes(1);

    // The parent re-renders with the pop-up still open: its ✕ works again.
    rerender(<ConfirmProvider>{tree()}</ConfirmProvider>);
    fireEvent.click(stuckX());
    expect(onCloseStuck).toHaveBeenCalledTimes(2);
  });

  it("closable false: no ✕, and Escape and an outside click do nothing", () => {
    const onClose = vi.fn();
    renderWithConfirm(
      <Modal open closable={false} title="T" onClose={onClose}>
        <p>inside</p>
      </Modal>,
    );
    expect(document.querySelector("[data-modal-x]")).toBeNull();
    fireEvent.keyDown(document.body, { key: "Escape" });
    fireEvent.mouseDown(overlayOf());
    fireEvent.click(overlayOf());
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText("inside")).toBeTruthy();
  });

  it("a non-closable pop-up on top takes Escape, and the closable one below is not closed", () => {
    const onCloseBelow = vi.fn();
    const onCloseTop = vi.fn();
    renderWithConfirm(
      <>
        <Modal open title="Below" onClose={onCloseBelow}>
          below
        </Modal>
        <Modal open closable={false} title="Top" onClose={onCloseTop}>
          top
        </Modal>
      </>,
    );
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onCloseBelow).not.toHaveBeenCalled();
    expect(onCloseTop).not.toHaveBeenCalled();
  });

  it("the title keeps the default class mb-4 text-lg font-semibold", () => {
    renderWithConfirm(
      <Modal open title="Гарчиг" onClose={vi.fn()}>
        x
      </Modal>,
    );
    const heading = screen.getByRole("heading", { name: "Гарчиг" });
    expect(heading.className).toBe("mb-4 text-lg font-semibold");
  });

  it("titleClass replaces the title's default classes", () => {
    renderWithConfirm(
      <Modal open title="Гарчиг" titleClass="mb-1 text-lg font-semibold" onClose={vi.fn()}>
        x
      </Modal>,
    );
    const heading = screen.getByRole("heading", { name: "Гарчиг" });
    expect(heading.className).toBe("mb-1 text-lg font-semibold");
    expect(heading.className).not.toContain("mb-4");
  });

  it("noAnim adds the no-anim class", () => {
    renderWithConfirm(
      <Modal open noAnim title="T" onClose={() => {}}>
        x
      </Modal>,
    );
    expect(overlayOf().classList.contains("no-anim")).toBe(true);
  });

  it("closing plays the exit (data-leaving and inert), then removes the modal", async () => {
    const { rerender } = renderWithConfirm(
      <Modal open title="T" onClose={() => {}}>
        x
      </Modal>,
    );
    rerender(
      <ConfirmProvider>
        <Modal open={false} title="T" onClose={() => {}}>
          x
        </Modal>
      </ConfirmProvider>,
    );
    expect(overlayOf().getAttribute("data-leaving")).toBe("");
    expect(overlayOf().hasAttribute("inert")).toBe(true);
    await waitFor(() => expect(document.querySelector(".fixed.inset-0.z-50")).toBeNull());
  });

  it("browsing a date picker inside the modal (a month change) does not mark it dirty", async () => {
    function Host() {
      const [open, setOpen] = useState(true);
      const [value, setValue] = useState("");
      return (
        <Modal open={open} title="T" onClose={() => setOpen(false)}>
          <label htmlFor="dob">Төрсөн өдөр</label>
          <DatePicker id="dob" name="dob" value={value} onChange={setValue} />
        </Modal>
      );
    }
    renderWithConfirm(<Host />);
    const field = screen.getByLabelText("Төрсөн өдөр");
    fireEvent.keyDown(field, { key: "ArrowDown" });
    // The month select lives in the picker's popup (in document.body), not in the field: browsing it is not typing.
    fireEvent.change(screen.getByLabelText("Сар"), { target: { value: "3" } });
    fireEvent.keyDown(field, { key: "Escape" }); // closes the picker only
    fireEvent.keyDown(field, { key: "Escape" }); // now the modal itself

    await waitFor(() => expect(document.querySelector(".fixed.inset-0.z-50")).toBeNull());
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});
