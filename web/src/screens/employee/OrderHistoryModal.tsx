import { useQueryClient } from "@tanstack/react-query";
import { Fragment } from "react";
import { useOrderHistory } from "../../api/orders";
import type { ApiFailure } from "../../api/mutate";
import { Modal } from "../../widgets/Modal";
import { loadMessagesOf, useStaleRefresh } from "./popupGuards";

// The read-only order history of `employees/_order_history.html`: the title and the entries come from the API (newest
// first, as sent; React does not re-sort). Nothing is typed here, so there is no dirty flag and no unsaved registry.
// Contract: the parent remounts the pop-up with a new key for each open, and keeps it mounted while `open` goes false so
// the Modal plays its exit. The query is disabled while closed, so a late answer after close is never shown.

export type OrderHistoryModalProps = {
  pk: number;
  orderId: number;
  open: boolean;
  // Called once the pop-up may close (Хаах, ✕, Escape, outside click). The parent sets open to false.
  onClose: () => void;
};

export function OrderHistoryModal({ pk, orderId, open, onClose }: OrderHistoryModalProps) {
  const queryClient = useQueryClient();
  const load = useOrderHistory(pk, orderId, open);
  const shown = load.data ?? null;

  // A load that answers 404 means the page changed: refresh the employee's work and activity.
  const loadFailure = load.isError ? (load.error as Partial<ApiFailure>) : null;
  useStaleRefresh(loadFailure?.status === 404, pk, queryClient, ["work", "activity"]);

  // A failed load shows its message and no timeline. Loading draws nothing (the Modal stays closed until the data or
  // the failure arrives).
  const showing = open && (shown !== null || load.isError);

  return (
    <Modal open={showing} onClose={onClose} title={shown?.title}>
      {shown ? (
        shown.entries.length === 0 ? (
          <p className="text-sm text-slate-500">Бүртгэл алга</p>
        ) : (
          <ol className="ml-1 border-l border-slate-200">
            {shown.entries.map((entry, i) => (
              <li key={i} className="relative pb-4 pl-4 text-sm last:pb-1">
                <span className="absolute top-1.5 -left-[5px] h-2.5 w-2.5 rounded-full border-2 border-surface bg-violet-500"></span>
                <div className="flex items-baseline gap-2">
                  <span className="truncate font-medium">{entry.by}</span>
                  <span className="ml-auto shrink-0 text-xs text-slate-400">{entry.at}</span>
                </div>
                <p className="mt-0.5 text-slate-700">{entry.message}</p>
                {entry.changes.length > 0 ? (
                  <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                    {entry.changes.map((change, j) => (
                      <Fragment key={j}>
                        <dt className="text-slate-500">{change.field}</dt>
                        <dd className="text-slate-800">
                          {change.old ? (
                            <>
                              <s className="text-slate-400">{change.old}</s> →{" "}
                            </>
                          ) : null}
                          {change.new || "(хоосон)"}
                        </dd>
                      </Fragment>
                    ))}
                  </dl>
                ) : null}
              </li>
            ))}
          </ol>
        )
      ) : (
        <p className="rounded bg-red-50 p-2 text-sm text-red-700">{loadMessagesOf(loadFailure).join(" ")}</p>
      )}
      <div className="flex justify-end pt-2">
        <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 text-sm">
          Хаах
        </button>
      </div>
    </Modal>
  );
}
