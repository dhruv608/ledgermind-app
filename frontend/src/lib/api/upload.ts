// Uploading a client's files: what each file is, its columns, and the upload itself.
import type { EngagementData } from "@/types/engagement";
import { API_BASE, FilesNeedRolesError, fetch, formatClientName } from "./client";

export type FileRole =
  | "TB" | "GL" | "AR" | "AP" | "UNKNOWN" | "SKIP"
  | "TB_PRIOR" // last year's TB (optional, for the last year vs this year comparison)
  // A client with no accounting software: bank statement, Dext lists, and last year's TB and unpaid lists
  | "BANK" | "SALES" | "BILLS" | "OPENING_TB" | "OPENING_SALES" | "OPENING_BILLS";

export interface IdentifiedFile {
  filename: string;
  role: FileRole;
  how: string;
  /** A TB or ledger the Xero / QuickBooks readers do not know (Sage, or any Excel): its columns to confirm */
  layout?: ColumnLayout;
}

export interface ColumnLayout {
  role: "TB" | "GL";
  known: boolean;               // a layout the firm confirmed before: read the same way
  header_row: number;
  headers: string[];
  preview: (string | number | null)[][];
  mapping: Record<string, number>;   // field -> column
  fields: { id: string; label: string; required: boolean }[];
  missing: string[];
  software: string;             // SAGE / OTHER
}

/** The columns confirmed at upload, per file: sent with the upload and remembered for the next file like it */
export interface ConfirmResult {
  confirmed: number;
  names: string[];        // the accounts really confirmed
  inSuspense: string[];   // still on 9999: need a real code first
  toCheck: string[];      // flagged "Check": confirmed one at a time
}

export type ConfirmedLayouts =Record<string, { role: string; header_row: number; mapping: Record<string, number>; software: string }>;

export const uploadApi = {
  /** What each chosen file is, read from its content (nothing is saved). */
  /** For one combined workbook, files are its tabs ('<tab>.xlsx'). */
  async identifyFiles(files: File[]): Promise<{ combined: boolean; raw?: boolean; workbook?: string; files: IdentifiedFile[]; year_end?: string | null; year_end_suggested?: string | null; year_end_why?: string }> {
    const formData = new FormData();
    for (const f of files) formData.append("files", f);
    const res = await fetch(`${API_BASE}/upload/identify`, { method: "POST", body: formData });
    if (!res.ok) throw new Error("Could not read the files");
    return res.json();
  },

  /** yearEnd (yyyy-mm-dd): a bank-only client's year end, typed on the upload screen when no file says it */
  /** How far an upload has got (the stage it is at, 1-based; 0 before it starts), for the upload screen. */
  async uploadProgress(progressId: string): Promise<{ stage: number; stages: string[] }> {
    const res = await fetch(`${API_BASE}/upload/progress/${progressId}`);
    if (!res.ok) return { stage: 0, stages: [] };
    return res.json();
  },

  async uploadFiles(files: File[], signal?: AbortSignal, roles?: Record<string, FileRole>, layouts?: ConfirmedLayouts, yearEnd?: string, progressId?: string): Promise<EngagementData> {
    const formData = new FormData();
    for (const f of files) {
      formData.append("files", f);
    }
    if (roles && Object.keys(roles).length) formData.append("roles", JSON.stringify(roles));
    if (layouts && Object.keys(layouts).length) formData.append("layouts", JSON.stringify(layouts));
    if (yearEnd) formData.append("year_end", yearEnd);
    if (progressId) formData.append("progress_id", progressId);
    const res = await fetch(`${API_BASE}/upload`, {
      method: "POST",
      body: formData,
      signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (res.status === 422 && err.detail?.files) throw new FilesNeedRolesError(err.detail.message, err.detail.files);
      throw new Error(typeof err.detail === "string" ? err.detail : "Upload failed. Verify backend server is running.");
    }
    const data: EngagementData = await res.json();
    return {
      ...data,
      client_name: formatClientName(data.client_name),
    };
  },
};
