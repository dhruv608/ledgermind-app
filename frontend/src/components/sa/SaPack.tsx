"use client";

// The working paper pack: an Excel workbook in the firm's working paper style. Every version is kept as
// made with its note (R-OUT-02); a final pack waits until no Block is open (R-OUT-01), a draft can be made any time
// for review and says so on every sheet.
import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { Download, FileSpreadsheet, OctagonAlert } from "lucide-react";
import { api, SaPacks as Data } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { NUM, PILL, SaHead, TABLE_WRAP, THEAD, TROW, text } from "@/components/sa/SaChrome";
import { cn } from "@/lib/utils";

const money = (v: number) => `${v < 0 ? "-" : ""}£${Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const when = (iso: string | null) => (iso ? new Date(iso + "Z").toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
const SHEETS = "Summary, Client info, PAYE, a sheet for each business, Property, Savings and dividends, Last year vs this year, Tax computation, Queries, Accountant decisions, Evidence map and Export (figures by SA box).";

export function SaPack({ jobId, onOpen }: { jobId: string; onOpen: (page: string) => void }) {
  const [data, setData] = useState<Data | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.getSaPacks(jobId).then(setData).catch(() => {}); }, [jobId]);
  if (!data) return <div className="skeleton h-48 rounded-xl" />;

  const blocks = data.counts.blocks;
  const make = async (final: boolean) => {
    setBusy(true);
    try {
      const out = await api.makeSaPack(jobId, final, note.trim() || null);
      setData(out);
      setNote("");
      toast.success(`${final ? "Final" : "Draft"} version ${out.versions[0].version} made`);
    } catch (e: any) {
      toast.error("Pack not made", { description: e.message });
    } finally {
      setBusy(false);
    }
  };
  const download = async (id: number) => {
    try { await api.downloadSaPack(jobId, id); } catch (e: any) { toast.error("Not downloaded", { description: e.message }); }
  };
  const latest = data.versions[0];

  return (
    <div className="space-y-4">
      <SaHead title="Working paper pack"
              state={blocks ? { text: `${blocks} block${blocks > 1 ? "s" : ""} open`, tone: "look" }
                     : latest?.kind === "FINAL" ? { text: `Final v${latest.version}`, tone: "done" } : { text: "Ready for a final pack", tone: "info" }}
              meta={`The working paper in the firm's style: ${SHEETS} Each version is kept as made.`}
              figures={[
                { label: "Versions", value: String(data.versions.length) },
                { label: "Latest", value: latest ? `${latest.kind === "FINAL" ? "Final" : "Draft"} v${latest.version}` : "None yet" },
                { label: "Blocks open", value: String(blocks), tone: blocks ? "text-rose-700" : undefined },
              ]} />

      <section className={cn(TABLE_WRAP, "p-4")}>
        <p className={text.card}>Make a new version</p>
        {blocks > 0 && (
          <p className="mt-2 flex items-start gap-1.5 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-800">
            <OctagonAlert className="mt-px h-3.5 w-3.5 shrink-0" />
            <span>{blocks} block{blocks > 1 ? "s" : ""} open: a final pack waits until {blocks > 1 ? "they are" : "it is"} answered.
              A draft can be made for review; it says DRAFT on every sheet.{" "}
              <button type="button" onClick={() => onOpen("queries")} className="font-semibold underline cursor-pointer">Open Queries</button></span>
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder="Version note (what changed, who it is for)"
                 className="h-8 min-w-0 flex-1 rounded-md border border-slate-200 px-2.5 text-xs focus:border-teal-500 focus:outline-none" />
          <Button size="sm" variant="outline" className="h-8 text-xs" disabled={busy} onClick={() => make(false)}>Make draft</Button>
          <Button size="sm" className="h-8 text-xs" disabled={busy || blocks > 0} onClick={() => make(true)}
                  title={blocks ? "Answer the Blocks on Queries first" : undefined}>
            <FileSpreadsheet className="mr-1 h-3.5 w-3.5" /> Make final pack
          </Button>
        </div>
      </section>

      <section className={TABLE_WRAP}>
        <div className="border-b border-slate-200 px-4 py-3"><p className={text.card}>Versions</p></div>
        <table className="w-full table-fixed text-xs">
          <thead className={THEAD}>
            <tr className="text-left">
              <th className="w-20 px-4 py-2 font-semibold">Version</th>
              <th className="w-36 px-3 py-2 font-semibold">Kind</th>
              <th className="px-3 py-2 font-semibold">Note</th>
              <th className="w-36 px-3 py-2 font-semibold">Made</th>
              <th className="w-28 px-3 py-2 text-right font-semibold">Balance to pay</th>
              <th className="w-24" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.versions.length === 0 && <tr><td colSpan={6} className="px-4 py-3 text-slate-500">No pack made yet.</td></tr>}
            {data.versions.map((v) => (
              <tr key={v.id} className={TROW}>
                <td className="px-4 py-2 font-semibold text-slate-700">v{v.version}</td>
                <td className="px-3 py-2">
                  <span className={cn("rounded-full px-2 py-px text-[10.5px] font-bold", v.kind === "FINAL" ? PILL.done : PILL.look)}>
                    {v.kind === "FINAL" ? "Final" : `Draft · ${v.blocks} block${v.blocks === 1 ? "" : "s"}`}
                  </span>
                </td>
                <td className="px-3 py-2 text-slate-700">{v.note || <span className="text-slate-400">—</span>}</td>
                <td className="px-3 py-2 text-slate-500">{when(v.created_at)}{v.made_by && <span className="block text-[11px]">{v.made_by}</span>}</td>
                <td className={cn("px-3 py-2 text-right", NUM)}>{v.balance === null ? "—" : money(v.balance)}</td>
                <td className="px-2 py-1.5 text-right">
                  <button type="button" onClick={() => download(v.id)} className="inline-flex items-center gap-1 text-[11px] font-semibold text-teal-700 hover:underline cursor-pointer">
                    <Download className="h-3.5 w-3.5" /> Excel
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
