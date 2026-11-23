// What a palette row does when it is chosen (Enter or a click). Every row closes the panel first (palette.js closePanel),
// then:
// - a page row (open.kind "page") goes to its path: a ported path is a client route (goPorted), any other path is a full
//   page load into Django (legacy);
// - a pop-up row (open.kind "popup") opens its pop-up over the page (palette.js data-palette-modal rows, which close the
//   panel with focus restored); the pop-up lives at shell level (PalettePopups), not on the page underneath;
// - a legacy row (open.kind "legacy") is a full page load of the Django LIST page that owns the unported pop-up, never the
//   htmx fragment.
// The «show all» row never reaches this function: the panel asks the search for more instead. The panel remembers a row's
// ref (recents) before it calls this function.
import type { PaletteRowOut } from "../../api/palette";
import type { PalettePopupsApi } from "./PalettePopups";
import { isPorted } from "../../lib/ported";
import { isRelativePath } from "../../lib/relativePath";

export type ActivateDeps = {
  // Closes the panel. restoreFocus true puts focus back on the element that had it when the panel opened.
  closePanel(restoreFocus: boolean): void;
  // Client-side navigation to a ported path (the same navigation TLink uses, see viewTransition.ts).
  goPorted(to: string): void;
  // A full page load of a path the Django site still serves (the caller adds the site origin, see legacyOrigin()).
  legacy(path: string): void;
  // Opens the pop-up of a pop-up row (PalettePopups).
  popups: PalettePopupsApi;
};

export function activateRow(row: PaletteRowOut, deps: ActivateDeps): void {
  const open = row.open;
  // A row with no target does nothing at all, not even closing the panel. The «show all» row is never sent here: the
  // panel handles it before this function (AssistantPanel.activate).
  if (!open) return;
  if (open.kind === "page") {
    deps.closePanel(false);
    if (!isRelativePath(open.path)) return;
    if (isPorted(open.path)) deps.goPorted(open.path);
    else deps.legacy(open.path);
    return;
  }
  if (open.kind === "popup") {
    // palette.js: a data-palette-modal row closes the panel with focus restored, then the pop-up opens over the page.
    deps.closePanel(true);
    deps.popups.open(open);
    return;
  }
  if (open.kind === "legacy") {
    // The Django list page, as a full page load. The panel does not restore focus (the page is replaced).
    deps.closePanel(false);
    if (isRelativePath(open.path)) deps.legacy(open.path);
    return;
  }
  // An unknown kind: the panel closes, nothing else happens.
  deps.closePanel(false);
}
