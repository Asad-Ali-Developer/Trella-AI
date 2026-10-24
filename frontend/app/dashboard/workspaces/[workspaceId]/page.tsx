"use client";

import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  Clock3,
  FileText,
  Layers3,
  Pencil,
  Unplug,
  X,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/atoms/Button";
import { IntegrationLogo, type IntegrationId } from "@/components/atoms/IntegrationLogo";
import { Sidebar } from "@/components/organisms/Sidebar";
import { WorkspaceCreateDrawer } from "@/components/organisms/WorkspaceCreateDrawer";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { clearSession, setAuthenticatedUser } from "@/lib/authSlice";
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

const apps: Array<{
  id: IntegrationId;
  name: string;
  description: string;
  available: boolean;
}> = [
  {
    id: "trello",
    name: "Trello",
    description: "Connect boards and organize project work by client.",
    available: true,
  },
  {
    id: "github",
    name: "GitHub",
    description: "Relate repositories and commits to client delivery.",
    available: true,
  },
  {
    id: "jira",
    name: "Jira",
    description: "Bring engineering projects and issues into context.",
    available: false,
  },
  {
    id: "slack",
    name: "Slack",
    description: "Share reports and updates with your team.",
    available: false,
  },
];

export default function WorkspaceDetailsPage() {
  const params = useParams<{ workspaceId: string }>();
  const workspaceId = params.workspaceId;
  const router = useRouter();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [trelloStatus, setTrelloStatus] = useState<TrelloConnectionStatus | null>(null);
  const [githubStatus, setGithubStatus] = useState<GithubConnectionStatus | null>(null);
  const [boards, setBoards] = useState<TrelloBoard[]>([]);
  const [mappings, setMappings] = useState<TrelloClientMapping[]>([]);
  const [loading, setLoading] = useState(true);
  const [editOpen, setEditOpen] = useState(false);
  const [disconnectTarget, setDisconnectTarget] = useState<"trello" | "github" | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [currentUser, workspaceList, details, trello, github] = await Promise.all([
        authService.me(),
        workspaceService.list(),
        workspaceService.get(workspaceId),
        trelloService.status(workspaceId).catch(() => ({ connected: false, username: null })),
        githubService.status(workspaceId).catch(() => ({ connected: false, username: null })),
      ]);
      dispatch(setAuthenticatedUser(currentUser));
      setWorkspaces(workspaceList);
      setWorkspace(details);
      setTrelloStatus(trello);
      setGithubStatus(github);
      workspaceStore.setWorkspaceId(workspaceId);
      if (trello.connected) {
        const [boardList, clientMappings] = await Promise.all([
          trelloService.listBoards(workspaceId).catch(() => []),
          trelloService.listClientMappings(workspaceId).catch(() => []),
        ]);
        setBoards(boardList);
        setMappings(clientMappings);
      } else {
        setBoards([]);
        setMappings([]);
      }
    } catch {
      setError("Could not load this workspace. It may not exist or you may not have access.");
    } finally {
      setLoading(false);
    }
  }, [dispatch, workspaceId]);

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
      setError("Could not sign out. Please retry.");
    }
  }

  function openIntegrationSettings(appId: IntegrationId) {
    workspaceStore.setWorkspaceId(workspaceId);
    if (appId === "trello") {
      router.push("/dashboard/trello");
    } else if (appId === "github") {
      router.push("/dashboard/github");
    } else {
      router.push("/dashboard/apps");
    }
  }

  function handleWorkspaceSaved(updated: Workspace) {
    setWorkspace(updated);
    setWorkspaces((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    setEditOpen(false);
  }

  async function disconnectApp() {
    if (!disconnectTarget) return;
    setDisconnecting(true);
    setError("");
    setNotice("");
    try {
      if (disconnectTarget === "trello") {
        const status = await trelloService.disconnect(workspaceId);
        setTrelloStatus(status);
        setBoards([]);
        setMappings([]);
        setNotice(
          "Trello was disconnected. Its synced boards, cards, and client mappings were removed from this workspace.",
        );
      } else if (disconnectTarget === "github") {
        const status = await githubService.disconnect(workspaceId);
        setGithubStatus(status);
        setNotice(
          "GitHub was disconnected. Its selected repositories and synced commits were removed from this workspace.",
        );
      }
      setDisconnectTarget(null);
    } catch {
      setError(
        `Could not disconnect ${disconnectTarget === "trello" ? "Trello" : "GitHub"}. No local connection data was removed. Please retry.`,
      );
    } finally {
      setDisconnecting(false);
    }
  }

  const includedBoards = boards.filter((board) => !board.excluded);
  const connectedClients = new Set(mappings.map((mapping) => mapping.client_name)).size;
  const connectedAppsCount = (trelloStatus?.connected ? 1 : 0) + (githubStatus?.connected ? 1 : 0);
  const canEditWorkspace = workspace?.role === "owner" || workspace?.role === "admin";

  return (
    <DashboardTemplate
      sidebar={
        <Sidebar
          user={user}
          workspaces={workspaces}
          selectedId={workspaceId}
          onSelectWorkspace={(selected) => {
            workspaceStore.setWorkspaceId(selected.id);
            router.push(`/dashboard/workspaces/${selected.id}`);
          }}
          onLogout={() => void logout()}
        />
      }
    >
      <div className="mx-auto w-full max-w-6xl space-y-7 pb-10">
        <Link
          href="/dashboard/workspaces"
          className="inline-flex items-center gap-2 text-sm font-medium text-zinc-500 transition hover:text-indigo-700"
        >
          <ArrowLeft className="h-4 w-4" />
          All workspaces
        </Link>

        {loading ? (
          <div role="status" className="rounded-2xl border border-zinc-200 bg-white p-6 text-sm text-zinc-500">
            Loading workspace details…
          </div>
        ) : error || !workspace ? (
          <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-800">
            {error || "Workspace not found."}
          </div>
        ) : (
          <>
            <header className="flex flex-col gap-5 border-b border-zinc-200 pb-6 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <p className="text-sm font-medium text-indigo-600">Workspace details</p>
                <h1 className="mt-1 text-3xl font-semibold tracking-tight text-zinc-950">{workspace.name}</h1>
                <p className="mt-2 text-sm text-zinc-500">
                  {workspace.client_name ? `Client: ${workspace.client_name}` : "No client name added"}
                  <span className="px-2 text-zinc-300">·</span>
                  {workspace.role}
                </p>
                {workspace.description ? (
                  <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-600">{workspace.description}</p>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-2 self-start">
                {canEditWorkspace ? (
                  <Button
                    type="button"
                    variant="secondary"
                    className="gap-2 rounded-lg border-zinc-200"
                    onClick={() => setEditOpen(true)}
                  >
                    <Pencil className="h-4 w-4" />
                    Edit workspace
                  </Button>
                ) : null}
                <Button
                  type="button"
                  variant="secondary"
                  className="gap-2 rounded-lg border-zinc-200"
                  onClick={() => {
                    workspaceStore.setWorkspaceId(workspaceId);
                    router.push("/dashboard/apps");
                  }}
                >
                  <Layers3 className="h-4 w-4" />
                  Manage integrations
                </Button>
              </div>
            </header>

            {notice ? (
              <p role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                {notice}
              </p>
            ) : null}

            <section aria-label="Workspace overview" className="grid gap-4 sm:grid-cols-3">
              <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                <p className="text-sm text-zinc-500">Connected apps</p>
                <p className="mt-2 text-2xl font-semibold text-zinc-950">{connectedAppsCount}</p>
                <p className="mt-1 text-xs text-zinc-500">of 4 integrations available or planned</p>
              </div>
              <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                <p className="text-sm text-zinc-500">Included Trello boards</p>
                <p className="mt-2 text-2xl font-semibold text-zinc-950">{includedBoards.length}</p>
                <p className="mt-1 text-xs text-zinc-500">Selected for this workspace</p>
              </div>
              <div className="rounded-2xl border border-zinc-200 bg-white p-5">
                <p className="text-sm text-zinc-500">Mapped clients</p>
                <p className="mt-2 text-2xl font-semibold text-zinc-950">{connectedClients}</p>
                <p className="mt-1 text-xs text-zinc-500">From Trello client rules</p>
              </div>
            </section>

            <section aria-labelledby="workspace-apps-heading">
              <div className="mb-4">
                <h2 id="workspace-apps-heading" className="text-lg font-semibold text-zinc-950">
                  Apps in this workspace
                </h2>
                <p className="mt-1 text-sm text-zinc-500">
                  Connect project sources and report delivery for {workspace.client_name || workspace.name}.
                </p>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                {apps.map((app) => {
                  const isTrello = app.id === "trello";
                  const isGithub = app.id === "github";
                  const connected = isTrello
                    ? Boolean(trelloStatus?.connected)
                    : isGithub
                      ? Boolean(githubStatus?.connected)
                      : false;
                  return (
                    <article key={app.id} className="flex items-center gap-4 rounded-2xl border border-zinc-200 bg-white p-5">
                      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-zinc-50">
                        <IntegrationLogo app={app.id} className="h-6 w-6" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-sm font-semibold text-zinc-950">{app.name}</h3>
                          {connected ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                              <Check className="h-3 w-3" />
                              Connected
                            </span>
                          ) : app.available ? (
                            <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-600">
                              Not connected
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800">
                              <Clock3 className="h-3 w-3" />
                              Coming soon
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-sm leading-5 text-zinc-500">{app.description}</p>
                      </div>
                      {app.available ? (
                        <div className="flex shrink-0 flex-col items-end gap-2">
                          <button
                            type="button"
                            onClick={() => openIntegrationSettings(app.id)}
                            className="inline-flex items-center gap-1 text-sm font-semibold text-indigo-700 hover:text-indigo-900"
                          >
                            {connected ? "Settings" : "Connect"}
                            <ArrowRight className="h-4 w-4" />
                          </button>
                          {connected ? (
                            <button
                              type="button"
                              onClick={() => setDisconnectTarget(isTrello ? "trello" : "github")}
                              className="inline-flex items-center gap-1 text-xs font-medium text-rose-600 hover:text-rose-800"
                            >
                              <Unplug className="h-3.5 w-3.5" />
                              Disconnect
                            </button>
                          ) : null}
                        </div>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            </section>

            <section className="rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-700">
                  <FileText className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="text-sm font-semibold text-zinc-900">Build context one source at a time</h2>
                  <p className="mt-1 text-sm leading-6 text-zinc-500">
                    Trello and GitHub are ready now. Jira will add engineering projects and issue activity, while Slack will deliver reports when those integrations become available.
                  </p>
                </div>
              </div>
            </section>
          </>
        )}
      </div>

      {editOpen && workspace ? (
        <WorkspaceCreateDrawer
          mode="edit"
          workspace={workspace}
          onClose={() => setEditOpen(false)}
          onSaved={handleWorkspaceSaved}
        />
      ) : null}

      {disconnectTarget ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/40 p-4 backdrop-blur-[2px]"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !disconnecting) setDisconnectTarget(null);
          }}
        >
          <section
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="disconnect-title"
            className="w-full max-w-md rounded-2xl border border-zinc-200 bg-white p-6 shadow-2xl"
          >
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-rose-50 text-rose-700">
              <AlertTriangle className="h-5 w-5" />
            </div>
            <h2 id="disconnect-title" className="mt-4 text-lg font-semibold text-zinc-950">
              Disconnect {disconnectTarget === "trello" ? "Trello" : "GitHub"}?
            </h2>
            <p className="mt-2 text-sm leading-6 text-zinc-600">
              {disconnectTarget === "trello"
                ? "This removes Trello and its synced boards, cards, comments, and client mappings from this workspace only. Other workspaces linked to the same account stay connected. The authorization is removed after its final workspace link is disconnected."
                : "This removes GitHub and its selected repositories and synced commits from this workspace only. Other workspaces linked to the same account stay connected. The authorization is removed after its final workspace link is disconnected."}
            </p>
            <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button
                type="button"
                variant="secondary"
                className="gap-2 rounded-lg"
                onClick={() => setDisconnectTarget(null)}
                disabled={disconnecting}
              >
                <X className="h-4 w-4" />
                Keep connected
              </Button>
              <Button
                type="button"
                className="gap-2 rounded-lg bg-rose-600 text-white hover:bg-rose-700"
                onClick={() => void disconnectApp()}
                disabled={disconnecting}
              >
                <Unplug className="h-4 w-4" />
                {disconnecting ? "Disconnecting…" : "Disconnect and remove data"}
              </Button>
            </div>
          </section>
        </div>
      ) : null}
    </DashboardTemplate>
  );
}
