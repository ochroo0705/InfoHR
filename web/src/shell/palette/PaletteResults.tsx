// The palette's result list. Port of the markup of app/employees/templates/employees/_palette_results.html, _palette_group.html,
// _palette_person.html, _palette_person_actions.html and _palette_icons.html. React draws what the API sends: the group
// order, the titles, the counts (and total when the API sends one), the note, the empty block and the fallback rows. It
// sorts, filters and highlights nothing; a piece with hit set is wrapped in the same <mark> the `hl` filter gives.
import { Fragment, useEffect, useRef, type MouseEvent, type ReactNode } from "react";
import type { PaletteOut, PalettePieceOut, PaletteRowOut } from "../../api/palette";
import { isRelativePath } from "../../lib/relativePath";
import { ScrollFloat } from "../../widgets/Scrollbar";

export type PaletteResultsProps = {
  answer: PaletteOut | null;
  busy: boolean;
  failed: boolean;
  selectedKey?: string | null;
  // True when the answer on screen is a «show all» answer: it keeps the scroll position. Any other answer scrolls the list
  // back to the top (palette.js `results.scrollTop = 0`).
  keepScroll?: boolean;
  // A typed query fills the panel (palette.js syncMode: flex-1 and no max height); the empty box keeps the 40vh cap.
  fill?: boolean;
  onSelect(key: string): void;
  onActivate(row: PaletteRowOut): void;
};

const ROW_CLASS =
  "group flex items-center gap-3 rounded-lg border-l-2 border-l-transparent px-3 py-2 text-sm hover:bg-violet-50 aria-selected:border-l-violet-600 aria-selected:bg-violet-50 max-sm:min-h-11";
const GROUP_WRAP_CLASS = "border-t border-slate-100 first:border-t-0";
const GROUP_HEAD_CLASS =
  "sticky top-0 z-10 flex items-baseline justify-between gap-2 bg-surface px-3 pb-1 pt-2 text-xs font-semibold tracking-wide text-slate-500";

// The pieces of one text: a piece with hit is marked (the `hl` filter's mark), the rest is plain text (React escapes it).
function Pieces({ pieces }: { pieces: PalettePieceOut[] }): ReactNode {
  return pieces.map((piece, i) =>
    piece.hit ? (
      <mark key={i} className="rounded bg-violet-200/60 text-inherit">
        {piece.text}
      </mark>
    ) : (
      <Fragment key={i}>{piece.text}</Fragment>
    ),
  );
}

