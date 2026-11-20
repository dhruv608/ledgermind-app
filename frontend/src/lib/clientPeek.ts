// What the app already knows about a client before its page loads (from the clients list, or the last visit), so the
// loading workspace shows the real name and checklist and only the figures still coming shimmer. Per browser tab.

export interface ClientPeek {
  name: string;
  source: string;            // source_system: BANK_DEXT clients have a Books step
  yearEnd?: string;
  areas?: string[];          // the areas the checklist showed last time
}

const KEY = "clients.peek";

function readAll(): Record<string, ClientPeek> {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) || "{}");
  } catch {
    return {};
  }
}

export function peekClient(id: string): ClientPeek | null {
  return readAll()[id] || null;
}

export function rememberClient(id: string, peek: Partial<ClientPeek> & { name: string }) {
  try {
    const all = readAll();
    all[id] = { ...all[id], ...peek, source: peek.source ?? all[id]?.source ?? "" };
    sessionStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    // no storage (a private window): the loading view shimmers the name instead
  }
}

export function rememberClients(list: { engagement_id: string; client_name: string; source_system: string; period_end_date: string }[]) {
  for (const c of list) rememberClient(c.engagement_id, { name: c.client_name, source: c.source_system, yearEnd: c.period_end_date });
}
