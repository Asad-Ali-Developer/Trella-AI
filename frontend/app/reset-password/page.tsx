"use client";

import Link from "next/link";
import { isAxiosError } from "axios";
import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/atoms/Button";
import { FormField } from "@/components/molecules/FormField";
import { AuthTemplate } from "@/components/templates/AuthTemplate";
import { authService } from "@/services/AuthService";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [complete, setComplete] = useState(false);

  useEffect(() => {
    const url = new URL(window.location.href);
    setToken(url.searchParams.get("token") ?? "");
    window.history.replaceState(null, "", url.pathname);
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    if (!token) {
      setError("This reset link is missing its token. Request a new one.");
      return;
    }

    setLoading(true);
    try {
      await authService.resetPassword(token, password);
      setComplete(true);
      window.history.replaceState(null, "", window.location.pathname);
      window.setTimeout(() => router.replace("/login"), 1500);
    } catch (requestError: unknown) {
      const detail = isAxiosError<{ detail?: unknown }>(requestError)
        ? requestError.response?.data?.detail
        : undefined;
      setError(typeof detail === "string" ? detail : "Could not reset your password. Try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthTemplate title="Choose a new password" subtitle="Use at least 8 characters.">
      {complete ? (
        <p role="status" className="text-sm text-emerald-700">
          Password updated. Redirecting you to sign in…
        </p>
      ) : (
        <form onSubmit={onSubmit} className="space-y-4">
          {!token ? (
            <p role="alert" className="text-sm text-red-600">
              This reset link is missing its token. Request a new one.
            </p>
          ) : null}
          <FormField
            id="password"
            label="New password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <FormField
            id="confirmation"
            label="Confirm new password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
          />
          {error ? <p role="alert" className="text-sm text-red-600">{error}</p> : null}
          <Button type="submit" className="w-full" disabled={loading || !token}>
            {loading ? "Updating…" : "Update password"}
          </Button>
        </form>
      )}
      <p className="mt-4 text-center text-sm text-muted-foreground">
        <Link href="/login" className="font-medium text-accent hover:underline">
          Back to sign in
        </Link>
      </p>
    </AuthTemplate>
  );
}
