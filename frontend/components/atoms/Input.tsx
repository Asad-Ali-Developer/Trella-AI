import { InputHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/cn";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => {
    return (
      <input
        ref={ref}
        className={cn(
          "h-10 w-full rounded-xl border border-[#9BA8AB] bg-white px-3.5 text-sm text-[#06141B] transition outline-none",
          "placeholder:text-[#4A5C6A]/70",
          "focus:border-[#253745] focus:ring-2 focus:ring-[#253745]/20",
          "dark:border-[#253745] dark:bg-[#11212D] dark:text-[#CCD0CF] dark:placeholder:text-[#9BA8AB]/50 dark:focus:border-[#4A5C6A] dark:focus:ring-[#4A5C6A]/20",
          className,
        )}
        {...props}
      />
    );
  },
);

Input.displayName = "Input";
