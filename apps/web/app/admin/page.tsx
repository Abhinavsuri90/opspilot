"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { AppShell } from "@/components/AppShell";
import { api } from "@/lib/api";

export default function AdminPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      const result = await api.GET("/v1/auth/me");
      if (result.response.status === 401) throw new Error("Unauthorized");
      if (result.error || !result.data) throw new Error("Could not load your workspace");
      return result.data;
    },
  });
  const isAdmin = session.data?.role === "admin";
  const members = useQuery({
    queryKey: ["members", session.data?.org_id],
    enabled: isAdmin,
    queryFn: async () => {
      const result = await api.GET("/v1/organization/members");
      if (result.response.status === 401) throw new Error("Unauthorized");
      if (result.response.status === 403) throw new Error("Forbidden");
      if (result.error || !result.data) throw new Error("Could not load members");
      return result.data;
    },
  });
  const documents = useQuery({
    queryKey: ["documents", session.data?.org_id],
    enabled: isAdmin,
    queryFn: async () => {
      const result = await api.GET("/v1/documents");
      if (result.response.status === 401) throw new Error("Unauthorized");
      if (result.error || !result.data) throw new Error("Could not load documents");
      return result.data;
    },
  });

  useEffect(() => {
    if ([session.error, members.error, documents.error].some(error => error?.message === "Unauthorized")) {
      queryClient.clear();
      router.replace("/login");
    }
  }, [session.error, members.error, documents.error, queryClient, router]);

  if ([session.error, members.error, documents.error].some(error => error?.message === "Unauthorized")) return <main className="p-8 text-slate-500" role="status">Checking your session…</main>;
  if (session.isError) return <main className="p-8"><p role="alert">Could not load your workspace.</p><button type="button" onClick={() => session.refetch()} className="primary mt-4">Try again</button></main>;
  if (!session.data) return <main className="p-8 text-slate-500" role="status">Loading workspace…</main>;

  if (!isAdmin || members.error?.message === "Forbidden") return <AppShell session={session.data} active="admin">
    <section className="mx-auto mt-12 max-w-xl rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
      <span aria-hidden="true" className="grid h-11 w-11 place-items-center rounded-xl bg-amber-50 text-xl text-amber-700">⊘</span>
      <h1 className="mt-5 text-2xl font-bold tracking-[-.03em] text-[#12233d]">Admin access required</h1>
      <p className="mt-2 text-sm leading-6 text-slate-600">Only workspace administrators can view the member directory.</p>
      <Link href="/dashboard" className="mt-5 inline-block text-sm font-semibold text-[#11627a] hover:underline">Return to dashboard →</Link>
    </section>
  </AppShell>;

  const roster = [...(members.data ?? [])].sort((a, b) => a.email.localeCompare(b.email));
  const recent = documents.data ?? [];
  const admins = roster.filter(member => member.role === "admin").length;
  const review = recent.filter(item => item.status === "needs_review").length;

  return <AppShell session={session.data} active="admin">
    <div className="mb-7">
      <p className="text-[11px] font-bold uppercase tracking-[.18em] text-cyan-700">Organization</p>
      <h1 className="mt-2 text-3xl font-bold tracking-[-.04em] text-[#12233d] sm:text-[38px]">Admin</h1>
      <p className="mt-2 text-sm leading-6 text-slate-600">View your workspace members and a snapshot of recent invoice activity.</p>
    </div>

    <section aria-label="Organization overview" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <div className="rounded-2xl border border-slate-200/80 bg-[#123757] p-5 text-white shadow-[0_8px_24px_rgba(18,55,87,.1)]">
        <p className="text-xs font-semibold text-cyan-100">Workspace</p>
        <p className="mt-4 truncate text-xl font-bold tracking-[-.03em]" title={session.data.org_name}>{session.data.org_name}</p>
        <p className="mt-2 text-xs text-slate-200">Your organization</p>
      </div>
      <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_6px_20px_rgba(15,23,42,.035)]">
        <p className="text-xs font-semibold text-slate-600">Members</p>
        <p className="mt-3 text-[31px] font-bold leading-none tracking-[-.04em] text-[#12233d]">{!members.data ? <span className="text-slate-300">—</span> : roster.length}</p>
        <p className="mt-2 text-xs text-slate-500">{!members.data ? "Directory unavailable" : `${admins} administrator${admins === 1 ? "" : "s"}`}</p>
      </div>
      <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_6px_20px_rgba(15,23,42,.035)]">
        <p className="text-xs font-semibold text-slate-600">Recent documents</p>
        <p className="mt-3 text-[31px] font-bold leading-none tracking-[-.04em] text-[#12233d]">{!documents.data ? <span className="text-slate-300">—</span> : recent.length}</p>
        <p className="mt-2 text-xs text-slate-500">Latest 50 shown</p>
      </div>
      <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_6px_20px_rgba(15,23,42,.035)]">
        <p className="text-xs font-semibold text-slate-600">Needs review</p>
        <p className="mt-3 text-[31px] font-bold leading-none tracking-[-.04em] text-[#12233d]">{!documents.data ? <span className="text-slate-300">—</span> : review}</p>
        <p className="mt-2 text-xs text-slate-500">In recent documents</p>
      </div>
    </section>

    <section aria-labelledby="members-heading" className="mt-6 overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-[0_6px_20px_rgba(15,23,42,.035)]">
      <div className="border-b border-slate-100 px-5 py-5 sm:px-6">
        <h2 id="members-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Member directory</h2>
        <p className="mt-1 text-xs text-slate-500">Read-only list of people with access to this organization.</p>
      </div>
      {members.isPending && <p role="status" className="px-6 py-10 text-center text-sm text-slate-500">Loading members…</p>}
      {members.isError && <p role="alert" className="px-6 py-8 text-sm text-rose-800">Could not load members. <button type="button" onClick={() => members.refetch()} className="font-semibold underline">Try again</button></p>}
      {members.isSuccess && roster.length === 0 && <p className="px-6 py-8 text-sm text-slate-500">No members found.</p>}
      {members.isSuccess && roster.length > 0 && <div className="divide-y divide-slate-100">
        {roster.map(member => <div key={member.user_id} className="flex min-w-0 items-center gap-3 px-5 py-4 sm:px-6">
          <span aria-hidden="true" className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#e6f3f6] text-xs font-bold text-[#12617b]">{member.email.slice(0, 2).toUpperCase()}</span>
          <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold text-slate-800">{member.email}{member.user_id === session.data.user_id && <span className="ml-2 text-xs font-normal text-slate-500">(you)</span>}</p><p className="mt-0.5 text-xs text-slate-500">Workspace member</p></div>
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold capitalize text-slate-700">{member.role}</span>
        </div>)}
      </div>}
    </section>

    <section aria-labelledby="roles-heading" className="mt-6 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_6px_20px_rgba(15,23,42,.035)] sm:p-6">
      <h2 id="roles-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Access by role</h2>
      <p className="mt-1 text-xs text-slate-500">Current permissions in this version of OpsPilot.</p>
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="text-sm font-bold text-slate-800">Admin</p><p className="mt-1 text-xs leading-5 text-slate-600">View members and documents; upload invoices and retry failed extraction.</p></div>
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="text-sm font-bold text-slate-800">Reviewer</p><p className="mt-1 text-xs leading-5 text-slate-600">View documents; upload invoices and retry failed extraction.</p></div>
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="text-sm font-bold text-slate-800">Viewer</p><p className="mt-1 text-xs leading-5 text-slate-600">View documents and extracted fields.</p></div>
      </div>
    </section>
  </AppShell>;
}
