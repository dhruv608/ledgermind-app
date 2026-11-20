// Review points that only tell the accountant something: information-only lines are kept apart from items
// that need action, and only action items need a response. They are shown, marked "For
// information", and left out of the "to look at" counts. A point with a journal waiting is always to act on.
import type { AuditFinding } from "@/types/engagement";

// Kinds that report what the app read or worked out, with nothing to decide
const INFO_REFS = new Set([
  "U-FAR-001",   // the fixed asset register was read (its agreement to the books is its own point)
  "U-FAR-002",   // the register agrees to the books
  "CT-DON-001",  // donations relieved as qualifying donations
  "U-OB-003",    // a balance opened on another code, no effect on the reserves
]);

export function isInfoPoint(f: AuditFinding, hasJournal = false): boolean {
  if (hasJournal) return false;
  if (INFO_REFS.has(f.procedure_ref)) return true;
  // The payroll report agrees with the books (no difference)
  if (f.procedure_ref === "U-PAY-001" && /\bagrees\b/i.test(f.finding_title || "")) return true;
  // A small VAT box difference that the next return corrects (VAT Notice 700/45 method 1), at low severity
  if ((f.procedure_ref === "V-C01" || f.procedure_ref === "V-D01") && f.severity === "LOW"
      && /correct on the next return/i.test(f.finding_details || "")) return true;
  return false;
}

/** The ids of points with a journal still to decide (those are never information only). */
export function withJournalIds(journals: { finding_id?: number | null; status: string }[]): Set<number> {
  return new Set(journals.filter((j) => j.status === "PROPOSED" && j.finding_id).map((j) => j.finding_id as number));
}
