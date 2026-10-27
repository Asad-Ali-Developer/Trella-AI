const WORKSPACE_KEY = "ci.workspace_id";

export const workspaceStore = {
  clear(): void {
    localStorage.removeItem(WORKSPACE_KEY);
  },
  getWorkspaceId(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(WORKSPACE_KEY);
  },
  setWorkspaceId(id: string): void {
    localStorage.setItem(WORKSPACE_KEY, id);
  },
};
