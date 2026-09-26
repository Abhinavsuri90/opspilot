"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { api } from "@/lib/api";

export function useWorkspace() {
  const client = useQueryClient();
  const router = useRouter();
  const session = useQuery({ queryKey: ["session"], refetchInterval: 15000, queryFn: async () => {
    const result = await api.GET("/v1/auth/me");
    if (result.response.status === 401 || result.response.status === 403) throw new Error("Unauthorized");
    if (result.error || !result.data) throw new Error("Could not load your workspace. Please try again.");
    return result.data;
  } });
  useEffect(() => { if (session.error?.message === "Unauthorized") { client.clear(); router.replace("/login"); } }, [session.error, client, router]);
  return session;
}

export function useWorkspaceSummary(orgId?: string, userId?: string) {
  return useQuery({ queryKey: ["workspace-summary", orgId, userId], enabled: Boolean(orgId), queryFn: async () => {
    const result = await api.GET("/v1/workspace/summary");
    if (!result.data || result.error) throw new Error("Could not load workspace totals");
    return result.data;
  }, refetchInterval: 15000 });
}
