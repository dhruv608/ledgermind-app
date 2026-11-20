// The clients list, a client's details and status, its ledger lines, deleting clients.
import type { EngagementStatus, EngagementData, ClientListItem } from "@/types/engagement";
import { API_BASE, fetch, formatClientName } from "./client";

export const clientsApi = {
  async listClients(): Promise<ClientListItem[]> {
    try {
      const res = await fetch(`${API_BASE}/engagements`);
      if (!res.ok) return [];
      const data: ClientListItem[] = await res.json();
      return data.map((c) => ({
        ...c,
        client_name: formatClientName(c.client_name),
      }));
    } catch (err) {
      console.warn("Backend server not reachable at " + API_BASE, err);
      return [];
    }
  },

  async getEngagementById(engagementId: string): Promise<EngagementData> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}`);
    if (!res.ok) throw new Error("Failed to load client details");
    const data: EngagementData = await res.json();
    return {
      ...data,
      client_name: formatClientName(data.client_name),
    };
  },

  async deleteClient(engagementId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error("Failed to delete client engagement");
  },

  async bulkDeleteClients(engagementIds: string[]): Promise<void> {
    const res = await fetch(`${API_BASE}/engagements/bulk-delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ engagement_ids: engagementIds }),
    });
    if (!res.ok) throw new Error("Failed to delete selected client engagements");
  },

  async getEngagementStatus(engagementId: string): Promise<EngagementStatus> {
    const res = await fetch(`${API_BASE}/engagements/${engagementId}/status`);
    if (!res.ok) throw new Error("Failed to load the client's status");
    return res.json();
  },

  async getTransactions(
    engagementId: string,
    accountName?: string,
    limit: number = 300
  ): Promise<any[]> {
    const query = new URLSearchParams();
    if (accountName) query.append("account_name", accountName);
    query.append("limit", limit.toString());

    const res = await fetch(`${API_BASE}/engagements/${engagementId}/transactions?${query.toString()}`);
    if (!res.ok) return [];
    return res.json();
  },
};
