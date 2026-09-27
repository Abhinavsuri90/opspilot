"use client";

import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { isUnauthorizedError, isUnauthorizedStatus, unauthorizedError } from "@/lib/errors";
import type { components } from "@/lib/schema";

export type Session = components["schemas"]["SessionResponse"];
export type WorkspaceSummary = components["schemas"]["WorkspaceSummary"];

export const SESSION_QUERY_KEY = ["session"] as const;

export async function fetchSession(): Promise<Session> {
  const result = await api.GET("/v1/auth/me");
  if (isUnauthorizedStatus(result.response.status)) throw unauthorizedError();
  if (result.error || !result.data) throw new Error("Could not load your workspace. Please try again.");
  return result.data;
}

// One definition so every page shares the same cache entry, polling and staleness.
export const sessionQueryOptions = {
  queryKey: SESSION_QUERY_KEY,
  queryFn: fetchSession,
  refetchInterval: 15_000,
  retry: false,
  staleTime: 5_000,
} as const;

export function useSession(overrides: { refetchInterval?: number | false } = {}): UseQueryResult<Session> {
  return useQuery({ ...sessionQueryOptions, ...overrides });
}

/** The session for a protected page: sends the visitor to sign in when the API no longer recognizes them. */
export function useWorkspace(): UseQueryResult<Session> {
  const client = useQueryClient();
  const router = useRouter();
  const session = useSession();
  useEffect(() => {
    if (isUnauthorizedError(session.error)) {
      client.clear();
      router.replace("/login");
    }
  }, [session.error, client, router]);
  return session;
}

export function useWorkspaceSummary(orgId?: string, userId?: string, options: { refetchInterval?: number } = {}): UseQueryResult<WorkspaceSummary> {
  return useQuery({
    queryKey: ["workspace-summary", orgId, userId],
    enabled: Boolean(orgId),
    queryFn: async () => {
      const result = await api.GET("/v1/workspace/summary");
      if (!result.data || result.error) throw new Error("Could not load workspace totals");
      return result.data;
    },
    refetchInterval: options.refetchInterval ?? 15_000,
  });
}
