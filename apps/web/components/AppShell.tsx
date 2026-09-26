"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { api } from "@/lib/api";

type Section = "dashboard" | "inbox" | "review" | "insights" | "admin";

type Session = {
  org_name: string;
  email: string;
  role: string;
};

type AppShellProps = {
  session: Session;
  active: Section;
  children: ReactNode;
};

function NavIcon({ name }: { name: Section }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" {...common}>
    {name === "dashboard" && <><rect x="3.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="3.5" y="13.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="13.5" width="7" height="7" rx="1.5" /></>}
    {name === "inbox" && <><path d="M4 4.5h16v13.2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4.5Z" /><path d="M4 14h4l1.5 2h5l1.5-2h4" /></>}
    {name === "review" && <><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4V2h6v2M9 11l2 2 4-4M9 17h6" /></>}
    {name === "insights" && <><path d="M4 4v16h17M8 16v-5M13 16V7M18 16v-8" /></>}
    {name === "admin" && <><circle cx="9" cy="8.5" r="3" /><path d="M3.5 19v-1.2A4.8 4.8 0 0 1 8.3 13h1.4a4.8 4.8 0 0 1 4.8 4.8V19H3.5Z" /><path d="M16 6a3 3 0 0 1 0 5.7M17 13.4a4.8 4.8 0 0 1 3.5 4.6v1" /></>}
  </svg>;
}

function Mark() {
  return <span aria-hidden="true" className="relative grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-cyan-400 text-[#0d2039] shadow-[0_8px_24px_rgba(34,211,238,.15)]">
    <span className="absolute left-[9px] top-[9px] h-[9px] w-[9px] rounded-[2px] bg-[#0d2039]" />
    <span className="absolute right-[9px] top-[9px] h-[9px] w-[9px] rounded-[2px] bg-[#0d2039]" />
    <span className="absolute bottom-[9px] left-[9px] h-[9px] w-[9px] rounded-[2px] bg-[#0d2039]" />
    <span className="absolute bottom-[9px] right-[9px] h-[9px] w-[9px] rounded-[2px] bg-[#0d2039]" />
  </span>;
}

function initials(value: string) {
  return value.slice(0, 2).toUpperCase();
}

export function AppShell({ session, active, children }: AppShellProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [menuOpen, setMenuOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const items: { key: Section; label: string; href: string }[] = [
    { key: "dashboard", label: "Dashboard", href: "/dashboard" },
    { key: "inbox", label: "Inbox", href: "/inbox" },
    ...(session.role === "admin" || session.role === "reviewer" ? [{ key: "review" as const, label: "Review", href: "/review" }] : []),
    { key: "insights", label: "Insights", href: "/insights" },
  ];

  async function signOut() {
    if (loggingOut) return;
    setLoggingOut(true);
    setLogoutError("");
    try {
      const result = await api.POST("/v1/auth/logout");
      if (result.error || result.response.status !== 204) throw new Error("Logout failed");
      queryClient.clear();
      router.replace("/login");
    } catch {
      setLogoutError("Could not sign out. Please try again.");
      setLoggingOut(false);
    }
  }

  const link = (item: { key: Section; label: string; href: string }) => <Link
    key={item.key}
    href={item.href}
    onClick={() => setMenuOpen(false)}
    aria-current={active === item.key ? "page" : undefined}
    className={`group flex min-h-11 items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium transition-colors ${active === item.key ? "bg-cyan-400/15 text-cyan-100 ring-1 ring-cyan-300/20" : "text-slate-300 hover:bg-white/10 hover:text-white"}`}
  >
    <NavIcon name={item.key} />
    <span className="flex-1">{item.label}</span>
    {active === item.key && <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-cyan-300" />}
  </Link>;

  return <div className="min-h-screen bg-[#f5f7fb] text-slate-900 lg:flex">
    <a href="#main-content" className="sr-only z-50 rounded-lg bg-white px-4 py-3 font-semibold text-slate-900 focus:not-sr-only focus:fixed focus:left-4 focus:top-4">Skip to content</a>
    <aside className="z-20 flex shrink-0 flex-col bg-[#0d2039] text-white lg:sticky lg:top-0 lg:h-screen lg:w-[268px]" aria-label="Workspace sidebar">
      <div className="flex items-center justify-between gap-3 px-5 py-5 lg:px-6 lg:py-7">
        <Link href="/dashboard" className="flex items-center gap-3 rounded-lg" aria-label="OpsPilot dashboard" onClick={() => setMenuOpen(false)}>
          <Mark />
          <span className="text-[19px] font-bold tracking-[-.04em]">OpsPilot<span className="text-cyan-300">.</span></span>
        </Link>
        <button
          type="button"
          className="grid h-10 w-10 place-items-center rounded-lg border border-white/15 text-slate-200 hover:bg-white/10 lg:hidden"
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
          aria-controls="workspace-navigation"
          onClick={() => setMenuOpen(open => !open)}
        >
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            {menuOpen ? <><path d="M5 5l14 14" /><path d="M19 5L5 19" /></> : <><path d="M4 7h16" /><path d="M4 12h16" /><path d="M4 17h16" /></>}
          </svg>
        </button>
      </div>

      <div id="workspace-navigation" className={`${menuOpen ? "flex" : "hidden"} min-h-0 flex-1 flex-col px-4 pb-5 lg:flex lg:px-4`}>
        <nav aria-label="Main navigation">
          <p className="mb-2 px-3.5 text-[10px] font-bold uppercase tracking-[.18em] text-slate-400">Workspace</p>
          <div className="space-y-1">{items.map(link)}</div>
          {session.role === "admin" && <>
            <p className="mb-2 mt-8 px-3.5 text-[10px] font-bold uppercase tracking-[.18em] text-slate-400">Organization</p>
            {link({ key: "admin", label: "Admin", href: "/admin" })}
          </>}
        </nav>

        <div className="mt-8 border-t border-white/10 pt-5 lg:mt-auto">
          <div className="rounded-xl bg-white/[.07] p-3.5 ring-1 ring-white/10">
            <div className="flex min-w-0 items-center gap-3">
              <span aria-hidden="true" className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-cyan-400/20 text-xs font-bold text-cyan-100">{initials(session.email)}</span>
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-white">{session.email}</p>
                <p className="mt-0.5 text-xs capitalize text-slate-300">{session.role} · {session.org_name}</p>
              </div>
            </div>
            <button type="button" onClick={signOut} disabled={loggingOut} className="mt-4 flex min-h-9 w-full items-center justify-center rounded-lg border border-white/15 px-3 text-xs font-semibold text-slate-200 transition-colors hover:bg-white/10 hover:text-white">
              {loggingOut ? "Signing out…" : "Sign out"}
            </button>
            {logoutError && <p role="alert" className="mt-3 text-xs text-rose-200">{logoutError}</p>}
          </div>
        </div>
      </div>
    </aside>

    <div className="min-w-0 flex-1">
      <header className="hidden h-[76px] items-center justify-between border-b border-slate-200/80 bg-white/80 px-8 backdrop-blur lg:flex xl:px-12">
        <div className="flex items-center gap-2 text-sm text-slate-500"><span>Workspace</span><span aria-hidden="true" className="text-slate-300">/</span><span className="font-semibold capitalize text-slate-800">{active}</span></div>
        <div className="flex items-center gap-3 text-sm"><span className="max-w-[240px] truncate font-semibold text-slate-700">{session.org_name}</span><span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium capitalize text-slate-600">{session.role}</span></div>
      </header>
      <main id="main-content" className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-7 sm:px-6 lg:px-8 lg:pt-9 xl:px-12">{children}</main>
    </div>
  </div>;
}
