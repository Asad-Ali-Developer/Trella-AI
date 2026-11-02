"use client";

import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/cn";

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  totalItems?: number;
  pageSize?: number;
  itemName?: string;
  className?: string;
}

export function Pagination({
  currentPage,
  totalPages,
  onPageChange,
  totalItems,
  pageSize,
  itemName = "reports",
  className,
}: PaginationProps) {
  if (totalPages <= 1 && (!totalItems || totalItems <= (pageSize || 10))) {
    return null;
  }

  // Calculate start & end item indices for "Showing X to Y of Z"
  const startItem = totalItems !== undefined && pageSize !== undefined
    ? Math.min((currentPage - 1) * pageSize + 1, totalItems)
    : undefined;
  const endItem = totalItems !== undefined && pageSize !== undefined
    ? Math.min(currentPage * pageSize, totalItems)
    : undefined;

  // Build page number list with ellipsis for large page counts
  const getPageNumbers = (): (number | string)[] => {
    if (totalPages <= 7) {
      return Array.from({ length: totalPages }, (_, i) => i + 1);
    }

    const pages: (number | string)[] = [];
    if (currentPage <= 4) {
      pages.push(1, 2, 3, 4, 5, "…", totalPages);
    } else if (currentPage >= totalPages - 3) {
      pages.push(1, "…", totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1, totalPages);
    } else {
      pages.push(1, "…", currentPage - 1, currentPage, currentPage + 1, "…", totalPages);
    }
    return pages;
  };

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-between gap-4 py-4 sm:flex-row",
        className
      )}
    >
      {/* Item range summary */}
      <div className="text-xs text-zinc-500 dark:text-[#9BA8AB]">
        {totalItems !== undefined && startItem !== undefined && endItem !== undefined ? (
          <span>
            Showing <strong className="font-semibold text-zinc-800 dark:text-[#F1F5F9]">{startItem}</strong> to{" "}
            <strong className="font-semibold text-zinc-800 dark:text-[#F1F5F9]">{endItem}</strong> of{" "}
            <strong className="font-semibold text-zinc-800 dark:text-[#F1F5F9]">{totalItems}</strong> {itemName}
          </span>
        ) : (
          <span>
            Page <strong className="font-semibold text-zinc-800 dark:text-[#F1F5F9]">{currentPage}</strong> of{" "}
            <strong className="font-semibold text-zinc-800 dark:text-[#F1F5F9]">{totalPages}</strong>
          </span>
        )}
      </div>

      {/* Page navigation controls */}
      <nav aria-label="Pagination Navigation" className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage <= 1}
          aria-label="Previous Page"
          className="inline-flex h-8 items-center gap-1 rounded-lg border border-zinc-200 bg-white px-2.5 text-xs font-medium text-zinc-700 shadow-xs transition hover:bg-zinc-50 disabled:opacity-40 disabled:cursor-not-allowed dark:border-[#253745] dark:bg-[#162736] dark:text-[#CCD0CF] dark:hover:bg-[#253745] dark:hover:text-white"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Prev</span>
        </button>

        <div className="flex items-center gap-1">
          {getPageNumbers().map((page, idx) => {
            if (typeof page === "string") {
              return (
                <span
                  key={`ellipsis-${idx}`}
                  className="px-2 text-xs text-zinc-400 dark:text-[#4A5C6A]"
                >
                  {page}
                </span>
              );
            }

            const isActive = page === currentPage;
            return (
              <button
                key={`page-${page}`}
                type="button"
                onClick={() => onPageChange(page)}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-lg text-xs font-semibold transition",
                  isActive
                    ? "bg-[#253745] text-white shadow-xs dark:bg-[#253745] dark:text-white dark:border dark:border-[#4A5C6A]"
                    : "border border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50 dark:border-[#253745] dark:bg-[#162736] dark:text-[#CCD0CF] dark:hover:bg-[#253745] dark:hover:text-white"
                )}
              >
                {page}
              </button>
            );
          })}
        </div>

        <button
          type="button"
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage >= totalPages}
          aria-label="Next Page"
          className="inline-flex h-8 items-center gap-1 rounded-lg border border-zinc-200 bg-white px-2.5 text-xs font-medium text-zinc-700 shadow-xs transition hover:bg-zinc-50 disabled:opacity-40 disabled:cursor-not-allowed dark:border-[#253745] dark:bg-[#162736] dark:text-[#CCD0CF] dark:hover:bg-[#253745] dark:hover:text-white"
        >
          <span className="hidden sm:inline">Next</span>
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </nav>
    </div>
  );
}
