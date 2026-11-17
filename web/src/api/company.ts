import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import { retryMe } from "./me";
import { unwrapQuery } from "./mutate";
import type { components } from "./schema";

export type CompanyPageOut = components["schemas"]["CompanyPageOut"];

// The company figures page («Компанийн байдал»). 403 without the employee-list right, as the Django page.
export function useCompany() {
  return useQuery({
    queryKey: ["company"],
    retry: retryMe,
    queryFn: async () => {
      const result = await api.GET("/api/v1/company");
      return unwrapQuery<CompanyPageOut>(result, "company request failed");
    },
  });
}
