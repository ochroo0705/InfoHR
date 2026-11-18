// The stale-check snapshot of a save (employees/stale.py: `json.dumps({name: value})`, unprefixed field names).
// The snapshot says what the user saw when the form loaded. For a name the user is still editing, the save must keep
// the value from the snapshot the user saw when the edit began (the "base"), not the value of a later refetch: otherwise
// the server would take the newer stored value as seen and the user's edit would overwrite it silently.

export type Snapshot = Record<string, unknown>;
// The base values of the edited names, by snapshot key.
export type Base = Record<string, unknown>;

// The snapshot as an object, or null when the text is not a JSON object.
function parseObject(json: string): Snapshot | null {
  try {
    const value: unknown = JSON.parse(json);
    return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Snapshot) : null;
  } catch {
    return null;
  }
}

// The snapshot as an object; a text that is not a JSON object reads as an empty snapshot.
export function parseLoaded(json: string): Snapshot {
  return parseObject(json) ?? {};
}

// The snapshot key of an HTML name. `prefix` (for example "si-" for the salary form) is removed only from a name that
// starts with it; any other name is its own key.
export function keyOf(name: string, prefix = ""): string {
  return prefix !== "" && name.startsWith(prefix) ? name.slice(prefix.length) : name;
}

// Records the base of `name` from `loadedJson` (the snapshot the user saw), unless a base is already recorded or the
// snapshot has no key for it. Returns the same object when nothing is recorded.
export function captureBase(base: Base, name: string, loadedJson: string, prefix = ""): Base {
  const key = keyOf(name, prefix);
  if (Object.hasOwn(base, key)) return base;
  const snapshot = parseObject(loadedJson);
  if (!snapshot || !Object.hasOwn(snapshot, key)) return base;
  return { ...base, [key]: snapshot[key] };
}

// Drops the base of `name` (its edit was removed, saved or refused). Returns the same object when there is none.
export function dropBase(base: Base, name: string, prefix = ""): Base {
  const key = keyOf(name, prefix);
  if (!Object.hasOwn(base, key)) return base;
  return Object.fromEntries(Object.entries(base).filter(([k]) => k !== key));
}

// The snapshot a save sends: the current snapshot with the base value substituted for every edited name that has a
// recorded base. When nothing is substituted, or the current text is not a JSON object, the current text is returned
// unchanged.
export function effectiveLoaded(
  currentLoadedJson: string,
  base: Base,
  editedNames: string[],
  prefix = "",
): string {
  const current = parseObject(currentLoadedJson);
  if (!current) return currentLoadedJson;
  let substituted = false;
  const snapshot: Snapshot = { ...current };
  for (const name of editedNames) {
    const key = keyOf(name, prefix);
    if (Object.hasOwn(base, key)) {
      snapshot[key] = base[key];
      substituted = true;
    }
  }
  return substituted ? JSON.stringify(snapshot) : currentLoadedJson;
}
