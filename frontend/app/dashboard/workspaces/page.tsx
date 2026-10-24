"use client";

import { ArrowRight, BriefcaseBusiness, Pencil, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/atoms/Button";
import { IntegrationLogo } from "@/components/atoms/IntegrationLogo";
import { Sidebar } from "@/components/organisms/Sidebar";
import { WorkspaceCreateDrawer } from "@/components/organisms/WorkspaceCreateDrawer";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { clearSession, setAuthenticatedUser } from "@/lib/authSlice";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { workspaceStore } from "@/lib/storage";
import type { GithubConnectionStatus, TrelloConnectionStatus, Workspace } from "@/lib/types";
import { authService } from "@/services/AuthService";
import { githubService } from "@/services/GithubService";
import { trelloService } from "@/services/TrelloService";
import { workspaceService } from "@/services/WorkspaceService";

interface WorkspaceAppsStatus {
  trello: TrelloConnectionStatus | null;
  github: GithubConnectionStatus | null;
}

export default function WorkspacesPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [appsByWorkspace, setAppsByWorkspace] = useState<Record<string, WorkspaceAppsStatus>>({});
  const [loading, setLoading] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [workspaceToEdit, setWorkspaceToEdit] = useState<Workspace | null>(null);
  const [error, setError] = useState("");

  const refreshWorkspaceStatuses = useCallback(async (items: Workspace[]) => {
    const statuses = await Promise.all(
      items.map(async (workspace) => {
        const [trello, github] = await Promise.all([
          trelloService.status(workspace.id).catch(() => null),
          githubService.status(workspace.id).catch(() => null),
        ]);
        return [workspace.id, { trello, github }] as const;
      }),
    );
    setAppsByWorkspace(Object.fromEntries(statuses));
    if (statuses.some(([, status]) => status.trello === null || status.github === null)) {
      setError("Some app statuses could not be loaded. Refresh the page to try again.");
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const [currentUser, items] = await Promise.all([authService.me(), workspaceService.list()]);
      dispatch(setAuthenticatedUser(currentUser));
      setWorkspaces(items);
      const storedId = workspaceStore.getWorkspaceId();
      const active = items.find((workspace) => workspace.id === storedId) ?? items[0] ?? null;
      setSelectedWorkspace(active);
      if (active) workspaceStore.setWorkspaceId(active.id);
      await refreshWorkspaceStatuses(items);
    } catch {
      dispatch(clearSession());
      workspaceStore.clear();
      router.replace("/login");
    } finally {
      setLoading(false);
    }
  }, [dispatch, refreshWorkspaceStatuses, router]);

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

  function selectWorkspace(workspace: Workspace) {
    workspaceStore.setWorkspaceId(workspace.id);
    setSelectedWorkspace(workspace);
  }

  function handleCreated(workspace: Workspace) {
    workspaceStore.setWorkspaceId(workspace.id);
    setWorkspaces((current) => [workspace, ...current]);
    setSelectedWorkspace(workspace);
    setAppsByWorkspace((current) => ({
      ...current,
      [workspace.id]: {
        trello: { connected: false, username: null },
        github: { connected: false, username: null },
      },
    }));
    setDrawerOpen(false);
    router.push(`/dashboard/workspaces/${workspace.id}`);
  }

  function handleWorkspaceSaved(workspace: Workspace) {
    setWorkspaces((current) => current.map((item) => item.id === workspace.id ? workspace : item));
    setSelectedWorkspace((current) => current?.id === workspace.id ? workspace : current);
    setWorkspaceToEdit(null);
    setDrawerOpen(false);
  }

  return (
    <DashboardTemplate
      sidebar={
        <Sidebar
          user={user}
          workspaces={workspaces}
          selectedId={selectedWorkspace?.id ?? null}
          onSelectWorkspace={selectWorkspace}
          onLogout={() => void logout()}
        />
      }
    >
      <div className="mx-auto w-full max-w-6xl space-y-8 pb-10">
        <header className="flex flex-col gap-5 border-b border-zinc-200 pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-medium text-indigo-600">Your organization</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight text-zinc-950">Workspaces</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-500">
              Each workspace brings one client’s projects, connected tools, and insights together.
            </p>
          </div>
          <Button className="h-11 gap-2 self-start rounded-lg px-4 sm:self-auto" onClick={() => setDrawerOpen(true)}>
            <Plus className="h-4 w-4" />
            Create workspace
          </Button>
        </header>

        {error ? (
          <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <span>{error}</span>
            <button
              type="button"
              className="shrink-0 font-semibold underline underline-offset-2"
              onClick={() => void refreshWorkspaceStatuses(workspaces)}
            >
              Retry
            </button>
          </div>
        ) : null}

        {loading ? (
          <div role="status" className="rounded-2xl border border-zinc-200 bg-white p-6 text-sm text-zinc-500">
            Loading workspaces…
          </div>
        ) : workspaces.length ? (
          <section aria-label="Your workspaces" className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {workspaces.map((workspace) => {
              const appStatus = appsByWorkspace[workspace.id];
              const trelloConnected = Boolean(appStatus?.trello?.connected);
              const githubConnected = Boolean(appStatus?.github?.connected);
              const connectedCount = (trelloConnected ? 1 : 0) + (githubConnected ? 1 : 0);
              const active = selectedWorkspace?.id === workspace.id;
              return (
                <article
                  key={workspace.id}
                  className={`group flex min-h-64 flex-col rounded-2xl border bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-indigo-100 ${
                    active ? "border-indigo-200 ring-1 ring-indigo-100" : "border-zinc-200"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-50 text-indigo-700">
                      <BriefcaseBusiness className="h-5 w-5" />
                    </span>
                    {connectedCount > 0 ? (
                      <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                        {connectedCount === 1 ? "1 app connected" : `${connectedCount} apps connected`}
                      </span>
                    ) : (
                      <span className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-600">
                        No apps connected
                      </span>
                    )}
                  </div>
                  <h2 className="mt-5 truncate text-lg font-semibold text-zinc-950">
                    {workspace.role === "owner" || workspace.role === "admin" ? (
                      <button
                        type="button"
                        onClick={() => setWorkspaceToEdit(workspace)}
                        className="rounded-sm text-left hover:text-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
                        aria-label={`Edit ${workspace.name}`}
                      >
                        {workspace.name}
                        <Pencil className="ml-1.5 inline h-3.5 w-3.5 text-zinc-400 opacity-0 transition group-hover:opacity-100" />
                      </button>
                    ) : workspace.name}
                  </h2>
                  <p className="mt-1 text-sm text-zinc-500">
                    {workspace.client_name ? `Client: ${workspace.client_name}` : "Client not specified"}
                  </p>
                  <p className="mt-3 line-clamp-2 min-h-10 text-sm leading-5 text-zinc-500">
                    {workspace.description || "No workspace description added yet."}
                  </p>
                  <div className="mt-auto flex items-center justify-between border-t border-zinc-100 pt-4">
                    <div className="flex items-center gap-2">
                      {connectedCount > 0 ? (
                        <>
                          {trelloConnected ? (
                            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50" title="Trello connected">
                              <IntegrationLogo app="trello" className="h-4 w-4" />
                            </span>
                          ) : null}
                          {githubConnected ? (
                            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-100" title="GitHub connected">
                              <IntegrationLogo app="github" className="h-4 w-4" />
                            </span>
                          ) : null}
                        </>
                      ) : (
                        <span className="text-xs text-zinc-400">Connect apps to build context</span>
                      )}
                    </div>
                    <Link
                      href={`/dashboard/workspaces/${workspace.id}`}
                      onClick={() => selectWorkspace(workspace)}
                      className="inline-flex items-center gap-1.5 text-sm font-semibold text-indigo-700"
                    >
                      Workspace details
                      <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                    </Link>
                  </div>
                </article>
              );
            })}
          </section>
        ) : (
          <section className="rounded-2xl border border-dashed border-zinc-300 bg-white px-6 py-14 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-700">
              <BriefcaseBusiness className="h-6 w-6" />
            </div>
            <h2 className="mt-4 text-lg font-semibold text-zinc-950">Create your first workspace</h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-zinc-500">
              Start with one client. Add its work tools and build a shared picture of what’s happening.
            </p>
            <Button className="mt-5 gap-2 rounded-lg" onClick={() => setDrawerOpen(true)}>
              <Plus className="h-4 w-4" />
              Create workspace
            </Button>
          </section>
        )}
      </div>

      {drawerOpen ? (
        <WorkspaceCreateDrawer
          onClose={() => setDrawerOpen(false)}
          onSaved={handleCreated}
        />
      ) : null}
      {workspaceToEdit ? (
        <WorkspaceCreateDrawer
          mode="edit"
          workspace={workspaceToEdit}
          onClose={() => setWorkspaceToEdit(null)}
          onSaved={handleWorkspaceSaved}
        />
      ) : null}
    </DashboardTemplate>
  );
}
