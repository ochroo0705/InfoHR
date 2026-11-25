import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StageRow, type ProgressItem } from "./StageRow";

const h = vi.hoisted(() => ({ confirm: vi.fn() }));
vi.mock("../../widgets/confirm", () => ({ confirm: (...args: unknown[]) => h.confirm(...args) }));

const PROGRESS: ProgressItem[] = [
  { key: "new", label: "Шинэ", state: "done" },
  { key: "screening", label: "Шалгаруулалт", state: "current" },
  { key: "interview", label: "Ярилцлага", state: "todo" },
  { key: "offer", label: "Санал", state: "todo" },
  { key: "hired", label: "Ажилд авсан", state: "todo" },
];

// Moves: the next step (interview) asks nothing; a back-move (new) and a skip (offer) ask first.
const MOVE_TO = ["new", "interview", "offer", "hired"];
const MOVE_CONFIRM = ["new", "offer", "hired"];

beforeEach(() => {
  h.confirm.mockReset();
  h.confirm.mockResolvedValue(true);
});

afterEach(() => {
  cleanup();
});

describe("StageRow", () => {
  it("draws the steps in an ordered list labelled Шат, with the current step marked", () => {
    render(<StageRow progress={PROGRESS} moveTo={MOVE_TO} moveConfirm={MOVE_CONFIRM} onMove={vi.fn()} />);

    const list = screen.getByRole("list", { name: "Шат" });
    expect(list.tagName).toBe("OL");
    expect(list.querySelectorAll("li")).toHaveLength(5);
    expect(screen.getByText("Шалгаруулалт").getAttribute("aria-current")).toBe("step");
    expect(screen.getByText("Ярилцлага").getAttribute("aria-current")).toBeNull();
  });

  it("makes a movable step a button titled with the move, and a done step shows the tick", () => {
    render(<StageRow progress={PROGRESS} moveTo={MOVE_TO} moveConfirm={MOVE_CONFIRM} onMove={vi.fn()} />);

    const button = screen.getByTitle("Ярилцлага шат руу шилжүүлэх");
    expect(button.tagName).toBe("BUTTON");
    expect(screen.getByTitle("Шинэ шат руу шилжүүлэх").textContent).toBe("✓ Шинэ");
    // The current step is not a button.
    expect(screen.queryByTitle("Шалгаруулалт шат руу шилжүүлэх")).toBeNull();
  });

  it("shows the help line only when there is a step to move to", () => {
    const { unmount } = render(
      <StageRow progress={PROGRESS} moveTo={MOVE_TO} moveConfirm={MOVE_CONFIRM} onMove={vi.fn()} />,
    );
    expect(screen.getByText(/Шат дээр дарж ажил хүсэгчийг шилжүүлнэ/)).toBeTruthy();
    unmount();

    render(<StageRow progress={PROGRESS} moveTo={[]} moveConfirm={[]} onMove={vi.fn()} />);
    expect(screen.queryByText(/Шат дээр дарж ажил хүсэгчийг шилжүүлнэ/)).toBeNull();
  });

  it("posts the stage of a move that needs no question", async () => {
    const onMove = vi.fn().mockResolvedValue(undefined);
    render(<StageRow progress={PROGRESS} moveTo={MOVE_TO} moveConfirm={MOVE_CONFIRM} onMove={onMove} />);

    fireEvent.click(screen.getByTitle("Ярилцлага шат руу шилжүүлэх"));

    await waitFor(() => expect(onMove).toHaveBeenCalledWith("interview"));
    expect(h.confirm).not.toHaveBeenCalled();
  });

  it("asks first for a move listed in moveConfirm, and posts nothing when declined", async () => {
    h.confirm.mockResolvedValue(false);
    const onMove = vi.fn().mockResolvedValue(undefined);
    render(<StageRow progress={PROGRESS} moveTo={MOVE_TO} moveConfirm={MOVE_CONFIRM} onMove={onMove} />);

    fireEvent.click(screen.getByTitle("Шинэ шат руу шилжүүлэх"));

    await waitFor(() => expect(h.confirm).toHaveBeenCalledWith("«Шинэ» шат руу шилжүүлэх үү?"));
    expect(onMove).not.toHaveBeenCalled();
  });

  it("posts a confirmed move listed in moveConfirm", async () => {
    const onMove = vi.fn().mockResolvedValue(undefined);
    render(<StageRow progress={PROGRESS} moveTo={MOVE_TO} moveConfirm={MOVE_CONFIRM} onMove={onMove} />);

    fireEvent.click(screen.getByTitle("Санал шат руу шилжүүлэх"));

    await waitFor(() => expect(onMove).toHaveBeenCalledWith("offer"));
    expect(h.confirm).toHaveBeenCalledWith("«Санал» шат руу шилжүүлэх үү?");
  });

  it("shows a refusal under the row and clears it on the next successful move", async () => {
    const onMove = vi
      .fn()
      .mockRejectedValueOnce(new Error("Ажил хүсэгчийг татгалзсан байна."))
      .mockResolvedValueOnce(undefined);
    render(<StageRow progress={PROGRESS} moveTo={MOVE_TO} moveConfirm={MOVE_CONFIRM} onMove={onMove} />);

    fireEvent.click(screen.getByTitle("Ярилцлага шат руу шилжүүлэх"));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe("Ажил хүсэгчийг татгалзсан байна."),
    );
    // The steps stay where they were.
    expect(screen.getByText("Шалгаруулалт").getAttribute("aria-current")).toBe("step");

    fireEvent.click(screen.getByTitle("Ярилцлага шат руу шилжүүлэх"));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe(""));
  });

  it("locks the step buttons while a move runs", async () => {
    let finish: () => void = () => {};
    const onMove = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    render(<StageRow progress={PROGRESS} moveTo={MOVE_TO} moveConfirm={MOVE_CONFIRM} onMove={onMove} />);

    fireEvent.click(screen.getByTitle("Ярилцлага шат руу шилжүүлэх"));

    await waitFor(() => expect((screen.getByTitle("Санал шат руу шилжүүлэх") as HTMLButtonElement).disabled).toBe(true));
    // A second click while the move runs posts nothing.
    fireEvent.click(screen.getByTitle("Санал шат руу шилжүүлэх"));
    expect(onMove).toHaveBeenCalledTimes(1);

    finish();
    await waitFor(() => expect((screen.getByTitle("Санал шат руу шилжүүлэх") as HTMLButtonElement).disabled).toBe(false));
  });
});
