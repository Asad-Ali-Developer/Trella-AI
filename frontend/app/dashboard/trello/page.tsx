"use client";

import {
  AlertCircle,
  Check,
  CheckCircle2,
  Circle,
  Clock3,
  ExternalLink,
  Layers3,
  ListTodo,
  LoaderCircle,
  Plus,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/atoms/Button";
import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { clearSession, setAuthenticatedUser } from "@/lib/authSlice";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { workspaceStore } from "@/lib/storage";
import type {
  TrelloBoard,
  TrelloClientMapping,
  TrelloConnectionStatus,
  TrelloMappingType,
  TrelloProviderAccount,
  Workspace,
} from "@/lib/types";
import { authService } from "@/services/AuthService";
import { trelloService } from "@/services/TrelloService";
import { workspaceService } from "@/services/WorkspaceService";

export default function TrelloSettingsPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [connection, setConnection] = useState<TrelloConnectionStatus | null>(null);
  const [accounts, setAccounts] = useState<TrelloProviderAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const [boards, setBoards] = useState<TrelloBoard[]>([]);
  const [savedBoardSelection, setSavedBoardSelection] = useState<Record<string, boolean>>({});
  const [clientMappings, setClientMappings] = useState<TrelloClientMapping[]>([]);
  const [mappingBoardId, setMappingBoardId] = useState("");
  const [mappingType, setMappingType] = useState<TrelloMappingType>("board");
  const [mappingValue, setMappingValue] = useState("");
  const [mappingClientName, setMappingClientName] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [linkingAccount, setLinkingAccount] = useState(false);
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
        trelloService.status(),
        trelloService.accounts(),
      ]);
      setConnection(status);
      setAccounts(accountList);
      setSelectedAccountId(
        status.account_id && accountList.some((account) => account.id === status.account_id)
          ? status.account_id
          : accountList[0]?.id ?? "",
      );
      const boardList = status.connected ? await trelloService.listBoards() : [];
      setBoards(boardList);
      setSavedBoardSelection(
        Object.fromEntries(boardList.map((board) => [board.id, !board.excluded])),
      );
      setClientMappings(status.connected ? await trelloService.listClientMappings() : []);
    } catch {
      setConnection(null);
      setAccounts([]);
      setSelectedAccountId("");
      setBoards([]);
      setSavedBoardSelection({});
      setClientMappings([]);
      setError("Could not load the Trello connection. Please retry.");
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
      if (workspace) {
        await loadWorkspace(workspace);
      } else {
        setLoading(false);
      }
      const params = new URLSearchParams(window.location.search);
      if (params.get("connected") === "1") {
        setNotice("Trello is connected. Choose which boards to include.");
      }
      if (params.get("error") === "trello") {
        setError("Trello connection failed. Please try again.");
      }
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
    if (!boards.some((board) => board.sync_status === "running")) return;
    const timer = window.setInterval(() => {
      void trelloService.listBoards().then(setBoards).catch(() => {
        setError("Could not refresh Trello sync status.");
      });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [boards]);

  async function connectTrello() {
    setError("");
    if (!selectedWorkspace) return;
    try {
      window.sessionStorage.setItem("trello.oauth_workspace_id", selectedWorkspace.id);
      const authorizationUrl = await trelloService.authorizationUrl();
      window.location.assign(authorizationUrl);
    } catch {
      window.sessionStorage.removeItem("trello.oauth_workspace_id");
      setError("Could not start Trello authorization. Check that Trello is configured.");
    }
  }

  async function reuseTrelloAccount() {
    if (!selectedWorkspace || !selectedAccountId) return;
    setLinkingAccount(true);
    setError("");
    try {
      await trelloService.linkAccount(selectedAccountId);
      await loadWorkspace(selectedWorkspace);
      setNotice("Trello account linked. Choose which boards to include in this workspace.");
    } catch {
      setError("Could not link this Trello account. Please retry.");
    } finally {
      setLinkingAccount(false);
    }
  }

  async function saveBoards() {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await trelloService.saveBoards(boards);
      const boardList = await trelloService.listBoards();
      setBoards(boardList);
      setSavedBoardSelection(
        Object.fromEntries(boardList.map((board) => [board.id, !board.excluded])),
      );
      setNotice("Board selections saved.");
    } catch {
      setError("Could not save board selections. Please retry.");
    } finally {
      setSaving(false);
    }
  }

  async function syncBoards() {
    setSyncing(true);
    setError("");
    try {
      await trelloService.syncBoards();
      setBoards(await trelloService.listBoards());
      setNotice("Board sync queued.");
    } catch {
      setError("Could not start Trello sync. Please retry.");
    } finally {
      setSyncing(false);
    }
  }

  async function saveMappings() {
    setSaving(true);
    setError("");
    try {
      await trelloService.saveClientMappings(
        clientMappings.map(({ board_id, mapping_type, external_ref, client_name }) => ({
          board_id,
          mapping_type,
          external_ref,
          client_name,
        })),
      );
      setClientMappings(await trelloService.listClientMappings());
      setNotice("Client mappings saved. Included boards are queued for sync.");
    } catch {
      setError("Could not save client mappings. Check the board and mapping values.");
    } finally {
      setSaving(false);
    }
  }

  function addClientMapping() {
    if (!mappingBoardId || !mappingClientName.trim()) return;
    const board = boards.find((item) => item.id === mappingBoardId);
    if (!board) return;
    setClientMappings((current) => [
      ...current,
      {
        board_id: board.id,
        board_name: board.name,
        mapping_type: mappingType,
        external_ref: mappingType === "board" ? board.id : mappingValue.trim(),
        client_name: mappingClientName.trim(),
      },
    ]);
    setMappingValue("");
    setMappingClientName("");
  }

  function updateBoard(id: string, excluded: boolean) {
    setBoards((current) => current.map((board) => (board.id === id ? { ...board, excluded } : board)));
  }

  function logout() {
    void authService
      .logout()
      .then(() => {
        dispatch(clearSession());
        router.replace("/login");
      })
      .catch(() => setError("Could not sign out. Please retry."));
  }

  const includedBoards = boards.filter((board) => !board.excluded);
  const boardSelectionChanged = boards.some(
    (board) => savedBoardSelection[board.id] !== !board.excluded,
  );

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
      <div className="mx-auto w-full max-w-6xl space-y-7 pb-10">
        <header className="flex flex-col gap-5 border-b border-zinc-200 pb-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm font-medium text-indigo-600">
              {selectedWorkspace?.name ?? "Workspace"} <span className="px-1 text-zinc-300">/</span> Integrations
            </p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight text-zinc-950">Trello</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-500">
              Choose the boards to bring into DeepClient, then match them to your clients.
            </p>
          </div>
          {connection?.connected ? (
            <div className="flex w-fit items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white text-emerald-700">
                <Check className="h-5 w-5" />
              </span>
              <div>
                <p className="text-sm font-semibold text-emerald-900">Trello connected</p>
                <p className="text-xs text-emerald-800">Account: {connection.username}</p>
              </div>
            </div>
          ) : null}
        </header>

        {error ? (
          <div role="alert" className="flex items-start gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
            <p>{error}</p>
          </div>
        ) : null}
        {notice ? (
          <div role="status" className="flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0" />
            <p>{notice}</p>
          </div>
        ) : null}

        {!selectedWorkspace ? (
          <section className="rounded-2xl border border-dashed border-zinc-300 bg-white px-6 py-12 text-center">
            <h2 className="text-lg font-semibold text-zinc-900">Create a workspace to get started</h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-zinc-500">
              Trello connections and board selections are saved to a workspace. Create or choose one from the sidebar.
            </p>
          </section>
        ) : loading ? (
          <div className="flex items-center gap-3 rounded-2xl border border-zinc-200 bg-white px-6 py-8 text-sm text-zinc-500" role="status">
            <LoaderCircle className="h-5 w-5 animate-spin text-indigo-600" />
            Loading your Trello workspace…
          </div>
        ) : !connection?.connected ? (
          <section className="overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm">
            <div className="grid gap-8 p-6 sm:p-9 md:grid-cols-[1fr_auto] md:items-center">
              <div>
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-700">
                  <ShieldCheck className="h-6 w-6" />
                </div>
                <h2 className="mt-5 text-xl font-semibold tracking-tight text-zinc-950">Connect your Trello account</h2>
                <p className="mt-2 max-w-xl text-sm leading-6 text-zinc-500">
                  Use an account you have already connected, or authorize a different account. Each workspace keeps its own board selections.
                </p>
                <p className="mt-2 max-w-xl text-xs leading-5 text-zinc-500">
                  Your saved Trello accounts can be reused across your workspaces without authorizing again.
                </p>
                {accounts.length ? (
                  <div className="mt-5 max-w-lg space-y-4">
                    <div className="space-y-2">
                      <label htmlFor="trello-account" className="text-sm font-medium text-zinc-800">
                        Use an existing account
                      </label>
                      <div className="flex flex-col gap-2 sm:flex-row">
                        <select
                          id="trello-account"
                          value={selectedAccountId}
                          onChange={(event) => setSelectedAccountId(event.target.value)}
                          className="min-h-10 flex-1 rounded-lg border border-zinc-200 bg-white px-3 text-sm text-zinc-800 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
                        >
                          {accounts.map((account) => (
                            <option key={account.id} value={account.id}>
                              {account.username}
                            </option>
                          ))}
                        </select>
                        <Button
                          type="button"
                          className="gap-2 rounded-lg px-4"
                          disabled={!selectedAccountId || linkingAccount}
                          onClick={() => void reuseTrelloAccount()}
                        >
                          {linkingAccount ? "Linking…" : "Use this account"}
                        </Button>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 text-xs font-medium uppercase tracking-wide text-zinc-400">
                      <span className="h-px flex-1 bg-zinc-200" />
                      or
                      <span className="h-px flex-1 bg-zinc-200" />
                    </div>
                    <Button
                      type="button"
                      variant="secondary"
                      className="gap-2 rounded-lg px-4"
                      onClick={() => void connectTrello()}
                    >
                      Connect a different account
                      <ExternalLink className="h-4 w-4" />
                    </Button>
                  </div>
                ) : (
                  <Button className="mt-5 gap-2 rounded-lg px-4" onClick={() => void connectTrello()}>
                    Connect Trello
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                )}
              </div>
              <div className="hidden h-36 w-36 items-center justify-center rounded-full bg-indigo-50 md:flex">
                <div className="flex h-24 w-24 items-center justify-center rounded-3xl bg-white text-indigo-600 shadow-sm">
                  <Check className="h-12 w-12" />
                </div>
              </div>
            </div>
            <div className="flex items-start gap-3 border-t border-zinc-100 bg-zinc-50 px-6 py-4 text-xs leading-5 text-zinc-500 sm:px-9">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-zinc-400" />
              <p>You can change which boards are included at any time. We only sync the boards you select.</p>
            </div>
          </section>
        ) : (
          <>
            <section aria-labelledby="boards-heading" className="overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm">
              <div className="flex flex-col gap-5 border-b border-zinc-100 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
                <div className="flex items-start gap-4">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
                    <Layers3 className="h-5 w-5" />
                  </div>
                  <div>
                    <h2 id="boards-heading" className="text-lg font-semibold text-zinc-950">Choose boards</h2>
                    <p className="mt-1 text-sm text-zinc-500">Only included boards are synced into this workspace.</p>
                    <p className="mt-2 inline-flex items-center rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-600">
                      {includedBoards.length} of {boards.length} boards included
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 sm:justify-end">
                  <Button
                    type="button"
                    variant="secondary"
                    className="gap-2 rounded-lg border-zinc-200 px-3"
                    disabled={loading}
                    onClick={() => void loadWorkspace(selectedWorkspace)}
                  >
                    <RefreshCw className="h-4 w-4" />
                    Refresh
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    className="gap-2 rounded-lg border-zinc-200 px-3"
                    disabled={syncing || !includedBoards.length || boardSelectionChanged}
                    onClick={() => void syncBoards()}
                  >
                    <RefreshCw className={`h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
                    {syncing ? "Starting…" : "Sync now"}
                  </Button>
                  <Button
                    type="button"
                    className="gap-2 rounded-lg px-4"
                    disabled={saving || !boards.length}
                    onClick={() => void saveBoards()}
                  >
                    <Save className="h-4 w-4" />
                    {saving ? "Saving…" : "Save boards"}
                  </Button>
                </div>
              </div>
              {boards.length ? (
                <ul className="divide-y divide-zinc-100">
                  {boards.map((board) => {
                    const syncingBoard = board.sync_status === "running";
                    const failedBoard = board.sync_status === "failed";
                    const completedBoard = board.sync_status === "completed";
                    return (
                      <li key={board.id} className="flex flex-col gap-4 px-5 py-5 transition-colors hover:bg-zinc-50/70 sm:flex-row sm:items-center sm:justify-between sm:px-6">
                        <div className="flex min-w-0 items-start gap-3">
                          <div className={`mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${board.excluded ? "bg-zinc-100 text-zinc-400" : "bg-blue-50 text-blue-700"}`}>
                            <Layers3 className="h-5 w-5" />
                          </div>
                          <div className="min-w-0">
                            <a
                              href={board.url}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex max-w-full items-center gap-1.5 text-sm font-semibold text-zinc-900 hover:text-indigo-700"
                            >
                              <span className="truncate">{board.name}</span>
                              <ExternalLink className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
                            </a>
                            <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-zinc-500">
                              <span className={`inline-flex items-center gap-1.5 font-medium ${failedBoard ? "text-rose-700" : completedBoard ? "text-emerald-700" : syncingBoard ? "text-blue-700" : "text-zinc-500"}`}>
                                {syncingBoard ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : failedBoard ? <AlertCircle className="h-3.5 w-3.5" /> : completedBoard ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Circle className="h-3.5 w-3.5" />}
                                {syncingBoard ? "Syncing" : failedBoard ? "Sync failed" : completedBoard ? "Up to date" : "Not synced yet"}
                              </span>
                              {board.last_synced_at ? (
                                <span className="inline-flex items-center gap-1">
                                  <Clock3 className="h-3 w-3" />
                                  Last synced {new Date(board.last_synced_at).toLocaleString()}
                                </span>
                              ) : null}
                            </div>
                            {board.sync_error ? (
                              <p className="mt-2 max-w-2xl text-xs leading-5 text-rose-700">{board.sync_error}</p>
                            ) : null}
                          </div>
                        </div>
                        <label className={`inline-flex min-h-10 shrink-0 cursor-pointer items-center gap-3 rounded-xl border px-3.5 py-2 text-sm font-medium transition-colors ${board.excluded ? "border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-50" : "border-indigo-200 bg-indigo-50 text-indigo-800"}`}>
                          <input
                            type="checkbox"
                            checked={!board.excluded}
                            onChange={(event) => updateBoard(board.id, !event.target.checked)}
                            className="h-4 w-4 rounded border-zinc-300 accent-indigo-600 focus:ring-indigo-500"
                          />
                          Include in sync
                        </label>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <div className="px-6 py-12 text-center">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-zinc-100 text-zinc-500">
                    <Layers3 className="h-6 w-6" />
                  </div>
                  <h3 className="mt-4 text-sm font-semibold text-zinc-900">No open boards found</h3>
                  <p className="mt-1 text-sm text-zinc-500">Check your Trello account or refresh to try again.</p>
                </div>
              )}
              <div className="border-t border-zinc-100 bg-zinc-50 px-5 py-3 text-xs leading-5 text-zinc-500 sm:px-6">
                {boardSelectionChanged
                  ? "You have unsaved board changes. Save your choices before starting a sync."
                  : "Only the boards marked “Include in sync” will be brought into this workspace."}
              </div>
            </section>

            <section aria-labelledby="mapping-heading" className="overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm">
              <div className="border-b border-zinc-100 p-5 sm:p-6">
                <div className="flex items-start gap-4">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-violet-50 text-violet-700">
                    <ListTodo className="h-5 w-5" />
                  </div>
                  <div>
                    <h2 id="mapping-heading" className="text-lg font-semibold text-zinc-950">Match boards to clients</h2>
                    <p className="mt-1 max-w-3xl text-sm leading-6 text-zinc-500">
                      Tell us which client each board, list, or label belongs to. Label and list rules take priority over a board rule.
                    </p>
                  </div>
                </div>
              </div>
              <div className="p-5 sm:p-6">
                <div className="grid gap-4 md:grid-cols-2">
                  <label className="block text-sm font-medium text-zinc-700">
                    Trello board
                    <select
                      className="mt-2 block h-11 w-full rounded-lg border border-zinc-200 bg-white px-3 text-sm text-zinc-900 shadow-sm outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
                      value={mappingBoardId}
                      onChange={(event) => setMappingBoardId(event.target.value)}
                    >
                      <option value="">Choose a board</option>
                      {includedBoards.map((board) => (
                        <option key={board.id} value={board.id}>{board.name}</option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-sm font-medium text-zinc-700">
                    Match using
                    <select
                      className="mt-2 block h-11 w-full rounded-lg border border-zinc-200 bg-white px-3 text-sm text-zinc-900 shadow-sm outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
                      value={mappingType}
                      onChange={(event) => setMappingType(event.target.value as TrelloMappingType)}
                    >
                      <option value="board">The entire board</option>
                      <option value="list">A Trello list</option>
                      <option value="label">A Trello label</option>
                    </select>
                  </label>
                  {mappingType !== "board" ? (
                    <label className="block text-sm font-medium text-zinc-700">
                      Trello {mappingType} name
                      <input
                        className="mt-2 block h-11 w-full rounded-lg border border-zinc-200 bg-white px-3 text-sm text-zinc-900 shadow-sm outline-none transition placeholder:text-zinc-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
                        value={mappingValue}
                        onChange={(event) => setMappingValue(event.target.value)}
                        placeholder={`Enter the exact ${mappingType} name`}
                        maxLength={255}
                      />
                    </label>
                  ) : null}
                  <label className="block text-sm font-medium text-zinc-700">
                    Client name
                    <input
                      className="mt-2 block h-11 w-full rounded-lg border border-zinc-200 bg-white px-3 text-sm text-zinc-900 shadow-sm outline-none transition placeholder:text-zinc-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
                      value={mappingClientName}
                      onChange={(event) => setMappingClientName(event.target.value)}
                      placeholder="e.g. Acme Studio"
                      maxLength={255}
                    />
                  </label>
                </div>
                <p className="mt-3 text-xs leading-5 text-zinc-500">
                  {mappingType === "board"
                    ? "Every card on this board will be associated with the client name you enter."
                    : `Cards matching this exact Trello ${mappingType} name will be associated with the client.`}
                </p>
                <div className="mt-5 flex flex-col gap-3 border-t border-zinc-100 pt-5 sm:flex-row sm:items-center sm:justify-between">
                  <Button
                    type="button"
                    variant="secondary"
                    className="w-fit gap-2 rounded-lg border-zinc-200"
                    disabled={!mappingBoardId || !mappingClientName.trim() || (mappingType !== "board" && !mappingValue.trim())}
                    onClick={addClientMapping}
                  >
                    <Plus className="h-4 w-4" />
                    Add rule
                  </Button>
                  <Button
                    type="button"
                    className="gap-2 rounded-lg px-4"
                    disabled={saving}
                    onClick={() => void saveMappings()}
                  >
                    <Save className="h-4 w-4" />
                    {saving ? "Saving rules…" : "Save client rules"}
                  </Button>
                </div>
              </div>
              {clientMappings.length ? (
                <ul className="border-t border-zinc-100">
                  {clientMappings.map((mapping, index) => (
                    <li
                      key={`${mapping.board_id}-${mapping.mapping_type}-${mapping.external_ref}-${index}`}
                      className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6"
                    >
                      <div className="flex min-w-0 items-center gap-3">
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-violet-50 text-violet-700">
                          <CheckCircle2 className="h-4 w-4" />
                        </div>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-zinc-900">{mapping.client_name}</p>
                          <p className="mt-0.5 truncate text-xs text-zinc-500">
                            {mapping.board_name} <span className="px-1">·</span> {mapping.mapping_type === "board" ? "Entire board" : `${mapping.mapping_type}: ${mapping.external_ref}`}
                          </p>
                        </div>
                      </div>
                      <button
                        type="button"
                        aria-label={`Remove ${mapping.client_name} mapping`}
                        className="inline-flex min-h-9 items-center gap-2 self-start rounded-lg px-3 text-sm font-medium text-zinc-500 transition hover:bg-rose-50 hover:text-rose-700 sm:self-auto"
                        onClick={() => setClientMappings((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                      >
                        <Trash2 className="h-4 w-4" />
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="border-t border-zinc-100 bg-zinc-50/60 px-6 py-8 text-center">
                  <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-white text-zinc-400 shadow-sm">
                    <ListTodo className="h-5 w-5" />
                  </div>
                  <p className="mt-3 text-sm font-medium text-zinc-700">No client rules yet</p>
                  <p className="mt-1 text-xs text-zinc-500">Add a rule above to organize synced work by client.</p>
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </DashboardTemplate>
  );
}