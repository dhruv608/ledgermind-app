"use client";

import React, { useEffect, useMemo, useState, useRef } from "react";
import { Modal } from "@/components/ui/dialog";
import {
  UploadCloud,
  FileSpreadsheet,
  ArrowRight,
  X,
  Plus,
  Loader2,
  AlertTriangle,
  Layers,
  CheckCircle2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { formatFileSize } from "@/lib/formatters";
import { api, ConfirmedLayouts, FileRole, IdentifiedFile } from "@/lib/api";
import { ColumnPicker, columnsMissing } from "@/components/upload/ColumnPicker";

const ROLE_OPTIONS: { value: FileRole; label: string }[] = [
  { value: "TB", label: "Trial balance" },
  { value: "GL", label: "General ledger" },
  { value: "AR", label: "Customer balances (debtors)" },
  { value: "AP", label: "Supplier balances (creditors)" },
  { value: "TB_PRIOR", label: "Last year's TB (optional)" },
];
// A client with no accounting software (bank statement and Dext)
const RAW_ROLE_OPTIONS: { value: FileRole; label: string }[] = [
  { value: "BANK", label: "Bank statement" },
  { value: "SALES", label: "Sales invoices (Dext)" },
  { value: "BILLS", label: "Purchase bills (Dext)" },
  { value: "OPENING_TB", label: "Last year's closing TB" },
  { value: "OPENING_SALES", label: "Last year's unpaid invoices" },
  { value: "OPENING_BILLS", label: "Last year's unpaid bills" },
];
const tabName = (name: string) => name.replace(/\.xlsx$/i, "");

interface UploadEngagementModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Opened from a company's "Add next year": the files are for its next year-end */
  nextYearOf?: { name: string; yearEnd: string };
  onFileUpload: (files: File[], roles?: Record<string, FileRole>, layouts?: ConfirmedLayouts, yearEnd?: string) => Promise<void>;
  isUploading: boolean;
  uploadProgress: string;
  uploadStep: number;
  uploadPercent: number;
}

// The upload's stages, as the server reports them (backend services/ingestion/upload_progress.py)
const UPLOAD_STAGES = ["Reading the files", "Saving the ledger lines", "Mapping the accounts", "Reading the client details"];

