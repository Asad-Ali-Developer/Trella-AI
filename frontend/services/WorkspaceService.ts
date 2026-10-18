import type { Workspace } from "@/lib/types";
import http from "@/services/http";

class WorkspaceService {
  async list(): Promise<Workspace[]> {
    const { data } = await http.get<Workspace[]>("/workspaces");
    return data;
  }

  async get(workspaceId: string): Promise<Workspace> {
    const { data } = await http.get<Workspace>(`/workspaces/${workspaceId}`);
    return data;
  }

  async create(name: string): Promise<Workspace> {
    const { data } = await http.post<Workspace>("/workspaces", { name });
    return data;
  }
}

export const workspaceService = new WorkspaceService();
