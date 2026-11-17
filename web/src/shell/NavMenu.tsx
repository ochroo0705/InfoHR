import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
  type RefObject,
} from "react";
import type { components } from "../api/schema";
import { usePresence } from "../lib/presence";
import { cn } from "../lib/utils";
import { TLink } from "../lib/viewTransition";
import { closeAll, closeMenu, finishClose, menuOf, openMenu, pickOpenMenu, type MenuMap } from "./navLogic";
import { NavIcon } from "./NavIcon";

// Port of the top bar drop-downs (base.html, details[data-nav-menu]; behaviour from app/static/js/nav.js). The menus
// share one state in NavMenuProvider, so only one is open at a time. An outside click, Escape, scrolling the strip
// and resizing the window close them.
//
// DropMenu is the shared base. NavMenu (the strip groups) uses the strip placement with hover. The theme and user
// menus (ThemeMenu, UserMenu) use the corner placement, and they open on hover as well as on click.

export type NavItemData = components["schemas"]["NavItemOut"];
export type NavGroupData = components["schemas"]["NavGroupOut"];

type Controls = {
  state: MenuMap;
  open: (id: string) => void;
  close: (id: string) => void;
  finish: (id: string, exit: number | null) => void;
  // The summary buttons by menu id, so Escape can give focus back to the one it closed.
  triggers: RefObject<Map<string, HTMLButtonElement>>;
};

const NavMenuContext = createContext<Controls | null>(null);

// Hover behaviour is for a mouse with a fine pointer only (nav.js, the `hover` media query).
function hoverMode(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(hover: hover) and (pointer: fine)").matches
  );
}

export function NavMenuProvider({
  stripRef,
  children,
}: {
  stripRef: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  const [state, setState] = useState<MenuMap>({});
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);
  const triggers = useRef(new Map<string, HTMLButtonElement>());

  const controls = useMemo<Controls>(
    () => ({
      state,
      open: (id) => setState((s) => openMenu(s, id)),
      close: (id) => setState((s) => closeMenu(s, id)),
      finish: (id, exit) => setState((s) => finishClose(s, id, exit)),
      triggers,
    }),
    [state],
  );

  // The global closers: outside click, Escape (capture, so the activity drawer does not also close), the strip's
  // sideways scroll and a window resize.
  useEffect(() => {
    const onClick = (e: Event) => {
      const target = e.target;
      if (!(target instanceof Element) || !target.closest("[data-nav-menu]")) {
        setState((s) => closeAll(s));
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const id = pickOpenMenu(stateRef.current);
      if (id === null) return;
      setState((s) => closeMenu(s, id));
      triggers.current.get(id)?.focus();
      e.stopPropagation();
    };
    const onResize = () => setState((s) => closeAll(s));
    const onScroll = () => setState((s) => closeAll(s));
    const strip = stripRef.current;
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", onResize);
    strip?.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("resize", onResize);
      strip?.removeEventListener("scroll", onScroll);
    };
  }, [stripRef]);

  return <NavMenuContext.Provider value={controls}>{children}</NavMenuContext.Provider>;
}

function useControls(): Controls {
  const ctx = useContext(NavMenuContext);
  if (!ctx) throw new Error("NavMenu must be rendered inside NavMenuProvider");
  return ctx;
}

type DropMenuProps = {
  // Unique among the open menus. The strip groups use their group key.
  id: string;
  // strip: fixed under the bar, moved left at the window's edge. corner: absolute at the bar's right edge.
  placement: "strip" | "corner";
  // Whether a mouse hover opens the menu. The strip groups, the theme menu and the user menu have it.
  hover: boolean;
  panelWidth: string;
  panelLabel?: string;
  // The summary's accessible name, when its content is not text (the theme icon, the user's avatar).
  ariaLabel?: string;
  // Classes for the summary button, on top of the shared base. Open-state colours are added here.
  triggerClassName: string;
  trigger: ReactNode;
  children: ReactNode;
};

