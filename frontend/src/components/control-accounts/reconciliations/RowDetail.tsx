// One balance sheet account opened: its figures, the year on the account, the forms to agree it and links onward.
import { FileSearch, List, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Reconciliation, Reconciliations } from "@/lib/api";
import { cn } from "@/lib/utils";
import { byHand, money } from "@/components/control-accounts/reconciliations/shared";
import { AgreeForm, StatementForm } from "@/components/control-accounts/reconciliations/EntryForms";
import { RollforwardBox } from "@/components/control-accounts/reconciliations/RollforwardBox";
import { DebtorAgeingBox } from "@/components/control-accounts/reconciliations/DebtorAgeingBox";
import { VatProofBox } from "@/components/control-accounts/reconciliations/VatProofBox";

export function RowDetail({
  row,
  engagementId,
  onOpenLedger,
  onOpenScrutiny,
  onGoTo,
  onOpenArea,
  onSaved,
}: {
  row: Reconciliation;
  engagementId: string;
  onOpenLedger: (code: number) => void;
  onOpenScrutiny?: (code: number) => void;
  onGoTo: (tab: "inputs" | "review") => void;
  /** Opens an area page; evidence: on its Evidence tab */
  onOpenArea?: (key: string, evidence?: boolean) => void;
  onSaved: (next: Reconciliations) => void;
}) {
  const bankCode = row.key.startsWith("bank:") ? Number(row.key.slice(5)) : null;
  const ledgerCode = bankCode ?? (row.codes.length === 1 && row.section !== "Profit and loss checks" ? row.codes[0] : null);
  return (
    <div className="space-y-3 rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-4">
        <Figure label="Books (after approved journals)" value={money(row.books)} />
        <Figure label="Last year" value={money(row.last_year)} />
        <Figure label={row.compared_with} value={row.ticked ? "Ticked as agreed" : row.other === null ? "Not entered" : money(row.other)} />
        <Figure
          label="Difference (books less the other)"
          value={money(row.difference)}
          className={row.status === "DIFFERENCE" ? "text-rose-700" : undefined}
        />
      </div>
      {row.note && <p className="text-[11px] text-slate-600">{row.note}</p>}

      {row.codes.length > 0 && row.section !== "Profit and loss checks" && (
        <RollforwardBox engagementId={engagementId} codes={row.codes} books={row.books} />
      )}
      {row.key === "ar" && <DebtorAgeingBox engagementId={engagementId} />}
      {row.key === "vat" && row.proof && <VatProofBox proof={row.proof} engagementId={engagementId} onSaved={onSaved} />}

      {bankCode !== null && (
        <StatementForm key={JSON.stringify(row.entered)} row={row} engagementId={engagementId} onSaved={onSaved} />
      )}
      {byHand(row.key) && (
        <AgreeForm key={JSON.stringify(row.entered)} row={row} engagementId={engagementId} onSaved={onSaved} />
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
        {ledgerCode !== null && (
          <Button variant="outline" size="sm" onClick={() => onOpenLedger(ledgerCode)}>
            <List className="mr-1.5 h-3.5 w-3.5" />
            See transactions
          </Button>
        )}
        {ledgerCode !== null && onOpenScrutiny && (
          <Button variant="outline" size="sm" onClick={() => onOpenScrutiny(ledgerCode)}>
            <FileSearch className="mr-1.5 h-3.5 w-3.5" />
            Open in GL scrutiny
          </Button>
        )}
        {(row.key === "vat" || row.key === "payroll") && row.status === "NEEDS_INPUT" && (
          <Button variant="outline" size="sm" onClick={() => (onOpenArea ? onOpenArea(row.key === "vat" ? "vat" : "payroll", true) : onGoTo("inputs"))}>
            <Pencil className="mr-1.5 h-3.5 w-3.5" />
            {row.key === "vat" ? "Enter the VAT returns" : "Upload the payroll report"}
          </Button>
        )}
        {(row.key === "ct" || row.key === "s455") && (
          <Button variant="outline" size="sm" onClick={() => (onOpenArea ? onOpenArea("tax") : onGoTo("review"))}>
            See the tax computation
          </Button>
        )}
        {row.tab && <span className="ml-auto text-[11px] text-slate-400">In the Excel: tab {row.tab}</span>}
      </div>
    </div>
  );
}

function Figure({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className="rounded-md bg-slate-50 px-3 py-2">
      <span className="block truncate text-[11px] text-slate-500" title={label}>{label}</span>
      <span className={cn("font-mono text-sm font-semibold text-slate-900", className)}>{value}</span>
    </div>
  );
}
