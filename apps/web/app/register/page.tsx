"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { PublicBrand } from "@/components/PublicBrand";
import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/errors";
import { firstIssueMessage, registrationSchema, templateOptions, type OrganizationTemplate, type Registration } from "@/lib/register";
import type { Session } from "@/lib/use-workspace";

type Mode = "create" | "join";
type RequestedRole = "member" | "reviewer";
type RegistrationResult =
  | { mode: "create"; session: Session }
  | { mode: "join"; orgName: string; slug: string };

export default function RegisterPage() {
  return <Suspense fallback={<main className="grid min-h-screen place-items-center bg-[#f9faf6]"><p role="status" className="text-sm font-semibold text-[#122f33]">Opening registration…</p></main>}><RegistrationEntry /></Suspense>;
}

function RegistrationEntry() {
  const searchParams = useSearchParams();
  const initialMode: Mode = searchParams.get("mode") === "join" ? "join" : "create";
  const initialRole: RequestedRole = initialMode === "join" && searchParams.get("role") === "reviewer" ? "reviewer" : "member";

  // Links select a form only. The API still creates pending memberships and
  // an organization administrator decides the approved role.
  return <RegistrationForm key={`${initialMode}:${initialRole}`} initialMode={initialMode} initialRole={initialRole} />;
}

