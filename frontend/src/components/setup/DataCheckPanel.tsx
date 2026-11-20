"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { accountLabel } from "@/lib/formatters";
import { AlertTriangle, CheckCircle2, ChevronDown, ClipboardCheck, Mail, OctagonX, RefreshCw, Upload } from "lucide-react";
import { toast } from "@/lib/notify";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SectionHeader } from "@/components/ui/section-header";
import { StatusChip } from "@/components/ui/status-chip";
import { SkeletonRows } from "@/components/common/SkeletonRows";
import { ClientEmailDialog, type EmailGroup } from "@/components/clients/ClientEmailDialog";
import { api, type DataCheck, type DataCheckItem } from "@/lib/api";
import { cn } from "@/lib/utils";

type GoTo = "inputs" | "recs";

/** What each item asks the client for, in the email (an item the accountant fixes in the app is not asked) */
const ASK_CLIENT: Partial<Record<DataCheckItem["action"], string>> = {
  upload_last_year_tb: "Last year's closing trial balance (or last year's accounts), for the opening balances.",
  reupload_tb: "The trial balance again: the one we have does not balance.",
  upload_gl: "The general ledger (nominal ledger detail) for the year, as an Excel export.",
  upload_far: "The fixed asset register: each asset with its cost, date bought and depreciation.",
  upload_payroll: "The payroll summary for the year (gross pay, tax, NI and pension per month).",
  enter_vat: "The VAT returns filed for the year (and any return still unpaid at the start of the year).",
  confirm_vat: "Whether the company is VAT registered: if it is, the VAT number and the VAT returns filed for the year.",
  loan_statement: "The year-end statement for each loan or mortgage (the balance owed at the year end and the interest charged in the year).",
  add_properties: "A list of the company's properties: for each, the address, whether it is held to rent out or to sell (or being developed to sell), and the completion statement for any bought or sold in the year.",
  upload_aged: "The aged debtors and aged creditors reports at the year end.",
  enter_bank: "The bank statements showing the balance at the year end, for each account.",
  reupload_bank: "The full bank statements for the year (every month, with the running balance), as issued by the bank.",
};

const LOOK = {
  STOP: { icon: OctagonX, row: "bg-rose-50/40", iconClass: "text-rose-600", chip: "danger" as const, chipText: "Must fix" },
  WARNING: { icon: AlertTriangle, row: "", iconClass: "text-amber-600", chip: "warning" as const, chipText: "Check" },
  OK: { icon: CheckCircle2, row: "", iconClass: "text-emerald-600", chip: "success" as const, chipText: "OK" },
};

/** The Data check: is everything the working papers need in the client's files, and was it read. Items that must be
 *  fixed block the workbook (the build refuses with the same reasons); items to check leave it a draft. Each item
 *  has its own way to fix it: upload last year's TB, tick the first year, add a report, or go to the screen for it. */
