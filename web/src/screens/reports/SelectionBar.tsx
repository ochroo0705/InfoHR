import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { copySelection, postSelection, printTicket } from "../../api/reports";
import { copyNote, isOn } from "./selectionState";
import type { ReportSelection } from "./useReportSelection";

// The selection bar above a report table (app/reports/templates/reports/_selection_bar.html, the DOM and behaviour of
// app/static/js/report_select.js, UI_RULES §4b). It is drawn only while selection is on. The actions act on the
// picked people: Excel and CSV save a file, Хэвлэх opens the print page of the picks, Хуулах copies their names.
// The checklist action is not drawn here (step 5e). An action whose URL is empty is not drawn.

const NETWORK_MSG = "Холбогдож чадсангүй. Дахин оролдоно уу.";
const FAILED_MSG = "Татаж чадсангүй. Дахин оролдоно уу.";
const CLIPBOARD_MSG = "Хуулж чадсангүй.";
const NOTE_MS = 4000;
const BUTTON_CLASS = "rounded-lg border border-slate-300 bg-surface px-3 py-1.5 hover:bg-slate-50";

type ActionKind = "excel" | "csv" | "print" | "copy";
const ACTIONS: { kind: ActionKind; label: string }[] = [
  { kind: "excel", label: "Excel" },
  { kind: "csv", label: "CSV" },
  { kind: "print", label: "Хэвлэх" },
  { kind: "copy", label: "Хуулах" },
];

export interface SelectionBarProps {
  reportKey: string;
  query: string;
  total: number;
  urls: Record<string, string>;
  selection: ReportSelection;
  pickedCount: number;
  // report_select.js sync(): «all matching» is offered when every row on screen is picked and more batches follow.
  // The caller computes both from the loaded rows (false when there are no rows).
  allVisiblePicked: boolean;
  hasMore: boolean;
  // Over the cap (Django: table.count > MAX_PEOPLE). Then the note replaces the «all matching» button. The cap is not
  // in the API payload yet, so the caller passes it (maxPeople) and computes overCap from the table count.
  overCap: boolean;
  maxPeople: number;
}

type Note = { text: string; isError: boolean };

// The text of a failed selection request: a refusal (it carries a status) shows its own message; anything that never
// reached the server shows the network text.
function messageOf(error: unknown): string {
  const failure = error as { status?: unknown; message?: unknown };
  return typeof failure.status === "number" && typeof failure.message === "string" ? failure.message : NETWORK_MSG;
}

// The clipboard API needs a secure context; a hidden textarea and execCommand are the fallback (report_select.js).
function fallbackCopy(text: string): boolean {
  const area = document.createElement("textarea");
  area.value = text;
  area.readOnly = true;
  area.className = "sr-only";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  area.remove();
  return ok;
}

function writeClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text).then(
      () => true,
      () => fallbackCopy(text),
    );
  }
  return Promise.resolve(fallbackCopy(text));
}

// The blob as a download: an anchor with the object URL, released after a second.
function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function SelectionBar(props: SelectionBarProps) {
  // Off: nothing is drawn. The inner bar unmounts with the mode, so its note and pending count start fresh each time.
  if (!isOn(props.selection.state)) return null;
  return <ActiveSelectionBar {...props} />;
}

