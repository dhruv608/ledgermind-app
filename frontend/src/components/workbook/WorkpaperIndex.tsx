"use client";

import { ArrowRight, Eye, ListTree } from "lucide-react";
import type { Reconciliation, Reconciliations } from "@/lib/api";
import { plural } from "@/lib/formatters";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { SectionHeader } from "@/components/ui/section-header";
import { StatusChip } from "@/components/ui/status-chip";
import { AuditFinding, ProposedJournal } from "@/types/engagement";

export type IndexTab = "review" | "journals" | "accounts" | "recs";

type Letter = "A" | "B" | "C" | "D" | "E" | "F" | "G" | "H" | "J" | "K";

// The workbook's sections, in its order: the sheet the viewer opens (its name prefix) and the tab the work is done on
// area: the working paper page the section is worked on (its own page, not an overview)
const SECTIONS: { letter: Letter; name: string; sheet: string; tab: IndexTab; area?: string }[] = [
  { letter: "A", name: "General checks", sheet: "A1", tab: "review" },
  { letter: "B", name: "ETB and journals", sheet: "B1", tab: "journals" },
  { letter: "C", name: "Fixed assets", sheet: "C1", tab: "recs", area: "fixed" },
  { letter: "D", name: "Stock", sheet: "D1", tab: "recs", area: "stock" },
  { letter: "E", name: "Debtors and prepayments", sheet: "E1", tab: "recs", area: "sales" },
  { letter: "F", name: "Bank", sheet: "F1", tab: "recs", area: "bank" },
  { letter: "G", name: "Creditors, VAT, payroll and loans", sheet: "G1", tab: "recs", area: "purchases" },
  { letter: "H", name: "Corporation tax", sheet: "H1", tab: "review", area: "tax" },
  { letter: "J", name: "Share capital and reserves", sheet: "J1", tab: "recs", area: "dla" },
  { letter: "K", name: "Profit and loss review", sheet: "K", tab: "review", area: "expenses" },
];

// A review point's section, from the middle part of its ref (U-FA-009 -> FA) or the whole ref for the other checks (CT-, V-, G1 ...)
const POINT_PART: Record<string, Letter> = {
  FA: "C", FAR: "C", CLS: "C", VAL: "C",
  STK: "D", INV: "D", WIP: "D",
  DEB: "E", PRE: "E",
  BNK: "F",
  CRD: "G", ACC: "G", PAY: "G", VAT: "G", DLA: "G", LOAN: "G", LSE: "G", SUB: "G", CIS: "G", DEP: "G",
  CT: "H", DT: "H",
  EQ: "J", DIV: "J",
  TB: "B", JNL: "B",
  REV: "K", COS: "K", EXP: "K", ENR: "K", LEV: "K", GRT: "K", INS: "K", LIC: "K", SVC: "K", REB: "K", ADJ: "K",
};
const POINT_REF: [RegExp, Letter][] = [
  [/^CT-/, "H"], [/^V-/, "G"], [/^CIS/, "G"], [/^G1$/, "C"], [/^G2$/, "E"], [/^G3$/, "G"], [/^G6$/, "G"],
  [/^G5$|^G9$|^PY-MOVE|^RES|^PRP/, "K"],
];

function pointSection(f: AuditFinding): Letter {
  for (const [re, letter] of POINT_REF) if (re.test(f.procedure_ref)) return letter;
  const part = f.procedure_ref.split("-")[1];
  return (part && POINT_PART[part]) || "A";
}

// A balance sheet account's section: by what it is agreed to, then where it sits on the balance sheet
function recSection(r: Reconciliation): Letter {
  const kind = r.key.split(":")[0];
  if (kind === "bank") return "F";
  if (kind === "far") return "C";
  if (kind === "ar" || kind === "s455") return "E";
  if (kind === "ct" || r.codes.includes(5310)) return "H";
  if (kind === "reserves") return "J";
  if (["ap", "vat", "cis_deducted", "cis_suffered"].includes(kind) || kind.startsWith("payroll")) return "G";
  if (r.codes.some((c) => c >= 4300 && c < 4400)) return "D";
  if (r.section === "Fixed assets") return "C";
  if (r.section === "Current assets") return "E";
  if (r.section === "Capital and reserves") return "J";
  if (r.section === "Must be nil") return "B";
  return "G";
}

interface Counts {
  accounts: number;
  agreed: number;
  differences: number;
  needsFigure: number;
  points: number;
  journals: number;
  mappings: number;
}

interface WorkpaperIndexProps {
  findings: AuditFinding[];
  journals: ProposedJournal[];
  recs: Reconciliations | null;
  mappingsToReview: number;
  reviewRan: boolean;
  /** The workbook's sheets can be opened (a workbook is built) */
  canView: boolean;
  onOpenSheet: (prefix: string) => void;
  onGoTo: (tab: IndexTab) => void;
  /** Opens a working paper area page */
  onOpenArea?: (key: string) => void;
}

