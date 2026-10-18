"use client";

import { LayoutDashboard, LogOut } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { WorkspaceSwitcher } from "@/components/organisms/WorkspaceSwitcher";
import type { User, Workspace } from "@/lib/types";

interface SidebarProps {
  user: User | null;
  workspaces: Workspace[];
  selectedId: string | null;
  onSelectWorkspace: (workspace: Workspace) => void;
  onWorkspaceCreated: (workspace: Workspace) => void;
  onLogout: () => void;
}

export function Sidebar({
  user,
  workspaces,
  selectedId,
  onSelectWorkspace,
  onWorkspaceCreated,
  onLogout,
}: SidebarProps) {
  return (
    <aside className="flex h-full w-64 flex-col border-r border-border bg-white">
      <div className="flex items-center gap-2 border-b border-border px-4 py-4">
        <div className="h-6 w-6 rounded bg-zinc-900" />
        <span className="text-sm font-semibold tracking-tight">Client Insights</span>
      </div>
      <div className="space-y-4 p-3">
        <WorkspaceSwitcher
          workspaces={workspaces}
          selectedId={selectedId}
          onSelect={onSelectWorkspace}
          onCreated={onWorkspaceCreated}
        />
        <nav>
          <Link
            href="/dashboard"
            className="flex items-center gap-2 rounded-md bg-muted px-2.5 py-2 text-sm font-medium text-foreground"
          >
            <LayoutDashboard className="h-4 w-4" />
            Dashboard
          </Link>
        </nav>
      </div>
      <div className="mt-auto space-y-2 border-t border-border p-3">
        <div className="px-1">
          <p className="truncate text-sm font-medium">{user?.name ?? "…"}</p>
          <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
        </div>
        <Badge>Phase 1 shell</Badge>
        <Button variant="ghost" className="w-full justify-start gap-2" onClick={onLogout}>
          <LogOut className="h-4 w-4" />
          Sign out
        </Button>
      </div>
    </aside>
  );
}
