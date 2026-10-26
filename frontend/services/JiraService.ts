import type {
  JiraConnectionStatus,
  JiraProject,
  JiraProviderAccount,
} from "@/lib/types";
import http from "@/services/http";

class JiraService {
  private workspaceConfig(workspaceId?: string) {
    return workspaceId ? { headers: { "X-Workspace-Id": workspaceId } } : undefined;
  }

  async authorizationUrl(workspaceId: string): Promise<string> {
    const { data } = await http.get<{ authorization_url: string }>(
      "/connections/jira/authorize",
      this.workspaceConfig(workspaceId),
    );
    return data.authorization_url;
  }

  async completeAuthorization(
    code: string,
    state: string,
    workspaceId?: string,
  ): Promise<JiraConnectionStatus> {
    const { data } = await http.post<JiraConnectionStatus>("/connections/jira/callback", {
      code,
      state,
      workspace_id: workspaceId || undefined,
    });
    return data;
  }


  async status(workspaceId?: string): Promise<JiraConnectionStatus> {
    const { data } = await http.get<JiraConnectionStatus>(
      "/connections/jira",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async accounts(workspaceId?: string): Promise<JiraProviderAccount[]> {
    const { data } = await http.get<JiraProviderAccount[]>(
      "/connections/jira/accounts",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async linkAccount(accountId: string, workspaceId?: string): Promise<JiraConnectionStatus> {
    const { data } = await http.post<JiraConnectionStatus>(
      "/connections/jira/accounts/link",
      { account_id: accountId },
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async disconnect(workspaceId?: string): Promise<JiraConnectionStatus> {
    const { data } = await http.delete<JiraConnectionStatus>(
      "/connections/jira",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async clients(workspaceId?: string): Promise<Array<{ id: string; name: string }>> {
    const { data } = await http.get<Array<{ id: string; name: string }>>(
      "/connections/jira/clients",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async projects(workspaceId?: string): Promise<JiraProject[]> {
    const { data } = await http.get<JiraProject[]>(
      "/connections/jira/projects",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }


  async saveProjects(
    selections: { project_id: string; included: boolean; client_id?: string | null }[],
    workspaceId?: string,
  ): Promise<JiraProject[]> {
    const { data } = await http.put<JiraProject[]>(
      "/connections/jira/projects",
      { selections },
      this.workspaceConfig(workspaceId),
    );
    return data;
  }
}

export const jiraService = new JiraService();
