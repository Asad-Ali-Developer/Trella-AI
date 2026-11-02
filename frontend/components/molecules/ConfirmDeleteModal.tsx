"use client";

import React, { useEffect } from "react";
import { AlertTriangle, LoaderCircle, Trash2 } from "lucide-react";
import { Button } from "@/components/atoms/Button";
import { Portal } from "@/components/atoms/Portal";

interface ConfirmDeleteModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void> | void;
  title?: string;
  description?: string;
  itemDetails?: {
    title?: string;
    subtitle?: string;
  };
  isLoading?: boolean;
}

export function ConfirmDeleteModal({
  isOpen,
  onClose,
  onConfirm,
  title = "Delete Report",
  description = "Are you sure you want to delete this report? This action cannot be undone and will permanently remove the report and all extracted insights.",
  itemDetails,
  isLoading = false,
}: ConfirmDeleteModalProps) {
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
    <Portal>
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
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-rose-200 bg-rose-50 text-rose-600 dark:border-rose-900/60 dark:bg-rose-950/50 dark:text-rose-400">
            <Trash2 className="h-6 w-6" />
          </div>

          <div className="flex-1 min-w-0">
            <h3 className="text-lg font-bold text-zinc-950 dark:text-[#F1F5F9]">{title}</h3>
            <p className="mt-1.5 text-xs leading-relaxed text-zinc-500 dark:text-[#9BA8AB]">
              {description}
            </p>

            {itemDetails && (itemDetails.title || itemDetails.subtitle) && (
              <div className="mt-3.5 rounded-xl border border-zinc-100 bg-zinc-50 p-3 text-xs dark:border-[#253745] dark:bg-[#162736]">
                {itemDetails.title && (
                  <p className="font-semibold text-zinc-800 dark:text-[#F1F5F9] truncate">
                    {itemDetails.title}
                  </p>
                )}
                {itemDetails.subtitle && (
                  <p className="mt-0.5 text-zinc-400 dark:text-[#9BA8AB] truncate">
                    {itemDetails.subtitle}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-2.5 pt-2 border-t border-zinc-100 dark:border-[#253745]">
          <Button
            type="button"
            variant="ghost"
            onClick={onClose}
            disabled={isLoading}
            className="rounded-xl px-4 py-2 text-xs font-semibold text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-[#CCD0CF] dark:hover:bg-[#253745] dark:hover:text-white"
          >
            Cancel
          </Button>

          <Button
            type="button"
            onClick={() => void onConfirm()}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-rose-700 dark:bg-rose-600 dark:hover:bg-rose-700 disabled:opacity-50"
          >
            {isLoading ? (
              <>
                <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                Deleting…
              </>
            ) : (
              <>
                <Trash2 className="h-3.5 w-3.5" />
                Delete Report
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
    </Portal>
  );
}
