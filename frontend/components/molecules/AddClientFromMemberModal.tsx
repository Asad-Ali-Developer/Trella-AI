"use client";

import React, { useEffect } from "react";
import { Check, LoaderCircle, Sparkles, UserPlus, Users } from "lucide-react";
import { Button } from "@/components/atoms/Button";

interface AddClientFromMemberModalProps {
  isOpen: boolean;
  memberName: string;
  username: string;
  workspaceName: string;
  isAlreadyClient?: boolean;
  isLoading?: boolean;
  onClose: () => void;
  onConfirmAddClient: () => Promise<void> | void;
  onConfirmRoleOnly: () => Promise<void> | void;
}

export function AddClientFromMemberModal({
  isOpen,
  memberName,
  username,
  workspaceName,
  isAlreadyClient = false,
  isLoading = false,
  onClose,
  onConfirmAddClient,
  onConfirmRoleOnly,
}: AddClientFromMemberModalProps) {
  // Close on Escape key
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && isOpen && !isLoading) {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, isLoading, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isLoading) {
          onClose();
        }
      }}
    >
      <div className="w-full max-w-md rounded-2xl border border-zinc-200 bg-white p-6 shadow-2xl transition-all dark:border-[#253745] dark:bg-[#11212D] dark:text-[#F1F5F9]">
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-indigo-200 bg-indigo-50 text-indigo-600 dark:border-indigo-900/60 dark:bg-indigo-950/50 dark:text-indigo-400">
            <UserPlus className="h-6 w-6" />
          </div>

          <div className="flex-1 min-w-0">
            <h3 className="text-lg font-bold text-zinc-950 dark:text-[#F1F5F9]">
              Add to Clients?
            </h3>
            <p className="mt-1.5 text-xs leading-relaxed text-zinc-600 dark:text-[#9BA8AB]">
              Do you want to add <strong className="font-bold text-zinc-950 dark:text-[#F1F5F9]">{memberName}</strong> into clients for <span className="font-semibold text-zinc-800 dark:text-[#CCD0CF]">{workspaceName}</span>?
            </p>

            <div className="mt-3.5 space-y-2 rounded-xl border border-zinc-100 bg-zinc-50 p-3 text-xs dark:border-[#253745] dark:bg-[#162736]">
              <div className="flex items-center justify-between">
                <span className="text-zinc-500 dark:text-[#9BA8AB]">Person:</span>
                <span className="font-semibold text-zinc-900 dark:text-[#F1F5F9]">
                  {memberName} <span className="text-zinc-400 dark:text-[#9BA8AB]">(@{username})</span>
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-zinc-500 dark:text-[#9BA8AB]">Workspace:</span>
                <span className="font-medium text-zinc-700 dark:text-[#CCD0CF]">{workspaceName}</span>
              </div>
              <div className="pt-2 border-t border-zinc-200/60 dark:border-[#253745] text-[11px] leading-relaxed text-zinc-500 dark:text-[#9BA8AB] flex items-start gap-1.5">
                <Sparkles className="h-3.5 w-3.5 shrink-0 text-indigo-500 mt-0.5" />
                <span>
                  Adding this client stores them in the database and links them with this workspace for better context, card mapping, and AI intelligence analysis.
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-[#253745]">
          <Button
            type="button"
            variant="ghost"
            onClick={onClose}
            disabled={isLoading}
            className="rounded-xl px-3 py-1.5 text-xs font-semibold text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-[#CCD0CF] dark:hover:bg-[#253745] dark:hover:text-white"
          >
            Cancel
          </Button>

          <Button
            type="button"
            variant="ghost"
            onClick={() => void onConfirmRoleOnly()}
            disabled={isLoading}
            className="rounded-xl border border-zinc-200 px-3 py-1.5 text-xs font-semibold text-zinc-700 hover:bg-zinc-50 dark:border-[#253745] dark:bg-[#162736] dark:text-[#CCD0CF] dark:hover:bg-[#253745] dark:hover:text-white"
          >
            Just Set Role
          </Button>

          <Button
            type="button"
            onClick={() => void onConfirmAddClient()}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700 dark:bg-[#253745] dark:hover:bg-[#354D60] dark:border dark:border-[#4A5C6A] disabled:opacity-50"
          >
            {isLoading ? (
              <>
                <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                Adding…
              </>
            ) : (
              <>
                <UserPlus className="h-3.5 w-3.5" />
                Yes, Add to Clients
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
