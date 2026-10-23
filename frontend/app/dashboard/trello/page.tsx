"use client";

import { Check, ExternalLink, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/atoms/Button";
import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { clearSession, setAuthenticatedUser } from "@/lib/authSlice";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { workspaceStore } from "@/lib/storage";
import type { TrelloBoard, TrelloConnectionStatus, Workspace } from "@/lib/types";
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
  const [boards, setBoards] = useState<TrelloBoard[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadWorkspace = useCallback(async (workspace: Workspace) => {
    workspaceStore.setWorkspaceId(workspace.id);
    setSelectedWorkspace(workspace);
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const status = await trelloService.status();
      setConnection(status);
      setBoards(status.connected ? await trelloService.listBoards() : []);
    } catch {
      setConnection(null);
      setBoards([]);
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

  async function saveBoards() {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await trelloService.saveBoards(boards);
      setNotice("Board selections saved.");
    } catch {
      setError("Could not save board selections. Please retry.");
    } finally {
      setSaving(false);
    }
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

  return (
    <DashboardTemplate
      sidebar={
        <Sidebar
          user={user}
          workspaces={workspaces}
          selectedId={selectedWorkspace?.id ?? null}
          onSelectWorkspace={(workspace) => void loadWorkspace(workspace)}
          onWorkspaceCreated={(workspace) => {
            setWorkspaces((current) => [workspace, ...current]);
            void loadWorkspace(workspace);
          }}
          onLogout={logout}
        />
      }
    >
      <div className="mx-auto w-full max-w-4xl space-y-6">
        <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm text-muted-foreground">Workspace integration</p>
            <h1 className="text-2xl font-semibold">Trello</h1>
          </div>
          {connection?.connected ? (
            <span className="inline-flex w-fit items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
              <Check className="h-4 w-4" />
              Connected as {connection.username}
            </span>
          ) : null}
        </header>

        {error ? <p role="alert" className="text-sm text-red-600">{error}</p> : null}
        {notice ? <p role="status" className="text-sm text-emerald-700">{notice}</p> : null}

        {!selectedWorkspace ? (
          <section className="border-t border-border py-6">
            <h2 className="text-lg font-medium">Create a workspace first</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Trello connections and board selections belong to a workspace.
            </p>
          </section>
        ) : loading ? (
          <div className="border-t border-border py-6 text-sm text-muted-foreground" role="status">
            Loading Trello connection…
          </div>
        ) : !connection?.connected ? (
          <section className="border-t border-border py-6">
            <h2 className="text-lg font-medium">Connect your Trello account</h2>
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
              Grant read-only access to choose boards. Your Trello token is encrypted before it is stored.
            </p>
            <Button className="mt-4 gap-2" onClick={() => void connectTrello()}>
              <ExternalLink className="h-4 w-4" />
              Connect Trello
            </Button>
          </section>
        ) : (
          <section className="border-t border-border pt-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 className="text-lg font-medium">Boards</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {boards.filter((board) => !board.excluded).length} of {boards.length} selected
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  className="gap-2"
                  disabled={loading}
                  onClick={() => void loadWorkspace(selectedWorkspace)}
                >
                  <RefreshCw className="h-4 w-4" />
                  Refresh boards
                </Button>
                <Button type="button" disabled={saving} onClick={() => void saveBoards()}>
                  {saving ? "Saving…" : "Save selection"}
                </Button>
              </div>
            </div>
            {boards.length ? (
              <ul className="mt-4 divide-y divide-border border-y border-border">
                {boards.map((board) => (
                  <li key={board.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <a
                        href={board.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex max-w-full items-center gap-1.5 text-sm font-medium hover:underline"
                      >
                        <span className="truncate">{board.name}</span>
                        <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                      </a>
                    </div>
                    <label className="inline-flex min-h-10 shrink-0 cursor-pointer items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={!board.excluded}
                        onChange={(event) => updateBoard(board.id, !event.target.checked)}
                        className="h-4 w-4 accent-emerald-700"
                      />
                      Include board
                    </label>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-4 border-y border-border py-5 text-sm text-muted-foreground">
                No open boards were found for this account.
              </p>
            )}
          </section>
        )}
      </div>
    </DashboardTemplate>
  );
}