// The pop-ups the assistant panel opens (palette.js data-palette-modal rows): the order detail, the contract event, the
// position-slot add form, the leave add form and the staff leave request form. They live at shell level, inside
// PalettePopups, so a pop-up opened from the panel never depends on the page underneath and never navigates. The employee
// pop-ups are EmployeePopups (no `pk` here: every open passes its own employee, as the register page does). The slot
// form, the leave add form and the leave request form are mounted only while open; their save refetches through the
// helpers.
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { PaletteOpenOut } from "../../api/palette";
import { EmployeePopups, useEmployeePopups } from "../../screens/employee/EmployeePopups";
import { LeaveFormModal } from "../../screens/leave/LeaveFormModal";
import { LeaveRequestModal } from "../../screens/leaveRequests/LeaveRequestModal";
import { SlotFormModal } from "../../screens/slots/SlotFormModal";

export type PalettePopupsApi = {
  // Opens the pop-up a palette row names. A target missing the value its pop-up needs (or with the wrong type) opens nothing.
  open(target: PaletteOpenOut): void;
};

export const PalettePopupsContext = createContext<PalettePopupsApi | null>(null);

// The pop-up openers of the panel. Outside PalettePopups there is nothing to open, so it throws.
export function usePalettePopups(): PalettePopupsApi {
  const api = useContext(PalettePopupsContext);
  if (api === null) {
    throw new Error("usePalettePopups must be used inside PalettePopups (AppShell mounts it).");
  }
  return api;
}

// A target field the pop-up needs. An absent key (undefined) or a wrong type counts as missing, so a malformed target
// opens nothing: no throw from EmployeePopups (pkOf) and no slot form with a year of "undefined".
const isNumber = (value: unknown): value is number => typeof value === "number";
const isText = (value: unknown): value is string => typeof value === "string" && value !== "";

export function PalettePopups({ children }: { children: ReactNode }) {
  return (
    <EmployeePopups>
      <PopupHost>{children}</PopupHost>
    </EmployeePopups>
  );
}

// Inside EmployeePopups, so the employee openers are available here.
function PopupHost({ children }: { children: ReactNode }) {
  const employeePopups = useEmployeePopups();
  // The year of the open slot form. Null: the form is closed and not mounted.
  const [slotYear, setSlotYear] = useState<number | null>(null);
  // The employee of the open leave add form (null: no one preselected). Null state: the form is closed and not mounted.
  const [leaveAdd, setLeaveAdd] = useState<{ employee: number | null } | null>(null);
  // Whether the staff leave request form is open. It is mounted only while open.
  const [leaveRequestOpen, setLeaveRequestOpen] = useState(false);

  const api = useMemo<PalettePopupsApi>(
    () => ({
      open(target) {
        if (target.popup === "order_detail") {
          if (isNumber(target.order) && isNumber(target.employee)) {
            employeePopups.openOrderDetail(target.order, target.employee);
          }
          return;
        }
        if (target.popup === "event") {
          if (isText(target.event_type) && isNumber(target.employee)) {
            employeePopups.openEvent(target.event_type, target.employee);
          }
          return;
        }
        if (target.popup === "slot_add") {
          const year = target.year;
          if (isNumber(year)) setSlotYear((current) => current ?? year);
          return;
        }
        if (target.popup === "leave_add") {
          // An absent or non-number employee opens the add form with no one preselected; the server decides who may be picked.
          const employee = isNumber(target.employee) ? target.employee : null;
          setLeaveAdd((current) => current ?? { employee });
          return;
        }
        if (target.popup === "leave_request") {
          setLeaveRequestOpen(true);
        }
      },
    }),
    [employeePopups],
  );

  return (
    <PalettePopupsContext.Provider value={api}>
      {children}
      {slotYear !== null ? <SlotFormModal year={slotYear} onClose={() => setSlotYear(null)} /> : null}
      {leaveAdd !== null ? (
        <LeaveFormModal mode={{ kind: "add", employee: leaveAdd.employee }} onClose={() => setLeaveAdd(null)} />
      ) : null}
      {leaveRequestOpen ? <LeaveRequestModal onClose={() => setLeaveRequestOpen(false)} /> : null}
    </PalettePopupsContext.Provider>
  );
}
