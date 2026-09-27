"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { isUnauthorizedError } from "@/lib/errors";
import { hardNavigate } from "@/lib/navigation";

export const SESSION_CHANGE_KEY = "opspilot.session-change";
export const SESSION_LOST_EVENT = "opspilot.session-lost";
const PUBLIC_PATHS = new Set(["/", "/login", "/register"]);
const SESSION_QUERY_KEY = ["session"];

type Actor = { user_id: string; org_id: string; role: string };

function isActor(value: unknown): value is Actor {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return typeof record.user_id === "string" && typeof record.org_id === "string" && typeof record.role === "string";
}

function createQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

export function Providers({ children, client: providedClient }: { children: ReactNode; client?: QueryClient }) {
  const [client] = useState(() => providedClient ?? createQueryClient());
  useEffect(() => {
    let previousActor = "";
    // Tenant data must never survive a change of user, organization or role.
    const unsubscribe = client.getQueryCache().subscribe(event => {
      if (event.type !== "updated" || event.query.queryKey[0] !== "session" || event.query.state.status !== "success") return;
      const session: unknown = event.query.state.data;
      if (!isActor(session)) return;
      const actor = `${session.user_id}:${session.org_id}:${session.role}`;
      if (previousActor && previousActor !== actor) {
        const protectedQueries = { predicate: (query: { queryKey: readonly unknown[] }) => query.queryKey[0] !== "session" };
        void client.cancelQueries(protectedQueries);
        client.removeQueries(protectedQueries);
      }
      previousActor = actor;
    });

    const sessionLost = () => {
      // On a public page a 401 only means "not signed in"; there is nothing to protect.
      if (PUBLIC_PATHS.has(window.location.pathname)) return;
      client.clear();
      hardNavigate("/login");
    };
    const sessionChanged = async (event: StorageEvent) => {
      if (event.key !== SESSION_CHANGE_KEY) return;
      // Another tab signed in, signed out or switched organization. Ask the API who
      // this tab is now; the actor subscription above purges data if that changed,
      // and only a rejected session sends this tab to sign in.
      await client.invalidateQueries({ queryKey: SESSION_QUERY_KEY });
      const state = client.getQueryState(SESSION_QUERY_KEY);
      if (state?.status === "error" && isUnauthorizedError(state.error)) sessionLost();
    };
    const onStorage = (event: StorageEvent) => { void sessionChanged(event); };
    window.addEventListener("storage", onStorage);
    window.addEventListener(SESSION_LOST_EVENT, sessionLost);
    return () => {
      unsubscribe();
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(SESSION_LOST_EVENT, sessionLost);
    };
  }, [client]);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
