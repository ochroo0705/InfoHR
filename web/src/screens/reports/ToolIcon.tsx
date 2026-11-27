import type { ReactNode } from "react";

// The 16px line icons of app/reports/templates/reports/_tool_icon.html, path by path. Decorative: the label beside the
// icon names the control. Only the kinds the report ribbon draws are here (search is drawn by FilterBar).
export type ToolIconKind =
  | "save"
  | "columns"
  | "filter"
  | "format"
  | "print"
  | "excel"
  | "select"
  | "reset"
  | "import"
  | "person_add"
  | "pencil";

const PATHS: Record<ToolIconKind, ReactNode> = {
  select: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <path d="M8 12l3 3 5-6" />
    </>
  ),
  save: (
    <>
      <path d="M5 3h11l3 3v15H5z" />
      <path d="M8 3v5h7V3M8 21v-7h8v7" />
    </>
  ),
  columns: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M9 4v16M15 4v16" />
    </>
  ),
  filter: <path d="M3 5h18l-7 8v6l-4 2v-8z" />,
  format: (
    <>
      <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="8" cy="17" r="2" />
    </>
  ),
  print: (
    <>
      <path d="M7 9V3h10v6M7 17H4v-7h16v7h-3" />
      <rect x="7" y="14" width="10" height="7" />
    </>
  ),
  excel: <path d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v3h16v-3" />,
  import: <path d="M12 15V3m0 0L8 7m4-4l4 4M4 17v3h16v-3" />,
  person_add: (
    <>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20c.8-3.4 3.4-5.2 6.5-5.2s5.7 1.8 6.5 5.2M19 8v6M16 11h6" />
    </>
  ),
  pencil: (
    <>
      <path d="M15.5 4.5l4 4L8 20H4v-4z" />
      <path d="M13.5 6.5l4 4" />
    </>
  ),
  reset: (
    <>
      <path d="M3 12a9 9 0 103-6.7L3 8" />
      <path d="M3 3v5h5" />
    </>
  ),
};

export function ToolIcon({ kind, className = "h-4 w-4" }: { kind: ToolIconKind; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`${className} shrink-0`}
    >
      {PATHS[kind]}
    </svg>
  );
}
