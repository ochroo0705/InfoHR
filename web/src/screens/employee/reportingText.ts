// Mongolian strings and small helpers for the reporting-line block (the chain of managers above an employee).
// Pure functions and constants only: no React, no network.

export const RL_TEXT = {
  heading: "Удирдлагын шат",
  none: "Удирдлага байхгүй",
  hide: "Нуух",
  date: "Огноо",
  phone: "Утас",
  email: "И-мэйл",
  department: "Хэлтэс",
  loadError: "Удирдлагын шатыг ачаалж чадсангүй.",
} as const;

// The label of the control that shows the levels hidden behind the first ones. hidden is the number of hidden levels.
export function showLabel(hidden: number): string {
  return `Бүх шатыг харуулах · ${hidden}`;
}

// A date followed by the Mongolian word for "until". An empty date gives an empty string, so nothing is shown.
export function untilLabel(iso: string): string {
  return iso === "" ? "" : `${iso} хүртэл`;
}

// The reveal delay for a level: index 0 is the nearest level. It grows 70 ms per level and stops at the sixth step.
export function staggerMs(index: number): number {
  return Math.min(index, 6) * 70;
}

// The value as it is, or an em dash when the value is blank (empty or only spaces).
export function orDash(value: string): string {
  return value.trim() === "" ? "—" : value;
}
