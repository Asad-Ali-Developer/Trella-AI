"use client";

import { CheckCircle2, MessageSquare, RefreshCw, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Button } from "@/components/atoms/Button";
import { workspaceStore } from "@/lib/storage";
import { slackService } from "@/services/SlackService";

function SlackCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    async function handleCallback() {
      const code = searchParams.get("code");
      const state = searchParams.get("state");
      const errorParam = searchParams.get("error");
      const workspaceId = workspaceStore.getWorkspaceId();

      if (errorParam) {
        setStatus("error");
        setErrorMessage(
          searchParams.get("error_description") || `Slack authorization was denied (${errorParam}).`
        );
        return;
      }

      if (!code || !state) {
        setStatus("error");
        setErrorMessage("Missing OAuth authorization code or state parameter.");
        return;
      }

      if (!workspaceId) {
        setStatus("error");
        setErrorMessage("No active workspace selected. Please log in and pick a workspace.");
        return;
      }

      try {
        await slackService.completeAuthorization(code, state, workspaceId);
        setStatus("success");
        setTimeout(() => {
          router.push("/dashboard/schedules");
        }, 1500);
      } catch (err: unknown) {
        setStatus("error");
        const msg = err instanceof Error ? err.message : "Failed to connect Slack.";
        setErrorMessage(msg);
      }
    }

    handleCallback();
  }, [router, searchParams]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#F8FAFC] p-4 dark:bg-[#06141B]">
      <div className="w-full max-w-md rounded-2xl border border-[#E2E8F0] bg-white p-8 text-center shadow-xl dark:border-[#253745] dark:bg-[#11212D]">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-violet-50 dark:bg-violet-950/40">
          <MessageSquare className="h-7 w-7 text-violet-600 dark:text-violet-400" />
        </div>

        {status === "loading" && (
          <div className="space-y-3">
            <h2 className="text-xl font-bold text-[#06141B] dark:text-[#F1F5F9]">
              Connecting Slack...
            </h2>
            <p className="text-sm text-[#4A5C6A] dark:text-[#9BA8AB]">
              Exchanging credentials and verifying your Slack workspace permissions.
            </p>
            <div className="flex justify-center pt-2">
              <RefreshCw className="h-6 w-6 animate-spin text-violet-600 dark:text-violet-400" />
            </div>
          </div>
        )}

        {status === "success" && (
          <div className="space-y-3 animate-in fade-in">
            <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400">
              <CheckCircle2 className="h-6 w-6" />
            </div>
            <h2 className="text-xl font-bold text-[#06141B] dark:text-[#F1F5F9]">
              Slack Connected!
            </h2>
            <p className="text-sm text-[#4A5C6A] dark:text-[#9BA8AB]">
              Your Slack workspace has been successfully connected. Redirecting you to schedules...
            </p>
          </div>
        )}

        {status === "error" && (
          <div className="space-y-4 animate-in fade-in">
            <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-red-100 text-red-600 dark:bg-red-950/50 dark:text-red-400">
              <XCircle className="h-6 w-6" />
            </div>
            <h2 className="text-xl font-bold text-[#06141B] dark:text-[#F1F5F9]">
              Connection Failed
            </h2>
            <p className="text-xs text-red-600 dark:text-red-400">{errorMessage}</p>
            <div className="flex justify-center gap-3 pt-2">
              <Link href="/dashboard/apps">
                <Button variant="secondary">Back to Connected Apps</Button>
              </Link>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function SlackCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-[#F8FAFC] dark:bg-[#06141B]">
          <RefreshCw className="h-6 w-6 animate-spin text-[#253745] dark:text-[#F1F5F9]" />
        </div>
      }
    >
      <SlackCallbackContent />
    </Suspense>
  );
}
