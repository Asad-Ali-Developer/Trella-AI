"use client";

import React from "react";
import { Skeleton } from "@/components/atoms/Skeleton";

export function DashboardPageSkeleton() {
  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 pb-10">
      {/* Header */}
      <div className="flex flex-col gap-4 border-b border-zinc-200 pb-6 sm:flex-row sm:items-end sm:justify-between dark:border-[#253745]">
        <div className="space-y-2">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-8 w-64" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-9 w-32 rounded-xl" />
          <Skeleton className="h-9 w-32 rounded-xl" />
        </div>
      </div>

      {/* KPI Stats */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div
            key={i}
            className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-[#253745] dark:bg-[#11212D]"
          >
            <div className="flex items-center justify-between">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-8 w-8 rounded-full" />
            </div>
            <Skeleton className="mt-4 h-7 w-16" />
            <Skeleton className="mt-2 h-3.5 w-36" />
          </div>
        ))}
      </div>

      {/* Featured Workspace */}
      <div className="rounded-2xl border border-zinc-200 bg-white p-6 dark:border-[#253745] dark:bg-[#11212D]">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <Skeleton className="h-12 w-12 rounded-2xl" />
            <div className="space-y-2">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-6 w-48" />
            </div>
          </div>
          <Skeleton className="h-9 w-36 rounded-xl" />
        </div>
      </div>

      {/* Secondary Banner */}
      <div className="rounded-2xl border border-zinc-200 bg-white p-6 dark:border-[#253745] dark:bg-[#11212D]">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="mt-2 h-4 w-full max-w-2xl" />
      </div>
    </div>
  );
}

export function ContextPageSkeleton() {
  return (
    <div className="mx-auto w-full max-w-6xl space-y-7 pb-10">
      {/* Header */}
      <div className="flex flex-col gap-5 border-b border-zinc-200 pb-6 sm:flex-row sm:items-end sm:justify-between dark:border-[#253745]">
        <div className="space-y-2">
          <Skeleton className="h-4 w-36" />
          <Skeleton className="h-8 w-60" />
          <Skeleton className="h-4 w-full max-w-xl" />
        </div>
        <Skeleton className="h-10 w-36 rounded-xl" />
      </div>

      {/* Action Buttons */}
      <div className="flex gap-2">
        <Skeleton className="h-9 w-36 rounded-xl" />
        <Skeleton className="h-9 w-44 rounded-xl" />
      </div>

      {/* Stats Grid */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div
            key={i}
            className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-[#253745] dark:bg-[#11212D]"
          >
            <Skeleton className="h-4 w-28" />
            <Skeleton className="mt-3 h-7 w-16" />
          </div>
        ))}
      </div>

      {/* People Section */}
      <div className="rounded-2xl border border-zinc-200 bg-white p-6 dark:border-[#253745] dark:bg-[#11212D]">
        <Skeleton className="h-5 w-44" />
        <Skeleton className="mt-1.5 h-3.5 w-72" />
        <div className="mt-5 space-y-3">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="flex items-center justify-between py-2 border-b border-zinc-100 dark:border-[#253745] last:border-0">
              <div className="space-y-1.5">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-24" />
              </div>
              <Skeleton className="h-9 w-36 rounded-xl" />
            </div>
          ))}
        </div>
      </div>

      {/* Search Section */}
      <div className="rounded-2xl border border-zinc-200 bg-white p-6 dark:border-[#253745] dark:bg-[#11212D]">
        <Skeleton className="h-5 w-36" />
        <Skeleton className="mt-1.5 h-3.5 w-64" />
        <div className="mt-4 flex gap-2">
          <Skeleton className="h-10 flex-1 rounded-xl" />
          <Skeleton className="h-10 w-28 rounded-xl" />
        </div>
      </div>

      {/* Included Accounts */}
      <div className="rounded-2xl border border-zinc-200 bg-white p-6 dark:border-[#253745] dark:bg-[#11212D]">
        <Skeleton className="h-5 w-52" />
        <div className="mt-5 grid gap-3 md:grid-cols-2">
          <Skeleton className="h-20 rounded-xl" />
          <Skeleton className="h-20 rounded-xl" />
        </div>
      </div>
    </div>
  );
}

