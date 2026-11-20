// The client questions by group, with answers, the client email, and the list to copy or download.

import { useMemo, useState } from "react";
import { Check, Copy, Download, Loader2, Mail } from "lucide-react";
import { toast } from "@/lib/notify";
import { Button } from "@/components/ui/button";
import { BooksQuestion } from "@/lib/api";
import { ClientEmailDialog } from "@/components/clients/ClientEmailDialog";
import { Empty } from "./common";

export const GROUPS: { group: BooksQuestion["group"]; title: string }[] = [
  { group: "explain", title: "Please explain" },
  { group: "confirm", title: "Please confirm" },
  { group: "documents", title: "Documents we need" },
];

export function Questions({ questions, client, yearEnd, saving, onChoose }: {
  questions: BooksQuestion[];
  client: string;
  yearEnd: string | null;
  saving: string | null;
  onChoose: (key: string, value: Record<string, unknown> | null) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [emailOpen, setEmailOpen] = useState(false);
  // The email asks only what is still open (answered questions are left out)
  const emailGroups = useMemo(() => GROUPS.map((g) => ({
    title: g.title, items: questions.filter((q) => q.group === g.group && !q.answered).map((q) => q.text),
  })), [questions]);
  const listText = () => {
    const lines = [`Questions for ${client || "the client"}`, ""];
    for (const g of GROUPS) {
      const qs = questions.filter((q) => q.group === g.group && !q.answered);
      if (!qs.length) continue;
      lines.push(g.title, ...qs.map((q, i) => `${i + 1}. ${q.text}`), "");
    }
    return lines.join("\n");
  };
  const download = () => {
    const blob = new Blob([listText()], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `Questions - ${client || "client"}.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  if (!questions.length) return <Empty text="No questions for the client." />;
  return (
    <div className="space-y-4">
      <ClientEmailDialog isOpen={emailOpen} onClose={() => setEmailOpen(false)} client={client} yearEnd={yearEnd} groups={emailGroups} />
      <div className="flex flex-wrap justify-end gap-2">
        <Button size="sm" variant="primary" disabled={!emailGroups.some((g) => g.items.length)} onClick={() => setEmailOpen(true)}>
          <Mail className="mr-1.5 h-3.5 w-3.5" /> Make client email
        </Button>
        <Button size="sm" variant="outline" onClick={() => navigator.clipboard.writeText(listText()).then(() => toast.success("Copied"))}>
          <Copy className="mr-1.5 h-3.5 w-3.5" /> Copy list
        </Button>
        <Button size="sm" variant="outline" onClick={download}>
          <Download className="mr-1.5 h-3.5 w-3.5" /> Download list to send
        </Button>
      </div>
      {GROUPS.map((g) => {
        const qs = questions.filter((q) => q.group === g.group);
        if (!qs.length) return null;
        return (
          <div key={g.group} className="overflow-hidden rounded-xl border border-slate-200 bg-white text-xs">
            <p className="bg-slate-50 px-3 py-2 font-semibold text-slate-600">{g.title} ({qs.filter((q) => !q.answered).length} open)</p>
            {qs.map((q) => {
              const key = `answer:${q.key}`;
              const draft = drafts[q.key] ?? q.answer;
              return (
                <div key={q.key} className="space-y-1.5 border-t border-slate-100 px-3 py-2.5">
                  <p className="text-slate-800">{q.text}</p>
                  <div className="flex items-center gap-2">
                    <input
                      value={draft}
                      onChange={(e) => setDrafts((d) => ({ ...d, [q.key]: e.target.value }))}
                      onKeyDown={(e) => e.key === "Enter" && draft.trim() && onChoose(key, { text: draft.trim() })}
                      placeholder="The client's answer"
                      className="h-7 flex-1 rounded-md border border-slate-200 px-2 text-[11px] focus:outline-none focus:ring-2 focus:ring-teal-200"
                    />
                    {saving === key ? (
                      <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
                    ) : q.answered && draft === q.answer ? (
                      <span className="flex items-center gap-1 text-[11px] text-emerald-700"><Check className="h-3.5 w-3.5" /> Answered</span>
                    ) : (
                      <Button size="sm" variant="outline" className="h-7 px-2 text-[11px]" disabled={!draft.trim()} onClick={() => onChoose(key, { text: draft.trim() })}>
                        Save
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}
      <p className="text-[11px] text-slate-500">
        An answer is a note for the file. To change where a line goes after the client answers, pick its type on the Bank or Bills list.
      </p>
    </div>
  );
}
