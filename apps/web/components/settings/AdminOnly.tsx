import Link from "next/link";

/** What a non-administrator sees on an administrator page: a clear message, never a broken form. */
export function AdminOnly({ description }: { description: string }) {
  return <section className="mx-auto mt-12 max-w-xl rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
    <span aria-hidden="true" className="grid h-11 w-11 place-items-center rounded-xl bg-amber-50 text-xl text-amber-700">⊘</span>
    <h1 className="mt-5 text-2xl font-bold tracking-[-.03em] text-[#12233d]">Admin access required</h1>
    <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
    <Link href="/dashboard" className="mt-5 inline-block text-sm font-semibold text-[#11627a] hover:underline">Return to dashboard →</Link>
  </section>;
}
