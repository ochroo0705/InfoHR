import { cn } from "../lib/utils";

// Port of app/templates/_nav_icon.html: a tinted icon tile for a row in a drop-down menu. `kind` is the icon name the
// server sends (accounts/nav.py NavItem.icon). Decorative: the row's text names it.

const TILE: Record<string, string> = {
  people: "bg-violet-100 text-violet-700",
  list: "bg-violet-100 text-violet-700",
  user: "bg-violet-100 text-violet-700",
  order: "bg-amber-100 text-amber-700",
  inbox: "bg-amber-100 text-amber-700",
  calendar: "bg-sky-100 text-sky-700",
  chart: "bg-emerald-100 text-emerald-700",
};

function Paths({ kind }: { kind: string }) {
  switch (kind) {
    case "people":
      return (
        <>
          <circle cx="7.5" cy="7" r="2.75" />
          <path d="M2.5 16c.6-2.6 2.6-4 5-4s4.4 1.4 5 4" />
          <circle cx="13.75" cy="6.5" r="2.25" />
          <path d="M14 11c1.9 0 3.4 1.2 3.8 3.5" />
        </>
      );
    case "order":
      return (
        <>
          <path d="M5 2.5h6.5l4 4V16a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 16V4A1.5 1.5 0 0 1 5 2.5z" />
          <path d="M11.5 2.5v4h4" />
          <path d="M6.5 10.5h7M6.5 13.5h7" />
        </>
      );
    case "calendar":
      return (
        <>
          <rect x="3" y="4" width="14" height="13.5" rx="2" />
          <path d="M3 8.5h14M7 2.5v3M13 2.5v3" />
        </>
      );
    case "inbox":
      return (
        <>
          <path d="M3 11l2-6.5h10L17 11v4.5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" />
          <path d="M3 11h4l1 2h4l1-2h4" />
        </>
      );
    case "chart":
      return <path d="M3.5 16.5h13M6 13.5v-4M10 13.5v-8M14 13.5v-6" />;
    case "history":
      return (
        <>
          <circle cx="10" cy="10" r="6.5" />
          <path d="M10 6.5V10l2.5 1.5" />
        </>
      );
    case "list":
      return <path d="M7.5 6h8M7.5 10h8M7.5 14h8M4 6h.01M4 10h.01M4 14h.01" />;
    case "gear":
      return (
        <>
          <circle cx="10" cy="10" r="2.5" />
          <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4" />
        </>
      );
    case "user":
      return (
        <>
          <circle cx="10" cy="7" r="3.5" />
          <path d="M3.5 17c1.2-3 3.7-4.5 6.5-4.5s5.3 1.5 6.5 4.5" />
        </>
      );
    case "key":
      return (
        <>
          <circle cx="7" cy="13" r="3.5" />
          <path d="M9.5 10.5L16 4M13.5 6.5l2 2" />
        </>
      );
    case "logout":
      return <path d="M8 3.5H5A1.5 1.5 0 0 0 3.5 5v10A1.5 1.5 0 0 0 5 16.5h3M12 6.5l3.5 3.5-3.5 3.5M15.5 10h-8" />;
    default:
      return (
        <>
          <rect x="3" y="3" width="14" height="14" rx="2" />
          <path d="M6.5 7.5h7M6.5 10.5h7M6.5 13.5h4" />
        </>
      );
  }
}

export function NavIcon({ kind }: { kind: string }) {
  return (
    <span
      className={cn(
        "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
        TILE[kind] ?? "bg-slate-100 text-slate-600",
      )}
    >
      <svg
        className="h-[18px] w-[18px]"
        viewBox="0 0 20 20"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
      >
        <Paths kind={kind} />
      </svg>
    </span>
  );
}
