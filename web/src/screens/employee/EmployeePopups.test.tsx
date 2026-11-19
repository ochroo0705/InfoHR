import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EmployeePopups, useEmployeePopups, type EmployeePopupsApi } from "./EmployeePopups";

// The pop-up components the provider mounts are stubbed: the test checks which one is mounted, with which props, and
// whether each open mounts a new instance (the stub records a serial per mount). `data-id` changes exactly when React
// remounts the stub. `h.detailClose` keeps the onClose of the last rendered detail, so a test can call it late.
const h = vi.hoisted(() => ({ serial: 0, detailClose: null as null | (() => void) }));

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

// The detail's five actions and the open of another order's detail, one button each (as the real pop-up's footer).
vi.mock("./OrderDetailModal", async () => {
  const { createElement, useRef } = await import("react");
  return {
    OrderDetailModal: (props: {
      pk: number;
      orderId: number;
      open: boolean;
      onClose: () => void;
      actions: {
        openOrder: (id: number, employeePk: number) => void;
        edit: (id: number) => void;
        upload: (id: number) => void;
        cancelOrder: (id: number) => void;
        cancelEvent: (id: number) => void;
        sign: (id: number) => void;
      };
    }) => {
      const id = useRef(++h.serial);
      h.detailClose = props.onClose;
      const { actions, orderId } = props;
      return createElement(
        "div",
        { "data-testid": "detail", "data-id": id.current, "data-pk": props.pk, "data-order": props.orderId, "data-open": String(props.open) },
        createElement("button", { type: "button", onClick: props.onClose }, "stub close"),
        createElement("button", { type: "button", onClick: () => actions.edit(orderId) }, "detail-edit"),
        createElement("button", { type: "button", onClick: () => actions.upload(orderId) }, "detail-upload"),
        createElement("button", { type: "button", onClick: () => actions.cancelOrder(orderId) }, "detail-cancel-order"),
        createElement("button", { type: "button", onClick: () => actions.cancelEvent(41) }, "detail-cancel-event"),
        createElement("button", { type: "button", onClick: () => actions.sign(orderId) }, "detail-sign"),
        createElement("button", { type: "button", onClick: () => actions.openOrder(99, props.pk) }, "detail-open-other"),
      );
    },
  };
});

vi.mock("./OrderSignModal", async () => {
  const { createElement, useRef } = await import("react");
  return {
    OrderSignModal: (props: { pk: number; orderId: number; open: boolean; onClose: () => void }) => {
      const id = useRef(++h.serial);
      return createElement(
        "div",
        { "data-testid": "sign", "data-id": id.current, "data-pk": props.pk, "data-order": props.orderId, "data-open": String(props.open) },
        createElement("button", { type: "button", onClick: props.onClose }, "stub close"),
      );
    },
  };
});

// A component that asks the hook for the openers, one button each.
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
      <button type="button" onClick={() => popups.openOrderDetail(60)}>
        open-detail
      </button>
      <button type="button" onClick={() => popups.openOrderCancel(62)}>
        open-order-cancel
      </button>
      <button type="button" onClick={() => popups.openOrderSign(63)}>
        open-sign
      </button>
    </>
  );
}

function Bare() {
  useEmployeePopups();
  return null;
}

