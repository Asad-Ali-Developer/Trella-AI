import type {
  ContextSummaryResult,
  SimilarContextCard,
  WorkspaceContextSnapshot,
} from "@/lib/types";
import http from "@/services/http";

class ContextService {
  async generate(workspaceId: string, maxTokens = 4000): Promise<WorkspaceContextSnapshot> {
    const { data } = await http.get<WorkspaceContextSnapshot>("/context", {
      headers: { "X-Workspace-Id": workspaceId },
      params: { max_tokens: maxTokens },
    });
    return data;
  }

  async classifyMember(
    workspaceId: string,
    memberId: string,
    roleTag: "unknown" | "client" | "internal",
  ): Promise<WorkspaceContextSnapshot["members"][number]> {
    const { data } = await http.patch<WorkspaceContextSnapshot["members"][number]>(
      `/context/members/${memberId}`,
      { role_tag: roleTag },
      { headers: { "X-Workspace-Id": workspaceId } },
    );
    return data;
  }

  async summarizeCards(workspaceId: string): Promise<{
    processed: number;
    generated: number;
    cached: number;
    summaries: ContextSummaryResult[];
  }> {
    const { data } = await http.post<{
      processed: number;
      generated: number;
      cached: number;
      summaries: ContextSummaryResult[];
    }>(
      "/context/summaries",
      { max_cards: 50 },
      { headers: { "X-Workspace-Id": workspaceId } },
    );
    return data;
  }

  async indexCards(workspaceId: string): Promise<{
    indexed: number;
    already_indexed: number;
    remaining: number;
  }> {
    const { data } = await http.post<{
      indexed: number;
      already_indexed: number;
      remaining: number;
    }>(
      "/context/index",
      { max_cards: 100 },
      { headers: { "X-Workspace-Id": workspaceId } },
    );
    return data;
  }

  async search(
    workspaceId: string,
    query: string,
  ): Promise<SimilarContextCard[]> {
    const { data } = await http.post<{ results: SimilarContextCard[] }>(
      "/context/search",
      { query, limit: 10 },
      { headers: { "X-Workspace-Id": workspaceId } },
    );
    return data.results;
  }
}

export const contextService = new ContextService();
