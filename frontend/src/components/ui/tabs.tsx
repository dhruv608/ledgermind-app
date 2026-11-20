"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export interface TabItem<T extends string> {
  id: T;
  label: string;
  count?: number;
  /** Something urgent inside (e.g. questions that must be answered): shown as a small red count */
  alert?: number;
}

/** The app's tab bar: the tabs on the left, underlined in teal when chosen, and the controls that filter what the tabs
 *  show (search, a filter) on the right of the same bar, so they read as one. When the bar is narrow the controls go
 *  above the tabs, so the tabs always sit on the line. */
export function Tabs<T extends string>({ items, value, onChange, actions, label, className }: {
  items: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  /** Controls on the right of the bar (filters, search) */
  actions?: React.ReactNode;
  /** What the tabs are, for screen readers */
  label: string;
  className?: string;
}) {
  return (
    <div className={cn("@container", className)}>
      <div className="flex flex-col-reverse gap-y-2 border-b border-slate-200 @[52rem]:flex-row @[52rem]:items-end @[52rem]:justify-between @[52rem]:gap-x-4">
        <div role="tablist" aria-label={label} className="-mb-px flex flex-wrap gap-1 @[52rem]:shrink-0 @[52rem]:flex-nowrap">
          {items.map((t) => {
            const on = t.id === value;
            return (
              <button key={t.id} type="button" role="tab" aria-selected={on} onClick={() => onChange(t.id)}
                      className={cn("border-b-2 px-3 py-2.5 text-[13px] transition-colors",
                                    on ? "border-teal-600 font-semibold text-teal-800"
                                       : "border-transparent font-medium text-slate-500 hover:border-teal-200 hover:text-slate-900")}>
                {t.label}
                {Boolean(t.alert) && (
                  <span className="ml-1.5 rounded-full bg-rose-100 px-1.5 py-px text-[10.5px] font-semibold tabular-nums text-rose-700"
                        title={`${t.alert} must be answered`}>
                    {t.alert}!
                  </span>
                )}
                {Boolean(t.count) && (
                  <span className={cn("ml-1.5 rounded-full px-1.5 py-px text-[10.5px] font-semibold tabular-nums",
                                      on ? "bg-teal-100 text-teal-800" : "bg-slate-100 text-slate-600")}>
                    {t.count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        {actions && <div className="flex min-w-0 flex-wrap items-center gap-2 @[52rem]:flex-1 @[52rem]:justify-end @[52rem]:pb-1.5">{actions}</div>}
      </div>
    </div>
  );
}
