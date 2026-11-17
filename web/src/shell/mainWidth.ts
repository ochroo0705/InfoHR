import { createContext, useContext, useLayoutEffect } from "react";

// The width classes of the signed-in <main> (base.html default). A page that is narrower sets its own with
// useMainWidth (me.html: max-w-2xl px-4); AppShell reads the value and falls back to this default when no page sets one.
export const DEFAULT_MAIN_WIDTH = "max-w-6xl px-4";

export type MainWidthSetter = (classes: string | null) => void;

// The router is a BrowserRouter (main.tsx), so route handles (useMatches) are not available; a context is used instead.
export const MainWidthContext = createContext<MainWidthSetter>(() => {});

// Sets the <main> width while the calling page is mounted; the default comes back when it unmounts.
export function useMainWidth(classes: string): void {
  const setWidth = useContext(MainWidthContext);
  useLayoutEffect(() => {
    setWidth(classes);
    return () => setWidth(null);
  }, [setWidth, classes]);
}