export function DataCheckPanel({
  engagementId,
  clientName,
  yearEnd,
  onChanged,
  onLoaded,
  onGoTo,
}: {
  engagementId: string;
  clientName: string;
  yearEnd: string | null;
  /** Something was added or ticked: the build gate and the other tabs are asked again */
  onChanged?: () => void;
  /** The counts each time the check is read (the tab's badge) */
  onLoaded?: (check: DataCheck) => void;
  onGoTo: (tab: GoTo) => void;
}) {
  const [check, setCheck] = useState<DataCheck | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [showOk, setShowOk] = useState(false);
  const [emailOpen, setEmailOpen] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const pendingUpload = useRef<DataCheckItem["action"]>("");

  const show = useCallback((c: DataCheck) => {
    setCheck(c);
    onLoaded?.(c);
  }, [onLoaded]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      show(await api.getDataCheck(engagementId));
    } catch (e: any) {
      toast.error(e.message || "Could not check the client's data");
    } finally {
      setLoading(false);
    }
  }, [engagementId, show]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load() is the shared refresh (also after uploads); it shows its spinner as it starts
    load();
  }, [load]);

  const firstYear = async (value: boolean) => {
    setBusy("first_year");
    try {
      show(await api.setFirstYear(engagementId, value));
      toast.success(value ? "Marked as the first year of trading" : "First year of trading cleared");
      onChanged?.();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setBusy(null);
    }
  };

  const pick = (action: DataCheckItem["action"]) => {
    pendingUpload.current = action;
    fileInput.current?.click();
  };

  const upload = async (file: File) => {
    const action = pendingUpload.current;
    setBusy(action);
    try {
      if (action === "upload_last_year_tb") {
        const result = await api.uploadLastYearTb(engagementId, file);
        show(result);
        toast.success(`Last year's TB added: ${result.added} opening balance${result.added === 1 ? "" : "s"} brought in (${result.how})`);
      } else {
        const type = action === "upload_far" ? "FIXED_ASSET_REGISTER" : "PAYROLL_P32";
        const res = await api.uploadSupplementaryDocuments(engagementId, [file], type);
        toast.success(`${file.name} uploaded`);
        (res?.warnings || []).forEach((w: string) => toast.warning(w, { duration: 12000 }));
        await load();
      }
      onChanged?.();
    } catch (e: any) {
      toast.error(e.message || "The file could not be used");
    } finally {
      setBusy(null);
    }
  };

  if (loading && !check) {
    return (
      <Card className="px-4 py-3.5">
        <SkeletonRows rows={6} />
      </Card>
    );
  }
  if (!check) return null;

  const stops = check.items.filter((i) => i.status === "STOP");
  const warnings = check.items.filter((i) => i.status === "WARNING");
  const ok = check.items.filter((i) => i.status === "OK");
  const asks = [...stops, ...warnings].map((i) => ASK_CLIENT[i.action]).filter((t): t is string => Boolean(t));
  const emailGroups: EmailGroup[] = [{ title: "Documents we still need:", items: Array.from(new Set(asks)) }];

  return (
    <div className="space-y-4">
      <Card className="px-4 py-3.5">
        <SectionHeader
          icon={ClipboardCheck}
          title="Files" page
          description="Is everything the working papers need in the client's files, and was it read. Items to fix stop the workbook; items to check leave it a draft."
          actions={
            <div className="flex gap-2">
              {asks.length > 0 && (
                <Button size="sm" variant="outline" onClick={() => setEmailOpen(true)}>
                  <Mail className="mr-1.5 h-3.5 w-3.5" /> Ask the client
                </Button>
              )}
              <Button size="sm" variant="outline" className="h-8 w-8 p-0" onClick={load} disabled={loading}
                      title="Check the files again (after an upload)" aria-label="Check the files again">
                <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
              </Button>
            </div>
          }
        />

        <div
          className={cn(
            "mt-3 flex items-start gap-2.5 rounded-lg border px-3 py-2 text-sm",
            check.ready ? (warnings.length ? "border-slate-200 bg-slate-50/70 text-slate-800" : "border-emerald-200 bg-emerald-50 text-emerald-900")
              : "border-rose-200 bg-rose-50 text-rose-900"
          )}
        >
          {check.ready ? <CheckCircle2 className={cn("mt-0.5 h-4 w-4 shrink-0", warnings.length ? "text-teal-600" : "")} /> : <OctagonX className="mt-0.5 h-4 w-4 shrink-0" />}
          <div>
            <p className="font-semibold">
              {!check.ready
                ? `${stops.length} thing${stops.length === 1 ? "" : "s"} must be fixed before the workbook can be built`
                : warnings.length
                  ? "The workbook can be built, as a draft until the points below are checked"
                  : "Everything is in: the workbook can be built"}
            </p>
            {(stops.length > 0 || warnings.length > 0) && (
              <p className="mt-0.5 text-xs opacity-80">
                {stops.length} to fix · {warnings.length} to check · {ok.length} OK
              </p>
            )}
          </div>
        </div>
      </Card>

      {/* The points to fix or check, as one list */}
      {stops.length + warnings.length > 0 && (
        <Card className="divide-y divide-slate-100 overflow-hidden p-0">
          {grouped([...stops, ...warnings]).map((item) => (
            <Row key={item.key} item={item} busy={busy} firstYearTicked={check.first_year}
                 onUpload={pick} onFirstYear={firstYear} onGoTo={onGoTo} />
          ))}
        </Card>
      )}

      {ok.length > 0 && (
        <Card className="p-0">
          <button type="button" onClick={() => setShowOk((v) => !v)}
                  className="flex w-full items-center justify-between rounded-xl px-5 py-3 text-left text-sm font-semibold text-slate-700 transition-colors hover:bg-teal-50/40 hover:text-teal-800">
            <span className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-600" /> {ok.length} item{ok.length === 1 ? "" : "s"} OK
            </span>
            <ChevronDown className={cn("h-4 w-4 text-slate-400 transition-transform", showOk && "rotate-180")} />
          </button>
          {showOk && (
            <div className="divide-y divide-slate-100 border-t border-slate-100">
              {ok.map((item) => (
                <Row key={item.key} item={item} busy={busy} firstYearTicked={check.first_year}
                     onUpload={pick} onFirstYear={firstYear} onGoTo={onGoTo} compact />
              ))}
            </div>
          )}
        </Card>
      )}

      <input ref={fileInput} type="file" accept=".xlsx,.xls,.csv" className="hidden"
             onChange={(e) => {
               const f = e.target.files?.[0];
               e.target.value = "";
               if (f) upload(f);
             }} />
      <ClientEmailDialog isOpen={emailOpen} onClose={() => setEmailOpen(false)} client={clientName} yearEnd={yearEnd} groups={emailGroups} />
    </div>
  );
}

