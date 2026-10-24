"use client";

import {
  ArrowRight,
  BriefcaseBusiness,
  CheckCircle2,
  Layers3,
  UsersRound,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import {
  clearSession,
  setAuthenticatedUser,
  setSessionLoading,
} from "@/lib/authSlice";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { workspaceStore } from "@/lib/storage";
import type {
  GithubConnectionStatus,
  TrelloBoard,
  TrelloClientMapping,
  TrelloConnectionStatus,
  Workspace,
} from "@/lib/types";
import { authService } from "@/services/AuthService";
import { githubService } from "@/services/GithubService";
import { trelloService } from "@/services/TrelloService";
import { workspaceService } from "@/services/WorkspaceService";

interface WorkspaceStats {
  connectedApps: number;
  includedBoards: number;
  mappedClients: number;
  completedBoards: number;
}

const emptyStats: WorkspaceStats = {
  connectedApps: 0,
  includedBoards: 0,
  mappedClients: 0,
  completedBoards: 0,
};

export default function DashboardPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(
    null,
  );
  const [stats, setStats] = useState<WorkspaceStats>(emptyStats);
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState("");

  const loadWorkspaceStats = useCallback(async (workspace: Workspace) => {
    workspaceStore.setWorkspaceId(workspace.id);
    setSelectedWorkspace(workspace);
    setStatsLoading(true);
    setStatsError("");
    try {
      const [trello, github] = await Promise.all([
        trelloService.status(workspace.id).catch(() => ({ connected: false, username: null })),
        githubService.status(workspace.id).catch(() => ({ connected: false, username: null })),
      ]);
      const connectedAppsCount = (trello.connected ? 1 : 0) + (github.connected ? 1 : 0);
      if (connectedAppsCount === 0) {
        setStats(emptyStats);
        return;
      }
      let includedBoardsCount = 0;
      let mappedClientsCount = 0;
      let completedBoardsCount = 0;
      if (trello.connected) {
        const [boards, mappings]: [TrelloBoard[], TrelloClientMapping[]] =
          await Promise.all([
            trelloService.listBoards(workspace.id).catch(() => []),
            trelloService.listClientMappings(workspace.id).catch(() => []),
          ]);
        const includedBoards = boards.filter((board) => !board.excluded);
        includedBoardsCount = includedBoards.length;
        mappedClientsCount = new Set(mappings.map((mapping) => mapping.client_name)).size;
        completedBoardsCount = includedBoards.filter(
          (board) => board.sync_status === "completed",
        ).length;
      }
      setStats({
        connectedApps: connectedAppsCount,
        includedBoards: includedBoardsCount,
        mappedClients: mappedClientsCount,
        completedBoards: completedBoardsCount,
      });
    } catch {
      setStats(emptyStats);
      setStatsError(
        "Workspace stats could not be loaded. Try switching workspaces or refreshing.",
      );
    } finally {
      setStatsLoading(false);
    }
  }, []);

  const load = useCallback(async () => {
    dispatch(setSessionLoading());
    try {
      const [me, items] = await Promise.all([
        authService.me(),
        workspaceService.list(),
      ]);
      dispatch(setAuthenticatedUser(me));
      setWorkspaces(items);
      const stored = workspaceStore.getWorkspaceId();
      const selected =
        items.find((workspace) => workspace.id === stored) ?? items[0] ?? null;
      if (selected) {
        await loadWorkspaceStats(selected);
      }
    } catch {
      dispatch(clearSession());
      workspaceStore.clear();
      router.replace("/login");
    } finally {
      setLoading(false);
    }
  }, [dispatch, loadWorkspaceStats, router]);

  useEffect(() => {
    void load();
  }, [load]);

  async function logout() {
    try {
      await authService.logout();
      dispatch(clearSession());
      workspaceStore.clear();
      router.replace("/login");
    } catch {
      setStatsError("Could not sign out. Please retry.");
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Loading your dashboard…
      </div>
    );
  }

  const statCards = [
    {
      label: "Workspaces",
      value: workspaces.length,
      detail: "Client spaces you can access",
      Icon: BriefcaseBusiness,
      color: "bg-indigo-50 text-indigo-700",
    },
    {
      label: "Connected apps",
      value: stats.connectedApps,
      detail: "Connected to this workspace",
      Icon: Workflow,
      color: "bg-violet-50 text-violet-700",
    },
    {
      label: "Included boards",
      value: stats.includedBoards,
      detail: `${stats.completedBoards} synced and up to date`,
      Icon: Layers3,
      color: "bg-blue-50 text-blue-700",
    },
    {
      label: "Mapped clients",
      value: stats.mappedClients,
      detail: "Organized from Trello rules",
      Icon: UsersRound,
      color: "bg-emerald-50 text-emerald-700",
    },
  ];

  return (
    <DashboardTemplate
      sidebar={
        <Sidebar
          user={user}
          workspaces={workspaces}
          selectedId={selectedWorkspace?.id ?? null}
          onSelectWorkspace={(workspace) => void loadWorkspaceStats(workspace)}
          onLogout={() => void logout()}
        />
      }
    >
      <div className="mx-auto w-full max-w-6xl space-y-8 pb-10">
        <header className="flex flex-col gap-4 border-b border-zinc-200 pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-medium text-indigo-600">Overview</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight text-zinc-950">
              Dashboard
            </h1>
            <p className="mt-2 text-sm text-zinc-500">
              {selectedWorkspace
                ? `A snapshot of ${selectedWorkspace.client_name || selectedWorkspace.name}.`
                : "Your client workspaces and connected sources at a glance."}
            </p>
          </div>
          <div className="flex gap-2">
            <Link
              href="/dashboard/workspaces"
              className="inline-flex h-10 items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3.5 text-sm font-medium text-zinc-700 shadow-sm transition hover:bg-zinc-50"
            >
              <BriefcaseBusiness className="h-4 w-4" />
              Workspaces
            </Link>
            {selectedWorkspace ? (
              <Link
                href="/dashboard/apps"
                className="inline-flex h-10 items-center gap-2 rounded-lg bg-indigo-600 px-3.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700"
              >
                Connected apps
                <ArrowRight className="h-4 w-4" />
              </Link>
            ) : null}
          </div>
        </header>

        {statsError ? (
          <div
            role="alert"
            className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"
          >
            {statsError}
          </div>
        ) : null}

        {selectedWorkspace ? (
          <>
            <section aria-label="Workspace statistics">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-base font-semibold text-zinc-900">
                  Workspace overview
                </h2>
                {statsLoading ? (
                  <span role="status" className="text-xs text-zinc-500">
                    Refreshing stats…
                  </span>
                ) : null}
              </div>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {statCards.map(({ label, value, detail, Icon, color }) => (
                  <article
                    key={label}
                    className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-medium text-zinc-500">
                        {label}
                      </p>
                      <span
                        className={`flex h-9 w-9 items-center justify-center rounded-xl ${color}`}
                      >
                        <Icon className="h-[18px] w-[18px]" />
                      </span>
                    </div>
                    <p className="mt-4 text-3xl font-semibold tracking-tight text-zinc-950">
                      {statsLoading && label !== "Workspaces" ? "—" : value}
                    </p>
                    <p className="mt-1 text-xs text-zinc-500">{detail}</p>
                  </article>
                ))}
              </div>
            </section>

            <section className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm sm:p-6">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-start gap-4">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-700">
                    <BriefcaseBusiness className="h-5 w-5" />
                  </span>
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                      Current workspace
                    </p>
                    <h2 className="mt-1 text-lg font-semibold text-zinc-950">
                      {selectedWorkspace.client_name || selectedWorkspace.name}
                    </h2>
                    <p className="mt-1 text-sm text-zinc-500">
                      {selectedWorkspace.description ||
                        "Connect the tools this client’s team uses to build shared context."}
                    </p>
                  </div>
                </div>
                <Link
                  href={`/dashboard/workspaces/${selectedWorkspace.id}`}
                  className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3.5 text-sm font-semibold text-zinc-700 transition hover:bg-zinc-50"
                >
                  View workspace
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
            </section>

            <section className="rounded-2xl border border-indigo-100 bg-indigo-50/60 p-5 sm:p-6">
              <div className="flex items-start gap-3">
                <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-indigo-700" />
                <div>
                  <h2 className="text-sm font-semibold text-indigo-950">
                    A clearer picture of client work
                  </h2>
                  <p className="mt-1 max-w-3xl text-sm leading-6 text-indigo-900/75">
                    DeepClient brings project activity and client context
                    together in each workspace. Trello and GitHub are available now;
                    Jira and Slack are coming soon.
                  </p>
                </div>
              </div>
            </section>
          </>
        ) : (
          <section className="rounded-2xl border border-dashed border-zinc-300 bg-white px-6 py-14 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-700">
              <BriefcaseBusiness className="h-6 w-6" />
            </div>
            <h2 className="mt-4 text-lg font-semibold text-zinc-950">
              Start with a workspace
            </h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-zinc-500">
              Create a workspace for a client to connect its project tools and
              bring work into one place.
            </p>
            <Link
              href="/dashboard/workspaces"
              className="mt-5 inline-flex h-10 items-center gap-2 rounded-lg bg-indigo-600 px-4 text-sm font-semibold text-white hover:bg-indigo-700"
            >
              Open workspaces
              <ArrowRight className="h-4 w-4" />
            </Link>
          </section>
        )}
      </div>
    </DashboardTemplate>
  );
}
