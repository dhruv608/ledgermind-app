/**
 * Where each part of a job stands, defined once. The sidebar, the area page's header, the 'Next' line and the
 * 'n of n done' count all read these, so two screens can never say different things about the same item.
 */
import type { AuditFinding, ProposedJournal } from "@/types/engagement";
import type { JobQueries, Reconciliation } from "@/lib/api";
import { isInfoPoint, withJournalIds } from "@/components/review/points/pointInfo";

export type Tone = "stop" | "needs" | "fix" | "wait" | "done";
export type State = { text: string; tone: Tone };

const s = (n: number, one: string, many = `${one}s`) => (n === 1 ? one : many);

/** Points the accountant must act on: open, not the tax computation (shown on its own), not for information only */
export function pointsToAct(findings: AuditFinding[], journals: ProposedJournal[]): AuditFinding[] {
  const ids = withJournalIds(journals);
  return findings.filter((f) => f.status === "OPEN" && f.procedure_ref !== "CT-01" && !isInfoPoint(f, ids.has(f.id)));
}

/** The fixed asset register's rows (far:<class>:...) are one line per asset class, as the area page shows them */
function balanceLines(ties: Reconciliation[]): Reconciliation["status"][] {
  const classes = new Map<string, Reconciliation["status"][]>();
  const rest: Reconciliation["status"][] = [];
  for (const t of ties) {
    if (t.key.startsWith("far:")) {
      const name = t.key.split(":")[1];
      classes.set(name, [...(classes.get(name) || []), t.status]);
    } else rest.push(t.status);
  }
  const perClass = [...classes.values()].map((st): Reconciliation["status"] =>
    st.includes("DIFFERENCE") ? "DIFFERENCE" : st.every((x) => x === "MATCHED") ? "MATCHED" : "NEEDS_INPUT");
  return [...rest, ...perClass];
}

/**
 * One area (bank, VAT, payroll ...): the sidebar's short words and the area header's long words, in one order:
 * a difference nothing explains, then a difference the proposed journals would clear, then open points, then a
 * balance waiting for its document, then done.
 */
export function areaState(findings: AuditFinding[], journals: ProposedJournal[], ties: Reconciliation[],
                          reviewRan: boolean): { short: State; long: State | null } {
  const open = pointsToAct(findings, journals);
  const openIds = new Set(open.map((f) => f.id));
  const proposed = journals.filter((j) => j.status === "PROPOSED");
  // A journal to decide sits on its point: counted once, with the point; only one whose point is not open adds
  const points = open.length + proposed.filter((j) => !(j.finding_id && openIds.has(j.finding_id))).length;
  const lines = balanceLines(ties);
  const differ = lines.filter((x) => x === "DIFFERENCE").length;
  const toAgree = lines.filter((x) => x === "NEEDS_INPUT").length;

  if (differ && !proposed.length)
    return { short: { text: `${differ} ${s(differ, "differs", "differ")}`, tone: "stop" }, long: { text: "Unexplained", tone: "stop" } };
  if (differ)
    return { short: { text: `${proposed.length} ${s(proposed.length, "fix", "fixes")} ready`, tone: "fix" },
             long: { text: "Explained by proposed journals", tone: "fix" } };
  if (points)
    return { short: { text: `${points} to look at`, tone: "needs" },
             long: { text: lines.length ? `Tied, ${points} ${s(points, "point")} open` : "To look at", tone: "needs" } };
  if (toAgree)
    return { short: { text: `${toAgree} to agree`, tone: "wait" }, long: { text: "Waiting for a document", tone: "wait" } };
  if (!reviewRan && !lines.length) return { short: { text: "Done", tone: "done" }, long: null };
  return { short: { text: "Done", tone: "done" }, long: { text: lines.length ? "Tied" : "Nothing to look at", tone: "done" } };
}

/** Queries: blocking first; then the accountant's own (for you), then the client's (with the client) */
export function queriesState(q: Pick<JobQueries, "open" | "blocking"> & Partial<Pick<JobQueries, "counts">> | null): State | undefined {
  if (!q) return undefined;
  if (q.blocking) return { text: `${q.blocking} blocking`, tone: "stop" };
  const client = q.counts ? q.counts.CLIENT?.open || 0 : q.open;
  const ours = q.counts ? (q.counts.ACCOUNTANT?.open || 0) + (q.counts.INTERNAL?.open || 0) : 0;
  if (ours) return { text: `${ours} for you`, tone: "needs" };
  if (client) return { text: `${client} with client`, tone: "wait" };
  return { text: "Done", tone: "done" };
}

/** Coding review: what its two tabs count (re-analysis moves and questions, recommended mispostings) */
export function codingState(re: { moves: number; questions: number } | null,
                            mis: { recommended: number } | null): State | null {
  if (!re && !mis) return null;
  const n = (re?.moves || 0) + (re?.questions || 0) + (mis?.recommended || 0);
  return n ? { text: `${n} to look at`, tone: "needs" } : { text: "Done", tone: "done" };
}

/** The review: being checked now, never run, out of date, points open, or done */
export function reviewState(running: boolean, ranAt: string | null | undefined, stale: boolean, openPoints: number): State {
  if (running) return { text: "Updating…", tone: "wait" };
  if (!ranAt) return { text: "Not run", tone: "wait" };
  if (stale) return { text: "Out of date", tone: "needs" };
  return openPoints ? { text: `${openPoints} to look at`, tone: "needs" } : { text: "Done", tone: "done" };
}

/** Something for the accountant to do now (not waiting on someone else, not done) */
export const isToDo = (st: State | null | undefined) => Boolean(st && (st.tone === "stop" || st.tone === "needs" || st.tone === "fix"));
