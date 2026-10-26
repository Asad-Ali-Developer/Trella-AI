import type { ClientProfile, ClientSummary, TimelineEvent } from "@/lib/types";
import http from "@/services/http";

class ClientService {
  async list(workspaceId: string): Promise<ClientSummary[]> {
    const { data } = await http.get<ClientSummary[]>("/clients", {
      headers: { "X-Workspace-Id": workspaceId },
    });
    return data;
  }

  async get(workspaceId: string, clientId: string): Promise<ClientProfile> {
    const { data } = await http.get<ClientProfile>(`/clients/${clientId}`, {
      headers: { "X-Workspace-Id": workspaceId },
    });
    return data;
  }

  async create(workspaceId: string, name: string): Promise<ClientSummary> {
    const { data } = await http.post<ClientSummary>(
      "/clients",
      { name },
      { headers: { "X-Workspace-Id": workspaceId } },
    );
    return data;
  }

  async getTimeline(workspaceId: string, clientId: string): Promise<TimelineEvent[]> {
    const { data } = await http.get<TimelineEvent[]>(`/clients/${clientId}/timeline`, {
      headers: { "X-Workspace-Id": workspaceId },
    });
    return data;
  }
}

export const clientService = new ClientService();
