"use client";

import Link from "next/link";
import {
  BookOpen, ClipboardCheck, FileSpreadsheet, ListChecks, MessageSquareMore, NotebookPen, PanelLeftOpen, Scale,
  SlidersHorizontal, Table2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import type { ClientPeek } from "@/lib/clientPeek";
import { cn } from "@/lib/utils";

// The checklist as the page will show it: its sections and steps are known before anything loads; only each step's
// state, the client's facts and the progress wait for the server
const GROUPS: { label: string; items: { label: string; icon: LucideIcon; books?: boolean }[]; papers?: boolean }[] = [
  { label: "1 · Set up", items: [{ label: "Files", icon: ClipboardCheck }, { label: "Client details", icon: SlidersHorizontal },
                                 { label: "Books", icon: BookOpen, books: true }] },
  { label: "2 · Trial balance", items: [{ label: "Accounts", icon: Table2 }] },
  { label: "3 · Working papers", items: [], papers: true },
  { label: "4 · Queries and journals", items: [{ label: "Queries", icon: MessageSquareMore }, { label: "Journals", icon: NotebookPen },
                                               { label: "Review points", icon: ListChecks }] },
  { label: "5 · Finish", items: [{ label: "Balance sheet check", icon: Scale }, { label: "Finish and download", icon: FileSpreadsheet }] },
];
const PILL_WIDTHS = ["w-10", "w-14", "w-8", "w-12"];

/** The client's workspace while it loads: the real checklist (name, sections, steps), with a sweep only on what is
 *  still coming (each step's state, the progress, the open tab's figures), so the page reads as half there. */
export function WorkspaceLoading({ peek, checklistOn }: { peek: ClientPeek | null; checklistOn: boolean }) {
  const groups = GROUPS.map((g) => ({ ...g, items: g.items.filter((i) => !i.books || peek?.source === "BANK_DEXT") }));
  const areas = peek?.areas?.length ? peek.areas : null;
  return (
    <div className="@container space-y-5" aria-busy="true" aria-label={peek ? `Loading ${peek.name}` : "Loading the client"}>
      <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-3 @[60rem]:gap-5">
        {/* Folded: the rail of icons */}
        <nav className={cn("flex w-12 flex-col items-center gap-1 rounded-xl border border-slate-200 bg-white py-2 shadow-sm",
                           checklistOn && "@[60rem]:hidden")}>
          <span className="mb-1 rounded-md p-2 text-slate-300"><PanelLeftOpen className="h-4 w-4" /></span>
          {groups.map((g, gi) => (
            <div key={g.label} className={cn("flex flex-col items-center gap-1", gi > 0 && "border-t border-slate-100 pt-1")}>
              {g.items.map(({ label, icon: Icon }) => (
                <span key={label} className="rounded-lg p-2 text-slate-400" title={label}><Icon className="h-4 w-4" /></span>
              ))}
            </div>
          ))}
        </nav>
        {/* Open: the checklist */}
        <nav className={cn("w-[14.5rem] space-y-4 rounded-xl border border-slate-200 bg-white p-3 shadow-sm",
                           checklistOn ? "hidden @[60rem]:block" : "hidden")}>
          <div className="px-1">
            <Link href="/" className="text-[11px] text-slate-400 transition hover:text-teal-700">← Clients</Link>
            {peek ? (
              <h1 className="mt-0.5 text-sm font-bold leading-snug text-slate-900">{peek.name}</h1>
            ) : (
              <div className="skeleton mt-1.5 h-4 w-36 rounded" />
            )}
            <div className="skeleton mt-2 h-2.5 w-44 rounded" />
          </div>
          <div className="border-b border-slate-100 px-1 pb-3">
            <div className="skeleton h-2.5 w-20 rounded" />
            <div className="skeleton mt-2 h-1 w-full rounded-full" />
          </div>
          {groups.map((g) => (
            <div key={g.label} className="space-y-4">
              <div>
                <p className="mb-1 flex items-center gap-1.5 px-2 text-[10.5px] font-bold uppercase tracking-wide text-slate-500">
                  <span className="grid h-4.5 w-4.5 place-items-center rounded-full bg-terra-100 text-[10px] text-terra-700">{g.label.split(" · ")[0]}</span>
                  {g.label.split(" · ")[1]}
                </p>
                <ul className="space-y-0.5">
                  {g.items.map(({ label, icon: Icon }, i) => (
                    <li key={label} className="flex items-center gap-2 px-2 py-1.5 text-xs font-semibold text-slate-500">
                      <Icon className="h-3.5 w-3.5 shrink-0" />
                      <span className="flex-1 truncate">{label}</span>
                      <span className={cn("skeleton h-3.5 rounded-full", PILL_WIDTHS[i % PILL_WIDTHS.length])} />
                    </li>
                  ))}
                </ul>
              </div>
              {g.papers && (
                <div>

                  <ul className="space-y-0.5">
                    {(areas || Array.from({ length: 6 }, () => "")).map((label, i) => (
                      <li key={i} className="flex items-center gap-2 px-2 py-1.5 text-xs font-semibold text-slate-500">
                        {label ? <span className="flex-1 truncate">{label}</span> : <span className="skeleton h-3 flex-1 rounded" />}
                        <span className={cn("skeleton h-3.5 rounded-full", PILL_WIDTHS[(i + 1) % PILL_WIDTHS.length])} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </nav>
        {/* The open tab, still coming: its title, its figures and its table, down to the bottom of the screen */}
        <div className="flex min-h-[calc(100vh-7rem)] min-w-0 flex-col gap-5">
          <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex items-center gap-3">
              <div className="skeleton h-9 w-9 rounded-lg" />
              <div className="flex-1 space-y-2">
                <div className="skeleton h-3.5 w-48 rounded" />
                <div className="skeleton h-2.5 w-2/3 rounded" />
              </div>
              <div className="skeleton h-8 w-28 rounded-lg" />
            </div>
            <div className="grid grid-cols-2 gap-3 pt-2 sm:grid-cols-4">
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="space-y-2 rounded-lg border border-slate-100 p-3">
                  <div className="skeleton h-2.5 w-16 rounded" />
                  <div className="skeleton h-4 w-24 rounded" />
                </div>
              ))}
            </div>
          </div>
          <div className="flex-1 overflow-hidden rounded-xl border border-slate-200 bg-white">
            <div className="flex gap-2 border-b border-slate-100 px-4 py-3">
              {[16, 20, 14, 18].map((w, i) => <div key={i} className="skeleton h-6 rounded-md" style={{ width: `${w * 4}px` }} />)}
            </div>
            <SkeletonRows rows={12} columns={4} quiet />
          </div>
        </div>
      </div>
    </div>
  );
}
