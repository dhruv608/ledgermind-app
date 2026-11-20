"use client";

// A document beside what was read from it: the photo or PDF on the left, the figures on the right. A P60's figures
// can be corrected; Confirm marks it checked and its income line follows.
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { toast } from "@/lib/notify";
import { CheckCircle2, X } from "lucide-react";
import { api, SaDocument } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const P60_FIELDS: [string, string, boolean][] = [
  ["employer", "Employer", false], ["paye_ref", "PAYE reference", false], ["pay_this", "Pay in this employment", true],
  ["tax_this", "Tax deducted", true], ["tax_code", "Final tax code", false], ["tax_year", "Tax year", false],
];

interface Props {
  jobId: string;
  docId: number | null;
  onClose: () => void;
  onSaved?: (doc: SaDocument) => void;
}

export function SaDocViewer({ jobId, docId, onClose, onSaved }: Props) {
  const [doc, setDoc] = useState<SaDocument | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  // Another document opened: empty until it arrives (closing keeps the last one, as nothing is shown)
  const [prevOpened, setPrevOpened] = useState({ jobId, docId });
  if (prevOpened.jobId !== jobId || prevOpened.docId !== docId) {
    setPrevOpened({ jobId, docId });
    if (docId != null) setDoc(null);
  }
  useEffect(() => {
    if (docId == null) return;
    api.listSaDocuments(jobId).then((all) => {
      const d = all.find((x) => x.id === docId) || null;
      setDoc(d);
      setValues(Object.fromEntries(P60_FIELDS.map(([k]) => [k, d?.fields?.[k] != null ? String(d!.fields![k]) : ""])));
    });
  }, [jobId, docId]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  if (docId == null) return null;
  const url = api.saDocumentUrl(jobId, docId);
  const isPdf = !!doc && /\.pdf$/i.test(doc.filename);
  const isImage = !!doc && /\.(png|jpe?g|webp|gif)$/i.test(doc.filename);
  const p60 = doc?.kind === "P60";

  const confirm = async () => {
    if (!doc) return;
    const changed = p60 ? Object.fromEntries(P60_FIELDS.map(([k]) => [k, values[k]])
      .filter(([k, v]) => String(doc.fields?.[k] ?? "") !== v)) : {};
    setSaving(true);
    try {
      const saved = await api.reviewSaDocument(jobId, doc.id, Object.keys(changed).length ? changed : null);
      toast.success(Object.keys(changed).length ? "Figures corrected and checked" : "Checked");
      onSaved?.(saved);
      onClose();
    } catch (e: any) {
      toast.error("Not saved", { description: e.message });
    } finally {
      setSaving(false);
    }
  };

  // Drawn on the page's body, so no layout around it can clip a fixed panel
  return createPortal(
    <div className="fixed inset-0 z-50 flex">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} />
      <div className="relative ml-auto h-full w-full max-w-5xl bg-white shadow-2xl flex flex-col">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
          <div className="min-w-0">
            <p className="text-sm font-bold text-slate-900 truncate">{doc?.filename.split(/[\\/]/).pop() || "Document"}</p>
            {doc?.note && <p className="text-xs text-amber-800 truncate">{doc.note}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="min-h-0 bg-slate-100 overflow-auto flex items-start justify-center p-4">
            {!doc ? <div className="skeleton h-96 w-full max-w-xl rounded-xl" />
              : isImage ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={url} alt="" className="max-w-full rounded-lg shadow" />
              ) : isPdf ? (
                <iframe src={url} title="Document" className="h-full min-h-[70vh] w-full rounded-lg bg-white shadow" />
              ) : (
                <p className="text-sm text-slate-500 mt-10">This kind of file is not shown here.</p>
              )}
          </div>
          <div className="border-t md:border-t-0 md:border-l border-slate-200 p-5 overflow-auto">
            <p className="text-[11px] font-bold uppercase tracking-wider text-teal-700">What was read</p>
            {p60 ? (
              <div className="mt-3 space-y-3">
                {P60_FIELDS.map(([k, label, money]) => (
                  <label key={k} className="block space-y-1">
                    <span className="text-xs font-semibold text-slate-600">{label}</span>
                    <Input value={values[k] ?? ""} onChange={(e) => setValues({ ...values, [k]: e.target.value })}
                           inputMode={money ? "decimal" : undefined} className={money ? "tabular-nums" : ""} />
                  </label>
                ))}
                <p className="text-[11px] text-slate-500">Only pay and tax &ldquo;in this employment&rdquo; go to the return.</p>
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-600">{doc ? `Kept as ${doc.kind.toLowerCase().replace(/_/g, " ")}: no figures are read from this kind yet.` : ""}</p>
            )}
            <div className="mt-6 flex gap-2">
              <Button variant="primary" onClick={confirm} disabled={!doc || saving}>
                <CheckCircle2 className="w-4 h-4 mr-1.5" /> {saving ? "Saving..." : "Confirm"}
              </Button>
              <Button variant="ghost" onClick={onClose}>Close</Button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
