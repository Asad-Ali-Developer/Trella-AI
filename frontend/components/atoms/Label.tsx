import { LabelHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export function Label({ className, ...props }: LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn("text-xs font-semibold text-[#06141B] dark:text-[#CCD0CF]", className)}
      {...props}
    />
  );
}
