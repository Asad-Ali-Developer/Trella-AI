"use client";

import { Building2, X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/atoms/Button";
import type { Workspace } from "@/lib/types";
import { workspaceService } from "@/services/WorkspaceService";

interface WorkspaceCreateDrawerProps {
  mode?: "create" | "edit";
  workspace?: Workspace;
  onClose: () => void;
  onSaved: (workspace: Workspace) => void;
}

export function WorkspaceCreateDrawer({
  mode = "create",
  workspace,
  onClose,
  onSaved,
}: WorkspaceCreateDrawerProps) {
  const [name, setName] = useState(workspace?.name ?? "");
  const [description, setDescription] = useState(workspace?.description ?? "");
  const [clientName, setClientName] = useState(workspace?.client_name ?? "");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setName(workspace?.name ?? "");
    setDescription(workspace?.description ?? "");
    setClientName(workspace?.client_name ?? "");
    setError("");
  }, [workspace]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !creating) onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [creating, onClose]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError("");
    try {
      const input = {
        name: name.trim(),
        description: description.trim() || undefined,
        client_name: clientName.trim() || undefined,
      };
      const savedWorkspace = mode === "edit" && workspace
        ? await workspaceService.update(workspace.id, input)
        : await workspaceService.create(input);
      onSaved(savedWorkspace);
    } catch {
      setError("Could not create the workspace. Please check the details and try again.");
      setCreating(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-zinc-950/35 backdrop-blur-[2px]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !creating) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-workspace-title"
        className="absolute inset-y-0 right-0 flex w-full max-w-lg flex-col bg-white shadow-2xl"
      >
        <div className="flex items-start justify-between border-b border-zinc-100 px-6 py-5">
          <div className="flex items-start gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-50 text-indigo-700">
              <Building2 className="h-5 w-5" />
            </span>
            <div>
              <h2 id="create-workspace-title" className="text-lg font-semibold text-zinc-950">
                {mode === "edit" ? "Edit workspace" : "Create a workspace"}
              </h2>
              <p className="mt-1 text-sm leading-5 text-zinc-500">
                {mode === "edit"
                  ? "Update the client details and workspace description."
                  : "Set up a home for one client and their connected work."}
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close create workspace panel"
            onClick={onClose}
            disabled={creating}
            className="flex h-9 w-9 items-center justify-center rounded-lg text-zinc-500 hover:bg-zinc-100 disabled:opacity-50"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
          <div className="flex-1 space-y-5 overflow-y-auto px-6 py-6">
            <label className="block text-sm font-medium text-zinc-700" htmlFor="workspace-name">
              Workspace name <span className="text-rose-600">*</span>
              <input
                id="workspace-name"
                autoFocus
                required
                maxLength={100}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. Acme client workspace"
                className="mt-2 block h-11 w-full rounded-lg border border-zinc-200 px-3 text-sm text-zinc-900 outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
              />
              <span className="mt-1.5 block text-xs font-normal text-zinc-500">
                A clear name helps your team find the right workspace.
              </span>
            </label>

            <label className="block text-sm font-medium text-zinc-700" htmlFor="workspace-client-name">
              Client name <span className="font-normal text-zinc-400">(optional)</span>
              <input
                id="workspace-client-name"
                maxLength={255}
                value={clientName}
                onChange={(event) => setClientName(event.target.value)}
                placeholder="e.g. Acme Studio"
                className="mt-2 block h-11 w-full rounded-lg border border-zinc-200 px-3 text-sm text-zinc-900 outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
              />
              <span className="mt-1.5 block text-xs font-normal text-zinc-500">
                Used to identify the client this workspace is for.
              </span>
            </label>

            <label className="block text-sm font-medium text-zinc-700" htmlFor="workspace-description">
              Description <span className="font-normal text-zinc-400">(optional)</span>
              <textarea
                id="workspace-description"
                rows={4}
                maxLength={2000}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="What work and tools will this workspace bring together?"
                className="mt-2 block w-full resize-y rounded-lg border border-zinc-200 px-3 py-2.5 text-sm text-zinc-900 outline-none focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100"
              />
              <span className="mt-1.5 block text-xs font-normal text-zinc-500">
                Add context for teammates who use this workspace.
              </span>
            </label>

            {error ? (
              <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2.5 text-sm text-rose-800">
                {error}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col-reverse gap-2 border-t border-zinc-100 bg-zinc-50 px-6 py-4 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="secondary"
              className="rounded-lg"
              onClick={onClose}
              disabled={creating}
            >
              Cancel
            </Button>
            <Button type="submit" className="rounded-lg px-4" disabled={creating || !name.trim()}>
              {creating ? (mode === "edit" ? "Saving…" : "Creating…") : (mode === "edit" ? "Save changes" : "Create workspace")}
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
}
