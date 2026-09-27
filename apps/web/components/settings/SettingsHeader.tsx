import Link from "next/link";
import type { ReactNode } from "react";

export type SettingsSection = "policies" | "connectors" | "workflow" | "api-keys" | "email-inbox" | "members" | "categories";

export const settingsTabs: { id: SettingsSection; label: string; href: string }[] = [
  { id: "policies", label: "Policies", href: "/settings/policies" },
  { id: "connectors", label: "Connectors", href: "/settings/connectors" },
  { id: "workflow", label: "Workflow", href: "/settings/workflow" },
  { id: "api-keys", label: "API keys", href: "/settings/api-keys" },
  { id: "email-inbox", label: "Email inbox", href: "/settings/email-inbox" },
  { id: "members", label: "Members", href: "/admin?tab=members" },
  { id: "categories", label: "Categories", href: "/admin?tab=categories" },
];

type SettingsHeaderProps = {
  active: SettingsSection;
  title: string;
  description: string;
  children?: ReactNode;
};

/** Page heading plus the settings sub-navigation, which matters on phones where the sidebar is folded away. */
export function SettingsHeader({ active, title, description, children }: SettingsHeaderProps) {
  return <div className="mb-6">
    <p className="text-[11px] font-bold uppercase tracking-[.18em] text-cyan-700">Settings</p>
    <div className="mt-2 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
      <div className="min-w-0"><h1 className="text-3xl font-bold tracking-[-.04em] text-[#12233d] sm:text-[38px]">{title}</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">{description}</p></div>
      {children && <div className="flex flex-wrap gap-2">{children}</div>}
    </div>
    <nav aria-label="Settings sections" className="mt-5 flex gap-1 overflow-x-auto border-b border-slate-200">
      {settingsTabs.map(tab => <Link key={tab.id} href={tab.href} aria-current={tab.id === active ? "page" : undefined} className={`whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-semibold ${tab.id === active ? "border-[#11627a] text-[#11627a]" : "border-transparent text-slate-500 hover:text-slate-800"}`}>{tab.label}</Link>)}
    </nav>
  </div>;
}
