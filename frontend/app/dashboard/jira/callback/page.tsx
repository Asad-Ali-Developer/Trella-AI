"use client";

import { isAxiosError } from "axios";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { workspaceStore } from "@/lib/storage";
import { jiraService } from "@/services/JiraService";

export default function JiraCallbackPage() {
  const router = useRouter();
  const [message, setMessage] = useState("Finishing Jira connection…");
  const [error, setError] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const callbackUrl = new URL(window.location.href);
    const oauthError = callbackUrl.searchParams.get("error");
    const code = callbackUrl.searchParams.get("code");
    const state = callbackUrl.searchParams.get("state");
    const workspaceId =
      window.sessionStorage.getItem("jira.oauth_workspace_id") ||
      workspaceStore.getWorkspaceId() ||
      undefined;

    window.history.replaceState(null, "", callbackUrl.pathname);

    if (oauthError) {
      setError("Atlassian did not authorize Jira access. You can try connecting again.");
      return;
    }
    if (!code || !state) {
      setError(
        "Atlassian returned without the required authorization code or state. Start the connection again from Jira settings.",
      );
      return;
    }

    void jiraService
      .completeAuthorization(code, state, workspaceId)
      .then(() => {
        window.sessionStorage.removeItem("jira.oauth_workspace_id");
        router.replace("/dashboard/jira?connected=1");
      })

      .catch((requestError: unknown) => {
        setMessage("Jira could not be connected.");
        const detail = isAxiosError<{ detail?: unknown }>(requestError)
          ? requestError.response?.data?.detail
          : undefined;
        setError(
          typeof detail === "string"
            ? detail
            : "The connection request failed. Check that Jira OAuth credentials are configured, then try again.",
        );
      });
  }, [router]);

  return (
    <main
      className="flex min-h-screen flex-col items-center justify-center gap-4 px-4 text-sm"
      role={error ? "alert" : "status"}
    >
      <p className={error ? "text-red-600" : "text-muted-foreground"}>{error || message}</p>
      {error ? (
        <a className="text-primary underline" href="/dashboard/jira">
          Back to Jira settings
        </a>
      ) : null}
    </main>
  );
}
