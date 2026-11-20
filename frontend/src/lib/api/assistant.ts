// The assistant's chat panel: the accountant's chats, one chat's messages, and a message answered as a stream.
import { API_BASE, chatPageQuery, fetch } from "./client";

/** Tokens and US$ of the assistant over a time (answers, voice questions and files read). */
export interface MeterSpend {
  tokens_in: number; tokens_out: number; usd: number; answers: number;
  answers_usd: number; voice_seconds: number; voice_usd: number; files_usd: number;
}

/** The cost meter: today, this month, ever and one chat, at AWS's London prices; the test page's daily limit. */
export interface AssistantMeter {
  today: MeterSpend; month: MeterSpend; total: MeterSpend;
  chat?: { tokens_in: number; tokens_out: number; usd: number };
  limit_usd: number | null;
  model: string;
  prices: Record<string, { in: number; out: number }>;
  voice_per_minute: number;
}

export interface ChatSummary {
  id: string;
  title: string;
  engagement_id: string | null;
  client_name: string | null;
  updated_at: string | null;
  cost_usd: number;
  tokens_in?: number;
  tokens_out?: number;
}

export interface ChatFileRef {
  id: string;
  name: string;
  kind: "xlsx" | "pdf";
  size: number;
}

export interface ChatChart {
  type: "bar" | "line";
  title: string;
  labels: string[];
  series: { name: string; values: (number | null)[] }[];
  unit: string;
}

/** A law source the answer used (HMRC manual section, notice, Act section), with its link. */
export interface ChatSource {
  ref: string;
  title: string;
  document: string;
  url: string;
  updated?: string | null;
}

/** Work the assistant prepared (a journal, clearing a point, a query, a note): done only when the accountant confirms. */
export interface ChatAction {
  id: string;
  kind: "propose_journal" | "journal_decision" | "clear_point" | "raise_query" | "add_note";
  title: string;
  text: string;
  why?: string;
  point?: string;
  total?: number;
  lines?: { account_code: number; account_name: string; debit: number; credit: number; narrative?: string }[];
  status: "WAITING" | "DONE" | "CANCELLED" | "FAILED";
  result?: string;
  decided_by?: string;
  decided_at?: string;
}

/** A file attached to a question: read when it was added (text: what was read, in the preview) */
export interface ChatUpload {
  id: string; name: string; mime: string; size: number; pages: number; status: "READ" | "UNREADABLE";
  note: string | null; chars: number; has_thumb: boolean; image: boolean; text?: string;
}

export interface ChatSuggestions {
  attachments?: ChatUpload[];
  followups?: string[];
  options?: { question: string; choices: string[] };
  files?: ChatFileRef[];
  charts?: ChatChart[];
  sources?: ChatSource[];
  actions?: ChatAction[];
}

export interface ChatMessage {
  id: number | string;
  role: "user" | "assistant";
  content: string;
  steps: string[];
  suggestions: ChatSuggestions;
  model?: string | null;
  tokens?: number;
  cost_usd?: number;
  created_at?: string | null;
}

export type ChatEvent =
  | { type: "status"; text: string }
  | { type: "delta"; text: string }
  | { type: "reset" }
  | { type: "file"; file: ChatFileRef }
  | { type: "chart"; chart: ChatChart }
  | { type: "sources"; sources: ChatSource[] }
  | { type: "action"; action: ChatAction }
  | { type: "done"; message: ChatMessage }
  | { type: "error"; text: string };

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "The assistant could not be reached");
  }
  return res.json();
}

export const assistantApi = {
  async listChats(engagementId: string | null, q = "", allClients = false): Promise<ChatSummary[]> {
    const p = new URLSearchParams();
    if (engagementId) p.set("engagement_id", engagementId);
    if (q) p.set("q", q);
    if (allClients) p.set("all_clients", "true");
    return json(await fetch(`${API_BASE}/assistant/sessions?${p}`));
  },

  async newChat(engagementId: string | null): Promise<ChatSummary> {
    return json(await fetch(`${API_BASE}/assistant/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ engagement_id: engagementId }),
    }));
  },

  async getChat(id: string): Promise<ChatSummary & { messages: ChatMessage[] }> {
    return json(await fetch(`${API_BASE}/assistant/sessions/${id}`));
  },

  async deleteChat(id: string): Promise<void> {
    await json(await fetch(`${API_BASE}/assistant/sessions/${id}`, { method: "DELETE" }));
  },

  /** The accountant's Confirm or Cancel on prepared work; the message comes back with the card's outcome. */
  async decideAction(messageId: number | string, actionId: string, decision: "CONFIRM" | "CANCEL"): Promise<ChatMessage> {
    return json(await fetch(`${API_BASE}/assistant/messages/${messageId}/actions/${actionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    }));
  },

  fileUrl(id: string): string {
    return `${API_BASE}/assistant/files/${id}${chatPageQuery()}`;
  },

  async meter(chatId: string | null): Promise<AssistantMeter> {
    return json(await fetch(`${API_BASE}/assistant/meter${chatId ? `?session_id=${encodeURIComponent(chatId)}` : ""}`));
  },

  async usage(): Promise<{ month_usd: number; month_answers: number; total_usd: number }> {
    return json(await fetch(`${API_BASE}/assistant/usage`));
  },

  /** Sends a message; onEvent gets each step, piece of text and the saved answer as they arrive. */
  /** context: the page open (tab, area), so "this" in a question means what is on screen */
  /** Attach a file: it is read now (a PDF's text, or a picture transcribed), so this can take a while for a scan */
  async upload(file: File, signal?: AbortSignal): Promise<ChatUpload> {
    const form = new FormData();
    form.append("file", file);
    return json(await fetch(`${API_BASE}/assistant/uploads`, { method: "POST", body: form, signal }));
  },

  async getUpload(id: string): Promise<ChatUpload> {
    return json(await fetch(`${API_BASE}/assistant/uploads/${id}`));
  },

  async removeUpload(id: string): Promise<void> {
    await fetch(`${API_BASE}/assistant/uploads/${id}`, { method: "DELETE" });
  },

  /** What was said: 16 kHz 16-bit mono PCM from the mic, written out by AWS Transcribe */
  async voice(pcm: ArrayBuffer): Promise<string> {
    const res = await fetch(`${API_BASE}/assistant/voice`, {
      method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: pcm,
    });
    return (await json<{ text: string }>(res)).text;
  },

  uploadThumbUrl(id: string): string {
    return `${API_BASE}/assistant/uploads/${id}/thumb${chatPageQuery()}`;
  },

  uploadFileUrl(id: string): string {
    return `${API_BASE}/assistant/uploads/${id}/file${chatPageQuery()}`;
  },

  async send(id: string, text: string, onEvent: (e: ChatEvent) => void, signal?: AbortSignal,
             context?: { tab?: string | null; area?: string | null }, files: string[] = []): Promise<void> {
    const res = await fetch(`${API_BASE}/assistant/sessions/${id}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, context: context || {}, files }),
      signal,
    });
    if (!res.ok || !res.body) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || "The assistant could not be reached");
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const chunk = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (line) {
          try {
            onEvent(JSON.parse(line.slice(6)));
          } catch {
            // a broken line: skip it
          }
        }
      }
    }
  },
};
