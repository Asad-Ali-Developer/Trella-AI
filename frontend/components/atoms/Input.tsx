import { InputHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/cn";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => {
    return (
      <input
        ref={ref}
        className={cn(
          "h-9 w-full rounded-md border border-border bg-white px-3 text-sm text-foreground",
          "placeholder:text-muted-foreground outline-none transition",
          "focus:border-accent focus:ring-2 focus:ring-indigo-100",
          className,
        )}
        {...props}
      />
    );
  },
);

Input.displayName = "Input";
