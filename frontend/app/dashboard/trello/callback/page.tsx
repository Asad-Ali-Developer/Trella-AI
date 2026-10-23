"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { trelloService } from "@/services/TrelloService";

export default function TrelloCallbackPage() {
  const router = useRouter();
  const [message, setMessage] = useState("Finishing Trello connection…");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const callbackUrl = new URL(window.location.href);
    const returnedState = callbackUrl.searchParams.get("state");
    const code = callbackUrl.searchParams.get("code");
    const oauthError = callbackUrl.searchParams.get("error");
    const workspaceId = window.sessionStorage.getItem("trello.oauth_workspace_id");
    window.sessionStorage.removeItem("trello.oauth_workspace_id");
    window.history.replaceState(null, "", callbackUrl.pathname);

    if (oauthError || !code || !returnedState || !workspaceId) {
      router.replace("/dashboard/trello?error=trello");
      return;
    }

    void trelloService
      .completeAuthorization(code, returnedState, workspaceId)
      .then(() => router.replace("/dashboard/trello?connected=1"))
      .catch(() => {
        setMessage("Trello could not be connected. Returning to settings…");
        router.replace("/dashboard/trello?error=trello");
      });
  }, [router]);

  return (
    <main className="flex min-h-screen items-center justify-center px-4 text-sm text-muted-foreground" role="status">
      {message}
    </main>
  );
}