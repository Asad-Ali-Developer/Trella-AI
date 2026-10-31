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
      className="fixed inset-0 z-50 bg-[#06141B]/60 backdrop-blur-sm"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !creating) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-workspace-title"
        className="absolute inset-y-0 right-0 flex w-full max-w-lg flex-col border-l border-[#9BA8AB] bg-white shadow-2xl transition-colors duration-200 dark:border-[#253745] dark:bg-[#11212D]"
      >
        <div className="flex items-start justify-between border-b border-[#9BA8AB]/40 px-6 py-5 dark:border-[#253745]">
          <div className="flex items-start gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl border border-[#4A5C6A] bg-[#253745] text-[#CCD0CF]">
              <Building2 className="h-5 w-5" />
            </span>
            <div>
              <h2 id="create-workspace-title" className="text-lg font-bold text-[#06141B] dark:text-[#CCD0CF]">
                {mode === "edit" ? "Edit workspace" : "Create a workspace"}
              </h2>
              <p className="mt-1 text-sm leading-5 text-[#4A5C6A] dark:text-[#9BA8AB]">
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
            className="flex h-9 w-9 items-center justify-center rounded-xl text-[#4A5C6A] hover:bg-[#CCD0CF]/40 dark:text-[#9BA8AB] dark:hover:bg-[#253745] disabled:opacity-50"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
          <div className="flex-1 space-y-5 overflow-y-auto px-6 py-6">
            <label className="block text-sm font-semibold text-[#06141B] dark:text-[#CCD0CF]" htmlFor="workspace-name">
              Workspace name <span className="text-[#4A5C6A] dark:text-[#9BA8AB]">*</span>
              <input
                id="workspace-name"
                autoFocus
                required
                maxLength={100}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. Acme client workspace"
                className="mt-2 block h-11 w-full rounded-2xl border border-[#9BA8AB] bg-white px-3.5 text-sm text-[#06141B] outline-none transition focus:border-[#253745] focus:ring-2 focus:ring-[#253745]/20 dark:border-[#253745] dark:bg-[#11212D] dark:text-[#CCD0CF] dark:focus:border-[#4A5C6A]"
              />
              <span className="mt-1.5 block text-xs font-normal text-[#4A5C6A] dark:text-[#9BA8AB]">
                A clear name helps your team find the right workspace.
              </span>
            </label>

            <label className="block text-sm font-semibold text-[#06141B] dark:text-[#CCD0CF]" htmlFor="workspace-client-name">
              Client name <span className="font-normal text-[#4A5C6A] dark:text-[#9BA8AB]">(optional)</span>
              <input
                id="workspace-client-name"
                maxLength={255}
                value={clientName}
                onChange={(event) => setClientName(event.target.value)}
                placeholder="e.g. Acme Studio"
                className="mt-2 block h-11 w-full rounded-2xl border border-[#9BA8AB] bg-white px-3.5 text-sm text-[#06141B] outline-none transition focus:border-[#253745] focus:ring-2 focus:ring-[#253745]/20 dark:border-[#253745] dark:bg-[#11212D] dark:text-[#CCD0CF] dark:focus:border-[#4A5C6A]"
              />
              <span className="mt-1.5 block text-xs font-normal text-[#4A5C6A] dark:text-[#9BA8AB]">
                Used to identify the client this workspace is for.
              </span>
            </label>

            <label className="block text-sm font-semibold text-[#06141B] dark:text-[#CCD0CF]" htmlFor="workspace-description">
              Description <span className="font-normal text-[#4A5C6A] dark:text-[#9BA8AB]">(optional)</span>
              <textarea
                id="workspace-description"
                rows={4}
                maxLength={2000}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="What work and tools will this workspace bring together?"
                className="mt-2 block w-full resize-y rounded-2xl border border-[#9BA8AB] bg-white px-3.5 py-2.5 text-sm text-[#06141B] outline-none transition focus:border-[#253745] focus:ring-2 focus:ring-[#253745]/20 dark:border-[#253745] dark:bg-[#11212D] dark:text-[#CCD0CF] dark:focus:border-[#4A5C6A]"
              />
              <span className="mt-1.5 block text-xs font-normal text-[#4A5C6A] dark:text-[#9BA8AB]">
                Add context for teammates who use this workspace.
              </span>
            </label>

            {error ? (
              <p role="alert" className="rounded-2xl border border-[#4A5C6A] bg-[#253745]/15 p-3 text-sm text-[#06141B] dark:bg-[#253745] dark:text-[#CCD0CF]">
                {error}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col-reverse gap-2 border-t border-[#9BA8AB]/40 bg-[#CCD0CF]/30 px-6 py-4 sm:flex-row sm:justify-end dark:border-[#253745] dark:bg-[#06141B]/40">
            <Button
              type="button"
              variant="secondary"
              className="rounded-xl"
              onClick={onClose}
              disabled={creating}
            >
              Cancel
            </Button>
            <Button type="submit" className="rounded-xl px-5" disabled={creating || !name.trim()}>
              {creating ? (mode === "edit" ? "Saving…" : "Creating…") : (mode === "edit" ? "Save changes" : "Create workspace")}
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
}
