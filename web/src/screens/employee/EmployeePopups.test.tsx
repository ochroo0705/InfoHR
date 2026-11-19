import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EmployeePopups, useEmployeePopups } from "./EmployeePopups";

// The three pop-up components the provider mounts are stubbed: the test checks which one is mounted, with which props, and
// whether each open mounts a new instance (the stub records a serial per mount). `data-id` changes exactly when React
// remounts the stub.
const h = vi.hoisted(() => ({ serial: 0 }));

vi.mock("./EventModal", async () => {
  const { createElement, useRef } = await import("react");
  return {
    EventModal: (props: { pk: number; type: string; open: boolean; onClose: () => void }) => {
      const id = useRef(++h.serial);
      return createElement(
        "div",
        { "data-testid": "event", "data-id": id.current, "data-pk": props.pk, "data-type": props.type, "data-open": String(props.open) },
        createElement("button", { type: "button", onClick: props.onClose }, "stub close"),
      );
    },
  };
});

vi.mock("./HrPopup", async () => {
  const { createElement, useRef } = await import("react");
  return {
    HrPopup: (props: { pk: number; target: unknown; open: boolean; onClose: () => void }) => {
      const id = useRef(++h.serial);
      return createElement(
        "div",
        { "data-testid": "hr", "data-id": id.current, "data-pk": props.pk, "data-target": JSON.stringify(props.target), "data-open": String(props.open) },
        createElement("button", { type: "button", onClick: props.onClose }, "stub close"),
      );
    },
  };
});

vi.mock("./OrderHistoryModal", async () => {
  const { createElement, useRef } = await import("react");
  return {
    OrderHistoryModal: (props: { pk: number; orderId: number; open: boolean; onClose: () => void }) => {
      const id = useRef(++h.serial);
      return createElement(
        "div",
        { "data-testid": "history", "data-id": id.current, "data-pk": props.pk, "data-order": props.orderId, "data-open": String(props.open) },
        createElement("button", { type: "button", onClick: props.onClose }, "stub close"),
      );
    },
  };
});

// A component that asks the hook for the five openers, one button each.
function Buttons() {
  const popups = useEmployeePopups();
  return (
    <>
      <button type="button" onClick={() => popups.openEvent("transfer")}>
        open-transfer
      </button>
      <button type="button" onClick={() => popups.openEvent("promotion")}>
        open-promotion
      </button>
      <button type="button" onClick={() => popups.openEventCancel(41)}>
        open-cancel
      </button>
      <button type="button" onClick={() => popups.openOrderEdit(51)}>
        open-edit
      </button>
      <button type="button" onClick={() => popups.openOrderUpload(52)}>
        open-upload
      </button>
      <button type="button" onClick={() => popups.openOrderHistory(53)}>
        open-history
      </button>
    </>
  );
}

function Bare() {
  useEmployeePopups();
  return null;
}

function renderPopups() {
  return render(
    <EmployeePopups pk={7}>
      <Buttons />
    </EmployeePopups>,
  );
}

function idOf(testId: string): string {
  return screen.getByTestId(testId).getAttribute("data-id") ?? "";
}

describe("EmployeePopups", () => {
  afterEach(() => {
    cleanup();
  });

  it("useEmployeePopups throws a clear error outside the provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      expect(() => render(<Bare />)).toThrow(/EmployeePopups/);
    } finally {
      spy.mockRestore();
    }
  });

  it("openEvent mounts the event pop-up for that type, with the employee's pk", () => {
    renderPopups();
    expect(screen.queryByTestId("event")).toBeNull();
    fireEvent.click(screen.getByText("open-transfer"));
    const modal = screen.getByTestId("event");
    expect(modal.getAttribute("data-type")).toBe("transfer");
    expect(modal.getAttribute("data-pk")).toBe("7");
    expect(modal.getAttribute("data-open")).toBe("true");
  });

  it("openEvent passes another type through unchanged", () => {
    renderPopups();
    fireEvent.click(screen.getByText("open-promotion"));
    expect(screen.getByTestId("event").getAttribute("data-type")).toBe("promotion");
  });

  it("the cancel, edit, upload and history openers mount their pop-up with the right target", () => {
    renderPopups();
    fireEvent.click(screen.getByText("open-cancel"));
    expect(JSON.parse(screen.getByTestId("hr").getAttribute("data-target") ?? "null")).toEqual({
      kind: "event-cancel",
      eventId: 41,
    });
    fireEvent.click(screen.getByText("stub close"));
    fireEvent.click(screen.getByText("open-edit"));
    expect(JSON.parse(screen.getByTestId("hr").getAttribute("data-target") ?? "null")).toEqual({
      kind: "order-edit",
      orderId: 51,
    });
    fireEvent.click(screen.getByText("stub close"));
    fireEvent.click(screen.getByText("open-upload"));
    expect(JSON.parse(screen.getByTestId("hr").getAttribute("data-target") ?? "null")).toEqual({
      kind: "order-upload",
      orderId: 52,
    });
    fireEvent.click(screen.getByText("stub close"));
    fireEvent.click(screen.getByText("open-history"));
    const history = screen.getByTestId("history");
    expect(history.getAttribute("data-pk")).toBe("7");
    expect(history.getAttribute("data-order")).toBe("53");
  });

  it("opening the same pop-up twice remounts it (the instance id differs)", () => {
    renderPopups();
    fireEvent.click(screen.getByText("open-transfer"));
    const first = idOf("event");
    fireEvent.click(screen.getByText("stub close"));
    fireEvent.click(screen.getByText("open-transfer"));
    expect(screen.getAllByTestId("event")).toHaveLength(1);
    expect(idOf("event")).not.toBe(first);
  });

  it("opening another pop-up after the first is closed replaces it", () => {
    renderPopups();
    fireEvent.click(screen.getByText("open-transfer"));
    fireEvent.click(screen.getByText("stub close"));
    fireEvent.click(screen.getByText("open-history"));
    expect(screen.queryByTestId("event")).toBeNull();
    expect(screen.getByTestId("history").getAttribute("data-open")).toBe("true");
  });

  it("a second opener while one is open does not replace it", () => {
    renderPopups();
    fireEvent.click(screen.getByText("open-transfer"));
    const first = idOf("event");
    fireEvent.click(screen.getByText("open-history"));
    expect(screen.queryByTestId("history")).toBeNull();
    expect(screen.getAllByTestId("event")).toHaveLength(1);
    expect(idOf("event")).toBe(first);
    expect(screen.getByTestId("event").getAttribute("data-type")).toBe("transfer");
    expect(screen.getByTestId("event").getAttribute("data-open")).toBe("true");
    // Once closed (still mounted for its exit), the next opener mounts a new instance.
    fireEvent.click(screen.getByText("stub close"));
    fireEvent.click(screen.getByText("open-history"));
    expect(screen.queryByTestId("event")).toBeNull();
    expect(screen.getByTestId("history").getAttribute("data-open")).toBe("true");
  });

  it("closing keeps the pop-up mounted with open false until the next open, which remounts it", () => {
    renderPopups();
    fireEvent.click(screen.getByText("open-transfer"));
    const first = idOf("event");
    fireEvent.click(screen.getByText("stub close"));
    expect(screen.getByTestId("event").getAttribute("data-open")).toBe("false");
    expect(idOf("event")).toBe(first);
    fireEvent.click(screen.getByText("open-transfer"));
    expect(screen.getByTestId("event").getAttribute("data-open")).toBe("true");
    expect(idOf("event")).not.toBe(first);
  });
});
