import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type ChipTone = "neutral" | "success" | "warning" | "danger" | "info";

const TONES: Record<ChipTone, string> = {
  neutral: "bg-slate-50 text-slate-600 border-slate-200",
  success: "bg-emerald-50 text-emerald-700 border-emerald-200",
  warning: "bg-amber-50 text-amber-800 border-amber-200",
  danger: "bg-rose-50 text-rose-700 border-rose-200",
  info: "bg-sky-50 text-sky-700 border-sky-200",
};

interface StatusChipProps {
  tone?: ChipTone;
  icon?: LucideIcon;
  children: React.ReactNode;
  title?: string;
  className?: string;
}

/** A small rounded label for a status: "37 mappings to review", "Draft", "VAT registered". */
export function StatusChip({ tone = "neutral", icon: Icon, children, title, className }: StatusChipProps) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold whitespace-nowrap",
        TONES[tone],
        className
      )}
    >
      {Icon && <Icon className="h-3.5 w-3.5 shrink-0" />}
      {children}
    </span>
  );
}
