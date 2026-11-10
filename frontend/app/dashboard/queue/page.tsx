"use client";

import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock,
  Layers,
  RefreshCw,
  Server,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/atoms/Button";
import { PageTransition } from "@/components/atoms/PageTransition";
import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { clearSession, setAuthenticatedUser } from "@/lib/authSlice";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { workspaceStore } from "@/lib/storage";
import type { Workspace } from "@/lib/types";
import { authService } from "@/services/AuthService";
import { queueService, type QueueStatusResponse } from "@/services/QueueService";
import { trelloService } from "@/services/TrelloService";
import { workspaceService } from "@/services/WorkspaceService";
import { useSyncQueue } from "@/components/providers/SyncQueueProvider";

export default function QueuePage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);
  const { notifySyncStarted } = useSyncQueue();

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [data, setData] = useState<QueueStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncingAll, setSyncingAll] = useState(false);
  const [syncingSourceId, setSyncingSourceId] = useState<string | null>(null);

  const loadQueue = useCallback(async (workspaceId: string) => {
    try {
      const res = await queueService.getStatus(workspaceId);
      setData(res);
    } catch {
      // silently ignore
    } finally {
      setLoading(false);
    }
  }, []);

  const loadWorkspace = useCallback(
    async (workspace: Workspace) => {
      workspaceStore.setWorkspaceId(workspace.id);
      setSelectedWorkspace(workspace);
      setLoading(true);
      await loadQueue(workspace.id);
    },
    [loadQueue],
  );

  const load = useCallback(async () => {
    try {
      const [currentUser, workspaceList] = await Promise.all([
        authService.me(),
        workspaceService.list(),
      ]);
      dispatch(setAuthenticatedUser(currentUser));
      setWorkspaces(workspaceList);
      const storedId = workspaceStore.getWorkspaceId();
      const workspace = workspaceList.find((item) => item.id === storedId) ?? workspaceList[0];
      if (workspace) {
        await loadWorkspace(workspace);
      }
    } catch {
      setLoading(false);
    }
  }, [dispatch, loadWorkspace]);

  useEffect(() => {
    void load();
  }, [load]);

  // Real-time polling while on this page (every 3 seconds)
  useEffect(() => {
    if (!selectedWorkspace) return;
    const interval = setInterval(() => {
      void loadQueue(selectedWorkspace.id);
    }, 3000);
    return () => clearInterval(interval);
  }, [loadQueue, selectedWorkspace]);

  function logout() {
    void authService
      .logout()
      .then(() => {
        dispatch(clearSession());
        router.replace("/login");
      })
      .catch(() => {});
  }

  async function handleSyncAll() {
    if (!selectedWorkspace) return;
    setSyncingAll(true);
    notifySyncStarted("All Workspace Sources");
    try {
      await queueService.syncAll(selectedWorkspace.id);
      await loadQueue(selectedWorkspace.id);
    } catch {
      // ignore
    } finally {
      setSyncingAll(false);
    }
  }

  async function handleSyncSingle(sourceId: string, name: string) {
    if (!selectedWorkspace) return;
    setSyncingSourceId(sourceId);
    notifySyncStarted(name);
    try {
      await trelloService.syncBoards();
      await loadQueue(selectedWorkspace.id);
    } catch {
      // ignore
    } finally {
      setSyncingSourceId(null);
    }
  }

  function formatTime(dateStr: string | null) {
    if (!dateStr) return "Never";
    const d = new Date(dateStr);
    const now = new Date();
    const diffSec = Math.floor((now.getTime() - d.getTime()) / 1000);
    if (diffSec < 60) return "Just now";
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    return d.toLocaleDateString();
  }

  return (
    <DashboardTemplate
      sidebar={
        <Sidebar
          user={user}
          workspaces={workspaces}
          selectedId={selectedWorkspace?.id ?? null}
          onSelectWorkspace={(workspace) => void loadWorkspace(workspace)}
          onLogout={logout}
        />
      }
    >
      <PageTransition className="mx-auto w-full max-w-6xl space-y-7 pb-10">
        {/* Header */}
        <header className="flex flex-col gap-4 border-b border-zinc-200 pb-6 sm:flex-row sm:items-center sm:justify-between dark:border-[#253745]">
          <div>
            <p className="text-sm font-semibold text-indigo-600 dark:text-[#CCD0CF]">
              {selectedWorkspace?.name ?? "Workspace"} <span className="px-1 text-zinc-300 dark:text-[#4A5C6A]">/</span> Sync Queue
            </p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight text-zinc-950 dark:text-[#F1F5F9]">
              Task & Ingestion Queue
            </h1>
            <p className="mt-1 text-sm text-zinc-500 dark:text-[#9BA8AB]">
              Real-time monitoring of Celery background workers, queue backlog, and source ingestion.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant="secondary"
              onClick={() => selectedWorkspace && void loadQueue(selectedWorkspace.id)}
              disabled={loading}
              className="gap-2"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            <Button
              onClick={handleSyncAll}
              disabled={syncingAll || !data?.is_worker_online}
              className="gap-2 bg-indigo-600 hover:bg-indigo-700 text-white dark:bg-indigo-600 dark:hover:bg-indigo-500"
            >
              <Zap className="h-4 w-4" />
              Sync All Sources
            </Button>
          </div>
        </header>

        {/* Top 4 KPI Metrics */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {/* Card 1: Worker Status */}
          <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-[#253745] dark:bg-[#11212D]">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wider text-zinc-500 dark:text-[#9BA8AB]">
                Worker Engine
              </span>
              <Server className="h-4 w-4 text-zinc-400" />
            </div>
            <div className="mt-3 flex items-center gap-2">
              <span
                className={`flex h-3 w-3 rounded-full ${
                  data?.is_worker_online ? "bg-emerald-500 animate-pulse" : "bg-rose-500"
                }`}
              />
              <span className="text-xl font-bold text-zinc-900 dark:text-[#F1F5F9]">
                {data?.is_worker_online ? "Worker Online" : "Worker Offline"}
              </span>
            </div>
            <p className="mt-1 truncate text-xs text-zinc-400 dark:text-[#9BA8AB]">
              {data?.is_worker_online ? data.worker_name || "Celery active" : "Run docker compose up -d worker"}
            </p>
          </div>

          {/* Card 2: Queue Backlog */}
          <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-[#253745] dark:bg-[#11212D]">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wider text-zinc-500 dark:text-[#9BA8AB]">
                Pending Backlog
              </span>
              <Layers className="h-4 w-4 text-zinc-400" />
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <span className="text-2xl font-bold text-zinc-900 dark:text-[#F1F5F9]">
                {data?.celery_queue_length ?? 0}
              </span>
              <span className="text-xs text-zinc-500 dark:text-[#9BA8AB]">tasks</span>
            </div>
            <p className="mt-1 text-xs text-zinc-400 dark:text-[#9BA8AB]">
              {data?.redis_connected ? "Redis broker connected" : "Broker disconnected"}
            </p>
          </div>

          {/* Card 3: Active Ingestion */}
          <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-[#253745] dark:bg-[#11212D]">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wider text-zinc-500 dark:text-[#9BA8AB]">
                Active Ingestion
              </span>
              <Activity className="h-4 w-4 text-zinc-400" />
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <span className="text-2xl font-bold text-zinc-900 dark:text-[#F1F5F9]">
                {data?.syncing_count ?? 0}
              </span>
              <span className="text-xs text-zinc-500 dark:text-[#9BA8AB]">in progress</span>
            </div>
            <p className="mt-1 text-xs text-zinc-400 dark:text-[#9BA8AB]">
              {(data?.syncing_count ?? 0) > 0 ? "Downloading & embedding" : "Idle (Ready)"}
            </p>
          </div>

          {/* Card 4: Indexed Chunks */}
          <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-[#253745] dark:bg-[#11212D]">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wider text-zinc-500 dark:text-[#9BA8AB]">
                Indexed Chunks
              </span>
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <span className="text-2xl font-bold text-zinc-900 dark:text-[#F1F5F9]">
                {data?.total_chunks ?? 0}
              </span>
              <span className="text-xs text-zinc-500 dark:text-[#9BA8AB]">vectors</span>
            </div>
            <p className="mt-1 text-xs text-zinc-400 dark:text-[#9BA8AB]">
              768-d Gemini embeddings ready
            </p>
          </div>
        </div>

        {/* Sources & Ingestion Status Section */}
        <div className="rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-[#253745] dark:bg-[#11212D]">
          <div className="flex items-center justify-between border-b border-zinc-200 px-6 py-4 dark:border-[#253745]">
            <div>
              <h2 className="text-lg font-semibold text-zinc-900 dark:text-[#F1F5F9]">
                Workspace Ingestion Sources
              </h2>
              <p className="text-xs text-zinc-500 dark:text-[#9BA8AB]">
                Trello boards and GitHub repositories configured for this workspace.
              </p>
            </div>
            <Link
              href="/dashboard/trello"
              className="text-xs font-medium text-indigo-600 hover:text-indigo-700 dark:text-indigo-400"
            >
              Configure Boards &rarr;
            </Link>
          </div>

          <div className="divide-y divide-zinc-200 dark:divide-[#253745]">
            {data?.items && data.items.length > 0 ? (
              data.items.map((item) => (
                <div
                  key={item.id}
                  className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex items-start gap-3">
                    <span
                      className={`mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${
                        item.source_type === "trello"
                          ? "bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-400"
                          : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
                      }`}
                    >
                      {item.source_type === "trello" ? "T" : "G"}
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-base font-medium text-zinc-900 dark:text-[#F1F5F9]">
                          {item.name}
                        </span>
                        <span className="rounded-md border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-[11px] font-medium text-zinc-600 dark:border-[#253745] dark:bg-[#162736] dark:text-[#CCD0CF]">
                          {item.source_type.toUpperCase()}
                        </span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-4 text-xs text-zinc-500 dark:text-[#9BA8AB]">
                        <span>Cards/Commits: <strong className="text-zinc-700 dark:text-zinc-300">{item.items_count}</strong></span>
                        <span>•</span>
                        <span>Vectors: <strong className="text-zinc-700 dark:text-zinc-300">{item.chunks_count}</strong></span>
                        <span>•</span>
                        <span>Last Synced: {formatTime(item.last_synced_at)}</span>
                      </div>
                      {item.sync_error && (
                        <p className="mt-1 text-xs text-rose-500 dark:text-rose-400">
                          {item.sync_error}
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-3 self-end sm:self-center">
                    {item.status === "completed" && (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-400">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        Synced
                      </span>
                    )}
                    {item.status === "running" && (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/40 dark:text-indigo-400">
                        <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                        Syncing...
                      </span>
                    )}
                    {item.status === "not_started" && (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-200 bg-zinc-100 px-3 py-1 text-xs font-medium text-zinc-600 dark:border-[#253745] dark:bg-[#162736] dark:text-[#9BA8AB]">
                        <Clock className="h-3.5 w-3.5" />
                        Not synced yet
                      </span>
                    )}
                    {item.status === "failed" && (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-rose-200 bg-rose-50 px-3 py-1 text-xs font-medium text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-400">
                        <AlertCircle className="h-3.5 w-3.5" />
                        Failed
                      </span>
                    )}

                    <Button
                      variant="secondary"
                      onClick={() => handleSyncSingle(item.id, item.name)}
                      disabled={syncingSourceId === item.id || item.status === "running" || !data?.is_worker_online}
                      className="gap-1.5 h-8 text-xs px-2.5"
                    >
                      <RefreshCw className={`h-3 w-3 ${syncingSourceId === item.id ? "animate-spin" : ""}`} />
                      Sync Now
                    </Button>
                  </div>
                </div>
              ))
            ) : (
              <div className="p-8 text-center text-sm text-zinc-500 dark:text-[#9BA8AB]">
                No sources connected yet. Go to{" "}
                <Link href="/dashboard/trello" className="font-semibold text-indigo-600 dark:text-indigo-400">
                  Connected Apps
                </Link>{" "}
                to connect Trello or GitHub.
              </div>
            )}
          </div>
        </div>

        {/* Recent Activity Log */}
        <div className="rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-[#253745] dark:bg-[#11212D]">
          <div className="border-b border-zinc-200 px-6 py-4 dark:border-[#253745]">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-[#F1F5F9]">
              Recent Worker Runs & Executions
            </h2>
            <p className="text-xs text-zinc-500 dark:text-[#9BA8AB]">
              Background executions processed by the Celery worker for this workspace.
            </p>
          </div>

          <div className="divide-y divide-zinc-200 dark:divide-[#253745]">
            {data?.recent_runs && data.recent_runs.length > 0 ? (
              data.recent_runs.map((run) => (
                <div key={run.id} className="flex items-center justify-between p-4 sm:px-6">
                  <div className="flex items-center gap-3">
                    <span
                      className={`flex h-8 w-8 items-center justify-center rounded-lg ${
                        run.status === "completed"
                          ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400"
                          : run.status === "running"
                          ? "bg-indigo-50 text-indigo-600 dark:bg-indigo-950/40 dark:text-indigo-400"
                          : "bg-zinc-100 text-zinc-600 dark:bg-[#162736] dark:text-[#9BA8AB]"
                      }`}
                    >
                      {run.status === "completed" ? (
                        <CheckCircle2 className="h-4 w-4" />
                      ) : (
                        <Activity className="h-4 w-4" />
                      )}
                    </span>
                    <div>
                      <p className="text-sm font-medium text-zinc-900 dark:text-[#F1F5F9]">
                        {run.skill_name}
                      </p>
                      <p className="text-xs text-zinc-500 dark:text-[#9BA8AB]">
                        Trigger: {run.trigger} • Tokens: {(run.tokens_in || 0) + (run.tokens_out || 0)} • {formatTime(run.created_at)}
                      </p>
                    </div>
                  </div>

                  <span
                    className={`rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${
                      run.status === "completed"
                        ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400"
                        : run.status === "failed"
                        ? "bg-rose-50 text-rose-700 dark:bg-rose-950/50 dark:text-rose-400"
                        : "bg-zinc-100 text-zinc-700 dark:bg-[#162736] dark:text-[#CCD0CF]"
                    }`}
                  >
                    {run.status}
                  </span>
                </div>
              ))
            ) : (
              <div className="p-6 text-center text-sm text-zinc-500 dark:text-[#9BA8AB]">
                No recent runs recorded yet.
              </div>
            )}
          </div>
        </div>
      </PageTransition>
    </DashboardTemplate>
  );
}
