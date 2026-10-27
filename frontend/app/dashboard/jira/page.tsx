"use client";

import {
  CheckCircle2,
  Circle,
  ExternalLink,
  LoaderCircle,
  RefreshCw,
  Save,
  ShieldCheck,
  Unplug,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/atoms/Button";
import { IntegrationLogo } from "@/components/atoms/IntegrationLogo";
import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { clearSession, setAuthenticatedUser } from "@/lib/authSlice";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { workspaceStore } from "@/lib/storage";
import type { JiraConnectionStatus, JiraProject, JiraProviderAccount, Workspace } from "@/lib/types";
import { authService } from "@/services/AuthService";
import { jiraService } from "@/services/JiraService";
import { workspaceService } from "@/services/WorkspaceService";

export default function JiraSettingsPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [connection, setConnection] = useState<JiraConnectionStatus | null>(null);
  const [accounts, setAccounts] = useState<JiraProviderAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const [projects, setProjects] = useState<JiraProject[]>([]);
  const [savedProjects, setSavedProjects] = useState<Record<string, boolean>>({});
  const [savedClientIds, setSavedClientIds] = useState<Record<string, string | null>>({});
  const [clients, setClients] = useState<Array<{ id: string; name: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [linking, setLinking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadWorkspace = useCallback(async (workspace: Workspace) => {
    workspaceStore.setWorkspaceId(workspace.id);
    setSelectedWorkspace(workspace);
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const [status, accountList] = await Promise.all([
        jiraService.status(workspace.id),
        jiraService.accounts(workspace.id),
      ]);
      setConnection(status);
      setAccounts(accountList);
      setSelectedAccountId(
        status.account_id && accountList.some((account) => account.id === status.account_id)
          ? status.account_id
          : accountList[0]?.id ?? "",
      );
      if (status.connected) {
        const [projectList, clientList] = await Promise.all([
          jiraService.projects(workspace.id),
          jiraService.clients(workspace.id),
        ]);
        setProjects(projectList);
        setClients(clientList);
        setSavedProjects(
          Object.fromEntries(projectList.map((project) => [project.id, project.included])),
        );
        setSavedClientIds(
          Object.fromEntries(projectList.map((project) => [project.id, project.client_id])),
        );
      } else {
        setProjects([]);
        setSavedProjects({});
        setSavedClientIds({});
        setClients([]);
      }
    } catch {
      setConnection(null);
      setAccounts([]);
      setProjects([]);
      setSavedProjects({});
      setSavedClientIds({});
      setClients([]);
      setError("Could not load Jira settings. Check the connection and retry.");
    } finally {
      setLoading(false);
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
      if (workspace) await loadWorkspace(workspace);
      else setLoading(false);

      const params = new URLSearchParams(window.location.search);
      if (params.get("connected") === "1") setNotice("Jira is connected. Choose projects to include.");
      if (params.get("error") === "jira") setError("Jira connection failed. Please try again.");
    } catch {
      dispatch(clearSession());
      workspaceStore.clear();
      router.replace("/login");
    }
  }, [dispatch, loadWorkspace, router]);

  useEffect(() => {
    void load();
  }, [load]);

  async function connectJira() {
    if (!selectedWorkspace) return;
    setError("");
    try {
      window.sessionStorage.setItem("jira.oauth_workspace_id", selectedWorkspace.id);
      window.location.assign(await jiraService.authorizationUrl(selectedWorkspace.id));
    } catch {
      window.sessionStorage.removeItem("jira.oauth_workspace_id");
      setError("Could not start Jira authorization. Check Jira OAuth settings in .env.");
    }
  }

  async function reuseJiraAccount() {
    if (!selectedWorkspace || !selectedAccountId) return;
    setLinking(true);
    setError("");
    try {
      await jiraService.linkAccount(selectedAccountId, selectedWorkspace.id);
      await loadWorkspace(selectedWorkspace);
      setNotice("Jira account linked. Select projects for this workspace.");
    } catch {
      setError("Could not link this Jira account. Disconnect the current account first if you want to switch.");
    } finally {
      setLinking(false);
    }
  }

  async function disconnectJira() {
    if (!selectedWorkspace) return;
    setSaving(true);
    setError("");
    try {
      await jiraService.disconnect(selectedWorkspace.id);
      await loadWorkspace(selectedWorkspace);
      setNotice("Jira was disconnected from this workspace.");
    } catch {
      setError("Could not disconnect Jira. Please retry.");
    } finally {
      setSaving(false);
    }
  }

  async function saveProjects() {
    if (!selectedWorkspace) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const selections = projects.map(({ id, client_id }) => ({
        project_id: id,
        included: savedProjects[id] ?? false,
        client_id,
      }));
      const updated = await jiraService.saveProjects(selections, selectedWorkspace.id);
      setProjects(updated);
      setSavedProjects(Object.fromEntries(updated.map((project) => [project.id, project.included])));
      setSavedClientIds(Object.fromEntries(updated.map((project) => [project.id, project.client_id])));
      setNotice("Project selections saved.");
    } catch {
      setError("Could not save project selections. Please retry.");
    } finally {
      setSaving(false);
    }
  }

  async function refreshProjects() {
    if (!selectedWorkspace) return;
    setSaving(true);
    setError("");
    try {
      const updated = await jiraService.projects(selectedWorkspace.id);
      setProjects(updated);
      setSavedProjects(Object.fromEntries(updated.map((project) => [project.id, project.included])));
      setSavedClientIds(Object.fromEntries(updated.map((project) => [project.id, project.client_id])));
      setNotice("Project list refreshed from Jira.");
    } catch {
      setError("Could not refresh projects from Jira. Check the account permissions and retry.");
    } finally {
      setSaving(false);
    }
  }

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

  const selectionChanged = projects.some(
    (project) =>
      (savedProjects[project.id] ?? false) !== project.included ||
      (savedClientIds[project.id] ?? null) !== project.client_id,
  );
  const includedCount = projects.filter((project) => savedProjects[project.id]).length;

  return (
    <DashboardTemplate
      sidebar={
        <Sidebar
          user={user}
          workspaces={workspaces}
          selectedId={selectedWorkspace?.id ?? null}
          onSelectWorkspace={(workspace) => void loadWorkspace(workspace)}
          onLogout={() => void logout()}
        />
      }
    >
      <div className="mx-auto w-full max-w-5xl space-y-7 pb-10">
        <header className="flex flex-col gap-4 border-b border-zinc-200 pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-medium text-indigo-600">
              {selectedWorkspace?.name ?? "Workspace"} <span className="px-1 text-zinc-300">/</span> Jira
            </p>
            <h1 className="mt-1 flex items-center gap-3 text-3xl font-semibold tracking-tight text-zinc-950">
              <IntegrationLogo app="jira" className="h-7 w-7" />
              Jira settings
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-500">
              Link an Atlassian Jira Cloud account, select engineering projects for this workspace, and connect each project to a client.
            </p>
          </div>
        </header>

        {error ? <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</div> : null}
        {notice ? <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</div> : null}

        {loading ? (
          <div role="status" className="rounded-2xl border border-zinc-200 bg-white p-6 text-sm text-zinc-500">
            Loading Jira settings…
          </div>
        ) : !selectedWorkspace ? (
          <div className="rounded-2xl border border-dashed border-zinc-300 bg-white p-8 text-center">
            <h2 className="text-lg font-semibold text-zinc-950">Create a workspace first</h2>
            <p className="mt-2 text-sm text-zinc-500">Jira accounts and project selections are managed per workspace.</p>
          </div>
        ) : !connection?.connected ? (
          <section className="rounded-2xl border border-zinc-200 bg-white p-6 sm:p-8">
            <div className="flex items-start gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-sky-50">
                <IntegrationLogo app="jira" className="h-6 w-6" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-zinc-950">Connect Jira to {selectedWorkspace.name}</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-500">
                  Authorize access to Jira Cloud sites you have access to. You can reuse this account in other workspaces and choose different projects there.
                </p>
                <div className="mt-4 flex flex-wrap gap-3">
                  <Button type="button" className="gap-2 rounded-lg" onClick={() => void connectJira()}>
                    <ShieldCheck className="h-4 w-4" /> Connect Jira
                  </Button>
                  {accounts.length ? (
                    <div className="flex flex-wrap gap-2">
                      <select
                        aria-label="Existing Jira account"
                        value={selectedAccountId}
                        onChange={(event) => setSelectedAccountId(event.target.value)}
                        className="min-h-10 rounded-lg border border-zinc-200 bg-white px-3 text-sm"
                      >
                        {accounts.map((account) => (
                          <option key={account.id} value={account.id}>
                            {account.username}
                          </option>
                        ))}
                      </select>
                      <Button
                        type="button"
                        variant="secondary"
                        className="rounded-lg"
                        disabled={!selectedAccountId || linking}
                        onClick={() => void reuseJiraAccount()}
                      >
                        {linking ? "Linking…" : "Reuse account"}
                      </Button>
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          </section>
        ) : (
          <>
            <section className="flex flex-col gap-3 rounded-2xl border border-zinc-200 bg-white p-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                <div>
                  <p className="text-sm font-semibold text-zinc-950">
                    Connected as {connection.username}
                    {connection.site_name ? ` (${connection.site_name})` : ""}
                  </p>
                  <p className="mt-0.5 text-xs text-zinc-500">
                    {connection.site_url ? `${connection.site_url} · ` : ""}
                    Project choices and synced issues are specific to this workspace.
                  </p>
                </div>
              </div>
              <Button
                type="button"
                variant="secondary"
                className="gap-2 rounded-lg"
                disabled={saving}
                onClick={() => void disconnectJira()}
              >
                <Unplug className="h-4 w-4" /> Disconnect workspace
              </Button>
            </section>

            <section className="overflow-hidden rounded-2xl border border-zinc-200 bg-white">
              <div className="flex flex-col gap-3 border-b border-zinc-100 p-5 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-zinc-950">Choose Jira projects</h2>
                  <p className="mt-1 text-sm text-zinc-500">
                    Select engineering projects to include in this workspace and map them to client accounts.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    className="gap-2 rounded-lg"
                    disabled={saving}
                    onClick={() => void refreshProjects()}
                  >
                    {saving ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                    Refresh list
                  </Button>
                  <Button
                    type="button"
                    className="gap-2 rounded-lg"
                    disabled={saving || !selectionChanged}
                    onClick={() => void saveProjects()}
                  >
                    {saving ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    {saving ? "Saving…" : "Save selection"}
                  </Button>
                </div>
              </div>

              {projects.length ? (
                <ul className="divide-y divide-zinc-100">
                  {projects.map((project) => (
                    <li
                      key={project.id}
                      className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5"
                    >
                      <label className="flex min-w-0 cursor-pointer items-start gap-3">
                        <input
                          type="checkbox"
                          checked={savedProjects[project.id] ?? false}
                          onChange={(event) =>
                            setSavedProjects((current) => ({
                              ...current,
                              [project.id]: event.target.checked,
                            }))
                          }
                          className="mt-1 h-4 w-4 rounded border-zinc-300 text-indigo-600 focus:ring-indigo-500"
                          aria-label={`Include ${project.name}`}
                        />
                        <div className="flex items-center gap-2.5">
                          {project.avatar_url ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={project.avatar_url}
                              alt=""
                              className="h-7 w-7 rounded-md object-contain"
                            />
                          ) : (
                            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-sky-100 text-xs font-bold text-sky-700">
                              {project.key.slice(0, 3)}
                            </span>
                          )}
                          <span className="min-w-0">
                            <span className="flex flex-wrap items-center gap-2 text-sm font-semibold text-zinc-900">
                              {project.name}
                              <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] font-semibold text-zinc-600">
                                {project.key}
                              </span>
                            </span>
                            <span className="mt-0.5 block text-xs text-zinc-500">
                              {project.sync_status.replaceAll("_", " ")}
                              {project.last_synced_at
                                ? ` · synced ${new Date(project.last_synced_at).toLocaleString()}`
                                : ""}
                              {project.sync_error ? ` · ${project.sync_error}` : ""}
                            </span>
                          </span>
                        </div>
                      </label>
                      <div className="flex items-center gap-2 pl-7 sm:pl-0">
                        <label htmlFor={`client-${project.id}`} className="sr-only">
                          Associate {project.name} with a client
                        </label>
                        <select
                          id={`client-${project.id}`}
                          value={project.client_id ?? ""}
                          onChange={(event) =>
                            setProjects((current) =>
                              current.map((item) =>
                                item.id === project.id
                                  ? { ...item, client_id: event.target.value || null }
                                  : item,
                              ),
                            )
                          }
                          className="min-h-9 max-w-52 rounded-lg border border-zinc-200 bg-white px-2 text-xs text-zinc-700"
                        >
                          <option value="">No client association</option>
                          {clients.map((client) => (
                            <option key={client.id} value={client.id}>
                              {client.name}
                            </option>
                          ))}
                        </select>
                        {connection.site_url ? (
                          <a
                            href={`${connection.site_url}/jira/software/projects/${project.key}/boards`}
                            target="_blank"
                            rel="noreferrer"
                            aria-label={`Open ${project.name} in Jira`}
                            className="rounded-lg p-2 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
                          >
                            <ExternalLink className="h-4 w-4" />
                          </a>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="p-8 text-center text-sm text-zinc-500">
                  <Circle className="mx-auto h-8 w-8 text-zinc-300" />
                  <p className="mt-3">No projects found in this Jira site.</p>
                </div>
              )}
              <div className="border-t border-zinc-100 bg-zinc-50 px-5 py-3 text-xs text-zinc-500">
                {selectionChanged
                  ? "You have unsaved project changes."
                  : `${includedCount} ${includedCount === 1 ? "project" : "projects"} selected.`}
              </div>
            </section>

            <p className="flex items-start gap-2 rounded-xl bg-sky-50 p-4 text-xs leading-5 text-sky-900">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
              Atlassian OAuth 2.0 (3LO) uses granular scopes (<code>read:jira-work</code>, <code>read:jira-user</code>, <code>offline_access</code>). DeepClient only reads project metadata and issue tracking details; tokens are securely encrypted at rest.
            </p>
          </>
        )}
      </div>
    </DashboardTemplate>
  );
}
