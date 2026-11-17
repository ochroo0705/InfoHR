import type { ReactNode } from "react";

// The inline SVGs of `_rail.html` and `detail.html`, copied from the template (paths, sizes and strokes). Each icon is
// decorative (aria-hidden); the text next to it, or the sr-only label, names it.

type IconProps = { size?: number; stroke?: number };

function Svg({
  children,
  size,
  stroke,
  viewBox = "0 0 20 20",
}: {
  children: ReactNode;
  size: number;
  stroke: number;
  viewBox?: string;
}) {
  return (
    <svg
      viewBox={viewBox}
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

// The briefcase: «Ажил» in the rail and the tab bar, and the «Албан тушаал» fact.
const WORK = (
  <>
    <rect x="3" y="6" width="14" height="10" rx="2" />
    <path d="M7.5 6V4.5A1.5 1.5 0 0 1 9 3h2a1.5 1.5 0 0 1 1.5 1.5V6M3 10.5h14" />
  </>
);

// The banknote: «Цалин, даатгал».
const SALARY = (
  <>
    <rect x="2.5" y="5" width="15" height="10" rx="2" />
    <circle cx="10" cy="10" r="2.2" />
    <path d="M5.5 8v4M14.5 8v4" />
  </>
);

// The person: «Хувийн», and the «Шууд удирдлага» fact.
const PERSON = (
  <>
    <circle cx="10" cy="7" r="3" />
    <path d="M4 17a6 6 0 0 1 12 0" />
  </>
);

// The building with windows: the «Хэлтэс» fact.
const DEPARTMENT = (
  <path d="M4 17V4.5A1.5 1.5 0 0 1 5.5 3h6A1.5 1.5 0 0 1 13 4.5V17M13 8h2.5A1.5 1.5 0 0 1 17 9.5V17M2.5 17h15M7 6.5h2M7 9.5h2M7 12.5h2" />
);

// The calendar: the «Ажилд орсон» fact.
const HIRE = (
  <>
    <rect x="3" y="4.5" width="14" height="12" rx="2" />
    <path d="M3 8.5h14M7 2.5v4M13 2.5v4" />
  </>
);

// The handset: the «Утас» fact.
const PHONE = <path d="M5 3h3l1.5 4-2 1.2a9 9 0 0 0 4.3 4.3L13 10.5l4 1.5v3a2 2 0 0 1-2 2A12 12 0 0 1 3 5a2 2 0 0 1 2-2z" />;

// The close cross of the «Түүх» drawer (detail.html, data-drawer-close).
const CLOSE = <path d="M6 6l12 12M18 6L6 18" />;

// Rail and tab-bar links: 16px, stroke 1.6.
export function WorkIcon({ size = 16, stroke = 1.6 }: IconProps) {
  return <Svg size={size} stroke={stroke}>{WORK}</Svg>;
}

export function SalaryIcon({ size = 16, stroke = 1.6 }: IconProps) {
  return <Svg size={size} stroke={stroke}>{SALARY}</Svg>;
}

export function PersonalIcon({ size = 16, stroke = 1.6 }: IconProps) {
  return <Svg size={size} stroke={stroke}>{PERSON}</Svg>;
}

// Facts card icons: 14px, stroke 1.5. The position icon uses the briefcase.
export function PositionIcon({ size = 14, stroke = 1.5 }: IconProps) {
  return <Svg size={size} stroke={stroke}>{WORK}</Svg>;
}

export function DepartmentIcon({ size = 14, stroke = 1.5 }: IconProps) {
  return <Svg size={size} stroke={stroke}>{DEPARTMENT}</Svg>;
}

export function ManagerIcon({ size = 14, stroke = 1.5 }: IconProps) {
  return <Svg size={size} stroke={stroke}>{PERSON}</Svg>;
}

export function HireDateIcon({ size = 14, stroke = 1.5 }: IconProps) {
  return <Svg size={size} stroke={stroke}>{HIRE}</Svg>;
}

export function PhoneIcon({ size = 14, stroke = 1.5 }: IconProps) {
  return <Svg size={size} stroke={stroke}>{PHONE}</Svg>;
}

// The drawer close button: 22px, stroke 2, on a 24 grid.
export function CloseIcon() {
  return (
    <Svg size={22} stroke={2} viewBox="0 0 24 24">
      {CLOSE}
    </Svg>
  );
}
