"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { AxiosError } from "axios";
import { Mail, Lock, Eye, EyeOff, ArrowRight, Loader2, AlertCircle } from "lucide-react";

import { useAppDispatch } from "@/lib/hooks";
import { setAuthenticatedUser } from "@/lib/authSlice";
import { GoogleIcon } from "@/components/atoms/GoogleIcon";
import { AuthTemplate } from "@/components/templates/AuthTemplate";
import { authService } from "@/services/AuthService";

export default function LoginPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);

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
      setError(axiosError.response?.data?.detail ?? "Unable to sign in. Please verify your credentials.");
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogleLogin() {
    setError("");
    setGoogleLoading(true);
    try {
      const { user } = await authService.googleAuth();
      dispatch(setAuthenticatedUser(user));
      router.replace("/dashboard");
    } catch (err) {
      const axiosError = err as AxiosError<{ detail?: string }>;
      setError(axiosError.response?.data?.detail ?? "Google sign-in failed. Please try again.");
    } finally {
      setGoogleLoading(false);
    }
  }

  return (
    <AuthTemplate title="Welcome back" subtitle="Sign in to your Trella workspace to view insights.">
      <div className="space-y-5">
        {/* Google Authentication Button */}
        <button
          type="button"
          onClick={handleGoogleLogin}
          disabled={googleLoading || loading}
          className="group relative flex w-full items-center justify-center gap-3 rounded-2xl border border-[#9BA8AB] bg-white px-4 py-2.5 text-sm font-semibold text-[#06141B] shadow-sm transition-all hover:bg-[#CCD0CF]/30 hover:border-[#4A5C6A] hover:shadow-md active:scale-[0.99] disabled:pointer-events-none disabled:opacity-50 dark:border-[#253745] dark:bg-[#11212D] dark:text-[#CCD0CF] dark:hover:bg-[#253745] dark:hover:border-[#4A5C6A]"
        >
          {googleLoading ? (
            <Loader2 className="h-4 w-4 animate-spin text-[#4A5C6A] dark:text-[#9BA8AB]" />
          ) : (
            <GoogleIcon className="h-5 w-5 shrink-0 transition-transform group-hover:scale-110" />
          )}
          <span>{googleLoading ? "Signing in with Google…" : "Continue with Google"}</span>
        </button>

        {/* Divider */}
        <div className="relative flex items-center justify-center">
          <div className="w-full border-t border-[#9BA8AB] dark:border-[#253745]" />
          <span className="absolute bg-white px-3 text-xs font-semibold uppercase tracking-wider text-[#4A5C6A] dark:bg-[#11212D] dark:text-[#9BA8AB]">
            Or sign in with email
          </span>
        </div>

        {/* Error Alert */}
        {error ? (
          <div className="flex items-start gap-2.5 rounded-2xl border border-[#4A5C6A] bg-[#253745]/15 p-3 text-sm text-[#06141B] dark:border-[#4A5C6A] dark:bg-[#253745] dark:text-[#CCD0CF]">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-[#253745] dark:text-[#CCD0CF]" />
            <p className="flex-1 text-xs font-medium leading-relaxed">{error}</p>
          </div>
        ) : null}

        {/* Credentials Form */}
        <form onSubmit={onSubmit} className="space-y-4">
          {/* Email Field */}
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

          {/* Password Field */}
          <div className="space-y-1.5 text-left">
            <div className="flex items-center justify-between">
              <label htmlFor="password" className="block text-xs font-semibold text-[#06141B] dark:text-[#CCD0CF]">
                Password
              </label>
              <Link
                href="/forgot-password"
                className="text-xs font-medium text-[#253745] transition hover:underline dark:text-[#9BA8AB] dark:hover:text-[#CCD0CF]"
              >
                Forgot password?
              </Link>
            </div>
            <div className="relative">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5 text-[#4A5C6A] dark:text-[#9BA8AB]">
                <Lock className="h-4 w-4" />
              </div>
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                required
                minLength={8}
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-11 w-full rounded-2xl border border-[#9BA8AB] bg-white pl-10 pr-10 text-sm text-[#06141B] placeholder:text-[#4A5C6A]/60 transition-all focus:border-[#253745] focus:outline-none focus:ring-2 focus:ring-[#253745]/20 dark:border-[#253745] dark:bg-[#11212D] dark:text-[#CCD0CF] dark:placeholder:text-[#9BA8AB]/50 dark:focus:border-[#4A5C6A] dark:focus:ring-[#4A5C6A]/20"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 flex items-center pr-3.5 text-[#4A5C6A] transition hover:text-[#06141B] dark:text-[#9BA8AB] dark:hover:text-[#CCD0CF]"
                tabIndex={-1}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {/* Remember Me Checkbox */}
          <div className="flex items-center gap-2 pt-0.5">
            <input
              id="remember-me"
              type="checkbox"
              checked={rememberMe}
              onChange={(e) => setRememberMe(e.target.checked)}
              className="h-4 w-4 rounded-md border-[#9BA8AB] text-[#253745] focus:ring-[#253745] dark:border-[#253745] dark:bg-[#11212D]"
            />
            <label htmlFor="remember-me" className="text-xs text-[#4A5C6A] select-none dark:text-[#9BA8AB]">
              Remember my session
            </label>
          </div>

          {/* Submit Button with Palette and Rounded Pill Box */}
          <button
            type="submit"
            disabled={loading || googleLoading}
            className="group flex h-11 w-full items-center justify-center gap-2 rounded-2xl border border-[#4A5C6A] bg-[#253745] px-4 text-sm font-semibold text-[#CCD0CF] shadow-md shadow-[#06141B]/15 transition-all hover:bg-[#11212D] hover:shadow-lg active:scale-[0.99] disabled:pointer-events-none disabled:opacity-50 dark:bg-[#253745] dark:hover:bg-[#4A5C6A]"
          >
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Signing in…</span>
              </>
            ) : (
              <>
                <span>Sign in to workspace</span>
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </>
            )}
          </button>
        </form>

        {/* Footer Redirect */}
        <p className="pt-2 text-center text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">
          Don&apos;t have an account yet?{" "}
          <Link
            href="/signup"
            className="font-semibold text-[#06141B] transition hover:underline dark:text-[#CCD0CF]"
          >
            Create free account
          </Link>
        </p>
      </div>
    </AuthTemplate>
  );
}
