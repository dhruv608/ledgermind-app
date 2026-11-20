"use client";

import React, { useState } from "react";
import { ChevronDown, Search } from "lucide-react";
import { Card } from "@/components/ui/card";

export type FaqGroup = { group: string; items: { q: string; a: string }[] };

/** *Button name* in the text, shown in bold. */
function bold(text: string) {
  return text.split("*").map((part, i) => (i % 2 ? <strong key={i} className="font-semibold text-slate-900">{part}</strong> : part));
}

/** The guide's questions with a search box: typing keeps only the questions and words that match. */
export function FaqSearch({ groups }: { groups: FaqGroup[] }) {
  const [query, setQuery] = useState("");
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = (q: string, a: string) => words.every((w) => `${q} ${a}`.toLowerCase().includes(w));
  const shown = groups
    .map(({ group, items }) => ({ group, items: items.filter(({ q, a }) => matches(q, a)) }))
    .filter(({ items }) => items.length);

  return (
    <div className="space-y-6">
      <label className="relative block">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the questions, e.g. allowance, loan, workbook"
          className="h-10 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm text-slate-800 placeholder:text-slate-400 focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-100"
        />
      </label>
      {shown.length === 0 && <p className="text-xs text-slate-500">No question matches “{query}”.</p>}
      {shown.map(({ group, items }) => (
        <section key={group}>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-teal-700">{group}</h3>
          <Card className="divide-y divide-slate-100 p-0">
            {items.map(({ q, a }) => (
              <details key={q} className="group px-5 py-3.5" open={words.length > 0}>
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium text-slate-800 [&::-webkit-details-marker]:hidden">
                  {q}
                  <ChevronDown className="h-4 w-4 shrink-0 text-slate-400 transition-transform group-open:rotate-180" />
                </summary>
                <p className="mt-2 max-w-3xl text-xs leading-relaxed text-slate-600">{bold(a)}</p>
              </details>
            ))}
          </Card>
        </section>
      ))}
    </div>
  );
}