// _palette_icons.html: a 16 px line icon, slate, violet on the selected row. Decorative: the row's text names it.
function RowIcon({ kind }: { kind: PaletteRowOut["kind"] }) {
  const common = {
    className: "h-4 w-4 shrink-0 text-slate-400 group-aria-selected:text-violet-600",
    viewBox: "0 0 20 20",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": "true" as const,
    focusable: "false" as const,
  };
  if (kind === "action") {
    return (
      <svg {...common}>
        <path d="M11.2 2.5L4.5 11h4.8l-1 6.5 6.7-8.5h-4.8z" />
      </svg>
    );
  }
  if (kind === "order") {
    return (
      <svg {...common}>
        <path d="M5 2.5h6.5l4 4V16a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 16V4A1.5 1.5 0 0 1 5 2.5z" />
        <path d="M11.5 2.5v4h4" />
        <path d="M6.5 10.5h7M6.5 13.5h7" />
      </svg>
    );
  }
  if (kind === "more") {
    return (
      <svg {...common} className="h-4 w-4 shrink-0 text-violet-500 group-aria-selected:text-violet-600">
        <path d="M5.5 8l4.5 4.5L14.5 8" />
      </svg>
    );
  }
  if (kind === "calendar") {
    return (
      <svg {...common}>
        <rect x="3" y="4" width="14" height="13.5" rx="2" />
        <path d="M3 8.5h14M7 2.5v3M13 2.5v3" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <rect x="3" y="3" width="14" height="14" rx="2" />
      <path d="M6.5 7.5h7M6.5 10.5h7M6.5 13.5h4" />
    </svg>
  );
}

// The text of a row, as its template draws it: a person (_palette_person.html), an order (its title and day line) or
// any other kind (one truncated title).
function RowText({ row }: { row: PaletteRowOut }) {
  if (row.kind === "person") {
    return (
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-2">
          <span className="min-w-0 truncate font-medium">
            <Pieces pieces={row.title} />
          </span>
          <span className="shrink-0 text-xs text-slate-500">
            <Pieces pieces={row.code} />
          </span>
        </span>
        {row.lines.map((line, i) => (
          <span key={i} className="block truncate text-xs text-slate-500">
            <Pieces pieces={line} />
          </span>
        ))}
      </span>
    );
  }
  if (row.kind === "order") {
    return (
      <span className="min-w-0">
        <span className="block truncate">
          <Pieces pieces={row.title} />
        </span>
        {row.day && <span className="block text-xs text-slate-500">{row.day}</span>}
      </span>
    );
  }
  return (
    <span className="min-w-0 truncate">
      <Pieces pieces={row.title} />
    </span>
  );
}

// One row. A row whose open.path is a same-site path is a link to it; any other row has no href and is still selectable.
// «show all» (kind more, open null) goes to onActivate like the others, which decides what happens. Rows dim while busy
// (the caller's answer is still on screen); the group headers, the note and the empty text stay bright.
function Row({
  row,
  selected,
  dim,
  onSelect,
  onActivate,
}: {
  row: PaletteRowOut;
  selected: boolean;
  dim: boolean;
  onSelect(key: string): void;
  onActivate(row: PaletteRowOut): void;
}) {
  const isPerson = row.kind === "person";
  const isMore = row.kind === "more";
  const href = isRelativePath(row.open?.path) ? row.open?.path : undefined;

  // A click with a modifier keeps the link's own behaviour (a new tab); a plain click goes to onActivate.
  const onClick = (e: MouseEvent<HTMLElement>) => {
    if (href && (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey)) return;
    e.preventDefault();
    onActivate(row);
  };

  const classes = [ROW_CLASS, isMore ? "text-violet-700" : "", dim ? "opacity-60" : ""].filter(Boolean).join(" ");

  const props = {
    role: "option",
    "aria-selected": selected,
    "data-palette-item": "",
    "data-palette-ref": row.ref ?? undefined,
    "data-palette-modal": row.open?.kind === "popup" ? "" : undefined,
    "data-palette-more": isMore ? "" : undefined,
    className: classes,
    onMouseMove: () => {
      if (!selected) onSelect(row.key);
    },
    onClick,
  };

  const content = (
    <>
      {isPerson ? (
        <span
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
            row.left ? "bg-slate-200 text-slate-600" : "bg-violet-100 text-violet-700"
          }`}
          aria-hidden="true"
        >
          {row.initials}
        </span>
      ) : (
        <RowIcon kind={row.kind} />
      )}
      <RowText row={row} />
      {isPerson && row.left && (
        <span className="shrink-0 rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-700">Гарсан</span>
      )}
    </>
  );

  return href ? (
    <a href={href} {...props}>
      {content}
    </a>
  ) : (
    <div {...props}>{content}</div>
  );
}

export function PaletteResults({
  answer,
  busy,
  failed,
  selectedKey,
  keepScroll = false,
  fill = false,
  onSelect,
  onActivate,
}: PaletteResultsProps) {
  const listRef = useRef<HTMLDivElement>(null);
  // Read in the effect below, which must run only when the answer changes (not when the flag flips on its own).
  const keepScrollRef = useRef(keepScroll);
  keepScrollRef.current = keepScroll;

  useEffect(() => {
    if (!keepScrollRef.current && listRef.current) listRef.current.scrollTop = 0;
  }, [answer]);

  const rowFor = (row: PaletteRowOut) => (
    <Row
      key={row.key}
      row={row}
      selected={row.key === selectedKey}
      dim={busy}
      onSelect={onSelect}
      onActivate={onActivate}
    />
  );

  let body: ReactNode = null;
  if (failed) {
    body = <p data-palette-failed className="px-3 py-2 text-sm text-red-600">Хайлт амжилтгүй боллоо</p>;
  } else if (answer) {
    body = (
      <>
        {answer.groups.map((group) => (
          <div key={group.key} className={GROUP_WRAP_CLASS}>
            <p className={GROUP_HEAD_CLASS}>
              <span>{group.title}</span>
              <span className="font-normal text-slate-400">
                {group.total != null ? `${group.count} / ${group.total}` : String(group.count)}
              </span>
            </p>
            {group.rows.map(rowFor)}
            {group.note && (
              <p data-palette-cut className="px-3 py-2 text-xs text-slate-500">
                {group.note}
              </p>
            )}
          </div>
        ))}
        {answer.empty && (
          <>
            <p data-palette-empty className="px-3 py-2 text-sm text-slate-500">
              {answer.empty_text}
            </p>
            <p className="px-3 pt-2 text-xs text-slate-500">{answer.fallback_heading}</p>
            {answer.fallback.map(rowFor)}
          </>
        )}
      </>
    );
  }

  // A float rail, as scrollbars.js gives the original's overflow-y-auto list (UI_RULES §4).
  return (
    <ScrollFloat
      boxRef={listRef}
      id="palette-results"
      data-palette-results
      role="listbox"
      aria-busy={busy ? true : undefined}
      className={fill ? "max-h-[40vh] shrink-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-2" : "max-h-[40vh] shrink-0 overflow-y-auto overscroll-contain px-2 pb-2"}
      style={fill ? { maxHeight: "none" } : undefined}
    >
      {body}
    </ScrollFloat>
  );
}
