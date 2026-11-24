// The requests list's URL state. `tab=mine` is the default and is left out of the address; any other tab value reads as
// mine (Django's default). The status is kept as typed: the server decides what an unknown value matches.
export type RequestTab = "mine" | "all";

export interface RequestParams {
  tab: RequestTab;
  status: string;
}

// The address as the requests list reads it. A missing, empty or junk tab is the mine tab.
export function parseRequestParams(search: URLSearchParams): RequestParams {
  return {
    tab: search.get("tab") === "all" ? "all" : "mine",
    status: search.get("status") ?? "",
  };
}

// The query string for the requests list's address: the mine tab and an empty status are left out.
export function toSearch(params: RequestParams): URLSearchParams {
  const search = new URLSearchParams();
  if (params.tab === "all") search.append("tab", "all");
  if (params.status) search.append("status", params.status);
  return search;
}
