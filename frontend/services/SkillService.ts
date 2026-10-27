import type { Skill } from "@/lib/types";
import http from "@/services/http";

class SkillService {
  async list(workspaceId: string): Promise<Skill[]> {
    const { data } = await http.get<Skill[]>("/skills", {
      headers: { "X-Workspace-Id": workspaceId },
    });
    return data;
  }

  async get(workspaceId: string, skillId: string): Promise<Skill> {
    const { data } = await http.get<Skill>(`/skills/${skillId}`, {
      headers: { "X-Workspace-Id": workspaceId },
    });
    return data;
  }

  async create(
    workspaceId: string,
    payload: {
      name: string;
      slug: string;
      description?: string;
      prompt_template: string;
      scope_json?: Record<string, unknown>;
      output_schema_json?: Record<string, unknown>;
      model_config_json?: Record<string, unknown>;
    },
  ): Promise<Skill> {
    const { data } = await http.post<Skill>("/skills", payload, {
      headers: { "X-Workspace-Id": workspaceId },
    });
    return data;
  }
}

export const skillService = new SkillService();
