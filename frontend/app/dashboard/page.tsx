"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/atoms/Button";
import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { clearSession, setAuthenticatedUser, setSessionLoading } from "@/lib/authSlice";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { workspaceStore } from "@/lib/storage";
import type { Workspace } from "@/lib/types";
import { authService } from "@/services/AuthService";
import { workspaceService } from "@/services/WorkspaceService";

export default function DashboardPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [logoutError, setLogoutError] = useState("");

  const load = useCallback(async () => {
    dispatch(setSessionLoading());
    try {
      const [me, list] = await Promise.all([authService.me(), workspaceService.list()]);
      dispatch(setAuthenticatedUser(me));
      setWorkspaces(list);
      const stored = workspaceStore.getWorkspaceId();
      const next = list.find((item) => item.id === stored) ?? list[0] ?? null;
      if (next) {
        workspaceStore.setWorkspaceId(next.id);
        setSelectedId(next.id);
      }
    } catch {
      dispatch(clearSession());
      workspaceStore.clear();
      router.replace("/login");
    } finally {
      setLoading(false);
    }
  }, [dispatch, router]);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = workspaces.find((workspace) => workspace.id === selectedId) ?? null;

  function logout() {
    setLogoutError("");
    void authService
      .logout()
      .then(() => {
        dispatch(clearSession());
        router.replace("/login");
      })
      .catch(() => setLogoutError("Could not sign out. Check your connection and try again."));
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Loading workspace…
      </div>
    );
  }

  return (
    <DashboardTemplate
      sidebar={
        <Sidebar
          user={user}
          workspaces={workspaces}
          selectedId={selectedId}
          onSelectWorkspace={(workspace) => setSelectedId(workspace.id)}
          onWorkspaceCreated={(workspace) => {
            setWorkspaces((current) => [workspace, ...current]);
            setSelectedId(workspace.id);
          }}
          onLogout={logout}
        />
      }
    >
      <div className="mx-auto max-w-3xl space-y-6">
        <div>
          <p className="text-sm text-muted-foreground">Overview</p>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        </div>
        {logoutError ? <p role="alert" className="text-sm text-red-600">{logoutError}</p> : null}
        {selected ? (
          <section className="rounded-xl border border-border bg-white p-6">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Current workspace</p>
            <h2 className="mt-1 text-lg font-medium">{selected.name}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Role: {selected.role} · slug {selected.slug}
            </p>
            <p className="mt-4 text-sm text-muted-foreground">
              Trello sync, skill runs, and reports land here in later phases.
            </p>
          </section>
        ) : (
          <section className="rounded-xl border border-dashed border-border bg-white p-6">
            <h2 className="text-lg font-medium">Create your first workspace</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Use the switcher in the sidebar to add a workspace. You become the owner.
            </p>
            <Button
              className="mt-4"
              onClick={() => {
                const name = window.prompt("Workspace name");
                if (!name?.trim()) return;
                void workspaceService.create(name.trim()).then((workspace) => {
                  workspaceStore.setWorkspaceId(workspace.id);
                  setWorkspaces((current) => [workspace, ...current]);
                  setSelectedId(workspace.id);
                });
              }}
            >
              New workspace
            </Button>
          </section>
        )}
      </div>
    </DashboardTemplate>
  );
}
