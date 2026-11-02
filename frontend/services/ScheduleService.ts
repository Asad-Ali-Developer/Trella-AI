import type {
  DeliveryListResponse,
  RunDetail,
  Schedule,
  ScheduleCreateRequest,
  ScheduleUpdateRequest,
} from "@/lib/types";
import http from "@/services/http";

class ScheduleService {
  async list(workspaceId: string): Promise<Schedule[]> {
    const { data } = await http.get<Schedule[]>("/schedules", {
      headers: { "X-Workspace-Id": workspaceId },
    });
    return data;
  }

  async get(workspaceId: string, scheduleId: string): Promise<Schedule> {
    const { data } = await http.get<Schedule>(`/schedules/${scheduleId}`, {
      headers: { "X-Workspace-Id": workspaceId },
    });
    return data;
  }

  async create(workspaceId: string, payload: ScheduleCreateRequest): Promise<Schedule> {
    const { data } = await http.post<Schedule>("/schedules", payload, {
      headers: { "X-Workspace-Id": workspaceId },
    });
    return data;
  }

  async update(
    workspaceId: string,
    scheduleId: string,
    payload: ScheduleUpdateRequest,
  ): Promise<Schedule> {
    const { data } = await http.patch<Schedule>(`/schedules/${scheduleId}`, payload, {
      headers: { "X-Workspace-Id": workspaceId },
    });
    return data;
  }

  async delete(workspaceId: string, scheduleId: string): Promise<void> {
    await http.delete(`/schedules/${scheduleId}`, {
      headers: { "X-Workspace-Id": workspaceId },
    });
  }

  async runNow(workspaceId: string, scheduleId: string): Promise<RunDetail | null> {
    const { data } = await http.post<RunDetail | null>(
      `/schedules/${scheduleId}/run-now`,
      {},
      { headers: { "X-Workspace-Id": workspaceId } },
    );
    return data;
  }

  async listDeliveries(
    workspaceId: string,
    skip = 0,
    limit = 20,
  ): Promise<DeliveryListResponse> {
    const { data } = await http.get<DeliveryListResponse>("/schedules/deliveries", {
      headers: { "X-Workspace-Id": workspaceId },
      params: { skip, limit },
    });
    return data;
  }

  async unsubscribe(email: string): Promise<{ success: boolean; message: string }> {
    const { data } = await http.post<{ success: boolean; message: string }>(
      "/delivery/unsubscribe",
      { email },
    );
    return data;
  }
}

export const scheduleService = new ScheduleService();
