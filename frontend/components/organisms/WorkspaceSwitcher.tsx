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
        className="flex w-full items-center justify-between rounded-xl border border-[#9BA8AB] bg-white px-3 py-2.5 text-left text-sm font-semibold text-[#06141B] shadow-sm transition-all hover:bg-[#CCD0CF]/40 dark:border-[#253745] dark:bg-[#11212D] dark:text-[#CCD0CF] dark:hover:bg-[#253745]"
      >
        <span className="truncate">
          {selected ? selected.name : "Select workspace"}
        </span>
        <ChevronsUpDown className="h-4 w-4 shrink-0 text-[#4A5C6A] dark:text-[#9BA8AB]" />
      </button>
      {open ? (
        <div className="absolute left-0 right-0 z-20 mt-1.5 rounded-2xl border border-[#9BA8AB] bg-white p-1.5 shadow-xl backdrop-blur-md dark:border-[#253745] dark:bg-[#11212D]">
          {workspaces.map((workspace) => (
            <button
              key={workspace.id}
              type="button"
              onClick={() => {
                workspaceStore.setWorkspaceId(workspace.id);
                onSelect(workspace);
                setOpen(false);
              }}
              className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm font-medium text-[#06141B] transition hover:bg-[#CCD0CF]/60 dark:text-[#CCD0CF] dark:hover:bg-[#253745]"
            >
              <span className="truncate">{workspace.name}</span>
              <span className="rounded-full border border-[#4A5C6A] bg-[#253745] px-2 py-0.5 text-[10px] font-semibold text-[#CCD0CF] uppercase">
                {workspace.role}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
