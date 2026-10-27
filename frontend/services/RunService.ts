import type { Insight, Run, RunDetail } from "@/lib/types";
import http from "@/services/http";

class RunService {
  async list(workspaceId: string, clientId?: string): Promise<Run[]> {
    const { data } = await http.get<Run[]>("/runs", {
      headers: { "X-Workspace-Id": workspaceId },
      params: clientId ? { client_id: clientId } : undefined,
    });
    return data;
  }

  async get(workspaceId: string, runId: string): Promise<RunDetail> {
    const { data } = await http.get<RunDetail>(`/runs/${runId}`, {
      headers: { "X-Workspace-Id": workspaceId },
    });
    return data;
  }

  async create(
    workspaceId: string,
    payload: {
      skill_id: string;
      client_id?: string | null;
      trigger?: "manual" | "scheduled" | "webhook";
      max_tokens?: number;
    },
    executeAsync = true,
  ): Promise<Run> {
    const { data } = await http.post<Run>("/runs", payload, {
      headers: { "X-Workspace-Id": workspaceId },
      params: { execute_async: executeAsync },
    });
    return data;
  }

  async execute(workspaceId: string, runId: string, executeAsync = true): Promise<Run> {
    const { data } = await http.post<Run>(
      `/runs/${runId}/execute`,
      {},
      {
        headers: { "X-Workspace-Id": workspaceId },
        params: { execute_async: executeAsync },
      },
    );
    return data;
  }

  async submitFeedback(
    workspaceId: string,
    insightId: string,
    feedback: "thumbs_up" | "thumbs_down",
    notes?: string,
  ): Promise<Insight> {
    const { data } = await http.post<Insight>(
      `/runs/insights/${insightId}/feedback`,
      { feedback, feedback_notes: notes },
      { headers: { "X-Workspace-Id": workspaceId } },
    );
    return data;
  }
}

export const runService = new RunService();
