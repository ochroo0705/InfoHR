import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { EventModal } from "./EventModal";
import { HrPopup, type HrPopupTarget } from "./HrPopup";
import { OrderDetailModal, type OrderDetailOpeners } from "./OrderDetailModal";
import { OrderHistoryModal } from "./OrderHistoryModal";
import { OrderSignModal } from "./OrderSignModal";

// The one place on the employee page that renders the pop-ups of the events and the orders: the event form (EventModal),
// the generic pop-up for the order edit, the order upload, the order cancel and the event cancel (HrPopup), the order
// history (OrderHistoryModal), the order detail (OrderDetailModal) and the order signing (OrderSignModal). A row or a
// menu item asks the hook for an opener; the provider holds which pop-up is open.
//
// Contract, for every pop-up here:
// - Each open gets a new `serial` (a counter that only grows) and the pop-up is rendered with `key={serial}`, so each
//   open REMOUNTS it: nothing typed, no `inFlight` guard and no fetched form carries over from the last open. EventModal
//   needs this: its in-flight guard stays set after a successful save.
// - Closing only sets `open` to false and keeps the pop-up mounted, so the Modal plays its exit. The next open remounts.
// - At most one pop-up is open at a time: while one is open, another opener does nothing (no focus trap in Modal, so the
//   open pop-up must not be replaced under the user's typing). A closed pop-up may be replaced by the next open.
// - The one exception is the order detail: its action buttons (edit, upload, cancel order, cancel event, sign, another
//   order's detail) REPLACE it, as the detail has no typed input. The replacement is allowed only when the call comes from
//   the open detail itself (its serial), so a late call from an older detail cannot replace a newer pop-up.
// The close is matched to its serial, so a late close of an older pop-up cannot close a newer one.
// This is the same pattern as useCorrectionPopup (CorrectionModal.tsx); it is kept as one provider, so each page mounts
// the pop-ups once. The `pk` prop is the default employee. Every pick carries its own pk, and an opener may pass another
// employee's pk as its second argument (the register page opens pop-ups for any employee). The provider decides no rule.

type PopupPick = (
  | { kind: "event"; type: string }
  | { kind: "hr"; target: HrPopupTarget }
  | { kind: "history"; orderId: number }
  | { kind: "detail"; orderId: number }
  | { kind: "sign"; orderId: number }
) & { pk: number };

type Popup = { pick: PopupPick; serial: number; open: boolean } | null;

export type EmployeePopupsApi = {
  openEvent: (type: string, employeePk?: number) => void;
  openEventCancel: (eventId: number, employeePk?: number) => void;
  openOrderEdit: (orderId: number, employeePk?: number) => void;
  openOrderUpload: (orderId: number, employeePk?: number) => void;
  openOrderHistory: (orderId: number, employeePk?: number) => void;
  openOrderDetail: (orderId: number, employeePk?: number) => void;
  openOrderCancel: (orderId: number, employeePk?: number) => void;
  openOrderSign: (orderId: number, employeePk?: number) => void;
};

const EmployeePopupsContext = createContext<EmployeePopupsApi | null>(null);

