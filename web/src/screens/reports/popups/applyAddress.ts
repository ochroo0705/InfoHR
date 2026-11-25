// The address a pop-up's Apply navigates to: the report's path, then the pop-up's `keep` pairs (the viewer's cleaned
// address minus the part the pop-up owns), then the pop-up's own pairs (cols, group, rules, ...). This is the GET the
// Django pop-up form makes. An own pair with an empty value is omitted, so the parameter is absent, not empty. Each
// name and value is percent-encoded; repeated keys keep their order. The server is the only parser of the address.

export function applyAddress(reportKey: string, keep: [string, string][], own: [string, string][]): string {
  const pair = ([name, value]: [string, string]): string => `${encodeURIComponent(name)}=${encodeURIComponent(value)}`;
  const parts = [...keep.map(pair), ...own.filter(([, value]) => value !== "").map(pair)];
  const search = parts.length > 0 ? `?${parts.join("&")}` : "";
  return `/reports/${reportKey}/${search}`;
}
