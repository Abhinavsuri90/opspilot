"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/lib/api";

type Mode = "create" | "join";

function requestError(value: unknown, fallback: string) {
  if (value && typeof value === "object" && "error" in value) {
    const error = value.error;
    if (error && typeof error === "object" && "message" in error && typeof error.message === "string") return error.message;
  }
  return fallback;
}

export default function RegisterPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>("create");
  const [orgName, setOrgName] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [search, setSearch] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [role, setRole] = useState<"member" | "reviewer">("member");
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
    mutationFn: async () => {
      const identity = { org_slug: orgSlug.trim().toLowerCase(), email: email.trim().toLowerCase(), password };
      if (mode === "create") {
        const result = await api.POST("/v1/auth/register-organization", {
          body: { ...identity, org_name: orgName.trim(), default_currency: currency },
        });
        if (result.error || !result.data) throw new Error(requestError(result.error, "Could not create the organization. Please try again."));
        queryClient.clear();
        queryClient.setQueryData(["session"], result.data);
        router.replace("/dashboard");
      } else {
        const result = await api.POST("/v1/auth/join-organization", { body: { ...identity, requested_role: role } });
        if (result.error || !result.data) throw new Error(requestError(result.error, "Could not send your request. Please try again."));
        queryClient.clear();
        setJoined({ orgName: result.data.org_name, slug: identity.org_slug });
        setPassword("");
        setConfirmation("");
      }
    },
  });

  function changeMode(value: Mode) {
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
    if (mode === "create" && orgName.trim().length < 2) {
      setValidationError("Enter an organization name with at least 2 characters.");
    } else if (!/^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$/.test(orgSlug.trim().toLowerCase())) {
      setValidationError("Use 1–80 letters, numbers, or hyphens for the workspace ID. Start and end with a letter or number.");
    } else if (password.length < 12 || password.length > 128 || !/\p{L}/u.test(password) || !/\p{Nd}/u.test(password)) {
      setValidationError("Use a password with 12–128 characters, including a letter and a number.");
    } else if (password !== confirmation) {
      setValidationError("The passwords do not match.");
    } else {
      registration.mutate();
    }
  }

  return <main className="min-h-screen bg-[#f5f7fb] lg:grid lg:grid-cols-[minmax(0,.85fr)_minmax(520px,1.15fr)]">
    <aside className="relative overflow-hidden bg-[#10223e] px-6 py-8 text-white sm:px-10 lg:flex lg:min-h-screen lg:flex-col lg:justify-between lg:px-12 lg:py-12 xl:px-16">
      <div aria-hidden="true" className="pointer-events-none absolute -left-20 top-1/3 h-80 w-80 rounded-full border-[50px] border-cyan-300/[.06]" />
      <Link href="/login" className="relative inline-flex items-center gap-3 rounded-lg"><span className="grid h-11 w-11 place-items-center rounded-xl bg-cyan-300 text-xl font-black text-[#10223e]">O</span><span className="text-xl font-bold tracking-tight">OpsPilot<span className="text-cyan-300">.</span></span></Link>
      <div className="relative mt-8 max-w-lg lg:my-16">
        <p className="text-[11px] font-bold uppercase tracking-[.2em] text-cyan-200">A workspace that belongs to your team</p>
        <h1 className="mt-4 text-3xl font-bold leading-tight tracking-[-.04em] lg:text-5xl">Clear invoices.<br />Clear ownership.</h1>
        <p className="mt-5 text-sm leading-7 text-slate-300 sm:text-base">Start an organization or request access to your team&apos;s workspace. Every invoice, comment, and review stays within the right organization.</p>
        <ol className="mt-9 hidden space-y-6 lg:block">
          {[['01', 'Set up your workspace', 'Choose a name, workspace ID, and reporting currency.'], ['02', 'Bring your people in', 'Your admin approves access and assigns each person a role.'], ['03', 'Work through invoices together', 'Upload, categorize, discuss, and review with a clear record.']].map(([number, title, description]) => <li key={number} className="flex gap-4"><span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-cyan-200/20 bg-cyan-200/10 text-xs font-bold text-cyan-200">{number}</span><div><p className="font-semibold">{title}</p><p className="mt-1 text-sm leading-6 text-slate-400">{description}</p></div></li>)}
        </ol>
      </div>
      <p className="relative hidden text-xs text-slate-400 lg:block">Membership approval keeps workspace access in your hands.</p>
    </aside>

    <section className="flex items-center justify-center px-5 py-10 sm:px-10 lg:py-12">
      <div className="w-full max-w-xl">
        {joined ? <div className="card p-7 sm:p-10" role="status">
          <span aria-hidden="true" className="grid h-14 w-14 place-items-center rounded-2xl bg-amber-50 text-2xl text-amber-700">◷</span>
          <p className="mt-6 text-xs font-bold uppercase tracking-[.16em] text-amber-700">Request received</p>
          <h2 className="mt-2 text-3xl font-bold tracking-tight text-[#12233d]">Waiting for approval</h2>
          <p className="mt-4 text-sm leading-7 text-slate-600">Your request to join <strong className="text-slate-900">{joined.orgName}</strong> is pending. An organization admin must approve your account and role before you can enter the workspace.</p>
          <p className="mt-4 rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-600">Let your admin know you registered as <strong className="break-all text-slate-800">{email}</strong>. Once they approve you, sign in using your email, password, and workspace ID <strong className="text-slate-800">{joined.slug}</strong>.</p>
          <Link href={`/login?organization=${encodeURIComponent(joined.slug)}`} className="primary mt-6 w-full">Go to sign in →</Link>
        </div> : <>
          <p className="eyebrow">Get started</p>
          <h2 className="mt-2 text-3xl font-bold tracking-[-.04em] text-[#12233d]">Your team starts here</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">Choose how you want to use OpsPilot.</p>
          <div className="mt-6 grid grid-cols-2 gap-2 rounded-xl bg-slate-200/70 p-1.5" role="group" aria-label="Registration type">
            <button type="button" aria-pressed={mode === "create"} disabled={registration.isPending} onClick={() => changeMode("create")} className={`rounded-lg px-3 py-3 text-sm font-semibold transition-colors ${mode === "create" ? "bg-white text-[#123757] shadow-sm" : "text-slate-600 hover:bg-white/50"}`}>Create organization</button>
            <button type="button" aria-pressed={mode === "join"} disabled={registration.isPending} onClick={() => changeMode("join")} className={`rounded-lg px-3 py-3 text-sm font-semibold transition-colors ${mode === "join" ? "bg-white text-[#123757] shadow-sm" : "text-slate-600 hover:bg-white/50"}`}>Join organization</button>
          </div>
          <form onSubmit={submit} className="card mt-5 space-y-5 p-6 sm:p-8">
            <p className="text-sm leading-6 text-slate-600">{mode === "create" ? "You will be the administrator and can approve members, manage categories, and review invoices." : "Select your organization and request a role. Your administrator decides whether to approve access."}</p>
            {mode === "create" && <div><label htmlFor="org-name" className="mb-2 block text-sm font-semibold text-slate-700">Organization name</label><input id="org-name" className="field" autoComplete="organization" required minLength={2} maxLength={200} placeholder="Acme Operations" value={orgName} onChange={event => {
              const value = event.target.value;
              setOrgName(value);
              if (!slugEdited) setOrgSlug(value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80));
            }} /></div>}
            <div><label htmlFor="org-slug" className="mb-2 block text-sm font-semibold text-slate-700">{mode === "create" ? "Workspace ID" : "Organization"}</label><input id="org-slug" className="field" list={mode === "join" ? "join-organizations" : undefined} autoComplete="off" required maxLength={80} placeholder={mode === "create" ? "acme-operations" : "Search or enter a workspace ID"} aria-describedby="slug-help" value={orgSlug} onChange={event => { setOrgSlug(event.target.value); setSlugEdited(true); }} />
              {mode === "join" && <datalist id="join-organizations">{organizations.data?.map(org => <option key={org.id} value={org.slug}>{org.name}</option>)}</datalist>}
              <p id="slug-help" className="mt-2 text-xs leading-5 text-slate-500">{mode === "create" ? "A unique ID your team will use at sign in. Your organization name and ID appear in organization search." : organizations.isError ? "Search is unavailable. Enter the workspace ID your admin shared." : "Search by organization name or enter the workspace ID shared by your admin."}</p>
            </div>
            {mode === "create" ? <div><label htmlFor="currency" className="mb-2 block text-sm font-semibold text-slate-700">Default invoice currency</label><select id="currency" className="field" value={currency} onChange={event => setCurrency(event.target.value)}>{[["USD", "US dollar"], ["INR", "Indian rupee"], ["EUR", "Euro"], ["GBP", "British pound"], ["CAD", "Canadian dollar"], ["AUD", "Australian dollar"], ["SGD", "Singapore dollar"], ["AED", "UAE dirham"]].map(([code, label]) => <option key={code} value={code}>{code} · {label}</option>)}</select><p className="mt-2 text-xs leading-5 text-slate-500">Reviewers can set the correct currency on each invoice. Totals stay separate by currency.</p></div> : <div><label htmlFor="requested-role" className="mb-2 block text-sm font-semibold text-slate-700">Requested role</label><select id="requested-role" className="field" value={role} onChange={event => setRole(event.target.value as "member" | "reviewer")}><option value="member">Member · upload and collaborate</option><option value="reviewer">Reviewer · review and approve invoices</option></select><p className="mt-2 text-xs leading-5 text-slate-500">Your admin confirms your role when approving your account.</p></div>}
            <div><label htmlFor="email" className="mb-2 block text-sm font-semibold text-slate-700">Email</label><input id="email" type="email" className="field" required maxLength={254} autoComplete="username" placeholder="you@company.com" value={email} onChange={event => setEmail(event.target.value)} /></div>
            <div><label htmlFor="password" className="mb-2 block text-sm font-semibold text-slate-700">Password</label><div className="relative"><input id="password" type={showPassword ? "text" : "password"} className="field pr-20" required minLength={12} maxLength={128} autoComplete="new-password" aria-describedby="password-help" value={password} onChange={event => setPassword(event.target.value)} /><button type="button" onClick={() => setShowPassword(value => !value)} className="absolute inset-y-0 right-2 px-2 text-xs font-bold text-[#11627a]" aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? "Hide" : "Show"}</button></div><p id="password-help" className="mt-2 text-xs leading-5 text-slate-500">12–128 characters with at least one letter and one number. If you already use OpsPilot in another organization, use your existing password.</p></div>
            <div><label htmlFor="confirm-password" className="mb-2 block text-sm font-semibold text-slate-700">Confirm password</label><input id="confirm-password" type={showPassword ? "text" : "password"} className="field" required maxLength={128} autoComplete="new-password" value={confirmation} onChange={event => setConfirmation(event.target.value)} /></div>
            {(validationError || registration.error) && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm leading-6 text-rose-800">{validationError || registration.error?.message}</p>}
            <button type="submit" disabled={registration.isPending} className="primary w-full">{registration.isPending ? mode === "create" ? "Creating workspace…" : "Sending request…" : mode === "create" ? "Create workspace" : "Request access"}<span aria-hidden="true">→</span></button>
          </form>
          <p className="mt-6 text-center text-sm text-slate-600">Already have access? <Link href="/login" className="font-semibold text-[#11627a] hover:underline">Sign in</Link></p>
        </>}
      </div>
    </section>
  </main>;
}
