// The one decision on a review point card (figures filled, one yes / no action, the proposed
// journal beside it, initials and date). The checks send free text; this picks the question to decide, the answer that
// clears the point (with its reason ready to save) and tidies the text the reader does not need.
import type { AuditFinding } from "@/types/engagement";

export interface Decision {
  /** The question the reviewer answers */
  question: string;
  /** No "ask the client" answer: the step is ours (enter the directors, accrue the fee) */
  ours?: boolean;
  /** The answer that clears the point, and the reason saved with it */
  fine: string;
  reason: string;
}

// By kind of point: what to decide. The first pattern that fits wins (its code, and its title when one code covers
// different kinds of point); anything else gets the plain question.
const DECISIONS: [RegExp, Decision, RegExp?][] = [
  [/^V-(C|D)0/, { question: "Is the difference explained by entries posted after the return was filed?",
    fine: "Yes, explained", reason: "Explained: entries posted after the return was filed" }],
  [/^V-F02/, { question: "Is the gap explained by zero-rated, exempt or outside-the-scope sales, other income or cut-off?",
    fine: "Yes, explained", reason: "Explained: sales outside the VAT boxes or cut-off" }],
  [/^V-F03/, { question: "Do the lines shown explain the VAT account difference?",
    fine: "Yes, explained", reason: "Explained by the VAT proof lines" }],
  [/^V-/, { question: "Does the VAT agree once this is explained?", fine: "Yes, agrees", reason: "VAT checked" }],
  [/^G9$/, { question: "Is each of these payments coded to the right account?",
    fine: "Yes, coded right", reason: "Checked: coded to the right account" }],
  // G5 is two checks: a customer or supplier settled both through the ledger and straight through the bank (the same
  // sale or bill could be in twice), and bills that look the same
  [/^G5$/, { question: "Are the direct receipts for different sales, not invoices already in the sales ledger?",
    fine: "Yes, different sales", reason: "Checked: the direct receipts are not invoiced sales" }, /customer.*direct receipts?/i],
  [/^G5$/, { question: "Are the direct payments for different costs, not bills already in the purchase ledger?",
    fine: "Yes, different costs", reason: "Checked: the direct payments are not ledger bills" }, /supplier.*direct payments?/i],
  [/^G5$/, { question: "Are these different purchases, not the same cost counted twice?",
    fine: "Yes, different", reason: "Checked: not counted twice" }],
  // A balance that moved a lot or is new against last year
  [/^PY-MOVE/, { question: "Do you know why it changed: a new account, a balance moved from another code, or the year's activity?",
    fine: "Yes, explained", reason: "Change against last year explained" }],
  [/^U-ADJ-003/, { question: "Is a fee for this year's accounts still to be accrued?",
    fine: "No fee to accrue", reason: "No accountancy fee to accrue", ours: true }],
  [/^RP-/, { question: "Are the directors and shareholders entered on Client details?",
    fine: "Yes, entered", reason: "Directors entered on Client details", ours: true }],
  [/^U-FA-004/, { question: "Is the depreciation in the books right?", fine: "Yes, books are right",
    reason: "Depreciation in the books is right" }],
];

const PLAIN: Decision = { question: "Is this fine as it is?", fine: "Yes, fine", reason: "" };

export function decisionFor(f: AuditFinding): Decision {
  return DECISIONS.find(([re, , title]) => re.test(f.procedure_ref || "") && (!title || title.test(f.finding_title || "")))?.[1] ?? PLAIN;
}

/** Text the reader does not need: the check's own codes, empty references, app words. Money with a minus sign in
 * brackets. */
export function tidy(text: string): string {
  return (text || "")
    .replace(/\s*\((?:V-[A-Z]\d+|K\d|G\d(?:\.\d)?)\)/g, "")
    .replace(/\s*Ref:\s*(?:\d+|-)\s*;\s*-\s*/g, " ")
    .replace(/\s*Ref:\s*(?:\d+|-)\s*;\s*/g, " Law: ")
    .replace(/What the app found:\s*/g, "")
    .replace(/\s*\(for review only\)/g, "")
    .replace(/£-([\d,]+(?:\.\d{2})?)/g, "(£$1)")
    .replace(/-£([\d,]+(?:\.\d{2})?)/g, "(£$1)")
    .replace(/\.\s*\.(?=\s|$)/g, ".")
    .replace(/\s{2,}/g, " ")
    .trim();
}

// A sentence that is our step, not the client's
const OUR_STEP = /^(Release|Enter|Check|Post|Move|Correct|Reverse|Review|Add|Record|Book|Claim|Set|Upload|Remove|Match|Disclose|Approve|Reject)\b/;
// A sentence the client can read: a request or a question to them
const TO_CLIENT = /^(Please|Are|Is|Do|Does|Did|Can|Could|Was|Were|Has|Have|What|Which|When|Who|How|Why|Send|Confirm)\b|\?$/;

/** A client question's text split in two: the words for the client, and the steps that are ours. */
export function splitClientText(text: string): { client: string; ours: string } {
  const client: string[] = [];
  const ours: string[] = [];
  for (const s of (text || "").split(/(?<=[.!?])\s+(?=[A-Z(£])/)) {
    const t = s.trim();
    if (!t) continue;
    // Requests, questions and the context around them go to the client; the steps that are ours stay with us
    if (OUR_STEP.test(t) && !TO_CLIENT.test(t)) ours.push(t);
    else client.push(t.charAt(0).toUpperCase() + t.slice(1));
  }
  return { client: client.join(" "), ours: ours.join(" ") };
}
