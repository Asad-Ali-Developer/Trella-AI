"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { isAxiosError } from "axios";
import { Mail, ArrowRight, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";

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
    <AuthTemplate title="Reset password" subtitle="We’ll email you a recovery link to restore access.">
      <form onSubmit={onSubmit} className="space-y-4">
        {message ? (
          <div className="flex items-start gap-2.5 rounded-2xl border border-[#4A5C6A] bg-[#253745]/20 p-3 text-sm text-[#06141B] dark:text-[#CCD0CF]">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[#253745] dark:text-[#CCD0CF]" />
            <p className="flex-1 text-xs font-medium leading-relaxed">{message}</p>
          </div>
        ) : null}

        {error ? (
          <div className="flex items-start gap-2.5 rounded-2xl border border-[#4A5C6A] bg-[#253745]/15 p-3 text-sm text-[#06141B] dark:border-[#4A5C6A] dark:bg-[#253745] dark:text-[#CCD0CF]">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-[#253745] dark:text-[#CCD0CF]" />
            <p className="flex-1 text-xs font-medium leading-relaxed">{error}</p>
          </div>
        ) : null}

        <div className="space-y-1.5 text-left">
          <label htmlFor="email" className="block text-xs font-semibold text-[#06141B] dark:text-[#CCD0CF]">
            Work Email
          </label>
          <div className="relative">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5 text-[#4A5C6A] dark:text-[#9BA8AB]">
              <Mail className="h-4 w-4" />
            </div>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="h-11 w-full rounded-2xl border border-[#9BA8AB] bg-white pl-10 pr-3 text-sm text-[#06141B] placeholder:text-[#4A5C6A]/60 transition-all focus:border-[#253745] focus:outline-none focus:ring-2 focus:ring-[#253745]/20 dark:border-[#253745] dark:bg-[#11212D] dark:text-[#CCD0CF] dark:placeholder:text-[#9BA8AB]/50 dark:focus:border-[#4A5C6A] dark:focus:ring-[#4A5C6A]/20"
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="group flex h-11 w-full items-center justify-center gap-2 rounded-2xl border border-[#4A5C6A] bg-[#253745] px-4 text-sm font-semibold text-[#CCD0CF] shadow-md shadow-[#06141B]/15 transition-all hover:bg-[#11212D] hover:shadow-lg active:scale-[0.99] disabled:pointer-events-none disabled:opacity-50 dark:bg-[#253745] dark:hover:bg-[#4A5C6A]"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Sending link…</span>
            </>
          ) : (
            <>
              <span>Send recovery link</span>
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </>
          )}
        </button>

        <p className="pt-2 text-center text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">
          Remember your password?{" "}
          <Link
            href="/login"
            className="font-semibold text-[#06141B] transition hover:underline dark:text-[#CCD0CF]"
          >
            Sign in
          </Link>
        </p>
      </form>
    </AuthTemplate>
  );
}
