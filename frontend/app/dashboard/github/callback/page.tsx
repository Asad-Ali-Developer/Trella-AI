"use client";

import { isAxiosError } from "axios";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { githubService } from "@/services/GithubService";

export default function GithubCallbackPage() {
  const router = useRouter();
  const [message, setMessage] = useState("Finishing GitHub connection…");
  const [error, setError] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const callbackUrl = new URL(window.location.href);
    const oauthError = callbackUrl.searchParams.get("error");
    const code = callbackUrl.searchParams.get("code");
    const state = callbackUrl.searchParams.get("state");
    const workspaceId = window.sessionStorage.getItem("github.oauth_workspace_id");
    window.sessionStorage.removeItem("github.oauth_workspace_id");
    window.history.replaceState(null, "", callbackUrl.pathname);

    if (oauthError) {
      setError("GitHub did not authorize access. You can try connecting again.");
      return;
    }
    if (!code || !state || !workspaceId) {
      const missing: string[] = [];
      if (!code) missing.push("code");
      if (!state) missing.push("state");
      if (!workspaceId) missing.push("workspace");
      setError(
        `GitHub returned without the required ${missing.join(", ")} information. Start the connection again from GitHub settings.`,
      );
      return;
    }

    void githubService
      .completeAuthorization(code, state, workspaceId)
      .then(() => router.replace("/dashboard/github?connected=1"))
      .catch((requestError: unknown) => {
        setMessage("GitHub could not be connected.");
        const detail = isAxiosError<{ detail?: unknown }>(requestError)
          ? requestError.response?.data?.detail
          : undefined;
        setError(
          typeof detail === "string"
            ? detail
            : "The connection request failed. Check that the backend is running, then try again.",
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
        <a className="text-primary underline" href="/dashboard/github">
          Back to GitHub settings
        </a>
      ) : null}
    </main>
  );
}
