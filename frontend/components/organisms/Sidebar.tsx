"use client";

import {
  Blocks,
  BrainCircuit,
  BriefcaseBusiness,
  FileText,
  LayoutDashboard,
  LogOut,
  Sparkles,
  User as UserIcon,
  Users,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Button } from "@/components/atoms/Button";
import { ThemeToggle } from "@/components/atoms/ThemeToggle";
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
      ? "flex items-center gap-3 rounded-xl border border-[#4A5C6A] bg-[#253745] px-3.5 py-2.5 text-sm font-semibold text-white shadow-sm transition-all dark:text-[#F1F5F9]"
      : "flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium text-[#4A5C6A] transition-colors hover:bg-[#F1F5F9] hover:text-[#06141B] dark:text-[#9BA8AB] dark:hover:bg-[#162736] dark:hover:text-[#F1F5F9]";
  }

  return (
    <aside className="flex w-full shrink-0 flex-col border-b border-[#E2E8F0] bg-white transition-colors duration-200 dark:border-[#253745] dark:bg-[#11212D] md:h-screen md:w-64 md:border-b-0 md:border-r">
      <div className="flex items-center justify-between border-b border-[#E2E8F0] px-5 py-3 dark:border-[#253745]">
        <div className="flex items-center pt-1.5" aria-label="DeepClient">
          <Image
            src="/DeepClient-light.png"
            alt="DeepClient"
            width={380}
            height={98}
            priority
            className="h-8 w-auto dark:hidden"
          />
          <Image
            src="/DeepClient-dark.png"
            alt="DeepClient"
            width={380}
            height={98}
            priority
            className="hidden h-8 w-auto dark:block"
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
          <p className="px-3.5 pb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#64748B] dark:text-[#9BA8AB]">
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
      <div className="mt-auto space-y-2 border-t border-[#E2E8F0] p-4 dark:border-[#253745]">
        <div className="flex items-center justify-between gap-2 rounded-2xl border border-[#E2E8F0] bg-[#F1F5F9] p-2.5 dark:border-[#253745] dark:bg-[#162736]">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#4A5C6A] bg-[#253745] text-sm font-semibold text-white">
              {user?.name?.trim().charAt(0).toUpperCase() || "U"}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-[#06141B] dark:text-[#F1F5F9]">
                {user?.name ?? "…"}
              </p>
              <p className="truncate text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">{user?.email}</p>
            </div>
          </div>
          <ThemeToggle />
        </div>

        <Link
          href="/dashboard/profile"
          className={`flex h-10 w-full items-center justify-start gap-2.5 rounded-xl px-3 text-sm font-medium transition-colors ${
            pathname === "/dashboard/profile"
              ? "bg-[#253745] font-semibold text-white dark:text-[#F1F5F9]"
              : "text-[#4A5C6A] hover:bg-[#F1F5F9] hover:text-[#06141B] dark:text-[#9BA8AB] dark:hover:bg-[#162736] dark:hover:text-[#F1F5F9]"
          }`}
        >
          <UserIcon className="h-4 w-4" />
          Profile
        </Link>

        <Button
          variant="ghost"
          className="h-10 w-full justify-start gap-2.5 px-3 text-[#4A5C6A] hover:bg-[#F1F5F9] hover:text-[#06141B] dark:text-[#9BA8AB] dark:hover:bg-[#162736] dark:hover:text-[#F1F5F9]"
          onClick={onLogout}
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </Button>
      </div>
    </aside>
  );
}
