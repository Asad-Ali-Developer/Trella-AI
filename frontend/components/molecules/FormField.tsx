import { InputHTMLAttributes } from "react";

import { Input } from "@/components/atoms/Input";
import { Label } from "@/components/atoms/Label";

interface FormFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
}

export function FormField({ label, error, id, ...props }: FormFieldProps) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} aria-invalid={Boolean(error)} {...props} />
      {error ? <p className="text-xs text-red-600">{error}</p> : null}
    </div>
  );
}
