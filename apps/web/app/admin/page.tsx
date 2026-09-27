"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { AppShell } from "@/components/AppShell";
import { SessionFallback } from "@/components/SessionFallback";
import { api } from "@/lib/api";
import { apiErrorMessage, isUnauthorizedError, unauthorizedError } from "@/lib/errors";
import type { components } from "@/lib/schema";
import { useWorkspace } from "@/lib/use-workspace";

type Role = "member" | "reviewer" | "viewer";
type Decision = "approved" | "rejected" | "suspended";
type Member = components["schemas"]["MemberResponse"];
type Category = components["schemas"]["CategoryResponse"];
type CategoryValues = { name?: string; description?: string; active?: boolean };

function assignableRole(value: string): Role {
  return value === "reviewer" || value === "viewer" ? value : "member";
}

function MemberRow({ member, currentUser, saving, onDecision }: {
  member: Member; currentUser: string; saving: boolean;
  onDecision: (userId: string, decision: Decision, role?: Role) => void;
}) {
  const [role, setRole] = useState<Role>(assignableRole(member.status === "pending" ? member.requested_role : member.role));
  // Removing access is confirmed in place; nothing leaves the row until confirmed.
  const [confirming, setConfirming] = useState<"reject" | "suspend" | null>(null);
  const active = member.status === "active";
  const pending = member.status === "pending";
  const statusStyle = pending ? "bg-amber-50 text-amber-800 ring-amber-200" : active ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-slate-100 text-slate-600 ring-slate-200";
  useEffect(() => {
    setRole(assignableRole(member.status === "pending" ? member.requested_role : member.role));
    setConfirming(null);
  }, [member.status, member.role, member.requested_role]);

  return <li className="px-5 py-5 sm:px-6">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex min-w-0 max-w-full gap-3">
        <span aria-hidden="true" className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#e6f3f6] text-xs font-bold text-[#12617b]">{member.email.slice(0, 2).toUpperCase()}</span>
        <div className="min-w-0"><p className="break-all text-sm font-semibold text-slate-800">{member.email}{member.user_id === currentUser && <span className="ml-2 font-normal text-slate-500">(you)</span>}</p><div className="mt-2 flex flex-wrap items-center gap-2"><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize ring-1 ${statusStyle}`}>{active ? "Active" : member.status}</span><span className="text-xs capitalize text-slate-500">{pending ? `Requested ${member.requested_role || "member"}` : member.role}</span></div></div>
      </div>
      {member.role === "admin" ? <span className="rounded-lg bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500">Administrator · protected</span> : <div className="flex max-w-full flex-wrap items-center gap-2">
        <select aria-label={`Role for ${member.email}`} className="field !w-auto !px-3 !py-2 text-sm" value={role} disabled={saving} onChange={event => setRole(event.target.value as Role)}><option value="member">Member</option><option value="reviewer">Reviewer</option><option value="viewer">Viewer</option></select>
        <button type="button" disabled={saving || (active && role === member.role)} className="secondary !min-h-10 !px-3 !text-xs" onClick={() => onDecision(member.user_id, "approved", role)}>{saving ? "Saving…" : pending ? "Approve access" : active ? "Save role" : "Restore access"}</button>
        {pending && confirming !== "reject" && <button type="button" disabled={saving} className="min-h-10 rounded-lg px-3 text-xs font-semibold text-rose-700 hover:bg-rose-50" onClick={() => setConfirming("reject")}>Reject</button>}
        {active && confirming !== "suspend" && <button type="button" disabled={saving} className="min-h-10 rounded-lg px-3 text-xs font-semibold text-rose-700 hover:bg-rose-50" onClick={() => setConfirming("suspend")}>Suspend</button>}
      </div>}
    </div>
    {confirming === "suspend" && <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-3"><p className="text-xs leading-5 text-rose-800">This person will lose access immediately, including existing sessions. You can restore access later.</p><div className="flex gap-2"><button type="button" disabled={saving} className="rounded-lg bg-rose-700 px-3 py-2 text-xs font-semibold text-white" onClick={() => onDecision(member.user_id, "suspended")}>Confirm suspension</button><button type="button" className="rounded-lg px-3 py-2 text-xs font-semibold text-slate-600" onClick={() => setConfirming(null)}>Cancel</button></div></div>}
    {confirming === "reject" && <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-3"><p className="text-xs leading-5 text-rose-800">This request will be declined and {member.email} will not be able to sign in. You can approve the account later from inactive accounts.</p><div className="flex gap-2"><button type="button" disabled={saving} className="rounded-lg bg-rose-700 px-3 py-2 text-xs font-semibold text-white" onClick={() => onDecision(member.user_id, "rejected")}>Confirm rejection</button><button type="button" className="rounded-lg px-3 py-2 text-xs font-semibold text-slate-600" onClick={() => setConfirming(null)}>Cancel</button></div></div>}
  </li>;
}

function CategoryRow({ category, saving, onSave }: { category: Category; saving: boolean; onSave: (category: Category, values: CategoryValues) => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(category.name);
  const [description, setDescription] = useState(category.description);
  useEffect(() => { setName(category.name); setDescription(category.description); setEditing(false); }, [category.name, category.description, category.version]);
  return <li className="px-5 py-4 sm:px-6">
    {editing ? <form className="space-y-3" onSubmit={event => { event.preventDefault(); if (name.trim()) onSave(category, { name: name.trim(), description: description.trim() }); }}>
      <label className="block text-xs font-semibold text-slate-600" htmlFor={`category-name-${category.id}`}>Category name</label><input id={`category-name-${category.id}`} className="field" value={name} onChange={event => setName(event.target.value)} required maxLength={80} />
      <label className="block text-xs font-semibold text-slate-600" htmlFor={`category-description-${category.id}`}>Description</label><input id={`category-description-${category.id}`} className="field" value={description} onChange={event => setDescription(event.target.value)} maxLength={500} />
      <div className="flex gap-2"><button type="submit" className="secondary !text-xs" disabled={saving || !name.trim()}>{saving ? "Saving…" : "Save category"}</button><button type="button" className="px-3 text-xs font-semibold text-slate-500" disabled={saving} onClick={() => { setEditing(false); setName(category.name); setDescription(category.description); }}>Cancel</button></div>
    </form> : <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><p className="break-words text-sm font-semibold text-slate-800">{category.name}</p>{!category.active && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">Archived</span>}</div><p className="mt-1 break-words text-xs leading-5 text-slate-500">{category.description || "No description"}</p></div>
      <div className="flex shrink-0 items-center gap-2"><button type="button" disabled={saving} className="secondary !min-h-9 !px-3 !py-2 !text-xs" onClick={() => setEditing(true)}>Edit</button><button type="button" disabled={saving} className="min-h-9 rounded-lg px-3 text-xs font-semibold text-slate-600 hover:bg-slate-100" onClick={() => onSave(category, { active: !category.active })}>{saving ? "Saving…" : category.active ? "Archive" : "Restore"}</button></div>
    </div>}
  </li>;
}

export default function AdminPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"members" | "categories">("members");
  const [memberFilter, setMemberFilter] = useState<"all" | "pending" | "active" | "inactive">("all");
  const [memberSearch, setMemberSearch] = useState("");
  const [categoryName, setCategoryName] = useState("");
  const [categoryDescription, setCategoryDescription] = useState("");
  const [notice, setNotice] = useState("");
  const [copied, setCopied] = useState(false);
  const session = useWorkspace();
  const isAdmin = session.data?.role === "admin";
  const members = useQuery({
    queryKey: ["members", session.data?.org_id, session.data?.user_id], enabled: isAdmin,
    queryFn: async () => {
      const result = await api.GET("/v1/organization/members");
      if (result.response.status === 401) throw unauthorizedError();
      if (result.response.status === 403) throw new Error("Forbidden");
      if (result.error || !result.data) throw new Error("Could not load members");
      return result.data;
    }, refetchInterval: 15_000,
  });
  const categories = useQuery({ queryKey: ["categories", session.data?.org_id, session.data?.user_id], enabled: isAdmin, queryFn: async () => {
    const result = await api.GET("/v1/categories");
    if (result.response.status === 401) throw unauthorizedError();
    if (result.response.status === 403) throw new Error("Forbidden");
    if (result.error || !result.data) throw new Error("Could not load categories");
    return result.data;
  } });
  const decision = useMutation({
    mutationFn: async (values: { userId: string; decision: Decision; role?: Role }) => {
      const result = await api.POST("/v1/organization/members/{user_id}/decision", { params: { path: { user_id: values.userId } }, body: { decision: values.decision, ...(values.role ? { role: values.role } : {}) } });
      if (result.response.status === 401) throw unauthorizedError();
      if (result.error || !result.data) throw new Error(apiErrorMessage(result.error, result.response.status, "Could not update this member. Please try again."));
      return result.data;
    }, onSuccess: async member => {
      setNotice(`Access updated for ${member.email}.`);
      await queryClient.invalidateQueries({ queryKey: ["members", session.data?.org_id, session.data?.user_id] });
    },
  });
  const createCategory = useMutation({
    mutationFn: async () => {
      const result = await api.POST("/v1/categories", { body: { name: categoryName.trim(), description: categoryDescription.trim() } });
      if (result.response.status === 401) throw unauthorizedError();
      if (result.error || !result.data) throw new Error(apiErrorMessage(result.error, result.response.status, "Could not create the category. Please try again."));
      return result.data;
    }, onSuccess: async category => {
      setCategoryName(""); setCategoryDescription(""); setNotice(`Category “${category.name}” created.`);
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
    },
  });
  const updateCategory = useMutation({
    mutationFn: async ({ category, values }: { category: Category; values: CategoryValues }) => {
      const result = await api.POST("/v1/categories/{category_id}", { params: { path: { category_id: category.id } }, body: { version: category.version, ...values } });
      if (result.response.status === 401) throw unauthorizedError();
      if (result.error || !result.data) {
        const status = result.response.status;
        if (status === 409) await queryClient.invalidateQueries({ queryKey: ["categories"] });
        throw new Error(apiErrorMessage(result.error, status, status === 409 ? "This category changed. Review the refreshed values and try again." : "Could not update the category. Please try again."));
      }
      return result.data;
    }, onSuccess: async category => {
      setNotice(`Category “${category.name}” updated.`);
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
      await queryClient.invalidateQueries({ queryKey: ["documents", session.data?.user_id, session.data?.org_id] });
    },
  });
  const unauthorized = [members.error, categories.error, decision.error, createCategory.error, updateCategory.error].some(isUnauthorizedError);
  useEffect(() => { if (unauthorized) { queryClient.clear(); router.replace("/login"); } }, [unauthorized, queryClient, router]);
  // The settings navigation deep-links to a tab: /admin?tab=categories.
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("tab");
    if (requested === "categories" || requested === "members") setTab(requested);
  }, []);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copyWorkspace() {
    if (!session.data) return;
    try { await navigator.clipboard.writeText(session.data.org_slug); setCopied(true); }
    catch { setNotice(`Share this workspace ID with your team: ${session.data.org_slug}`); }
  }
  function addCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (categoryName.trim() && !createCategory.isPending) { setNotice(""); createCategory.mutate(); }
  }

  if (session.isError || !session.data || unauthorized) return <SessionFallback session={session} />;
  if (!isAdmin || members.error?.message === "Forbidden" || categories.error?.message === "Forbidden") return <AppShell session={session.data} active="admin"><section className="mx-auto mt-12 max-w-xl rounded-2xl border border-slate-200 bg-white p-8 shadow-sm"><span aria-hidden="true" className="grid h-11 w-11 place-items-center rounded-xl bg-amber-50 text-xl text-amber-700">⊘</span><h1 className="mt-5 text-2xl font-bold tracking-[-.03em] text-[#12233d]">Admin access required</h1><p className="mt-2 text-sm leading-6 text-slate-600">Only organization administrators can approve accounts, change member roles, and manage invoice categories.</p><Link href="/dashboard" className="mt-5 inline-block text-sm font-semibold text-[#11627a] hover:underline">Return to dashboard →</Link></section></AppShell>;

  const roster = [...(members.data ?? [])].sort((a, b) => a.status === "pending" && b.status !== "pending" ? -1 : b.status === "pending" && a.status !== "pending" ? 1 : a.email.localeCompare(b.email));
  const pendingCount = roster.filter(member => member.status === "pending").length;
  const visibleMembers = roster.filter(member => (memberFilter === "all" || (memberFilter === "inactive" ? member.status === "rejected" || member.status === "suspended" : member.status === memberFilter)) && member.email.toLowerCase().includes(memberSearch.toLowerCase().trim()));
  const categoryList = [...(categories.data ?? [])].sort((a, b) => Number(b.active) - Number(a.active) || a.name.localeCompare(b.name));

  return <AppShell session={session.data} active="admin">
    <div className="mb-7"><p className="text-[11px] font-bold uppercase tracking-[.18em] text-cyan-700">Organization control</p><h1 className="mt-2 text-3xl font-bold tracking-[-.04em] text-[#12233d] sm:text-[38px]">Admin</h1><p className="mt-2 text-sm leading-6 text-slate-600">Approve your team, set the right access, and keep invoice categories consistent.</p></div>
    <section aria-label="Organization overview" className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <div className="rounded-2xl bg-[#123757] p-5 text-white shadow-sm"><p className="text-xs font-semibold text-cyan-100">Workspace</p><p className="mt-3 truncate text-xl font-bold tracking-[-.03em]" title={session.data.org_name}>{session.data.org_name}</p><div className="mt-3 flex items-center justify-between gap-2"><span className="truncate text-xs text-slate-200">{session.data.org_slug}</span><button type="button" className="shrink-0 rounded-md border border-white/20 px-2 py-1 text-xs text-white hover:bg-white/10" onClick={copyWorkspace}>{copied ? "Copied" : "Copy ID"}</button></div></div>
      <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm"><p className="text-xs font-semibold text-slate-600">Active members</p><p className="mt-3 text-[31px] font-bold leading-none tracking-[-.04em] text-[#12233d]">{members.data ? roster.filter(member => member.status === "active").length : "—"}</p><p className="mt-3 text-xs text-slate-500">People with workspace access</p></div>
      <button type="button" onClick={() => { setTab("members"); setMemberFilter("pending"); }} className="rounded-2xl border border-amber-200/80 bg-amber-50/60 p-5 text-left shadow-sm transition-colors hover:bg-amber-50"><p className="text-xs font-semibold text-amber-800">Pending requests</p><p className="mt-3 text-[31px] font-bold leading-none tracking-[-.04em] text-[#12233d]">{members.data ? pendingCount : "—"}</p><p className="mt-3 text-xs text-amber-800">Review access requests →</p></button>
      <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm"><p className="text-xs font-semibold text-slate-600">Active categories</p><p className="mt-3 text-[31px] font-bold leading-none tracking-[-.04em] text-[#12233d]">{categories.data ? categoryList.filter(category => category.active).length : "—"}</p><p className="mt-3 text-xs text-slate-500">Default currency: {session.data.default_currency}</p></div>
    </section>
    <div className="mt-7 flex gap-1 border-b border-slate-200" role="tablist" aria-label="Organization administration">{[{ id: "members", label: "People & access" }, { id: "categories", label: "Invoice categories" }].map(item => <button key={item.id} id={`tab-${item.id}`} type="button" role="tab" tabIndex={tab === item.id ? 0 : -1} aria-selected={tab === item.id} aria-controls={`panel-${item.id}`} onKeyDown={event => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) { event.preventDefault(); const next = event.key === "Home" ? "members" : event.key === "End" ? "categories" : tab === "members" ? "categories" : "members"; setTab(next); setNotice(""); document.getElementById(`tab-${next}`)?.focus(); } }} onClick={() => { setTab(item.id as "members" | "categories"); setNotice(""); }} className={`border-b-2 px-4 py-3 text-sm font-semibold ${tab === item.id ? "border-[#11627a] text-[#11627a]" : "border-transparent text-slate-500 hover:text-slate-800"}`}>{item.label}{item.id === "members" && pendingCount > 0 && <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-800">{pendingCount}</span>}</button>)}</div>
    {notice && <p role="status" className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</p>}

    {tab === "members" && <section id="panel-members" role="tabpanel" aria-labelledby="tab-members" className="mt-5">
      <div className="mb-5 rounded-xl border border-cyan-200 bg-cyan-50/60 px-5 py-4"><h2 className="text-sm font-semibold text-[#123757]">Bring your team into {session.data.org_name}</h2><p className="mt-1 text-sm leading-6 text-slate-600">Ask them to open <Link href="/register" className="font-semibold text-[#11627a] underline">Create or join an organization</Link>, choose <strong>Join organization</strong>, and enter <strong>{session.data.org_slug}</strong>. Their accounts stay pending until you approve them here. Confirm the person&apos;s identity before granting access.</p></div>
      {decision.error && !isUnauthorizedError(decision.error) && <p role="alert" className="mb-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{decision.error.message}</p>}
      <div role="region" aria-label="Member directory" className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm">
        <div className="flex flex-col justify-between gap-4 border-b border-slate-100 px-5 py-5 sm:px-6 xl:flex-row xl:items-center"><div><h2 className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Member directory</h2><p className="mt-1 text-xs text-slate-500">Manage requests and existing accounts. Refreshes every 15 seconds.</p></div><div className="flex flex-wrap gap-2"><input aria-label="Search members" className="field !w-auto min-w-0 flex-1 !py-2 !text-sm" type="search" placeholder="Search by email" value={memberSearch} onChange={event => setMemberSearch(event.target.value)} /><select aria-label="Filter members" className="field !w-auto !py-2 !text-sm" value={memberFilter} onChange={event => setMemberFilter(event.target.value as typeof memberFilter)}><option value="all">All accounts</option><option value="pending">Pending requests</option><option value="active">Active members</option><option value="inactive">Inactive accounts</option></select></div></div>
        {members.isPending && <p role="status" className="px-6 py-10 text-center text-sm text-slate-500">Loading members…</p>}
        {members.isError && <p role="alert" className="px-6 py-8 text-sm text-rose-800">Could not load members. <button type="button" onClick={() => members.refetch()} className="font-semibold underline">Try again</button></p>}
        {members.isSuccess && visibleMembers.length === 0 && <div className="px-6 py-10 text-center"><p className="font-semibold text-slate-700">{memberFilter === "pending" ? "No pending requests" : "No matching accounts"}</p><p className="mt-2 text-sm text-slate-500">{memberFilter === "pending" ? "New requests appear here for your approval." : "Try a different search or account filter."}</p></div>}
        {members.isSuccess && visibleMembers.length > 0 && <ul className="divide-y divide-slate-100">{visibleMembers.map(member => <MemberRow key={member.user_id} member={member} currentUser={session.data.user_id} saving={decision.isPending} onDecision={(userId, value, role) => { setNotice(""); decision.mutate({ userId, decision: value, role }); }} />)}</ul>}
      </div>
      <section aria-labelledby="roles-heading" className="mt-6 rounded-2xl border border-slate-200/80 bg-white p-5 sm:p-6"><h2 id="roles-heading" className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Choose the right level of access</h2><div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">{[['Admin', 'Approves members, manages categories and sharing, assigns reviewers, and reviews invoices.'], ['Reviewer', 'Uploads invoices, verifies fields, and approves or rejects invoices assigned to them or awaiting a reviewer.'], ['Member', 'Uploads invoices, views accessible documents, adds comments, and manages sharing on their own invoices.'], ['Viewer', 'Reads accessible invoices, evidence, discussions, and summaries. Cannot upload, comment, or review.']].map(([role, description]) => <div key={role} className="rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="text-sm font-bold text-slate-800">{role}</p><p className="mt-2 text-xs leading-5 text-slate-600">{description}</p></div>)}</div><p className="mt-4 text-xs leading-5 text-slate-500">Workspace invoices are visible to approved members. Restricted invoices are visible only to their uploader, administrators, the assigned reviewer, and people granted access. Rejected and suspended accounts cannot enter the workspace.</p></section>
    </section>}

    {tab === "categories" && <section id="panel-categories" role="tabpanel" aria-labelledby="tab-categories" className="mt-5 grid min-w-0 grid-cols-1 items-start gap-5 xl:grid-cols-[minmax(280px,.7fr)_minmax(0,1.3fr)]">
      <form onSubmit={addCategory} className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm sm:p-6"><h2 className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Create a category</h2><p className="mt-2 text-xs leading-6 text-slate-500">Give reviewers consistent choices such as Office supplies, Logistics, or Software.</p><div className="mt-5"><label htmlFor="new-category-name" className="mb-2 block text-sm font-semibold text-slate-700">Category name</label><input id="new-category-name" className="field" required maxLength={80} placeholder="Office supplies" value={categoryName} onChange={event => setCategoryName(event.target.value)} /></div><div className="mt-4"><label htmlFor="new-category-description" className="mb-2 block text-sm font-semibold text-slate-700">Description <span className="font-normal text-slate-400">(optional)</span></label><textarea id="new-category-description" className="field min-h-24 resize-y" maxLength={500} placeholder="When should your team use this category?" value={categoryDescription} onChange={event => setCategoryDescription(event.target.value)} /></div>{createCategory.error && <p role="alert" className="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{createCategory.error.message}</p>}<button type="submit" disabled={createCategory.isPending || !categoryName.trim()} className="primary mt-5 w-full">{createCategory.isPending ? "Creating…" : "Create category"}</button></form>
      <div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm"><div className="border-b border-slate-100 px-5 py-5 sm:px-6"><h2 className="text-lg font-bold tracking-[-.02em] text-[#12233d]">Invoice categories</h2><p className="mt-1 text-xs leading-5 text-slate-500">Archive a category to stop new assignments. Existing invoices keep their category.</p></div>
        {updateCategory.error && <p role="alert" className="m-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{updateCategory.error.message}</p>}
        {categories.isPending && <p role="status" className="px-6 py-10 text-center text-sm text-slate-500">Loading categories…</p>}
        {categories.isError && <p role="alert" className="px-6 py-8 text-sm text-rose-800">Could not load categories. <button type="button" onClick={() => categories.refetch()} className="font-semibold underline">Try again</button></p>}
        {categories.isSuccess && categoryList.length === 0 && <div className="px-6 py-10 text-center"><p className="font-semibold text-slate-700">Start with your first category</p><p className="mt-2 text-sm leading-6 text-slate-500">Create categories that match how your organization tracks invoice spending.</p></div>}
        {categoryList.length > 0 && <ul className="divide-y divide-slate-100">{categoryList.map(category => <CategoryRow key={category.id} category={category} saving={updateCategory.isPending} onSave={(item, values) => { setNotice(""); updateCategory.mutate({ category: item, values }); }} />)}</ul>}
      </div>
    </section>}
  </AppShell>;
}
