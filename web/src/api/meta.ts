import { api, setCsrf } from "./client";

// The meta query options: company, modules, the CSRF token and the signed-in user. Kept in api/ so the mutation helper
// (api/mutate.ts) can refetch the same query without depending on the shell.
export const metaQueryOptions = {
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
};
