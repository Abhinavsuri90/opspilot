"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const navigation = ["Dashboard", "Inbox", "Review", "Actions", "Settings"];

export default function DashboardPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [logoutError, setLogoutError] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);
  const session = useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      const result = await api.GET("/v1/auth/me");
      if (result.response.status === 401) throw new Error("Unauthorized");
      if (result.error || !result.data) throw new Error("Could not load your workspace");
      return result.data;
    },
  });
  useEffect(() => {
    if (session.error?.message === "Unauthorized") router.replace("/login");
  }, [session.error, router]);

  async function signOut() {
    setLoggingOut(true);
    setLogoutError("");
    try {
      const result = await api.POST("/v1/auth/logout");
      if (result.error || result.response.status !== 204) throw new Error("Logout failed");
      queryClient.clear();
      router.replace("/login");
    } catch {
      setLogoutError("Could not sign out. Please try again.");
      setLoggingOut(false);
    }
  }

  if (session.isError && session.error?.message !== "Unauthorized") {
    return <main className="p-8">
      <p role="alert">Could not load your workspace.</p>
      <button onClick={() => session.refetch()} className="mt-4 primary">Try again</button>
    </main>;
  }
  if (!session.data) return <div className="p-8 text-slate-500" role="status">Loading workspace…</div>;

  return <div className="min-h-screen md:flex">
    <aside className="w-full border-b border-slate-200 bg-white p-5 md:min-h-screen md:w-64 md:border-b-0 md:border-r dark:bg-slate-900 dark:border-slate-700">
      <div className="mb-9 flex items-center gap-3"><span className="grid h-9 w-9 place-items-center rounded-lg bg-blue-900 text-white font-bold">O</span><strong className="text-xl">OpsPilot</strong></div>
      <nav aria-label="Main navigation" className="space-y-1">
        {navigation.map(item => item === "Dashboard" || item === "Inbox"
          ? <Link key={item} href={item === "Dashboard" ? "/dashboard" : "/inbox"} className={`nav-link ${item === "Dashboard" ? "active" : ""}`}>{item}</Link>
          : <span key={item} className="nav-link opacity-60">{item}</span>)}
      </nav>
      <div className="mt-10 border-t border-slate-200 pt-5 text-sm dark:border-slate-700">
        <p className="font-semibold">{session.data.org_name}</p>
        <p className="mt-1 text-slate-500">{session.data.email}</p>
        <p className="mt-1 capitalize text-slate-500">{session.data.role}</p>
        {logoutError && <p role="alert" className="mt-4 text-red-700">{logoutError}</p>}
        <button onClick={signOut} disabled={loggingOut} className="mt-4 text-blue-700 hover:underline dark:text-blue-300">{loggingOut ? "Signing out…" : "Sign out"}</button>
      </div>
    </aside>
    <main className="flex-1 p-6 md:p-10">
      <div className="mb-8"><p className="text-sm font-semibold uppercase tracking-wider text-blue-700 dark:text-blue-300">Overview</p><h1 className="mt-2 text-3xl font-bold">Dashboard</h1><p className="mt-2 text-slate-500">Your document operations at a glance.</p></div>
      <section className="card max-w-3xl p-8">
        <div className="mb-5 grid h-12 w-12 place-items-center rounded-xl bg-blue-50 text-2xl text-blue-800 dark:bg-slate-700">▣</div>
        <h2 className="text-xl font-semibold">Your workspace is ready</h2>
        <p className="mt-3 max-w-xl leading-7 text-slate-600 dark:text-slate-300">Upload a text-layer invoice to see tenant-isolated intake and evidence-backed field extraction. Human review and governed actions are still being built.</p>
        <Link href="/inbox" className="mt-5 inline-block text-blue-700 hover:underline">Open inbox →</Link>
      </section>
    </main>
  </div>;
}