export function ClientsPageSkeleton() {
  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 pb-10">
      {/* Header */}
      <div className="flex flex-col gap-4 border-b border-zinc-200 pb-6 sm:flex-row sm:items-end sm:justify-between dark:border-[#253745]">
        <div className="space-y-2">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-4 w-96" />
        </div>
        <Skeleton className="h-10 w-32 rounded-xl" />
      </div>

      {/* Metrics Row */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div
            key={i}
            className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-[#253745] dark:bg-[#11212D]"
          >
            <Skeleton className="h-4 w-28" />
            <Skeleton className="mt-3 h-7 w-12" />
          </div>
        ))}
      </div>

      {/* Search Input */}
      <Skeleton className="h-11 w-full max-w-md rounded-xl" />

      {/* Client Dossier Cards */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {[...Array(3)].map((_, i) => (
          <div
            key={i}
            className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-[#253745] dark:bg-[#11212D]"
          >
            <div className="flex items-center gap-3">
              <Skeleton className="h-10 w-10 rounded-full" />
              <div className="space-y-1.5 flex-1">
                <Skeleton className="h-4 w-28" />
                <Skeleton className="h-3 w-20" />
              </div>
              <Skeleton className="h-6 w-16 rounded-full" />
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2 border-y border-zinc-100 py-3 dark:border-[#253745]">
              <Skeleton className="h-8 rounded-lg" />
              <Skeleton className="h-8 rounded-lg" />
              <Skeleton className="h-8 rounded-lg" />
            </div>
            <Skeleton className="mt-4 h-9 w-full rounded-xl" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function ReportsPageSkeleton() {
  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 pb-10">
      {/* Header */}
      <div className="flex flex-col gap-4 border-b border-zinc-200 pb-6 sm:flex-row sm:items-end sm:justify-between dark:border-[#253745]">
        <div className="space-y-2">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-8 w-60" />
          <Skeleton className="h-4 w-96" />
        </div>
        <Skeleton className="h-10 w-36 rounded-xl" />
      </div>

      {/* KPI Stats */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div
            key={i}
            className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-[#253745] dark:bg-[#11212D]"
          >
            <Skeleton className="h-4 w-24" />
            <Skeleton className="mt-3 h-7 w-16" />
          </div>
        ))}
      </div>

      {/* Filter Strip */}
      <div className="flex items-center justify-between border-b border-zinc-200 pb-4 dark:border-[#253745]">
        <div className="flex gap-3">
          <Skeleton className="h-9 w-32 rounded-xl" />
          <Skeleton className="h-9 w-36 rounded-xl" />
        </div>
        <Skeleton className="h-4 w-32" />
      </div>

      {/* Reports List */}
      <div className="space-y-3">
        {[...Array(4)].map((_, i) => (
          <div
            key={i}
            className="flex items-center justify-between rounded-2xl border border-zinc-200 bg-white p-5 dark:border-[#253745] dark:bg-[#11212D]"
          >
            <div className="flex items-center gap-4">
              <Skeleton className="h-10 w-10 rounded-xl" />
              <div className="space-y-2">
                <Skeleton className="h-4 w-44" />
                <Skeleton className="h-3 w-64" />
              </div>
            </div>
            <div className="flex items-center gap-4">
              <Skeleton className="h-8 w-24 rounded-lg" />
              <Skeleton className="h-8 w-28 rounded-xl" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function SkillsPageSkeleton() {
  return (
    <div className="mx-auto max-w-6xl space-y-8 p-6 md:p-8">
      {/* Header */}
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="space-y-2">
          <Skeleton className="h-6 w-52 rounded-full" />
          <Skeleton className="h-8 w-60" />
          <Skeleton className="h-4 w-96" />
        </div>
        <Skeleton className="h-11 w-44 rounded-xl" />
      </div>

      {/* Skill Cards */}
      <div className="space-y-3">
        <Skeleton className="h-4 w-44" />
        <div className="grid gap-4 md:grid-cols-2">
          {[...Array(2)].map((_, i) => (
            <div
              key={i}
              className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-[#253745] dark:bg-[#11212D]"
            >
              <div className="flex items-center gap-3">
                <Skeleton className="h-10 w-10 rounded-xl" />
                <div className="space-y-1.5 flex-1">
                  <Skeleton className="h-4 w-36" />
                  <Skeleton className="h-3 w-28" />
                </div>
              </div>
              <Skeleton className="mt-4 h-10 w-full" />
              <Skeleton className="mt-4 h-3 w-48" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function WorkspacesPageSkeleton() {
  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 pb-10">
      {/* Header */}
      <div className="flex flex-col gap-5 border-b border-zinc-200 pb-6 sm:flex-row sm:items-end sm:justify-between dark:border-[#253745]">
        <div className="space-y-2">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-8 w-44" />
          <Skeleton className="h-4 w-80" />
        </div>
        <Skeleton className="h-11 w-40 rounded-xl" />
      </div>

      {/* Grid of Workspaces */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {[...Array(3)].map((_, i) => (
          <div
            key={i}
            className="flex min-h-64 flex-col rounded-2xl border border-zinc-200 bg-white p-5 dark:border-[#253745] dark:bg-[#11212D]"
          >
            <div className="flex items-start justify-between">
              <Skeleton className="h-11 w-11 rounded-xl" />
              <Skeleton className="h-6 w-28 rounded-full" />
            </div>
            <Skeleton className="mt-5 h-5 w-40" />
            <Skeleton className="mt-2 h-3.5 w-28" />
            <Skeleton className="mt-3 h-10 w-full" />
            <div className="mt-auto border-t border-zinc-100 pt-4 dark:border-[#253745] flex justify-between">
              <Skeleton className="h-6 w-20" />
              <Skeleton className="h-6 w-32" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AppsPageSkeleton() {
  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 pb-10">
      {/* Header */}
      <div className="border-b border-zinc-200 pb-6 dark:border-[#253745]">
        <Skeleton className="h-4 w-36" />
        <Skeleton className="mt-2 h-8 w-56" />
        <Skeleton className="mt-2 h-4 w-full max-w-xl" />
      </div>

      {/* App Groups */}
      <div className="space-y-8">
        {/* Work sources */}
        <div>
          <div className="mb-4 flex items-end justify-between">
            <div className="space-y-1.5">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-4 w-64" />
            </div>
            <Skeleton className="h-6 w-36 rounded-full" />
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            {[...Array(3)].map((_, i) => (
              <div
                key={i}
                className="flex min-h-56 flex-col rounded-2xl border border-zinc-200 bg-white p-5 dark:border-[#253745] dark:bg-[#11212D]"
              >
                <div className="flex items-start justify-between">
                  <Skeleton className="h-12 w-12 rounded-2xl" />
                  <Skeleton className="h-6 w-20 rounded-full" />
                </div>
                <Skeleton className="mt-5 h-5 w-28" />
                <Skeleton className="mt-2 h-4 w-full" />
                <Skeleton className="mt-auto pt-5 h-4 w-28" />
              </div>
            ))}
          </div>
        </div>

        {/* Report delivery */}
        <div>
          <div className="mb-4 space-y-1.5">
            <Skeleton className="h-5 w-36" />
            <Skeleton className="h-4 w-56" />
          </div>
          <div className="max-w-md">
            <div className="flex min-h-56 flex-col rounded-2xl border border-zinc-200 bg-white p-5 dark:border-[#253745] dark:bg-[#11212D]">
              <div className="flex items-start justify-between">
                <Skeleton className="h-12 w-12 rounded-2xl" />
                <Skeleton className="h-6 w-24 rounded-full" />
              </div>
              <Skeleton className="mt-5 h-5 w-24" />
              <Skeleton className="mt-2 h-4 w-full" />
              <Skeleton className="mt-auto pt-5 h-4 w-24" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function IntegrationSettingsPageSkeleton() {
  return (
    <div className="mx-auto w-full max-w-5xl space-y-7 pb-10">
      {/* Header */}
      <div className="flex flex-col gap-4 border-b border-zinc-200 pb-6 sm:flex-row sm:items-end sm:justify-between dark:border-[#253745]">
        <div className="space-y-2">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-8 w-60" />
          <Skeleton className="h-4 w-full max-w-xl" />
        </div>
        <Skeleton className="h-10 w-36 rounded-xl" />
      </div>

      {/* Account Info Card */}
      <div className="rounded-2xl border border-zinc-200 bg-white p-6 sm:p-7 dark:border-[#253745] dark:bg-[#11212D]">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-4">
            <Skeleton className="h-14 w-14 rounded-2xl" />
            <div className="space-y-2">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-4 w-32" />
            </div>
          </div>
          <div className="flex gap-2">
            <Skeleton className="h-9 w-28 rounded-xl" />
            <Skeleton className="h-9 w-28 rounded-xl" />
          </div>
        </div>
      </div>

      {/* Items List Card */}
      <div className="rounded-2xl border border-zinc-200 bg-white p-6 dark:border-[#253745] dark:bg-[#11212D]">
        <div className="flex items-center justify-between pb-4 border-b border-zinc-100 dark:border-[#253745]">
          <Skeleton className="h-5 w-44" />
          <Skeleton className="h-9 w-32 rounded-xl" />
        </div>
        <div className="mt-4 space-y-3">
          {[...Array(3)].map((_, i) => (
            <div
              key={i}
              className="flex items-center justify-between py-3 border-b border-zinc-100 last:border-0 dark:border-[#253745]"
            >
              <div className="flex items-center gap-3">
                <Skeleton className="h-5 w-5 rounded-md" />
                <div className="space-y-1.5">
                  <Skeleton className="h-4 w-36" />
                  <Skeleton className="h-3 w-28" />
                </div>
              </div>
              <Skeleton className="h-9 w-40 rounded-xl" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
