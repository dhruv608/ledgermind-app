// Where a client stands: the stage filters, deadlines, the four year-end steps and the year-end date helpers.
import { ClientListItem } from "@/types/engagement";
import { plural } from "@/lib/formatters";

export type StageFilter = "all" | "overdue" | "soon" | "review" | "final";

// "Ready to review" shows only when a client is in it (never an empty, unused filter)
export const STAGES: { id: StageFilter; label: string; hint: string; optional?: boolean }[] = [
  { id: "all", label: "All", hint: "Every client" },
  { id: "overdue", label: "Overdue", hint: "Accounts or a VAT return past its due date" },
  { id: "soon", label: "Due soon", hint: "Accounts due within 60 days or a VAT return within 14 days" },
  { id: "review", label: "Ready to review", hint: "A draft workbook is built: to review and finish", optional: true },
  { id: "final", label: "Done", hint: "Finished: the final workbook is built" },
];

/** Days from today to a yyyy-mm-dd date (negative when passed), or null */
const daysTo = (iso?: string | null) => (iso ? Math.round((new Date(iso).getTime() - Date.now()) / 86400000) : null);
// The same limits as the deadline tags on the company rows: a finished year's accounts no longer count
const deadlines = (c: ClientListItem) => {
  const acc = c.workbook_state === "final" ? null : daysTo(c.accounts_due);
  const vat = c.vat_period_end ? daysTo(c.vat_due) : null;
  return {
    overdue: (acc !== null && acc < 0) || (vat !== null && vat < 0),
    soon: (acc !== null && acc >= 0 && acc <= 60) || (vat !== null && vat >= 0 && vat <= 14),
  };
};

export const matchesStage = (c: ClientListItem, stage: StageFilter) => {
  if (stage === "overdue") return deadlines(c).overdue;
  if (stage === "soon") return deadlines(c).soon;
  if (stage === "review") return c.workbook_state === "draft";
  if (stage === "final") return c.workbook_state === "final";
  return true;
};

// The year-end in four steps: done, part done (amber) or not started
export type StepState = "done" | "part" | "todo";
export const stepsOf = (c: ClientListItem): { label: string; state: StepState; hint: string }[] => [
  { label: "Setup", state: c.setup_confirmed ? "done" : "todo", hint: c.setup_confirmed ? "Setup confirmed" : "Setup not confirmed yet" },
  {
    label: "Accounts",
    state: (c.mappings_to_review || 0) === 0 ? "done" : "part",
    hint: (c.mappings_to_review || 0) === 0 ? "All mappings reviewed" : `${plural(c.mappings_to_review, "account")} to check`,
  },
  { label: "Review", state: c.review_stale ? "todo" : "done", hint: c.review_stale ? "Review not run since the last changes" : "Review up to date" },
  {
    label: "Workbook",
    state: c.workbook_state === "final" && !c.workbook_stale ? "done" : c.workbook_state === "none" ? "todo" : "part",
    hint:
      c.workbook_state === "none"
        ? "Not built yet"
        : c.workbook_stale
        ? `${c.workbook_state === "final" ? "Final" : "Draft"} built before the latest changes: build it again`
        : c.workbook_state === "draft"
        ? "Draft built"
        : "Final workbook up to date",
  },
];

/** dd/mm/yyyy of a yyyy-mm-dd date */
export const ukDate = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;

/** The year end a year after this one (dd/mm/yyyy; a month end stays a month end) */
export const nextYearEnd = (v: string) => {
  const m = v.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (!m) return "";
  const [d, mo, y] = [Number(m[1]), Number(m[2]), Number(m[3]) + 1];
  const last = new Date(y, mo, 0).getDate();
  const day = d === new Date(y - 1, mo, 0).getDate() ? last : Math.min(d, last);
  return `${String(day).padStart(2, "0")}/${String(mo).padStart(2, "0")}/${y}`;
};

/** Year end arrives as dd/mm/yyyy: compare it as a real date (new Date() would read it the US way). */
export const yearEndTime = (v: string) => {
  const m = v.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  return m ? new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1])).getTime() : 0;
};