export function UploadEngagementModal({
  isOpen,
  onClose,
  nextYearOf,
  onFileUpload,
  isUploading,
  uploadProgress,
  uploadStep,
  uploadPercent,
}: UploadEngagementModalProps) {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // What each file is: read from its content by the server as soon as files are chosen; the accountant can change it
  const [found, setFound] = useState<Record<string, IdentifiedFile>>({});
  const [tabs, setTabs] = useState<IdentifiedFile[]>([]);
  const [roles, setRoles] = useState<Record<string, FileRole>>({});
  const [combined, setCombined] = useState(false);
  const [raw, setRaw] = useState(false);
  // A bank-only client's year end: read from the files when one says it, else typed here (statements rarely say it)
  const [yearEndFound, setYearEndFound] = useState<string | null>(null);
  const [yearEnd, setYearEnd] = useState("");
  // Where a suggested year end came from (Companies House), shown under the box
  const [yearEndWhy, setYearEndWhy] = useState("");
  const [reading, setReading] = useState(false);
  const options = raw ? RAW_ROLE_OPTIONS : ROLE_OPTIONS;
  // Column choices for a TB or ledger the usual readers do not know (Sage, or any Excel): file -> {field: column}
  const [columns, setColumns] = useState<Record<string, Record<string, number>>>({});
  const withLayout = (combined ? tabs : Object.values(found)).filter((f) => f.layout && roles[f.filename] === f.layout.role);

  // A new list of files: an empty list clears what was read; otherwise reading starts (set while rendering, not in
  // the effect below, which asks the server)
  const [readFor, setReadFor] = useState(selectedFiles);
  if (readFor !== selectedFiles) {
    setReadFor(selectedFiles);
    if (!selectedFiles.length) {
      setFound({});
      setTabs([]);
      setRoles({});
      setCombined(false);
      setRaw(false);
    } else {
      setReading(true);
    }
  }
  useEffect(() => {
    if (!selectedFiles.length) return;
    let alive = true;
    api
      .identifyFiles(selectedFiles)
      .then((r) => {
        if (!alive) return;
        // Bank + Dext files are listed sheet by sheet, like the tabs of a combined workbook
        setRaw(Boolean(r.raw));
        setYearEndFound(r.year_end ?? null);
        if (!r.year_end && r.year_end_suggested) {
          setYearEnd((prev) => prev || r.year_end_suggested!);
          setYearEndWhy(r.year_end_why || "");
        }
        setCombined(r.combined || Boolean(r.raw));
        setTabs(r.combined || r.raw ? r.files : []);
        setFound(Object.fromEntries(r.files.map((f) => [f.filename, f])));
        setColumns(Object.fromEntries(r.files.filter((f) => f.layout).map((f) => [f.filename, f.layout!.mapping])));
        // Keep a choice the accountant already made; otherwise take what the server read
        setRoles((prev) => Object.fromEntries(r.files.map((f) => [f.filename, prev[f.filename] ?? f.role])));
      })
      .catch(() => alive && setFound({}))
      .finally(() => alive && setReading(false));
    return () => {
      alive = false;
    };
  }, [selectedFiles]);

  // Every file needs a kind, and no kind twice (a combined workbook is read tab by tab)
  const problem = useMemo(() => {
    if (reading || !selectedFiles.length) return null;
    const names = combined ? tabs.map((t) => t.filename) : selectedFiles.map((f) => f.name);
    const missing = names.filter((n) => !roles[n] || roles[n] === "UNKNOWN");
    const what = combined ? "tab" : "file";
    if (missing.length)
      return `Choose what ${missing.length === 1 ? `the ${what} "${tabName(missing[0])}" is` : `these ${what}s are`}.`;
    const used = names.map((n) => roles[n]);
    if (raw) {
      // One last-year TB; one bank statement per bank account; invoice and bill lists may come in several sheets
      const twiceRaw = RAW_ROLE_OPTIONS.find((o) => o.value === "OPENING_TB" && used.filter((r) => r === o.value).length > 1);
      if (twiceRaw) return `Two ${what}s are set as the ${twiceRaw.label.toLowerCase()}: only one can be (${combined ? "skip the other" : "remove the other with ×"}).`;
      if (!used.includes("BANK")) return `At least one of the ${what}s must be a bank statement.`;
      if (!yearEndFound && !yearEnd) return "Enter the client's year end: the statements do not say it.";
      return null;
    }
    const twice = ROLE_OPTIONS.find((o) => used.filter((r) => r === o.value).length > 1);
    // A second ledger is usually next year's (the months after the year end): it has its own upload on the client's
    // page (Supporting documents, Next year's ledger), so it is pointed there (only one GL is uploaded here)
    if (twice?.value === "GL")
      return `Two ${what}s are set as the general ledger: only one can be. If one is the ledger after the year end, ${combined ? "skip it" : "remove it with ×"} here and upload it on the client's page under Supporting documents, Next year's ledger.`;
    if (twice) return `Two ${what}s are set as the ${twice.label.replace(" (optional)", "").toLowerCase()}: only one can be (${combined ? "skip the other" : "remove the other with ×"}).`;
    if (!used.includes("TB")) return `One of the ${what}s must be the trial balance.`;
    const unchosen = withLayout.find((f) => columnsMissing(f.layout!, columns[f.filename] || {}).length);
    if (unchosen) return `Choose the columns of ${tabName(unchosen.filename)}: ${columnsMissing(unchosen.layout!, columns[unchosen.filename] || {}).join(", ")}.`;
    return null;
  }, [combined, raw, tabs, reading, selectedFiles, roles, columns, withLayout, yearEndFound, yearEnd]);

  const handleFilesAdded = (incomingFiles: FileList | null) => {
    if (!incomingFiles || incomingFiles.length === 0) return;
    const newFiles = Array.from(incomingFiles);
    setSelectedFiles((prev) => {
      const existingNames = new Set(prev.map((f) => f.name));
      const filtered = newFiles.filter((f) => !existingNames.has(f.name));
      return [...prev, ...filtered];
    });
  };

  const handleRemoveFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedFiles.length > 0 && !problem && !reading) {
      const layouts: ConfirmedLayouts = Object.fromEntries(withLayout.map((f) => [f.filename, {
        role: f.layout!.role, header_row: f.layout!.header_row, mapping: columns[f.filename] || {}, software: f.layout!.software,
      }]));
      onFileUpload(selectedFiles, roles, layouts, raw && !yearEndFound ? yearEnd : undefined);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={nextYearOf ? `Next year for ${nextYearOf.name}` : "New client"}
      description={
        nextYearOf
          ? `Upload ${nextYearOf.name}'s exports for the year ended ${nextYearOf.yearEnd}: trial balance and general ledger, or the bank statement with the Dext invoices and bills. The new year shows under the company once the files are read.`
          : "Upload the client's exports from Xero or QuickBooks (trial balance, general ledger, and optional aged debtors and creditors), or for a client with no accounting software, the bank statement with the Dext invoices and bills."
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Drop Zone */}
        {!isUploading && (
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              handleFilesAdded(e.dataTransfer.files);
            }}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-2xl p-6 transition-all flex flex-col items-center justify-center text-center cursor-pointer ${
              dragOver
                ? "border-teal-600 bg-teal-50/60"
                : "border-slate-300 hover:border-teal-500 bg-slate-50/50 hover:bg-slate-50"
            }`}
          >
            <div className="w-12 h-12 rounded-2xl bg-teal-50 border border-teal-200 flex items-center justify-center text-teal-700 mb-3 shadow-2xs">
              <UploadCloud className="w-6 h-6" />
            </div>

            <h3 className="text-sm font-bold text-slate-800">
              Drop the files here, or click to choose
            </h3>
            <p className="text-xs text-slate-500 mt-1 max-w-md">
              Excel or CSV (.xlsx, .xls, .csv). Any file names: each file is recognised from what is in it. Add last year&apos;s TB too to compare the two years.
            </p>
            <a
              href="/guide#before-upload"
              target="_blank"
              rel="noopener"
              onClick={(e) => e.stopPropagation()}
              className="mt-2 text-xs font-medium text-teal-700 underline-offset-2 hover:underline"
            >
              How to get the files ready
            </a>

            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".xlsx,.xls,.csv"
              onChange={(e) => handleFilesAdded(e.target.files)}
              className="hidden"
            />
          </div>
        )}

        {/* Selected Files List */}
        {!isUploading && selectedFiles.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-700">
              <span>Files to upload ({selectedFiles.length})</span>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="text-teal-700 hover:text-teal-800 flex items-center space-x-1 cursor-pointer"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Add more</span>
              </button>
            </div>

            <div className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
              {selectedFiles.map((f, idx) => {
                const info = found[f.name];
                const role = roles[f.name];
                return (
                  <div key={idx} className="flex flex-col gap-2 p-2.5 text-xs transition hover:bg-slate-50 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex min-w-0 items-center space-x-2.5 pr-2">
                      <FileSpreadsheet className="h-4 w-4 shrink-0 text-emerald-600" />
                      <div className="min-w-0">
                        <p className="truncate font-semibold text-slate-800">{f.name}</p>
                        <p className="text-[11px] text-slate-400">
                          {formatFileSize(f.size)}
                          {info && !combined && (
                            <> · {info.role !== "UNKNOWN" ? (info.how === "content" ? "recognised from its content" : info.how === "file name"
                              ? "recognised from its name" : `recognised (${info.how || "by its content"})`)
                              : role && role !== "UNKNOWN" ? "not recognised" : "not recognised: please choose"}</>
                          )}
                        </p>
                        {/* A file the app could not recognise, given a kind by hand: said now, not only on the Files tab after the upload */}
                        {info && !combined && info.role === "UNKNOWN" && role && role !== "UNKNOWN" && (
                          <p className="mt-0.5 flex items-start gap-1 text-[11px] text-amber-700">
                            <AlertTriangle className="mt-px h-3 w-3 shrink-0" />
                            <span>
                              Nothing in this file looks like the {(ROLE_OPTIONS.find((o) => o.value === role)?.label || "file of this kind").replace(" (optional)", "").toLowerCase()}.
                              Check it is the right file; if nothing can be read from it, the Files tab will say so after the upload.
                            </span>
                          </p>
                        )}
                      </div>
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      {reading ? (
                        <span className="inline-flex items-center gap-1 text-[11px] text-slate-400">
                          <Loader2 className="h-3 w-3 animate-spin" /> Reading…
                        </span>
                      ) : combined ? (
                        <span className="inline-flex items-center gap-1 rounded-md border border-sky-200 bg-sky-50 px-2 py-0.5 text-[11px] font-semibold text-sky-700">
                          <Layers className="h-3 w-3" /> {raw ? "Bank + Dext" : `Combined workbook: ${tabs.length} tabs`}
                        </span>
                      ) : (
                        <CustomSelect
                          size="sm"
                          align="right"
                          value={role && role !== "UNKNOWN" ? role : ""}
                          placeholder="What is this file?"
                          onChange={(v) => setRoles((prev) => ({ ...prev, [f.name]: v as FileRole }))}
                          options={ROLE_OPTIONS}
                          buttonClassName={!role || role === "UNKNOWN" ? "border-amber-300 bg-amber-50 text-amber-800" : ""}
                        />
                      )}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleRemoveFile(idx);
                        }}
                        className="cursor-pointer rounded-md p-1 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600"
                        title="Remove this file"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
            {combined && !reading && tabs.length > 0 && (
              <div className="rounded-xl border border-slate-200 bg-white">
                <p className="border-b border-slate-100 px-3 py-2 text-[11px] font-semibold text-slate-700">
                  {raw ? "What each sheet is (the books will be prepared in the app)" : "What each tab is"}
                </p>
                <div className="divide-y divide-slate-100">
                  {tabs.map((t) => {
                    const role = roles[t.filename];
                    return (
                      <div key={t.filename} className="flex items-center justify-between gap-3 px-3 py-2 text-xs">
                        <div className="min-w-0">
                          <p className="truncate font-medium text-slate-800">{tabName(t.filename)}</p>
                          <p className="text-[11px] text-slate-400">
                            {t.how === "content" ? "recognised from its content" : t.how === "file name" ? "recognised from its name" : t.how}
                          </p>
                        </div>
                        <CustomSelect
                          size="sm"
                          align="right"
                          className="shrink-0"
                          value={role && role !== "UNKNOWN" ? role : ""}
                          placeholder="What is this tab?"
                          onChange={(v) => setRoles((prev) => ({ ...prev, [t.filename]: v as FileRole }))}
                          options={[...options, { value: "SKIP", label: "Skip this tab" }]}
                          buttonClassName={role === "SKIP" ? "bg-slate-50 text-slate-500" : ""}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            {raw && !reading && !yearEndFound && (
              <label className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs">
                <span>
                  <span className="block font-semibold text-slate-800">Year end</span>
                  <span className="text-[11px] text-slate-500">
                    {yearEndWhy ? `${yearEndWhy}: check it` : "The statements do not say it: the date the accounts are made up to"}
                  </span>
                </span>
                <input
                  type="date"
                  value={yearEnd}
                  onChange={(e) => setYearEnd(e.target.value)}
                  className="h-8 rounded-md border border-slate-200 px-2 text-xs focus:outline-none focus:ring-2 focus:ring-teal-200"
                />
              </label>
            )}
            {!reading && withLayout.map((f) => (
              <ColumnPicker
                key={f.filename}
                filename={f.filename}
                layout={f.layout!}
                mapping={columns[f.filename] || {}}
                onChange={(m) => setColumns((prev) => ({ ...prev, [f.filename]: m }))}
              />
            ))}

            {problem && (
              <p className="flex items-center gap-1.5 text-[11px] font-medium text-amber-800">
                <AlertTriangle className="h-3.5 w-3.5" /> {problem}
              </p>
            )}

            {/* Ingestion Submit Action */}
            <div className="pt-2 flex justify-end">
              <Button
                type="submit"
                variant="primary"
                size="sm"
                className="w-full sm:w-auto"
                disabled={reading || Boolean(problem)}
              >
                <span>Upload {selectedFiles.length} file{selectedFiles.length > 1 ? "s" : ""}</span>
                <ArrowRight className="w-3.5 h-3.5 ml-1.5" />
              </Button>
            </div>
          </div>
        )}

        {/* While the server works: elapsed time, no made-up percentage */}
        {isUploading && (
          <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex items-start gap-3">
              <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-teal-700" />
              <div className="min-w-0 flex-1 space-y-2">
                <div className="flex items-center justify-between gap-2 text-xs font-semibold text-slate-800">
                  <span>{uploadProgress}</span>
                  {uploadPercent >= 0 && <span className="shrink-0 font-mono text-teal-700">{uploadPercent}%</span>}
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                  {uploadPercent >= 0 ? (
                    <div className="h-full rounded-full bg-teal-600 transition-all duration-200" style={{ width: `${uploadPercent}%` }} />
                  ) : (
                    <div className="h-full w-full animate-pulse rounded-full bg-teal-300" />
                  )}
                </div>
              </div>
            </div>

            {/* The stage the server is at, ticked off as it goes */}
            <ol className="space-y-1.5">
              {UPLOAD_STAGES.map((label, i) => {
                const n = i + 1;
                const done = uploadStep > n, now = uploadStep === n;
                return (
                  <li key={label} className={cn("flex items-center gap-2 text-xs",
                                                done ? "text-slate-500" : now ? "font-semibold text-slate-900" : "text-slate-400")}>
                    {done ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                      : now ? <Loader2 className="h-3.5 w-3.5 animate-spin text-teal-700" />
                      : <span className="mx-[3px] h-2 w-2 rounded-full border border-slate-300" />}
                    {label}
                  </li>
                );
              })}
            </ol>

            <p className="text-[11px] leading-relaxed text-slate-500">
              Every account is mapped to the firm&apos;s chart (the AI is asked only where the rules and earlier answers
              have none). Mapping takes longest on a full ledger. Keep this window open.
            </p>

            <div className="flex justify-end">
              <Button type="button" variant="outline" size="sm" onClick={onClose} className="hover:border-rose-300 hover:text-rose-600">
                <X className="mr-1 h-3.5 w-3.5" />
                Cancel upload
              </Button>
            </div>
          </div>
        )}
      </form>
    </Modal>
  );
}
