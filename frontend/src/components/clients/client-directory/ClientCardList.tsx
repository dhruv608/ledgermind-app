// The client list on a phone: a heading per company, then one card per year-end.
import React from "react";
import { getAccountingSystemBadge } from "@/lib/badges";
import { plural, timeAgo } from "@/lib/formatters";
import { StatusChip } from "@/components/ui/status-chip";
import { ClientListItem } from "@/types/engagement";
import { AlertTriangle, ArrowRight, CheckCircle2, FileSpreadsheet, ListChecks } from "lucide-react";
import { CheckingChip, DueDate, StepBar, VatDue } from "@/components/clients/client-directory/RowParts";
import { Row } from "@/components/clients/client-directory/useClientDirectory";

export function ClientCardList({
  rows,
  companyCheckbox,
  addNextYear,
  onSelectClient,
}: {
  rows: Row[];
  companyCheckbox: (years: ClientListItem[]) => React.ReactNode;
  addNextYear: (latest: ClientListItem) => React.ReactNode;
  onSelectClient: (engagementId: string) => void;
}) {
  return (
    <ul className="divide-y divide-slate-100 sm:hidden">
      {rows.map((row) => {
        if ("head" in row) {
          const first = row.head.years[0];
          return (
            <li key={`head:${row.head.key}`} className="flex items-start gap-3 bg-slate-50 px-4 py-2">
              <div className="pt-0.5">{companyCheckbox(row.head.years)}</div>
              <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-slate-900">{first.client_name}</p>
              <p className="text-[11px] text-slate-500">
                {[getAccountingSystemBadge(first.source_system).label, first.is_vat_registered ? "VAT" : null, plural(row.head.years.length, "year-end")]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <div className="mt-1 flex flex-wrap items-center gap-3">
                <DueDate client={first} />
                <VatDue client={first} />
                {addNextYear(first)}
              </div>
              </div>
            </li>
          );
        }
        const { client } = row;
        const mappings = client.mappings_to_review || 0;
        const points = client.open_audit_findings || 0;
        return (
          <li key={client.engagement_id}>
            <button
              type="button"
              onClick={() => onSelectClient(client.engagement_id)}
              className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left active:bg-slate-50"
            >
              <div className="min-w-0 space-y-1.5">
                <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
                  <span className="text-[11px] text-slate-500">Year end</span>
                  <span className="font-mono text-sm font-semibold text-slate-900">{client.period_end_date}</span>
                  <span>· {client.total_tb_rows} accounts</span>
                </div>
                <StepBar client={client} />
                <div className="flex flex-wrap gap-1">
                  {client.checking && <CheckingChip progress={client.checking} />}
                  {mappings > 0 && <StatusChip tone="warning" icon={AlertTriangle}>{plural(mappings, "account")} to check</StatusChip>}
                  {points > 0 && <StatusChip icon={ListChecks}>{plural(points, "point")} to clear</StatusChip>}
                  {mappings === 0 && points === 0 && <StatusChip tone="success" icon={CheckCircle2}>Nothing open</StatusChip>}
                  {client.workbook_state !== "none" && (
                    <StatusChip tone={client.workbook_state === "final" ? "success" : "warning"} icon={FileSpreadsheet}>
                      {client.workbook_state === "final" ? "Final" : "Draft"}
                    </StatusChip>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-2">
                <ArrowRight className="mt-1 h-4 w-4 text-slate-300" />
                <span className="text-[11px] text-slate-400">{timeAgo(client.last_activity_at) || "—"}</span>
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