function RegistrationForm({ initialMode, initialRole }: { initialMode: Mode; initialRole: RequestedRole }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [orgName, setOrgName] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [search, setSearch] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [template, setTemplate] = useState<OrganizationTemplate>("invoice");
  const [role, setRole] = useState<RequestedRole>(initialRole);
  const [showPassword, setShowPassword] = useState(false);
  const [validationError, setValidationError] = useState("");
  const [joined, setJoined] = useState<{ orgName: string; slug: string } | null>(null);

  useEffect(() => {
    const timeout = setTimeout(() => setSearch(orgSlug.trim()), 250);
    return () => clearTimeout(timeout);
  }, [orgSlug]);

  const organizations = useQuery({
    queryKey: ["organizations", search],
    enabled: mode === "join",
    queryFn: async () => {
      const result = await api.GET("/v1/organizations", { params: { query: { search } } });
      if (result.error || !result.data) throw new Error("Could not load organizations");
      return result.data;
    },
    staleTime: 30_000,
    retry: false,
  });

  const registration = useMutation({
    mutationFn: async (values: Registration): Promise<RegistrationResult> => {
      const identity = { org_slug: values.org_slug, email: values.email, password: values.password };
      if (values.mode === "create") {
        const result = await api.POST("/v1/auth/register-organization", {
          body: { ...identity, org_name: values.org_name, default_currency: values.default_currency, template: values.template },
        });
        if (result.error || !result.data) throw new Error(apiErrorMessage(result.error, result.response.status, "Could not create the organization. Please try again."));
        return { mode: "create", session: result.data };
      }
      const result = await api.POST("/v1/auth/join-organization", { body: { ...identity, requested_role: values.requested_role } });
      if (result.error || !result.data) throw new Error(apiErrorMessage(result.error, result.response.status, "Could not send your request. Please try again."));
      return { mode: "join", orgName: result.data.org_name, slug: values.org_slug };
    },
    // Side effects live here so a failed request can never half-apply them.
    onSuccess: result => {
      queryClient.clear();
      if (result.mode === "create") {
        queryClient.setQueryData(["session"], result.session);
        router.replace("/dashboard");
        return;
      }
      setJoined({ orgName: result.orgName, slug: result.slug });
      setPassword("");
      setConfirmation("");
    },
  });

  function changeMode(value: Mode) {
    if (value === mode) return;
    setMode(value);
    setOrgSlug("");
    setOrgName("");
    setSlugEdited(false);
    setValidationError("");
    registration.reset();
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (registration.isPending) return;
    registration.reset();
    setValidationError("");
    const parsed = registrationSchema.safeParse(mode === "create"
      ? { mode, org_name: orgName, org_slug: orgSlug, default_currency: currency, template, email, password, confirmation }
      : { mode, org_slug: orgSlug, requested_role: role, email, password, confirmation });
    if (!parsed.success) {
      setValidationError(firstIssueMessage(parsed.error));
      return;
    }
    registration.mutate(parsed.data);
  }

  return <main className="min-h-screen bg-[#f9faf6] lg:grid lg:grid-cols-[minmax(0,.85fr)_minmax(520px,1.15fr)]">
    <aside className="relative overflow-hidden bg-[#122f33] px-6 py-8 text-white sm:px-10 lg:flex lg:min-h-screen lg:flex-col lg:justify-between lg:px-12 lg:py-12 xl:px-16">
      <div aria-hidden="true" className="pointer-events-none absolute -left-20 top-1/3 h-80 w-80 rounded-full border-[50px] border-[#d3e8b8]/[.06]" />
      <PublicBrand light className="relative" />
      <div className="relative mt-8 max-w-lg lg:my-16">
        <p className="text-[11px] font-bold uppercase tracking-[.2em] text-[#d3e8b8]">A workspace that belongs to your team</p>
        <h1 className="mt-4 text-3xl font-bold leading-tight tracking-[-.04em] lg:text-5xl">Clear documents.<br />Clear ownership.</h1>
        <p className="mt-5 text-sm leading-7 text-[#c4d5ce] sm:text-base">Start an organization or request access to your team&apos;s workspace. Every invoice, comment, and review stays within the right organization.</p>
        <ol className="mt-9 hidden space-y-6 lg:block">
          {[['01', 'Set up your workspace', 'Choose a name, workspace ID, starting documents and reporting currency.'], ['02', 'Bring your people in', 'Your admin approves access and assigns each person a role.'], ['03', 'Work through invoices together', 'Upload, categorize, discuss, and review with a clear record.']].map(([number, title, description]) => <li key={number} className="flex gap-4"><span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-[#d3e8b8]/20 bg-[#d3e8b8]/10 text-xs font-bold text-[#d3e8b8]">{number}</span><div><p className="font-semibold">{title}</p><p className="mt-1 text-sm leading-6 text-[#b5ccc4]">{description}</p></div></li>)}
        </ol>
      </div>
      <p className="relative hidden text-xs text-[#b5ccc4] lg:block">Membership approval keeps workspace access in your hands.</p>
    </aside>

    <section className="flex items-center justify-center px-5 py-10 sm:px-10 lg:py-12">
      <div className="w-full max-w-xl">
        {joined ? <div className="card !border-[#dce5dc] !shadow-[0_12px_35px_#173b3c09] p-7 sm:p-10" role="status">
          <span aria-hidden="true" className="grid h-14 w-14 place-items-center rounded-2xl bg-amber-50 text-2xl text-amber-700">◷</span>
          <p className="mt-6 text-xs font-bold uppercase tracking-[.16em] text-amber-700">Request received</p>
          <h2 className="mt-2 text-3xl font-bold tracking-tight text-[#122f33]">Waiting for approval</h2>
          <p className="mt-4 text-sm leading-7 text-slate-600">Your request to join <strong className="text-slate-900">{joined.orgName}</strong> is pending. An organization admin must approve your account and role before you can enter the workspace.</p>
          <p className="mt-4 rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-600">Let your admin know you registered as <strong className="break-all text-slate-800">{email}</strong>. Once they approve you, sign in using your email, password, and workspace ID <strong className="text-slate-800">{joined.slug}</strong>.</p>
          <Link href={`/login?organization=${encodeURIComponent(joined.slug)}`} className="primary !border-[#006b60] !bg-[#006b60] !shadow-[0_5px_13px_#006b601c] hover:!bg-[#004e46] mt-6 w-full">Go to sign in →</Link>
        </div> : <>
          <p className="eyebrow !text-[#006b60]">Get started</p>
          <h2 className="mt-2 text-3xl font-bold tracking-[-.04em] text-[#122f33]">{mode === "create" ? "A home for your operations" : role === "reviewer" ? "Bring clarity to every review" : "Join your team’s workspace"}</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">{mode === "create" ? "Create your organization and invite your team to request access." : "Find your organization, choose your role, and request access."}</p>
          <div className="mt-6 grid grid-cols-2 gap-2 rounded-xl bg-[#e8eee3] p-1.5" role="group" aria-label="Registration type">
            <button type="button" aria-pressed={mode === "create"} disabled={registration.isPending} onClick={() => changeMode("create")} className={`rounded-lg px-3 py-3 text-sm font-semibold transition-colors ${mode === "create" ? "bg-white text-[#122f33] shadow-sm" : "text-slate-600 hover:bg-white/50"}`}>Create organization</button>
            <button type="button" aria-pressed={mode === "join"} disabled={registration.isPending} onClick={() => changeMode("join")} className={`rounded-lg px-3 py-3 text-sm font-semibold transition-colors ${mode === "join" ? "bg-white text-[#122f33] shadow-sm" : "text-slate-600 hover:bg-white/50"}`}>Join organization</button>
          </div>
          <form onSubmit={submit} className="card !border-[#dce5dc] !shadow-[0_12px_35px_#173b3c09] mt-5 space-y-5 p-6 sm:p-8">
            <div className="rounded-xl border border-[#dce5dc] bg-[#edf3e8] p-4">
              <p className="text-xs font-bold uppercase tracking-[.12em] text-[#006b60]">{mode === "create" ? "Organization administrator" : role === "reviewer" ? "Reviewer access request" : "Member access request"}</p>
              <p className="mt-2 text-sm leading-6 text-slate-600">{mode === "create" ? "You will be the administrator and can approve members, manage categories, and review invoices." : role === "reviewer" ? "Review invoice evidence, discuss corrections, and record decisions after an administrator approves your reviewer role." : "Upload invoices, follow their progress, and collaborate with your team after an administrator approves your membership."}</p>
            </div>
            {mode === "create" && <div><label htmlFor="org-name" className="mb-2 block text-sm font-semibold text-slate-700">Organization name</label><input id="org-name" className="field !border-[#ccd9cf] focus:!border-[#006b60] focus:!shadow-[0_0_0_4px_#006b601a]" autoComplete="organization" required minLength={2} maxLength={200} placeholder="Acme Operations" value={orgName} onChange={event => {
              const value = event.target.value;
              setOrgName(value);
              if (!slugEdited) setOrgSlug(value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80));
            }} /></div>}
            <div><label htmlFor="org-slug" className="mb-2 block text-sm font-semibold text-slate-700">{mode === "create" ? "Workspace ID" : "Organization"}</label><input id="org-slug" className="field !border-[#ccd9cf] focus:!border-[#006b60] focus:!shadow-[0_0_0_4px_#006b601a]" list={mode === "join" ? "join-organizations" : undefined} autoComplete="off" required maxLength={80} placeholder={mode === "create" ? "acme-operations" : "Search or enter a workspace ID"} aria-describedby="slug-help" value={orgSlug} onChange={event => { setOrgSlug(event.target.value); setSlugEdited(true); }} />
              {mode === "join" && <datalist id="join-organizations">{organizations.data?.map(org => <option key={org.id} value={org.slug}>{org.name}</option>)}</datalist>}
              <p id="slug-help" className="mt-2 text-xs leading-5 text-slate-500">{mode === "create" ? "A unique ID your team will use at sign in. Your organization name and ID appear in organization search." : organizations.isError ? "Search is unavailable. Enter the workspace ID your admin shared." : "Search by organization name or enter the workspace ID shared by your admin."}</p>
            </div>
            {mode === "create" && <fieldset>
              <legend className="mb-2 block text-sm font-semibold text-slate-700">Documents your workspace starts with</legend>
              <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Workflow template">
                {templateOptions.map(option => <label key={option.value} className={`flex cursor-pointer gap-3 rounded-xl border p-3 text-sm transition-colors ${template === option.value ? "border-[#006b60] bg-[#edf3e8] ring-1 ring-[#006b60]" : "border-[#dce5dc] hover:bg-[#f4f8f1]"}`}>
                  <input type="radio" name="template" value={option.value} checked={template === option.value} onChange={() => setTemplate(option.value)} disabled={registration.isPending} className="mt-1 accent-[#006b60]" />
                  <span><span className="block font-bold text-[#122f33]">{option.label}</span><span className="mt-0.5 block text-xs leading-5 text-slate-600">{option.description}</span></span>
                </label>)}
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-500">This becomes version 1 of your workflow configuration. Administrators can edit it, and add more document types, later.</p>
            </fieldset>}
            {mode === "create" ? <div><label htmlFor="currency" className="mb-2 block text-sm font-semibold text-slate-700">Default invoice currency</label><select id="currency" className="field !border-[#ccd9cf] focus:!border-[#006b60] focus:!shadow-[0_0_0_4px_#006b601a]" value={currency} onChange={event => setCurrency(event.target.value)}>{[["USD", "US dollar"], ["INR", "Indian rupee"], ["EUR", "Euro"], ["GBP", "British pound"], ["CAD", "Canadian dollar"], ["AUD", "Australian dollar"], ["SGD", "Singapore dollar"], ["AED", "UAE dirham"]].map(([code, label]) => <option key={code} value={code}>{code} · {label}</option>)}</select><p className="mt-2 text-xs leading-5 text-slate-500">Reviewers can set the correct currency on each invoice. Totals stay separate by currency.</p></div> : <div><label htmlFor="requested-role" className="mb-2 block text-sm font-semibold text-slate-700">Requested role</label><select id="requested-role" className="field !border-[#ccd9cf] focus:!border-[#006b60] focus:!shadow-[0_0_0_4px_#006b601a]" value={role} onChange={event => setRole(event.target.value as RequestedRole)}><option value="member">Member · upload and collaborate</option><option value="reviewer">Reviewer · review and approve invoices</option></select><p className="mt-2 text-xs leading-5 text-slate-500">Your admin confirms your role when approving your account.</p></div>}
            <div><label htmlFor="email" className="mb-2 block text-sm font-semibold text-slate-700">Email</label><input id="email" type="email" className="field !border-[#ccd9cf] focus:!border-[#006b60] focus:!shadow-[0_0_0_4px_#006b601a]" required maxLength={254} autoComplete="username" placeholder="you@company.com" value={email} onChange={event => setEmail(event.target.value)} /></div>
            <div><label htmlFor="password" className="mb-2 block text-sm font-semibold text-slate-700">Password</label><div className="relative"><input id="password" type={showPassword ? "text" : "password"} className="field !border-[#ccd9cf] focus:!border-[#006b60] focus:!shadow-[0_0_0_4px_#006b601a] pr-20" required minLength={12} maxLength={128} autoComplete="new-password" aria-describedby="password-help" value={password} onChange={event => setPassword(event.target.value)} /><button type="button" onClick={() => setShowPassword(value => !value)} className="absolute inset-y-0 right-2 px-2 text-xs font-bold text-[#006b60]" aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? "Hide" : "Show"}</button></div><p id="password-help" className="mt-2 text-xs leading-5 text-slate-500">12–128 characters with at least one letter and one number. If you already use OpsPilot in another organization, use your existing password.</p></div>
            <div><label htmlFor="confirm-password" className="mb-2 block text-sm font-semibold text-slate-700">Confirm password</label><input id="confirm-password" type={showPassword ? "text" : "password"} className="field !border-[#ccd9cf] focus:!border-[#006b60] focus:!shadow-[0_0_0_4px_#006b601a]" required maxLength={128} autoComplete="new-password" value={confirmation} onChange={event => setConfirmation(event.target.value)} /></div>
            {(validationError || registration.error) && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm leading-6 text-rose-800">{validationError || registration.error?.message}</p>}
            <button type="submit" disabled={registration.isPending} className="primary !border-[#006b60] !bg-[#006b60] !shadow-[0_5px_13px_#006b601c] hover:!bg-[#004e46] w-full">{registration.isPending ? mode === "create" ? "Creating workspace…" : "Sending request…" : mode === "create" ? "Create workspace" : "Request access"}<span aria-hidden="true">→</span></button>
          </form>
          <p className="mt-6 text-center text-sm text-slate-600">Already have access? <Link href="/login" className="font-semibold text-[#006b60] hover:underline">Sign in</Link></p>
        </>}
        <p className="mt-5 text-center"><Link href="/" className="text-xs font-semibold text-slate-500 hover:text-[#006b60]">← Back to OpsPilot</Link></p>
      </div>
    </section>
  </main>;
}
