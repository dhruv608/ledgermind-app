"use client";

import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { assistantApi, type AssistantMeter, type MeterSpend } from "@/lib/api/assistant";

/** The chat page's cost meter, at the foot of the chats sidebar: today's spend against the day's limit, tokens in and
 * out, and (opened) this chat, this month, ever, and the prices used. Real AWS London prices, in US$. */

const usd = (v: number) => (v < 0.01 && v > 0 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`);
const tok = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

function Row({ label, s }: { label: string; s: MeterSpend | { tokens_in: number; tokens_out: number; usd: number } }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-slate-500">{label}</span>
      <span className="tabular-nums text-slate-700" title={`${s.tokens_in.toLocaleString()} in, ${s.tokens_out.toLocaleString()} out`}>
        {tok(s.tokens_in + s.tokens_out)} · {usd(s.usd)}
      </span>
    </div>
  );
}

export function CostMeter({ chatId, tick }: { chatId: string | null; tick: number }) {
  const [m, setM] = useState<AssistantMeter | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    assistantApi.meter(chatId).then((x) => alive && setM(x)).catch(() => undefined);
    return () => { alive = false; };
  }, [chatId, tick]);

  if (!m) return null;
  const t = m.today;
  const limit = m.limit_usd;
  const share = limit ? Math.min(t.usd / limit, 1) : 0;
  const bar = share >= 0.9 ? "bg-rose-500" : share >= 0.7 ? "bg-amber-500" : "bg-teal-600";
  const price = m.prices[m.model];

  return (
    <div className="border-t border-slate-200 px-3 py-2.5 text-[11.5px]">
      <button type="button" onClick={() => setOpen((v) => !v)} className="w-full text-left cursor-pointer" aria-expanded={open}>
        <div className="flex items-baseline justify-between">
          <span className="font-medium text-slate-700">Today</span>
          <span className="tabular-nums text-slate-800">
            {usd(t.usd)}{limit ? <span className="text-slate-400"> of {usd(limit)}</span> : null}
          </span>
        </div>
        {limit ? (
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-200">
            <div className={`h-full rounded-full ${bar}`} style={{ width: `${Math.max(share * 100, t.usd > 0 ? 2 : 0)}%` }} />
          </div>
        ) : null}
        <div className="mt-1.5 flex items-center justify-between text-slate-500">
          <span className="tabular-nums">{tok(t.tokens_in)} in · {tok(t.tokens_out)} out · {t.answers} {t.answers === 1 ? "answer" : "answers"}</span>
          <ChevronDown className={`h-3.5 w-3.5 transition ${open ? "rotate-180" : ""}`} />
        </div>
      </button>
      {open && (
        <div className="mt-2 space-y-1 border-t border-slate-100 pt-2">
          {m.chat && <Row label="This chat" s={m.chat} />}
          <Row label="This month" s={m.month} />
          <Row label="Ever" s={m.total} />
          {(t.voice_seconds > 0 || t.files_usd > 0) && (
            <p className="text-slate-400">
              Today: voice {Math.round(t.voice_seconds)}s ({usd(t.voice_usd)}), files read {usd(t.files_usd)}
            </p>
          )}
          {price && (
            <p className="pt-1 leading-snug text-slate-400">
              {m.model}: ${price.in} in, ${price.out} out per million tokens; voice about ${m.voice_per_minute.toFixed(3)} a minute
              (AWS London)
            </p>
          )}
        </div>
      )}
    </div>
  );
}
