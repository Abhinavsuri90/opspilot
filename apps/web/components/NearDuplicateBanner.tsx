import Link from "next/link";
import { StatusBadge } from "@/components/StatusBadge";
import { documentTypeLabel } from "@/lib/document-types";
import { formatDateTime } from "@/lib/format";
import type { components } from "@/lib/schema";

type NearDuplicateRef = components["schemas"]["NearDuplicateRef"];

/**
 * A document with the same counterparty, number and total as another one in
 * the workspace. Only the linked documents the viewer may open are listed.
 */
export function NearDuplicateBanner({ duplicates, linkTo = "inbox", onOpen }: { duplicates: NearDuplicateRef[] | null | undefined; linkTo?: "inbox" | "review"; /** When set, the inbox switches its selection in place instead of navigating. */ onOpen?: (documentId: string) => void }) {
  if (!duplicates || duplicates.length === 0) return null;
  const href = (id: string) => linkTo === "review" ? `/review/${encodeURIComponent(id)}` : `/inbox?document=${encodeURIComponent(id)}`;
  return <div role="alert" data-testid="near-duplicate-banner" className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
    <p className="font-bold">Possible duplicate</p>
    <p className="mt-1 text-xs leading-5 text-amber-900">This document has the same counterparty, number and total as {duplicates.length === 1 ? "another document" : `${duplicates.length} other documents`} in this workspace, so it needs a person&apos;s decision even if every field is confident.</p>
    <ul className="mt-2 space-y-1.5" aria-label="Linked documents">
      {duplicates.map(item => <li key={item.document_id} className="flex flex-wrap items-center gap-2 text-xs">
        {onOpen
          ? <button type="button" onClick={() => onOpen(item.document_id)} className="break-all text-left font-semibold text-[#11627a] underline">{item.filename}</button>
          : <Link href={href(item.document_id)} className="break-all font-semibold text-[#11627a] underline">{item.filename}</Link>}
        <span className="text-amber-900">{documentTypeLabel(item.document_type)} · {formatDateTime(item.created_at)}</span>
        <StatusBadge status={item.status} className="!py-0.5 !text-[10px]" />
      </li>)}
    </ul>
  </div>;
}
