"use client";

// Queries (the firm's Queries sheet): client queries in plain English with the client's answer, and the accountant's
// decisions. Each comes from its page (last year's checklist, this year's questions, the bank signs) and its answer
// is kept there. A Block stops the return being finished. The open client queries can be copied as one message.
import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { ArrowRight, Copy, OctagonAlert } from "lucide-react";
import { api, SaQueries as Data, SaQueryItem } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { PILL, SaHead, TABLE_WRAP, THEAD, TROW, text } from "@/components/sa/SaChrome";
import { cn } from "@/lib/utils";

const STATUS: Record<SaQueryItem["status"], [string, string]> = {
  OPEN: ["Open", PILL.look], ANSWERED: ["Answered", PILL.info], DONE: ["Actioned", PILL.done],
};
const PAGE_LABELS: Record<string, string> = { "last-year": "Last year" };

function Table({ title, items, answerable, onAnswer, onOpen }: {
  title: string; items: SaQueryItem[]; answerable: boolean;
  onAnswer: (key: string, v: string) => void; onOpen: (page: string) => void;
}) {
  return (
    <section className={TABLE_WRAP}>
      <div className="border-b border-slate-200 px-4 py-3"><p className={text.card}>{title}</p></div>
      <table className="w-full table-fixed text-xs">
        <thead className={THEAD}>
          <tr className="text-left">
            <th className="w-12 px-4 py-2 font-semibold">No.</th>
            <th className="px-3 py-2 font-semibold">{answerable ? "Query" : "Decision"}</th>
            {answerable && <th className="w-[32%] px-3 py-2 font-semibold">Answer</th>}
            <th className="w-28 px-3 py-2 font-semibold">Status</th>
            <th className="w-20" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.length === 0 && <tr><td colSpan={5} className="px-4 py-3 text-slate-500">None.</td></tr>}
          {items.map((q) => (
            <tr key={q.key} className={cn(TROW, "align-top")}>
              <td className="px-4 py-2 font-semibold text-slate-500">{q.no}</td>
              <td className="px-3 py-2">
                <p className="text-slate-800">{q.text}</p>
                <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-400">
                  {q.block && <span className="inline-flex items-center gap-0.5 rounded-full bg-rose-50 px-1.5 py-px font-bold text-rose-700"><OctagonAlert className="h-3 w-3" />Block</span>}
                  {q.about}
                </p>
              </td>
              {answerable && (
                <td className="px-2 py-1.5">
                  <textarea key={q.answer || ""} defaultValue={q.answer || ""} rows={2} placeholder="The client's answer"
                            onBlur={(e) => { if (e.target.value.trim() !== (q.answer || "")) onAnswer(q.key, e.target.value); }}
                            className="w-full resize-y rounded border border-slate-200 bg-white px-2 py-1 text-xs focus:border-teal-500 focus:outline-none" />
                </td>
              )}
              <td className="px-3 py-2">
                <span className={cn("rounded-full px-2 py-px text-[10.5px] font-bold", STATUS[q.status][1])}>{STATUS[q.status][0]}</span>
              </td>
              <td className="px-2 py-2 text-right">
                <button type="button" onClick={() => onOpen(q.page)} className="inline-flex items-center gap-0.5 text-[11px] font-semibold text-teal-700 hover:underline cursor-pointer">
                  {PAGE_LABELS[q.page] || "Open"}<ArrowRight className="h-3 w-3" />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function SaQueries({ jobId, onOpen }: { jobId: string; onOpen: (page: string) => void }) {
  const [data, setData] = useState<Data | null>(null);
  useEffect(() => { api.getSaQueries(jobId).then(setData).catch(() => {}); }, [jobId]);
  if (!data) return <div className="skeleton h-48 rounded-xl" />;

  const answer = async (key: string, v: string) => {
    try { setData(await api.answerSaQuery(jobId, key, v.trim() || null)); } catch (e: any) { toast.error("Not saved", { description: e.message }); }
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(data.message); toast.success("Open client queries copied"); }
    catch { toast.error("Could not copy"); }
  };
  const client = data.items.filter((i) => i.kind === "CLIENT");
  const decisions = data.items.filter((i) => i.kind === "DECISION");
  const c = data.counts;

  return (
    <div className="space-y-4">
      <SaHead title="Queries"
              state={c.blocks ? { text: `${c.blocks} block${c.blocks > 1 ? "s" : ""}`, tone: "look" }
                     : c.client || c.decisions ? { text: "Open", tone: "look" } : { text: "None open", tone: "done" }}
              meta="Questions for the client in plain English, and the accountant's decisions. Each comes from its page and is answered there or here. The return cannot be finished while a Block is open."
              actions={client.some((q) => q.status === "OPEN") ? (
                <Button size="sm" variant="outline" className="h-8 text-xs" onClick={copy}><Copy className="mr-1 h-3.5 w-3.5" /> Copy for the client</Button>
              ) : undefined}
              figures={[
                { label: "Blocks open", value: String(c.blocks), tone: c.blocks ? "text-rose-700" : undefined },
                { label: "Client queries open", value: String(c.client) },
                { label: "Decisions open", value: String(c.decisions) },
              ]} />
      <Table title="Client queries" items={client} answerable onAnswer={answer} onOpen={onOpen} />
      <Table title="Accountant decisions" items={decisions} answerable={false} onAnswer={answer} onOpen={onOpen} />
    </div>
  );
}
