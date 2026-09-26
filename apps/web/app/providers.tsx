"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  useEffect(() => {
    let previousActor = "";
    const unsubscribe = client.getQueryCache().subscribe(event => {
      if (event.type !== "updated" || event.query.queryKey[0] !== "session" || event.query.state.status !== "success") return;
      const session = event.query.state.data as { user_id: string; org_id: string; role: string } | undefined;
      if (!session) return;
      const actor = `${session.user_id}:${session.org_id}:${session.role}`;
      if (previousActor && previousActor !== actor) {
        const protectedQueries = { predicate: (query: { queryKey: readonly unknown[] }) => query.queryKey[0] !== "session" };
        void client.cancelQueries(protectedQueries);
        client.removeQueries(protectedQueries);
      }
      previousActor = actor;
    });
    const reset = () => { client.clear(); window.location.replace("/login"); };
    const storage = (event: StorageEvent) => { if (event.key === "opspilot.session-change") reset(); };
    window.addEventListener("storage", storage);
    window.addEventListener("opspilot.session-lost", reset);
    return () => { unsubscribe(); window.removeEventListener("storage", storage); window.removeEventListener("opspilot.session-lost", reset); };
  }, [client]);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
