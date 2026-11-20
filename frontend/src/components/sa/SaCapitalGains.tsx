"use client";

// Capital gains (SA108): each disposal with its gain or loss, home relief and 60-day return, then the year's tax
// after losses and the annual exempt amount. What is still unknown is a Block on Queries.
import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { MessageSquareMore, OctagonAlert, Pencil, Plus, Trash2 } from "lucide-react";
import { api, SaCapitalGains as Data, SaDisposalIn, SaDisposalKind } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { Modal } from "@/components/ui/dialog";
import { AddButton, AddPopup, NUM, PopupField, SaHead, TABLE_WRAP, THEAD, TROW, text } from "@/components/sa/SaChrome";
import { cn } from "@/lib/utils";

const money = (v: number) => `${v < 0 ? "-" : ""}£${Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const INPUT = "h-8 w-full rounded-md border border-slate-200 bg-white px-2.5 text-xs focus:border-teal-500 focus:outline-none";
const day = (iso: string | null) => (iso ? iso.split("-").reverse().join("/") : "—");
const BLANK: SaDisposalIn = {
  kind: "LISTED", name: "", acquired: null, contract_date: null, completion_date: null, proceeds: 0, cost: 0, costs: 0,
  improvements: 0, share: 1, uk: true, main_home_months: null, badr: false, negligible: false, rtt_date: null, rtt_gain: null,
  rtt_tax: null, note: null,
};

function F({ label, hint, children, wide }: { label: string; hint?: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <label className={cn("block", wide && "sm:col-span-2")}>
      <span className="text-[11px] font-semibold text-slate-600">{label}</span>
      <div className="mt-0.5">{children}</div>
      {hint && <span className="mt-0.5 block text-[10.5px] text-slate-400">{hint}</span>}
    </label>
  );
}

function Form({ kinds, start, onSave, onCancel }: { kinds: Data["kinds"]; start: SaDisposalIn; onSave: (b: SaDisposalIn) => void; onCancel: () => void }) {
  const [b, setB] = useState<SaDisposalIn>(start);
  const set = (p: Partial<SaDisposalIn>) => setB({ ...b, ...p });
  const amount = (k: keyof SaDisposalIn) => (
    <input className={cn(INPUT, NUM)} defaultValue={(b[k] as number | null) ?? ""} onBlur={(e) => set({ [k]: e.target.value.trim() === "" ? (k.startsWith("rtt") ? null : 0) : Number(e.target.value.replace(/[£,]/g, "")) } as Partial<SaDisposalIn>)} />
  );
  const date = (k: "acquired" | "contract_date" | "completion_date" | "rtt_date") => (
    <input className={INPUT} type="date" value={b[k] ?? ""} onChange={(e) => set({ [k]: e.target.value || null })} />
  );
  const home = b.kind === "RESIDENTIAL";
  return (
    <div className="pt-4">
      <div className="grid gap-3 sm:grid-cols-4">
        <F label="Kind" wide>
          <CustomSelect fullWidth value={b.kind} onChange={(v) => set({ kind: v as SaDisposalKind })}
                        options={kinds.map((k) => ({ value: k.kind, label: k.label }))} />
        </F>
        <F label="Asset" wide><input className={INPUT} value={b.name} onChange={(e) => set({ name: e.target.value })} placeholder="12 Any Street, 500 Company A shares..." /></F>
        <F label="Person's share" hint="0.5 for a joint asset"><input className={cn(INPUT, NUM)} type="number" step="0.01" min={0.01} max={1} value={b.share} onChange={(e) => set({ share: Number(e.target.value) || 1 })} /></F>
        <F label="Bought on">{date("acquired")}</F>
        <F label="Contract (exchange) date" hint="The date of disposal (TCGA s28)">{date("contract_date")}</F>
        <F label="Completion date" hint={home ? "Starts the 60 days" : undefined}>{date("completion_date")}</F>
        <F label="Proceeds">{amount("proceeds")}</F>
        <F label="Cost" hint="Shares and crypto: the matched cost">{amount("cost")}</F>
        <F label="Buying and selling costs" hint="Fees, stamp duty">{amount("costs")}</F>
        <F label="Improvements">{amount("improvements")}</F>
        <F label="Claims">
          <span className="flex flex-col gap-1 text-xs text-slate-700">
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={b.badr} onChange={(e) => set({ badr: e.target.checked })} /> Business Asset Disposal Relief</label>
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={b.negligible} onChange={(e) => set({ negligible: e.target.checked })} /> Negligible value claim</label>
          </span>
        </F>
        {home && <>
          <F label="Months as main home" hint="Before the final 9 months, which always count"><input className={cn(INPUT, NUM)} type="number" min={0} value={b.main_home_months ?? ""} onChange={(e) => set({ main_home_months: e.target.value === "" ? null : Number(e.target.value) })} /></F>
          <F label="In the UK"><label className="flex items-center gap-1.5 pt-1.5 text-xs text-slate-700"><input type="checkbox" checked={b.uk} onChange={(e) => set({ uk: e.target.checked })} /> UK property (60-day return)</label></F>
          <F label="60-day return sent on">{date("rtt_date")}</F>
          <F label="Gain on the 60-day return">{amount("rtt_gain")}</F>
          <F label="Tax paid with it">{amount("rtt_tax")}</F>
        </>}
        <F label="Note" wide><input className={INPUT} value={b.note ?? ""} onChange={(e) => set({ note: e.target.value || null })} /></F>
      </div>
      <div className="mt-4 flex justify-end gap-2 border-t border-slate-100 pt-3">
        <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={onCancel}>Cancel</Button>
        <Button size="sm" className="h-8 text-xs" onClick={() => onSave(b)}>Save</Button>
      </div>
    </div>
  );
}

// Shares and crypto from their trades: each sale matched with the same day's buys, then the next 30 days', then the
// section 104 pool at average cost (TCGA s104-s106A). The year's sales become disposals above.
function Trades({ jobId, data, run }: { jobId: string; data: Data; run: (p: Promise<Data>) => void }) {
  const [t, setT] = useState({ holding: "", kind: "LISTED", on: "", side: "BUY", quantity: "", amount: "" });
  const [open, setOpen] = useState(false);
  const add = () => {
    const quantity = Number(t.quantity), amount = Number(t.amount.replace(/[£,]/g, ""));
    if (!t.holding.trim() || !t.on || !(quantity > 0) || isNaN(amount)) return toast.error("Enter the holding, date, quantity and amount");
    run(api.addSaShareTrade(jobId, { ...t, holding: t.holding.trim(), quantity, amount }));
    setT({ ...t, on: "", quantity: "", amount: "" });
  };
  return (
    <section className={TABLE_WRAP}>
      <div className="flex items-start justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div>
          <p className={text.card}>Shares and crypto from the trades</p>
          <p className="text-[11px] text-slate-500">Each sale is matched with buys of the same day, then the next 30 days, then the pool at average cost. Enter every buy and sale, or the pool brought forward.</p>
        </div>
        <AddButton onClick={() => setOpen(true)}>Add trade</AddButton>
      </div>
      {data.holdings.length === 0 && <p className="px-4 py-3 text-xs text-slate-500">No trades entered.</p>}
      {data.holdings.map((h) => (
        <div key={h.holding + h.kind} className="border-b border-slate-100 px-4 py-2 text-xs">
          <p className="font-semibold text-slate-800">{h.holding} <span className="font-normal text-slate-500">· {h.kind === "CRYPTO" ? "Crypto" : h.kind === "UNLISTED" ? "Unlisted" : "Listed"} · pool left {h.pool.qty.toLocaleString("en-GB")} costing {money(h.pool.cost)}</span></p>
          {h.issues.map((i) => <p key={i} className="text-rose-700">{i}</p>)}
          <div className="mt-1 grid gap-x-6 sm:grid-cols-2">
            <div>
              {h.trades.map((x) => (
                <p key={x.id} className="flex items-center gap-2 text-slate-600">
                  <span className={cn("w-16", NUM)}>{day(x.on)}</span>
                  <span className="w-10 font-semibold">{x.side === "POOL" ? "Pool" : x.side === "BUY" ? "Buy" : "Sell"}</span>
                  <span className={cn("w-20 text-right", NUM)}>{x.quantity.toLocaleString("en-GB")}</span>
                  <span className={cn("w-24 text-right", NUM)}>{money(x.amount)}</span>
                  <button type="button" title="Delete" onClick={() => run(api.deleteSaShareTrade(jobId, x.id))} className="rounded p-0.5 text-slate-400 hover:text-rose-600 cursor-pointer"><Trash2 className="h-3 w-3" /></button>
                </p>
              ))}
            </div>
            <div>
              {h.sales.map((s) => (
                <p key={s.on} className="text-slate-600">
                  Sale {day(s.on)}: cost <span className={NUM}>{money(s.cost)}</span> ({s.parts.map((p) => `${p.qty.toLocaleString("en-GB")} ${p.rule}`).join(", ")}), gain <b className={NUM}>{money(s.gain)}</b>
                </p>
              ))}
            </div>
          </div>
        </div>
      ))}
      <AddPopup open={open} onClose={() => setOpen(false)} onAdd={add} addLabel="Add trade" title="Add a trade"
                description="A buy (cost with fees), a sale (proceeds less fees), or the pool brought forward from earlier years.">
        <PopupField label="Holding" wide><input className={INPUT} placeholder="Company A plc, Bitcoin..." value={t.holding} onChange={(e) => setT({ ...t, holding: e.target.value })} /></PopupField>
        <PopupField label="Kind"><CustomSelect fullWidth value={t.kind} onChange={(v) => setT({ ...t, kind: v })}
          options={[{ value: "LISTED", label: "Listed shares" }, { value: "UNLISTED", label: "Unlisted shares" }, { value: "CRYPTO", label: "Crypto" }]} /></PopupField>
        <PopupField label="Trade"><CustomSelect fullWidth value={t.side} onChange={(v) => setT({ ...t, side: v })}
          options={[{ value: "BUY", label: "Buy" }, { value: "SELL", label: "Sell" }, { value: "POOL", label: "Pool brought forward" }]} /></PopupField>
        <PopupField label="Date"><input className={INPUT} type="date" value={t.on} onChange={(e) => setT({ ...t, on: e.target.value })} /></PopupField>
        <PopupField label="Quantity"><input className={cn(INPUT, NUM)} value={t.quantity} onChange={(e) => setT({ ...t, quantity: e.target.value })} /></PopupField>
        <PopupField label={t.side === "SELL" ? "Proceeds less fees (£)" : "Cost with fees (£)"} wide>
          <input className={cn(INPUT, NUM)} value={t.amount} onChange={(e) => setT({ ...t, amount: e.target.value })} /></PopupField>
      </AddPopup>
    </section>
  );
}

export function SaCapitalGains({ jobId, onOpen, onChange }: { jobId: string; onOpen: (page: string) => void; onChange?: () => void }) {
  const [data, setData] = useState<Data | null>(null);
  const [editing, setEditing] = useState<number | "new" | null>(null);
  useEffect(() => { api.getSaCapitalGains(jobId).then(setData).catch(() => {}); }, [jobId]);
  if (!data) return <div className="skeleton h-48 rounded-xl" />;

  const run = async (p: Promise<Data>) => {
    try { setData(await p); setEditing(null); onChange?.(); } catch (e: any) { toast.error("Not saved", { description: e.message }); }
  };
  const s = data.summary;
  const blocks = data.issues.filter((i) => i.block).length;

  return (
    <div className="space-y-4">
      <SaHead title="Capital gains"
              state={blocks ? { text: `${blocks} block${blocks > 1 ? "s" : ""}`, tone: "look" } : data.disposals.length ? { text: "Done", tone: "done" } : { text: "No disposals", tone: "empty" }}
              meta="Each disposal at its contract date, with home relief and the 60-day return for UK homes. This year's losses come off in full; losses brought forward only down to the annual exempt amount."
              actions={<Button size="sm" className="h-8 text-xs" onClick={() => setEditing("new")}><Plus className="mr-1 h-3.5 w-3.5" /> Add disposal</Button>}
              figures={[
                { label: "Net gains", value: money(s.net) },
                { label: "Chargeable gains", value: money(s.chargeable) },
                { label: "Capital gains tax", value: money(s.tax) },
                { label: "Paid on 60-day returns", value: money(s.paid_60_day) },
              ]} />

      {data.issues.length > 0 && (
        <div className="space-y-1 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-xs text-rose-900">
          {data.issues.map((i) => (
            <p key={i.key} className="flex gap-1.5">
              {i.kind === "CLIENT" ? <MessageSquareMore className="mt-px h-3.5 w-3.5 shrink-0" /> : <OctagonAlert className="mt-px h-3.5 w-3.5 shrink-0" />}
              <span>{i.text}{i.block && <b> Block.</b>}</span>
            </p>
          ))}
          <button type="button" onClick={() => onOpen("queries")} className="font-semibold underline cursor-pointer">Open Queries</button>
        </div>
      )}

      {/* Add or edit a disposal in a pop-up */}
      <Modal isOpen={editing !== null} onClose={() => setEditing(null)} className="max-w-3xl"
             title={editing === "new" ? "Add a disposal" : "Edit disposal"}
             description="Each thing sold or given away. Shares and crypto bought and sold through the year: use the trades below instead.">
        {editing !== null && (() => {
          const row = editing === "new" ? null : data.disposals.find((d) => d.id === editing);
          return <Form key={String(editing)} kinds={data.kinds} start={row ? row.input : BLANK}
                       onSave={(b) => run(api.saveSaDisposal(jobId, b, row ? row.id : undefined))} onCancel={() => setEditing(null)} />;
        })()}
      </Modal>

      <section className={TABLE_WRAP}>
        <table className="w-full table-fixed text-xs">
          <thead className={THEAD}>
            <tr className="text-left">
              <th className="px-4 py-2 font-semibold">Asset</th>
              <th className="w-20 px-3 py-2 font-semibold">Sold</th>
              <th className="w-24 px-3 py-2 text-right font-semibold">Proceeds</th>
              <th className="w-24 px-3 py-2 text-right font-semibold">Costs</th>
              <th className="w-24 px-3 py-2 text-right font-semibold">Home relief</th>
              <th className="w-28 px-3 py-2 text-right font-semibold">Gain (loss)</th>
              <th className="w-16" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.disposals.length === 0 && <tr><td colSpan={7} className="px-4 py-3 text-slate-500">No disposals entered.</td></tr>}
            {data.disposals.map((d) => (
              <tr key={d.id} className={cn(TROW, "align-top", !d.in_year && "opacity-60")}>
                <td className="px-4 py-2">
                  <p className="font-semibold text-slate-800">{d.name}</p>
                  <p className="text-[11px] text-slate-500">{d.kind_label}{d.badr && " · BADR"}{d.negligible && " · negligible value"}{!d.in_year && " · not this year"}</p>
                  {d.notes.map((n) => <p key={n} className="text-[11px] text-slate-400">{n.replace(`${d.name}: `, "")}</p>)}
                </td>
                <td className="px-3 py-2 text-slate-600">{day(d.sold)}</td>
                <td className={cn("px-3 py-2 text-right", NUM)}>{money(d.proceeds)}</td>
                <td className={cn("px-3 py-2 text-right", NUM)}>{money(d.allowable)}</td>
                <td className={cn("px-3 py-2 text-right", NUM)}>{d.relief ? money(d.relief) : "—"}</td>
                <td className={cn("px-3 py-2 text-right font-semibold", NUM, d.gain < 0 && "text-rose-700")}>{money(d.gain)}</td>
                <td className="px-2 py-1.5 text-right">
                  {d.matched ? <span className="text-[10.5px] text-slate-400">from trades</span> : (
                  <span className="inline-flex gap-1">
                    <button type="button" title="Edit" onClick={() => setEditing(d.id)} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-teal-700 cursor-pointer"><Pencil className="h-3.5 w-3.5" /></button>
                    <button type="button" title="Delete" onClick={() => run(api.deleteSaDisposal(jobId, d.id))} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-rose-600 cursor-pointer"><Trash2 className="h-3.5 w-3.5" /></button>
                  </span>)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <Trades jobId={jobId} data={data} run={run} />

      <section className={cn(TABLE_WRAP, "p-4")}>
        <p className={text.card}>The year&apos;s capital gains tax</p>
        <div className="mt-2 grid gap-x-8 text-xs sm:grid-cols-2">
          <dl className="divide-y divide-slate-100">
            {([["Gains", s.gains], ["Less losses this year", -s.losses], ["Net gains", s.net], ["Less losses brought forward", -s.losses_bf_used],
               ["Less annual exempt amount", -s.exempt_used], ["Chargeable gains", s.chargeable]] as [string, number][]).map(([k, v]) => (
              <div key={k} className="flex justify-between py-1"><dt className="text-slate-600">{k}</dt><dd className={NUM}>{money(v)}</dd></div>
            ))}
          </dl>
          <div>
            {s.lines.map((l, i) => (
              <p key={i} className="flex justify-between py-1"><span className="text-slate-600">{l.name}: {l.band === "BADR" ? "BADR" : l.band} {money(l.amount)} at {(l.rate * 100).toFixed(0)}%</span><span className={NUM}>{money(l.tax)}</span></p>
            ))}
            <p className="flex justify-between border-t border-slate-200 py-1 font-semibold"><span>Capital gains tax</span><span className={NUM}>{money(s.tax)}</span></p>
            <label className="mt-2 flex items-center justify-between gap-2 text-slate-600">
              Losses brought forward
              <input className={cn(INPUT, NUM, "w-32")} defaultValue={data.losses_bf || ""} key={data.losses_bf}
                     onBlur={(e) => { const v = Number(e.target.value.replace(/[£,]/g, "") || 0); if (v !== data.losses_bf) run(api.putSaCapitalLosses(jobId, v)); }} />
            </label>
            {s.loss_cf > 0 && <p className="mt-1 text-slate-500">Losses to carry forward: <span className={NUM}>{money(s.loss_cf)}</span></p>}
          </div>
        </div>
      </section>
    </div>
  );
}
