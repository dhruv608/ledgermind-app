"use client";

// The return's pages use the company workspace's own parts (components/review/area/AreaPanel.tsx): a white header card
// with the title, its state, one grey line, the actions, and figure tiles; tables in the same frame and head.
import { Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { gap, text } from "@/lib/ui";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/dialog";

export const TABLE_WRAP = "overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs";
export const THEAD = "border-b border-slate-200 bg-slate-50 text-[10.5px] uppercase tracking-wide text-slate-500";
export const TROW = "hover:bg-slate-50";
export const NUM = "font-mono tabular-nums";

export type Tone = "done" | "look" | "empty" | "info";
export const PILL: Record<Tone, string> = {
  done: "bg-emerald-50 text-emerald-700",
  look: "bg-amber-100 text-amber-800",
  empty: "bg-slate-100 text-slate-600",
  info: "bg-sky-50 text-sky-700",
};

export function Figure({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <span className="block text-[11px] text-slate-500">{label}</span>
      <span className={cn(NUM, "text-sm font-semibold text-slate-900", tone)}>{value}</span>
    </div>
  );
}

interface HeadProps {
  title: string;
  state?: { text: string; tone: Tone };
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  figures?: { label: string; value: string; tone?: string }[];
}

export function SaHead({ title, state, meta, actions, figures }: HeadProps) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
      {/* The page's buttons stay top right, beside the title, however long the description */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h2 className={cn("flex flex-wrap items-center gap-2", text.page)}>
            {title}
            {state && <span className={cn("rounded-full px-2 py-px text-[10.5px] font-bold", PILL[state.tone])}>{state.text}</span>}
          </h2>
          {meta && <p className={cn("mt-0.5 max-w-3xl", text.meta)}>{meta}</p>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap justify-end gap-2">{actions}</div>}
      </div>
      {figures && figures.length > 0 && (
        <div className={cn("mt-3 grid grid-cols-2 gap-2", figures.length >= 4 ? "sm:grid-cols-4" : "sm:grid-cols-3")}>
          {figures.map((f) => <Figure key={f.label} {...f} />)}
        </div>
      )}
    </div>
  );
}

// A section's add button: small, at the right of the section's title row
export function AddButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <Button size="sm" variant="outline" className="h-7 shrink-0 text-xs" onClick={onClick}>
      <Plus className="mr-1 h-3.5 w-3.5" /> {children}
    </Button>
  );
}

// The fields to add a line, in a pop-up that stays open for the next line (Done closes it)
export function AddPopup({ open, onClose, title, description, onAdd, addLabel = "Add", children }: {
  open: boolean; onClose: () => void; title: string; description?: string; onAdd: () => void; addLabel?: string;
  children: React.ReactNode;
}) {
  return (
    <Modal isOpen={open} onClose={onClose} title={title} description={description} className="max-w-lg">
      <div className="space-y-3 pt-4">
        <div className="grid gap-3 sm:grid-cols-2">{children}</div>
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
          <Button variant="ghost" size="sm" onClick={onClose}>Done</Button>
          <Button variant="primary" size="sm" onClick={onAdd}>{addLabel}</Button>
        </div>
      </div>
    </Modal>
  );
}

// A labelled field in an AddPopup (wide: the whole row)
export function PopupField({ label, wide, children }: { label: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <label className={cn("block space-y-1", wide && "sm:col-span-2")}>
      <span className="text-xs font-semibold text-slate-700">{label}</span>
      {children}
    </label>
  );
}

export { gap, text };
