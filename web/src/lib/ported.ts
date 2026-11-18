// Paths the React app serves itself. Every other path is still served by Django, so a link to it is a full page load.
export const PORTED: RegExp[] = [
  /^\/$/,
  /^\/employees\/today\/$/,
  /^\/employees\/\d+\/$/,
  /^\/employees\/company\/$/,
  /^\/employees\/new\/$/,
  /^\/me\/$/,
  /^\/password\/change$/,
];

// True when the path (without query string or hash) is served by the React app.
export function isPorted(path: string): boolean {
  const pathname = path.split(/[?#]/)[0];
  return PORTED.some((pattern) => pattern.test(pathname));
}
