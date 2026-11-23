import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useLocation } from "react-router";
import { api } from "../api/client";
import { AppLink } from "../lib/AppLink";
import { TLink } from "../lib/viewTransition";
import { ScrollFloat } from "../widgets/Scrollbar";
import { NavMenu, NavMenuProvider, type NavGroupData } from "./NavMenu";
import { usePalettePanel } from "./palette/PalettePanelContext";
import { ThemeMenu } from "./ThemeMenu";
import { UserMenu } from "./UserMenu";
import { useMeta } from "./useMeta";

// The top bar (base.html lines 25-58): brand, the nav strip, the search button, and the theme and user menus. The two
// menus are direct flex items of the nav, as in base.html, so each one takes the full bar height.
// The nav groups are re-fetched when the location changes.
function useNav(pathname: string) {
  // A user who must change the password has nothing else reachable, so the strip stays empty for them. The meta answer
  // comes first: until it does, the forced user is not yet known and no nav request is sent.
  const { data: meta } = useMeta();
  const forced = meta?.user?.must_change_password === true;
  return useQuery({
    queryKey: ["nav", pathname],
    enabled: meta !== undefined && !forced,
    queryFn: async (): Promise<NavGroupData[]> => {
      const { data, error, response } = await api.GET("/api/v1/nav", {
        params: { query: { path: pathname } },
      });
      const status = response.status;
      if (error || !data) {
        throw Object.assign(new Error("nav request failed"), { status });
      }
      return data;
    },
  });
}

export function TopBar() {
  const { pathname } = useLocation();
  const stripRef = useRef<HTMLDivElement>(null);
  const { data: groups } = useNav(pathname);
  const palette = usePalettePanel();

  // The active item scrolls into view after every page load (base.html line 88): once the strip has the groups for
  // the current location. A new location gives a new groups list, so the effect runs again for it.
  useEffect(() => {
    if (!groups || groups.length === 0) return;
    const active = stripRef.current?.querySelector<HTMLElement>(".border-violet-400");
    active?.scrollIntoView?.({ inline: "nearest", block: "nearest" });
  }, [groups, pathname]);

  return (
    <header className="sticky top-0 z-40 bg-slate-800 text-white shadow-sm">
      <NavMenuProvider stripRef={stripRef}>
        <nav className="flex flex-wrap items-stretch gap-1 px-4 text-sm sm:h-14 sm:flex-nowrap sm:px-6">
          <TLink
            to="/"
            className="mr-2 flex shrink-0 items-center whitespace-nowrap text-base font-extrabold tracking-tight max-sm:mr-auto max-sm:min-h-14 sm:mr-4 sm:text-lg"
          >
            MACS&nbsp;<span className="text-violet-300">Human Capital</span>
          </TLink>
          {/* The strip scrolls sideways: scrollbars.js gives every scroll box a float rail, so does this. */}
          <ScrollFloat
            data-nav=""
            boxRef={stripRef}
            className="flex min-w-0 flex-1 items-stretch gap-0.5 overflow-x-auto max-sm:order-last max-sm:h-11 max-sm:basis-full max-sm:border-t max-sm:border-white/10 xl:gap-1 [scrollbar-width:none]"
          >
            {(groups ?? []).map((group) =>
              group.items.length === 1 ? (
                <AppLink
                  key={group.key}
                  to={group.items[0].url}
                  aria-current={group.items[0].active ? "page" : undefined}
                  className={`flex shrink-0 items-center whitespace-nowrap border-b-2 px-2 hover:bg-white/10 hover:text-white xl:px-3 ${
                    group.items[0].active ? "border-violet-400 font-semibold text-white" : "border-transparent text-white/70"
                  }`}
                >
                  {group.items[0].label}
                  {group.items[0].badge ? (
                    <>
                      {" "}
                      <span className="ml-1 rounded-full bg-amber-400 px-1.5 text-xs font-semibold text-slate-900">
                        {group.items[0].badge}
                      </span>
                    </>
                  ) : null}
                </AppLink>
              ) : (
                <NavMenu key={group.key} group={group} />
              ),
            )}
          </ScrollFloat>
          <button
            type="button"
            data-palette-open=""
            aria-label="Хайх"
            onClick={palette.toggle}
            className="flex shrink-0 items-center gap-2 px-3 text-white/70 hover:bg-white/10 hover:text-white"
          >
            <svg
              viewBox="0 0 20 20"
              width="16"
              height="16"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              strokeLinecap="round"
              aria-hidden="true"
            >
              <circle cx="9" cy="9" r="5.5" />
              <path d="M13.2 13.2L17 17" />
            </svg>
            <span className="hidden lg:inline">Хайх</span>
            <kbd className="hidden text-xs text-white/50 xl:inline">Ctrl K</kbd>
          </button>
          <ThemeMenu />
          <UserMenu />
        </nav>
      </NavMenuProvider>
    </header>
  );
}
