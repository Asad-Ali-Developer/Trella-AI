import type { SlackChannel, SlackConnectionStatus } from "@/lib/types";
import http from "@/services/http";

class SlackService {
  async getAuthorizationUrl(workspaceId: string): Promise<string> {
    const { data } = await http.get<{ authorization_url: string }>(
      "/connections/slack/authorize",
      { headers: { "X-Workspace-Id": workspaceId } },
    );
    return data.authorization_url;
  }

  async completeAuthorization(
    code: string,
    state: string,
    workspaceId: string,
  ): Promise<SlackConnectionStatus> {
    const { data } = await http.post<SlackConnectionStatus>(
      "/connections/slack/callback",
      { code, state, workspace_id: workspaceId },
      { headers: { "X-Workspace-Id": workspaceId } },
    );
    return data;
  }

  async getStatus(workspaceId: string): Promise<SlackConnectionStatus> {
    const { data } = await http.get<SlackConnectionStatus>("/connections/slack", {
      headers: { "X-Workspace-Id": workspaceId },
    });
    return data;
  }

  async getChannels(workspaceId: string): Promise<SlackChannel[]> {
    const { data } = await http.get<SlackChannel[]>("/connections/slack/channels", {
      headers: { "X-Workspace-Id": workspaceId },
    });
    return data;
  }

  async disconnect(workspaceId: string): Promise<SlackConnectionStatus> {
    const { data } = await http.delete<SlackConnectionStatus>("/connections/slack", {
      headers: { "X-Workspace-Id": workspaceId },
    });
    return data;
  }
}

export const slackService = new SlackService();
