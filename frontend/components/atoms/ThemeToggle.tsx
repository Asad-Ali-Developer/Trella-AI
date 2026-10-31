"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { useTheme } from "@/components/providers/ThemeProvider";
import { cn } from "@/lib/cn";

interface ThemeToggleProps {
  className?: string;
  showLabel?: boolean;
}

export function ThemeToggle({ className, showLabel = false }: ThemeToggleProps) {
  const { isDark, toggleTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <div
        className={cn(
          "inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[#9BA8AB] bg-white opacity-50 dark:border-[#253745] dark:bg-[#11212D]",
          className,
        )}
      />
    );
  }

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className={cn(
        "group relative inline-flex items-center gap-2.5 rounded-xl border border-[#9BA8AB] bg-white px-2.5 py-1.5 text-sm font-medium text-[#06141B] shadow-sm transition-all hover:bg-[#CCD0CF]/40 dark:border-[#253745] dark:bg-[#11212D] dark:text-[#CCD0CF] dark:hover:bg-[#253745]",
        !showLabel && "h-9 w-9 justify-center px-0 py-0",
        className,
      )}
    >
      <div className="relative flex h-4 w-4 items-center justify-center">
        {isDark ? (
          <Moon className="h-4 w-4 text-[#CCD0CF] transition-transform duration-300 group-hover:-rotate-12" />
        ) : (
          <Sun className="h-4 w-4 text-[#253745] transition-transform duration-300 group-hover:rotate-45" />
        )}
      </div>
      {showLabel ? (
        <span className="text-xs font-semibold">
          {isDark ? "Dark theme" : "Light theme"}
        </span>
      ) : null}
    </button>
  );
}