export function DropMenu({
  id,
  placement,
  hover,
  panelWidth,
  panelLabel,
  ariaLabel,
  triggerClassName,
  trigger,
  children,
}: DropMenuProps) {
  const ctl = useControls();
  const menu = menuOf(ctl.state, id);
  // The panel stays mounted through its exit: it is open, or leaving.
  const presence = usePresence(menu.open && !menu.leaving);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const hoverTimer = useRef(0);

  const setPanel = useCallback(
    (el: HTMLDivElement | null) => {
      presence.ref(el);
      panelRef.current = el;
    },
    [presence.ref],
  );

  // When the exit is over (the panel is gone), the menu closes for real. A stale exit does nothing (finishClose).
  useEffect(() => {
    if (menu.leaving && !presence.mounted) ctl.finish(id, menu.exit);
  }, [menu.leaving, menu.exit, presence.mounted, ctl, id]);

  // A strip panel is position: fixed. When it would run past the window's right edge it moves left (nav.js).
  useLayoutEffect(() => {
    const el = panelRef.current;
    if (!el || !menu.open || placement !== "strip") return;
    el.style.left = "";
    const box = el.getBoundingClientRect();
    if (box.right > window.innerWidth - 8) {
      el.style.left = `${Math.max(8, window.innerWidth - box.width - 8)}px`;
    }
  }, [menu.open, presence.mounted, placement]);

  useEffect(() => () => window.clearTimeout(hoverTimer.current), []);

  function later(open: boolean, ms: number) {
    window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(() => {
      if (open) ctl.open(id);
      else ctl.close(id);
    }, ms);
  }

  function onSummaryClick(e: MouseEvent<HTMLButtonElement>) {
    window.clearTimeout(hoverTimer.current);
    if (!menu.open) {
      ctl.open(id);
      return;
    }
    // A mouse click on a menu the hover has opened keeps it open (nav.js); any other click toggles it.
    if (hover && !menu.leaving && hoverMode() && e.detail > 0) return;
    if (menu.leaving) ctl.open(id);
    else ctl.close(id);
  }

  function onPanelClick(e: MouseEvent<HTMLDivElement>) {
    // Following a link in the menu closes the menu, because the page changes under it.
    if (e.target instanceof Element && e.target.closest("a")) ctl.close(id);
  }

  return (
    <div
      data-nav-menu
      className={cn("flex shrink-0 items-stretch", placement === "corner" && "relative")}
      onMouseEnter={
        hover
          ? () => {
              if (hoverMode()) later(true, 60);
            }
          : undefined
      }
      onMouseLeave={
        hover
          ? () => {
              if (hoverMode()) later(false, 200);
            }
          : undefined
      }
    >
      <button
        type="button"
        data-nav-trigger={id}
        aria-label={ariaLabel}
        aria-expanded={menu.open}
        onClick={onSummaryClick}
        ref={(el) => {
          if (el) ctl.triggers.current?.set(id, el);
          else ctl.triggers.current?.delete(id);
        }}
        className={cn(
          "flex h-full list-none items-center gap-1 whitespace-nowrap hover:bg-white/10 hover:text-white",
          triggerClassName,
          menu.open && "bg-white/10 text-white",
        )}
      >
        {trigger}
        <svg
          viewBox="0 0 20 20"
          width="14"
          height="14"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          className={cn("opacity-70 transition-transform", menu.open && "rotate-180")}
        >
          <path d="M6 8l4 4 4-4" />
        </svg>
      </button>
      {presence.mounted ? (
        <div
          ref={setPanel}
          data-nav-panel
          data-leaving={presence.leaving ? "" : undefined}
          inert={presence.leaving}
          role={panelLabel ? "group" : undefined}
          aria-label={panelLabel}
          onClick={onPanelClick}
          className={cn(
            "nav-panel z-50 mt-1.5 p-1.5 text-slate-700 [animation:pal-in_.12s_ease-out]",
            placement === "strip" ? "fixed top-14" : "absolute right-2 top-full",
            panelWidth,
          )}
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}

export function NavMenu({ group }: { group: NavGroupData }) {
  return (
    <DropMenu
      id={group.key}
      placement="strip"
      hover
      panelWidth="w-72"
      triggerClassName={cn(
        "border-b-2 px-2 xl:px-3",
        group.active ? "border-violet-400 font-semibold text-white" : "border-transparent text-white/70",
      )}
      trigger={
        <>
          {group.label}
          {group.badge ? (
            <>
              {" "}
              <span className="ml-1 rounded-full bg-amber-400 px-1.5 text-xs font-semibold text-slate-900">{group.badge}</span>
            </>
          ) : null}
        </>
      }
    >
      {group.items.map((item, i) => (
        <PanelRow key={`${item.url}-${i}`} item={item} />
      ))}
    </DropMenu>
  );
}

function PanelRow({ item }: { item: NavItemData }) {
  const current = item.active ? "page" : undefined;
  return (
    <>
      {item.section ? (
        <p className="mt-1.5 border-t border-slate-200 px-2.5 pb-1 pt-2 text-xs font-medium text-slate-500">
          {item.section}
        </p>
      ) : null}
      {item.compact ? (
        <TLink
          to={item.url}
          aria-current={current}
          className={cn(
            "block rounded-lg px-2.5 py-1.5 text-sm hover:bg-slate-50",
            item.active ? "bg-violet-50 font-medium text-violet-700 hover:bg-violet-50" : "text-slate-700",
          )}
        >
          {item.label}
        </TLink>
      ) : (
        <TLink
          to={item.url}
          aria-current={current}
          className={cn(
            "flex items-center gap-3 rounded-lg px-2.5 py-2 hover:bg-slate-50",
            item.active && "bg-violet-50 hover:bg-violet-50",
          )}
        >
          <NavIcon kind={item.icon} />
          <span className="min-w-0 flex-1">
            <span className={cn("flex items-center gap-2 font-medium", item.active ? "text-violet-700" : "text-slate-800")}>
              {item.label}
              {item.badge ? (
                <span className="rounded-full bg-amber-400 px-1.5 text-xs font-semibold text-slate-900">{item.badge}</span>
              ) : null}
            </span>
            {item.hint ? <span className="block truncate text-xs text-slate-500">{item.hint}</span> : null}
          </span>
        </TLink>
      )}
    </>
  );
}
