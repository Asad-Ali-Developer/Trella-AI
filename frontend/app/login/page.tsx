"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { AxiosError } from "axios";

import { useAppDispatch } from "@/lib/hooks";
import { setAuthenticatedUser } from "@/lib/authSlice";
import { Button } from "@/components/atoms/Button";
import { FormField } from "@/components/molecules/FormField";
import { AuthTemplate } from "@/components/templates/AuthTemplate";
import { authService } from "@/services/AuthService";

export default function LoginPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { user } = await authService.login({ email, password });
      dispatch(setAuthenticatedUser(user));
      router.replace("/dashboard");
    } catch (err) {
      const axiosError = err as AxiosError<{ detail?: string }>;
      setError(axiosError.response?.data?.detail ?? "Unable to sign in.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthTemplate title="Sign in" subtitle="Access your workspaces and reports.">
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
        <FormField
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          minLength={8}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <p className="text-right text-sm">
          <Link href="/forgot-password" className="font-medium text-accent hover:underline">
            Forgot password?
          </Link>
        </p>
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? "Signing in…" : "Sign in"}
        </Button>
        <p className="text-center text-sm text-muted-foreground">
          No account?{" "}
          <Link href="/signup" className="font-medium text-accent hover:underline">
            Create one
          </Link>
        </p>
      </form>
    </AuthTemplate>
  );
}
