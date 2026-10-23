"use client";

import { Cable, LayoutDashboard, LogOut } from "lucide-react";
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
    <aside className="flex w-full flex-col border-b border-border bg-white md:h-full md:w-64 md:border-b-0 md:border-r">
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
        <nav className="flex flex-wrap gap-1">
          <Link
            href="/dashboard"
            className="flex items-center gap-2 rounded-md bg-muted px-2.5 py-2 text-sm font-medium text-foreground"
          >
            <LayoutDashboard className="h-4 w-4" />
            Dashboard
          </Link>
          <Link
            href="/dashboard/trello"
            className="flex items-center gap-2 rounded-md px-2.5 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <Cable className="h-4 w-4" />
            Trello
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
