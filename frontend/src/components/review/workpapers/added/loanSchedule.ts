/**
 * A loan's repayment schedule (loans and HP by principal, instalments and interest). A repayment loan at a fixed
 * annual rate paid monthly: each month's opening, instalment, interest, principal and closing; then at the year end
 * the interest for the year and the balance due within one year (the principal of the next twelve instalments) and
 * after one year.
 */
export interface LoanTerms { amount: number; rate: number; months: number; start: string }
export interface LoanMonth { date: string; opening: number; instalment: number; interest: number; principal: number; closing: number }
export interface LoanYear { interest: number; principal: number; closing: number; withinYear: number; afterYear: number }

const r2 = (n: number) => Math.round(n * 100) / 100;

export function schedule(t: LoanTerms): LoanMonth[] {
  if (!(t.amount > 0) || !(t.months > 0) || !t.start) return [];
  const i = t.rate / 100 / 12;
  const instalment = i ? (t.amount * i) / (1 - Math.pow(1 + i, -t.months)) : t.amount / t.months;
  const out: LoanMonth[] = [];
  let bal = t.amount;
  const [y, m, d] = t.start.split("-").map(Number);
  for (let k = 0; k < t.months && bal > 0.005; k++) {
    const interest = bal * i;
    const principal = Math.min(instalment - interest, bal);
    const date = new Date(Date.UTC(y, m - 1 + k + 1, Math.min(d, 28))).toISOString().slice(0, 10);
    out.push({ date, opening: r2(bal), instalment: r2(principal + interest), interest: r2(interest), principal: r2(principal), closing: r2(bal - principal) });
    bal -= principal;
  }
  return out;
}

/** The accounting year to yearEnd (yyyy-mm-dd): interest and principal paid in it, the balance at the year end, and
 *  that balance split into due within one year and after one year. */
export function atYearEnd(rows: LoanMonth[], amount: number, yearEnd: string): LoanYear {
  const end = new Date(`${yearEnd}T00:00:00Z`);
  const start = new Date(end); start.setUTCFullYear(end.getUTCFullYear() - 1);
  const nextEnd = new Date(end); nextEnd.setUTCFullYear(end.getUTCFullYear() + 1);
  const at = (s: string) => new Date(`${s}T00:00:00Z`);
  const inYear = rows.filter((r) => at(r.date) > start && at(r.date) <= end);
  const paidBy = rows.filter((r) => at(r.date) <= end);
  const closing = paidBy.length ? paidBy[paidBy.length - 1].closing : amount;
  const nextYear = rows.filter((r) => at(r.date) > end && at(r.date) <= nextEnd).reduce((s, r) => s + r.principal, 0);
  return {
    interest: r2(inYear.reduce((s, r) => s + r.interest, 0)),
    principal: r2(inYear.reduce((s, r) => s + r.principal, 0)),
    closing: r2(closing),
    withinYear: r2(Math.min(nextYear, closing)),
    afterYear: r2(closing - Math.min(nextYear, closing)),
  };
}
