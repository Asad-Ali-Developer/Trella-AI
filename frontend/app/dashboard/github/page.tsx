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
import type { GithubConnectionStatus, GithubProviderAccount, GithubRepository, Workspace } from "@/lib/types";
import { authService } from "@/services/AuthService";
import { githubService } from "@/services/GithubService";
import { workspaceService } from "@/services/WorkspaceService";

export default function GithubSettingsPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [connection, setConnection] = useState<GithubConnectionStatus | null>(null);
  const [accounts, setAccounts] = useState<GithubProviderAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const [repositories, setRepositories] = useState<GithubRepository[]>([]);
  const [savedRepositories, setSavedRepositories] = useState<Record<string, boolean>>({});
  const [savedClientIds, setSavedClientIds] = useState<Record<string, string | null>>({});
  const [clients, setClients] = useState<Array<{ id: string; name: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
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
        githubService.status(workspace.id),
        githubService.accounts(workspace.id),
      ]);
      setConnection(status);
      setAccounts(accountList);
      setSelectedAccountId(
        status.account_id && accountList.some((account) => account.id === status.account_id)
          ? status.account_id
          : accountList[0]?.id ?? "",
      );
      if (status.connected) {
        const [repoList, clientList] = await Promise.all([
          githubService.refreshRepositories(workspace.id),
          githubService.clients(workspace.id),
        ]);
        setRepositories(repoList);
        setClients(clientList);
        setSavedRepositories(
          Object.fromEntries(repoList.map((repo) => [repo.id, repo.included])),
        );
        setSavedClientIds(Object.fromEntries(repoList.map((repo) => [repo.id, repo.client_id])));
      } else {
        setRepositories([]);
        setSavedRepositories({});
        setSavedClientIds({});
        setClients([]);
      }
    } catch {
      setConnection(null);
      setAccounts([]);
      setRepositories([]);
      setSavedRepositories({});
      setClients([]);
      setError("Could not load GitHub settings. Check the connection and retry.");
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
      if (params.get("connected") === "1") setNotice("GitHub is connected. Choose repositories to include.");
      if (params.get("error") === "github") setError("GitHub connection failed. Please try again.");
    } catch {
      dispatch(clearSession());
      workspaceStore.clear();
      router.replace("/login");
    }
  }, [dispatch, loadWorkspace, router]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!repositories.some((repository) => repository.sync_status === "running")) return;
    const timer = window.setInterval(() => {
      if (selectedWorkspace) {
        void githubService.repositories(selectedWorkspace.id).then((updated) => {
          setRepositories(updated);
        }).catch(() => setError("Could not refresh GitHub sync status."));
      }
    }, 5000);
    return () => window.clearInterval(timer);
  }, [repositories, selectedWorkspace]);

  async function connectGithub() {
    if (!selectedWorkspace) return;
    setError("");
    try {
      window.sessionStorage.setItem("github.oauth_workspace_id", selectedWorkspace.id);
      window.location.assign(await githubService.authorizationUrl(selectedWorkspace.id));
    } catch {
      window.sessionStorage.removeItem("github.oauth_workspace_id");
      setError("Could not start GitHub authorization. Check GitHub OAuth settings.");
    }
  }

  async function reuseGithubAccount() {
    if (!selectedWorkspace || !selectedAccountId) return;
    setLinking(true);
    setError("");
    try {
      await githubService.linkAccount(selectedAccountId, selectedWorkspace.id);
      await loadWorkspace(selectedWorkspace);
      setNotice("GitHub account linked. Select repositories for this workspace.");
    } catch {
      setError("Could not link this GitHub account. Disconnect the current account first if you want to switch.");
    } finally {
      setLinking(false);
    }
  }

  async function disconnectGithub() {
    if (!selectedWorkspace) return;
    setSaving(true);
    setError("");
    try {
      await githubService.disconnect(selectedWorkspace.id);
      await loadWorkspace(selectedWorkspace);
      setNotice("GitHub was disconnected from this workspace.");
    } catch {
      setError("Could not disconnect GitHub. Please retry.");
    } finally {
      setSaving(false);
    }
  }

  async function saveRepositories() {
    if (!selectedWorkspace) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await githubService.saveRepositories(
        repositories.map(({ id, client_id }) => ({
          id,
          included: savedRepositories[id] ?? false,
          client_id,
        })),
        selectedWorkspace.id,
      );
      const updated = await githubService.repositories(selectedWorkspace.id);
      setRepositories(updated);
      setSavedRepositories(Object.fromEntries(updated.map((repo) => [repo.id, repo.included])));
      setSavedClientIds(Object.fromEntries(updated.map((repo) => [repo.id, repo.client_id])));
      setNotice("Repository selections saved. Included repositories are queued for sync.");
    } catch {
      setError("Could not save repository selections. Please retry.");
    } finally {
      setSaving(false);
    }
  }

  async function refreshRepositories() {
    if (!selectedWorkspace) return;
    setSaving(true);
    setError("");
    try {
      const updated = await githubService.refreshRepositories(selectedWorkspace.id);
      setRepositories(updated);
      setSavedRepositories(Object.fromEntries(updated.map((repo) => [repo.id, repo.included])));
      setSavedClientIds(Object.fromEntries(updated.map((repo) => [repo.id, repo.client_id])));
      setNotice("Repository list refreshed from GitHub.");
    } catch {
      setError("Could not refresh repositories from GitHub. Check the account permissions and retry.");
    } finally {
      setSaving(false);
    }
  }

  async function syncRepositories() {
    if (!selectedWorkspace) return;
    setSyncing(true);
    setError("");
    setNotice("");
    try {
      const scheduled = await githubService.sync(selectedWorkspace.id);
      setNotice(`${scheduled} selected ${scheduled === 1 ? "repository is" : "repositories are"} queued for sync.`);
      setRepositories(await githubService.repositories(selectedWorkspace.id));
    } catch {
      setError("Could not start GitHub synchronization. Please retry.");
    } finally {
      setSyncing(false);
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

  const selectionChanged = repositories.some(
    (repo) =>
      (savedRepositories[repo.id] ?? false) !== repo.included ||
      (savedClientIds[repo.id] ?? null) !== repo.client_id,
  );
  const includedCount = repositories.filter((repo) => savedRepositories[repo.id]).length;

  return (
    <DashboardTemplate sidebar={
      <Sidebar
        user={user}
        workspaces={workspaces}
        selectedId={selectedWorkspace?.id ?? null}
        onSelectWorkspace={(workspace) => void loadWorkspace(workspace)}
        onLogout={() => void logout()}
      />
    }>
      <div className="mx-auto w-full max-w-5xl space-y-7 pb-10">
        <header className="flex flex-col gap-4 border-b border-zinc-200 pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-medium text-indigo-600">
              {selectedWorkspace?.name ?? "Workspace"} <span className="px-1 text-zinc-300">/</span> GitHub
            </p>
            <h1 className="mt-1 flex items-center gap-3 text-3xl font-semibold tracking-tight text-zinc-950">
              <IntegrationLogo app="github" className="h-7 w-7" />
              GitHub settings
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-500">
              Link a GitHub account, select repositories for this workspace, and connect each repository to a client.
              Only recent commit metadata is synchronized; DeepClient does not clone code or write to GitHub.
            </p>
          </div>
          {connection?.connected ? (
            <Button type="button" variant="secondary" className="gap-2 rounded-lg" disabled={syncing || saving || !includedCount} onClick={() => void syncRepositories()}>
              {syncing ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              {syncing ? "Queueing sync…" : "Sync selected repos"}
            </Button>
          ) : null}
        </header>

        {error ? <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</div> : null}
        {notice ? <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</div> : null}

        {loading ? (
          <div role="status" className="rounded-2xl border border-zinc-200 bg-white p-6 text-sm text-zinc-500">Loading GitHub settings…</div>
        ) : !selectedWorkspace ? (
          <div className="rounded-2xl border border-dashed border-zinc-300 bg-white p-8 text-center">
            <h2 className="text-lg font-semibold text-zinc-950">Create a workspace first</h2>
            <p className="mt-2 text-sm text-zinc-500">GitHub accounts and repository selections are managed per workspace.</p>
          </div>
        ) : !connection?.connected ? (
          <section className="rounded-2xl border border-zinc-200 bg-white p-6 sm:p-8">
            <div className="flex items-start gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-zinc-100">
                <IntegrationLogo app="github" className="h-6 w-6" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-zinc-950">Connect GitHub to {selectedWorkspace.name}</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-500">
                  Authorize access to repositories you can already access. You can reuse this account in other workspaces and choose different repositories there.
                </p>
                <div className="mt-4 flex flex-wrap gap-3">
                  <Button type="button" className="gap-2 rounded-lg" onClick={() => void connectGithub()}>
                    <ShieldCheck className="h-4 w-4" /> Connect GitHub
                  </Button>
                  {accounts.length ? (
                    <div className="flex flex-wrap gap-2">
                      <select aria-label="Existing GitHub account" value={selectedAccountId} onChange={(event) => setSelectedAccountId(event.target.value)} className="min-h-10 rounded-lg border border-zinc-200 bg-white px-3 text-sm">
                        {accounts.map((account) => <option key={account.id} value={account.id}>@{account.username}</option>)}
                      </select>
                      <Button type="button" variant="secondary" className="rounded-lg" disabled={!selectedAccountId || linking} onClick={() => void reuseGithubAccount()}>
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
                  <p className="text-sm font-semibold text-zinc-950">Connected as @{connection.username}</p>
                  <p className="mt-0.5 text-xs text-zinc-500">Repository choices and synced commits are specific to this workspace.</p>
                </div>
              </div>
              <Button type="button" variant="secondary" className="gap-2 rounded-lg" disabled={saving} onClick={() => void disconnectGithub()}>
                <Unplug className="h-4 w-4" /> Disconnect workspace
              </Button>
            </section>
            <section className="overflow-hidden rounded-2xl border border-zinc-200 bg-white">
              <div className="flex flex-col gap-3 border-b border-zinc-100 p-5 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-zinc-950">Choose repositories</h2>
                  <p className="mt-1 text-sm text-zinc-500">Select up to 500 recent commits per repository for workspace context. Private status is shown for clarity.</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="secondary" className="gap-2 rounded-lg" disabled={saving} onClick={() => void refreshRepositories()}>
                    {saving ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                    Refresh list
                  </Button>
                  <Button type="button" className="gap-2 rounded-lg" disabled={saving || !selectionChanged} onClick={() => void saveRepositories()}>
                    {saving ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    {saving ? "Saving…" : "Save selection"}
                  </Button>
                </div>
              </div>
              {repositories.length ? (
                <ul className="divide-y divide-zinc-100">
                  {repositories.map((repository) => (
                    <li key={repository.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
                      <label className="flex min-w-0 cursor-pointer items-start gap-3">
                        <input
                          type="checkbox"
                          checked={savedRepositories[repository.id] ?? false}
                          onChange={(event) => setSavedRepositories((current) => ({ ...current, [repository.id]: event.target.checked }))}
                          className="mt-1 h-4 w-4 rounded border-zinc-300 text-indigo-600 focus:ring-indigo-500"
                          aria-label={`Include ${repository.full_name}`}
                        />
                        <span className="min-w-0">
                          <span className="flex flex-wrap items-center gap-2 text-sm font-semibold text-zinc-900">
                            {repository.full_name}
                            {repository.private ? <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-800">Private</span> : null}
                          </span>
                          <span className="mt-1 block text-xs text-zinc-500">{repository.description || `Default branch: ${repository.default_branch}`}</span>
                          <span className="mt-1 block text-xs text-zinc-500">
                            {repository.sync_status.replaceAll("_", " ")}
                            {repository.last_synced_at ? ` · synced ${new Date(repository.last_synced_at).toLocaleString()}` : ""}
                            {repository.sync_error ? ` · ${repository.sync_error}` : ""}
                          </span>
                        </span>
                      </label>
                      <div className="flex items-center gap-2 pl-7 sm:pl-0">
                        <label htmlFor={`client-${repository.id}`} className="sr-only">Associate {repository.full_name} with a client</label>
                        <select
                          id={`client-${repository.id}`}
                          value={repository.client_id ?? ""}
                          onChange={(event) => setRepositories((current) => current.map((item) => item.id === repository.id ? { ...item, client_id: event.target.value || null } : item))}
                          className="min-h-9 max-w-52 rounded-lg border border-zinc-200 bg-white px-2 text-xs text-zinc-700"
                        >
                          <option value="">No client association</option>
                          {clients.map((client) => <option key={client.id} value={client.id}>{client.name}</option>)}
                        </select>
                        <a href={repository.url} target="_blank" rel="noreferrer" aria-label={`Open ${repository.full_name} on GitHub`} className="rounded-lg p-2 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700">
                          <ExternalLink className="h-4 w-4" />
                        </a>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="p-8 text-center text-sm text-zinc-500">
                  <Circle className="mx-auto h-8 w-8 text-zinc-300" />
                  <p className="mt-3">No repositories are available to this account.</p>
                </div>
              )}
              <div className="border-t border-zinc-100 bg-zinc-50 px-5 py-3 text-xs text-zinc-500">
                {selectionChanged ? "You have unsaved repository changes." : `${includedCount} ${includedCount === 1 ? "repository" : "repositories"} selected.`}
              </div>
            </section>
            <p className="flex items-start gap-2 rounded-xl bg-amber-50 p-4 text-xs leading-5 text-amber-900">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
              GitHub OAuth&apos;s <code>repo</code> scope is required to access private repositories and grants repository access to the token. DeepClient uses that token only for GitHub read requests; tokens are encrypted at rest.
            </p>
          </>
        )}
      </div>
    </DashboardTemplate>
  );
}
