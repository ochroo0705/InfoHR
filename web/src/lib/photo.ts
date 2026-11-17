import { legacyOrigin } from "./AppLink";

// The employee photo is served by Django (same origin in production). In dev the React server is on another port, so
// a path gets the Django origin. Shared by the rail and the header.
export function photoSrc(url: string): string {
  return url.startsWith("/") ? legacyOrigin() + url : url;
}

// `photo_srcset` is "<url> 2x, <url> 3x": each candidate's URL gets the same origin as `src`. Undefined when empty.
export function photoSrcSet(srcset: string): string | undefined {
  if (!srcset) return undefined;
  return srcset
    .split(",")
    .map((candidate) => {
      const [url, descriptor] = candidate.trim().split(/\s+/);
      return descriptor ? `${photoSrc(url)} ${descriptor}` : photoSrc(url);
    })
    .join(", ");
}
