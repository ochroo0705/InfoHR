import type { AnchorHTMLAttributes, ReactNode } from "react";
import { isPorted } from "./ported";
import { TLink } from "./viewTransition";

// Fragment-only, query-only, and absolute targets (http:, mailto:, //host) are not paths on the Django site, so they
// keep their href as written.
const NOT_A_PATH = /^([a-z][a-z0-9+.-]*:|\/\/)/i;

function isPlainHref(to: string): boolean {
  return to.startsWith("#") || to.startsWith("?") || NOT_A_PATH.test(to);
}

// Origin of the Django site while the React dev server runs on another port. Empty in production, where both share
// one origin. Set by web/vite.config.ts from DJANGO_URL in serve mode, or by VITE_LEGACY_ORIGIN.
export function legacyOrigin(): string {
  return import.meta.env.VITE_LEGACY_ORIGIN ?? "";
}

type AppLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  to: string;
  children: ReactNode;
};

// Ported paths use the router (client-side, with the page cross-fade). Other paths are a full page load into Django.
export function AppLink({ to, className, children, ...rest }: AppLinkProps) {
  if (isPlainHref(to)) {
    return (
      <a {...rest} href={to} className={className}>
        {children}
      </a>
    );
  }
  if (isPorted(to)) {
    return (
      <TLink
        {...rest}
        to={to}
        className={className}
        aria-current={rest["aria-current"] === "page" ? "page" : undefined}
      >
        {children}
      </TLink>
    );
  }
  return (
    <a {...rest} href={legacyOrigin() + to} className={className}>
      {children}
    </a>
  );
}

// Opens the Django employee page for writes (ruling D2): a full page load, no fetch. Step 3b wires the pop-ups on the
// React side.
export function openLegacyEmployee(pk: number): void {
  window.location.href = legacyOrigin() + "/employees/" + pk + "/";
}
