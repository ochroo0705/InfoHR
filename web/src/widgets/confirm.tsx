import { useCallback, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { usePresence } from "../lib/presence";
import { popModal, pushModal, type StackEntry } from "./modalLogic";

// The in-app confirm (port of window.hrConfirm, app/static/js/modal.js; UI_RULES §6). It replaces the browser's own
// box. Escape, an outside click or «Болих» resolve false; «Тийм» (or opts.ok) resolves true. Focus starts on the
// cancel button, so a stray Enter keeps the user's work. It sits at z-70, above the pop-ups, and plays the pop-up exit.

export interface ConfirmOptions {
  ok?: string;
  cancel?: string;
  // Accepted so callers written against modal.js keep working, but it has NO visual effect. modal.js documents
  // `danger` and never styles it, so the port matches that: every OK button looks the same.
  danger?: boolean;
}

type Pending = {
  message: string;
  opts: ConfirmOptions;
  opener: HTMLElement | null;
  resolve: (ok: boolean) => void;
};

// The provider registers its opener here. confirm() needs no hook, so any module (Modal.tsx, a page) can call it.
let bridge: ((message: string, opts: ConfirmOptions) => Promise<boolean>) | null = null;

export function confirm(message: string, opts: ConfirmOptions = {}): Promise<boolean> {
  if (!bridge) {
    // Without a ConfirmProvider nothing can be shown. Resolving false keeps the user's work (the safe answer).
    console.warn("confirm() called without a ConfirmProvider; answering no.");
    return Promise.resolve(false);
  }
  return bridge(message, opts);
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);
  const pendingRef = useRef<Pending | null>(null);

  const answer = useCallback((ok: boolean) => {
    const current = pendingRef.current;
    if (!current) return;
    pendingRef.current = null;
    setPending(null);
    if (current.opener && current.opener.isConnected) current.opener.focus();
    current.resolve(ok);
  }, []);

  useEffect(() => {
    const mine: (message: string, opts: ConfirmOptions) => Promise<boolean> = (message, opts) =>
      new Promise<boolean>((resolve) => {
        const previous = pendingRef.current;
        // A second question replaces the first one, which is answered no.
        const opener = previous ? previous.opener : document.activeElement instanceof HTMLElement ? document.activeElement : null;
        if (previous) previous.resolve(false);
        const next: Pending = { message, opts, opener, resolve };
        pendingRef.current = next;
        setPending(next);
      });
    bridge = mine;
    return () => {
      // Clear the module bridge only if it is still ours. A newer provider may have taken it since.
      if (bridge === mine) bridge = null;
      const current = pendingRef.current;
      pendingRef.current = null;
      if (current) current.resolve(false);
    };
  }, []);

  return (
    <>
      {children}
      <ConfirmDialog pending={pending} onAnswer={answer} />
    </>
  );
}

function ConfirmDialog({ pending, onAnswer }: { pending: Pending | null; onAnswer: (ok: boolean) => void }) {
  const open = pending !== null;
  const presence = usePresence(open);
  // The last question stays on screen while its exit plays, so the text does not vanish mid-animation.
  const [shown, setShown] = useState<Pending | null>(pending);
  if (pending && pending !== shown) setShown(pending);

  const cancelRef = useRef<HTMLButtonElement>(null);
  const okRef = useRef<HTMLButtonElement>(null);
  const downOnOverlay = useRef(false);

  // While the question is on the screen (also while its exit plays) it is on the pop-up stack, so the palette's Ctrl+K and
  // Escape see an open pop-up and stay away from it.
  // `leaving` is read live, so a pop-up underneath ignores Escape while this question's exit plays.
  const leavingRef = useRef(false);
  leavingRef.current = presence.leaving;
  useEffect(() => {
    if (!presence.mounted) return;
    const entry: StackEntry = {
      closable: true,
      get leaving() {
        return leavingRef.current;
      },
    };
    pushModal(entry);
    return () => popModal(entry);
  }, [presence.mounted]);

  // Focus starts on cancel once the dialog is mounted (the mount can come a render after open turns true). A replaced
  // question (a new `pending`) starts on cancel again, too.
  useEffect(() => {
    if (open && presence.mounted) cancelRef.current?.focus();
  }, [open, presence.mounted, pending]);

  // Capture phase: this runs before the pop-up's own Escape listener, and stopImmediatePropagation keeps the pop-up
  // underneath from closing with the same key.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopImmediatePropagation();
        onAnswer(false);
      } else if (e.key === "Tab") {
        // Focus stays between the two buttons.
        e.preventDefault();
        const next = document.activeElement === cancelRef.current ? okRef.current : cancelRef.current;
        next?.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [open, onAnswer]);

  if (!presence.mounted || !shown) return null;
  const leaving = presence.leaving;

  // A drag that starts inside the panel and ends on the overlay does not count as an outside click.
  const onOverlayMouseDown = (e: MouseEvent<HTMLDivElement>) => {
    downOnOverlay.current = e.target === e.currentTarget;
  };
  const onOverlayClick = (e: MouseEvent<HTMLDivElement>) => {
    if (downOnOverlay.current && e.target === e.currentTarget) onAnswer(false);
  };

  return createPortal(
    <div
      ref={presence.ref}
      role="alertdialog"
      aria-modal="true"
      aria-label={shown.message}
      className="hr-confirm fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-4"
      data-leaving={leaving ? "" : undefined}
      inert={leaving}
      onMouseDown={onOverlayMouseDown}
      onClick={onOverlayClick}
    >
      <div className="hr-confirm-panel">
        <p className="hr-confirm-text">{shown.message}</p>
        <div className="hr-confirm-row">
          <button ref={cancelRef} type="button" className="hr-confirm-no" onClick={() => onAnswer(false)}>
            {shown.opts.cancel || "Болих"}
          </button>
          <button
            ref={okRef}
            type="button"
            className="hr-confirm-yes"
            onClick={() => onAnswer(true)}
          >
            {shown.opts.ok || "Тийм"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
