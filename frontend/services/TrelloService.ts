import type {
  TrelloBoard,
  TrelloClientMapping,
  TrelloConnectionStatus,
  TrelloMappingType,
  TrelloProviderAccount,
} from "@/lib/types";
import http from "@/services/http";

class TrelloService {
  private workspaceConfig(workspaceId?: string) {
    return workspaceId ? { headers: { "X-Workspace-Id": workspaceId } } : undefined;
  }

  async authorizationUrl(): Promise<string> {
    const { data } = await http.get<{ authorization_url: string }>(
      "/connections/trello/token/authorize",
    );
    return data.authorization_url;
  }

  async completeAuthorization(
    token: string,
    state: string,
    workspaceId: string,
  ): Promise<TrelloConnectionStatus> {
    const { data } = await http.post<TrelloConnectionStatus>("/connections/trello/token/callback", {
      token,
      state,
      workspace_id: workspaceId,
    });
    return data;
  }

  async status(workspaceId?: string): Promise<TrelloConnectionStatus> {
    const { data } = await http.get<TrelloConnectionStatus>(
      "/connections/trello",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async accounts(workspaceId?: string): Promise<TrelloProviderAccount[]> {
    const { data } = await http.get<TrelloProviderAccount[]>(
      "/connections/trello/accounts",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async linkAccount(accountId: string, workspaceId?: string): Promise<TrelloConnectionStatus> {
    const { data } = await http.post<TrelloConnectionStatus>(
      "/connections/trello/accounts/link",
      { account_id: accountId },
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async disconnect(workspaceId?: string): Promise<TrelloConnectionStatus> {
    const { data } = await http.delete<TrelloConnectionStatus>(
      "/connections/trello",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async listBoards(workspaceId?: string): Promise<TrelloBoard[]> {
    const { data } = await http.get<TrelloBoard[]>(
      "/connections/trello/boards",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async saveBoards(boards: TrelloBoard[]): Promise<void> {
    await http.put("/connections/trello/boards", {
      boards: boards.map(({ id, excluded }) => ({ id, excluded })),
    });
  }

  async syncBoards(): Promise<number> {
    const { data } = await http.post<{ scheduled: number }>("/connections/trello/sync");
    return data.scheduled;
  }

  async listClientMappings(workspaceId?: string): Promise<TrelloClientMapping[]> {
    const { data } = await http.get<TrelloClientMapping[]>(
      "/connections/trello/clients",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async saveClientMappings(
    mappings: Array<{
      board_id: string;
      mapping_type: TrelloMappingType;
      external_ref: string;
      client_name: string;
    }>,
  ): Promise<number> {
    const { data } = await http.put<{ saved: number }>("/connections/trello/clients", {
      mappings,
    });
    return data.saved;
  }
}

export const trelloService = new TrelloService();