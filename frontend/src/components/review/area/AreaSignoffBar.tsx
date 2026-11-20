"use client";

import { useState } from "react";
import { AlertTriangle, Check } from "lucide-react";
import { toast } from "@/lib/notify";
import type { AuditFinding } from "@/types/engagement";
import type { AreaSignoff, SignoffRole } from "@/lib/api";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { serverDate } from "@/lib/formatters";

const STEPS: { role: SignoffRole; label: string; done: string }[] = [
  { role: "PREPARER", label: "Prepare", done: "Prepared" },
  { role: "REVIEWER", label: "Review", done: "Reviewed" },
  { role: "PARTNER", label: "Approve", done: "Approved" },
];

/** The area's points as a short fingerprint (their references and titles): a sign-off keeps the one it was given, so
 *  the page can say when the points changed after it. */
export function areaFingerprint(findings: AuditFinding[]): string {
  const text = findings.map((f) => `${f.procedure_ref}|${f.finding_title}|${f.status}`).sort().join("\n");
  let h1 = 0x811c9dc5, h2 = 0x01000193;
  for (let i = 0; i < text.length; i++) {
    h1 = Math.imul(h1 ^ text.charCodeAt(i), 16777619) >>> 0;
    h2 = Math.imul(h2 + text.charCodeAt(i), 2246822519) >>> 0;
  }
  return h1.toString(16).padStart(8, "0") + h2.toString(16).padStart(8, "0");
}

/** An area's sign-off: Prepared, then Reviewed, then Approved, each with initials and date. A step can be signed
 *  only after the one before it, and taken off only after the ones after it. */
export function AreaSignoffBar({
  engagementId, area, findings, signoffs = [], onChange,
}: {
  engagementId: string;
  area: string;
  findings: AuditFinding[];
  signoffs?: AreaSignoff[];
  onChange: (next: Record<string, AreaSignoff[]>) => void;
}) {
  const [busy, setBusy] = useState(false);
  const now = areaFingerprint(findings);
  const by = (role: SignoffRole) => signoffs.find((s) => s.role === role);
  const changed = signoffs.some((s) => s.fingerprint && s.fingerprint !== now);
  const next = STEPS.find((s) => !by(s.role));

  const act = async (role: SignoffRole, clear: boolean) => {
    setBusy(true);
    try {
      onChange(await api.signOffArea(engagementId, area, role, clear, now));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the sign-off");
    } finally {
      setBusy(false);
    }
  };

  // One small control in the area's header: three parts (prepared, reviewed, approved), the next one to sign
  // dashed, the signed ones filled with initials; the last signed one can be taken off
  return (
    <div className="inline-flex items-center gap-1.5">
      {changed && (
        <span title="The points changed after this area was signed off: look again, then sign again" className="text-amber-600">
          <AlertTriangle className="h-4 w-4" />
        </span>
      )}
      <div className="inline-flex h-8 items-stretch overflow-hidden rounded-md border border-slate-200 bg-white text-[11px]" role="group" aria-label="Area sign-off">
        {STEPS.map((s, i) => {
          const done = by(s.role);
          const isNext = next?.role === s.role;
          const when = done?.signed_at ? serverDate(done.signed_at).toLocaleDateString("en-GB") : "";
          const last = STEPS.slice(i + 1).every((t) => !by(t.role));
          return (
            <button key={s.role} type="button" disabled={busy || (done ? !last : !isNext)}
                    onClick={() => act(s.role, Boolean(done))}
                    title={done ? (last ? `${s.done} by ${done.initials} on ${when}: click to take it off` : `${s.done} by ${done.initials} on ${when}`)
                      : isNext ? `Sign the area off as ${s.done.toLowerCase()}` : `After the ${STEPS[i - 1]?.done.toLowerCase()} sign-off`}
                    className={cn("inline-flex items-center gap-1 px-2.5 font-semibold transition",
                                  i > 0 && "border-l border-slate-200",
                                  done ? "bg-teal-700 text-white enabled:hover:bg-teal-800"
                                    : isNext ? "text-teal-800 hover:bg-teal-50" : "text-slate-300")}>
              {done ? <><Check className="h-3 w-3" />{done.initials || s.done[0]}</> : s.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