function ActiveSelectionBar({
  reportKey,
  query,
  total,
  urls,
  selection,
  pickedCount,
  allVisiblePicked,
  hasMore,
  overCap,
  maxPeople,
}: SelectionBarProps) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState<Note | null>(null);
  const [busy, setBusy] = useState(0);
  const busyRef = useRef(0);
  const all = selection.state.all;

  // A success note clears itself; an error stays until the next action.
  useEffect(() => {
    if (note === null || note.isError) return;
    const timer = setTimeout(() => setNote(null), NOTE_MS);
    return () => clearTimeout(timer);
  }, [note]);

  // Every request takes one begin() and calls the returned finish() exactly once. The action buttons are off while any
  // request is pending.
  function begin(): () => void {
    busyRef.current += 1;
    setBusy(busyRef.current);
    let done = false;
    return () => {
      if (done) return;
      done = true;
      busyRef.current -= 1;
      setBusy(busyRef.current);
    };
  }

  async function saveFile(kind: "excel" | "csv"): Promise<void> {
    const { blob, filename } = await postSelection(queryClient, reportKey, kind, selection.body(query));
    try {
      saveBlob(blob, filename);
    } catch {
      // The file arrived but could not be saved here: a plain failure, not a network one.
      setNote({ text: FAILED_MSG, isError: true });
    }
  }

  async function copyPicks(): Promise<void> {
    const data = await copySelection(queryClient, reportKey, selection.body(query));
    const ok = await writeClipboard(data.text);
    setNote(ok ? { text: copyNote(data), isError: false } : { text: CLIPBOARD_MSG, isError: true });
  }

  function runFileOrCopy(kind: "excel" | "csv" | "copy"): void {
    if (busyRef.current > 0) return;
    const finish = begin();
    const job = kind === "copy" ? copyPicks() : saveFile(kind);
    job.catch((error: unknown) => setNote({ text: messageOf(error), isError: true })).finally(finish);
  }

  // The blank window opens inside the click, so the browser allows it; the print page loads once the ticket is ready.
  function runPrint(): void {
    const win = window.open("", "_blank");
    if (!win) {
      setNote({ text: FAILED_MSG, isError: true });
      return;
    }
    const finish = begin();
    printTicket(queryClient, reportKey, selection.body(query))
      .then((ticket) => {
        win.location.href = `/reports/${reportKey}/print/?sel=${encodeURIComponent(ticket)}`;
      })
      .catch((error: unknown) => {
        win.close();
        setNote({ text: messageOf(error), isError: true });
      })
      .finally(finish);
  }

  function runAction(kind: ActionKind): void {
    if (!urls[kind]) return;
    if (kind === "print") runPrint();
    else runFileOrCopy(kind);
  }

  // report_select.js sync(): the offer needs every row on screen picked and more batches (never in all-matching mode).
  // Over the cap the note stands in for the button.
  const offer = !all && allVisiblePicked && hasMore;
  const offerAll = offer && !overCap;
  const showOverCap = offer && overCap;
  const count = all ? `Бүгд (${total})` : String(pickedCount);

  return (
    <div
      id="selection-bar"
      data-query={query}
      className="selection-bar mb-3 flex min-w-0 max-w-full flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-sm"
    >
      <span className="font-medium text-slate-900">
        <span data-count>{count}</span> сонгосон
      </span>
      {note && (
        <span
          data-select-msg
          role={note.isError ? "alert" : "status"}
          className={note.isError ? "text-sm text-red-700" : "text-sm text-slate-700"}
        >
          {note.text}
        </span>
      )}
      {showOverCap && (
        <span data-over-cap className="px-2 py-1 text-xs text-slate-500">
          {`${maxPeople}-аас олон мөр сонгох боломжгүй. Шүүлтүүрээр нарийвчилна уу.`}
        </span>
      )}
      {offerAll && (
        <button
          type="button"
          data-select-matching
          onClick={selection.pickAll}
          className="rounded-lg px-2 py-1 text-violet-700 hover:underline"
        >
          {`Бүх ${total} мөрийг сонгох`}
        </button>
      )}
      <div className="ml-auto flex max-w-full min-w-0 flex-wrap items-center gap-2">
        {ACTIONS.filter(({ kind }) => Boolean(urls[kind])).map(({ kind, label }) => (
          <button
            key={kind}
            type="button"
            data-action={kind}
            data-url={urls[kind]}
            disabled={busy > 0}
            onClick={() => runAction(kind)}
            className={BUTTON_CLASS}
          >
            {label}
          </button>
        ))}
        <button
          type="button"
          data-select-cancel
          onClick={selection.cancel}
          className="rounded-lg px-3 py-1.5 text-slate-600 hover:underline"
        >
          Болих
        </button>
      </div>
    </div>
  );
}
