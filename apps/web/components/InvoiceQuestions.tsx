"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";

export function InvoiceQuestions({ documentId, categoryId }: { documentId?: string; categoryId?: string }) {
  const [question, setQuestion] = useState("");
  const answer = useMutation({
    mutationFn: async (text: string) => {
      const result = await api.POST("/v1/workspace/questions", { body: { question: text, document_id: documentId, category_id: categoryId } });
      if (result.error || !result.data) throw new Error("Could not answer this question. Check your connection and try again.");
      return result.data;
    },
  });
  function ask(event: FormEvent) { event.preventDefault(); if (question.trim()) answer.mutate(question); }
  const examples = documentId ? ["Summarize this invoice", "What is the total?", "Who is the vendor?"] : ["How many invoices need review?", "What is the total amount pending review?", "Show invoice categories"];
  return <section aria-label="Invoice questions" className="card overflow-hidden">
    <div className="border-b border-slate-100 bg-slate-50/60 p-5"><p className="eyebrow">Workspace answers</p><h2 className="mt-1 text-lg font-bold">Ask your invoices</h2><p className="mt-1 text-xs leading-5 text-slate-500">Live counts, verified totals, categories and extracted fields. Answers use records you can access; unsupported questions are identified.</p></div>
    <div className="space-y-4 p-5">
      <div className="flex flex-wrap gap-2">{examples.map(example => <button type="button" key={example} disabled={answer.isPending} onClick={() => { setQuestion(example); answer.mutate(example); }} className="rounded-full border border-cyan-100 bg-cyan-50 px-3 py-2 text-xs font-semibold text-cyan-900 hover:bg-cyan-100">{example}</button>)}</div>
      <form onSubmit={ask} className="flex flex-col gap-2 sm:flex-row"><label className="sr-only" htmlFor={`question-${documentId ?? "workspace"}`}>Your question</label><input id={`question-${documentId ?? "workspace"}`} value={question} onChange={event => setQuestion(event.target.value)} maxLength={1000} placeholder="Ask a question about your invoices…" className="field min-w-0 flex-1 text-sm" required /><button className="primary" disabled={answer.isPending || !question.trim()}>{answer.isPending ? "Checking…" : "Ask"}</button></form>
      {answer.isError && <p role="alert" className="text-sm text-rose-700">{answer.error.message}</p>}
      {answer.data && <div aria-live="polite" className="rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="whitespace-pre-wrap text-sm leading-7 text-slate-800">{answer.data.answer}</p><p className="mt-3 text-xs text-slate-500">{answer.data.supported ? "Checked against current records" : "Question outside supported scope"} · {new Date(answer.data.as_of).toLocaleString()}</p>{(answer.data.citations ?? []).length > 0 && <ul className="mt-4 space-y-2">{(answer.data.citations ?? []).map((citation, index) => <li key={index} className="rounded-lg bg-white p-3 text-xs leading-5"><Link className="font-semibold text-cyan-800 underline" href={`/inbox?document=${citation.document_id}`}>{citation.filename}</Link><p>{citation.field.replaceAll("_", " ")}: {citation.value}</p><p className="text-slate-500">{citation.evidence}{citation.page_number ? ` · Page ${citation.page_number}` : ""}</p></li>)}</ul>}</div>}
    </div>
  </section>;
}
