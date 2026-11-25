// String edits of a report address (the query string). No rule is decided here: which filters exist, which values are
// valid and what a value means is the API's business. These helpers only keep every other parameter as it was typed:
// the order, the repeated keys (add=, cols=) and the percent-encoding of each part are copied unchanged.

// The `offset` parameter is the batch position; a filter change always starts again from the first batch.
const OFFSET = "offset";

// The parts of a query, without a leading "?" and without empty parts. Each part is the raw "key=value" text.
function partsOf(query: string): string[] {
  const raw = query.startsWith("?") ? query.slice(1) : query;
  return raw === "" ? [] : raw.split("&").filter((part) => part !== "");
}

// The name of one part, decoded, for comparison only. The part itself is never rewritten.
function nameOf(part: string): string {
  const eq = part.indexOf("=");
  const raw = (eq === -1 ? part : part.slice(0, eq)).replace(/\+/g, " ");
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

// The same query text back: a leading "?" is kept only when the caller's text had one.
function joined(query: string, parts: string[]): string {
  const body = parts.join("&");
  if (body === "") return "";
  return query.startsWith("?") ? `?${body}` : body;
}

// Sets ONE parameter. The first occurrence of `name` is replaced in place (or appended when there is none); further
// occurrences of `name` are dropped, so the name holds one value. An empty `value` removes the parameter. Every other
// part (including repeated keys such as add= and cols=) is kept as written, and `offset` is always removed.
export function set(query: string, name: string, value: string): string {
  const next: string[] = [];
  let placed = false;
  const fresh = value === "" ? null : `${encodeURIComponent(name)}=${encodeURIComponent(value)}`;
  for (const part of partsOf(query)) {
    const key = nameOf(part);
    if (key === OFFSET) continue;
    if (key === name) {
      if (fresh !== null && !placed) next.push(fresh);
      placed = true;
      continue;
    }
    next.push(part);
  }
  if (fresh !== null && !placed) next.push(fresh);
  return joined(query, next);
}

// The same address without `offset`, every other part kept as written.
export function clearOffset(query: string): string {
  return joined(query, partsOf(query).filter((part) => nameOf(part) !== OFFSET));
}
