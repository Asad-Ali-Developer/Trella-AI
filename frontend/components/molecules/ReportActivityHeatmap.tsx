"use client";

import React, { useMemo, useRef, useState } from "react";
import { Calendar } from "lucide-react";

interface ReportActivityHeatmapProps {
  activityMap?: Record<string, number>;
  totalRuns?: number;
  isLoading?: boolean;
}

interface HoveredCellState {
  dateStr: string;
  count: number;
  x: number;
  y: number;
}

function getOrdinalSuffix(n: number): string {
  if (n >= 11 && n <= 13) return "th";
  switch (n % 10) {
    case 1:
      return "st";
    case 2:
      return "nd";
    case 3:
      return "rd";
    default:
      return "th";
  }
}

function formatTooltipDate(dateStr: string): string {
  const [year, month, day] = dateStr.split("-").map(Number);
  const d = new Date(year, month - 1, day);
  const monthName = d.toLocaleString("en-US", { month: "long" });
  return `${monthName} ${day}${getOrdinalSuffix(day)}`;
}

function getCellColorClass(count: number): string {
  if (!count || count <= 0) {
    return "bg-zinc-100 border border-zinc-200/80 dark:bg-[#162736] dark:border-[#253745]/30 hover:border-zinc-400";
  }
  if (count <= 2) {
    return "bg-emerald-200 border border-emerald-300 dark:bg-[#0e4429] dark:border-emerald-900/40 hover:border-emerald-400";
  }
  if (count <= 4) {
    return "bg-emerald-400 border border-emerald-500 dark:bg-[#006d32] dark:border-emerald-800/40 hover:border-emerald-300";
  }
  if (count <= 6) {
    return "bg-emerald-600 border border-emerald-700 dark:bg-[#26a641] dark:border-emerald-600/40 hover:border-emerald-200";
  }
  return "bg-emerald-500 border border-emerald-600 dark:bg-[#39d353] dark:border-emerald-400/50 hover:border-white";
}