/** Items that ask the same thing of several accounts ('Bank statement: 4800 ...', 'Bank statement: 4801 ...') as one
 *  row: one line per account under one button, instead of a row and a button each. */
function grouped(items: DataCheckItem[]): DataCheckItem[] {
  const head = (i: DataCheckItem) => (i.label.includes(":") ? i.label.split(":")[0].trim() : "");
  const out: DataCheckItem[] = [];
  const seen = new Map<string, DataCheckItem[]>();
  for (const i of items) {
    const k = head(i) && i.action ? `${i.status}|${i.action}|${head(i)}` : "";
    if (!k) { out.push(i); continue; }
    if (!seen.has(k)) { seen.set(k, []); out.push(i); }
    seen.get(k)!.push(i);
  }
  return out.map((i) => {
    const k = head(i) && i.action ? `${i.status}|${i.action}|${head(i)}` : "";
    const all = k ? seen.get(k)! : [i];
    if (all.length < 2) return i;
    // One line, not one per account: the reason once, then the accounts by name (each one's figure is on its own page)
    const names = all.map((x) => accountLabel(x.label.slice(head(x).length + 1).trim()));
    const reason = (i.detail || "").replace(/\s*\(books [^)]*\)\.?$/, "").replace(/\.$/, "");
    return { ...i, key: `group:${k}`, label: `${head(i)}s: ${all.length} accounts`,
             detail: `${reason} for ${names.slice(0, 4).join(", ")}${names.length > 4 ? ` and ${names.length - 4} more` : ""}.` };
  });
}

function Row({ item, busy, firstYearTicked, onUpload, onFirstYear, onGoTo, compact = false }: {
  item: DataCheckItem;
  busy: string | null;
  firstYearTicked: boolean;
  onUpload: (action: DataCheckItem["action"]) => void;
  onFirstYear: (value: boolean) => void;
  onGoTo: (tab: GoTo) => void;
  compact?: boolean;
}) {
  const look = LOOK[item.status];
  const Icon = look.icon;
  const working = busy !== null;
  return (
    <div className={cn("flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-start sm:justify-between", look.row, compact && "py-2.5")}>
      <div className="flex min-w-0 gap-3">
        <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", look.iconClass)} />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-slate-900">{item.label}</p>
            {!compact && <StatusChip tone={look.chip}>{look.chipText}</StatusChip>}
          </div>
          <p className="mt-0.5 whitespace-pre-line text-xs leading-relaxed text-slate-600">{item.detail}</p>
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap gap-2 sm:justify-end">
        {item.action === "upload_last_year_tb" && (
          <>
            <Button size="sm" variant="primary" disabled={working} onClick={() => onUpload("upload_last_year_tb")}>
              <Upload className="mr-1.5 h-3.5 w-3.5" /> {busy === "upload_last_year_tb" ? "Adding…" : "Upload last year's TB"}
            </Button>
            <Button size="sm" variant="outline" disabled={working} onClick={() => onFirstYear(true)}>
              First year of trading
            </Button>
          </>
        )}
        {item.action === "first_year" && firstYearTicked && (
          <Button size="sm" variant="ghost" disabled={working} onClick={() => onFirstYear(false)}>
            Not the first year
          </Button>
        )}
        {(item.action === "upload_far" || item.action === "upload_payroll") && item.status !== "OK" && (
          <Button size="sm" variant="outline" disabled={working} onClick={() => onUpload(item.action)}>
            <Upload className="mr-1.5 h-3.5 w-3.5" /> {busy === item.action ? "Uploading…" : item.action === "upload_far" ? "Upload asset register" : "Upload payroll report"}
          </Button>
        )}
        {item.action === "loan_statement" && (
          <Button size="sm" variant="outline" onClick={() => onGoTo("recs")}>Enter statement balance</Button>
        )}
        {item.action === "confirm_vat" && (
          <p className="max-w-[16rem] text-[11px] leading-snug text-slate-500">
            Change VAT on the client setup if it is registered, then enter the VAT returns.
          </p>
        )}
        {item.action === "add_properties" && (
          <p className="max-w-[16rem] text-[11px] leading-snug text-slate-500">
            Add each property on the client setup (rental or trading), then run the books again.
          </p>
        )}
        {item.action === "enter_vat" && (
          <Button size="sm" variant="outline" onClick={() => onGoTo("inputs")}>Enter VAT returns</Button>
        )}
        {item.action === "enter_bank" && (
          <Button size="sm" variant="outline" onClick={() => onGoTo("recs")}>Enter statement balances</Button>
        )}
        {(item.action === "reupload_tb" || item.action === "upload_gl" || item.action === "upload_aged") && item.status !== "OK" && (
          <p className="max-w-[16rem] text-[11px] leading-snug text-slate-500">
            Upload it with the client&apos;s files again (New client, same name and year end): the setup answers are kept.
          </p>
        )}
      </div>
    </div>
  );
}
