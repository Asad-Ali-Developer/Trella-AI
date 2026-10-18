"use client";

import { ChevronsUpDown, Plus } from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";

import { Button } from "@/components/atoms/Button";
import { Input } from "@/components/atoms/Input";
import type { Workspace } from "@/lib/types";
import { workspaceStore } from "@/lib/storage";
import { workspaceService } from "@/services/WorkspaceService";

interface WorkspaceSwitcherProps {
  workspaces: Workspace[];
  selectedId: string | null;
  onSelect: (workspace: Workspace) => void;
  onCreated: (workspace: Workspace) => void;
}

export function WorkspaceSwitcher({
  workspaces,
  selectedId,
  onSelect,
  onCreated,
}: WorkspaceSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  const selected = workspaces.find((workspace) => workspace.id === selectedId) ?? workspaces[0];

  useEffect(() => {
    function onClick(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError("");
    try {
      const workspace = await workspaceService.create(name.trim());
      workspaceStore.setWorkspaceId(workspace.id);
      onCreated(workspace);
      setName("");
      setOpen(false);
    } catch {
      setError("Could not create workspace.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between rounded-md border border-border bg-white px-2.5 py-2 text-left text-sm hover:bg-muted"
      >
        <span className="truncate font-medium">
          {selected ? selected.name : "Select workspace"}
        </span>
        <ChevronsUpDown className="h-4 w-4 text-muted-foreground" />
      </button>
      {open ? (
        <div className="absolute left-0 right-0 z-20 mt-1 rounded-md border border-border bg-white p-1 shadow-sm">
          {workspaces.map((workspace) => (
            <button
              key={workspace.id}
              type="button"
              onClick={() => {
                workspaceStore.setWorkspaceId(workspace.id);
                onSelect(workspace);
                setOpen(false);
              }}
              className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm hover:bg-muted"
            >
              <span className="truncate">{workspace.name}</span>
              <span className="text-[11px] uppercase text-muted-foreground">{workspace.role}</span>
            </button>
          ))}
          <form onSubmit={handleCreate} className="mt-1 space-y-1.5 border-t border-border p-1.5">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="New workspace"
            />
            {error ? <p className="text-xs text-red-600">{error}</p> : null}
            <Button type="submit" variant="secondary" className="w-full gap-1.5" disabled={creating}>
              <Plus className="h-3.5 w-3.5" />
              Create
            </Button>
          </form>
        </div>
      ) : null}
    </div>
  );
}