export function ReportActivityHeatmap({
  activityMap = {},
  totalRuns,
  isLoading = false,
}: ReportActivityHeatmapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredCell, setHoveredCell] = useState<HoveredCellState | null>(null);

  // Generate 53 weeks aligned to Sunday ending on current week
  const { weeks, monthLabels, totalInHeatmap } = useMemo(() => {
    const today = new Date();
    // 0 = Sun, 1 = Mon, ..., 6 = Sat
    const currentDayOfWeek = today.getDay();
    const startOfCurrentWeek = new Date(today);
    startOfCurrentWeek.setDate(today.getDate() - currentDayOfWeek);
    startOfCurrentWeek.setHours(0, 0, 0, 0);

    const startOfGrid = new Date(startOfCurrentWeek);
    startOfGrid.setDate(startOfCurrentWeek.getDate() - 52 * 7);

    const weeksList: Array<Array<{ date: Date; dateStr: string; isFuture: boolean }>> = [];
    const labels: Array<{ weekIndex: number; name: string }> = [];
    let lastMonth = -1;
    let sum = 0;

    for (let w = 0; w < 53; w++) {
      const weekDays: Array<{ date: Date; dateStr: string; isFuture: boolean }> = [];
      for (let d = 0; d < 7; d++) {
        const dayDate = new Date(startOfGrid);
        dayDate.setDate(startOfGrid.getDate() + w * 7 + d);

        const year = dayDate.getFullYear();
        const month = String(dayDate.getMonth() + 1).padStart(2, "0");
        const day = String(dayDate.getDate()).padStart(2, "0");
        const dateStr = `${year}-${month}-${day}`;
        const isFuture = dayDate.getTime() > today.getTime();

        if (!isFuture) {
          sum += activityMap[dateStr] || 0;
        }

        weekDays.push({ date: dayDate, dateStr, isFuture });
      }

      // Check if first day of this week changes month
      const firstDayMonth = weekDays[0].date.getMonth();
      if (firstDayMonth !== lastMonth) {
        labels.push({
          weekIndex: w,
          name: weekDays[0].date.toLocaleString("en-US", { month: "short" }),
        });
        lastMonth = firstDayMonth;
      }

      weeksList.push(weekDays);
    }

    return { weeks: weeksList, monthLabels: labels, totalInHeatmap: sum };
  }, [activityMap]);

  return (
    <div className="flex h-full flex-col justify-between rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-[#253745] dark:bg-[#11212D]">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-[#9BA8AB]">
          <Calendar className="h-4 w-4 text-emerald-500 dark:text-[#34D399]" />
          Report Generation Activity
        </div>
        <span className="text-xs text-zinc-400 dark:text-[#9BA8AB]">
          {totalInHeatmap} {totalInHeatmap === 1 ? "report" : "reports"} in past year
        </span>
      </div>

      {/* Scrollable Container with Full Width Grid */}
      <div
        ref={containerRef}
        className="relative w-full pb-1 scrollbar-thin scrollbar-thumb-zinc-700"
      >
        <div className="w-full min-w-[680px]">
          {/* Month Labels Header */}
          <div className="flex pl-7 mb-2 w-full">
            <div className="grid grid-flow-col auto-cols-fr gap-[3px] sm:gap-[4px] w-full">
              {weeks.map((_, colIdx) => {
                const label = monthLabels.find((m) => m.weekIndex === colIdx);
                return (
                  <div
                    key={colIdx}
                    className="h-3 text-[11px] leading-3 text-zinc-400 dark:text-[#9BA8AB] select-none"
                  >
                    {label ? (
                      <span className="whitespace-nowrap font-medium">{label.name}</span>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Main Grid: Left Day Labels + 53 Week Columns */}
          <div className="flex items-start gap-2 w-full">
            {/* Left Day Labels */}
            <div className="flex flex-col justify-between h-[105px] text-[10px] leading-[11px] text-zinc-400 dark:text-[#9BA8AB] select-none pt-0 shrink-0">
              <span className="h-3 w-5" /> {/* Sun */}
              <span className="h-3 w-5 font-medium">Mon</span>
              <span className="h-3 w-5" /> {/* Tue */}
              <span className="h-3 w-5 font-medium">Wed</span>
              <span className="h-3 w-5" /> {/* Thu */}
              <span className="h-3 w-5 font-medium">Fri</span>
              <span className="h-3 w-5" /> {/* Sat */}
            </div>

            {/* Weeks Columns - Auto stretching to fill 100% width */}
            <div className="grid grid-flow-col auto-cols-fr gap-[3px] sm:gap-[4px] w-full">
              {weeks.map((week, weekIdx) => (
                <div key={weekIdx} className="flex flex-col gap-[3px] sm:gap-[4px] w-full">
                  {week.map(({ dateStr, isFuture }) => {
                    const count = activityMap[dateStr] || 0;
                    if (isFuture) {
                      return (
                        <div
                          key={dateStr}
                          className="w-full aspect-square rounded-[2px] opacity-0 pointer-events-none"
                        />
                      );
                    }

                    return (
                      <div
                        key={dateStr}
                        onMouseEnter={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          setHoveredCell({
                            dateStr,
                            count,
                            x: rect.left + rect.width / 2,
                            y: rect.top,
                          });
                        }}
                        onMouseLeave={() => setHoveredCell(null)}
                        className={`w-full aspect-square min-w-[10px] rounded-[2px] transition-all cursor-pointer ${getCellColorClass(
                          count,
                        )}`}
                      />
                    );
                  })}
                </div>
              ))}
            </div>
          </div>

          {/* Floating Tooltip */}
          {hoveredCell && (
            <div
              style={{
                position: "fixed",
                left: `${hoveredCell.x}px`,
                top: `${hoveredCell.y - 8}px`,
                transform: "translate(-50%, -100%)",
              }}
              className="pointer-events-none z-50 whitespace-nowrap rounded-lg border border-[#30363d] bg-[#21262d] px-3 py-1.5 text-xs font-normal text-[#f0f6fc] shadow-xl"
            >
              {hoveredCell.count === 0
                ? "No reports generated"
                : `${hoveredCell.count} ${
                    hoveredCell.count === 1 ? "report generated" : "reports generated"
                  }`}{" "}
              on {formatTooltipDate(hoveredCell.dateStr)}.
            </div>
          )}

          {/* Bottom Bar: Link & Legend */}
          <div className="mt-4 flex flex-wrap items-center justify-between gap-4 pt-1 text-xs text-zinc-500 dark:text-[#9BA8AB]">
            <a
              href="#reports-info"
              onClick={(e) => e.preventDefault()}
              className="hover:text-zinc-700 dark:hover:text-zinc-300 transition-colors cursor-default"
            >
              Learn how reports generated are counted
            </a>

            <div className="flex items-center gap-1.5">
              <span>Less</span>
              <span
                className="h-[11px] w-[11px] rounded-[2px] bg-zinc-100 border border-zinc-200/80 dark:bg-[#162736] dark:border-[#253745]/30"
                title="0 reports generated"
              />
              <span
                className="h-[11px] w-[11px] rounded-[2px] bg-emerald-200 border border-emerald-300 dark:bg-[#0e4429] dark:border-emerald-900/40"
                title="1-2 reports generated"
              />
              <span
                className="h-[11px] w-[11px] rounded-[2px] bg-emerald-400 border border-emerald-500 dark:bg-[#006d32] dark:border-emerald-800/40"
                title="3-4 reports generated"
              />
              <span
                className="h-[11px] w-[11px] rounded-[2px] bg-emerald-600 border border-emerald-700 dark:bg-[#26a641] dark:border-emerald-600/40"
                title="5-6 reports generated"
              />
              <span
                className="h-[11px] w-[11px] rounded-[2px] bg-emerald-500 border border-emerald-600 dark:bg-[#39d353] dark:border-emerald-400/50"
                title="7+ reports generated"
              />
              <span>More</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
