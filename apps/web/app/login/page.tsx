"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { loginSchema } from "@/lib/login";

function responseMessage(value: unknown) {
  if (value && typeof value === "object" && "error" in value) {
    const error = value.error;
    if (error && typeof error === "object" && "message" in error && typeof error.message === "string") return error.message;
  }
  return undefined;
}

export default function LoginPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [orgSlug, setOrgSlug] = useState("");
  const [search, setSearch] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

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

  useEffect(() => {
    const selected = new URLSearchParams(window.location.search).get("organization");
    if (selected) setOrgSlug(selected.slice(0, 80));
  }, []);

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
        const serverMessage = responseMessage(result.error);
        setError(result.response.status === 401
          ? "Invalid organization, email, or password."
          : result.response.status === 403
            ? serverMessage || "Your account is waiting for organization approval. Contact your administrator."
          : result.response.status === 429
            ? "Too many sign-in attempts. Please wait 15 minutes before trying again."
          : "Sign in is temporarily unavailable. Please try again.");
        return;
      }
      // A new login may belong to a different workspace. Discard cached documents first.
      queryClient.clear();
      queryClient.setQueryData(["session"], result.data);
      router.replace("/dashboard");
    } catch {
      setError("Could not reach the API. Try again shortly.");
    } finally {
      setPending(false);
    }
  }

  return <main className="grid min-h-screen lg:grid-cols-[minmax(0,1.05fr)_minmax(440px,.95fr)]">
    <section className="relative hidden overflow-hidden bg-[#10223e] px-12 py-12 text-white lg:flex lg:flex-col lg:justify-between xl:px-20" aria-label="OpsPilot overview">
      <div className="absolute -right-36 -top-40 h-[500px] w-[500px] rounded-full border border-white/10 bg-blue-400/10 blur-2xl" aria-hidden="true" />
      <div className="absolute -bottom-48 -left-24 h-[420px] w-[420px] rounded-full bg-cyan-300/10 blur-3xl" aria-hidden="true" />
      <div className="relative flex items-center gap-3"><span className="grid h-11 w-11 place-items-center rounded-xl bg-white text-xl font-black text-[#18427d]">O</span><span className="text-xl font-bold tracking-tight">OpsPilot</span></div>
      <div className="relative max-w-xl">
        <p className="text-xs font-bold uppercase tracking-[.2em] text-blue-200">Document operations, clearly</p>
        <h1 className="mt-5 text-5xl font-bold leading-[1.08] tracking-tight xl:text-6xl">From invoice to evidence, in one workspace.</h1>
        <p className="mt-6 max-w-lg text-base leading-7 text-slate-300">Bring invoice intake, evidence, team conversations, and approvals into one place. Your organization controls who can join and who can review.</p>
        <div className="mt-10 grid max-w-lg grid-cols-3 gap-3 text-sm">
          <div className="rounded-2xl border border-white/15 bg-white/5 p-4"><span className="block text-2xl font-bold text-cyan-200">01</span><span className="mt-2 block text-slate-200">Upload PDF</span></div>
          <div className="rounded-2xl border border-white/15 bg-white/5 p-4"><span className="block text-2xl font-bold text-cyan-200">02</span><span className="mt-2 block text-slate-200">Extract fields</span></div>
          <div className="rounded-2xl border border-white/15 bg-white/5 p-4"><span className="block text-2xl font-bold text-cyan-200">03</span><span className="mt-2 block text-slate-200">Review together</span></div>
        </div>
      </div>
      <p className="relative text-xs text-slate-400">Your workspace. Your team. Clear decisions.</p>
    </section>
    <section className="flex min-h-screen items-center justify-center px-5 py-10 sm:px-10">
      <div className="w-full max-w-md">
        <div className="mb-9 lg:hidden"><span className="grid h-11 w-11 place-items-center rounded-xl bg-[#18427d] text-xl font-black text-white">O</span><p className="mt-3 text-xl font-bold">OpsPilot</p></div>
        <p className="eyebrow">Workspace access</p>
        <h2 className="mt-2 text-3xl font-bold tracking-tight text-slate-900">Welcome back</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">Sign in to view your organization&apos;s invoice queue.</p>
        <form onSubmit={submit} className="card mt-7 space-y-5 p-6 sm:p-8">
          <div><label htmlFor="org" className="mb-2 block text-sm font-semibold text-slate-700">Organization</label><input id="org" className="field" list="login-organizations" autoComplete="organization" placeholder="Search or enter your workspace ID" maxLength={80} aria-describedby="organization-help" value={orgSlug} onChange={e => setOrgSlug(e.target.value)} />
            <datalist id="login-organizations">{organizations.data?.map(org => <option key={org.id} value={org.slug}>{org.name}</option>)}</datalist>
            <p id="organization-help" className="mt-2 text-xs leading-5 text-slate-500">{organizations.isError ? "Search is unavailable. You can still enter your workspace ID." : "Choose your organization or enter the workspace ID shared by your admin."}</p>
          </div>
          <div><label htmlFor="email" className="mb-2 block text-sm font-semibold text-slate-700">Email</label><input id="email" type="email" className="field" autoComplete="username" placeholder="you@company.com" maxLength={254} value={email} onChange={e => setEmail(e.target.value)} /></div>
          <div><label htmlFor="password" className="mb-2 block text-sm font-semibold text-slate-700">Password</label><div className="relative"><input id="password" type={showPassword ? "text" : "password"} className="field pr-20" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /><button type="button" onClick={() => setShowPassword(value => !value)} className="absolute inset-y-0 right-2 px-2 text-xs font-bold text-blue-700" aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? "Hide" : "Show"}</button></div></div>
          {error && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
          <button type="submit" disabled={pending} className="primary w-full">{pending ? "Signing in…" : "Sign in"}<span aria-hidden="true">→</span></button>
        </form>
        <p className="mt-6 text-center text-sm text-slate-600">New to OpsPilot? <Link href="/register" className="font-semibold text-[#11627a] hover:underline">Create or join an organization →</Link></p>
      </div>
    </section>
  </main>;
}
