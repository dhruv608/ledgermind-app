"use client";

// The return's documents: drop everything in one go (zips are unpacked); each file shows what it is, its tax year,
// what was read from it and why a person may need to look.
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "@/lib/notify";
import { FileStack, FileText, Image as ImageIcon, Loader2, Trash2, UploadCloud } from "lucide-react";
import { api, SaDocument, SaDocStatus } from "@/lib/api";
import { plural } from "@/lib/formatters";
import { ScanQueue, ScanResult } from "@/components/sa/ScanQueue";
import { SaHead, TABLE_WRAP, THEAD, TROW } from "@/components/sa/SaChrome";
import { cn } from "@/lib/utils";

const KIND_LABELS: Record<string, string> = {
  P60: "P60", P45: "P45", PAYSLIP: "Payslip", P11D: "P11D", TAX_CODE_NOTICE: "Tax code notice",
  TAX_CALCULATION: "Tax calculation", PENSION_STATEMENT: "Pension statement", MORTGAGE_INTEREST: "Mortgage interest",
  LETTING_STATEMENT: "Letting statement", INTEREST_STATEMENT: "Interest / savings", DIVIDEND_VOUCHER: "Dividend voucher",
  BANK_STATEMENT: "Bank statement", WORKING_PAPER: "Working paper", INVOICE: "Invoice / receipt", OTHER: "Other",
  DWP_LETTER: "DWP letter", CIS_STATEMENT: "CIS statement", FOSTER_LETTER: "Foster care letter",
  CLIENT_ACCOUNTS: "Client's income and expenses", BUNDLE: "Bundle (cut into parts)",
  FOREIGN_TAX: "Foreign tax document", DONATIONS: "Charity donations (Gift Aid)",
  VAT_RETURN: "VAT return", HMRC_STATEMENT: "HMRC statement",
};
const STATUS: Record<SaDocStatus, { label: string; cls: string }> = {
  READ: { label: "Read", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  CHECK: { label: "Check", cls: "bg-amber-50 text-amber-800 border-amber-200" },
  UNREADABLE: { label: "Can't read", cls: "bg-rose-50 text-rose-700 border-rose-200" },
  DUPLICATE: { label: "Duplicate", cls: "bg-slate-50 text-slate-500 border-slate-200" },
  OTHER_YEAR: { label: "Other year", cls: "bg-slate-50 text-slate-600 border-slate-200" },
  FILED: { label: "Kept", cls: "bg-teal-50 text-teal-700 border-teal-200" },
};
const money = (v: unknown) =>
  typeof v === "number" ? `£${v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—";

function found(d: SaDocument): string {
  const f = d.fields;
  if (!f) return "";
  if (d.kind === "P60")
    return [f.employer, f.paye_ref && `PAYE ${f.paye_ref}`, `pay ${money(f.pay_this)}`, `tax ${money(f.tax_this)}`,
            f.tax_code && `code ${f.tax_code}`].filter(Boolean).join(" · ");
  return "";
}

export function SaDocuments({ jobId, taxYear, onChange, onOpen }: { jobId: string; taxYear: string; onChange?: () => void; onOpen?: (docId: number) => void }) {
  const [docs, setDocs] = useState<SaDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  // The file being read now, its step, its place in the queue, and the one just finished
  const [current, setCurrent] = useState<File | null>(null);
  const [step, setStep] = useState(0);
  const [index, setIndex] = useState(0);
  const [last, setLast] = useState<ScanResult | null>(null);

  useEffect(() => {
    api.listSaDocuments(jobId).then(setDocs).catch(() => {}).finally(() => setLoading(false));
  }, [jobId]);

  const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));

  // One file at a time, so each is seen being read; the steps move on while the server reads it
  const send = async (list: FileList | null) => {
    if (!list || !list.length) return;
    const files = Array.from(list);
    setSending(files.length);
    setLast(null);
    let all = docs, added = 0, look = 0;
    try {
      for (let i = 0; i < files.length; i++) {
        setIndex(i);
        setCurrent(files[i]);
        setStep(0);
        const timers = [setTimeout(() => setStep(1), 1200), setTimeout(() => setStep(2), 3500)];
        const before = all.length;
        try {
          all = await api.uploadSaDocuments(jobId, [files[i]]);
        } finally {
          timers.forEach(clearTimeout);
        }
        const fresh = all.slice(before);
        added += fresh.length;
        look += fresh.filter((d) => d.status === "CHECK" || d.status === "UNREADABLE").length;
        setDocs(all);
        setCurrent(null);
        setLast({ name: files[i].name, file: files[i], docs: fresh });
        await pause(files.length > 1 ? 1100 : 0);
      }
      setIndex(files.length);
      toast.success(`${plural(added, "document")} added`, { description: look ? `${look} to look at` : "Nothing to look at" });
      onChange?.();
    } catch (e: any) {
      toast.error("Documents not added", { description: e.message });
      setLast(null);
    } finally {
      setCurrent(null);
      setSending(0);
    }
  };

  const remove = async (d: SaDocument) => {
    try {
      setDocs(await api.deleteSaDocument(jobId, d.id));
      onChange?.();
    } catch (e: any) {
      toast.error("Not removed", { description: e.message });
    }
  };

  const counts = useMemo(() => {
    const c: Partial<Record<SaDocStatus, number>> = {};
    docs.forEach((d) => (c[d.status] = (c[d.status] || 0) + 1));
    return c;
  }, [docs]);

  // Bank statements that came as a photo or a scan (read as pictures by the AI): a CSV download is exact and costs no AI
  const pictureBanks = useMemo(() => docs.filter((d) => d.kind === "BANK_STATEMENT" && d.status !== "DUPLICATE"
    && (/\.(png|jpe?g|webp|gif|heic)$/i.test(d.filename)
        || (/\.pdf$/i.test(d.filename) && !!d.read_by && !/\(text\)|code/.test(d.read_by)))).length, [docs]);

  return (
    <div className="space-y-4">
    <SaHead title="Documents"
            state={docs.length === 0 ? { text: "None yet", tone: "empty" } : ((counts.CHECK || 0) + (counts.UNREADABLE || 0)) ? { text: `${((counts.CHECK || 0) + (counts.UNREADABLE || 0))} to check`, tone: "look" } : { text: "All read", tone: "done" }}
            meta={`Everything the client sent for ${taxYear}: each file is sorted by kind and its figures read; anything uncertain waits here for a check.`}
            figures={docs.length ? [
              { label: "Documents", value: String(docs.length) },
              { label: "Read", value: String(counts.READ || 0) },
              { label: "To check", value: String(((counts.CHECK || 0) + (counts.UNREADABLE || 0))), tone: ((counts.CHECK || 0) + (counts.UNREADABLE || 0)) ? "text-amber-700" : undefined },
              { label: "Kept, duplicate or other year", value: String((counts.FILED || 0) + (counts.DUPLICATE || 0) + (counts.OTHER_YEAR || 0)) },
            ] : undefined} />
    <section className="space-y-4">
      <div className="space-y-4">
        {(sending > 0 || last) && (
          <ScanQueue file={current} step={step} index={index} total={sending || 1} last={last} />
        )}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => { e.preventDefault(); setDragOver(false); send(e.dataTransfer.files); }}
          onClick={() => !sending && input.current?.click()}
          className={`rounded-xl border-2 border-dashed p-5 text-center cursor-pointer transition-colors ${
            dragOver ? "border-teal-500 bg-teal-50/60" : "border-slate-300 hover:border-teal-400 bg-white"}`}
        >
          {sending ? (
            <p className="text-xs text-slate-600 flex items-center justify-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin text-teal-600" />
              Reading the documents: a photo or scan takes about 10 seconds
            </p>
          ) : (
            <>
              <span className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-teal-50 text-teal-700"><UploadCloud className="w-5 h-5" /></span>
              <p className="mt-2 text-sm font-semibold text-slate-800">Drop the client&apos;s documents here, or click to choose</p>
              <p className="text-xs text-slate-500">
                P60s, P45s, payslips, statements, letting and mortgage statements, photos, PDFs and zips, all in one go.
                For {taxYear}.
              </p>
              <p className="mt-1 text-[11px] text-slate-500">
                Best: bank statements as a CSV or Excel download from online banking (read exactly, no AI), other
                documents as PDFs downloaded from the website, and receipts as one list rather than photos.
              </p>
            </>
          )}
          <input ref={input} type="file" multiple className="hidden" onChange={(e) => { send(e.target.files); e.target.value = ""; }} />
        </div>

        {pictureBanks > 0 && (
          <p className="rounded-lg border border-teal-200 bg-teal-50/60 px-3 py-2 text-xs text-teal-900">
            {pictureBanks} bank statement{pictureBanks > 1 ? "s" : ""} came as a photo or scan. A CSV or Excel download
            from the client&apos;s online banking is read exactly, line for line, with no AI: ask for it next time.
          </p>
        )}
        {loading ? (
          <div className="skeleton h-16 rounded-xl" />
        ) : docs.length > 0 && (
          <div className={cn(TABLE_WRAP, "overflow-x-auto")}>
            <table className="w-full text-xs">
              <thead className={THEAD}>
                <tr className="text-left">
                  <th className="py-2 pl-3 pr-3 font-semibold">File</th>
                  <th className="py-2 pr-3 font-semibold">What it is</th>
                  <th className="py-2 pr-3 font-semibold">Year</th>
                  <th className="py-2 pr-3 font-semibold">Read</th>
                  <th className="py-2 pr-3 font-semibold">Status</th>
                  <th />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {docs.map((d) => {
                  const leaf = d.filename.split(/[\\/]/).pop();
                  const isImage = /\.(png|jpe?g|webp|gif|heic)$/i.test(d.filename);
                  return (
                    <tr key={d.id} className={cn("align-top", TROW)}>
                      <td className="py-2 pl-3 pr-3 max-w-[16rem]">
                        <button type="button" onClick={() => onOpen?.(d.id)} className="flex w-full max-w-[15rem] min-w-0 items-start gap-1.5 text-left text-slate-800 hover:text-teal-700 cursor-pointer" title={`Open ${d.filename}`}>
                          {isImage ? <ImageIcon className="w-3.5 h-3.5 mt-0.5 text-slate-400 shrink-0" /> : <FileText className="w-3.5 h-3.5 mt-0.5 text-slate-400 shrink-0" />}
                          <span className="truncate">{leaf}</span>
                        </button>
                      </td>
                      <td className="py-2 pr-3 whitespace-nowrap text-slate-700">{KIND_LABELS[d.kind] || d.kind}</td>
                      <td className="py-2 pr-3 whitespace-nowrap text-slate-500">{d.tax_year || "—"}</td>
                      <td className="py-2 pr-3 text-slate-700">
                        {found(d)}
                        {d.note && <span className="block text-[11px] text-amber-800 mt-0.5">{d.note}</span>}
                      </td>
                      <td className="py-2 pr-3">
                        {d.status === "CHECK" && onOpen ? (
                          <button type="button" onClick={() => onOpen(d.id)}
                                  className={`inline-block rounded-full border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap cursor-pointer hover:ring-2 hover:ring-amber-200 ${STATUS[d.status].cls}`}>
                            Check now
                          </button>
                        ) : (
                          <span className={`inline-block rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap ${STATUS[d.status].cls}`}>
                            {STATUS[d.status].label}
                          </span>
                        )}
                      </td>
                      <td className="py-2 text-right">
                        <button type="button" onClick={() => remove(d)} title="Remove"
                                className="p-1 rounded text-slate-400 hover:text-rose-600 hover:bg-rose-50 cursor-pointer">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
    </div>
  );
}
