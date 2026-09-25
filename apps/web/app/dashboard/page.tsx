"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { api } from "@/lib/api";

const navigation = ["Dashboard", "Inbox", "Review", "Actions", "Settings"];

export default function DashboardPage() {
  const router = useRouter();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      const result = await api.GET("/v1/auth/me");
      if (result.error || !result.data) throw new Error("Unauthorized");
      return result.data;
    },
  });
  useEffect(() => { if (session.isError) router.replace("/login"); }, [session.isError, router]);

  async function signOut() {
    await api.POST("/v1/auth/logout");
    router.replace("/login");
  }

  if (!session.data) return <div className="p-8 text-slate-500" role="status">Loading workspace…</div>;

  return <div className="min-h-screen md:flex">
    <aside className="w-full border-b border-slate-200 bg-white p-5 md:min-h-screen md:w-64 md:border-b-0 md:border-r dark:bg-slate-900 dark:border-slate-700">
      <div className="mb-9 flex items-center gap-3"><span className="grid h-9 w-9 place-items-center rounded-lg bg-blue-900 text-white font-bold">O</span><strong className="text-xl">OpsPilot</strong></div>
      <nav aria-label="Main navigation" className="space-y-1">
        {navigation.map(item => <span key={item} className={`nav-link ${item === "Dashboard" ? "active" : "opacity-60"}`}>{item}</span>)}
      </nav>
      <div className="mt-10 border-t border-slate-200 pt-5 text-sm dark:border-slate-700">
        <p className="font-semibold">{session.data.org_name}</p>
        <p className="mt-1 text-slate-500">{session.data.email}</p>
        <p className="mt-1 capitalize text-slate-500">{session.data.role}</p>
        <button onClick={signOut} className="mt-4 text-blue-700 hover:underline dark:text-blue-300">Sign out</button>
      </div>
    </aside>
    <main className="flex-1 p-6 md:p-10">
      <div className="mb-8"><p className="text-sm font-semibold uppercase tracking-wider text-blue-700 dark:text-blue-300">Overview</p><h1 className="mt-2 text-3xl font-bold">Dashboard</h1><p className="mt-2 text-slate-500">Your document operations at a glance.</p></div>
      <section className="card max-w-3xl p-8">
        <div className="mb-5 grid h-12 w-12 place-items-center rounded-xl bg-blue-50 text-2xl text-blue-800 dark:bg-slate-700">▣</div>
        <h2 className="text-xl font-semibold">Your workspace is ready</h2>
        <p className="mt-3 max-w-xl leading-7 text-slate-500">Document intake, extraction, review, and governed actions will appear here as they are built in the next phases. No activity has been recorded yet.</p>
      </section>
    </main>
  </div>;
}
