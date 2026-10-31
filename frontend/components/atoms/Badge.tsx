import { HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export function Badge({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border border-[#9BA8AB] bg-[#CCD0CF] px-2.5 py-0.5 text-[11px] font-semibold tracking-wide text-[#06141B] uppercase dark:border-[#4A5C6A] dark:bg-[#253745] dark:text-[#CCD0CF]",
        className,
      )}
      {...props}
    />
  );
}
