import type { LedgerViewLine, PayrollSummary } from "@/lib/api";

/**
 * The net wages T split into employee wages payable, director wages payable, employee wages paid and director wages
 * paid. Owed comes from the payroll report's Employees and Directors tables; paid from the wages payments in the
 * ledger, a payment naming a director (their surname, or full name) counted as the director's. Null when no director
 * is on the payroll (one line each).
 */
export interface WagesSplit {
  employeeOwed: number;
  directorOwed: number;
  /** Owed in the books beyond the payroll report's net pay (shown on its own line, so the T still adds up) */
  otherOwed: number;
  employeePaid: number;
  directorPaid: number;
}

const words = (name: string) => name.toLowerCase().split(/[^a-z]+/).filter((w) => w.length > 2);

export function wagesSplit(owed: number, paid: number, summary: PayrollSummary | undefined, ledger: LedgerViewLine[] | undefined): WagesSplit | null {
  const staff = summary?.tables.find((t) => t.key === "employees")?.total.net ?? 0;
  const directors = summary?.tables.find((t) => t.key === "directors")?.total.net;
  if (directors === undefined) return null;
  const names = (summary?.director_names ?? []).map(words).filter((w) => w.length);
  // A payment out of net wages is a debit on it; it is a director's when its words hold the director's surname
  const isDirector = (text: string) => {
    const t = text.toLowerCase();
    return names.some((w) => t.includes(w[w.length - 1]));
  };
  const directorPaid = (ledger ?? []).filter((l) => l.net > 0 && isDirector(`${l.description} ${l.account}`)).reduce((s, l) => s + l.net, 0);
  const other = Math.abs(owed - staff - directors) >= 1 ? owed - staff - directors : 0;
  return { employeeOwed: staff, directorOwed: directors, otherOwed: other, employeePaid: paid - Math.min(directorPaid, paid), directorPaid: Math.min(directorPaid, paid) };
}
