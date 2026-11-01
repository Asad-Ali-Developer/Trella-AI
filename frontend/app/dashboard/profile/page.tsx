"use client";

import {
  AlertCircle,
  BriefcaseBusiness,
  Check,
  CheckCircle2,
  Copy,
  Eye,
  EyeOff,
  KeyRound,
  Lock,
  Mail,
  ShieldCheck,
  User,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/atoms/Button";
import { PageTransition } from "@/components/atoms/PageTransition";
import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { clearSession, setAuthenticatedUser } from "@/lib/authSlice";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { workspaceStore } from "@/lib/storage";
import type { Workspace } from "@/lib/types";
import { authService } from "@/services/AuthService";
import { workspaceService } from "@/services/WorkspaceService";

export default function UserProfilePage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);

  // Profile Edit State
  const [name, setName] = useState("");
  const [nameSaving, setNameSaving] = useState(false);
  const [nameSuccess, setNameSuccess] = useState(false);
  const [nameError, setNameError] = useState("");

  // Password Change State
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordSuccess, setPasswordSuccess] = useState(false);
  const [passwordError, setPasswordError] = useState("");

  // Copy ID State
  const [copiedId, setCopiedId] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const [currentUser, items] = await Promise.all([
        authService.me(),
        workspaceService.list().catch(() => []),
      ]);
      dispatch(setAuthenticatedUser(currentUser));
      setName(currentUser.name || "");
      setWorkspaces(items);

      const storedId = workspaceStore.getWorkspaceId();
      const active = items.find((w) => w.id === storedId) ?? items[0] ?? null;
      setSelectedWorkspace(active);
    } catch {
      router.push("/login");
    } finally {
      setLoading(false);
    }
  }, [dispatch, router]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Handle Profile Name Update
  const handleUpdateProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setNameError("");
    setNameSuccess(false);

    const cleanName = name.trim();
    if (!cleanName) {
      setNameError("Please enter a valid display name.");
      return;
    }

    try {
      setNameSaving(true);
      const updatedUser = await authService.updateProfile({ name: cleanName });
      dispatch(setAuthenticatedUser(updatedUser));
      setName(updatedUser.name);
      setNameSuccess(true);
      setTimeout(() => setNameSuccess(false), 4000);
    } catch (err: unknown) {
      const errorMsg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Failed to update profile name. Please try again.";
      setNameError(errorMsg);
    } finally {
      setNameSaving(false);
    }
  };

  // Handle Password Change
  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError("");
    setPasswordSuccess(false);

    if (!currentPassword) {
      setPasswordError("Current password is required.");
      return;
    }
    if (newPassword.length < 8) {
      setPasswordError("New password must be at least 8 characters long.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("New password and confirmation do not match.");
      return;
    }
    if (newPassword === currentPassword) {
      setPasswordError("New password must be different from current password.");
      return;
    }

    try {
      setPasswordSaving(true);
      await authService.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setPasswordSuccess(true);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setTimeout(() => setPasswordSuccess(false), 5000);
    } catch (err: unknown) {
      const errorMsg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Failed to change password. Please verify current credentials.";
      setPasswordError(errorMsg);
    } finally {
      setPasswordSaving(false);
    }
  };

  const handleCopyId = () => {
    if (!user?.id) return;
    navigator.clipboard.writeText(user.id);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  const handleLogout = async () => {
    await authService.logout().catch(() => {});
    dispatch(clearSession());
    router.push("/login");
  };

  if (loading) {
    return (
      <DashboardTemplate
        sidebar={
          <Sidebar
            user={user}
            workspaces={workspaces}
            selectedId={selectedWorkspace?.id ?? null}
            onSelectWorkspace={(w) => setSelectedWorkspace(w)}
            onLogout={() => void handleLogout()}
          />
        }
      >
        <div className="flex h-96 items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#253745] border-t-transparent dark:border-[#CCD0CF]" />
        </div>
      </DashboardTemplate>
    );
  }

  const memberSince = user?.created_at
    ? new Date(user.created_at).toLocaleDateString(undefined, {
        year: "numeric",
        month: "long",
        day: "numeric",
      })
    : "Verified member";

  return (
    <DashboardTemplate
      sidebar={
        <Sidebar
          user={user}
          workspaces={workspaces}
          selectedId={selectedWorkspace?.id ?? null}
          onSelectWorkspace={(w) => setSelectedWorkspace(w)}
          onLogout={() => void handleLogout()}
        />
      }
    >
      <PageTransition className="mx-auto w-full max-w-5xl space-y-8 pb-14">
        {/* Breadcrumb & Header */}
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-zinc-400 dark:text-[#9BA8AB]">
            <Link href="/dashboard" className="transition hover:text-zinc-700 dark:hover:text-[#F1F5F9]">
              Dashboard
            </Link>
            <span>/</span>
            <span className="text-zinc-700 dark:text-[#CCD0CF]">Profile</span>
          </div>
          <div className="mt-2 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-[#F1F5F9] sm:text-3xl">
                Profile
              </h1>
              <p className="mt-1 text-sm text-zinc-500 dark:text-[#9BA8AB]">
                View and edit your personal details, credentials, and linked workspaces.
              </p>
            </div>
            <div className="mt-3 flex items-center gap-2 sm:mt-0">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 dark:border-emerald-800/60 dark:bg-emerald-950/40 dark:text-emerald-400">
                <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                Active Account
              </span>
            </div>
          </div>
        </div>

        {/* Hero Identity Banner */}
        <section className="relative overflow-hidden rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-[#253745] dark:bg-[#11212D] sm:p-8">
          <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-5">
              <div className="relative flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl border-2 border-[#4A5C6A] bg-gradient-to-br from-[#253745] to-[#11212D] text-3xl font-bold text-white shadow-md">
                {user?.name?.trim().charAt(0).toUpperCase() || "U"}
                <span className="absolute -bottom-1 -right-1 flex h-6 w-6 items-center justify-center rounded-full border-2 border-white bg-emerald-500 text-white dark:border-[#11212D]">
                  <Check className="h-3 w-3" />
                </span>
              </div>
              <div className="min-w-0">
                <h2 className="truncate text-xl font-bold text-zinc-900 dark:text-[#F1F5F9]">
                  {user?.name || "User"}
                </h2>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-zinc-500 dark:text-[#9BA8AB]">
                  <span className="flex items-center gap-1">
                    <Mail className="h-3.5 w-3.5" />
                    {user?.email}
                  </span>
                  <span>•</span>
                  <span>Member since {memberSince}</span>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center gap-1 rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-0.5 text-xs font-medium text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/50 dark:text-indigo-300">
                    <ShieldCheck className="h-3.5 w-3.5 text-indigo-600 dark:text-indigo-400" />
                    Verified Identity
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-lg border border-zinc-200 bg-zinc-50 px-2.5 py-0.5 text-xs font-medium text-zinc-600 dark:border-[#253745] dark:bg-[#162736] dark:text-[#CCD0CF]">
                    <BriefcaseBusiness className="h-3.5 w-3.5 text-zinc-500" />
                    {workspaces.length} {workspaces.length === 1 ? "Workspace" : "Workspaces"}
                  </span>
                </div>
              </div>
            </div>

            {/* Quick Account ID snippet */}
            <div className="flex flex-col gap-1 rounded-xl border border-zinc-100 bg-zinc-50/70 p-3.5 dark:border-[#253745] dark:bg-[#162736] sm:min-w-56">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400 dark:text-[#9BA8AB]">
                User Account ID
              </span>
              <div className="flex items-center justify-between gap-2">
                <code className="truncate text-xs font-mono text-zinc-700 dark:text-[#CCD0CF]">
                  {user?.id ? `${user.id.slice(0, 18)}…` : "—"}
                </code>
                <button
                  type="button"
                  onClick={handleCopyId}
                  className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-white hover:text-zinc-700 dark:hover:bg-[#253745] dark:hover:text-white"
                  title="Copy full User ID"
                >
                  {copiedId ? (
                    <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" />
                  )}
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* Two Column Grid: Personal Details & Password Security */}
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
          {/* Section 1: Edit Profile Name */}
          <section className="flex flex-col rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-[#253745] dark:bg-[#11212D]">
            <div className="flex items-center gap-3 border-b border-zinc-100 pb-4 dark:border-[#253745]">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50 text-indigo-700 dark:bg-[#162736] dark:text-indigo-400">
                <User className="h-5 w-5" />
              </span>
              <div>
                <h3 className="font-bold text-zinc-900 dark:text-[#F1F5F9]">Personal Details</h3>
                <p className="text-xs text-zinc-500 dark:text-[#9BA8AB]">
                  Update your public display name across workspaces and reports.
                </p>
              </div>
            </div>

            <form onSubmit={handleUpdateProfile} className="mt-5 flex flex-1 flex-col justify-between space-y-4">
              <div className="space-y-4">
                {nameSuccess && (
                  <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-semibold text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/50 dark:text-emerald-300">
                    <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                    Profile name updated successfully.
                  </div>
                )}
                {nameError && (
                  <div className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-semibold text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/50 dark:text-rose-300">
                    <AlertCircle className="h-4 w-4 shrink-0 text-rose-600 dark:text-rose-400" />
                    {nameError}
                  </div>
                )}

                <div>
                  <label htmlFor="user-name" className="block text-xs font-semibold uppercase tracking-wider text-zinc-600 dark:text-[#CCD0CF]">
                    Full Display Name
                  </label>
                  <input
                    id="user-name"
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                    placeholder="e.g. Alex Montgomery"
                    className="mt-1.5 w-full rounded-xl border border-zinc-200 bg-white px-3.5 py-2.5 text-sm text-zinc-900 shadow-xs transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100 dark:border-[#253745] dark:bg-[#162736] dark:text-[#F1F5F9] dark:focus:border-indigo-400"
                  />
                  <p className="mt-1 text-[11px] text-zinc-400 dark:text-[#9BA8AB]">
                    This name will appear on AI analysis run logs, audit trails, and member cards.
                  </p>
                </div>

                <div>
                  <label htmlFor="user-email" className="block text-xs font-semibold uppercase tracking-wider text-zinc-600 dark:text-[#CCD0CF]">
                    Primary Email Address
                  </label>
                  <div className="relative mt-1.5">
                    <input
                      id="user-email"
                      type="email"
                      value={user?.email || ""}
                      disabled
                      className="w-full cursor-not-allowed rounded-xl border border-zinc-200 bg-zinc-50 px-3.5 py-2.5 text-sm text-zinc-500 shadow-xs dark:border-[#253745] dark:bg-[#06141B] dark:text-[#9BA8AB]"
                    />
                    <span className="absolute inset-y-0 right-3 flex items-center text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                      <Lock className="mr-1 h-3.5 w-3.5" />
                      Locked
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-zinc-400 dark:text-[#9BA8AB]">
                    Email is linked to your login identity and cannot be altered directly.
                  </p>
                </div>
              </div>

              <div className="pt-4 border-t border-zinc-100 dark:border-[#253745]">
                <Button
                  type="submit"
                  disabled={nameSaving || name.trim() === user?.name}
                  className="w-full sm:w-auto"
                >
                  {nameSaving ? "Saving changes…" : "Save Profile"}
                </Button>
              </div>
            </form>
          </section>

          {/* Section 2: Security & Change Password */}
          <section className="flex flex-col rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-[#253745] dark:bg-[#11212D]">
            <div className="flex items-center gap-3 border-b border-zinc-100 pb-4 dark:border-[#253745]">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-50 text-amber-700 dark:bg-[#162736] dark:text-amber-400">
                <KeyRound className="h-5 w-5" />
              </span>
              <div>
                <h3 className="font-bold text-zinc-900 dark:text-[#F1F5F9]">Security & Credentials</h3>
                <p className="text-xs text-zinc-500 dark:text-[#9BA8AB]">
                  Change your master account password securely.
                </p>
              </div>
            </div>

            <form onSubmit={handleChangePassword} className="mt-5 flex flex-1 flex-col justify-between space-y-4">
              <div className="space-y-4">
                {passwordSuccess && (
                  <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs font-semibold text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/50 dark:text-emerald-300">
                    <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                    Your password was updated successfully.
                  </div>
                )}
                {passwordError && (
                  <div className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-semibold text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/50 dark:text-rose-300">
                    <AlertCircle className="h-4 w-4 shrink-0 text-rose-600 dark:text-rose-400" />
                    {passwordError}
                  </div>
                )}

                <div>
                  <label htmlFor="current-pw" className="block text-xs font-semibold uppercase tracking-wider text-zinc-600 dark:text-[#CCD0CF]">
                    Current Password
                  </label>
                  <div className="relative mt-1.5">
                    <input
                      id="current-pw"
                      type={showCurrentPassword ? "text" : "password"}
                      value={currentPassword}
                      onChange={(e) => setCurrentPassword(e.target.value)}
                      placeholder="Enter current password"
                      className="w-full rounded-xl border border-zinc-200 bg-white px-3.5 py-2.5 pr-10 text-sm text-zinc-900 shadow-xs transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100 dark:border-[#253745] dark:bg-[#162736] dark:text-[#F1F5F9]"
                    />
                    <button
                      type="button"
                      onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                      className="absolute inset-y-0 right-3 flex items-center text-zinc-400 hover:text-zinc-600 dark:hover:text-white"
                      tabIndex={-1}
                    >
                      {showCurrentPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                <div>
                  <label htmlFor="new-pw" className="block text-xs font-semibold uppercase tracking-wider text-zinc-600 dark:text-[#CCD0CF]">
                    New Password
                  </label>
                  <div className="relative mt-1.5">
                    <input
                      id="new-pw"
                      type={showNewPassword ? "text" : "password"}
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      placeholder="Minimum 8 characters"
                      className="w-full rounded-xl border border-zinc-200 bg-white px-3.5 py-2.5 pr-10 text-sm text-zinc-900 shadow-xs transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100 dark:border-[#253745] dark:bg-[#162736] dark:text-[#F1F5F9]"
                    />
                    <button
                      type="button"
                      onClick={() => setShowNewPassword(!showNewPassword)}
                      className="absolute inset-y-0 right-3 flex items-center text-zinc-400 hover:text-zinc-600 dark:hover:text-white"
                      tabIndex={-1}
                    >
                      {showNewPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                <div>
                  <label htmlFor="confirm-pw" className="block text-xs font-semibold uppercase tracking-wider text-zinc-600 dark:text-[#CCD0CF]">
                    Confirm New Password
                  </label>
                  <div className="relative mt-1.5">
                    <input
                      id="confirm-pw"
                      type={showConfirmPassword ? "text" : "password"}
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      placeholder="Re-type new password"
                      className="w-full rounded-xl border border-zinc-200 bg-white px-3.5 py-2.5 pr-10 text-sm text-zinc-900 shadow-xs transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100 dark:border-[#253745] dark:bg-[#162736] dark:text-[#F1F5F9]"
                    />
                    <button
                      type="button"
                      onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                      className="absolute inset-y-0 right-3 flex items-center text-zinc-400 hover:text-zinc-600 dark:hover:text-white"
                      tabIndex={-1}
                    >
                      {showConfirmPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
              </div>

              <div className="pt-4 border-t border-zinc-100 dark:border-[#253745]">
                <Button
                  type="submit"
                  disabled={passwordSaving || !currentPassword || !newPassword || !confirmPassword}
                  className="w-full sm:w-auto"
                >
                  {passwordSaving ? "Updating password…" : "Update Password"}
                </Button>
              </div>
            </form>
          </section>
        </div>

        {/* Section 3: Workspace Memberships Overview */}
        <section className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-[#253745] dark:bg-[#11212D]">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-zinc-100 pb-4 dark:border-[#253745]">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700 dark:bg-[#162736] dark:text-emerald-400">
                <BriefcaseBusiness className="h-5 w-5" />
              </span>
              <div>
                <h3 className="font-bold text-zinc-900 dark:text-[#F1F5F9]">Linked Workspaces & Role Access</h3>
                <p className="text-xs text-zinc-500 dark:text-[#9BA8AB]">
                  Workspaces where your identity has active permissions and operational roles.
                </p>
              </div>
            </div>
            <Link
              href="/dashboard/workspaces"
              className="inline-flex items-center gap-1.5 rounded-xl bg-indigo-50 px-3.5 py-1.5 text-xs font-semibold text-indigo-700 transition-colors hover:bg-indigo-600 hover:text-white dark:bg-indigo-950/60 dark:text-indigo-300 dark:hover:bg-indigo-600 dark:hover:text-white"
            >
              Manage Workspaces →
            </Link>
          </div>

          <div className="mt-5">
            {workspaces.length === 0 ? (
              <p className="py-4 text-center text-xs text-zinc-400 dark:text-[#9BA8AB]">
                No workspaces joined yet.
              </p>
            ) : (
              <div className="divide-y divide-zinc-100 dark:divide-[#253745]">
                {workspaces.map((workspace) => (
                  <div
                    key={workspace.id}
                    className="flex flex-col gap-3 py-3.5 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-zinc-200 bg-zinc-50 text-xs font-bold text-zinc-700 dark:border-[#253745] dark:bg-[#162736] dark:text-[#CCD0CF]">
                        {workspace.name.slice(0, 2).toUpperCase()}
                      </div>
                      <div>
                        <h4 className="text-sm font-semibold text-zinc-900 dark:text-[#F1F5F9]">
                          {workspace.name}
                        </h4>
                        <p className="text-xs text-zinc-400 dark:text-[#9BA8AB]">
                          {workspace.client_name ? `Client: ${workspace.client_name}` : "General Workspace"}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <span className="rounded-full border border-indigo-200 bg-indigo-50/70 px-2.5 py-0.5 text-xs font-semibold capitalize text-indigo-700 dark:border-indigo-900/60 dark:bg-indigo-950/50 dark:text-indigo-300">
                        {workspace.role || "member"}
                      </span>
                      <Link
                        href={`/dashboard/workspaces/${workspace.id}`}
                        className="inline-flex items-center gap-1 text-xs font-medium text-zinc-500 hover:text-indigo-700 dark:text-[#9BA8AB] dark:hover:text-white"
                      >
                        Open Details →
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </PageTransition>
    </DashboardTemplate>
  );
}
