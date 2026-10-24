"use client";

import { ChevronsUpDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { Workspace } from "@/lib/types";
import { workspaceStore } from "@/lib/storage";

interface WorkspaceSwitcherProps {
  workspaces: Workspace[];
  selectedId: string | null;
  onSelect: (workspace: Workspace) => void;
}

export function WorkspaceSwitcher({ workspaces, selectedId, onSelect }: WorkspaceSwitcherProps) {
  const [open, setOpen] = useState(false);
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
        </div>
      ) : null}
    </div>
  );
}
