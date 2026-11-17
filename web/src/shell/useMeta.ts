import { useQuery } from "@tanstack/react-query";
import { metaQueryOptions } from "../api/meta";

// The meta query: company, modules, the CSRF token and the signed-in user (null when nobody is signed in).
// The SPA reads it before anything else; the answer is fresh for a minute. A failed request throws an Error that
// carries the HTTP status, so the shell can tell an offline server from a server error.
export function useMeta() {
  return useQuery(metaQueryOptions);
}
