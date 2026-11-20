"use client";

import { useRef, useState } from "react";
import { CheckCircle2, FileUp, Loader2, Upload } from "lucide-react";
import { toast } from "@/lib/notify";
import { Modal } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { READ_AS } from "@/components/review/area/AreaEvidence";
import { AREA_EVIDENCE, AREAS } from "@/lib/areas";
import { api } from "@/lib/api";
import { useJobStore } from "@/lib/queries/job";
import { cn } from "@/lib/utils";

/**
 * Add document (on the top bar of every screen): a document the client sends in the middle of the job, filed with
 * the working paper it belongs to. The same upload as that working paper's Evidence tab: the app keeps it for the
 * reviewer, and the VAT returns, payroll report, asset register and loan register are read into the checks.
 * A new trial balance or ledger is not a document: it goes in through Files (it is coded again).
 */
export function AddDocumentModal({ engagementId, isOpen, onClose, area, onRead, onGoToFiles }: {
  engagementId: string;
  isOpen: boolean;
  onClose: () => void;
  /** The working paper open when the window was opened: chosen in advance */
  area?: string | null;
  /** A document the checks read: the checks run again */
  onRead?: () => void;
  onGoToFiles: () => void;
}) {
  const papers = AREAS.filter((a) => AREA_EVIDENCE[a.key]);
  const [picked, setPicked] = useState<string | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ area: string; read: string[]; kept: number } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const store = useJobStore(engagementId);
  const chosen = picked ?? (area && AREA_EVIDENCE[area] ? area : null);

  const close = () => {
    setPicked(null);
    setFiles([]);
    setDone(null);
    onClose();
  };

  const send = async () => {
    if (!chosen || !files.length) return;
    setBusy(true);
    try {
      const next = await api.addEvidence(engagementId, chosen, files);
      store.setEvidence(next);
      const mine = (next[chosen] || []).filter((d) => files.some((f) => f.name === d.filename));
      const read = mine.filter((d) => d.read_as).map((d) => `${d.filename}: read as the ${READ_AS[d.read_as!] || d.read_as}${d.records ? ` (${d.records} rows)` : ""}`);
      setDone({ area: chosen, read, kept: mine.length - read.length });
      if (read.length) onRead?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not upload");
    } finally {
      setBusy(false);
    }
  };

  const label = (key: string) => papers.find((a) => a.key === key)?.label ?? key;
  return (
    <Modal isOpen={isOpen} onClose={close} title="Add a document"
           description="File a document with the working paper it belongs to. The app keeps it for the reviewer and reads the ones it can.">
      {done ? (
        <div className="space-y-4">
          <div className="rounded-xl border border-emerald-100 bg-emerald-50/70 p-4 text-sm">
            <p className="flex items-center gap-2 font-semibold text-emerald-800">
              <CheckCircle2 className="h-4 w-4" /> Filed with {label(done.area)}
            </p>
            {done.read.map((r) => <p key={r} className="mt-1.5 text-xs text-emerald-800">{r}. The checks run again with it.</p>)}
            {done.kept > 0 && <p className="mt-1.5 text-xs text-emerald-800">{done.kept} kept for the reviewer.</p>}
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => { setDone(null); setFiles([]); }}>Add another</Button>
            <Button size="sm" onClick={close}>Done</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <section>
            <p className="mb-2 text-xs font-semibold text-slate-700">1. Which working paper is it for?</p>
            <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
              {papers.map((a) => (
                <button key={a.key} type="button" onClick={() => setPicked(a.key)}
                        className={cn("rounded-lg border px-3 py-2 text-left transition",
                                      chosen === a.key ? "border-teal-300 bg-teal-50 ring-1 ring-teal-200" : "border-slate-200 hover:border-teal-200 hover:bg-slate-50")}>
                  <span className="block text-xs font-semibold text-slate-800">{a.label}</span>
                  <span className="block truncate text-[11px] text-slate-500" title={AREA_EVIDENCE[a.key].what}>{AREA_EVIDENCE[a.key].what}</span>
                </button>
              ))}
            </div>
          </section>
          <section>
            <p className="mb-2 text-xs font-semibold text-slate-700">2. The file</p>
            <button type="button" onClick={() => input.current?.click()}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => { e.preventDefault(); setFiles(Array.from(e.dataTransfer.files)); }}
                    className="flex w-full flex-col items-center gap-1 rounded-xl border border-dashed border-slate-300 px-4 py-5 text-xs text-slate-500 transition hover:border-teal-300 hover:bg-teal-50/40">
              <Upload className="h-5 w-5 text-slate-400" />
              {files.length ? <span className="font-medium text-slate-800">{files.map((f) => f.name).join(", ")}</span>
                : <span>Drop the file here, or click to choose (PDF, Excel, CSV, image)</span>}
            </button>
            <input ref={input} type="file" multiple className="hidden" onChange={(e) => setFiles(Array.from(e.target.files || []))} />
          </section>
          <p className="text-[11px] text-slate-500">
            A new trial balance or ledger?{" "}
            <button type="button" className="font-semibold text-teal-700 hover:underline" onClick={() => { close(); onGoToFiles(); }}>Add it in Files</button>
            {" "}so its accounts are coded again.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={close}>Cancel</Button>
            <Button size="sm" disabled={!chosen || !files.length || busy} onClick={send}>
              {busy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <FileUp className="mr-1.5 h-3.5 w-3.5" />}
              Add to {chosen ? label(chosen) : "the working paper"}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
