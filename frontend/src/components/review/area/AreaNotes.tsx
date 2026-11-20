"use client";

import { useEffect, useRef, useState } from "react";
import { CornerDownRight, Loader2, Trash2 } from "lucide-react";
import { toast } from "@/lib/notify";
import type { AuditFinding } from "@/types/engagement";
import type { AreaNote } from "@/lib/api";
import type { Area } from "@/lib/areas";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { CustomSelect } from "@/components/ui/custom-select";
import { serverDate } from "@/lib/formatters";

// Enter sends, Shift+Enter starts a new line (as in the assistant's chat)
const enterSends = (e: React.KeyboardEvent<HTMLTextAreaElement>, send: () => void) => {
  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
    e.preventDefault();
    send();
  }
};
// The box grows with its text
const grow = (e: React.FormEvent<HTMLTextAreaElement>) => {
  const el = e.currentTarget;
  el.style.height = "";
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
};

const when = (iso: string | null) =>
  iso ? serverDate(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";

/** An area page's Notes tab: threaded comments with who and when, on the account or on one of its points,
 *  separate from the points themselves. */
export function AreaNotes({
  engagementId, area, notes, onNotes, findings, noteFor, onNoteForUsed,
}: {
  engagementId: string;
  area: Area;
  notes: AreaNote[] | null;
  onNotes: (next: AreaNote[]) => void;
  /** The area's points, for 'About' */
  findings: AuditFinding[];
  /** A point whose Notes button was pressed: the new note is about it */
  noteFor?: AuditFinding | null;
  onNoteForUsed?: () => void;
}) {
  const [text, setText] = useState("");
  const [about, setAbout] = useState<number | 0>(0);
  const [replyTo, setReplyTo] = useState<number | null>(null);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);

  // A point's Notes button: the new note is about that point (set during render), then the box gets the focus and
  // the request is cleared
  const [aboutFrom, setAboutFrom] = useState<AuditFinding | null | undefined>(undefined);
  if (noteFor !== aboutFrom) {
    setAboutFrom(noteFor);
    if (noteFor) setAbout(noteFor.id);
  }
  useEffect(() => {
    if (!noteFor) return;
    box.current?.focus();
    onNoteForUsed?.();
  }, [noteFor, onNoteForUsed]);

  const add = async (body: string, parentId?: number) => {
    if (!body.trim() || busy) return;
    setBusy(true);
    try {
      onNotes(await api.addNote(engagementId, {
        area: area.key, text: body, parent_id: parentId, finding_id: !parentId && about ? about : undefined,
      }));
      if (parentId) {
        setReply("");
        setReplyTo(null);
      } else {
        setText("");
        if (box.current) box.current.style.height = "";
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the note");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    setBusy(true);
    try {
      onNotes(await api.deleteNote(engagementId, id));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not remove the note");
    } finally {
      setBusy(false);
    }
  };

  const mine = (notes || []).filter((n) => n.area === area.key);
  const threads = mine.filter((n) => !n.parent_id).reverse();      // newest thread first
  const replies = (id: number) => mine.filter((n) => n.parent_id === id);
  const pointName = (n: AreaNote) =>
    n.finding_id ? findings.find((f) => f.id === n.finding_id)?.finding_title || n.point_title : n.point_title ? `${n.point_title} (point no longer raised)` : "";

  const Note = ({ n, lead }: { n: AreaNote; lead?: boolean }) => (
    <div className="group flex gap-2.5">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-teal-600 text-[10px] font-bold text-white" title={n.author}>
        {n.initials || "?"}
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-x-2 text-[11px] text-slate-500">
          <span className="font-semibold text-slate-700">{n.author || "Someone"}</span>
          <span>{when(n.created_at)}</span>
          <button type="button" className="ml-auto text-slate-400 opacity-0 transition hover:text-rose-600 focus:opacity-100 group-hover:opacity-100" disabled={busy}
                  onClick={() => remove(n.id)} aria-label="Remove this note" title={lead ? "Remove this note and its replies" : "Remove this note"}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </p>
        <p className="mt-0.5 whitespace-pre-line text-xs leading-relaxed text-slate-800">{n.text}</p>
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="space-y-2 rounded-xl border border-slate-200 bg-white p-3 text-xs shadow-2xs focus-within:border-teal-300">
        <textarea ref={box} value={text} onChange={(e) => setText(e.target.value)} onInput={grow} rows={2}
                  onKeyDown={(e) => enterSends(e, () => add(text))}
                  placeholder={`A note on ${area.label}: what you checked, what you decided, what the reviewer should know`}
                  className="w-full resize-none border-0 px-1 py-0.5 text-xs focus:outline-none" />
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex min-w-0 items-center gap-1.5 text-[11px] text-slate-500">
            About
            <CustomSelect size="sm" value={about} onChange={(v) => setAbout(Number(v))} buttonClassName="max-w-[22rem]"
                          options={[{ value: 0, label: "The whole account" },
                                    ...findings.map((f) => ({ value: f.id, label: f.finding_title }))]} />
          </label>
          <span className="ml-auto flex items-center gap-2">
            <span className="hidden text-[10.5px] text-slate-400 sm:inline">Enter to add · Shift+Enter new line</span>
            {busy && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
            <Button size="sm" className="h-7 text-xs" disabled={busy || !text.trim()} onClick={() => add(text)}>Add note</Button>
          </span>
        </div>
      </div>

      {notes === null ? (
        <p className="flex items-center gap-2 text-xs text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading the notes…</p>
      ) : threads.length === 0 ? (
        <p className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">No notes on this account yet.</p>
      ) : (
        <ul className="space-y-3">
          {threads.map((n) => (
            <li key={n.id} className="space-y-2.5 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-2xs">
              {pointName(n) && <p className="truncate text-[11px] font-medium text-slate-500" title={pointName(n)}>About the point: {pointName(n)}</p>}
              <Note n={n} lead />
              {replies(n.id).map((r) => (
                <div key={r.id} className="ml-9 border-l-2 border-slate-100 pl-3"><Note n={r} /></div>
              ))}
              {replyTo === n.id ? (
                <div className="ml-9 flex items-start gap-2">
                  <textarea autoFocus value={reply} onChange={(e) => setReply(e.target.value)} onInput={grow} rows={1}
                            onKeyDown={(e) => enterSends(e, () => add(reply, n.id))} placeholder="Your reply (Enter to send)"
                            className="flex-1 resize-none rounded-md border border-slate-200 px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-teal-200" />
                  <Button size="sm" className="h-7 text-xs" disabled={busy || !reply.trim()} onClick={() => add(reply, n.id)}>Reply</Button>
                  <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => { setReplyTo(null); setReply(""); }}>Cancel</Button>
                </div>
              ) : (
                <button type="button" className="ml-9 flex items-center gap-1 text-[11px] font-semibold text-teal-700 hover:text-teal-900"
                        onClick={() => { setReplyTo(n.id); setReply(""); }}>
                  <CornerDownRight className="h-3.5 w-3.5" /> Reply
                  {replies(n.id).length > 0 && (
                    <span className="font-normal text-slate-400">· {replies(n.id).length} {replies(n.id).length === 1 ? "reply" : "replies"}</span>
                  )}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