export function EmployeePopups({ pk, children }: { pk?: number; children: ReactNode }) {
  const [popup, setPopup] = useState<Popup>(null);

  // A new open takes the next serial. The serial is read from the previous pop-up, which is never cleared, so it only grows.
  // While a pop-up is open, another opener is ignored: Modal has no focus trap, so Tab can reach a menu button behind it,
  // and replacing the open pop-up would unmount it and lose what was typed. A closed pop-up (still mounted for its exit)
  // may be replaced. The one exception: `replacing` is the serial of the open order detail that asks; only that detail
  // is replaced, by the new pick, and it gets the next serial.
  const show = useCallback((pick: PopupPick, replacing?: number) => {
    setPopup((prev) => {
      if (prev?.open) {
        const replaces = replacing !== undefined && prev.serial === replacing && prev.pick.kind === "detail";
        if (!replaces) return prev;
      }
      return { pick, serial: (prev?.serial ?? 0) + 1, open: true };
    });
  }, []);
  const close = useCallback((serial: number) => {
    setPopup((prev) => (prev && prev.serial === serial ? { ...prev, open: false } : prev));
  }, []);

  // The openers the order detail gets. Each one replaces that detail (matched by its serial). The replacement is for the
  // SHOWN detail's employee (`detailPk`), so a detail of another employee opens that employee's pop-ups. A row of
  // another order passes the employee the detail shows (`employeePk`).
  const detailActions = (serial: number, detailPk: number): OrderDetailOpeners => ({
    openOrder: (orderId, employeePk) => show({ kind: "detail", orderId, pk: employeePk }, serial),
    edit: (orderId) => show({ kind: "hr", target: { kind: "order-edit", orderId }, pk: detailPk }, serial),
    upload: (orderId) => show({ kind: "hr", target: { kind: "order-upload", orderId }, pk: detailPk }, serial),
    cancelOrder: (orderId) => show({ kind: "hr", target: { kind: "order-cancel", orderId }, pk: detailPk }, serial),
    cancelEvent: (eventId) => show({ kind: "hr", target: { kind: "event-cancel", eventId }, pk: detailPk }, serial),
    sign: (orderId) => show({ kind: "sign", orderId, pk: detailPk }, serial),
  });

  const api = useMemo<EmployeePopupsApi>(() => {
    // The employee an opener acts for: its own argument, else the provider's default. With neither, the call is a bug.
    const pkOf = (employeePk?: number): number => {
      const found = employeePk ?? pk;
      if (found === undefined) throw new Error("EmployeePopups needs a pk.");
      return found;
    };
    return {
      openEvent: (type, employeePk) => show({ kind: "event", type, pk: pkOf(employeePk) }),
      openEventCancel: (eventId, employeePk) =>
        show({ kind: "hr", target: { kind: "event-cancel", eventId }, pk: pkOf(employeePk) }),
      openOrderEdit: (orderId, employeePk) =>
        show({ kind: "hr", target: { kind: "order-edit", orderId }, pk: pkOf(employeePk) }),
      openOrderUpload: (orderId, employeePk) =>
        show({ kind: "hr", target: { kind: "order-upload", orderId }, pk: pkOf(employeePk) }),
      openOrderHistory: (orderId, employeePk) => show({ kind: "history", orderId, pk: pkOf(employeePk) }),
      openOrderDetail: (orderId, employeePk) => show({ kind: "detail", orderId, pk: pkOf(employeePk) }),
      openOrderCancel: (orderId, employeePk) =>
        show({ kind: "hr", target: { kind: "order-cancel", orderId }, pk: pkOf(employeePk) }),
      openOrderSign: (orderId, employeePk) => show({ kind: "sign", orderId, pk: pkOf(employeePk) }),
    };
  }, [show, pk]);

  let modal: ReactNode = null;
  if (popup) {
    const { pick, serial, open } = popup;
    const onClose = () => close(serial);
    if (pick.kind === "event") {
      modal = <EventModal key={serial} pk={pick.pk} type={pick.type} open={open} onClose={onClose} />;
    } else if (pick.kind === "hr") {
      modal = <HrPopup key={serial} pk={pick.pk} target={pick.target} open={open} onClose={onClose} />;
    } else if (pick.kind === "detail") {
      modal = (
        <OrderDetailModal
          key={serial}
          pk={pick.pk}
          orderId={pick.orderId}
          open={open}
          onClose={onClose}
          actions={detailActions(serial, pick.pk)}
        />
      );
    } else if (pick.kind === "sign") {
      modal = <OrderSignModal key={serial} pk={pick.pk} orderId={pick.orderId} open={open} onClose={onClose} />;
    } else {
      modal = <OrderHistoryModal key={serial} pk={pick.pk} orderId={pick.orderId} open={open} onClose={onClose} />;
    }
  }

  return (
    <EmployeePopupsContext.Provider value={api}>
      {children}
      {modal}
    </EmployeePopupsContext.Provider>
  );
}

// The openers of the page's pop-ups. Outside EmployeePopups there is nothing to open, so it throws.
export function useEmployeePopups(): EmployeePopupsApi {
  const api = useContext(EmployeePopupsContext);
  if (!api) throw new Error("useEmployeePopups must be used inside <EmployeePopups>.");
  return api;
}
