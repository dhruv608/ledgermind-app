"use client";

// This year's questions (R-EX-05: the yearly yes/no list, every one answered) and the signs of new income in
// the bank statements (each one a question to confirm, never an assumption). Shown on the Last year page,
// under last year's sources.
import { useEffect, useState } from "react";
import { toast } from "@/lib/notify";
import { ChevronDown, ChevronRight, MessageSquareMore, Radar } from "lucide-react";
import { api, SaQuestions as Data, SaSignal } from "@/lib/api";
import { NUM, PILL, TABLE_WRAP, text } from "@/components/sa/SaChrome";
import { cn } from "@/lib/utils";

const money = (v: number) => `£${v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const day = (iso: string) => { const [y, m, d] = iso.split("-"); return `${d}/${m}/${y.slice(2)}`; };

function Choice({ value, options, onPick }: { value: string | null; options: [string, string][]; onPick: (v: string | null) => void }) {
  return (
    <span className="inline-flex shrink-0 overflow-hidden rounded-md border border-slate-200">
      {options.map(([v, label]) => (
        <button key={v} type="button" onClick={() => onPick(value === v ? null : v)}
                className={cn("px-2.5 py-1 text-[11.5px] font-semibold cursor-pointer",
                  value === v ? (v === "YES" || v === "ASKED" ? "bg-teal-700 text-white" : "bg-slate-700 text-white") : "bg-white text-slate-600 hover:bg-slate-50")}>
          {label}
        </button>
      ))}
    </span>
  );
}

function Signal({ s, onPick }: { s: SaSignal; onPick: (v: string | null) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={cn("px-4 py-2.5", s.state === "DISMISSED" && "opacity-60")}>
      <div className="flex items-start justify-between gap-3">
        <button type="button" onClick={() => setOpen(!open)} className="flex min-w-0 items-start gap-1.5 text-left cursor-pointer">
          {open ? <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" /> : <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />}
          <span className="min-w-0">
            <span className="block text-xs font-semibold text-slate-800">{s.title} <span className="font-normal text-slate-500">· {s.lines.length} line{s.lines.length > 1 ? "s" : ""} · <span className={NUM}>{money(s.total)}</span></span></span>
            <span className="mt-0.5 flex gap-1.5 text-[11.5px] text-amber-900"><MessageSquareMore className="mt-px h-3.5 w-3.5 shrink-0" />{s.question}</span>
          </span>
        </button>
        <Choice value={s.state} options={[["ASKED", "Ask"], ["DISMISSED", "Not income"]]} onPick={onPick} />
      </div>
      {open && (
        <div className="mt-2 ml-5 space-y-0.5">
          {s.lines.map((l, i) => (
            <p key={i} className="flex gap-3 text-[11.5px] text-slate-600">
              <span className={cn("w-16 shrink-0", NUM)}>{day(l.on)}</span>
              <span className="min-w-0 flex-1 truncate">{l.description}</span>
              <span className={cn("shrink-0", NUM)}>{money(l.amount)}</span>
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

export function SaQuestions({ jobId }: { jobId: string }) {
  const [data, setData] = useState<Data | null>(null);
  useEffect(() => { api.getSaQuestions(jobId).then(setData).catch(() => {}); }, [jobId]);
  if (!data) return <div className="skeleton h-32 rounded-xl" />;

  const put = async (key: string, value: string | null) => {
    try { setData(await api.putSaAnswer(jobId, key, value)); } catch (e: any) { toast.error("Not saved", { description: e.message }); }
  };
  const unanswered = data.questions.filter((q) => !q.answer).length;
  const openSigns = data.signals.filter((s) => !s.state).length;

  return (
    <>
      <section className={TABLE_WRAP}>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
          <p className={text.card}>This year&apos;s questions</p>
          <span className={cn("rounded-full px-2 py-px text-[10.5px] font-bold", unanswered ? PILL.look : PILL.done)}>
            {unanswered ? `${unanswered} not answered` : "All answered"}
          </span>
        </div>
        <div className="divide-y divide-slate-100">
          {data.questions.map((q) => (
            <div key={q.key} className="flex items-start justify-between gap-3 px-4 py-2">
              <div className="min-w-0">
                <p className="text-xs text-slate-800">{q.question}</p>
                {q.last_year && <p className="text-[11px] text-slate-400">Last year: {q.last_year}</p>}
                {q.follow && <p className="mt-0.5 text-[11.5px] text-teal-800">{q.follow}</p>}
              </div>
              <Choice value={q.answer} options={[["YES", "Yes"], ["NO", "No"]]} onPick={(v) => put(`q:${q.key}`, v)} />
            </div>
          ))}
        </div>
      </section>

      <section className={TABLE_WRAP}>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
          <p className={cn(text.card, "flex items-center gap-1.5")}><Radar className="h-4 w-4 text-teal-700" />Signs of new income in the bank</p>
          {data.signals.length > 0 && (
            <span className={cn("rounded-full px-2 py-px text-[10.5px] font-bold", openSigns ? PILL.look : PILL.done)}>
              {openSigns ? `${openSigns} to decide` : "All decided"}
            </span>
          )}
        </div>
        {data.bank_lines === 0 ? (
          <p className="px-4 py-3 text-xs text-slate-500">No bank statements for the year: add them on Documents and they are looked through here.</p>
        ) : data.signals.length === 0 ? (
          <p className="px-4 py-3 text-xs text-slate-500">Nothing found in {data.bank_lines} bank lines: no dividends, rent, money from abroad, platform sales, savings or pension payments, or large one-off payments in.</p>
        ) : (
          <div className="divide-y divide-slate-100">
            {data.signals.map((s) => <Signal key={s.key} s={s} onPick={(v) => put(`s:${s.key}`, v)} />)}
          </div>
        )}
      </section>
    </>
  );
}
