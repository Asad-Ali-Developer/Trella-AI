import type {
  GithubConnectionStatus,
  GithubProviderAccount,
  GithubRepository,
} from "@/lib/types";
import http from "@/services/http";

class GithubService {
  private workspaceConfig(workspaceId?: string) {
    return workspaceId ? { headers: { "X-Workspace-Id": workspaceId } } : undefined;
  }

  async authorizationUrl(workspaceId: string): Promise<string> {
    const { data } = await http.get<{ authorization_url: string }>(
      "/connections/github/authorize",
      this.workspaceConfig(workspaceId),
    );
    return data.authorization_url;
  }

  async completeAuthorization(
    code: string,
    state: string,
    workspaceId: string,
  ): Promise<GithubConnectionStatus> {
    const { data } = await http.post<GithubConnectionStatus>("/connections/github/callback", {
      code,
      state,
      workspace_id: workspaceId,
    });
    return data;
  }

  async status(workspaceId?: string): Promise<GithubConnectionStatus> {
    const { data } = await http.get<GithubConnectionStatus>(
      "/connections/github",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async accounts(workspaceId?: string): Promise<GithubProviderAccount[]> {
    const { data } = await http.get<GithubProviderAccount[]>(
      "/connections/github/accounts",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async linkAccount(accountId: string, workspaceId?: string): Promise<GithubConnectionStatus> {
    const { data } = await http.post<GithubConnectionStatus>(
      "/connections/github/accounts/link",
      { account_id: accountId },
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async disconnect(workspaceId?: string): Promise<GithubConnectionStatus> {
    const { data } = await http.delete<GithubConnectionStatus>(
      "/connections/github",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async repositories(workspaceId?: string): Promise<GithubRepository[]> {
    const { data } = await http.get<GithubRepository[]>(
      "/connections/github/repositories",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async refreshRepositories(workspaceId?: string): Promise<GithubRepository[]> {
    const { data } = await http.post<GithubRepository[]>(
      "/connections/github/repositories/refresh",
      {},
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async clients(workspaceId?: string): Promise<Array<{ id: string; name: string }>> {
    const { data } = await http.get<Array<{ id: string; name: string }>>(
      "/connections/github/clients",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async saveRepositories(
    repositories: Array<Pick<GithubRepository, "id" | "included" | "client_id">>,
    workspaceId?: string,
  ): Promise<number> {
    const { data } = await http.put<{ saved: number }>(
      "/connections/github/repositories",
      { repositories },
      this.workspaceConfig(workspaceId),
    );
    return data.saved;
  }

  async sync(workspaceId?: string): Promise<number> {
    const { data } = await http.post<{ scheduled: number }>(
      "/connections/github/sync",
      {},
      this.workspaceConfig(workspaceId),
    );
    return data.scheduled;
  }
}

export const githubService = new GithubService();