// Opens the detail of order 60 of employee 9, a pk other than the provider default (7).
function OtherEmployee() {
  const popups = useEmployeePopups();
  return (
    <button type="button" onClick={() => popups.openOrderDetail(60, 9)}>
      open-other-employee-detail
    </button>
  );
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

function targetOf(testId: string): unknown {
  return JSON.parse(screen.getByTestId(testId).getAttribute("data-target") ?? "null");
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

  it("openOrderDetail mounts the detail of that order, with the employee's pk", () => {
    renderPopups();
    fireEvent.click(screen.getByText("open-detail"));
    const detail = screen.getByTestId("detail");
    expect(detail.getAttribute("data-pk")).toBe("7");
    expect(detail.getAttribute("data-order")).toBe("60");
    expect(detail.getAttribute("data-open")).toBe("true");
  });

  it("openOrderCancel mounts the order cancel pop-up, and openOrderSign mounts the signing pop-up", () => {
    renderPopups();
    fireEvent.click(screen.getByText("open-order-cancel"));
    expect(targetOf("hr")).toEqual({ kind: "order-cancel", orderId: 62 });
    fireEvent.click(screen.getByText("stub close"));
    fireEvent.click(screen.getByText("open-sign"));
    const sign = screen.getByTestId("sign");
    expect(sign.getAttribute("data-pk")).toBe("7");
    expect(sign.getAttribute("data-order")).toBe("63");
    expect(sign.getAttribute("data-open")).toBe("true");
  });

  it("a detail action replaces the detail (edit, upload, cancel order, cancel event, sign)", () => {
    renderPopups();
    fireEvent.click(screen.getByText("open-detail"));
    const first = idOf("detail");

    fireEvent.click(screen.getByText("detail-edit"));
    expect(screen.queryByTestId("detail")).toBeNull();
    expect(targetOf("hr")).toEqual({ kind: "order-edit", orderId: 60 });
    expect(idOf("hr")).not.toBe(first);
    fireEvent.click(screen.getByText("stub close"));

    fireEvent.click(screen.getByText("open-detail"));
    fireEvent.click(screen.getByText("detail-upload"));
    expect(screen.queryByTestId("detail")).toBeNull();
    expect(targetOf("hr")).toEqual({ kind: "order-upload", orderId: 60 });
    fireEvent.click(screen.getByText("stub close"));

    fireEvent.click(screen.getByText("open-detail"));
    fireEvent.click(screen.getByText("detail-cancel-order"));
    expect(screen.queryByTestId("detail")).toBeNull();
    expect(targetOf("hr")).toEqual({ kind: "order-cancel", orderId: 60 });
    fireEvent.click(screen.getByText("stub close"));

    fireEvent.click(screen.getByText("open-detail"));
    fireEvent.click(screen.getByText("detail-cancel-event"));
    expect(screen.queryByTestId("detail")).toBeNull();
    expect(targetOf("hr")).toEqual({ kind: "event-cancel", eventId: 41 });
    fireEvent.click(screen.getByText("stub close"));

    fireEvent.click(screen.getByText("open-detail"));
    fireEvent.click(screen.getByText("detail-sign"));
    expect(screen.queryByTestId("detail")).toBeNull();
    expect(screen.getByTestId("sign").getAttribute("data-order")).toBe("60");
    fireEvent.click(screen.getByText("stub close"));

    fireEvent.click(screen.getByText("open-detail"));
    fireEvent.click(screen.getByText("detail-open-other"));
    expect(screen.getByTestId("detail").getAttribute("data-order")).toBe("99");
    expect(screen.getAllByTestId("detail")).toHaveLength(1);
  });

  it("another opener is still ignored while the detail is open", () => {
    renderPopups();
    fireEvent.click(screen.getByText("open-detail"));
    const first = idOf("detail");
    fireEvent.click(screen.getByText("open-transfer"));
    fireEvent.click(screen.getByText("open-history"));
    fireEvent.click(screen.getByText("open-sign"));
    fireEvent.click(screen.getByText("open-detail"));
    expect(screen.queryByTestId("event")).toBeNull();
    expect(screen.queryByTestId("history")).toBeNull();
    expect(screen.queryByTestId("sign")).toBeNull();
    expect(screen.getAllByTestId("detail")).toHaveLength(1);
    expect(idOf("detail")).toBe(first);
    expect(screen.getByTestId("detail").getAttribute("data-open")).toBe("true");
  });

  it("late close of the replaced detail does not close the new pop-up", () => {
    renderPopups();
    fireEvent.click(screen.getByText("open-detail"));
    const lateClose = h.detailClose;
    expect(lateClose).not.toBeNull();
    fireEvent.click(screen.getByText("detail-edit"));
    expect(targetOf("hr")).toEqual({ kind: "order-edit", orderId: 60 });
    act(() => {
      lateClose?.();
    });
    expect(screen.getByTestId("hr").getAttribute("data-open")).toBe("true");
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

  it("opens a detail for another employee than the provider default", () => {
    render(
      <EmployeePopups pk={7}>
        <OtherEmployee />
      </EmployeePopups>,
    );
    fireEvent.click(screen.getByText("open-other-employee-detail"));
    const detail = screen.getByTestId("detail");
    expect(detail.getAttribute("data-pk")).toBe("9");
    expect(detail.getAttribute("data-order")).toBe("60");
  });

  it("a replacement from that detail keeps the shown employee's pk", () => {
    render(
      <EmployeePopups pk={7}>
        <OtherEmployee />
      </EmployeePopups>,
    );
    fireEvent.click(screen.getByText("open-other-employee-detail"));
    fireEvent.click(screen.getByText("detail-edit"));
    expect(screen.getByTestId("hr").getAttribute("data-pk")).toBe("9");
    expect(targetOf("hr")).toEqual({ kind: "order-edit", orderId: 60 });
    fireEvent.click(screen.getByText("stub close"));

    fireEvent.click(screen.getByText("open-other-employee-detail"));
    fireEvent.click(screen.getByText("detail-sign"));
    expect(screen.getByTestId("sign").getAttribute("data-pk")).toBe("9");
    fireEvent.click(screen.getByText("stub close"));

    fireEvent.click(screen.getByText("open-other-employee-detail"));
    fireEvent.click(screen.getByText("detail-open-other"));
    expect(screen.getByTestId("detail").getAttribute("data-pk")).toBe("9");
    expect(screen.getByTestId("detail").getAttribute("data-order")).toBe("99");
  });

  it("openOrderDetail without any pk throws", () => {
    const held: { api: EmployeePopupsApi | null } = { api: null };
    function Grab() {
      held.api = useEmployeePopups();
      return null;
    }
    render(
      <EmployeePopups>
        <Grab />
      </EmployeePopups>,
    );
    expect(() => held.api?.openOrderDetail(60)).toThrow("EmployeePopups needs a pk.");
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
