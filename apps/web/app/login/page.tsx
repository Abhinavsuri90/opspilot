"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { loginSchema } from "@/lib/login";

export default function LoginPage() {
  const router = useRouter();
  const [orgSlug, setOrgSlug] = useState("northwind");
  const [email, setEmail] = useState("northwind@example.com");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = loginSchema.safeParse({ org_slug: orgSlug, email, password });
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Check the form");
      return;
    }
    setPending(true);
    setError("");
    try {
      const result = await api.POST("/v1/auth/login", { body: parsed.data });
      if (result.error) {
        setError("Invalid organization, email, or password");
        return;
      }
      router.push("/dashboard");
    } catch {
      setError("Could not reach the API. Try again shortly.");
    } finally {
      setPending(false);
    }
  }

  return <main className="min-h-screen grid place-items-center px-4 py-10">
    <div className="w-full max-w-md">
      <div className="mb-8 text-center">
        <div className="mx-auto mb-5 grid h-12 w-12 place-items-center rounded-xl bg-blue-900 text-white font-bold text-2xl">O</div>
        <h1 className="text-3xl font-bold tracking-tight">OpsPilot</h1>
        <p className="mt-2 text-slate-500">Sign in to your operations workspace</p>
      </div>
      <form onSubmit={submit} className="card p-7 space-y-5">
        <div><label htmlFor="org" className="mb-2 block text-sm font-semibold">Organization</label><input id="org" className="field" autoComplete="organization" value={orgSlug} onChange={e => setOrgSlug(e.target.value)} /></div>
        <div><label htmlFor="email" className="mb-2 block text-sm font-semibold">Email</label><input id="email" type="email" className="field" autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} /></div>
        <div><label htmlFor="password" className="mb-2 block text-sm font-semibold">Password</label><input id="password" type="password" className="field" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></div>
        {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
        <button type="submit" disabled={pending} className="primary w-full">{pending ? "Signing in…" : "Sign in"}</button>
      </form>
      <p className="mt-5 text-center text-sm text-slate-500">Local demo credentials are set in your environment.</p>
    </div>
  </main>;
}
