// One ledger line in GL scrutiny: its flags and the decision on it (OK, moved by a journal, or asked of the client).
import { useMemo, useState } from "react";
import { Check, Flag, MessageCircleQuestion, Undo2 } from "lucide-react";
import { ScrutinyLine } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CustomSelect } from "@/components/ui/custom-select";
import { formatCurrency } from "@/lib/formatters";
import { ChartCode, PICKER_FILTERS } from "@/components/mapping/scrutiny/shared";

export function LineRow({
  l,
  hasVat,
  chart,
  canMove,
  fromCode,
  fromName,
  busy,
  moving,
  setMoving,
  onOk,
  onMove,
  onUndo,
  onAsk,
}: {
  l: ScrutinyLine;
  hasVat: boolean;
  chart: ChartCode[];
  canMove: boolean;
  fromCode: number | null;
  fromName: string;
  busy: boolean;
  moving: boolean;
  setMoving: (on: boolean) => void;
  onOk: (ok: boolean) => void;
  onMove: (code: number) => void;
  onUndo: () => void;
  onAsk: (question: string) => void;
}) {
  const [target, setTarget] = useState("");
  const [asking, setAsking] = useState(false);
  const [question, setQuestion] = useState("");
  const d = l.decision;
  const code = parseInt(target, 10);
  const known = chart.find((c) => c.std_code === code);
  // The chart as picker options: the asset flag's suggested code first, then the firm chart, then the extra codes
  const suggested = l.flags.find((f) => f.kind === "asset")?.suggested_code ?? null;
  const options = useMemo(() => {
    if (!moving) return [];
    const label = (c: ChartCode) => `${String(c.std_code).padStart(4, "0")} ${c.std_name}`;
    const tags = (c: ChartCode) => [c.financial_class === "Profit and Loss" ? "pl" : "bs"];
    const sug = chart.find((c) => c.std_code === suggested);
    return [
      ...(sug ? [{ value: String(sug.std_code), label: label(sug), description: sug.category, group: "Suggested", tags: tags(sug) }] : []),
      ...chart
        .filter((c) => c.std_code !== suggested && c.std_code !== fromCode)
        .map((c) => ({
          value: String(c.std_code),
          label: label(c),
          description: c.category,
          group: c.is_extended ? "Full chart (more codes)" : "Firm chart",
          tags: tags(c),
        })),
    ];
  }, [moving, chart, suggested, fromCode]);
  const btn = "whitespace-nowrap rounded-md border px-2 py-0.5 text-[11px] font-medium disabled:opacity-50";
  return (
    <tr className={cn("align-top transition-colors hover:bg-teal-50/40", d?.status === "OK" && "bg-emerald-50/30", d?.status === "MOVED" && "bg-teal-50/40")}>
      <td className="whitespace-nowrap py-2 pl-4 font-mono text-[11px] text-slate-600">
        {l.date ? l.date.split("-").reverse().join("/") : "—"}
      </td>
      <td className="truncate px-3 py-2 text-[11px] text-slate-600" title={l.source}>{l.source || "—"}</td>
      <td className="px-3 py-2">
        <p className="truncate text-slate-900" title={l.description}>{l.description || l.reference || "—"}</p>
        <p className="truncate text-[11px] text-slate-400">
          {[l.reference && l.reference !== l.description ? l.reference : "", l.account].filter(Boolean).join(" · ")}
        </p>
        {l.flags.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {l.flags.map((f) => (
              <span
                key={f.kind}
                title={f.text}
                className="inline-flex cursor-help items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-800"
              >
                <Flag className="h-2.5 w-2.5" />
                {f.label}
              </span>
            ))}
          </div>
        )}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-slate-900">{l.net > 0 ? formatCurrency(l.net) : ""}</td>
      <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-slate-900">{l.net < 0 ? formatCurrency(-l.net) : ""}</td>
      {hasVat && <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-slate-500">{l.vat ? formatCurrency(l.vat) : ""}</td>}
      <td className="py-2 pl-3 pr-4">
        {d?.status === "MOVED" ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-teal-800">
              Moved to <span className="font-mono font-semibold">{d.to_code}</span> {d.to_name} · {d.journal_ref}
              {d.journal_status === "APPROVED" ? " (approved)" : ""}
            </span>
            {d.journal_status !== "APPROVED" && (
              <button type="button" disabled={busy} onClick={onUndo} className={cn(btn, "border-slate-200 text-slate-600 hover:border-teal-300 hover:bg-teal-50 hover:text-teal-800")}>
                <Undo2 className="mr-1 inline h-3 w-3" />Undo
              </button>
            )}
          </div>
        ) : moving ? (
          <div className="space-y-1.5">
            <CustomSelect
              size="sm"
              fullWidth
              searchable
              searchPlaceholder="Type a code or name"
              filters={PICKER_FILTERS}
              value={target}
              placeholder="Pick the right code…"
              onChange={(v) => setTarget(String(v ?? ""))}
              options={options}
              menuClassName="left-auto right-0 w-[22rem] max-w-[calc(100vw-2rem)]"
              align="right"
            />
            {known && code !== fromCode && (
              <div className="rounded-md border border-teal-200 bg-teal-50/60 px-2 py-1 text-[10px] leading-relaxed text-teal-900">
                <p className="font-semibold">Journal to propose:</p>
                <p>
                  Dr <span className="font-mono">{l.net >= 0 ? code : fromCode}</span> {l.net >= 0 ? known.std_name : fromName}{" "}
                  {formatCurrency(Math.abs(l.net))}
                </p>
                <p>
                  Cr <span className="font-mono">{l.net >= 0 ? fromCode : code}</span> {l.net >= 0 ? fromName : known.std_name}{" "}
                  {formatCurrency(Math.abs(l.net))}
                </p>
                <p className="text-teal-700">Goes to the Journals tab; the books change once it is approved.</p>
              </div>
            )}
            {known && code === fromCode && <p className="text-[10px] text-amber-700">The line is already on this code.</p>}
            <div className="flex gap-1">
              <button
                type="button"
                disabled={busy || !known || code === fromCode}
                onClick={() => onMove(code)}
                className={cn(btn, "border-teal-600 bg-teal-600 text-white hover:bg-teal-700")}
              >
                Move
              </button>
              <button type="button" onClick={() => setMoving(false)} className={cn(btn, "border-slate-200 text-slate-600 hover:border-teal-300 hover:bg-teal-50 hover:text-teal-800")}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-1.5">
            {d?.status === "MOVE_REJECTED" && (
              <span className="text-[11px] text-rose-700">Move {d.journal_ref} rejected ·</span>
            )}
            {d?.status === "OK" ? (
              <button type="button" disabled={busy} onClick={() => onOk(false)} className={cn(btn, "border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100")} title="Take the OK off">
                <Check className="mr-1 inline h-3 w-3" />OK
              </button>
            ) : (
              <button type="button" disabled={busy} onClick={() => onOk(true)} className={cn(btn, "border-slate-200 text-slate-700 hover:border-teal-300 hover:bg-teal-50 hover:text-teal-800")}>
                OK
              </button>
            )}
            {canMove && (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  if (suggested && !target) setTarget(String(suggested));
                  setMoving(true);
                }}
                className={cn(btn, "border-slate-200 text-slate-700 hover:border-teal-300 hover:bg-teal-50 hover:text-teal-800")}
              >
                Move to…
              </button>
            )}
            {!d?.question && !asking && (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setQuestion(`What was this ${l.net >= 0 ? "payment" : "receipt"} of ${formatCurrency(Math.abs(l.net))} on ${l.date ? l.date.split("-").reverse().join("/") : "this date"} for?`);
                  setAsking(true);
                }}
                className={cn(btn, "border-slate-200 text-slate-700 hover:border-teal-300 hover:bg-teal-50 hover:text-teal-800")}
              >
                Ask client
              </button>
            )}
          </div>
        )}
        {asking ? (
          <div className="mt-1.5 space-y-1">
            <textarea
              autoFocus
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={2}
              placeholder="The question for the client"
              className="w-full rounded border border-slate-300 px-2 py-1 text-[11px]"
            />
            <div className="flex gap-1">
              <button
                type="button"
                disabled={busy || !question.trim()}
                onClick={() => {
                  onAsk(question.trim());
                  setAsking(false);
                }}
                className={cn(btn, "border-violet-600 bg-violet-600 text-white hover:bg-violet-700")}
              >
                Save question
              </button>
              <button type="button" onClick={() => setAsking(false)} className={cn(btn, "border-slate-200 text-slate-600 hover:border-teal-300 hover:bg-teal-50 hover:text-teal-800")}>
                Cancel
              </button>
            </div>
          </div>
        ) : d?.question ? (
          <div className="mt-1.5 rounded-md border border-violet-200 bg-violet-50/60 px-2 py-1 text-[11px] text-violet-900">
            <p>
              <MessageCircleQuestion className="mr-1 inline h-3 w-3" />
              {d.question}
            </p>
            <div className="mt-0.5 flex gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setQuestion(d.question || "");
                  setAsking(true);
                }}
                className="font-medium text-violet-700 hover:underline"
              >
                Edit
              </button>
              <button type="button" disabled={busy} onClick={() => onAsk("")} className="font-medium text-violet-700 hover:underline">
                Remove
              </button>
            </div>
          </div>
        ) : null}
      </td>
    </tr>
  );
}
