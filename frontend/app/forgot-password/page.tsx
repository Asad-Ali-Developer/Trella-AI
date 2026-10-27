"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { isAxiosError } from "axios";

import { Button } from "@/components/atoms/Button";
import { FormField } from "@/components/molecules/FormField";
import { AuthTemplate } from "@/components/templates/AuthTemplate";
import { authService } from "@/services/AuthService";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);
    try {
      await authService.requestPasswordReset(email);
      setMessage("If that email belongs to an account, a reset link will be sent.");
    } catch (requestError: unknown) {
      const detail = isAxiosError<{ detail?: unknown }>(requestError)
        ? requestError.response?.data?.detail
        : undefined;
      setError(typeof detail === "string" ? detail : "Could not request a reset link. Try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthTemplate title="Reset password" subtitle="We’ll email you a link if the account exists.">
      <form onSubmit={onSubmit} className="space-y-4">
        <FormField
          id="email"
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        {message ? <p role="status" className="text-sm text-emerald-700">{message}</p> : null}
        {error ? <p role="alert" className="text-sm text-red-600">{error}</p> : null}
        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? "Sending…" : "Send reset link"}
        </Button>
        <p className="text-center text-sm text-muted-foreground">
          Remembered it?{" "}
          <Link href="/login" className="font-medium text-accent hover:underline">
            Sign in
          </Link>
        </p>
      </form>
    </AuthTemplate>
  );
}
