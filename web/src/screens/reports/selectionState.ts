// Row selection on a report page: the pure state machine (port of the helpers in app/static/js/report_select.js).
// Every function returns a new state and never changes its input. `ids` holds the picked person ids as strings, in the
// order they were picked. `all` is «Бүх N мөрийг сонгох» (every matching row, no ids are sent). `held` is the «Сонгох»
// toggle: the mode stays on with nothing picked. Escape, a new report page and the toggle's off press end the mode.
// `visible` is always the person ids of the rows on screen, in the order they are drawn.

export type SelState = {
  ids: ReadonlySet<string>;
  all: boolean;
  held: boolean;
};

// The class of a picked row; its lime look is in static/css/input.css (.is-picked).
export const PICKED_CLASS = "is-picked";

// A person id as the server writes it: ASCII digits only, at most 12 of them. Anything else is ignored.
export function isPersonId(value: unknown): boolean {
  return /^\d{1,12}$/.test(String(value));
}

export function createState(): SelState {
  return { ids: new Set<string>(), all: false, held: false };
}

// The mode is on while the toggle holds it, or while anything is picked.
export function isOn(s: SelState): boolean {
  return s.held || s.all || s.ids.size > 0;
}

// «Сонгох»: turns the mode on with nothing picked, or off (and clears) when it is on.
export function toggleMode(s: SelState): SelState {
  if (isOn(s)) return endMode(s);
  return { ...s, held: true };
}

// Esc, «Болих», the toggle's off press, a page replacement or a history restore: picks and mode both go.
export function endMode(s: SelState): SelState {
  return { ids: new Set<string>(), all: false, held: false };
}

export function clearPicks(s: SelState): SelState {
  return { ids: new Set<string>(), all: false, held: s.held };
}

export function isPicked(s: SelState, id: unknown): boolean {
  return s.all || s.ids.has(String(id));
}

// The header box for the rows on screen: checked when all of them are picked, indeterminate when some are.
export function headerMark(s: SelState, visible: readonly string[]): { checked: boolean; indeterminate: boolean } {
  const ids = visible.filter(isPersonId);
  const picked = ids.filter((id) => isPicked(s, id)).length;
  return { checked: ids.length > 0 && picked === ids.length, indeterminate: picked > 0 && picked < ids.length };
}

// Ticks or unticks one person. `visible` is the ids of the rows on screen. Unticking while all matching rows are
// selected ends that mode: the rows on screen stay picked, minus this one.
export function setRow(s: SelState, id: string | number, on: boolean, visible: readonly string[]): SelState {
  if (!isPersonId(id)) return s;
  const key = String(id);
  if (s.all) {
    if (on) return s;
    const rest = visible.filter((x) => isPersonId(x) && String(x) !== key).map(String);
    return { ids: new Set(rest), all: false, held: s.held };
  }
  const ids = new Set(s.ids);
  if (on) ids.add(key);
  else ids.delete(key);
  return { ...s, ids };
}

// The header box: picks every row on screen, or clears the selection.
export function setVisible(s: SelState, on: boolean, visible: readonly string[]): SelState {
  if (!on) return clearPicks(s);
  const ids = new Set(s.ids);
  visible.filter(isPersonId).forEach((id) => ids.add(String(id)));
  return { ...s, ids };
}

// «Бүх N мөрийг сонгох»: every matching row, not only the ones on screen. The ids are not sent.
export function selectAll(s: SelState): SelState {
  return { ids: new Set<string>(), all: true, held: s.held };
}

// A new report page is a new list: its selection starts again. `changed` is false when it is the same page.
export function resetIfNewPage<T>(s: SelState, page: T, last: T | null): { state: SelState; changed: boolean } {
  if (page === last) return { state: s, changed: false };
  return { state: endMode(s), changed: true };
}

// The body of a selection action: the report address, then `all` or the picked person ids (only person ids, in the
// order they were picked).
export function selectionBody(query: string, s: SelState): { query: string; ids: string[]; all: boolean } {
  if (s.all) return { query, ids: [], all: true };
  return { query, ids: [...s.ids].filter(isPersonId), all: false };
}

// The note after «Хуулах»: the count, and how many rows the copy had to drop.
export function copyNote(data: { count: number; dropped: number }): string {
  const dropped = data.dropped ? " · " + data.dropped + " хасагдсан" : "";
  return "Хууллаа: " + data.count + dropped;
}
