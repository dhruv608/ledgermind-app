// The client list on a wider screen: a heading row per company, then a row per year-end with its progress and actions.
import React from "react";
import { getDownloadUrl } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/ui/status-chip";
import { getAccountingSystemBadge } from "@/lib/badges";
import { plural, timeAgo } from "@/lib/formatters";
import { ClientListItem } from "@/types/engagement";
import { AlertTriangle, ArrowRight, CheckCircle2, FileSpreadsheet, ListChecks } from "lucide-react";
import { CheckingChip, DownloadButton, DueDate, StepBar, VatDue } from "@/components/clients/client-directory/RowParts";
import { Row } from "@/components/clients/client-directory/useClientDirectory";

export function ClientTable({
  rows,
  companyCheckbox,
  addNextYear,
  onSelectClient,
  selectedIds,
  handleToggleRow,
  boxShown,
  isAllPageSelected,
  isSomePageSelected,
  handleToggleSelectAllPage,
}: {
  rows: Row[];
  companyCheckbox: (years: ClientListItem[]) => React.ReactNode;
  addNextYear: (latest: ClientListItem) => React.ReactNode;
  onSelectClient: (engagementId: string) => void;
  selectedIds: Set<string>;
  handleToggleRow: (id: string) => void;
  boxShown: (ticked: boolean) => string;
  isAllPageSelected: boolean;
  isSomePageSelected: boolean;
  handleToggleSelectAllPage: () => void;
}) {
  return (
    <div className="hidden overflow-x-auto sm:block">
      <table className="w-full min-w-[920px] text-left text-xs">
        <thead className="border-b border-slate-200 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
          <tr>
            <th className="w-10 px-3.5 py-2.5 text-center">
              <input
                type="checkbox"
                checked={isAllPageSelected}
                ref={(el) => {
                  if (el) el.indeterminate = isSomePageSelected;
                }}
                onChange={handleToggleSelectAllPage}
                className="h-4 w-4 cursor-pointer rounded border-slate-300 accent-teal-700"
                title={isAllPageSelected ? "Unselect this page" : "Select this page"}
              />
            </th>
            <th className="px-3 py-2.5 font-semibold">Year end</th>
            <th className="px-3 py-2.5 font-semibold">Progress</th>
            <th className="px-3 py-2.5 font-semibold">To do</th>
            <th className="px-3 py-2.5 font-semibold">Workbook</th>
            <th className="whitespace-nowrap px-3 py-2.5 font-semibold">Last worked on</th>
            <th className="px-4 py-2.5" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 text-slate-700">
          {rows.map((row) => {
            if ("head" in row) {
              const first = row.head.years[0];
              const software = getAccountingSystemBadge(first.source_system);
              return (
                <tr key={`head:${row.head.key}`} className="group border-t border-slate-200 bg-slate-100/70">
                  <td className="px-3.5 py-2 text-center">{companyCheckbox(row.head.years)}</td>
                  <td colSpan={7} className="px-3 py-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                    <span className="text-sm font-semibold text-slate-900">{first.client_name}</span>
                    <span className={`ml-2 rounded border px-1 py-px align-[1px] text-[10px] font-semibold ${software.className}`}>{software.label}</span>
                    <span className="ml-2 text-[11px] text-slate-500">
                      {[first.company_number || null, first.is_vat_registered ? "VAT" : null, plural(row.head.years.length, "year-end")]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                      </div>
                      <div className="flex items-center gap-3">
                        <DueDate client={first} />
                        <VatDue client={first} />
                        {addNextYear(first)}
                      </div>
                    </div>
                  </td>
                </tr>
              );
            }
            const { client } = row;
            const selected = selectedIds.has(client.engagement_id);
            const mappings = client.mappings_to_review || 0;
            const points = client.open_audit_findings || 0;

            return (
              <tr
                key={client.engagement_id}
                className={`group cursor-pointer transition-colors ${selected ? "bg-teal-50" : "hover:bg-teal-50/60"}`}
                onClick={() => onSelectClient(client.engagement_id)}
              >
                <td className="px-3.5 py-2 text-center" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => handleToggleRow(client.engagement_id)}
                    className={`h-4 w-4 cursor-pointer rounded border-slate-300 accent-teal-700 ${boxShown(selected)}`}
                    aria-label={`Tick ${client.client_name} ${client.period_end_date}`}
                  />
                </td>

                {/* The year-end, set in under its company's heading */}
                <td className="min-w-[160px] py-2 pl-6 pr-3">
                  <p className="font-mono text-sm font-semibold text-slate-900 group-hover:text-teal-800">{client.period_end_date}</p>
                  <p className="mt-0.5 text-[11px] text-slate-500">{client.total_tb_rows} accounts</p>
                </td>

                <td className="px-3 py-2">
                  <StepBar client={client} />
                </td>

                <td className="px-3 py-2">
                  {client.checking ? (
                    <CheckingChip progress={client.checking} />
                  ) : mappings === 0 && points === 0 ? (
                    <StatusChip tone="success" icon={CheckCircle2}>Nothing open</StatusChip>
                  ) : (
                    <div className="flex flex-col items-start gap-1">
                      {mappings > 0 && <StatusChip tone="warning" icon={AlertTriangle}>{plural(mappings, "account")} to check</StatusChip>}
                      {points > 0 && <StatusChip tone="neutral" icon={ListChecks}>{plural(points, "point")} to clear</StatusChip>}
                    </div>
                  )}
                </td>

                <td className="px-3 py-2">
                  {client.workbook_state === "final" ? (
                    <StatusChip tone="success" icon={FileSpreadsheet}>Final</StatusChip>
                  ) : client.workbook_state === "draft" ? (
                    <StatusChip tone="warning" icon={FileSpreadsheet}>Draft</StatusChip>
                  ) : (
                    <span className="text-[11px] text-slate-400">Not built</span>
                  )}
                  {client.workbook_stale && (
                    <p className="mt-1 whitespace-nowrap text-[11px] text-amber-700" title="Built before the latest changes: build it again">
                      Needs refresh
                    </p>
                  )}
                </td>

                <td className="whitespace-nowrap px-3 py-2 text-[11px] text-slate-500" title={client.last_activity_at || ""}>
                  {timeAgo(client.last_activity_at) || "—"}
                </td>

                <td className="px-4 py-2">
                  <div className="flex items-center justify-end gap-1">
                    <DownloadButton downloadUrl={client.latest_workpaper_id ? getDownloadUrl(client.latest_workpaper_id) : undefined} />
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectClient(client.engagement_id);
                      }}
                      className="ml-1 h-7 text-xs group-hover:border-teal-700 group-hover:bg-teal-700 group-hover:text-white"
                    >
                      Open
                      <ArrowRight className="ml-1 h-3 w-3" />
                    </Button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
