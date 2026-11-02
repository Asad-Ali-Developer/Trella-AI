import { ButtonHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

const variants: Record<Variant, string> = {
  primary:
    "bg-[#253745] text-[#CCD0CF] border border-[#4A5C6A] hover:bg-[#11212D] dark:bg-[#253745] dark:hover:bg-[#4A5C6A] shadow-sm",
  secondary:
    "bg-white dark:bg-[#11212D] text-[#06141B] dark:text-[#CCD0CF] border border-[#9BA8AB] dark:border-[#253745] hover:bg-[#CCD0CF]/30 dark:hover:bg-[#253745]",
  ghost:
    "bg-transparent text-[#4A5C6A] dark:text-[#9BA8AB] hover:bg-[#CCD0CF]/40 dark:hover:bg-[#253745] hover:text-[#06141B] dark:hover:text-[#CCD0CF]",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", type = "button", ...props }, ref) => {
    return (
      <button
        ref={ref}
        type={type}
        className={cn(
          "inline-flex h-9 items-center justify-center rounded-xl px-3.5 text-sm font-medium transition-all active:scale-[0.99]",
          "disabled:pointer-events-none disabled:opacity-50",
          variants[variant],
          className,
        )}
        {...props}
      />
    );
  },
);

Button.displayName = "Button";
