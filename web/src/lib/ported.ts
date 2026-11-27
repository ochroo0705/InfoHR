// Paths the React app serves itself. Every other path is still served by Django, so a link to it is a full page load.
export const PORTED: RegExp[] = [
  /^\/$/,
  /^\/employees\/today\/$/,
  /^\/employees\/\d+\/$/,
  /^\/employees\/company\/$/,
  /^\/employees\/orders\/$/,
  /^\/employees\/orders\/print\/$/,
  /^\/employees\/new\/$/,
  /^\/me\/$/,
  /^\/password\/change$/,
  /^\/welcome\/?$/,
  /^\/employees\/slots\/$/,
  /^\/employees\/self-forms\/$/,
  /^\/employees\/self-forms\/\d+\/$/,
  /^\/logs\/$/,
  /^\/logs\/system\/$/,
  /^\/lists\/$/,
  /^\/lists\/meaning\/$/,
  /^\/lists\/[^/]+\/$/,
  /^\/checklists\/mine\/$/,
  /^\/leave\/$/,
  /^\/leave\/requests\/$/,
  /^\/leave\/balances\/$/,
  /^\/leave\/calendar\/$/,
  /^\/leave\/holidays\/$/,
  /^\/leave\/settings\/$/,
  /^\/recruitment\/$/,
  /^\/recruitment\/vacancies\/\d+\/$/,
  /^\/recruitment\/candidates\/\d+\/$/,
  /^\/recruitment\/purge\/$/,
  /^\/reports\/$/,
  /^\/reports\/[^/]+\/print\/$/,
];

// True when the path (without query string or hash) is served by the React app.
export function isPorted(path: string): boolean {
  const pathname = path.split(/[?#]/)[0];
  return PORTED.some((pattern) => pattern.test(pathname));
}
