"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { isUnauthorizedStatus, unauthorizedError } from "@/lib/errors";
import { POLICIES_QUERY_KEY, type PoliciesResponse } from "@/lib/policies";
import type { Session } from "@/lib/use-workspace";

export function policiesQueryKey(session: Pick<Session, "org_id" | "user_id"> | undefined) {
  return [POLICIES_QUERY_KEY, session?.org_id, session?.user_id] as const;
}

export async function fetchPolicies(): Promise<PoliciesResponse> {
  const result = await api.GET("/v1/settings/policies");
  if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
  if (result.error || !result.data) throw new Error("Could not load the agent policies.");
  return result.data;
}

/**
 * The organization's agent switches and policies. Only administrators may read
 * them, so the query is idle for everyone else; the shell and the settings page
 * share this cache entry, which is why a saved switch shows in the banner at once.
 */
export function usePolicies(session: Session | undefined, options: { refetchInterval?: number | false } = {}): UseQueryResult<PoliciesResponse> {
  return useQuery({
    queryKey: policiesQueryKey(session),
    enabled: session?.role === "admin",
    queryFn: fetchPolicies,
    refetchInterval: options.refetchInterval ?? 15_000,
    staleTime: 5_000,
  });
}
