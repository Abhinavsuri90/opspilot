"use client";

import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { SessionFallback } from "@/components/SessionFallback";
import { useWorkspace } from "@/lib/use-workspace";

const journey = [
  { number: "01", name: "Collect", description: "Upload a text-based PDF in Inbox, send it with an organization API key, or connect a mailbox. OpsPilot stores the original and queues extraction.", href: "/inbox", action: "Open Inbox" },
  { number: "02", name: "Understand", description: "The worker extracts fields and source snippets, checks rules and confidence, and highlights uncertainty. Read the complete PDF next to each proposed value.", href: "/inbox", action: "Inspect a document" },
  { number: "03", name: "Decide", description: "An eligible reviewer verifies amount and currency, chooses a category, discusses questions with the team, then approves or rejects with a recorded decision.", href: "/review", action: "Open Review" },
  { number: "04", name: "Act & measure", description: "Approved records can propose controlled connector actions. Policies decide whether they run, wait for approval, or are forbidden. Dashboard and Insights show the resulting work.", href: "/actions", action: "Open Actions" },
] as const;

const places = [
  { name: "Dashboard", href: "/dashboard", explanation: "See throughput, review backlog, estimated model use and weekly reviewer corrections." },
  { name: "Inbox", href: "/inbox", explanation: "Upload, search, read the original PDF, inspect fields, set invoice details, comment and manage sharing." },
  { name: "Review", href: "/review", explanation: "Work through documents waiting for a decision. The document view keeps the source, corrections and timeline together." },
  { name: "Actions", href: "/actions", explanation: "Inspect pending connector actions, approve or reject them, and retry failures when appropriate." },
  { name: "Insights", href: "/insights", explanation: "See verified totals by currency and category, and ask bounded questions that cite the records used." },
  { name: "Admin", href: "/admin", explanation: "Approve membership requests, assign roles and maintain your organization’s invoice categories." },
  { name: "Policies", href: "/settings/policies", explanation: "Set the emergency stop, shadow mode, model spend cap and permission for each action type." },
  { name: "Workflow", href: "/settings/workflow", explanation: "Version the document types, fields, rules and connector destinations used by new documents." },
  { name: "Connectors", href: "/settings/connectors", explanation: "Configure and test a destination such as CSV export, webhook, Postgres table or Google Sheets." },
  { name: "API keys & email", href: "/settings/api-keys", explanation: "Give this organization additional ways to submit documents without using the browser upload." },
  { name: "Quality lab", href: "/evals", explanation: "Read the most recent synthetic extraction evaluation and its limits." },
] as const;

