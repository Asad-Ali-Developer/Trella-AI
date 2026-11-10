import http from "@/services/http";

export interface QueueItem {
  id: string;
  name: string;
  source_type: "trello" | "github" | "run";
  status: "not_started" | "queued" | "running" | "completed" | "failed";
  last_synced_at: string | null;
  sync_error: string | null;
  items_count: number;
  chunks_count: number;
}

export interface RecentRunItem {
  id: string;
  skill_name: string;
  status: string;
  trigger: string;
  created_at: string;
  completed_at: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | null;
  error: string | null;
}

export interface QueueStatusResponse {
  is_worker_online: boolean;
  redis_connected: boolean;
  celery_queue_length: number;
  syncing_count: number;
  worker_name: string | null;
  items: QueueItem[];
  recent_runs: RecentRunItem[];
  total_chunks: number;
  last_checked_at: string;
}

class QueueService {
  private workspaceConfig(workspaceId?: string) {
    return workspaceId ? { headers: { "X-Workspace-Id": workspaceId } } : undefined;
  }

  async getStatus(workspaceId?: string): Promise<QueueStatusResponse> {
    const { data } = await http.get<QueueStatusResponse>(
      "/queue/status",
      this.workspaceConfig(workspaceId),
    );
    return data;
  }

  async syncAll(workspaceId?: string): Promise<{ scheduled: number }> {
    const { data } = await http.post<{ scheduled: number }>(
      "/queue/sync-all",
      {},
      this.workspaceConfig(workspaceId),
    );
    return data;
  }
}

export const queueService = new QueueService();
export default queueService;

