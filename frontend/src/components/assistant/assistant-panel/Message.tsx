// One chat message (the question bubble or the answer with its steps, charts, files, actions and sources).

import { useState } from "react";
import { Check, ChevronDown, Copy, Loader2 } from "lucide-react";
import type { ChatMessage, ChatSource, ChatUpload } from "@/lib/api/assistant";
import { Markdown } from "../Markdown";
import { ChartCard, FileCard } from "../Outputs";
import { ActionCard } from "../ActionCard";
import { UploadTile } from "../Attachments";
import { When } from "./time";

export function Steps({ steps, live = false }: { steps: string[]; live?: boolean }) {
  const [shown, setShown] = useState(false);
  if (!steps.length) return null;
  if (live) {
    return (
      <ul className="mb-2 space-y-0.5">
        {steps.map((s, i) => (
          <li key={i} className="flex items-center gap-1.5 text-[11.5px] text-slate-500">
            {i === steps.length - 1 ? <Loader2 className="h-3 w-3 animate-spin" /> : <span className="h-1.5 w-1.5 rounded-full bg-teal-500" />}
            {s}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <div className="mb-1">
      <button type="button" onClick={() => setShown((v) => !v)} className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-600">
        Looked at {steps.length} {steps.length === 1 ? "thing" : "things"}
        <ChevronDown className={`h-3 w-3 transition ${shown ? "rotate-180" : ""}`} />
      </button>
      {shown && (
        <ul className="mt-1 space-y-0.5 border-l-2 border-slate-100 pl-2">
          {steps.map((s, i) => <li key={i} className="text-[11px] text-slate-500">{s}</li>)}
        </ul>
      )}
    </div>
  );
}

/** The law sources an answer used, each a link to the HMRC / legislation page (the date HMRC last changed it on hover). */
export function Sources({ sources }: { sources: ChatSource[] }) {
  if (!sources.length) return null;
  return (
    <div className="mt-2.5 border-t border-slate-100 pt-2">
      <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-slate-400">Sources</p>
      <div className="flex flex-wrap gap-1.5">
        {sources.map((x) => (
          <a key={x.url} href={x.url} target="_blank" rel="noopener noreferrer"
             title={`${x.document}: ${x.title}${x.updated ? ` (updated ${new Date(x.updated).toLocaleDateString("en-GB")})` : ""}`}
             className="inline-flex max-w-full items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-[11px] text-slate-700 transition hover:border-teal-300 hover:bg-teal-50 hover:text-teal-800">
            <span className="font-semibold">{x.ref}</span>
            <span className="truncate text-slate-500">{x.title.length > 48 ? `${x.title.slice(0, 46)}…` : x.title}</span>
          </a>
        ))}
      </div>
    </div>
  );
}

export function Message({ m, onUpdated, onOpenFile, showCost = false }: {
  m: ChatMessage; onUpdated: (m: ChatMessage) => void; onOpenFile: (u: ChatUpload) => void; showCost?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  if (m.role === "user") {
    const files = m.suggestions?.attachments || [];
    return (
      <div className="group/user flex flex-col items-end gap-2">
        {files.length > 0 && (
          <div className="flex max-w-[85%] flex-wrap justify-end gap-1.5">
            {files.map((u) => <UploadTile key={u.id} u={u} small onOpen={() => onOpenFile(u)} />)}
          </div>
        )}
        <p className="max-w-[85%] whitespace-pre-wrap rounded-3xl bg-slate-100 px-4 py-2.5 text-[14px] leading-relaxed text-slate-900">{m.content}</p>
        <span className="-mt-1 pr-2 opacity-0 transition group-hover/user:opacity-100"><When iso={m.created_at} /></span>
      </div>
    );
  }
  const cost = m.cost_usd ? `$${m.cost_usd < 0.01 ? m.cost_usd.toFixed(4) : m.cost_usd.toFixed(3)}` : "";
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(m.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* not copied */ }
  };
  return (
    <div className="group">
      <Steps steps={m.steps || []} />
      {(m.suggestions?.charts || []).map((c, i) => <ChartCard key={i} chart={c} />)}
      <div className="text-[14px]"><Markdown text={m.content} /></div>
      {(m.suggestions?.files || []).length > 0 && (
        <div className="mt-2 space-y-1.5">
          {(m.suggestions.files || []).map((f) => <FileCard key={f.id} file={f} />)}
        </div>
      )}
      {(m.suggestions?.actions || []).map((a) => (
        <ActionCard key={a.id} messageId={m.id} action={a} onDecided={onUpdated} />
      ))}
      <Sources sources={m.suggestions?.sources || []} />
      <div className="mt-1.5 flex items-center gap-1.5">
        <button type="button" onClick={copy} title={copied ? "Copied" : "Copy"} aria-label={copied ? "Copied" : "Copy"} className={`rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 cursor-pointer ${copied ? "" : "opacity-0 group-hover:opacity-100 focus:opacity-100"}`}>
          {copied ? <Check className="h-3.5 w-3.5 text-teal-600" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
        <When iso={m.created_at} extra={[m.tokens ? `${(m.tokens / 1000).toFixed(1)}k tokens` : "", cost].filter(Boolean).join(", ")} />
        {showCost && (m.tokens || cost) && (
          <span className="text-[11px] tabular-nums text-slate-400">
            · {[m.tokens ? `${(m.tokens / 1000).toFixed(1)}k tokens` : "", cost].filter(Boolean).join(" · ")}
          </span>
        )}
      </div>
    </div>
  );
}
