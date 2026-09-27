"use client";

import { isUnauthorizedError } from "@/lib/errors";

type SessionState = { isError: boolean; error: unknown; refetch: () => unknown };

/**
 * What a protected page shows before it has a session. An unauthorized answer is
 * never shown as an error: the redirect to sign in is already on its way.
 */
export function SessionFallback({ session }: { session: SessionState }) {
  if (session.isError && !isUnauthorizedError(session.error)) {
    return <main className="p-8">
      <p role="alert">Could not load your workspace.</p>
      <button type="button" onClick={() => session.refetch()} className="primary mt-4">Try again</button>
    </main>;
  }
  return <main className="p-8 text-slate-500" role="status">Checking your session…</main>;
}
