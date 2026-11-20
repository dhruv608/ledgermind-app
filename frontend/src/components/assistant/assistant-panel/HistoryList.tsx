// The list of past chats, grouped by day, with search, the client / all clients switch and delete.

import { useEffect, useMemo, useState } from "react";
import { Loader2, Search, Trash2 } from "lucide-react";
import { assistantApi, type ChatSummary } from "@/lib/api/assistant";
import { dayGroup } from "./time";

export function HistoryList({ clientId, clientName, currentId, onOpen, onDeleted, sidebar = false, footer, tick = 0 }: {
  clientId: string | null; clientName: string | null; currentId: string | null;
  onOpen: (id: string) => void; onDeleted: (id: string) => void; sidebar?: boolean;
  footer?: React.ReactNode;           // in place of the month's cost line (the chat page's cost meter)
  tick?: number;                      // bumped after each answer: a new chat appears with its title
}) {
  const [q, setQ] = useState("");
  const [all, setAll] = useState(!clientId);
  const [chats, setChats] = useState<ChatSummary[] | null>(null);
  const [usage, setUsage] = useState<{ month_usd: number; month_answers: number } | null>(null);

  useEffect(() => {
    let alive = true;
    const t = setTimeout(() => {
      assistantApi.listChats(clientId, q, all).then((c) => alive && setChats(c)).catch(() => alive && setChats([]));
    }, q ? 250 : 0);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [clientId, q, all, tick]);
  useEffect(() => {
    if (!footer) assistantApi.usage().then(setUsage).catch(() => setUsage(null));
  }, [footer]);

  const groups = useMemo(() => {
    const out: [string, ChatSummary[]][] = [];
    for (const c of chats || []) {
      const g = dayGroup(c.updated_at);
      const found = out.find((x) => x[0] === g);
      if (found) found[1].push(c);
      else out.push([g, [c]]);
    }
    return out;
  }, [chats]);

  const remove = async (id: string) => {
    await assistantApi.deleteChat(id).catch(() => undefined);
    setChats((c) => (c || []).filter((x) => x.id !== id));
    onDeleted(id);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className={`space-y-2 px-2 ${sidebar ? "pb-2" : "py-3"}`}>
        <div className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-slate-500 transition focus-within:bg-white focus-within:ring-1 focus-within:ring-slate-200 hover:bg-slate-100/70">
          <Search className="h-4 w-4 shrink-0" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search chats"
                 className="focus-in-parent min-w-0 flex-1 bg-transparent text-[13px] text-slate-800 outline-none placeholder:text-slate-500" />
        </div>
        {clientId && (
          <div className="flex gap-1 px-1 text-[12px]">
            {[[false, clientName || "This client"], [true, "All clients"]].map(([v, label]) => (
              <button key={String(v)} type="button" onClick={() => setAll(v as boolean)}
                      className={`truncate rounded-md px-2 py-1 transition cursor-pointer ${all === v ? "bg-slate-200/70 font-medium text-slate-900" : "text-slate-500 hover:bg-slate-100"}`}>
                {label as string}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="lm-scroll min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {chats === null && <p className="flex items-center gap-2 px-2.5 py-2 text-[12.5px] text-slate-400"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading</p>}
        {chats?.length === 0 && <p className="px-2.5 py-2 text-[12.5px] text-slate-400">{q ? "No chats match." : "No chats yet."}</p>}
        {groups.map(([g, list]) => (
          <div key={g} className="mb-3">
            <p className="px-2.5 pb-1 pt-2 text-[11.5px] font-medium text-slate-400">{g}</p>
            {list.map((c) => (
              <div key={c.id}
                   className={`group flex items-center rounded-lg transition ${c.id === currentId ? "bg-slate-200/70" : "hover:bg-slate-100"}`}>
                <button type="button" onClick={() => onOpen(c.id)} title={all && c.client_name ? `${c.title} · ${c.client_name}` : c.title}
                        className="min-w-0 flex-1 px-2.5 py-2 text-left cursor-pointer">
                  <p className="truncate text-[13px] text-slate-800">{c.title}</p>
                </button>
                <button type="button" onClick={() => remove(c.id)} title="Delete chat"
                        className="mr-1 rounded-md p-1 text-slate-400 opacity-0 transition hover:bg-slate-200 hover:text-rose-600 group-hover:opacity-100 cursor-pointer">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        ))}
      </div>
      {footer}
      {!footer && usage && (
        <p className="border-t border-slate-100 px-4 py-2.5 text-[11px] text-slate-400">
          This month: {usage.month_answers} answers · about ${usage.month_usd.toFixed(2)}
        </p>
      )}
    </div>
  );
}
