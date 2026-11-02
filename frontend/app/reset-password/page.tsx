"use client";

import Link from "next/link";
import { isAxiosError } from "axios";
import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Lock, Eye, EyeOff, ArrowRight, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";

import { AuthTemplate } from "@/components/templates/AuthTemplate";
import { authService } from "@/services/AuthService";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [showPassword, setShowPassword] = useState(false);
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
    <AuthTemplate title="Choose a new password" subtitle="Enter your updated password below.">
      {complete ? (
        <div className="flex items-center gap-2.5 rounded-2xl border border-[#4A5C6A] bg-[#253745]/20 p-4 text-[#06141B] dark:text-[#CCD0CF]">
          <CheckCircle2 className="h-5 w-5 shrink-0 text-[#253745] dark:text-[#CCD0CF]" />
          <p className="text-sm font-medium">Password updated successfully. Redirecting you to sign in…</p>
        </div>
      ) : (
        <form onSubmit={onSubmit} className="space-y-4">
          {!token ? (
            <div className="flex items-start gap-2.5 rounded-2xl border border-[#4A5C6A] bg-[#253745]/15 p-3 text-sm text-[#06141B] dark:text-[#CCD0CF]">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <p className="flex-1 text-xs font-medium">This reset link is missing its token. Please request a new one.</p>
            </div>
          ) : null}

          {error ? (
            <div className="flex items-start gap-2.5 rounded-2xl border border-[#4A5C6A] bg-[#253745]/15 p-3 text-sm text-[#06141B] dark:text-[#CCD0CF]">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <p className="flex-1 text-xs font-medium">{error}</p>
            </div>
          ) : null}

          <div className="space-y-1.5 text-left">
            <label htmlFor="password" className="block text-xs font-semibold text-[#06141B] dark:text-[#CCD0CF]">
              New Password
            </label>
            <div className="relative">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5 text-[#4A5C6A] dark:text-[#9BA8AB]">
                <Lock className="h-4 w-4" />
              </div>
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                required
                minLength={8}
                placeholder="At least 8 characters"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-11 w-full rounded-2xl border border-[#9BA8AB] bg-white pl-10 pr-10 text-sm text-[#06141B] placeholder:text-[#4A5C6A]/60 transition-all focus:border-[#253745] focus:outline-none focus:ring-2 focus:ring-[#253745]/20 dark:border-[#253745] dark:bg-[#11212D] dark:text-[#CCD0CF] dark:placeholder:text-[#9BA8AB]/50 dark:focus:border-[#4A5C6A] dark:focus:ring-[#4A5C6A]/20"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 flex items-center pr-3.5 text-[#4A5C6A] transition hover:text-[#06141B] dark:text-[#9BA8AB] dark:hover:text-[#CCD0CF]"
                tabIndex={-1}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          <div className="space-y-1.5 text-left">
            <label htmlFor="confirmation" className="block text-xs font-semibold text-[#06141B] dark:text-[#CCD0CF]">
              Confirm New Password
            </label>
            <div className="relative">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5 text-[#4A5C6A] dark:text-[#9BA8AB]">
                <Lock className="h-4 w-4" />
              </div>
              <input
                id="confirmation"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                required
                minLength={8}
                placeholder="Repeat new password"
                value={confirmation}
                onChange={(e) => setConfirmation(e.target.value)}
                className="h-11 w-full rounded-2xl border border-[#9BA8AB] bg-white pl-10 pr-10 text-sm text-[#06141B] placeholder:text-[#4A5C6A]/60 transition-all focus:border-[#253745] focus:outline-none focus:ring-2 focus:ring-[#253745]/20 dark:border-[#253745] dark:bg-[#11212D] dark:text-[#CCD0CF] dark:placeholder:text-[#9BA8AB]/50 dark:focus:border-[#4A5C6A] dark:focus:ring-[#4A5C6A]/20"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading || !token}
            className="group flex h-11 w-full items-center justify-center gap-2 rounded-2xl border border-[#4A5C6A] bg-[#253745] px-4 text-sm font-semibold text-[#CCD0CF] shadow-md shadow-[#06141B]/15 transition-all hover:bg-[#11212D] hover:shadow-lg active:scale-[0.99] disabled:pointer-events-none disabled:opacity-50 dark:bg-[#253745] dark:hover:bg-[#4A5C6A]"
          >
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Updating password…</span>
              </>
            ) : (
              <>
                <span>Update password</span>
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </>
            )}
          </button>
        </form>
      )}

      <p className="mt-4 text-center text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">
        <Link href="/login" className="font-semibold text-[#06141B] transition hover:underline dark:text-[#CCD0CF]">
          Back to sign in
        </Link>
      </p>
    </AuthTemplate>
  );
}
