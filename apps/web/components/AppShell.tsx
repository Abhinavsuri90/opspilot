"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { components } from "@/lib/schema";
import { usePolicies } from "@/lib/use-policies";

export type Section = "dashboard" | "inbox" | "review" | "actions" | "insights" | "guide" | "admin" | "policies" | "connectors" | "workflow" | "api-keys" | "email-inbox" | "evals";

type Session = components["schemas"]["SessionResponse"];

type AppShellProps = {
  session: Session;
  active: Section;
  children: ReactNode;
};

type NavItem = { key: string; section?: Section; label: string; href: string; icon: Section | "sub" };

const sectionLabels: Record<Section, string> = {
  dashboard: "Dashboard",
  inbox: "Inbox",
  review: "Review",
  actions: "Actions",
  insights: "Insights",
  guide: "Guide",
  admin: "Admin",
  policies: "Policies",
  connectors: "Connectors",
  workflow: "Workflow",
  "api-keys": "API keys",
  "email-inbox": "Email inbox",
  evals: "Quality lab",
};

function NavIcon({ name }: { name: Section | "sub" }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (name === "sub") return <span aria-hidden="true" className="grid h-5 w-5 place-items-center"><span className="h-1.5 w-1.5 rounded-full bg-current opacity-60" /></span>;
  return <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" {...common}>
    {name === "dashboard" && <><rect x="3.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="3.5" y="13.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="13.5" width="7" height="7" rx="1.5" /></>}
    {name === "inbox" && <><path d="M4 4.5h16v13.2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4.5Z" /><path d="M4 14h4l1.5 2h5l1.5-2h4" /></>}
    {name === "review" && <><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4V2h6v2M9 11l2 2 4-4M9 17h6" /></>}
    {name === "actions" && <><path d="M13 3 5 13.5h6L10 21l9-11h-6l0-7Z" /></>}
    {name === "insights" && <><path d="M4 4v16h17M8 16v-5M13 16V7M18 16v-8" /></>}
    {name === "guide" && <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11v17H6.5A2.5 2.5 0 0 0 4 22V5.5ZM20 5.5A2.5 2.5 0 0 0 17.5 3H13v17h4.5A2.5 2.5 0 0 1 20 22V5.5Z" /></>}
    {name === "admin" && <><circle cx="9" cy="8.5" r="3" /><path d="M3.5 19v-1.2A4.8 4.8 0 0 1 8.3 13h1.4a4.8 4.8 0 0 1 4.8 4.8V19H3.5Z" /><path d="M16 6a3 3 0 0 1 0 5.7M17 13.4a4.8 4.8 0 0 1 3.5 4.6v1" /></>}
    {name === "policies" && <><path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6L12 3Z" /><path d="M9.5 12l1.8 1.8L15 10" /></>}
    {name === "connectors" && <><path d="M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0V7Z" /><path d="M12 16v5" /></>}
    {name === "workflow" && <><rect x="3.5" y="4" width="7" height="5" rx="1.2" /><rect x="13.5" y="15" width="7" height="5" rx="1.2" /><path d="M10.5 6.5H15a2 2 0 0 1 2 2V15" /></>}
    {name === "api-keys" && <><circle cx="8" cy="12" r="4" /><path d="M12 12h9M18 12v3M15 12v2" /></>}
    {name === "email-inbox" && <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></>}
    {name === "evals" && <><path d="M4 19h16M5 16l4-5 4 3 6-9" /><circle cx="19" cy="5" r="1" /></>}
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
  const isAdmin = session.role === "admin";
  // Only administrators may read the switches; for everyone else the query stays idle and no banner shows.
  const policies = usePolicies(session);
  const paused = Boolean(policies.data?.kill_switch);

  const workspaceItems: NavItem[] = [
    { key: "dashboard", section: "dashboard", label: "Dashboard", href: "/dashboard", icon: "dashboard" },
    { key: "inbox", section: "inbox", label: "Inbox", href: "/inbox", icon: "inbox" },
    ...(isAdmin || session.role === "reviewer" ? [{ key: "review", section: "review" as const, label: "Review", href: "/review", icon: "review" as const }] : []),
    { key: "actions", section: "actions", label: "Actions", href: "/actions", icon: "actions" },
    { key: "insights", section: "insights", label: "Insights", href: "/insights", icon: "insights" },
    { key: "guide", section: "guide", label: "Guide", href: "/guide", icon: "guide" },
  ];
  // Members and categories live on the admin page; the sub-links open its tabs directly.
  const settingsItems: NavItem[] = [
    { key: "admin", section: "admin", label: "Admin", href: "/admin", icon: "admin" },
    { key: "members", label: "Members", href: "/admin?tab=members", icon: "sub" },
    { key: "categories", label: "Categories", href: "/admin?tab=categories", icon: "sub" },
    { key: "policies", section: "policies", label: "Policies", href: "/settings/policies", icon: "policies" },
    { key: "connectors", section: "connectors", label: "Connectors", href: "/settings/connectors", icon: "connectors" },
    { key: "workflow", section: "workflow", label: "Workflow", href: "/settings/workflow", icon: "workflow" },
    { key: "api-keys", section: "api-keys", label: "API keys", href: "/settings/api-keys", icon: "api-keys" },
    { key: "email-inbox", section: "email-inbox", label: "Email inbox", href: "/settings/email-inbox", icon: "email-inbox" },
    { key: "evals", section: "evals", label: "Quality lab", href: "/evals", icon: "evals" },
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

  const link = (item: NavItem) => {
    const current = item.section !== undefined && active === item.section;
    const sub = item.icon === "sub";
    return <Link
      key={item.key}
      href={item.href}
      onClick={() => setMenuOpen(false)}
      aria-current={current ? "page" : undefined}
      className={`group flex items-center gap-3 rounded-xl px-3.5 text-sm font-medium transition-colors ${sub ? "min-h-9 py-1.5 pl-6 text-[13px]" : "min-h-11 py-2.5"} ${current ? "bg-cyan-400/15 text-cyan-100 ring-1 ring-cyan-300/20" : "text-slate-300 hover:bg-white/10 hover:text-white"}`}
    >
      <NavIcon name={item.icon} />
      <span className="flex-1">{item.label}</span>
      {current && <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-cyan-300" />}
    </Link>;
  };

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

      <div id="workspace-navigation" className={`${menuOpen ? "flex" : "hidden"} min-h-0 flex-1 flex-col overflow-y-auto px-4 pb-5 lg:flex lg:px-4`}>
        <nav aria-label="Main navigation">
          <p className="mb-2 px-3.5 text-[10px] font-bold uppercase tracking-[.18em] text-slate-400">Workspace</p>
          <div className="space-y-1">{workspaceItems.map(link)}</div>
          {isAdmin && <>
            <p className="mb-2 mt-8 px-3.5 text-[10px] font-bold uppercase tracking-[.18em] text-slate-400">Settings</p>
            <div className="space-y-1">{settingsItems.map(link)}</div>
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
        <div className="flex items-center gap-2 text-sm text-slate-500"><span>Workspace</span><span aria-hidden="true" className="text-slate-300">/</span><span className="font-semibold text-slate-800">{sectionLabels[active]}</span></div>
        <div className="flex items-center gap-3 text-sm"><span className="max-w-[240px] truncate font-semibold text-slate-700">{session.org_name}</span><span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium capitalize text-slate-600">{session.role}</span></div>
      </header>
      {paused && <div role="status" data-testid="agent-paused-banner" className="flex flex-wrap items-center justify-between gap-2 bg-rose-700 px-4 py-2.5 text-sm font-semibold text-white sm:px-6 lg:px-8 xl:px-12">
        <span><span aria-hidden="true" className="mr-2">■</span>Agent paused. No actions execute until the kill switch is disengaged.</span>
        {active !== "policies" && <Link href="/settings/policies" className="rounded-lg border border-white/40 px-2.5 py-1 text-xs font-semibold text-white hover:bg-white/10">Open policies →</Link>}
      </div>}
      <main id="main-content" className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-7 sm:px-6 lg:px-8 lg:pt-9 xl:px-12">{children}</main>
    </div>
  </div>;
}
