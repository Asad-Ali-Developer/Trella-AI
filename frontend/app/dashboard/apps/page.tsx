"use client";

import {
  ArrowRight,
  Check,
  Clock3,
  ExternalLink,
  GitBranch,
  Layers3,
  MessageSquareText,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/atoms/Button";
import { IntegrationLogo, type IntegrationId } from "@/components/atoms/IntegrationLogo";
import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { clearSession, setAuthenticatedUser } from "@/lib/authSlice";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { workspaceStore } from "@/lib/storage";
import type { GithubConnectionStatus, TrelloConnectionStatus, Workspace } from "@/lib/types";
import { authService } from "@/services/AuthService";
import { githubService } from "@/services/GithubService";
import { trelloService } from "@/services/TrelloService";
import { workspaceService } from "@/services/WorkspaceService";

type AppId = IntegrationId;

const apps = [
  {
    id: "trello" as const,
    name: "Trello",
    category: "Work source",
    summary: "Bring project boards, cards, and client work into the workspace.",
    detail: "Sync selected Trello boards and organize cards by client.",
    iconClass: "bg-blue-50 text-blue-700",
    available: true,
  },
  {
    id: "github" as const,
    name: "GitHub",
    category: "Work source",
    summary: "Add repositories and commits to the client-work context.",
    detail: "Connect a GitHub account, select repositories, and bring recent commits into workspace context.",
    iconClass: "bg-zinc-100 text-zinc-800",
    available: true,
  },
  {
    id: "jira" as const,
    name: "Jira",
    category: "Work source",
    summary: "Add engineering projects and issue activity.",
    detail: "Jira integration is in our roadmap. We’ll share an update when it’s ready.",
    iconClass: "bg-sky-50 text-sky-700",
    available: false,
  },
  {
    id: "slack" as const,
    name: "Slack",
    category: "Report delivery",
    summary: "Send useful client reports and updates to your team.",
    detail: "Slack notifications and sharing are in our roadmap. Coming soon.",
    iconClass: "bg-violet-50 text-violet-700",
    available: false,
  },
];

const appGroups = [
  {
    title: "Work sources",
    description: "Bring project activity into a shared client context.",
    apps: apps.filter((app) => app.category === "Work source"),
  },
  {
    title: "Report delivery",
    description: "Share client insights with your team.",
    apps: apps.filter((app) => app.category === "Report delivery"),
  },
];

export default function ConnectedAppsPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [trelloConnection, setTrelloConnection] = useState<TrelloConnectionStatus | null>(null);
  const [githubConnection, setGithubConnection] = useState<GithubConnectionStatus | null>(null);
  const [selectedApp, setSelectedApp] = useState<AppId | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadConnectionStatus = useCallback(async (workspace: Workspace) => {
    workspaceStore.setWorkspaceId(workspace.id);
    setSelectedWorkspace(workspace);
    setError("");
    try {
      const [trello, github] = await Promise.all([
        trelloService.status(workspace.id),
        githubService.status(workspace.id),
      ]);
      setTrelloConnection(trello);
      setGithubConnection(github);
    } catch {
      setTrelloConnection(null);
      setGithubConnection(null);
      setError("Could not check app connections. Please try again.");
    }
  }, []);

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
        await loadConnectionStatus(workspace);
      }
    } catch {
      dispatch(clearSession());
      workspaceStore.clear();
      router.replace("/login");
    } finally {
      setLoading(false);
    }
  }, [dispatch, loadConnectionStatus, router]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selectedApp) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setSelectedApp(null);
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedApp]);

  async function logout() {
    try {
      await authService.logout();
      dispatch(clearSession());
      router.replace("/login");
    } catch {
      setError("Could not sign out. Please retry.");
    }
  }

  const selectedAppDetails = apps.find((app) => app.id === selectedApp);
  const trelloIsConnected = trelloConnection?.connected ?? false;
  const githubIsConnected = githubConnection?.connected ?? false;

  return (
    <DashboardTemplate
      sidebar={
        <Sidebar
          user={user}
          workspaces={workspaces}
          selectedId={selectedWorkspace?.id ?? null}
          onSelectWorkspace={(workspace) => void loadConnectionStatus(workspace)}
          onLogout={() => void logout()}
        />
      }
    >
      <div className="mx-auto w-full max-w-6xl space-y-8 pb-10">
        <header className="border-b border-zinc-200 pb-6">
          <p className="text-sm font-medium text-indigo-600">
            {selectedWorkspace?.name ?? "Workspace"} <span className="px-1 text-zinc-300">/</span> Workspace
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-zinc-950">Connected Apps</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-500">
            Make this workspace the home for a client’s work. Connect project tools to build shared context, then deliver useful reports to your team.
          </p>
        </header>

        {error ? (
          <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div role="status" className="rounded-2xl border border-zinc-200 bg-white p-6 text-sm text-zinc-500">
            Loading your connected apps…
          </div>
        ) : !selectedWorkspace ? (
          <div className="rounded-2xl border border-dashed border-zinc-300 bg-white px-6 py-12 text-center">
            <h2 className="text-lg font-semibold text-zinc-900">Create a workspace to connect apps</h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-zinc-500">
              Apps are connected to a workspace. Create or choose a workspace from the sidebar to continue.
            </p>
          </div>
        ) : (
          <>
            <div className="space-y-8">
              {appGroups.map((group, groupIndex) => (
                <section key={group.title} aria-labelledby={`app-group-${groupIndex}`}>
                  <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
                    <div>
                      <h2 id={`app-group-${groupIndex}`} className="text-lg font-semibold text-zinc-950">
                        {group.title}
                      </h2>
                      <p className="mt-1 text-sm text-zinc-500">{group.description}</p>
                    </div>
                    {groupIndex === 0 ? (
                      <span className="rounded-full bg-zinc-100 px-3 py-1 text-xs font-medium text-zinc-600">
                        2 available · 1 coming soon
                      </span>
                    ) : null}
                  </div>

                  <div className={`grid gap-4 ${group.apps.length > 1 ? "lg:grid-cols-3" : "max-w-md"}`}>
                    {group.apps.map(({ id, name, summary, iconClass, available }) => {
                  const connected = (id === "trello" && trelloIsConnected) ||
                    (id === "github" && githubIsConnected);
                  const clickable = available && !loading;

                  return (
                    <button
                      key={id}
                      type="button"
                      disabled={!clickable}
                      aria-label={`${name}${connected ? ", connected" : available ? ", connect app" : ", coming soon"}`}
                      onClick={() => clickable && setSelectedApp(id)}
                      className={`group relative flex min-h-56 flex-col rounded-2xl border bg-white p-5 text-left shadow-sm transition ${
                        available
                          ? "border-zinc-200 hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-indigo-100"
                          : "cursor-default border-zinc-200/80"
                      }`}
                    >
                      <div className="flex w-full items-start justify-between gap-3">
                        <span className={`flex h-12 w-12 items-center justify-center rounded-2xl ${iconClass}`}>
                          <IntegrationLogo app={id} className="h-6 w-6" />
                        </span>
                        {connected ? (
                          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                            <Check className="h-3.5 w-3.5" />
                            Connected
                          </span>
                        ) : available ? (
                          <span className="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700">
                            Available
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">
                            <Clock3 className="h-3.5 w-3.5" />
                            Coming soon
                          </span>
                        )}
                      </div>
                      <h3 className="mt-5 text-base font-semibold text-zinc-950">{name}</h3>
                      <p className="mt-1 text-sm leading-5 text-zinc-500">{summary}</p>
                      <span className={`mt-auto inline-flex items-center gap-2 pt-5 text-sm font-semibold ${
                        available ? "text-indigo-700" : "text-zinc-400"
                      }`}>
                        {connected ? "View settings" : available ? "View details" : "Not available yet"}
                        {available ? (
                          <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                        ) : null}
                      </span>
                    </button>
                    );
                    })}
                  </div>
                </section>
              ))}
            </div>

            <aside className="flex items-start gap-3 rounded-2xl border border-zinc-200 bg-white p-5">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-700">
                <GitBranch className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-zinc-900">One workspace. A clearer picture of every client.</h2>
                <p className="mt-1 text-sm leading-5 text-zinc-500">
                  DeepClient is designed to relate project plans to development activity, turn that shared context into traceable insights, and deliver reports through your team’s tools. Jira and Slack integrations are coming soon.
                </p>
              </div>
            </aside>
          </>
        )}
      </div>

      {selectedAppDetails ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/40 p-4 backdrop-blur-[2px]"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setSelectedApp(null);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="app-dialog-title"
            className="w-full max-w-md overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl"
          >
            <div className="flex items-start justify-between border-b border-zinc-100 p-5">
              <div className="flex items-center gap-3">
                <span className={`flex h-12 w-12 items-center justify-center rounded-2xl ${
                  selectedAppDetails.iconClass
                }`}>
                  <IntegrationLogo app={selectedAppDetails.id} className="h-6 w-6" />
                </span>
                <div>
                  <h2 id="app-dialog-title" className="text-lg font-semibold text-zinc-950">
                    {selectedAppDetails.name}
                  </h2>
                  <p className="text-sm text-zinc-500">
                    {selectedApp === "github" && githubIsConnected
                      ? `Connected as @${githubConnection?.username}`
                      : selectedApp === "trello" && trelloIsConnected
                        ? `Connected as ${trelloConnection?.username}`
                        : "Workspace integration"}
                  </p>
                </div>
              </div>
              <button
                type="button"
                aria-label="Close app details"
                onClick={() => setSelectedApp(null)}
                className="flex h-9 w-9 items-center justify-center rounded-lg text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="p-5">
              <p className="text-sm leading-6 text-zinc-600">{selectedAppDetails.detail}</p>
              {selectedAppDetails.id === "trello" || selectedAppDetails.id === "github" ? (
                <div className="mt-4 flex items-start gap-2.5 rounded-xl bg-zinc-50 p-3 text-xs leading-5 text-zinc-500">
                  <Layers3 className="mt-0.5 h-4 w-4 shrink-0 text-zinc-400" />
                  <p>
                    {selectedAppDetails.id === "trello"
                      ? "Choose which boards to sync and manage client mappings from Trello settings."
                      : "Choose repositories, connect them to workspace clients, and sync commit history from GitHub settings."}
                  </p>
                </div>
              ) : null}
            </div>
            <div className="flex flex-col-reverse gap-2 border-t border-zinc-100 bg-zinc-50 p-4 sm:flex-row sm:justify-end">
              <Button
                type="button"
                variant="secondary"
                className="rounded-lg"
                onClick={() => setSelectedApp(null)}
              >
                Close
              </Button>
              <Button
                type="button"
                className="gap-2 rounded-lg px-4"
                onClick={() => router.push(selectedAppDetails.id === "github" ? "/dashboard/github" : "/dashboard/trello")}
              >
                {selectedAppDetails.id === "github"
                  ? githubIsConnected ? "Open GitHub settings" : "Connect GitHub"
                  : trelloIsConnected ? "Open Trello settings" : "Connect Trello"}
                <ExternalLink className="h-4 w-4" />
              </Button>
            </div>
          </section>
        </div>
      ) : null}
    </DashboardTemplate>
  );
}
