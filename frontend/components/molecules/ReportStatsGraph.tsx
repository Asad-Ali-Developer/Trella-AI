"use client";

import React, { useMemo, useState } from "react";
import { BarChart3, Calendar, CheckCircle2, Flame, TrendingUp } from "lucide-react";

import type { Run } from "@/lib/types";

interface ReportStatsGraphProps {
  activityMap?: Record<string, number>;
  runs?: Run[];
}

interface HoveredBar {
  weekLabel: string;
  count: number;
  x: number;
  y: number;
}

export function ReportStatsGraph({ activityMap = {}, runs = [] }: ReportStatsGraphProps) {
  const [hoveredBar, setHoveredBar] = useState<HoveredBar | null>(null);

  const { weeklyData, maxCount, totalLast30Days, busiestDayFormatted, activeDaysCount, completionRate } =
    useMemo(() => {
      const today = new Date();
      // Calculate 12 weeks of data
      const weeks: Array<{ label: string; rangeText: string; count: number }> = [];
      const currentDayOfWeek = today.getDay(); // 0 = Sun
      const startOfCurrentWeek = new Date(today);
      startOfCurrentWeek.setDate(today.getDate() - currentDayOfWeek);
      startOfCurrentWeek.setHours(0, 0, 0, 0);

      for (let i = 11; i >= 0; i--) {
        const weekStart = new Date(startOfCurrentWeek);
        weekStart.setDate(startOfCurrentWeek.getDate() - i * 7);

        const weekEnd = new Date(weekStart);
        weekEnd.setDate(weekStart.getDate() + 6);

        let count = 0;
        for (let d = 0; d < 7; d++) {
          const day = new Date(weekStart);
          day.setDate(weekStart.getDate() + d);
          const y = day.getFullYear();
          const m = String(day.getMonth() + 1).padStart(2, "0");
          const dt = String(day.getDate()).padStart(2, "0");
          count += activityMap[`${y}-${m}-${dt}`] || 0;
        }

        const label = weekStart.toLocaleDateString("en-US", { month: "short", day: "numeric" });
        const endLabel = weekEnd.toLocaleDateString("en-US", { month: "short", day: "numeric" });
        weeks.push({
          label,
          rangeText: `${label} – ${endLabel}`,
          count,
        });
      }

      const max = Math.max(...weeks.map((w) => w.count), 1);

      // Last 30 days total
      let last30 = 0;
      for (let i = 0; i < 30; i++) {
        const d = new Date(today);
        d.setDate(today.getDate() - i);
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const dt = String(d.getDate()).padStart(2, "0");
        last30 += activityMap[`${y}-${m}-${dt}`] || 0;
      }

      // Busiest day
      let busiestDay = "";
      let highestCount = 0;
      let activeDays = 0;

      for (const [dateStr, cnt] of Object.entries(activityMap)) {
        if (cnt > 0) activeDays++;
        if (cnt > highestCount) {
          highestCount = cnt;
          busiestDay = dateStr;
        }
      }

      let busiestFormatted = "—";
      if (busiestDay) {
        const [yr, mo, da] = busiestDay.split("-").map(Number);
        const bDate = new Date(yr, mo - 1, da);
        busiestFormatted = `${bDate.toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
        })} (${highestCount})`;
      }

      // Completion Rate from runs
      const completed = runs.filter((r) => r.status === "completed").length;
      const rate = runs.length > 0 ? Math.round((completed / runs.length) * 100) : 100;

      return {
        weeklyData: weeks,
        maxCount: max,
        totalLast30Days: last30,
        busiestDayFormatted: busiestFormatted,
        activeDaysCount: activeDays,
        completionRate: rate,
      };
    }, [activityMap, runs]);

  return (
    <div className="flex h-full flex-col justify-between rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-[#253745] dark:bg-[#11212D]">
      {/* Top Header */}
      <div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-[#9BA8AB]">
            <TrendingUp className="h-4 w-4 text-emerald-500 dark:text-[#34D399]" />
            Report Velocity
          </div>
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 border border-emerald-200 dark:bg-emerald-950/40 dark:text-[#34D399] dark:border-emerald-800/40">
            12-Week Trajectory
          </span>
        </div>

        <div className="mt-3 flex items-baseline gap-2">
          <span className="text-3xl font-extrabold tracking-tight text-zinc-900 dark:text-[#F1F5F9]">
            {totalLast30Days}
          </span>
          <span className="text-xs text-zinc-500 dark:text-[#9BA8AB]">
            reports generated in past 30 days
          </span>
        </div>
      </div>

      {/* Modern Minimalistic Bar Graph */}
      <div className="relative my-4">
        <div className="relative flex h-28 items-end gap-1.5 pt-4">
          {weeklyData.map((week, idx) => {
            const heightPercent =
              week.count === 0 ? 8 : Math.max(16, Math.round((week.count / maxCount) * 100));

            return (
              <div
                key={idx}
                className="group relative flex flex-1 flex-col items-center h-full justify-end"
                onMouseEnter={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  setHoveredBar({
                    weekLabel: week.rangeText,
                    count: week.count,
                    x: rect.left + rect.width / 2,
                    y: rect.top,
                  });
                }}
                onMouseLeave={() => setHoveredBar(null)}
              >
                <div
                  style={{ height: `${heightPercent}%` }}
                  className={`w-full rounded-t-md transition-all duration-200 ${
                    week.count > 0
                      ? "bg-gradient-to-t from-emerald-600 to-emerald-400 group-hover:from-emerald-500 group-hover:to-emerald-300 dark:from-[#006d32] dark:to-[#39d353] dark:group-hover:to-[#44e85f]"
                      : "bg-zinc-100 dark:bg-[#162736] group-hover:bg-zinc-200 dark:group-hover:bg-[#1f364a]"
                  }`}
                />
              </div>
            );
          })}
        </div>

        {/* Floating Tooltip */}
        {hoveredBar && (
          <div
            style={{
              position: "fixed",
              left: `${hoveredBar.x}px`,
              top: `${hoveredBar.y - 10}px`,
              transform: "translate(-50%, -100%)",
            }}
            className="pointer-events-none z-50 whitespace-nowrap rounded-lg border border-[#30363d] bg-[#21262d] px-3 py-1.5 text-xs text-[#f0f6fc] shadow-xl"
          >
            <div className="font-semibold text-emerald-400">
              {hoveredBar.count} {hoveredBar.count === 1 ? "report generated" : "reports generated"}
            </div>
            <div className="text-[11px] text-zinc-400">{hoveredBar.weekLabel}</div>
          </div>
        )}

        {/* Graph Bottom Axis Labels */}
        <div className="mt-2 flex items-center justify-between text-[10px] text-zinc-400 dark:text-[#9BA8AB]">
          <span>{weeklyData[0]?.label}</span>
          <span>12 Weeks</span>
          <span>Today</span>
        </div>
      </div>

      {/* Mini Stats Footer */}
      <div className="grid grid-cols-3 gap-2 border-t border-zinc-100 pt-3 dark:border-[#253745]">
        <div>
          <div className="text-[10px] text-zinc-400 dark:text-[#9BA8AB]">Busiest Day</div>
          <div className="mt-0.5 truncate text-xs font-semibold text-zinc-800 dark:text-[#CCD0CF]">
            {busiestDayFormatted}
          </div>
        </div>

        <div>
          <div className="text-[10px] text-zinc-400 dark:text-[#9BA8AB]">Active Days</div>
          <div className="mt-0.5 text-xs font-semibold text-zinc-800 dark:text-[#CCD0CF]">
            {activeDaysCount} days
          </div>
        </div>

        <div>
          <div className="text-[10px] text-zinc-400 dark:text-[#9BA8AB]">Success Rate</div>
          <div className="mt-0.5 text-xs font-semibold text-emerald-600 dark:text-[#34D399]">
            {completionRate}%
          </div>
        </div>
      </div>
    </div>
  );
}

