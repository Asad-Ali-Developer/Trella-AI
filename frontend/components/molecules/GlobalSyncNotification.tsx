"use client";

import React from "react";
import Link from "next/link";
import { CheckCircle2, RefreshCw, X, Layers } from "lucide-react";
import { useSyncQueue } from "@/components/providers/SyncQueueProvider";

export function GlobalSyncNotification() {
  const { isSyncing, activeJobName, showCompleted, completedMessage, dismissCompleted, status } =
    useSyncQueue();

  if (!isSyncing && !showCompleted) {
    return null;
  }

  return (
    <aside
      aria-label="Background synchronization status"
      className="fixed bottom-6 right-6 z-50 w-[calc(100vw-3rem)] max-w-sm animate-in fade-in slide-in-from-bottom-4 duration-300"
    >
      <div className="rounded-2xl border border-[#E2E8F0] bg-white/95 p-4 shadow-2xl backdrop-blur-md dark:border-[#253745] dark:bg-[#11212D]/95">
        {isSyncing ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2.5">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-50 dark:bg-indigo-950/60">
                  <RefreshCw className="h-3.5 w-3.5 animate-spin text-indigo-600 dark:text-indigo-400" />
                </span>
                <span className="text-sm font-semibold text-[#06141B] dark:text-[#F1F5F9]">
                  Syncing {activeJobName || "Workspace"}
                </span>
              </div>
              <span className="inline-flex items-center gap-1 rounded-full border border-indigo-200/80 bg-indigo-50/80 px-2 py-0.5 text-[11px] font-medium text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/40 dark:text-indigo-300">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-500" />
                Processing
              </span>
            </div>

            <p className="text-xs text-[#64748B] dark:text-[#9BA8AB]">
              Downloading cards & comments, and embedding vector chunks in background.
            </p>

            {/* Modern Minimalistic Animated Progress Bar */}
            <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-[#162736]">
              <div className="absolute inset-y-0 w-2/5 animate-[pulse_1.5s_infinite_ease-in-out] rounded-full bg-gradient-to-r from-indigo-500 via-sky-400 to-indigo-500" />
            </div>

            <div className="flex items-center justify-between pt-1">
              <div className="flex items-center gap-1 text-[11px] text-[#64748B] dark:text-[#9BA8AB]">
                <Layers className="h-3 w-3" />
                <span>
                  {status?.celery_queue_length
                    ? `${status.celery_queue_length} tasks in queue`
                    : "Queue active"}
                </span>
              </div>
              <Link
                href="/dashboard/queue"
                className="text-xs font-medium text-indigo-600 transition-colors hover:text-indigo-700 dark:text-indigo-400 dark:hover:text-indigo-300"
              >
                View Queue &rarr;
              </Link>
            </div>
          </div>
        ) : showCompleted ? (
          <div className="space-y-2">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2.5">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-50 dark:bg-emerald-950/60">
                  <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                </span>
                <div>
                  <h4 className="text-sm font-semibold text-[#06141B] dark:text-[#F1F5F9]">
                    Sync Complete
                  </h4>
                  <p className="text-xs text-[#64748B] dark:text-[#9BA8AB]">
                    {completedMessage || "All workspace sources are fully indexed."}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={dismissCompleted}
                className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-[#162736] dark:hover:text-zinc-200"
                aria-label="Dismiss notification"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="flex justify-end pt-1">
              <Link
                href="/dashboard/queue"
                className="text-xs font-medium text-emerald-600 hover:text-emerald-700 dark:text-emerald-400"
              >
                View details &rarr;
              </Link>
            </div>
          </div>
        ) : null}
      </div>
    </aside>
  );
}

