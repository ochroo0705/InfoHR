// The assistant panel's open state and its opener. The provider owns the open flag (panelStore, per user, in
// sessionStorage) and the global Ctrl+K shortcut (palette.js, capture-phase keydown). Anything that opens or closes the
// panel (the top-bar «Хайх» button, the shortcut, the panel's ×) goes through this context.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { modalStack } from "../../widgets/modalLogic";
import { useMeta } from "../useMeta";
import { isOpenShortcut } from "./paletteKeys";
import { createPanelStore, type PanelStore } from "./panelStore";

export type PalettePanelApi = {
  open(): void;
  // Closes the panel. restoreFocus (default true) puts focus back on the element that had it when the panel opened, when
  // that element is still in the page; without it, focus falls to the top-bar «Хайх» button if it was inside the panel.
  close(restoreFocus?: boolean): void;
  // Opens when closed, closes when open (the top-bar button and the shortcut both toggle, as in palette.js).
  toggle(): void;
  isOpen: boolean;
  // False when the stored flag reopened the panel on page load: that open does not play the enter motion (data-no-enter).
  openedByUser: boolean;
  // Counts the opens. The panel body is keyed by it, so a reopen during the exit starts with an empty box.
  session: number;
};

export const PalettePanelContext = createContext<PalettePanelApi | null>(null);

// The context of the nearest provider. Outside a provider this is a bug, so it throws instead of guessing.
export function usePalettePanel(): PalettePanelApi {
  const api = useContext(PalettePanelContext);
  if (api === null) {
    throw new Error("usePalettePanel must be used inside PalettePanelProvider (AppShell mounts it).");
  }
  return api;
}

// A browser storage, or null when the browser blocks it (reading window.localStorage itself can throw).
export function browserStorage(kind: "localStorage" | "sessionStorage"): Storage | null {
  try {
    return window[kind];
  } catch {
    return null;
  }
}

type PanelState = { open: boolean; openedByUser: boolean; session: number };

export function PalettePanelProvider({ children }: { children: ReactNode }) {
  const { data: meta } = useMeta();
  const userId = meta?.user?.id ?? null;
  // The open flag is per user. Until the meta answer names the user there is no store, and the panel stays closed.
  const store: PanelStore | null = useMemo(
    () => (userId === null ? null : createPanelStore(browserStorage("sessionStorage"), userId)),
    [userId],
  );

  const [state, setState] = useState<PanelState>({ open: false, openedByUser: false, session: 0 });
  // The handlers below read the live state, so a key press never acts on the render it was set up in.
  const stateRef = useRef(state);
  stateRef.current = state;
  // The element that had focus when the panel was opened by the user (palette.js `opener`).
  const openerRef = useRef<Element | null>(null);
  // Set once the user has opened or closed the panel. From then on the panel's state wins over the stored flag, so a
  // meta answer that arrives late does not undo an open made before it (Ctrl+K before the meta answer).
  const touchedRef = useRef(false);

  // The store appears with the meta answer. Without a user action yet, the stored flag decides, and a reopen here takes
  // no focus and plays no enter motion. After a user action, the current state is written to the new store instead.
  useLayoutEffect(() => {
    if (touchedRef.current) {
      store?.setOpen(stateRef.current.open);
      return;
    }
    const open = store !== null && store.isOpen();
    setState((s) => ({ open, openedByUser: false, session: s.session + 1 }));
  }, [store]);

  const open = useCallback(() => {
    touchedRef.current = true;
    if (stateRef.current.open) return;
    openerRef.current = document.activeElement;
    store?.setOpen(true);
    setState((s) => ({ open: true, openedByUser: true, session: s.session + 1 }));
  }, [store]);

  const close = useCallback(
    (restoreFocus = true) => {
      touchedRef.current = true;
      if (!stateRef.current.open) return;
      const back = openerRef.current as HTMLElement | null;
      openerRef.current = null;
      const useBack = restoreFocus && back !== null && back.isConnected && typeof back.focus === "function";
      // Focus inside the panel must not fall to the body when the panel hides: move it to the top-bar button first.
      const aside = document.querySelector("[data-assistant-panel]");
      const inside = aside !== null && aside.contains(document.activeElement);
      if (inside && !useBack) document.querySelector<HTMLElement>("[data-palette-open]")?.focus();
      store?.setOpen(false);
      setState((s) => ({ ...s, open: false }));
      if (useBack) back?.focus();
    },
    [store],
  );

  const toggle = useCallback(() => {
    if (stateRef.current.open) close(true);
    else open();
  }, [open, close]);

  // Ctrl+K / Cmd+K, capture phase, so it works while a text box has focus. The browser's own Ctrl+K is always stopped
  // first (preventDefault and stopPropagation), then a repeat and an open pop-up (Modal or confirm) do nothing else.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!isOpenShortcut(e)) return;
      e.preventDefault();
      e.stopPropagation();
      if (modalStack().length > 0) return;
      if (e.repeat) return;
      toggle();
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [toggle]);

  const value = useMemo<PalettePanelApi>(
    () => ({
      open,
      close,
      toggle,
      isOpen: state.open,
      openedByUser: state.openedByUser,
      session: state.session,
    }),
    [open, close, toggle, state.open, state.openedByUser, state.session],
  );

  return <PalettePanelContext.Provider value={value}>{children}</PalettePanelContext.Provider>;
}
