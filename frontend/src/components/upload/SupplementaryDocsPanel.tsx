"use client";

import React, { useState } from "react";
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, Building2, CalendarClock, CheckCircle2, Download, FileText, FolderOpen, History, Landmark, Loader2, Upload, Users } from "lucide-react";
import { SupplementaryDocument, SupplementaryData } from "@/types/engagement";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { SectionHeader } from "@/components/ui/section-header";
import { StatusChip, ChipTone } from "@/components/ui/status-chip";
import { plural, formatCurrency } from "@/lib/formatters";

interface SupplementaryDocsPanelProps {
  engagementId: string;
  documents: SupplementaryDocument[];
  data: SupplementaryData;
  onRefresh: () => void;
  /** The rows to show (the Files tab shows last year's WP and next year's ledger; the area documents are on each
   * area's Evidence tab). All of them when not given. */
  only?: string[];
}

const DOC_TYPES: Record<string, { label: string; tone: ChipTone }> = {
  VAT_100: { label: "VAT 100 return", tone: "success" },
  FIXED_ASSET_REGISTER: { label: "Fixed asset register", tone: "info" },
  FIXED_ASSET_REGISTER_EMPTY: { label: "Fixed asset register: empty template", tone: "warning" },
  PAYROLL_P32: { label: "Payroll report", tone: "info" },
  PAYROLL_FROM_GL: { label: "Built from the ledger, not a payroll report", tone: "warning" },
  LOANS_REGISTER: { label: "Loans register", tone: "info" },
  LAST_YEAR_WP: { label: "Last year's working paper", tone: "info" },
  NEXT_YEAR_LEDGER: { label: "Next year's ledger", tone: "info" },
};

const money = (v: number) => formatCurrency(v);
const sum = <T,>(rows: T[], pick: (r: T) => number | null | undefined) => rows.reduce((acc, r) => acc + (pick(r) || 0), 0);

