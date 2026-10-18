import { ButtonHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

const variants: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-foreground hover:bg-indigo-600 shadow-sm",
  secondary:
    "bg-white text-foreground border border-border hover:bg-muted",
  ghost: "bg-transparent text-muted-foreground hover:bg-muted hover:text-foreground",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", type = "button", ...props }, ref) => {
    return (
      <button
        ref={ref}
        type={type}
        className={cn(
          "inline-flex h-9 items-center justify-center rounded-md px-3.5 text-sm font-medium transition-colors",
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
