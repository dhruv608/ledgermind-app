// LM's background checks on the client page: their progress, starting them, watching for the re-check a change
// starts, and the refresh (with a 'what changed' message) when they finish.
import { useState, useEffect, useRef } from "react";
import type { MutableRefObject } from "react";
import { useJobChanged } from "@/lib/jobEvents";
import { toast } from "@/lib/notify";
import { api } from "@/lib/api";
import type { CheckRun } from "@/lib/api";
import { plural } from "@/lib/formatters";
import type { AuditFinding } from "@/types/engagement";
import type { TabId } from "./tabs";

export function useChecksWatch(
  id: string,
  refreshAll: () => Promise<AuditFinding[] | undefined>,
  goToTab: (next: TabId, force?: boolean) => void,
  findingsNow: MutableRefObject<AuditFinding[]>,
) {
  // The checks running in the background (they start by themselves once the setup is complete, after a save of the
  // setup or a new upload, or from Run review): asked every 2 seconds while they run; when they finish, the points
  // and journals are read again
  const [checks, setChecks] = useState<CheckRun | null>(null);
  const checksWas = useRef<string | null>(null);
  // A big change (new files, the client details) covers the whole page while LM checks again
  const [bigUpdate, setBigUpdate] = useState(false);
  const loadChecks = async () => {
    try {
      const run = await api.getChecks(id);
      const was = checksWas.current;
      checksWas.current = run.status;
      setChecks(run);
      if (run.status !== "RUNNING") setBigUpdate(false);
      if (was === "RUNNING" && run.status === "DONE") {
        // LM answers back: what its check changed, not only that it finished. A point is the same point across
        // checks when its check and title are (its id changes)
        const key = (f: AuditFinding) => `${f.procedure_ref}|${f.finding_title}`;
        const open = (list: AuditFinding[]) => new Set(list.filter((f) => f.status === "OPEN").map(key));
        const before = open(findingsNow.current);
        const hadBefore = findingsNow.current.length > 0;
        refreshAll().then((after) => {
          const now = open(after || []);
          const cleared = [...before].filter((k) => !now.has(k)).length;
          const added = [...now].filter((k) => !before.has(k)).length;
          const parts = hadBefore
            ? [cleared && `${plural(cleared, "point")} cleared`, added && `${added} new`].filter(Boolean).join(" · ") || "Nothing changed in the points"
            : `${plural(run.summary?.points ?? now.size, "point")} to look at, ${plural(run.summary?.journals ?? 0, "journal")} proposed`;
          toast.success("LM updated the client", {
            description: parts + ".",
            action: { label: "See the points", onClick: () => goToTab("review") },
          });
        });
      } else if (was === "RUNNING" && run.status === "FAILED") {
        toast.error("The checks stopped", { description: run.error || "Run them again from Review." });
      }
    } catch {
      // the progress line just stays as it was
    }
  };
  const startChecks = async () => {
    try {
      const run = await api.startChecks(id);
      if (run.waiting_for_setup?.length) {
        toast.warning("Finish the client setup first", { description: run.waiting_for_setup.join(" · ") });
        return;
      }
      checksWas.current = checksWas.current === "RUNNING" ? "RUNNING" : run.status;
      setChecks(run);
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  useEffect(() => {
    checksWas.current = null;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- loadChecks sets state only after its await (the server's answer)
    loadChecks();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once per client id: loadChecks is recreated each render
  }, [id]);
  useEffect(() => {
    if (checks?.status !== "RUNNING") return;
    const timer = setInterval(loadChecks, 2000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the poll restarts only when the run's status or the client changes, not each render
  }, [checks?.status, id]);

  // After a change, LM's re-check (which the change starts on the server by itself) is watched: the server starts it
  // a moment after the save, so the page looks for a few seconds; when it ends, loadChecks refreshes everything again.
  const watchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const watchChecks = (tries = 6) => {
    if (watchTimer.current) clearTimeout(watchTimer.current);
    const look = async (left: number) => {
      await loadChecks();
      if (checksWas.current !== "RUNNING" && left > 0) watchTimer.current = setTimeout(() => look(left - 1), 1000);
      else if (checksWas.current !== "RUNNING") setBigUpdate(false);
    };
    watchTimer.current = setTimeout(() => look(tries), 600);
  };
  useEffect(() => () => { if (watchTimer.current) clearTimeout(watchTimer.current); }, []);
  useJobChanged(id, (change) => {
    if (change.big) setBigUpdate(true);
    refreshAll();
    watchChecks();
  });

  return { checks, startChecks, bigUpdate };
}
