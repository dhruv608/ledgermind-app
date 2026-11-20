"use client";

// Foreign income (SA106): each source by country and kind, in pounds, with the foreign tax, the treaty and the
// Foreign Tax Credit Relief (the lower of the foreign tax and the UK tax on it). A pension is taxed on 90%.
import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { MessageSquareMore, OctagonAlert, Pencil, Plus, Trash2 } from "lucide-react";
import { api, SaForeign as Data, SaForeignIn, SaForeignKind } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { Modal } from "@/components/ui/dialog";
import { NUM, SaHead, TABLE_WRAP, THEAD, TROW } from "@/components/sa/SaChrome";
import { cn } from "@/lib/utils";
import { SaPropertyPage } from "@/components/sa/SaPropertyPage";

const money = (v: number) => `${v < 0 ? "-" : ""}£${Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const INPUT = "h-8 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs focus:border-teal-500 focus:outline-none";
const BLANK: SaForeignIn = { country: "USA", kind: "INTEREST", payer: "", amount: 0, foreign_tax: 0, share: 1, claim: true, note: null };

function F({ label, hint, wide, children }: { label: string; hint?: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <label className={cn("block", wide && "sm:col-span-2")}>
      <span className="text-[11px] font-semibold text-slate-600">{label}</span>
      <div className="mt-0.5">{children}</div>
      {hint && <span className="mt-0.5 block text-[10.5px] text-slate-400">{hint}</span>}
    </label>
  );
}

function Form({ data, start, onSave, onCancel }: { data: Data; start: SaForeignIn; onSave: (b: SaForeignIn) => void; onCancel: () => void }) {
  const [b, setB] = useState<SaForeignIn>(start);
  const set = (p: Partial<SaForeignIn>) => setB({ ...b, ...p });
  const known = data.countries.some((c) => c.code === b.country);
  return (
    <div className="pt-4">
      <div className="grid gap-3 sm:grid-cols-4">
        <F label="Country" hint="HMRC's 3-letter code">
          <CustomSelect fullWidth searchable value={known ? b.country : "_other"} onChange={(v) => set({ country: v === "_other" ? "" : v })}
                        options={[...data.countries.map((c) => ({ value: c.code, label: `${c.name} (${c.code})` })), { value: "_other", label: "Other: type the code" }]} />
          {!known && <input className={cn(INPUT, "mt-1 uppercase")} maxLength={3} value={b.country} onChange={(e) => set({ country: e.target.value.toUpperCase() })} />}
        </F>
        <F label="Kind" wide>
          <CustomSelect fullWidth value={b.kind} onChange={(v) => set({ kind: v as SaForeignKind })}
                        options={data.kinds.map((k) => ({ value: k.kind, label: k.label }))} />
        </F>
        <F label="Person's share" hint="0.5 for a joint account"><input className={cn(INPUT, NUM)} type="number" step="0.01" min={0.01} max={1} value={b.share} onChange={(e) => set({ share: Number(e.target.value) || 1 })} /></F>
        <F label="Payer or account" wide><input className={INPUT} value={b.payer} onChange={(e) => set({ payer: e.target.value })} /></F>
        <F label="Gross amount in £" hint="Before foreign tax, at HMRC's rate"><input className={cn(INPUT, NUM)} defaultValue={b.amount || ""} onBlur={(e) => set({ amount: Number(e.target.value.replace(/[£,]/g, "") || 0) })} /></F>
        <F label="Foreign tax in £"><input className={cn(INPUT, NUM)} defaultValue={b.foreign_tax || ""} onBlur={(e) => set({ foreign_tax: Number(e.target.value.replace(/[£,]/g, "") || 0) })} /></F>
        <F label="Relief for the foreign tax">
          <span className="flex flex-col gap-1 text-xs text-slate-700">
            <label className="flex items-center gap-1.5"><input type="radio" checked={b.claim} onChange={() => set({ claim: true })} /> Credit (usually best)</label>
            <label className="flex items-center gap-1.5"><input type="radio" checked={!b.claim} onChange={() => set({ claim: false })} /> Deduct from the income</label>
          </span>
        </F>
        <F label="Note"><input className={INPUT} value={b.note ?? ""} onChange={(e) => set({ note: e.target.value || null })} /></F>
      </div>
      <div className="mt-4 flex justify-end gap-2 border-t border-slate-100 pt-3">
        <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={onCancel}>Cancel</Button>
        <Button size="sm" className="h-8 text-xs" onClick={() => onSave(b)}>Save</Button>
      </div>
    </div>
  );
}

export function SaForeign({ jobId, taxYear, onOpen, onChange }: { jobId: string; taxYear: string; onOpen: (page: string) => void; onChange?: () => void }) {
  const [data, setData] = useState<Data | null>(null);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  useEffect(() => { api.getSaForeign(jobId).then(setData).catch(() => {}); }, [jobId]);
  if (!data) return <div className="skeleton h-48 rounded-xl" />;

  const run = async (p: Promise<Data>) => {
    try { setData(await p); setEditing(null); onChange?.(); } catch (e: any) { toast.error("Not saved", { description: e.message }); }
  };
  const total = (k: "gross" | "foreign_tax" | "taxable") => data.rows.reduce((a, r) => a + r[k], 0);
  const blocks = data.issues.filter((i) => i.block).length;

  return (
    <div className="space-y-4">
      <SaHead title="Foreign income"
              state={blocks ? { text: `${blocks} block${blocks > 1 ? "s" : ""}`, tone: "look" } : data.issues.length ? { text: "To check", tone: "look" }
                     : data.rows.length ? { text: "Done", tone: "done" } : { text: "No sources", tone: "empty" }}
              meta="Each source by country and kind, in pounds. Interest and dividends keep their own rates; a foreign pension is taxed on 90%. The credit is the lower of the foreign tax (as the treaty allows) and the UK tax on that income."
              actions={<Button size="sm" className="h-8 text-xs" onClick={() => setEditing("new")}><Plus className="mr-1 h-3.5 w-3.5" /> Add source</Button>}
              figures={[
                { label: "Gross", value: money(total("gross")) },
                { label: "Foreign tax", value: money(total("foreign_tax")) },
                { label: "Taxable in the UK", value: money(total("taxable")) },
                { label: "Foreign tax credit", value: money(data.credit) },
              ]} />

      {data.issues.length > 0 && (
        <div className="space-y-1 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-900">
          {data.issues.map((i) => (
            <p key={i.key} className="flex gap-1.5">
              {i.kind === "CLIENT" ? <MessageSquareMore className="mt-px h-3.5 w-3.5 shrink-0" /> : <OctagonAlert className="mt-px h-3.5 w-3.5 shrink-0" />}
              <span>{i.text}{i.block && <b> Block.</b>}</span>
            </p>
          ))}
          <button type="button" onClick={() => onOpen("queries")} className="font-semibold underline cursor-pointer">Open Queries</button>
        </div>
      )}

      {/* Add or edit a source in a pop-up */}
      <Modal isOpen={editing !== null} onClose={() => setEditing(null)} className="max-w-3xl"
             title={editing === "new" ? "Add a foreign source" : "Edit foreign source"}
             description="In pounds at HMRC's exchange rate. Interest and dividends keep their own rates; a pension is taxed on 90%.">
        {editing !== null && (() => {
          const row = editing === "new" ? null : data.rows.find((r) => r.id === editing);
          return <Form key={String(editing)} data={data} start={row ? row.input : BLANK}
                       onSave={(b) => run(api.saveSaForeign(jobId, b, row ? row.id : undefined))} onCancel={() => setEditing(null)} />;
        })()}
      </Modal>

      <section className={TABLE_WRAP}>
        <table className="w-full table-fixed text-xs">
          <thead className={THEAD}>
            <tr className="text-left">
              <th className="px-4 py-2 font-semibold">Source</th>
              <th className="w-24 px-3 py-2 text-right font-semibold">Gross</th>
              <th className="w-24 px-3 py-2 text-right font-semibold">Foreign tax</th>
              <th className="w-24 px-3 py-2 text-right font-semibold">Taxable</th>
              <th className="w-24 px-3 py-2 text-right font-semibold">Credit</th>
              <th className="w-16" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.rows.length === 0 && <tr><td colSpan={6} className="px-4 py-3 text-slate-500">No foreign income entered.</td></tr>}
            {data.rows.map((r) => (
              <tr key={r.id} className={cn(TROW, "align-top")}>
                <td className="px-4 py-2">
                  <p className="font-semibold text-slate-800">{r.payer || r.kind_label} <span className="font-normal text-slate-500">· {r.country_name}</span></p>
                  <p className="text-[11px] text-slate-500">{r.kind_label}{r.exempt ? " · 10% exempt" : ""}{r.claim ? "" : " · tax deducted, no credit"}</p>
                  {r.treaty && <p className="text-[11px] text-teal-800">{r.treaty}</p>}
                  {r.notes.map((n) => <p key={n} className="text-[11px] text-slate-400">{n.replace(/^[^:]*\): /, "")}</p>)}
                </td>
                <td className={cn("px-3 py-2 text-right", NUM)}>{money(r.gross)}</td>
                <td className={cn("px-3 py-2 text-right", NUM)}>{money(r.foreign_tax)}</td>
                <td className={cn("px-3 py-2 text-right font-semibold", NUM)}>{money(r.taxable)}</td>
                <td className={cn("px-3 py-2 text-right", NUM)}>{r.credit ? money(r.credit) : "—"}</td>
                <td className="px-2 py-1.5 text-right">
                  <span className="inline-flex gap-1">
                    <button type="button" title="Edit" onClick={() => setEditing(r.id)} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-teal-700 cursor-pointer"><Pencil className="h-3.5 w-3.5" /></button>
                    <button type="button" title="Delete" onClick={() => run(api.deleteSaForeign(jobId, r.id))} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-rose-600 cursor-pointer"><Trash2 className="h-3.5 w-3.5" /></button>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <SaPropertyPage jobId={jobId} taxYear={taxYear} onChange={onChange} overseas />
    </div>
  );
}
