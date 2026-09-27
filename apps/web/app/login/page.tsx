"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { PublicBrand } from "@/components/PublicBrand";
import { api } from "@/lib/api";
import { apiErrorMessage, retryAfterMinutes, waitMessage } from "@/lib/errors";
import { loginSchema } from "@/lib/login";
import { useSession } from "@/lib/use-workspace";

export default function LoginPage() {
  return <Suspense fallback={<main className="grid min-h-screen place-items-center bg-[#f9faf6]"><p role="status" className="text-sm font-semibold text-[#122f33]">Opening sign in…</p></main>}><LoginEntry /></Suspense>;
}

function LoginEntry() {
  const searchParams = useSearchParams();
  const organization = searchParams.get("organization")?.trim().toLowerCase() ?? "";
  const initialOrganization = /^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$/.test(organization) ? organization : "";
  return <LoginForm key={initialOrganization} initialOrganization={initialOrganization} />;
}

function LoginForm({ initialOrganization }: { initialOrganization: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const redirected = useRef(false);
  const [orgSlug, setOrgSlug] = useState(initialOrganization);
  const [search, setSearch] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  // A visitor who already holds a valid session goes straight to the workspace.
  // Only the API can tell: the cookie is HttpOnly, and the edge check lets any
  // cookie through. The redirect happens once, here or after signing in.
  const existing = useSession({ refetchInterval: false });
  useEffect(() => {
    if (existing.data && !redirected.current) {
      redirected.current = true;
      router.replace("/dashboard");
    }
  }, [existing.data, router]);

  useEffect(() => {
    const timeout = setTimeout(() => setSearch(orgSlug.trim()), 250);
    return () => clearTimeout(timeout);
  }, [orgSlug]);

  const organizations = useQuery({
    queryKey: ["organizations", search],
    queryFn: async () => {
      const result = await api.GET("/v1/organizations", { params: { query: { search } } });
      if (result.error || !result.data) throw new Error("Could not load organizations");
      return result.data;
    },
    staleTime: 30_000,
    retry: false,
  });

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const parsed = loginSchema.safeParse({ org_slug: orgSlug, email, password });
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Check the form");
      return;
    }
    setPending(true);
    setError("");
    try {
      const result = await api.POST("/v1/auth/login", { body: parsed.data });
      if (result.error || !result.data) {
        const status = result.response.status;
        setError(status === 401
          ? "Invalid organization, email, or password."
          : status === 403
            ? apiErrorMessage(result.error, status, "Your account is waiting for organization approval. Contact your administrator.")
          : status === 429
            ? `Too many sign-in attempts. Please wait ${waitMessage(retryAfterMinutes(result.response.headers.get("retry-after")))} before trying again.`
          : "Sign in is temporarily unavailable. Please try again.");
        return;
      }
      // A new login may belong to a different workspace. Discard cached documents first.
      queryClient.clear();
      queryClient.setQueryData(["session"], result.data);
      redirected.current = true;
      router.replace("/dashboard");
    } catch {
      setError("Could not reach the API. Try again shortly.");
    } finally {
      setPending(false);
    }
  }

  return <main className="grid min-h-screen bg-[#f9faf6] lg:grid-cols-[minmax(0,1.05fr)_minmax(440px,.95fr)]">
    <section className="relative hidden overflow-hidden bg-[#122f33] px-12 py-12 text-white lg:flex lg:flex-col lg:justify-between xl:px-20" aria-label="OpsPilot overview">
      <div className="absolute -right-36 -top-40 h-[500px] w-[500px] rounded-full border border-white/10 bg-[#d3e8b8]/10 blur-2xl" aria-hidden="true" />
      <div className="absolute -bottom-48 -left-24 h-[420px] w-[420px] rounded-full bg-[#d3e8b8]/10 blur-3xl" aria-hidden="true" />
      <PublicBrand light className="relative" />
      <div className="relative max-w-xl">
        <p className="text-xs font-bold uppercase tracking-[.2em] text-[#d3e8b8]">Document operations, clearly</p>
        <h1 className="mt-5 text-5xl font-bold leading-[1.08] tracking-tight xl:text-6xl">From invoice to evidence, in one workspace.</h1>
        <p className="mt-6 max-w-lg text-base leading-7 text-[#c4d5ce]">Bring invoice intake, evidence, team conversations, and approvals into one place. Your organization controls who can join and who can review.</p>
        <div className="mt-10 grid max-w-lg grid-cols-3 gap-3 text-sm">
          <div className="rounded-2xl border border-white/15 bg-white/5 p-4"><span className="block text-2xl font-bold text-[#d3e8b8]">01</span><span className="mt-2 block text-slate-200">Upload PDF</span></div>
          <div className="rounded-2xl border border-white/15 bg-white/5 p-4"><span className="block text-2xl font-bold text-[#d3e8b8]">02</span><span className="mt-2 block text-slate-200">Extract fields</span></div>
          <div className="rounded-2xl border border-white/15 bg-white/5 p-4"><span className="block text-2xl font-bold text-[#d3e8b8]">03</span><span className="mt-2 block text-slate-200">Review together</span></div>
        </div>
      </div>
      <p className="relative text-xs text-[#b5ccc4]">Your workspace. Your team. Clear decisions.</p>
    </section>
    <section className="flex min-h-screen items-center justify-center px-5 py-10 sm:px-10">
      <div className="w-full max-w-md">
        <PublicBrand className="mb-9 lg:hidden" />
        <p className="eyebrow !text-[#006b60]">Workspace access</p>
        <h2 className="mt-2 text-3xl font-bold tracking-tight text-slate-900">Welcome back</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">One sign in for your whole team. Choose your organization to open your workspace.</p>
        <div className="mt-5 rounded-xl border border-[#dce5dc] bg-[#edf3e8] p-4">
          <p className="text-xs font-bold uppercase tracking-[.1em] text-[#006b60]">Admins · Members · Reviewers</p>
          <p className="mt-2 text-xs leading-5 text-slate-600">Use your organization, email, and password. Your approved role determines the pages and actions available to you. New join requests need an administrator&apos;s approval.</p>
        </div>
        <form onSubmit={submit} className="card !border-[#dce5dc] !shadow-[0_12px_35px_#173b3c09] mt-7 space-y-5 p-6 sm:p-8">
          <div><label htmlFor="org" className="mb-2 block text-sm font-semibold text-slate-700">Organization</label><input id="org" className="field !border-[#ccd9cf] focus:!border-[#006b60] focus:!shadow-[0_0_0_4px_#006b601a]" list="login-organizations" autoComplete="organization" placeholder="Search or enter your workspace ID" maxLength={80} aria-describedby="organization-help" value={orgSlug} onChange={e => setOrgSlug(e.target.value)} />
            <datalist id="login-organizations">{organizations.data?.map(org => <option key={org.id} value={org.slug}>{org.name}</option>)}</datalist>
            <p id="organization-help" className="mt-2 text-xs leading-5 text-slate-500">{organizations.isError ? "Search is unavailable. You can still enter your workspace ID." : "Choose your organization or enter the workspace ID shared by your admin."}</p>
          </div>
          <div><label htmlFor="email" className="mb-2 block text-sm font-semibold text-slate-700">Email</label><input id="email" type="email" className="field !border-[#ccd9cf] focus:!border-[#006b60] focus:!shadow-[0_0_0_4px_#006b601a]" autoComplete="username" placeholder="you@company.com" maxLength={254} value={email} onChange={e => setEmail(e.target.value)} /></div>
          <div><label htmlFor="password" className="mb-2 block text-sm font-semibold text-slate-700">Password</label><div className="relative"><input id="password" type={showPassword ? "text" : "password"} className="field !border-[#ccd9cf] focus:!border-[#006b60] focus:!shadow-[0_0_0_4px_#006b601a] pr-20" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /><button type="button" onClick={() => setShowPassword(value => !value)} className="absolute inset-y-0 right-2 px-2 text-xs font-bold text-[#006b60]" aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? "Hide" : "Show"}</button></div></div>
          {error && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
          <button type="submit" disabled={pending} className="primary !border-[#006b60] !bg-[#006b60] !shadow-[0_5px_13px_#006b601c] hover:!bg-[#004e46] w-full">{pending ? "Signing in…" : "Sign in"}<span aria-hidden="true">→</span></button>
        </form>
        <div className="mt-6 text-center text-sm text-slate-600">
          <p>Starting a workspace? <Link href="/register?mode=create" className="font-semibold text-[#006b60] hover:underline">Create an organization →</Link></p>
          <p className="mt-3 text-xs leading-6">Joining your team? <Link href="/register?mode=join&role=member" className="font-semibold text-[#006b60] hover:underline">Join as a member</Link><span aria-hidden="true" className="mx-2">·</span><Link href="/register?mode=join&role=reviewer" className="font-semibold text-[#006b60] hover:underline">Join as a reviewer</Link></p>
          <Link href="/" className="mt-5 inline-block text-xs font-semibold text-slate-500 hover:text-[#006b60]">← Back to OpsPilot</Link>
        </div>
      </div>
    </section>
  </main>;
}
