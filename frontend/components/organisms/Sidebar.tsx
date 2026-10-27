"use client";

import { Blocks, BrainCircuit, BriefcaseBusiness, FileText, LayoutDashboard, LogOut, Sparkles, Users } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Button } from "@/components/atoms/Button";
import { WorkspaceSwitcher } from "@/components/organisms/WorkspaceSwitcher";
import type { User, Workspace } from "@/lib/types";

interface SidebarProps {
  user: User | null;
  workspaces: Workspace[];
  selectedId: string | null;
  onSelectWorkspace: (workspace: Workspace) => void;
  onLogout: () => void;
}

export function Sidebar({
  user,
  workspaces,
  selectedId,
  onSelectWorkspace,
  onLogout,
}: SidebarProps) {
  const pathname = usePathname();

  function navClass(active: boolean) {
    return active
      ? "flex items-center gap-3 rounded-lg bg-indigo-50 px-3 py-2.5 text-sm font-semibold text-indigo-700"
      : "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-zinc-100 hover:text-foreground";
  }

  return (
    <aside className="flex w-full shrink-0 flex-col border-b border-zinc-200 bg-white md:h-screen md:w-64 md:border-b-0 md:border-r">
      <div className="border-b border-zinc-100 px-5 py-2.5">
        <div className="relative h-[40px] w-full overflow-hidden" aria-label="DeepClient">
          <Image
            src="/DeepClient.png"
            alt="DeepClient"
            width={512}
            height={293}
            priority
            className="absolute -top-[21px] left-0 h-auto w-[148px] max-w-none"
          />
        </div>
      </div>
      <div className="space-y-6 p-4">
        <WorkspaceSwitcher
            workspaces={workspaces}
            selectedId={selectedId}
            onSelect={onSelectWorkspace}
          />
        <nav aria-label="Main navigation" className="space-y-1">
          <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-400">
            Workspace
          </p>
          <Link
            href="/dashboard"
            aria-current={pathname === "/dashboard" ? "page" : undefined}
            className={navClass(pathname === "/dashboard")}
          >
            <LayoutDashboard className="h-[18px] w-[18px]" />
            Dashboard
          </Link>
          <Link
            href="/dashboard/clients"
            aria-current={pathname.startsWith("/dashboard/clients") ? "page" : undefined}
            className={navClass(pathname.startsWith("/dashboard/clients"))}
          >
            <Users className="h-[18px] w-[18px]" />
            Client Profiles
          </Link>
          <Link
            href="/dashboard/reports"
            aria-current={pathname.startsWith("/dashboard/reports") ? "page" : undefined}
            className={navClass(pathname.startsWith("/dashboard/reports"))}
          >
            <FileText className="h-[18px] w-[18px]" />
            Reports & Runs
          </Link>
          <Link
            href="/dashboard/skills"
            aria-current={pathname.startsWith("/dashboard/skills") ? "page" : undefined}
            className={navClass(pathname.startsWith("/dashboard/skills"))}
          >
            <Sparkles className="h-[18px] w-[18px]" />
            AI Skills Lab
          </Link>
          <Link
            href="/dashboard/context"
            aria-current={pathname.startsWith("/dashboard/context") ? "page" : undefined}
            className={navClass(pathname.startsWith("/dashboard/context"))}
          >
            <BrainCircuit className="h-[18px] w-[18px]" />
            Workspace context
          </Link>
          <Link
            href="/dashboard/workspaces"
            aria-current={
              pathname.startsWith("/dashboard/workspaces") ? "page" : undefined
            }
            className={navClass(pathname.startsWith("/dashboard/workspaces"))}
          >
            <BriefcaseBusiness className="h-[18px] w-[18px]" />
            Workspaces
          </Link>
          <Link
            href="/dashboard/apps"
            aria-current={
              pathname.startsWith("/dashboard/apps") ||
              pathname.startsWith("/dashboard/trello") ||
              pathname.startsWith("/dashboard/github")
                ? "page"
                : undefined
            }
            className={navClass(
              pathname.startsWith("/dashboard/apps") ||
              pathname.startsWith("/dashboard/trello") ||
              pathname.startsWith("/dashboard/github"),
            )}
          >
            <Blocks className="h-[18px] w-[18px]" />
            Connected Apps
          </Link>
        </nav>
      </div>
      <div className="mt-auto space-y-3 border-t border-zinc-100 p-4">
        <div className="flex items-center gap-3 rounded-xl bg-zinc-50 p-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-sm font-semibold text-indigo-700">
            {user?.name?.trim().charAt(0).toUpperCase() || "U"}
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-zinc-900">{user?.name ?? "…"}</p>
            <p className="truncate text-xs text-zinc-500">{user?.email}</p>
          </div>
        </div>
        <Button
          variant="ghost"
          className="h-10 w-full justify-start gap-2.5 px-3 text-zinc-500 hover:text-zinc-900"
          onClick={onLogout}
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </Button>
      </div>
    </aside>
  );
}
