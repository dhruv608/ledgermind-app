import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { text } from "@/lib/ui";
import { cn } from "@/lib/utils";

interface SectionHeaderProps {
  icon?: LucideIcon;
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
  /** The panel that fills a job's screen: the top bar already names it, so only its help line and buttons show */
  page?: boolean;
}

/** The title row of a card or tab: icon, title, one line of help, and the buttons for that section. */
export function SectionHeader({ icon: Icon, title, description, actions, className, page }: SectionHeaderProps) {
  if (page) {
    return (
      <div className={cn("flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between", className)}>
        {description ? <p className={cn("min-w-0 leading-relaxed", text.meta)}>{description}</p> : <span aria-label={title} />}
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    );
  }
  return (
    <div className={cn("flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between", className)}>
      <div className="flex min-w-0 items-start gap-2.5">
        {Icon && (
          <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-teal-50 text-teal-700">
            <Icon className="h-4 w-4" />
          </div>
        )}
        <div className="min-w-0">
          <h3 className={text.section}>{title}</h3>
          {description && <p className={cn("mt-0.5 leading-relaxed", text.meta)}>{description}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
