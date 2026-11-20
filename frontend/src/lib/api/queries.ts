// The Queries tab: one list of everything the app asks about the job, for the client, the accountant or the preparer.
import { API_BASE, fetch } from "./client";

export type QueryAudience = "CLIENT" | "ACCOUNTANT" | "INTERNAL";
export type QueryStatus = "OPEN" | "ANSWERED" | "CLEARED";

/** One line of a grouped query (a bank line or bill), answered on its own. */
export interface QueryItem {
  key: string;
  text: string;
  answer: string;
  answered: boolean;
}

export interface JobQuery {
  key: string;
  source: "data" | "books" | "review" | "rules" | "gl" | "raised";   // rules: query rules no other check raises; gl: a line asked about on GL scrutiny; raised: by hand on an area page
  audience: QueryAudience;
  title: string;
  detail: string;
  amount: number;
  blocking: boolean;          // stops the job until it is answered
  go_to: "data" | "books" | "review" | "accounts" | "";
  items: QueryItem[];         // a bank query: its lines (one for a single question)
  status: QueryStatus;
  answer: string;
  finding_id?: number;
  severity?: string;
  ref?: string;
  area?: string;              // raised: the area page it was raised on
  raised_id?: number;
}

export interface JobQueries {
  queries: JobQuery[];
  counts: Record<QueryAudience, { open: number; blocking: number; total: number }>;
  open: number;
  blocking: number;
}

/** A query raised by hand on an area page, on the account or on one of its points. */
export interface RaisedQueryIn {
  title: string;
  detail?: string;
  audience: QueryAudience;
  area: string;
  amount?: number;
  finding_id?: number;
}

export interface QueryUpdate {
  key: string;
  status?: QueryStatus;
  answer?: string;
  audience?: QueryAudience;
  item_answers?: Record<string, string>;
}

async function detail(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => ({}));
  return typeof body.detail === "string" ? body.detail : fallback;
}

export const queriesApi = {
  async getQueries(engagementId: string): Promise<JobQueries> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/queries`);
    if (!res.ok) throw new Error(await detail(res, "Could not load the queries"));
    return res.json();
  },

  /** Save what was done to one query; the whole list comes back. */
  async saveQuery(engagementId: string, update: QueryUpdate): Promise<JobQueries> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/queries`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not save the query"));
    return res.json();
  },

  /** Raise a query by hand; the whole list comes back. */
  async raiseQuery(engagementId: string, query: RaisedQueryIn): Promise<JobQueries> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/queries/raised`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(query),
    });
    if (!res.ok) throw new Error(await detail(res, "Could not raise the query"));
    return res.json();
  },

  async removeRaisedQuery(engagementId: string, raisedId: number): Promise<JobQueries> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/queries/raised/${raisedId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await detail(res, "Could not remove the query"));
    return res.json();
  },
};
