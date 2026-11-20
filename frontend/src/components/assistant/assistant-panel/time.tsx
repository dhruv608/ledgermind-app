// How the assistant shows times and days: day groups, "5 min ago" labels and the live time element.

import { useEffect, useState } from "react";

export function dayGroup(iso: string | null): string {
  if (!iso) return "Older";
  const d = new Date(iso);
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  const t = d.getTime();
  if (t >= start) return "Today";
  if (t >= start - 86400000) return "Yesterday";
  if (t >= start - 7 * 86400000) return "Previous 7 days";
  if (t >= start - 30 * 86400000) return "Previous 30 days";
  return "Older";
}

// A message's time as a chat shows it: "just now", "5 min ago", "2 h ago", then "Yesterday 14:05" or "3 Nov, 14:05";
// the full date and time on hover
export const clock = (d: Date) => d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
export function whenText(iso: string): string {
  const d = new Date(iso);
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const group = dayGroup(iso);
  if (group === "Today") return mins < 6 * 60 ? `${Math.floor(mins / 60)} h ago` : clock(d);
  if (group === "Yesterday") return `Yesterday ${clock(d)}`;
  return `${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}, ${clock(d)}`;
}
export const fullWhen = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });

/** The time of a message, kept fresh while the panel is open */
export function When({ iso, extra }: { iso?: string | null; extra?: string }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 30000);
    return () => clearInterval(t);
  }, []);
  if (!iso) return null;
  return (
    <time dateTime={iso} title={[fullWhen(iso), extra].filter(Boolean).join(". ")} className="text-[11px] text-slate-400">
      {whenText(iso)}
    </time>
  );
}

/** The day a message was sent, as a divider between days */
export const dayLabel = (iso: string) => {
  const g = dayGroup(iso);
  return g === "Today" || g === "Yesterday" ? g
    : new Date(iso).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
};

export const fmtYE = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB");
};
