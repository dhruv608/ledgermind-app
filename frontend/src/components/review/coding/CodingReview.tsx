"use client";

import { useState } from "react";
import type { Mispostings, Reanalysis } from "@/lib/api";
import { MispostingPanel } from "@/components/review/coding/MispostingPanel";
import { ReanalysisPanel } from "@/components/review/coding/ReanalysisPanel";
import { Tabs } from "@/components/ui/tabs";

type View = "reanalysis" | "mispostings";

/** Costs in the wrong account, in one place: the re-analysis (each merchant's lines against what the firm and the
 *  client usually code them to) and the misposting review (a supplier split across accounts). */
export function CodingReview({
  engagementId, start = "reanalysis", reanalysis, mispostings, onReanalysis, onMispostings, onChanged,
}: {
  engagementId: string;
  start?: View;
  reanalysis: Reanalysis["summary"] | null;
  mispostings: Mispostings["summary"] | null;
  onReanalysis: (r: Reanalysis) => void;
  onMispostings: (m: Mispostings) => void;
  onChanged: () => void;
}) {
  const [view, setView] = useState<View>(start);
  const views: { id: View; label: string; count?: number }[] = [
    { id: "reanalysis", label: "Re-analysis", count: reanalysis ? reanalysis.moves + reanalysis.questions : undefined },
    { id: "mispostings", label: "Mispostings", count: mispostings ? mispostings.recommended : undefined },
  ];
  return (
    <div className="space-y-4">
      <Tabs label="Coding review" items={views} value={view} onChange={setView} />
      {view === "reanalysis"
        ? <ReanalysisPanel engagementId={engagementId} onLoaded={onReanalysis} onChanged={onChanged} />
        : <MispostingPanel engagementId={engagementId} onLoaded={onMispostings} onChanged={onChanged} />}
    </div>
  );
}
