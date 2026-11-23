// The Ctrl+K palette's answer (GET /api/v1/palette). Plain request through the api client, no TanStack cache: the answer
// depends on who asks and on what is typed, and a stale answer must never be reused. The caller passes an AbortSignal
// so a superseded query is cancelled (shell/palette/usePaletteSearch).
import { api } from "./client";
import { unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type PaletteOut = components["schemas"]["PaletteOut"];
export type PaletteGroupOut = components["schemas"]["PaletteGroupOut"];
export type PaletteRowOut = components["schemas"]["PaletteRowOut"];
export type PaletteOpenOut = components["schemas"]["PaletteOpenOut"];
export type PalettePieceOut = components["schemas"]["PalettePieceOut"];

export type PaletteParams = {
  q: string;
  // «Show all» people: sent as more=1 only when true.
  more?: boolean;
  // The empty box's remembered references (comma list). Sent only when given (the empty box).
  recent?: string;
  // The page path the palette was opened on. Sent only when given (the empty box).
  from?: string;
};

export async function fetchPalette(params: PaletteParams, signal?: AbortSignal): Promise<PaletteOut> {
  const query: { q: string; more?: string; recent?: string; from?: string } = { q: params.q };
  if (params.more) query.more = "1";
  if (params.recent !== undefined) query.recent = params.recent;
  if (params.from !== undefined) query.from = params.from;
  const result = await api.GET("/api/v1/palette", { params: { query }, signal });
  return unwrapQuery<PaletteOut>(result, "palette request failed");
}
