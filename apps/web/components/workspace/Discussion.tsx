"use client";

import type { FormEvent } from "react";
import { formatDateTime } from "@/lib/format";
import type { Workspace } from "./types";

type DiscussionProps = {
  data: Workspace;
  comment: string;
  saving: boolean;
  onCommentChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

/** The comment thread on an invoice and, for people who may comment, the composer. */
export function Discussion({ data, comment, saving, onCommentChange, onSubmit }: DiscussionProps) {
  return <section aria-label="Invoice discussion"><h4 className="text-sm font-bold">Discussion <span className="ml-1 text-slate-400">{data.comments.length}</span></h4><div className="mt-3 max-h-80 space-y-3 overflow-auto">{data.comments.length === 0 && <p className="text-xs text-slate-500">Start a conversation about this invoice.</p>}{data.comments.map(item => <article key={item.id} className="rounded-xl bg-slate-50 p-3"><div className="flex flex-wrap justify-between gap-1 text-xs"><span className="break-all font-bold text-slate-700">{item.author_email}</span><time dateTime={item.created_at} className="text-slate-400">{formatDateTime(item.created_at)}</time></div><p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">{item.body}</p></article>)}</div>{data.capabilities.can_comment && <form onSubmit={onSubmit} className="mt-3 space-y-2"><label className="sr-only" htmlFor="invoice-comment">Comment on invoice</label><textarea id="invoice-comment" className="field text-sm" maxLength={4000} rows={3} value={comment} onChange={event => onCommentChange(event.target.value)} placeholder="Add context or ask your reviewer a question…" required /><button className="secondary text-sm" disabled={saving || !comment.trim()}>Post comment</button></form>}</section>;
}
