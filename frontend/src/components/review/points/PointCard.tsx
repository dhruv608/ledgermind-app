"use client";

import { askLedge } from "@/components/assistant/AskLedge";
import { useState } from "react";
import { BookOpen, Check, CheckCircle2, MessageSquarePlus, Sparkles, StickyNote, X } from "lucide-react";
import { toast } from "@/lib/notify";
import { isInfoPoint } from "@/components/review/points/pointInfo";
import { decisionFor, splitClientText, tidy } from "@/components/review/points/pointDecision";
import type { AuditFinding, FigureCell, PointFigures, ProposedJournal } from "@/types/engagement";
import type { PointSignoff, SignoffRole } from "@/lib/api";
import { api } from "@/lib/api";
import { areaOfPoint } from "@/lib/areas";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { nameVatBoxes } from "@/lib/vatBoxes";
import { text } from "@/lib/ui";
import { formatCurrency, serverDate } from "@/lib/formatters";
import { ContactLedger } from "@/components/review/workpapers/ContactLedger";

// Severity as a coloured dot and word: colour is kept for status, so the card's text stays calm
const SEVERITY: Record<string, { dot: string; text: string }> = {
  CRITICAL: { dot: "bg-rose-500", text: "text-rose-700" },
  HIGH: { dot: "bg-amber-500", text: "text-amber-700" },
  MEDIUM: { dot: "bg-sky-500", text: "text-sky-700" },
  LOW: { dot: "bg-slate-400", text: "text-slate-500" },
};

const money = (n: number) => formatCurrency(Math.abs(n));

