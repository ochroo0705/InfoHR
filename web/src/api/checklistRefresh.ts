import type { QueryClient } from "@tanstack/react-query";

// The key of «Миний даалгавар», the signed-in user's open tasks.
export const checklistMineKey = ["checklists", "mine"] as const;

// Refreshes what a checklist write can change: every employee's work data (the panels and their counts; the key is
// ["employee", pk, "work"] and the write does not know the pk, so every employee's work refetches), «Миний даалгавар»,
// the My page and the Today page. The header and the other employee tabs are not touched.
export async function refreshAfterChecklistWrite(queryClient: QueryClient): Promise<void> {
  await queryClient.invalidateQueries({
    predicate: (query) => query.queryKey[0] === "employee" && query.queryKey[2] === "work",
  });
  await queryClient.invalidateQueries({ queryKey: checklistMineKey });
  await queryClient.invalidateQueries({ queryKey: ["me"] });
  // exact: open lazy lists under ["today", ...] are not refetched by a checklist write.
  await queryClient.invalidateQueries({ queryKey: ["today"], exact: true });
}

// A refused write (404: no right or the row is gone; 409: the change is refused) changed nothing, but the page on
// screen may be stale, so the same button would fail again. A 400 (a bad date) changes nothing and the data is fine.
export function isRefusedWrite(error: unknown): boolean {
  const status = (error as { status?: number } | null)?.status;
  return status === 404 || status === 409;
}

// On a refused write, refreshes the checklist data. The caller still gets the error to show its message.
export async function refreshIfRefused(queryClient: QueryClient, error: unknown): Promise<void> {
  if (isRefusedWrite(error)) await refreshAfterChecklistWrite(queryClient);
}