/** The working papers section by section, as the workbook is lettered: what is agreed and what is still open in each. */
export function WorkpaperIndex({
  findings,
  journals,
  recs,
  mappingsToReview,
  reviewRan,
  canView,
  onOpenSheet,
  onGoTo,
  onOpenArea,
}: WorkpaperIndexProps) {
  const counts = Object.fromEntries(
    SECTIONS.map((s) => [s.letter, { accounts: 0, agreed: 0, differences: 0, needsFigure: 0, points: 0, journals: 0, mappings: 0 }]),
  ) as Record<Letter, Counts>;
  for (const r of recs?.rows || []) {
    if (r.section === "Profit and loss checks" && !["ct", "payroll", "payroll_er_ni", "payroll_er_pension"].includes(r.key)) continue;
    const c = counts[recSection(r)];
    c.accounts += 1;
    if (r.status === "DIFFERENCE") c.differences += 1;
    else if (r.status === "NEEDS_INPUT") c.needsFigure += 1;
    else c.agreed += 1;
  }
  // The tax computation (CT-01) is shown on its own, not counted as a point
  for (const f of findings) if (f.status === "OPEN" && f.procedure_ref !== "CT-01") counts[pointSection(f)].points += 1;
  counts.B.journals = journals.filter((j) => j.status === "PROPOSED").length;
  counts.B.mappings = mappingsToReview;

  const rows = SECTIONS.map((s) => {
    const c = counts[s.letter];
    const issues = c.differences + c.points + c.journals + c.mappings;
    const empty = c.accounts === 0 && issues === 0 && c.needsFigure === 0 && !["A", "B", "K"].includes(s.letter);
    // Open items show as soon as they are known; with none, a section is done only once the review has run
    const state: "issues" | "todo" | "done" | "empty" = empty ? "empty"
      : issues > 0 ? "issues" : c.needsFigure > 0 || !reviewRan ? "todo" : "done";
    // Where to go: the first thing open in the section
    const tab: IndexTab = c.mappings ? "accounts" : c.journals ? "journals" : c.differences || c.needsFigure ? "recs"
      : c.points ? "review" : s.tab;
    return { ...s, c, state, tab };
  });
  const done = rows.filter((r) => r.state === "done").length;
  const used = rows.filter((r) => r.state !== "empty").length;

  return (
    <Card className="overflow-hidden">
      <div className="p-5 pb-3">
        <SectionHeader
          icon={ListTree}
          title="Workpaper index"
          description="Each section of the workbook: what is agreed and what is still open."
          actions={<span className="text-xs font-medium text-slate-500">{done} of {used} sections done</span>}
        />
      </div>
      <ul className="divide-y divide-slate-100 border-t border-slate-100">
        {rows.map((r) => (
          <li key={r.letter} className={cn("flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-center", r.state === "empty" && "opacity-60")}>
            <div className="flex min-w-0 flex-1 items-center gap-3">
              <span
                // The section's letter is its Excel sheet (A, B ...), not a status: the chip on the right says where it stands
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-100 font-mono text-xs font-semibold text-slate-500"
                title={`Excel sheet ${r.letter}`}
              >
                {r.letter}
              </span>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-900">{r.name}</p>
                <p className="truncate text-[11px] text-slate-500">{detail(r.letter, r.c, r.state, reviewRan, findings.length > 0)}</p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2 pl-10 sm:pl-0">
              <StatusChip tone={r.state === "done" ? "success" : r.state === "issues" ? "warning" : r.state === "todo" ? "info" : "neutral"}>
                {r.state === "done" ? "Done" : r.state === "issues" ? "Open items" : r.state === "todo" ? "To do" : "Not used"}
              </StatusChip>
              {canView && r.state !== "empty" && (
                <button
                  type="button"
                  onClick={() => onOpenSheet(r.sheet)}
                  className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-600 transition hover:border-teal-300 hover:text-teal-800"
                  title={`Open sheet ${r.sheet} in the workbook`}
                >
                  <Eye className="h-3 w-3" />
                  Sheet
                </button>
              )}
              {r.state !== "empty" && (
                <button
                  type="button"
                  onClick={() => (r.area && onOpenArea && !r.c.mappings && !r.c.journals ? onOpenArea(r.area) : onGoTo(r.tab))}
                  className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-teal-800 hover:bg-teal-50"
                >
                  Open
                  <ArrowRight className="h-3 w-3" />
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

// One line under the section's name: what is open first, then what is agreed
function detail(letter: Letter, c: Counts, state: string, reviewRan: boolean, hasPoints: boolean): string {
  if (state === "empty") return "No accounts in this section";
  // Points from an earlier run are shown: the review ran, something changed since
  if (letter === "A" && !reviewRan) return hasPoints ? "The review is out of date: run it again" : "The review has not run yet";
  const parts: string[] = [];
  if (c.mappings) parts.push(`${plural(c.mappings, "mapping")} to check`);
  if (c.journals) parts.push(`${plural(c.journals, "journal")} to approve`);
  if (c.differences) parts.push(`${plural(c.differences, "difference")}`);
  if (c.needsFigure) parts.push(`${plural(c.needsFigure, "balance")} to agree`);
  if (c.points) parts.push(`${plural(c.points, "review point")} open`);
  if (c.accounts) parts.push(`${c.agreed} of ${plural(c.accounts, "account")} agreed`);
  if (!parts.length) return letter === "A" ? "No open general points" : letter === "B" ? "All journals done" : letter === "K" ? "No open profit and loss points" : "Nothing open";
  return parts.join(" · ");
}