// A question to the client, or the CT600 guide's question and evidence lines, in a point's text
const QUESTION = /(?:Query to the client|Client question|Question to the client|Client query|Question)\s*:\s*/i;
const EVIDENCE = /(?:Evidence needed|Evidence required|Evidence)\s*:\s*/i;
const REFERENCE = /^Reference\s*:\s*/i;
// A sentence that tells the accountant what to do
const DO_WORDS = /^(?:If\b.*?[,:]\s*)?(Enter|Check|Confirm|Ask|Post|Upload|Approve|Reject|Clear|Decide|Agree|Find|Set|Release|Move|Correct|Reverse|Type|Add|Answer|Review|Request|Tell|Mark|Change|Choose|Make|Get|Send|Raise|Write|Book|Claim|Record|Look|Remove|Disclose|Match)\b/;
// The sentence naming the proposed journal (shown in its own box), to its full stop: a stop that ends the sentence,
// never the decimal point in an amount ('(£223.02) / Cr 4154 ...')
const JOURNAL_PROPOSED = /(?:A journal is proposed|Suggested journal)[^:]*:[\s\S]*?(?:\.(?=\s+[A-Z(])|\.?$)/gi;
// Where a VAT difference goes: 'correct on the next return (Method 1)' / 'disclose to HMRC on form VAT652 (Method 2)'
const VAT_ROUTE = /:\s*((?:correct on the next return|disclose to HMRC on form VAT652)[^.(]*(?:\([^)]*\))?)/i;

export interface PointParts {
  /** The issue: the card's heading */
  issue: string;
  /** Why: the detail with its figures */
  detail: string;
  /** The words for the client (a client query), else empty */
  ask: string;
  /** What we do (our steps), else empty */
  ours: string;
  clientQuery: boolean;
}

const sentenceEnd = (s: string) => (/[.?!]$/.test(s) ? s : `${s}.`);

/** A point's Issue / Detail / Ask / Our step: the title is the issue, a question to the client is the ask (only
 * words the client can read), the sentences that say what we do are our step, the rest is the detail with its
 * figures. */
export function pointParts(f: AuditFinding, hasJournal: boolean): PointParts {
  let body = (f.finding_details || "").trim();
  const ask: string[] = [];
  const ours: string[] = [];
  let clientQuery = false;
  // Lines of their own: 'Question: ...', 'Evidence needed: ...', 'Reference: ...' (the CT600 guide)
  const keep: string[] = [];
  for (const raw of body.split(/\n+/)) {
    const line = raw.trim();
    if (!line) continue;
    const q = line.match(QUESTION);
    if (q && q.index !== undefined) {
      const before = line.slice(0, q.index).trim();
      if (before) keep.push(before);
      const split = splitClientText(line.slice(q.index + q[0].length).trim());
      if (split.client) ask.push(split.client);
      if (split.ours) ours.push(split.ours);
      clientQuery = true;
    } else if (/^(?:Evidence needed|Evidence required|Evidence)\s*:/i.test(line)) {
      // What to send is the client's; a reference after it (the law) stays in the detail
      const [what, ref] = line.replace(EVIDENCE, "").trim().split(/\s*(?=Ref:)/);
      ask.push(`Please send: ${sentenceEnd(what.replace(/\.$/, "").trim())}`);
      if (ref) keep.push(ref);
    } else if (REFERENCE.test(line)) {
      keep.push(`(${line.replace(REFERENCE, "").trim()})`);
    } else {
      keep.push(line);
    }
  }
  body = keep.join(" ");
  // 'Evidence: ...' inside a sentence (the industry library): what to send, for the client
  body = body.replace(/\s*Evidence(?: needed| required)?:\s*([^.]*?)\.(?=\s|$)/gi, (_, what: string) => {
    ask.push(`Please send: ${sentenceEnd(what.trim())}`);
    return "";
  });
  if (body.search(JOURNAL_PROPOSED) >= 0) {       // search(), not test(): a global pattern keeps its place between cards
    body = body.replace(JOURNAL_PROPOSED, "").trim();
  }
  // The route is our step, said once (not again in the detail)
  const route = body.match(VAT_ROUTE);
  if (route) {
    ours.push(`If not explained: ${route[1].trim()}.`);
    body = body.replace(route[0], "").replace(/\s+\./g, ".");
  }
  // Sentences that say what to do are our step; the rest stays as the detail
  const detail: string[] = [];
  for (const s of body.split(/(?<=[.!?])\s+(?=[A-Z(£])/)) {
    const t = s.trim();
    if (!t) continue;
    if (DO_WORDS.test(t) && ours.length < 3) ours.push(t);
    else detail.push(t);
  }
  if (ask.length) clientQuery = true;
  // VAT return boxes named for the reader ('Box 1' -> 'Box 1 (VAT on sales)'), on the screen only
  return {
    issue: tidy(nameVatBoxes(f.finding_title)),
    detail: tidy(nameVatBoxes(detail.join(" ").trim() || f.procedure_name)),
    ask: tidy(nameVatBoxes(ask.join(" "))),
    ours: hasJournal ? "" : tidy(nameVatBoxes(ours.join(" "))),
    clientQuery,
  };
}

// A duplicates point about a supplier or customer (or the list of suppliers with bills and direct payments): its
// ledger can be shown under it
const hasContactLedger = (f: AuditFinding) =>
  f.procedure_ref === "G5" && /^(supplier |customer |Suppliers with bills and direct payments$)/.test(f.source_row_ref || "");

const ROLES: { role: SignoffRole; short: string; name: string }[] = [
  { role: "PREPARER", short: "P", name: "Preparer" },
  { role: "REVIEWER", short: "R", name: "Reviewer" },
  { role: "PARTNER", short: "Pt", name: "Partner" },
];

/** One review point as a card with one decision (figures filled, one yes / no action, the proposed journal beside
 * it, initials and date): what it is and how much, why, then the decision box with its buttons; clearing always
 * keeps a reason. */
export function PointCard({
  engagementId, finding: f, journal, signoffs = [], onSignoffs, onClear, onJournalsUpdated, extra,
  onRaiseQuery, queries = 0, onNote, notes = 0, links, showArea = false, children,
}: {
  engagementId: string;
  finding: AuditFinding;
  /** The journal this point proposes, if any */
  journal?: ProposedJournal;
  signoffs?: PointSignoff[];
  onSignoffs?: (next: Record<string, PointSignoff[]>) => void;
  /** Clear the point, with the reason kept on the file */
  onClear?: (id: number, note?: string) => Promise<void> | void;
  onJournalsUpdated?: () => void;
  /** The point's own choice buttons (the dividend or s455), shown as its decision */
  extra?: React.ReactNode;
  /** Raise a query on this point (the area's Queries tab), and how many were raised on it */
  onRaiseQuery?: (f: AuditFinding) => void;
  queries?: number;
  /** Write a note on this point (the area's Notes tab), and how many there are */
  onNote?: (f: AuditFinding) => void;
  notes?: number;
  /** Links of the screen showing the card (the point's ledger lines), in its footer */
  links?: React.ReactNode;
  /** Name the point's area on its top line (the Review points tab, where points of every area are listed) */
  showArea?: boolean;
  /** Shown under the card's detail */
  children?: React.ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [showLedger, setShowLedger] = useState(false);
  const [allDetail, setAllDetail] = useState(false);
  // The clear form: open with its reason ready (the answer chosen), saved with the point
  const [clearing, setClearing] = useState<string | null>(null);
  const waiting = journal?.status === "PROPOSED";
  const parts = pointParts(f, Boolean(waiting));
  // A point that only tells the accountant something: marked, and nothing to decide
  const info = isInfoPoint(f, waiting);
  const sev = SEVERITY[f.severity] || SEVERITY.LOW;
  const open = f.status === "OPEN";
  const decision = decisionFor(f);
  const amount = Number(f.quantified_amount) || 0;
  // With a figures table the sentence repeats its numbers: two lines of it, the rest on Show more
  const figures = f.figures && f.figures.rows?.length ? f.figures : null;
  const longDetail = parts.detail.length > (figures ? 160 : 260);

  const sign = async (role: SignoffRole, signed: boolean) => {
    setBusy(true);
    try {
      onSignoffs?.(await api.signOffPoint(engagementId, f.id, role, signed));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the sign-off");
    } finally {
      setBusy(false);
    }
  };
  // V-F07 (the returns look like the flat rate scheme): the accountant confirms it here; the setup then says flat rate
  // and the checks run again, which propose the flat rate surplus journal
  const setFlatRate = async () => {
    setBusy(true);
    try {
      await api.updateProfile(engagementId, { vat_scheme: "FLAT_RATE" });
      toast.success("VAT scheme set to flat rate: the checks are running again");
      onJournalsUpdated?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not change the VAT scheme");
    } finally {
      setBusy(false);
    }
  };
  // Use of home (U-ADJ-004, added per job by the accountant, never a firm setting): saved as the client
  // questions save it, so the review proposes the journal (Dr rent / Cr director's loan), or answers no
  const saveHome = async (value: number) => {
    setBusy(true);
    try {
      const profile = await api.getProfile(engagementId);
      const setup = ((profile as any).setup || {}) as Record<string, any>;
      await api.updateProfile(engagementId, {
        setup: { ...setup, people: { ...(setup.people || {}), use_of_home: value } },
      } as any);
      toast.success(value > 0 ? `Use of home ${formatCurrency(value)} saved: the journal is proposed when the checks run`
        : "Saved: the director does not work from home");
      onJournalsUpdated?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save use of home");
    } finally {
      setBusy(false);
    }
  };
  const act = async (action: "APPROVE" | "REJECT") => {
    if (!journal) return;
    setBusy(true);
    try {
      await api.actOnJournal(journal.id, action);
      toast.success(action === "APPROVE" ? "Journal approved" : "Journal rejected");
      onJournalsUpdated?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the decision");
    } finally {
      setBusy(false);
    }
  };
  // No: a query to the client on this point (the area's Queries form when the screen has one, else raised at once)
  const askClient = async () => {
    if (onRaiseQuery) return onRaiseQuery(f);
    setBusy(true);
    try {
      await api.raiseQuery(engagementId, {
        title: parts.issue, detail: parts.ours || parts.detail, audience: "CLIENT", area: areaOfPoint(f).key,
        amount, finding_id: f.id,
      });
      toast.success("Query raised: it goes in the client email on the Queries tab");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not raise the query");
    } finally {
      setBusy(false);
    }
  };
  const clear = async () => {
    if (!onClear || clearing === null) return;
    setBusy(true);
    try {
      await onClear(f.id, clearing.trim() || undefined);
      setClearing(null);
    } finally {
      setBusy(false);
    }
  };

  // The decision: the question, and its buttons (the journal's, the point's own, or clear with a reason)
  const special = f.procedure_ref === "V-F07" ? "flat" : f.procedure_ref === "U-ADJ-004" && !journal && amount > 0 ? "home" : null;
  const question = extra ? "Declare a dividend, or charge s455 on the overdrawn loan?"
    : waiting ? `Post journal ${journal!.journal_ref}?`
    : special === "flat" ? "Do the returns use the flat rate scheme?"
    : special === "home" ? "Does the director work from home?"
    : info ? "For information: nothing to decide."
    : parts.clientQuery ? "Has the client answered, and is it fine?"
    : decision.question;
  const fine = info ? "Noted" : parts.clientQuery ? "Answered, fine" : decision.fine;
  const reason = info ? "Noted" : parts.clientQuery ? "Client answered: " : decision.reason;
  const button = "h-7 text-xs";
  const choiceButtons = !open || clearing !== null ? null : extra ? extra
    : waiting ? (
      <>
        <Button size="sm" className={cn(button, "bg-terra-600 hover:bg-terra-700")} disabled={busy} onClick={() => act("APPROVE")}>
          <Check className="mr-1 h-3.5 w-3.5" /> Yes, approve {money(Number(journal!.amount))}
        </Button>
        <Button variant="outline" size="sm" className={button} disabled={busy} onClick={() => act("REJECT")}>
          <X className="mr-1 h-3.5 w-3.5" /> No, reject
        </Button>
      </>
    ) : special === "flat" ? (
      <>
        <Button size="sm" className={cn(button, "bg-terra-600 hover:bg-terra-700")} disabled={busy} onClick={setFlatRate}>
          <Check className="mr-1 h-3.5 w-3.5" /> Yes, flat rate
        </Button>
        {onClear && <Button variant="outline" size="sm" className={button} onClick={() => setClearing("Not on the flat rate scheme")}>No</Button>}
      </>
    ) : special === "home" ? (
      <>
        <Button size="sm" className={cn(button, "bg-terra-600 hover:bg-terra-700")} disabled={busy} onClick={() => saveHome(amount)}>
          <Check className="mr-1 h-3.5 w-3.5" /> Yes, add {formatCurrency(amount)}
        </Button>
        <Button variant="outline" size="sm" className={button} disabled={busy} onClick={() => saveHome(0)}>
          <X className="mr-1 h-3.5 w-3.5" /> No
        </Button>
      </>
    ) : onClear ? (
      <>
        <Button size="sm" className={cn(button, "bg-terra-600 hover:bg-terra-700")} onClick={() => setClearing(reason)}>
          <CheckCircle2 className="mr-1 h-3.5 w-3.5" /> {fine}
        </Button>
        {!info && !parts.clientQuery && !decision.ours && (
          <Button variant="outline" size="sm" className={button} disabled={busy} onClick={askClient}>
            <MessageSquarePlus className="mr-1 h-3.5 w-3.5" /> No, ask the client
          </Button>
        )}
      </>
    ) : null;

  return (
    <li className={cn("rounded-xl border bg-white shadow-2xs", open ? "border-slate-200" : "border-slate-100 opacity-80")}>
      {/* 1. How serious, which area, how much */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-3.5">
        <p className="flex min-w-0 flex-1 items-center gap-2 text-xs">
          <span className={cn("inline-flex shrink-0 items-center gap-1.5 font-semibold", sev.text)}>
            <span className={cn("h-2 w-2 rounded-full", sev.dot)} />
            {f.severity.charAt(0) + f.severity.slice(1).toLowerCase()}
          </span>
          {showArea && <span className="truncate text-slate-500" title={`${f.procedure_name} · ${f.procedure_ref}`}>{areaOfPoint(f).label}</span>}
          {parts.clientQuery && <span className="rounded-full bg-terra-50 px-2 py-0.5 text-[11px] font-semibold text-terra-700">Client query</span>}
          {info && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600">For information</span>}
        </p>
        {amount > 0 && <span className="text-sm font-semibold tabular-nums text-slate-900" title="The amount this point is about">{money(amount)}</span>}
      </div>

      {/* 2. The issue, as the card's heading */}
      <h4 className={cn("px-4 pt-1", text.card)} title={`${f.procedure_name} · ${f.procedure_ref}`}>{parts.issue}</h4>

      {/* 3. Why: the detail with its figures */}
      <div className="px-4 pt-1.5">
        <p className={cn("whitespace-pre-line text-[13px] leading-relaxed text-slate-600", longDetail && !allDetail && (figures ? "line-clamp-2" : "line-clamp-3"))}>{parts.detail}</p>
        {longDetail && (
          <button type="button" onClick={() => setAllDetail((v) => !v)} className="mt-0.5 text-xs font-medium text-teal-700 hover:underline">
            {allDetail ? "Show less" : "Show more"}
          </button>
        )}
      </div>

      {/* 4. The figures it turns on, as a small table */}
      {figures && <FiguresTable figures={figures} />}

      {showLedger && <div className="mx-4 mt-3"><ContactLedger engagementId={engagementId} findingId={f.id} /></div>}
      {children && <div className="mx-4 mt-3">{children}</div>}

      {/* 5. The one decision */}
      <div className={cn("mx-4 mb-3 mt-3 rounded-lg border px-3 py-2.5",
                         open && !info ? "border-terra-100 bg-terra-50/60" : "border-slate-100 bg-slate-50/70")}>
        {parts.ask && (
          <div className="mb-2">
            <p className={cn(text.label, "text-terra-700")}>Ask the client</p>
            <p className="mt-0.5 text-[13px] leading-relaxed text-slate-900">{parts.ask}</p>
          </div>
        )}
        {open ? (
          <>
            <p className={cn(text.label, info ? "text-slate-500" : "text-terra-700")}>Decide</p>
            <p className="mt-0.5 text-[13px] font-medium leading-relaxed text-slate-900">{question}</p>
            {waiting && (
              <p className="mt-1 text-xs text-slate-600">
                {journal!.lines && journal!.lines.length > 2
                  ? `${journal!.lines.length} lines`
                  : `Dr ${journal!.debit_code} ${journal!.debit_name} / Cr ${journal!.credit_code} ${journal!.credit_name}`}
                <span className="ml-1.5 font-mono font-semibold tabular-nums text-slate-900">{money(Number(journal!.amount))}</span>
              </p>
            )}
            {parts.ours && <p className="mt-1 text-xs leading-relaxed text-slate-600"><span className="font-semibold text-slate-700">Our step: </span>{parts.ours}</p>}
            {journal && !waiting && (
              <p className={cn("mt-1 text-xs font-semibold", journal.status === "APPROVED" ? "text-emerald-700" : "text-slate-500")}>
                Journal {journal.journal_ref} {journal.status === "APPROVED" ? "approved" : "rejected"}
              </p>
            )}
            {choiceButtons && <div className="mt-2 flex flex-wrap gap-1.5">{choiceButtons}</div>}
            {clearing !== null && (
              <form onSubmit={(e) => { e.preventDefault(); clear(); }} className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
                <input
                  autoFocus
                  value={clearing}
                  onChange={(e) => setClearing(e.target.value)}
                  placeholder="Why is this fine? (kept with the point)"
                  className="h-8 flex-1 rounded-md border border-slate-300 bg-white px-2.5 text-xs focus:outline-none focus:ring-2 focus:ring-teal-200"
                />
                <div className="flex gap-1.5">
                  <Button type="button" variant="ghost" size="sm" className="h-8 px-2" onClick={() => setClearing(null)} title="Cancel">
                    <X className="h-3.5 w-3.5" />
                  </Button>
                  <Button type="submit" size="sm" className="h-8 text-[11px]" disabled={busy}>
                    <Check className="mr-1 h-3 w-3" /> Clear point
                  </Button>
                </div>
              </form>
            )}
          </>
        ) : (
          <p className="text-xs text-emerald-800">
            <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" />
            Cleared{f.cleared_at ? ` ${serverDate(f.cleared_at).toLocaleDateString("en-GB")}` : ""}{f.cleared_note ? `: ${f.cleared_note}` : ""}
          </p>
        )}
      </div>

      {/* 6. Sign-off and the point's links */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-b-xl border-t border-slate-100 bg-slate-50/50 px-4 py-1.5">
        <div className="flex items-center gap-1.5" aria-label="Sign-off">
          <span className="mr-1 text-[11px] text-slate-500">Sign-off</span>
          {ROLES.map(({ role, short, name }) => {
            const s = signoffs.find((x) => x.role === role);
            const when = s?.signed_at ? serverDate(s.signed_at).toLocaleDateString("en-GB") : "";
            return (
              <button
                key={role}
                type="button"
                disabled={busy}
                onClick={() => sign(role, Boolean(s))}
                title={s ? `${name}: ${s.initials} on ${when} (click to remove)` : `Sign off as ${name.toLowerCase()}`}
                aria-label={s ? `${name} signed off by ${s.initials} on ${when}` : `Sign off as ${name.toLowerCase()}`}
                className={cn("flex h-6 min-w-6 items-center justify-center rounded-full px-1.5 text-[10px] font-bold",
                              s ? "bg-teal-600 text-white" : "border border-dashed border-slate-300 text-slate-400 hover:border-teal-500 hover:text-teal-700")}
              >
                {s ? s.initials : short}
              </button>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {links}
          {hasContactLedger(f) && (
            <Button variant="ghost" size="sm" className={cn("h-7 text-xs hover:text-teal-800", showLedger ? "text-teal-800" : "text-slate-500")}
                    onClick={() => setShowLedger((v) => !v)}>
              <BookOpen className="mr-1 h-3.5 w-3.5" /> {showLedger ? "Hide ledger" : "Ledger"}
            </Button>
          )}
          <Button variant="ghost" size="sm" className="h-7 text-xs text-slate-500 hover:text-terra-700"
                  onClick={() => askLedge(`Explain point ${f.procedure_ref} (id ${f.id}): ${f.finding_title}`)}>
            <Sparkles className="mr-1 h-3.5 w-3.5 text-terra-500" /> Explain
          </Button>
          {onRaiseQuery && parts.clientQuery && (
            <Button variant="ghost" size="sm" className="h-7 text-xs text-slate-500 hover:text-teal-800" onClick={() => onRaiseQuery(f)}>
              <MessageSquarePlus className="mr-1 h-3.5 w-3.5" /> Raise query{queries > 0 ? ` (${queries} raised)` : ""}
            </Button>
          )}
          {onNote && (
            <Button variant="ghost" size="sm" className="h-7 text-xs text-slate-500 hover:text-teal-800" onClick={() => onNote(f)}>
              <StickyNote className="mr-1 h-3.5 w-3.5" /> Notes ({notes})
            </Button>
          )}
        </div>
      </div>
    </li>
  );
}

// A money cell as the accounts show it: £1,234.56, a minus in brackets
const cell = (v: FigureCell) => (typeof v === "number" ? (v < 0 ? `(${money(v)})` : money(v)) : v ?? "");

/** The point's figures: a heading row, the figure rows (the one the decision turns on in bold), and how many more. */
function FiguresTable({ figures }: { figures: PointFigures }) {
  const [label, ...cols] = figures.columns;
  return (
    <div className="mx-4 mt-2.5 overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full text-xs">
        {(label || cols.some(Boolean)) && (
          <thead className="bg-slate-50 text-[11px] font-semibold text-teal-800">
            <tr>
              <th className="px-3 py-1.5 text-left font-semibold">{label}</th>
              {cols.map((c, i) => <th key={i} className="px-3 py-1.5 text-right font-semibold">{c}</th>)}
            </tr>
          </thead>
        )}
        <tbody className="divide-y divide-slate-100">
          {figures.rows.map((r, i) => (
            <tr key={i} className={r.strong ? "bg-teal-50/60 font-semibold text-slate-900" : "text-slate-700"}>
              <td className="px-3 py-1.5">{r.label}</td>
              {r.values.map((v, j) => (
                <td key={j} className={cn("whitespace-nowrap px-3 py-1.5 text-right", typeof v === "number" && "font-mono tabular-nums")}>{cell(v)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {figures.more ? <p className="border-t border-slate-100 px-3 py-1 text-[11px] text-slate-500">and {figures.more} more</p> : null}
    </div>
  );
}
