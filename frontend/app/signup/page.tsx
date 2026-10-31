"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { AxiosError } from "axios";
import { User as UserIcon, Mail, Lock, Eye, EyeOff, ArrowRight, Loader2, AlertCircle, Check } from "lucide-react";

import { useAppDispatch } from "@/lib/hooks";
import { setAuthenticatedUser } from "@/lib/authSlice";
import { GoogleIcon } from "@/components/atoms/GoogleIcon";
import { AuthTemplate } from "@/components/templates/AuthTemplate";
import { authService } from "@/services/AuthService";

export default function SignupPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);

  const isPasswordLongEnough = password.length >= 8;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!isPasswordLongEnough) {
      setError("Password must contain at least 8 characters.");
      return;
    }

    setError("");
    setLoading(true);
    try {
      const { user } = await authService.signup({ name, email, password });
      dispatch(setAuthenticatedUser(user));
      router.replace("/dashboard");
    } catch (err) {
      const axiosError = err as AxiosError<{ detail?: string }>;
      setError(axiosError.response?.data?.detail ?? "Unable to create account. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogleSignup() {
    setError("");
    setGoogleLoading(true);
    try {
      const { user } = await authService.googleAuth();
      dispatch(setAuthenticatedUser(user));
      router.replace("/dashboard");
    } catch (err) {
      const axiosError = err as AxiosError<{ detail?: string }>;
      setError(axiosError.response?.data?.detail ?? "Google sign-up failed. Please try again.");
    } finally {
      setGoogleLoading(false);
    }
  }

  return (
    <AuthTemplate title="Create your account" subtitle="Start analyzing boards and generating grounded AI insights.">
      <div className="space-y-5">
        {/* Google Authentication Button */}
        <button
          type="button"
          onClick={handleGoogleSignup}
          disabled={googleLoading || loading}
          className="group relative flex w-full items-center justify-center gap-3 rounded-2xl border border-[#9BA8AB] bg-white px-4 py-2.5 text-sm font-semibold text-[#06141B] shadow-sm transition-all hover:bg-[#CCD0CF]/30 hover:border-[#4A5C6A] hover:shadow-md active:scale-[0.99] disabled:pointer-events-none disabled:opacity-50 dark:border-[#253745] dark:bg-[#11212D] dark:text-[#CCD0CF] dark:hover:bg-[#253745] dark:hover:border-[#4A5C6A]"
        >
          {googleLoading ? (
            <Loader2 className="h-4 w-4 animate-spin text-[#4A5C6A] dark:text-[#9BA8AB]" />
          ) : (
            <GoogleIcon className="h-5 w-5 shrink-0 transition-transform group-hover:scale-110" />
          )}
          <span>{googleLoading ? "Connecting to Google…" : "Continue with Google"}</span>
        </button>

        {/* Divider */}
        <div className="relative flex items-center justify-center">
          <div className="w-full border-t border-[#9BA8AB] dark:border-[#253745]" />
          <span className="absolute bg-white px-3 text-xs font-semibold uppercase tracking-wider text-[#4A5C6A] dark:bg-[#11212D] dark:text-[#9BA8AB]">
            Or register with email
          </span>
        </div>

        {/* Error Alert */}
        {error ? (
          <div className="flex items-start gap-2.5 rounded-2xl border border-[#4A5C6A] bg-[#253745]/15 p-3 text-sm text-[#06141B] dark:border-[#4A5C6A] dark:bg-[#253745] dark:text-[#CCD0CF]">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-[#253745] dark:text-[#CCD0CF]" />
            <p className="flex-1 text-xs font-medium leading-relaxed">{error}</p>
          </div>
        ) : null}

        {/* Registration Form */}
        <form onSubmit={onSubmit} className="space-y-4">
          {/* Full Name Field */}
          <div className="space-y-1.5 text-left">
            <label htmlFor="name" className="block text-xs font-semibold text-[#06141B] dark:text-[#CCD0CF]">
              Full Name
            </label>
            <div className="relative">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5 text-[#4A5C6A] dark:text-[#9BA8AB]">
                <UserIcon className="h-4 w-4" />
              </div>
              <input
                id="name"
                type="text"
                autoComplete="name"
                required
                placeholder="Alex Morgan"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="h-11 w-full rounded-2xl border border-[#9BA8AB] bg-white pl-10 pr-3 text-sm text-[#06141B] placeholder:text-[#4A5C6A]/60 transition-all focus:border-[#253745] focus:outline-none focus:ring-2 focus:ring-[#253745]/20 dark:border-[#253745] dark:bg-[#11212D] dark:text-[#CCD0CF] dark:placeholder:text-[#9BA8AB]/50 dark:focus:border-[#4A5C6A] dark:focus:ring-[#4A5C6A]/20"
              />
            </div>
          </div>

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
                placeholder="alex@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="h-11 w-full rounded-2xl border border-[#9BA8AB] bg-white pl-10 pr-3 text-sm text-[#06141B] placeholder:text-[#4A5C6A]/60 transition-all focus:border-[#253745] focus:outline-none focus:ring-2 focus:ring-[#253745]/20 dark:border-[#253745] dark:bg-[#11212D] dark:text-[#CCD0CF] dark:placeholder:text-[#9BA8AB]/50 dark:focus:border-[#4A5C6A] dark:focus:ring-[#4A5C6A]/20"
              />
            </div>
          </div>

          {/* Password Field */}
          <div className="space-y-1.5 text-left">
            <label htmlFor="password" className="block text-xs font-semibold text-[#06141B] dark:text-[#CCD0CF]">
              Password
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
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            {/* Password requirement hint */}
            <div className="flex items-center gap-1.5 pt-1 text-[11px] text-[#4A5C6A] dark:text-[#9BA8AB]">
              <div
                className={`flex h-4 w-4 items-center justify-center rounded-full transition-colors ${
                  isPasswordLongEnough
                    ? "bg-[#253745] text-[#CCD0CF] border border-[#4A5C6A]"
                    : "bg-[#CCD0CF] text-[#4A5C6A] border border-[#9BA8AB] dark:bg-[#11212D] dark:text-[#4A5C6A]"
                }`}
              >
                <Check className="h-2.5 w-2.5 stroke-[3]" />
              </div>
              <span className={isPasswordLongEnough ? "text-[#06141B] font-semibold dark:text-[#CCD0CF]" : ""}>
                Minimum 8 characters
              </span>
            </div>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={loading || googleLoading}
            className="group flex h-11 w-full items-center justify-center gap-2 rounded-2xl border border-[#4A5C6A] bg-[#253745] px-4 text-sm font-semibold text-[#CCD0CF] shadow-md shadow-[#06141B]/15 transition-all hover:bg-[#11212D] hover:shadow-lg active:scale-[0.99] disabled:pointer-events-none disabled:opacity-50 dark:bg-[#253745] dark:hover:bg-[#4A5C6A]"
          >
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Creating account…</span>
              </>
            ) : (
              <>
                <span>Create account</span>
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </>
            )}
          </button>
        </form>

        {/* Footer Redirect */}
        <p className="pt-2 text-center text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">
          Already registered?{" "}
          <Link
            href="/login"
            className="font-semibold text-[#06141B] transition hover:underline dark:text-[#CCD0CF]"
          >
            Sign in
          </Link>
        </p>
      </div>
    </AuthTemplate>
  );
}
