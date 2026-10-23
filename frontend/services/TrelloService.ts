import type { TrelloBoard, TrelloConnectionStatus } from "@/lib/types";
import http from "@/services/http";

class TrelloService {
  async authorizationUrl(): Promise<string> {
    const { data } = await http.get<{ authorization_url: string }>("/connections/trello/authorize");
    return data.authorization_url;
  }

  async completeAuthorization(
    code: string,
    state: string,
    workspaceId: string,
  ): Promise<TrelloConnectionStatus> {
    const { data } = await http.post<TrelloConnectionStatus>("/connections/trello/callback", {
      code,
      state,
      workspace_id: workspaceId,
    });
    return data;
  }

  async status(): Promise<TrelloConnectionStatus> {
    const { data } = await http.get<TrelloConnectionStatus>("/connections/trello");
    return data;
  }

  async listBoards(): Promise<TrelloBoard[]> {
    const { data } = await http.get<TrelloBoard[]>("/connections/trello/boards");
    return data;
  }

  async saveBoards(boards: TrelloBoard[]): Promise<void> {
    await http.put("/connections/trello/boards", {
      boards: boards.map(({ id, excluded }) => ({ id, excluded })),
    });
  }
}

export const trelloService = new TrelloService();