/** One kind of file: what it is, whether it is in, its totals, and its own Upload button. */
function FileRow({
  icon: Icon,
  title,
  hint,
  status,
  totals,
  busy,
  onPick,
  templateHref,
}: {
  icon: LucideIcon;
  title: string;
  hint: string;
  status: string | null;
  totals: { label: string; value: number }[] | null;
  busy: boolean;
  onPick: (files: File[]) => void;
  /** An empty form to fill in before uploading (offered as a download beside the Upload button) */
  templateHref?: string;
}) {
  return (
    <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${status ? "bg-emerald-50 text-emerald-600" : "bg-slate-100 text-slate-400"}`}>
          {status ? <CheckCircle2 className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
        </span>
        <div className="min-w-0">
          <p className="text-sm font-medium text-slate-900">{title}</p>
          <p className="text-[11px] text-slate-500">{status || hint}</p>
          {totals && (
            <p className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-slate-600">
              {totals.map((t) => (
                <span key={t.label}>
                  {t.label}: <b className="font-mono font-semibold text-slate-900">{money(t.value)}</b>
                </span>
              ))}
            </p>
          )}
        </div>
      </div>
      {templateHref && (
        <a
          href={templateHref}
          download
          className="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 self-start rounded-lg border border-slate-200 bg-white px-3 text-xs font-medium text-slate-700 transition hover:bg-slate-50 sm:self-center"
        >
          <Download className="h-3.5 w-3.5" />
          Download template
        </a>
      )}
      <label
        className={`inline-flex h-8 shrink-0 cursor-pointer items-center justify-center gap-1.5 self-start rounded-lg border px-3 text-xs font-medium transition sm:self-center ${
          status ? "border-slate-200 bg-white text-slate-700 hover:bg-slate-50" : "border-teal-700 bg-teal-700 text-white hover:bg-teal-800"
        } ${busy ? "pointer-events-none opacity-60" : ""}`}
      >
        <Upload className="h-3.5 w-3.5" />
        {status ? "Upload again" : "Upload"}
        <input
          type="file"
          multiple
          accept=".xlsx,.xls,.csv"
          className="hidden"
          disabled={busy}
          onChange={(e) => {
            const files = Array.from(e.target.files || []);
            e.target.value = "";
            if (files.length) onPick(files);
          }}
        />
      </label>
    </div>
  );
}

export const SupplementaryDocsPanel: React.FC<SupplementaryDocsPanelProps> = ({
  engagementId,
  documents,
  data,
  onRefresh,
  only,
}) => {
  const shows = (docType: string) => !only || only.includes(docType);
  const [isUploading, setIsUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const upload = async (fileList: File[], docType?: string) => {
    setIsUploading(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const res = await api.uploadSupplementaryDocuments(engagementId, fileList, docType);
      setSuccessMessage(`${plural(fileList.length, "file")} uploaded and read.`);
      if (res?.warnings?.length) setErrorMessage(res.warnings.join(" "));
      onRefresh();
    } catch (err: any) {
      setErrorMessage(err.message || "The files could not be uploaded.");
    } finally {
      setIsUploading(false);
    }
  };

  const far = data.fixed_asset_records;
  const payroll = data.payroll_records;
  const others = documents.filter((d) => !["PAYROLL_P32", "FIXED_ASSET_REGISTER", "LOANS_REGISTER", "LAST_YEAR_WP", "NEXT_YEAR_LEDGER"].includes(d.doc_type));
  const loansRegister = documents.filter((d) => d.doc_type === "LOANS_REGISTER").pop();
  const lastYearWp = documents.filter((d) => d.doc_type === "LAST_YEAR_WP").pop();
  const nextYear = documents.filter((d) => d.doc_type === "NEXT_YEAR_LEDGER").pop();

  return (
    <Card className="overflow-hidden">
      <SectionHeader
        icon={Users}
        title={only ? "Other years" : "Payroll, fixed assets, loans and other years"}
        description={only ? "Upload these if you have them. Uploaded again, each replaces the earlier one."
          : "Upload these if the client has them. A payroll report uploaded again replaces the months it covers; last year's working paper and next year's ledger uploaded again replace the earlier one."}
        className="border-b border-slate-100 p-5"
        actions={
          isUploading ? (
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Reading the file…
            </span>
          ) : undefined
        }
      />

      {(errorMessage || successMessage) && (
        <div
          className={`flex items-center gap-2 border-b px-5 py-2.5 text-xs ${
            errorMessage ? "border-rose-100 bg-rose-50 text-rose-800" : "border-emerald-100 bg-emerald-50 text-emerald-800"
          }`}
        >
          {errorMessage ? <AlertTriangle className="h-4 w-4 shrink-0 text-rose-500" /> : <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />}
          {errorMessage || successMessage}
        </div>
      )}

      <div className="divide-y divide-slate-100">
        {shows("PAYROLL_P32") && (
          <FileRow
            icon={Users}
            title="Payroll report"
            hint="From BrightPay: Report 1, saved as CSV (one line per employee per month)"
            status={payroll.length ? `${plural(payroll.length, "payroll line")} read` : null}
            totals={
              payroll.length
                ? [
                    { label: "Gross pay", value: sum(payroll, (r) => r.gross_pay) },
                    { label: "Employer NI", value: sum(payroll, (r) => r.employer_nic) },
                    { label: "Due to HMRC", value: sum(payroll, (r) => r.total_hmrc_due) },
                  ]
                : null
            }
            busy={isUploading}
            onPick={(files) => upload(files, "PAYROLL_P32")}
          />
        )}
        {shows("FIXED_ASSET_REGISTER") && (
          <FileRow
            icon={Building2}
            title="Fixed asset register"
            hint="A list of the client's assets with cost and depreciation"
            status={far.length ? `${plural(far.length, "asset")} read` : null}
            totals={
              far.length
                ? [
                    { label: "Additions", value: sum(far, (r) => r.additions) },
                    { label: "Depreciation", value: sum(far, (r) => r.depr_charge) },
                    { label: "Net book value", value: sum(far, (r) => r.nbv) },
                  ]
                : null
            }
            busy={isUploading}
            onPick={(files) => upload(files, "FIXED_ASSET_REGISTER")}
          />
        )}
        {shows("LOANS_REGISTER") && (
          <FileRow
            icon={Landmark}
            title="Loans and HP register"
            hint="The firm's loans register: one row per agreement (amount, payments, rate or payment, method). Download the template, fill in the client's loans, upload it."
            status={loansRegister ? `${plural(loansRegister.parsed_records_count, "agreement")} read` : null}
            totals={null}
            busy={isUploading}
            onPick={(files) => upload(files, "LOANS_REGISTER")}
            templateHref="/templates/loans-register-template.xlsx"
          />
        )}
        {shows("LAST_YEAR_WP") && (
          <FileRow
            icon={History}
            title="Last year's final working paper"
            hint="The whole finished workbook for the year before: its accruals and prepayments are reversed, its fixed assets rolled forward, and its final balances checked against last year's TB"
            status={lastYearWp ? `${lastYearWp.filename} read` : null}
            totals={null}
            busy={isUploading}
            onPick={(files) => upload(files.slice(0, 1), "LAST_YEAR_WP")}
          />
        )}
        {shows("NEXT_YEAR_LEDGER") && (
          <FileRow
            icon={CalendarClock}
            title="Next year's ledger"
            hint="The general ledger for the months after the year end: bills that belong to this year become accruals, and payments after the year end show what was paid (debtors, creditors, payroll, director's loan)"
            status={nextYear ? `${plural(nextYear.parsed_records_count, "line")} after the year end read` : null}
            totals={null}
            busy={isUploading}
            onPick={(files) => upload(files.slice(0, 1), "NEXT_YEAR_LEDGER")}
          />
        )}
      </div>

      {documents.length > 0 && !only && (
        <details className="border-t border-slate-100">
          <summary className="flex cursor-pointer items-center gap-2 px-5 py-3 text-xs font-medium text-slate-600 hover:bg-slate-50">
            <FolderOpen className="h-4 w-4 text-slate-400" />
            Files uploaded ({documents.length}){others.length > 0 && ` · ${others.length} other`}
          </summary>
          <ul className="divide-y divide-slate-100 border-t border-slate-100">
            {documents.map((doc) => {
              const type = DOC_TYPES[doc.doc_type] || { label: "Other schedule", tone: "neutral" as ChipTone };
              return (
                <li key={doc.id} className="flex items-center justify-between gap-3 px-5 py-2.5">
                  <div className="flex min-w-0 items-center gap-3">
                    <FileText className="h-4 w-4 shrink-0 text-slate-400" />
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium text-slate-800" title={doc.filename}>{doc.filename}</p>
                      <p className="mt-0.5 text-[11px] text-slate-500">
                        {(doc.file_size_bytes / 1024).toFixed(1)} KB · {plural(doc.parsed_records_count, "row")} read
                      </p>
                    </div>
                  </div>
                  <StatusChip tone={type.tone} className="shrink-0">{type.label}</StatusChip>
                </li>
              );
            })}
          </ul>
        </details>
      )}
    </Card>
  );
};
