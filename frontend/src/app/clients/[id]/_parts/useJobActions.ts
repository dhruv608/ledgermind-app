// The job's actions on the client page: clearing review points, building the workbook and deleting the client.
import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { jobChanged } from "@/lib/jobEvents";
import { toast } from "@/lib/notify";
import { api, BuildBlockedError } from "@/lib/api";
import { plural } from "@/lib/formatters";
import type { AuditFinding, EngagementData, LatestWorkpaper } from "@/types/engagement";

export function useJobActions(
  id: string,
  engagement: EngagementData | null,
  setAuditFindings: Dispatch<SetStateAction<AuditFinding[]>>,
  setWorkpaper: Dispatch<SetStateAction<LatestWorkpaper | null>>,
  refreshStatus: () => Promise<void>,
  refreshAll: () => Promise<AuditFinding[] | undefined>,
  setIsViewerOpen: Dispatch<SetStateAction<boolean>>,
  router: { push: (href: string) => void },
) {
  const [isGenerating, setIsGenerating] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const handleClearFinding = async (findingId: number, note?: string) => {
    try {
      await api.clearAuditFinding(findingId, note);
      setAuditFindings((prev) =>
        prev.map((f) =>
          f.id === findingId ? { ...f, status: "CLEARED", cleared_note: note || null, cleared_at: new Date().toISOString() } : f
        )
      );
      toast.success("Point cleared");
      jobChanged(id);
    } catch (e) {
      toast.error(e, { action: { label: "Reload", onClick: () => { refreshAll(); } } });
    }
  };

  // Several points cleared with one note (the review's low points): one message at the end
  const handleClearMany = async (findingIds: number[], note: string) => {
    const done: number[] = [];
    for (const id of findingIds) {
      try {
        await api.clearAuditFinding(id, note);
        done.push(id);
      } catch {}
    }
    const when = new Date().toISOString();
    setAuditFindings((prev) => prev.map((f) => (done.includes(f.id) ? { ...f, status: "CLEARED", cleared_note: note, cleared_at: when } : f)));
    if (done.length) jobChanged(id);
    if (done.length === findingIds.length) toast.success(`${plural(done.length, "point")} cleared`);
    else toast.error(`${done.length} of ${findingIds.length} points cleared; try again for the rest`);
  };

  const handleGenerateWorkpaper = async () => {
    if (!engagement) return;
    setIsGenerating(true);
    try {
      const res = await api.generateWorkpapers(engagement.engagement_id);
      setWorkpaper({
        id: 0,
        filename: res.filename,
        generated_at: "just now",
        is_draft: res.filename.toUpperCase().endsWith("_DRAFT.XLSX"),
        download_url: res.download_url,
      });
      setIsViewerOpen(true);
      refreshStatus();
      toast.success("Workbook ready", { description: res.filename });
    } catch (err) {
      if (err instanceof BuildBlockedError) {
        toast.warning("Not ready to build the workbook", { description: err.blockers.join(" · "), duration: 10000 });
        refreshStatus();
      } else {
        toast.error("Could not build the workbook");
      }
    } finally {
      setIsGenerating(false);
    }
  };

  const handleConfirmDelete = async () => {
    if (!engagement) return;
    setIsDeleting(true);
    try {
      await api.deleteClient(engagement.engagement_id);
      setIsDeleteModalOpen(false);
      toast.success("Client deleted", { description: `"${engagement.client_name}" and its working papers were removed.` });
      router.push("/");
    } catch (err: any) {
      toast.error("Could not delete the client", { description: err.message });
    } finally {
      setIsDeleting(false);
    }
  };

  return {
    isGenerating, isDeleteModalOpen, setIsDeleteModalOpen, isDeleting,
    handleClearFinding, handleClearMany, handleGenerateWorkpaper, handleConfirmDelete,
  };
}
