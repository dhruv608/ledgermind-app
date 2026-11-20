// The base for every call: the server's address, fetch with the sign-in cookie, errors and URL helpers.
import type { IdentifiedFile } from "./upload";

/** The review refused because the client setup still has blocking gaps. */
export class SetupGapsError extends Error {
  constructor(message: string, public gaps: string[]) {
    super(message);
    this.name = "SetupGapsError";
  }
}

export class FilesNeedRolesError extends Error {
  constructor(message: string, public files: IdentifiedFile[]) {
    super(message);
    this.name = "FilesNeedRolesError";
  }
}

/** Building the workbook refused: the setup, accounts or review are not done yet. */
export class BuildBlockedError extends Error {
  constructor(message: string, public blockers: string[]) {
    super(message);
    this.name = "BuildBlockedError";
  }
}

// Backend URL resolution with support for dedicated frontend .env.local. Online the app and the server share one
// address: NEXT_PUBLIC_API_URL is empty and NEXT_PUBLIC_API_BASE_URL is "/api" (set when the Docker image is built)
export const BACKEND_HOST = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || `${BACKEND_HOST}/api`;

/** The test chat page (/chat): opened with a code, not a sign-in. Its calls say so (the server then uses the code's
 * cookie, never the sign-in), and "enter the code" (401) shows the code screen again instead of the sign-in page. */
export const CHAT_PAGE_HEADER = "X-LedgerMind-Chat";
export const CHAT_LOCKED_EVENT = "lm-chat-locked";

export function onChatPage(): boolean {
  return typeof window !== "undefined" && /^\/chat(\/|$)/.test(window.location.pathname);
}

/** For a picture or download link on the chat page (a link cannot send a header). */
export function chatPageQuery(): string {
  return onChatPage() ? "?chat=1" : "";
}

/** A save that worked (any call that is not a read) tells the open client page, which refreshes every count from it
 * (one way in for every save, so no screen is left showing old figures). Calls that only read, chat or start LM's
 * own work are not saves. */
export const SAVED_EVENT = "lm:saved";
const NOT_A_SAVE = /\/(assistant|auth|chat-access|checks|workpapers\/generate|upload\/identify|mapping\/options|bank-statement\/read|books\/[^/]+\/ai-suggest)(\/|\?|$)/;

function savedSignal(input: RequestInfo | URL, method?: string) {
  const m = (method || "GET").toUpperCase();
  if (m === "GET" || m === "HEAD" || typeof window === "undefined") return;
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  if (NOT_A_SAVE.test(url)) return;
  window.dispatchEvent(new CustomEvent(SAVED_EVENT, { detail: { url, method: m } }));
}

/** The server's named errors (backend/app/core/errors.py: code, message, what to do next, an error id) */
export type ServerError = { code: string; message: string; next?: string; go_to?: string; error_id?: string };

/** A named error read as every screen already reads errors: detail is one sentence (the message and what to do
 * next); the parts stay on `error` for screens that show them apart */
async function plainError(res: Response): Promise<Response> {
  if (!(res.headers.get("content-type") || "").includes("application/json")) return res;
  try {
    const body = await res.clone().json();
    const d = body?.detail;
    if (!d || typeof d !== "object" || typeof d.code !== "string" || typeof d.message !== "string") return res;
    const text = [d.message, d.next].filter(Boolean).join(" ");
    // The item changed under the screen (LM checked again): the open page reads everything again by itself
    if (d.code === "OutOfDate" && typeof window !== "undefined") window.dispatchEvent(new CustomEvent(SAVED_EVENT, { detail: { url: res.url, method: "STALE" } }));
    return new Response(JSON.stringify({ ...body, detail: text, error: d as ServerError }),
                        { status: res.status, statusText: res.statusText, headers: res.headers });
  } catch {
    return res;
  }
}

/** Every call to the server sends the sign-in cookie; "please sign in" (401) goes back to the sign-in page. */
export const fetch: typeof globalThis.fetch = async (input, init) => {
  const chat = onChatPage();
  let opts: RequestInit = { credentials: "include", ...init };
  if (chat) {
    const headers = new Headers(init?.headers);
    headers.set(CHAT_PAGE_HEADER, "1");
    opts = { ...opts, headers };
  }
  let res = await globalThis.fetch(input, opts);
  if (res.ok) savedSignal(input, opts.method);
  else res = await plainError(res);
  if (res.status === 401 && chat) {
    window.dispatchEvent(new Event(CHAT_LOCKED_EVENT));
    return res;
  }
  if (res.status === 401 && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    try {
      window.localStorage.removeItem("ff_login");
    } catch {
      // nothing saved
    }
    // A full page load on purpose: the sign-in state is reset, outside the React router
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
  }
  return res;
};


export function getApiBaseUrl(): string {
  return API_BASE;
}

export function getDownloadUrl(workpaperId: number | string): string {
  return `${API_BASE}/workpapers/download/${workpaperId}`;
}

export function resolveBackendUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  if (url.startsWith("/")) return `${BACKEND_HOST}${url}`;
  return `${BACKEND_HOST}/${url}`;
}

export function formatClientName(name: string): string {
  if (!name) return "Unknown Client";
  return name.replace(/^(client|company|organisation|organization|name)\s*(name)?\s*:\s*/i, "").trim();
}
