"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { AxiosError } from "axios";

import { Button } from "@/components/atoms/Button";
import { FormField } from "@/components/molecules/FormField";
import { AuthTemplate } from "@/components/templates/AuthTemplate";
import { authService } from "@/services/AuthService";

export default function SignupPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await authService.signup({ name, email, password });
      router.replace("/dashboard");
    } catch (err) {
      const axiosError = err as AxiosError<{ detail?: string }>;
      setError(axiosError.response?.data?.detail ?? "Unable to create account.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthTemplate title="Create account" subtitle="Sign up to connect Trello and run insights.">
      <form onSubmit={onSubmit} className="space-y-4">
        <FormField
          id="name"
          label="Name"
          required
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
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
          autoComplete="new-password"
          required
          minLength={8}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? "Creating…" : "Create account"}
        </Button>
        <p className="text-center text-sm text-muted-foreground">
          Already registered?{" "}
          <Link href="/login" className="font-medium text-accent hover:underline">
            Sign in
          </Link>
        </p>
      </form>
    </AuthTemplate>
  );
}