export default function GuidePage() {
  const session = useWorkspace();
  if (session.isError || !session.data) return <SessionFallback session={session} />;
  const isAdmin = session.data.role === "admin";
  const isReviewer = session.data.role === "reviewer";
  const roleMessage = isAdmin
    ? "Start in Admin to approve teammates and add categories. Then upload an invoice in Inbox, assign a reviewer, and inspect its source. Policies and connectors are optional until you want actions to leave the workspace."
    : isReviewer
      ? "Start in Review. Check the source PDF, correct any wrong fields, verify the amount and currency, then record your decision. You can comment when you need context from a teammate."
      : session.data.role === "viewer"
        ? "Start in Inbox to inspect invoices you can access. Viewer access is read-only; ask an administrator for a different role if you need to upload or comment."
        : "Start in Inbox. Upload a document and watch its status move through extraction. You can inspect and discuss invoices you can access; a reviewer or admin records the final decision.";
  return <AppShell session={session.data} active="guide">
    <div className="rounded-[28px] bg-[#102b47] px-6 py-8 text-white shadow-[0_20px_50px_rgba(13,32,57,.14)] sm:px-9 sm:py-10">
      <p className="text-[11px] font-bold uppercase tracking-[.2em] text-cyan-300">Your workspace field guide</p>
      <h1 className="mt-3 max-w-3xl text-3xl font-bold leading-tight tracking-[-.04em] sm:text-4xl">From incoming PDF to a decision everyone can trace.</h1>
      <p className="mt-4 max-w-3xl text-sm leading-6 text-slate-200">OpsPilot is a shared invoice operations workspace for <strong className="text-white">{session.data.org_name}</strong>. People control access and decisions; background workers organize extraction and permitted follow-up actions.</p>
      <div className="mt-6 flex flex-wrap gap-2"><Link href="/inbox" className="inline-flex min-h-10 items-center rounded-xl bg-cyan-300 px-4 text-sm font-bold text-[#102b47] hover:bg-cyan-200">Open Inbox →</Link><Link href="/dashboard" className="inline-flex min-h-10 items-center rounded-xl border border-white/30 px-4 text-sm font-semibold text-white hover:bg-white/10">See Dashboard</Link></div>
    </div>

    <section aria-labelledby="your-start-heading" className="card mt-6 border-cyan-200 bg-cyan-50/60 p-5 sm:p-6"><p className="text-[11px] font-bold uppercase tracking-[.16em] text-cyan-800">For your role</p><h2 id="your-start-heading" className="mt-2 text-lg font-bold text-[#12233d]">Where to start as {session.data.role === "admin" ? "an admin" : session.data.role === "reviewer" ? "a reviewer" : "a teammate"}</h2><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-700">{roleMessage}</p></section>

    <section aria-labelledby="journey-heading" className="mt-9"><div><p className="text-[11px] font-bold uppercase tracking-[.16em] text-cyan-700">The operating loop</p><h2 id="journey-heading" className="mt-2 text-2xl font-bold tracking-[-.03em] text-[#12233d]">Four steps through an invoice</h2></div><ol className="mt-4 grid gap-4 md:grid-cols-2">{journey.map(step => <li key={step.number} className="card p-5"><span className="text-xs font-bold tracking-[.16em] text-cyan-700">{step.number} / {step.name.toUpperCase()}</span><h3 className="mt-3 text-lg font-bold text-[#12233d]">{step.name}</h3><p className="mt-2 min-h-16 text-sm leading-6 text-slate-600">{step.description}</p><Link href={step.href} className="mt-4 inline-flex text-sm font-bold text-[#11627a] hover:underline">{step.action} →</Link></li>)}</ol></section>

    <section aria-labelledby="places-heading" className="mt-9"><h2 id="places-heading" className="text-2xl font-bold tracking-[-.03em] text-[#12233d]">What each place is for</h2><p className="mt-2 text-sm text-slate-600">Links appear according to your approved role.</p><div className="card mt-4 divide-y divide-slate-100 overflow-hidden">{places.filter(place => (isAdmin || !["Admin", "Policies", "Workflow", "Connectors", "API keys & email", "Quality lab"].includes(place.name)) && (isAdmin || isReviewer || place.name !== "Review")).map(place => <div key={place.name} className="grid gap-1 px-5 py-4 sm:grid-cols-[170px_1fr]"><Link href={place.href} className="text-sm font-bold text-[#11627a] hover:underline">{place.name} →</Link><p className="text-sm leading-6 text-slate-600">{place.explanation}</p></div>)}</div></section>

    <section aria-labelledby="words-heading" className="card mt-9 p-5 sm:p-6"><h2 id="words-heading" className="text-lg font-bold text-[#12233d]">A few words you will see</h2><dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2"><div><dt className="font-bold text-slate-800">Needs review</dt><dd className="mt-1 leading-6 text-slate-600">Extraction finished; a person must check and decide.</dd></div><div><dt className="font-bold text-slate-800">Verified amount</dt><dd className="mt-1 leading-6 text-slate-600">The amount a reviewer confirmed. Insights totals use this value, grouped by currency.</dd></div><div><dt className="font-bold text-slate-800">Source evidence</dt><dd className="mt-1 leading-6 text-slate-600">The text from the PDF used to support an extracted field.</dd></div><div><dt className="font-bold text-slate-800">Pending action</dt><dd className="mt-1 leading-6 text-slate-600">An approved invoice proposed a connector change that still needs separate approval.</dd></div></dl></section>
    <p className="mt-6 text-xs leading-5 text-slate-500">Supported intake is unencrypted text-based PDF up to 10 MB and 10 pages. Scanned pages need OCR, which is not available. A model result is a proposal; a reviewer remains responsible for the decision.</p>
  </AppShell>;
}
