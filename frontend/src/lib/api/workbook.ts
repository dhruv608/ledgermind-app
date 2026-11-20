// Building the workbook and its versions.
import type { LatestWorkpaper } from "@/types/engagement";
import { API_BASE, BuildBlockedError, fetch } from "./client";

export const workbookApi = {
  async generateWorkpapers(engagementId: string): Promise<{ download_url: string; filename: string }> {
    const res = await fetch(`${API_BASE}/workpapers/generate/${engagementId}`, { method: "POST" });
    if (res.status === 409) {
      const err = await res.json().catch(() => null);
      throw new BuildBlockedError(err?.detail?.message || "Not ready to build the workbook", err?.detail?.blockers || []);
    }
    if (!res.ok) throw new Error("Failed to generate workpapers");
    return res.json();
  },

  async getWorkpaperHistory(engagementId: string): Promise<LatestWorkpaper[]> {
    const res = await fetch(`${API_BASE}/workpapers/history/${engagementId}`);
    if (!res.ok) return [];
    return res.json();
  },
};
