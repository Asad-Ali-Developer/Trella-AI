"use client";

import {
  AlertCircle,
  CheckCircle2,
  Clock,
  ExternalLink,
  Mail,
  MessageSquare,
  MinusCircle,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";

import { Pagination } from "@/components/molecules/Pagination";
import type { Delivery } from "@/lib/types";

interface DeliveriesTableProps {
  deliveries: Delivery[];
  total: number;
  currentPage: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  loading: boolean;
}

export function DeliveriesTable({
  deliveries,
  total,
  currentPage,
  pageSize,
  onPageChange,
  loading,
}: DeliveriesTableProps) {
  function renderStatusBadge(status: string) {
    switch (status) {
      case "sent":
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/30 dark:text-emerald-400">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Delivered
          </span>
        );
      case "skipped":
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700 dark:border-slate-800 dark:bg-slate-800/40 dark:text-slate-300">
            <MinusCircle className="h-3.5 w-3.5" />
            Skipped (Delta)
          </span>
        );
      case "failed":
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-red-200 bg-red-50 px-2.5 py-1 text-xs font-semibold text-red-700 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-400">
            <AlertCircle className="h-3.5 w-3.5" />
            Failed
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs font-semibold text-sky-700 dark:border-sky-900/40 dark:bg-sky-950/30 dark:text-sky-400">
            <Clock className="h-3.5 w-3.5" />
            Pending
          </span>
        );
    }
  }

  function renderChannelIcon(channel: string) {
    if (channel === "slack") {
      return (
        <span className="flex items-center gap-1.5 font-medium text-violet-700 dark:text-violet-400">
          <MessageSquare className="h-4 w-4" />
          Slack
        </span>
      );
    }
    return (
      <span className="flex items-center gap-1.5 font-medium text-blue-700 dark:text-blue-400">
        <Mail className="h-4 w-4" />
        Email
      </span>
    );
  }

  const totalPages = Math.ceil(total / pageSize) || 1;

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-[#4A5C6A] dark:text-[#9BA8AB]">
        <RefreshCw className="mb-2 h-6 w-6 animate-spin" />
        <p className="text-sm">Loading delivery records...</p>
      </div>
    );
  }

  if (deliveries.length === 0) {
    return (
      <div className="rounded-2xl border border-[#E2E8F0] bg-white p-12 text-center dark:border-[#253745] dark:bg-[#11212D]">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-[#F1F5F9] dark:bg-[#162736]">
          <Clock className="h-6 w-6 text-[#4A5C6A] dark:text-[#9BA8AB]" />
        </div>
        <h3 className="text-base font-semibold text-[#06141B] dark:text-[#F1F5F9]">
          No Deliveries Dispatched Yet
        </h3>
        <p className="mx-auto mt-1 max-w-sm text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">
          When your automated report schedules run, delivery logs and dispatch receipts will appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-2xl border border-[#E2E8F0] bg-white shadow-sm dark:border-[#253745] dark:bg-[#11212D]">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-[#E2E8F0] bg-[#F8FAFC] text-[11px] font-semibold uppercase tracking-wider text-[#4A5C6A] dark:border-[#253745] dark:bg-[#162736]/50 dark:text-[#9BA8AB]">
              <tr>
                <th scope="col" className="px-5 py-3.5">
                  Timestamp
                </th>
                <th scope="col" className="px-5 py-3.5">
                  Channel
                </th>
                <th scope="col" className="px-5 py-3.5">
                  Recipient
                </th>
                <th scope="col" className="px-5 py-3.5">
                  Status
                </th>
                <th scope="col" className="px-5 py-3.5">
                  Attempts
                </th>
                <th scope="col" className="px-5 py-3.5">
                  Report
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E2E8F0] dark:divide-[#253745]">
              {deliveries.map((delivery) => {
                const dateStr = delivery.delivered_at || delivery.created_at;
                const formattedDate = dateStr
                  ? new Date(dateStr).toLocaleString("en-US", {
                      month: "short",
                      day: "numeric",
                      hour: "numeric",
                      minute: "2-digit",
                    })
                  : "—";

                return (
                  <tr
                    key={delivery.id}
                    className="transition-colors hover:bg-[#F8FAFC] dark:hover:bg-[#162736]/30"
                  >
                    <td className="whitespace-nowrap px-5 py-3.5 text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">
                      {formattedDate}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-xs">
                      {renderChannelIcon(delivery.channel)}
                    </td>
                    <td className="max-w-[220px] truncate px-5 py-3.5 text-xs font-medium text-[#06141B] dark:text-[#F1F5F9]">
                      {delivery.recipient}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5">
                      {renderStatusBadge(delivery.status)}
                      {delivery.error && (
                        <p className="mt-1 max-w-xs truncate text-[10px] text-red-600 dark:text-red-400">
                          {delivery.error}
                        </p>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">
                      {delivery.attempts} {delivery.attempts === 1 ? "try" : "tries"}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-xs">
                      {delivery.run_id ? (
                        <Link
                          href={`/dashboard/reports/${delivery.run_id}`}
                          className="inline-flex items-center gap-1 font-semibold text-[#253745] hover:underline dark:text-[#88E5BE]"
                        >
                          View Report
                          <ExternalLink className="h-3.5 w-3.5" />
                        </Link>
                      ) : (
                        <span className="text-[#9BA8AB]">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {totalPages > 1 && (
        <Pagination
          currentPage={currentPage}
          totalPages={totalPages}
          onPageChange={onPageChange}
        />
      )}
    </div>
  );
}
