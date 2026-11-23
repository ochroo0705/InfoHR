// Recents («Сүүлд нээсэн») of the palette. Port of the recents part of app/static/js/palette.js: readRecent, remember and
// the `recent` parameter that the empty box sends to /employees/palette/. A reference is short and carries no name:
// `p:<pk>` a person, `s:<path>` a fixed page. Every storage call is guarded: a blocked or full storage, or a value that
// is not ours, just means nothing is remembered or shown.
//
// The key is per user: "palette-recent-" + userId, where userId is the panel's data-user (so shared PCs do not mix them).
// Every function takes the userId; there is no shared default key.

// The key prefix only; the full key is RECENT_KEY_PREFIX + userId (see recentKey).
export const RECENT_KEY_PREFIX = "palette-recent-";
export const RECENT_MAX = 5;
// The longest `recent` value this module returns. The original palette.js sends the list uncapped; the server cuts it
// at RECENT_PARAM_LIMIT as well, so this cut is harmless and only keeps the request URL short.
export const RECENT_PARAM_MAX = 400;
// palette.js REF_SHAPE: `p:<pk>` (up to 12 digits) or `s:/<path>` (printable ASCII, up to 200 characters).
const REF_SHAPE = /^(p:[0-9]{1,12}|s:\/[!-~]{0,200})$/;

export function recentKey(userId: string | number): string {
  return RECENT_KEY_PREFIX + String(userId);
}

// An empty user id (the panel can open before the meta answer) has no key of its own: nothing is read or written for it,
// so every user does not share the bare "palette-recent-" key.
function hasUser(userId: string | number): boolean {
  return String(userId) !== "";
}

// The stored list, newest first. A stored value that is not a string in the ref shape is dropped on read, as in palette.js.
export function readRecent(storage: Storage | null, userId: string | number): string[] {
  if (!storage || !hasUser(userId)) return [];
  try {
    const list: unknown = JSON.parse(storage.getItem(recentKey(userId)) || "[]");
    if (!Array.isArray(list)) return [];
    return list
      .filter((ref): ref is string => typeof ref === "string" && REF_SHAPE.test(ref))
      .slice(0, RECENT_MAX);
  } catch {
    return [];
  }
}

// Puts `ref` first, drops its older copy, and keeps only RECENT_MAX references. A malformed or empty ref is ignored.
export function remember(storage: Storage | null, ref: string, userId: string | number): void {
  if (!storage || !hasUser(userId) || !ref || !REF_SHAPE.test(ref)) return;
  const list = [ref, ...readRecent(storage, userId).filter((r) => r !== ref)];
  try {
    storage.setItem(recentKey(userId), JSON.stringify(list.slice(0, RECENT_MAX)));
  } catch {
    // storage blocked or full: the box is simply not remembered
  }
}

// The comma list sent as `recent`, newest first. Whole references only: when the list would be longer than
// RECENT_PARAM_MAX characters, the oldest references are dropped until it fits.
export function recentParam(storage: Storage | null, userId: string | number): string {
  if (!hasUser(userId)) return "";
  const list = readRecent(storage, userId);
  while (list.length > 0 && list.join(",").length > RECENT_PARAM_MAX) list.pop();
  return list.join(",");
}
