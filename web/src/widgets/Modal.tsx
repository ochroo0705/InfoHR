import { useEffect, useId, useRef, useState, type MouseEvent, type ReactNode, type SyntheticEvent } from "react";
import { createPortal } from "react-dom";
import { usePresence } from "../lib/presence";
import { cn } from "../lib/utils";
import { confirm } from "./confirm";
import {
  hasServerErrors,
  modalStack,
  pickEscapeTarget,
  popModal,
  pushModal,
  tryClose,
  type ServerErrors,
  type StackEntry,
} from "./modalLogic";

// The pop-up shell (UI_RULES §6; model: employees/_modal.html and app/static/js/modal.js).
// - Closes on an outside click, on ✕ (top right) and on Escape. Escape closes the topmost pop-up that is not leaving.
// - An inner popup (a dropdown, a date picker) that handles Escape calls event.preventDefault() in its own keydown
//   handler. Modal ignores an Escape that was already defaultPrevented, so that Escape closes nothing here.
// - With typed input (dirty) or a server error, ✕, Escape and an outside click ask first (confirm.tsx).
// - Enter: the overlay fades and the panel lifts (the hr-fade and hr-pop rules of styles/motion.css).
//   Exit: usePresence keeps it mounted while the data-leaving rules play, then removes it.
// - An open pop-up locks the page behind it (body:has(.fixed.inset-0.z-50) in styles/motion.css).

export interface ModalProps {
  open: boolean;
  // Called once the close is allowed (after the dirty check). The parent sets open to false.
  onClose: () => void;
  dirty?: boolean;
  serverErrors?: ServerErrors | null;
  title?: ReactNode;
  // No enter and no exit animation; the pop-up appears and goes at once (the legacy no-anim class).
  noAnim?: boolean;
  // false: no ✕, and Escape, ✕ and an outside click do nothing (the one-time password, UI_RULES §6a). Default true.
  closable?: boolean;
  // A Tailwind max-width class for the panel. Default max-w-2xl, as in employees/_modal.html.
  width?: string;
  // The Tailwind classes of the title (h2). Default "mb-4 text-lg font-semibold". A Django pop-up with a smaller gap under
  // its title passes its own, e.g. "mb-1 text-lg font-semibold" (leave request detail) or "mb-2 text-lg font-semibold".
  titleClass?: string;
  children?: ReactNode;
}

export function Modal({
  open,
  onClose,
  dirty = false,
  serverErrors = null,
  title,
  noAnim = false,
  closable = true,
  width = "max-w-2xl",
  titleClass = "mb-4 text-lg font-semibold",
  children,
}: ModalProps) {
  const titleId = useId();
  const presence = usePresence(open);
  // Set when this pop-up has asked to close, so a second Escape or click before the parent re-renders does nothing.
  const closedRef = useRef(false);
  const downOnOverlay = useRef(false);
  // Set by any input or change event inside the panel (legacy modal.js rule). Cleared when the pop-up reopens.
  const [touched, setTouched] = useState(false);

  // A noAnim pop-up skips the exit (legacy rule: no exit for a noAnim shell). Presence plays the exit otherwise.
  const playsExit = !noAnim;
  const mounted = playsExit ? presence.mounted : open;
  const leaving = playsExit && presence.leaving;

  const dirtyNow = dirty || touched || hasServerErrors(serverErrors);

  const requestClose = (): void => {
    if (!closable) return;
    void tryClose(
      {
        dirty: dirtyNow,
        leaving: closedRef.current || leaving,
        close: () => {
          closedRef.current = true;
          onClose();
        },
      },
      (message) => confirm(message, { ok: "Хаах" }),
    );
  };

  // The Escape listener and the stack entry read these live, so they never act on the render they were set up in.
  // `leaving` is the exit that is actually playing. The closed mark is not an exit: a pop-up whose parent did not close
  // it must not block Escape for the pop-ups above it.
  const live = useRef({ requestClose, leaving: false, closable });
  live.current = { requestClose, leaving, closable };

  // Every render with open still true clears the closed mark. A parent that re-renders after a close request (or
  // reopens the pop-up) gets a working ✕ and Escape again.
  useEffect(() => {
    if (open) closedRef.current = false;
  });

  // Reopening clears the typed-input mark.
  useEffect(() => {
    if (open) setTouched(false);
  }, [open]);

  // While mounted (also while leaving), the pop-up is on the stack. Escape goes to the topmost one that is not leaving.
  useEffect(() => {
    if (!mounted) return;
    const entry: StackEntry = {
      get closable() {
        return live.current.closable;
      },
      get leaving() {
        return live.current.leaving;
      },
    };
    pushModal(entry);
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;  // an inner popup already used this Escape
      if (modalStack().some((s) => s.leaving)) return;  // an exit is under way: the next Escape waits for it
      // A non-closable top pop-up takes the Escape (requestClose does nothing), so it never reaches one below.
      if (pickEscapeTarget(modalStack()) !== entry) return;
      e.preventDefault();
      live.current.requestClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      popModal(entry);
    };
  }, [mounted]);

  if (!mounted) return null;

  // Outside click: the press and the release both have to be on the overlay itself.
  const onOverlayMouseDown = (e: MouseEvent<HTMLDivElement>) => {
    downOnOverlay.current = e.target === e.currentTarget;
  };
  const onOverlayClick = (e: MouseEvent<HTMLDivElement>) => {
    if (downOnOverlay.current && e.target === e.currentTarget) requestClose();
  };
  // The date picker and the select list keep their popups in document.body, but React events still bubble up to this
  // panel. Browsing them (a month change, a list scroll) is not typing, so only events outside those popups mark it.
  const markTouched = (e: SyntheticEvent<HTMLDivElement>) => {
    const target = e.target;
    if (target instanceof Element && target.closest(".dp-popup, .sel-popup")) return;
    setTouched(true);
  };

  return createPortal(
    <div
      ref={presence.ref}
      className={cn("fixed inset-0 z-50 flex items-center justify-center bg-black/40", noAnim && "no-anim")}
      data-leaving={leaving ? "" : undefined}
      inert={leaving}
      onMouseDown={onOverlayMouseDown}
      onClick={onOverlayClick}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        onInput={markTouched}
        onChange={markTouched}
        className={cn(
          "relative max-h-[90vh] w-full overflow-y-auto rounded-xl bg-surface p-6 shadow-xl",
          width,
        )}
      >
        {title ? (
          <h2 id={titleId} className={titleClass}>
            {title}
          </h2>
        ) : null}
        {children}
        {closable ? (
        <button
          type="button"
          data-modal-x=""
          aria-label="Хаах"
          title="Хаах (Esc)"
          onClick={requestClose}
          className="absolute top-3 right-3 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
        >
          <svg
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
