import { useState, type ReactNode } from "react";
import { DropMenu } from "./NavMenu";
import { getChoice, setChoice, type Choice } from "./theme";

// The «Өнгө» drop-down in the corner of the top bar (base.html lines 41-48). It opens on hover and on click, like the
// nav menus (nav.js). Its state is shared with the other menus, so it closes when another menu opens. The rows and
// icons are copied from base.html; the selected row and its check mark are styled by the theme-item and theme-check
// rules in styles/motion.css (input.css 236-238).

const ROWS: { value: Choice; label: string; icon: ReactNode }[] = [
  {
    value: "light",
    label: "Цайвар",
    icon: (
      <>
        <circle cx="10" cy="10" r="3.5" />
        <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4" />
      </>
    ),
  },
  {
    value: "dark",
    label: "Бараан",
    icon: <path d="M16.5 11.5A6.5 6.5 0 0 1 8.5 3.5a6.5 6.5 0 1 0 8 8z" />,
  },
  {
    value: "auto",
    label: "Автомат",
    icon: (
      <>
        <circle cx="10" cy="10" r="6.5" />
        <path d="M10 3.5v13" />
      </>
    ),
  },
];

function IconStroke({ children, size, className }: { children: ReactNode; size: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      {children}
    </svg>
  );
}

export function ThemeMenu() {
  const [choice, setLocal] = useState<Choice>(getChoice);

  function pick(value: Choice) {
    setChoice(value);
    setLocal(value);
  }

  return (
    <DropMenu
      id="ui:theme"
      placement="corner"
      hover={true}
      panelWidth="w-48"
      panelLabel="Өнгө"
      ariaLabel="Өнгө"
      triggerClassName="px-3 text-white/70"
      trigger={<IconStroke size={18}>{ROWS[2].icon}</IconStroke>}
    >
      {ROWS.map((row) => {
        const pressed = choice === row.value;
        return (
          <button
            key={row.value}
            type="button"
            data-theme-choice={row.value}
            aria-pressed={pressed}
            onClick={() => pick(row.value)}
            className="theme-item flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-slate-800 hover:bg-slate-50"
          >
            <IconStroke size={18} className="text-slate-500">
              {row.icon}
            </IconStroke>
            {row.label}
            <svg
              className="theme-check ml-auto"
              viewBox="0 0 20 20"
              width="16"
              height="16"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              focusable="false"
            >
              <path d="M4.5 10.5l3.5 3.5 7.5-8" />
            </svg>
          </button>
        );
      })}
    </DropMenu>
  );
}
