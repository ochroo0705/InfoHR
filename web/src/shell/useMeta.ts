import { useQuery } from "@tanstack/react-query";
import { api, setCsrf } from "../api/client";

// The meta query: company, modules, the CSRF token and the signed-in user (null when nobody is signed in).
// The SPA reads it before anything else; the answer is fresh for a minute. A failed request throws an Error that
// carries the HTTP status, so the shell can tell an offline server from a server error.
export function useMeta() {
  return useQuery({
    queryKey: ["meta"],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/meta");
      const status = response.status;
      if (error || !data) {
        throw Object.assign(new Error("meta request failed"), { status });
      }
      // Set the token before the data reaches any component, so the first render already has it.
      setCsrf(data.csrf);
      return data;
    },
    staleTime: 60_000,
  });
}
