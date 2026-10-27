"use client";

import { isAxiosError } from "axios";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { trelloService } from "@/services/TrelloService";

export default function TrelloCallbackPage() {
  const router = useRouter();
  const [message, setMessage] = useState("Finishing Trello connection…");
  const [error, setError] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const callbackUrl = new URL(window.location.href);
    const fragment = new URLSearchParams(callbackUrl.hash.slice(1));
    const returnedState =
      callbackUrl.searchParams.get("state") ?? fragment.get("state");
    const token =
      fragment.get("token") ??
      callbackUrl.searchParams.get("token") ??
      (callbackUrl.hash.length > 1 && !callbackUrl.hash.includes("=")
        ? callbackUrl.hash.slice(1)
        : null);
    const authorizationError =
      callbackUrl.searchParams.get("error") ??
      fragment.get("error") ??
      callbackUrl.searchParams.get("error_description") ??
      fragment.get("error_description");
    const workspaceId = window.sessionStorage.getItem("trello.oauth_workspace_id");
    window.sessionStorage.removeItem("trello.oauth_workspace_id");
    window.history.replaceState(null, "", callbackUrl.pathname);

    if (authorizationError) {
      setError(
        "Trello did not authorize access. You can try connecting again.",
      );
      return;
    }
    if (!token || !returnedState || !workspaceId) {
      const missing: string[] = [];
      if (!token) missing.push("token");
      if (!returnedState) missing.push("state");
      if (!workspaceId) missing.push("workspace");
      setError(
        `Trello returned without the required ${missing.join(", ")} information. Start the connection again from Trello settings.`,
      );
      return;
    }

    void trelloService
      .completeAuthorization(token, returnedState, workspaceId)
      .then(() => router.replace("/dashboard/trello?connected=1"))
      .catch((requestError: unknown) => {
        setMessage("Trello could not be connected.");
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
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-4 text-sm" role={error ? "alert" : "status"}>
      <p className={error ? "text-red-600" : "text-muted-foreground"}>{error || message}</p>
      {error ? (
        <a className="text-primary underline" href="/dashboard/trello">
          Back to Trello settings
        </a>
      ) : null}
    </main>
  );
}