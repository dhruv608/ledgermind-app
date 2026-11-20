// Notes on an area page: threaded comments, who and when, on the account or on one point.
import { API_BASE, fetch } from "./client";

export interface AreaNote {
  id: number;
  area: string;
  parent_id: number | null;   // the thread's first note, for a reply
  text: string;
  author: string;
  initials: string;
  user_id: number | null;
  created_at: string | null;
  finding_id: number | null;  // the point it is about, as it is now (null: about the account, or the point is gone)
  point_title: string;
}

export interface AreaNoteIn {
  area: string;
  text: string;
  parent_id?: number;
  finding_id?: number;
}

async function detail(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => ({}));
  return typeof body.detail === "string" ? body.detail : fallback;
}

export const notesApi = {
  async getNotes(engagementId: string): Promise<AreaNote[]> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/notes`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the notes"));
    return res.json();
  },

  /** Add a note (or a reply); every note of the job comes back. */
  async addNote(engagementId: string, note: AreaNoteIn): Promise<AreaNote[]> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(note),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save the note"));
    return res.json();
  },

  async deleteNote(engagementId: string, noteId: number): Promise<AreaNote[]> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/notes/${noteId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not remove the note"));
    return res.json();
  },
};
