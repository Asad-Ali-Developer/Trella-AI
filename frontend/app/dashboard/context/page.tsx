"use client";

import {
  BrainCircuit,
  CheckCircle2,
  Clock3,
  ExternalLink,
  FileText,
  Layers3,
  LoaderCircle,
  Search,
  RefreshCw,
  UsersRound,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/atoms/Button";
import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { clearSession, setAuthenticatedUser } from "@/lib/authSlice";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { workspaceStore } from "@/lib/storage";
import type { SimilarContextCard, Workspace, WorkspaceContextSnapshot } from "@/lib/types";
import { authService } from "@/services/AuthService";
import { contextService } from "@/services/ContextService";
import { workspaceService } from "@/services/WorkspaceService";

export default function WorkspaceContextPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [context, setContext] = useState<WorkspaceContextSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SimilarContextCard[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [indexRemaining, setIndexRemaining] = useState<number | null>(null);
  const [updatingMemberId, setUpdatingMemberId] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [currentUser, workspaceList] = await Promise.all([
        authService.me(),
        workspaceService.list(),
      ]);
      dispatch(setAuthenticatedUser(currentUser));
      setWorkspaces(workspaceList);
      const storedId = workspaceStore.getWorkspaceId();
      const workspace = workspaceList.find((item) => item.id === storedId) ?? workspaceList[0] ?? null;
      if (workspace) {
        workspaceStore.setWorkspaceId(workspace.id);
        setSelectedWorkspace(workspace);
      }
    } catch {
      dispatch(clearSession());
      workspaceStore.clear();
      router.replace("/login");
    } finally {
      setLoading(false);
    }
  }, [dispatch, router]);

  useEffect(() => {
    void load();
  }, [load]);

  async function buildContext() {
    if (!selectedWorkspace) return;
    setBuilding(true);
    setError("");
    try {
      const snapshot = await contextService.generate(selectedWorkspace.id);
      setContext(snapshot);
      setNotice("");
    } catch {
      setError("Could not build workspace context. Please retry.");
    } finally {
      setBuilding(false);
    }
  }

  async function summarizeCards() {
    if (!selectedWorkspace) return;
    setSummarizing(true);
    setError("");
    setNotice("");
    try {
      const result = await contextService.summarizeCards(selectedWorkspace.id);
      setContext(await contextService.generate(selectedWorkspace.id));
      setNotice(
        `Summaries ready: ${result.generated} generated and ${result.cached} reused from cache.`,
      );
    } catch {
      setError("Could not summarize this workspace’s cards. Check Gemini configuration and retry.");
    } finally {
      setSummarizing(false);
    }
  }

  async function indexCards() {
    if (!selectedWorkspace) return;
    setIndexing(true);
    setError("");
    setNotice("");
    try {
      const result = await contextService.indexCards(selectedWorkspace.id);
      setIndexRemaining(result.remaining);
      setNotice(
        result.remaining
          ? `${result.indexed} cards indexed. ${result.remaining} remain; run indexing again to continue.`
          : `${result.indexed} cards indexed; ${result.already_indexed} were already up to date.`,
      );
    } catch {
      setError("Could not index this workspace’s cards. Check Gemini and database configuration.");
    } finally {
      setIndexing(false);
    }
  }

  async function searchRelated(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedWorkspace || searchQuery.trim().length < 3) return;
    setSearching(true);
    setError("");
    setSearchResults([]);
    setHasSearched(false);
    try {
      setSearchResults(await contextService.search(selectedWorkspace.id, searchQuery.trim()));
      setHasSearched(true);
    } catch {
      setError("Could not search related cards. Index this workspace first and check Gemini configuration.");
    } finally {
      setSearching(false);
    }
  }

  async function updateMemberClassification(
    memberId: string,
    roleTag: "unknown" | "client" | "internal",
  ) {
    if (!selectedWorkspace || !context) return;
    setUpdatingMemberId(memberId);
    setError("");
    try {
      const updatedMember = await contextService.classifyMember(
        selectedWorkspace.id,
        memberId,
        roleTag,
      );
      setContext((current) => current ? {
        ...current,
        members: current.members.map((member) =>
          member.id === memberId ? updatedMember : member,
        ),
        chunks: current.chunks.map((chunk) => ({
          ...chunk,
          items: chunk.items.map((item) =>
            item.item_type === "person" && item.metadata.external_id === updatedMember.external_id
              ? { ...item, metadata: { ...item.metadata, classification: updatedMember.role_tag } }
              : item,
          ),
        })),
      } : current);
      setNotice(`${updatedMember.name} marked as ${updatedMember.role_tag}.`);
    } catch {
      setError("Could not save this member classification.");
    } finally {
      setUpdatingMemberId(null);
    }
  }

  async function logout() {
    try {
      await authService.logout();
      dispatch(clearSession());
      workspaceStore.clear();
      router.replace("/login");
    } catch {
      setError("Could not sign out. Please retry.");
    }
  }

  function selectWorkspace(workspace: Workspace) {
    workspaceStore.setWorkspaceId(workspace.id);
    setSelectedWorkspace(workspace);
    setContext(null);
    setSearchResults([]);
    setHasSearched(false);
    setIndexRemaining(null);
    setError("");
    setNotice("");
  }

  return (
    <DashboardTemplate
      sidebar={
        <Sidebar
          user={user}
          workspaces={workspaces}
          selectedId={selectedWorkspace?.id ?? null}
          onSelectWorkspace={selectWorkspace}
          onLogout={() => void logout()}
        />
      }
    >
      <div className="mx-auto w-full max-w-6xl space-y-7 pb-10">
        <header className="flex flex-col gap-5 border-b border-zinc-200 pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-medium text-indigo-600">
              {selectedWorkspace?.name ?? "Workspace"} <span className="px-1 text-zinc-300">/</span> Context
            </p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight text-zinc-950">
              Workspace context
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-500">
              Build an ordered snapshot from this workspace’s connected accounts and included, synced sources.
              Each workspace is processed independently—even when it has only one connected account.
            </p>
          </div>
          <Button
            type="button"
            className="gap-2 rounded-lg px-4"
            disabled={!selectedWorkspace || building || loading}
            onClick={() => void buildContext()}
          >
            {building ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {building ? "Building context…" : context ? "Refresh context" : "Build context"}
          </Button>
        </header>

        {error ? (
          <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
            {error}
          </div>
        ) : null}
        {notice ? (
          <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
            {notice}
          </div>
        ) : null}

        {loading ? (
          <div role="status" className="rounded-2xl border border-zinc-200 bg-white p-6 text-sm text-zinc-500">
            Loading your workspaces…
          </div>
        ) : !selectedWorkspace ? (
          <section className="rounded-2xl border border-dashed border-zinc-300 bg-white px-6 py-12 text-center">
            <h2 className="text-lg font-semibold text-zinc-900">Create a workspace to get started</h2>
            <p className="mt-2 text-sm text-zinc-500">Context is always generated inside a specific workspace.</p>
            <Link
              href="/dashboard/workspaces"
              className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-indigo-700"
            >
              Go to workspaces <ExternalLink className="h-4 w-4" />
            </Link>
          </section>
        ) : !context ? (
          <section className="rounded-2xl border border-zinc-200 bg-white p-6 sm:p-8">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-700">
              <BrainCircuit className="h-6 w-6" />
            </div>
            <h2 className="mt-5 text-lg font-semibold text-zinc-950">Build context for {selectedWorkspace.name}</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-500">
              DeepClient gathers data only from this workspace’s linked accounts and included boards. One connected
              account is enough; other workspaces and their sources are never mixed into this context.
            </p>
            <Button
              type="button"
              className="mt-5 gap-2 rounded-lg px-4"
              disabled={building}
              onClick={() => void buildContext()}
            >
              {building ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <BrainCircuit className="h-4 w-4" />}
              {building ? "Building context…" : "Build workspace context"}
            </Button>
          </section>
        ) : (
          <>
            <section className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="secondary"
                className="gap-2 rounded-lg"
                disabled={summarizing || !context.sources.length}
                onClick={() => void summarizeCards()}
              >
                {summarizing ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                {summarizing ? "Summarizing…" : "Summarize cards"}
              </Button>
              <Button
                type="button"
                variant="secondary"
                className="gap-2 rounded-lg"
                disabled={indexing || !context.sources.length}
                onClick={() => void indexCards()}
              >
                {indexing ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <BrainCircuit className="h-4 w-4" />}
                {indexing ? "Indexing…" : indexRemaining ? `Index next batch (${indexRemaining} left)` : "Index for related search"}
              </Button>
            </section>

            <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {[
                { label: "Connected accounts", value: context.connected_accounts.length, icon: UsersRound },
                { label: "Included sources", value: context.sources.length, icon: Layers3 },
                { label: "Context items", value: context.item_count, icon: FileText },
                { label: "Estimated tokens", value: `${context.estimated_tokens} / ${context.token_budget}`, icon: BrainCircuit },
              ].map(({ label, value, icon: Icon }) => (
                <div key={label} className="rounded-2xl border border-zinc-200 bg-white p-5">
                  <div className="flex items-center gap-3 text-zinc-500">
                    <Icon className="h-4 w-4" />
                    <p className="text-sm">{label}</p>
                  </div>
                  <p className="mt-3 text-2xl font-semibold text-zinc-950">{value}</p>
                </div>
              ))}
            </section>

            <section className="rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6">
              <div className="flex flex-col gap-1">
                <h2 className="text-lg font-semibold text-zinc-950">People in this workspace</h2>
                <p className="text-sm text-zinc-500">
                  Classifications are workspace-specific and can be changed by a workspace owner or admin.
                </p>
              </div>
              {context.members.length ? (
                <ul className="mt-4 divide-y divide-zinc-100">
                  {context.members.map((member) => (
                    <li key={member.id} className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <p className="text-sm font-semibold text-zinc-900">{member.name}</p>
                        <p className="mt-0.5 text-xs text-zinc-500">@{member.username}</p>
                      </div>
                      <select
                        aria-label={`Classify ${member.name}`}
                        value={member.role_tag}
                        disabled={updatingMemberId === member.id}
                        onChange={(event) => void updateMemberClassification(
                          member.id,
                          event.target.value as "unknown" | "client" | "internal",
                        )}
                        className="min-h-10 rounded-lg border border-zinc-200 bg-white px-3 text-sm text-zinc-700 disabled:opacity-60"
                      >
                        <option value="unknown">Unclassified</option>
                        <option value="client">Client</option>
                        <option value="internal">Internal team</option>
                      </select>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-4 text-sm text-zinc-500">People appear here after the included boards sync.</p>
              )}
            </section>

            <section className="rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6">
              <div>
                <h2 className="text-lg font-semibold text-zinc-950">Find related work</h2>
                <p className="mt-1 text-sm text-zinc-500">
                  Search semantically across cards indexed from this workspace only.
                </p>
              </div>
              <form className="mt-4 flex flex-col gap-2 sm:flex-row" onSubmit={(event) => void searchRelated(event)}>
                <input
                  type="search"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  minLength={3}
                  maxLength={1000}
                  required
                  aria-label="Describe the work to find"
                  placeholder="e.g. recurring onboarding requests"
                  className="min-h-10 flex-1 rounded-lg border border-zinc-200 px-3 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                />
                <Button type="submit" className="gap-2 rounded-lg" disabled={searching || searchQuery.trim().length < 3}>
                  {searching ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  {searching ? "Searching…" : "Search"}
                </Button>
              </form>
              {searchResults.length ? (
                <ul className="mt-4 space-y-2">
                  {searchResults.map((result) => (
                    <li key={result.card_id}>
                      <a
                        href={result.url}
                        target="_blank"
                        rel="noreferrer"
                        className="block rounded-xl border border-zinc-100 p-4 transition hover:border-indigo-200 hover:bg-indigo-50/40"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-semibold text-zinc-900">{result.title}</p>
                          <span className="text-xs text-zinc-500">{Math.round(result.similarity * 100)}% match</span>
                        </div>
                        <p className="mt-1 line-clamp-2 text-sm text-zinc-600">{result.description}</p>
                        {result.client_name ? <p className="mt-2 text-xs text-zinc-500">{result.client_name}</p> : null}
                      </a>
                    </li>
                  ))}
                </ul>
              ) : null}
              {hasSearched && !searchResults.length ? (
                <p role="status" className="mt-4 text-sm text-zinc-500">
                  No related cards were found in this workspace.
                </p>
              ) : null}
            </section>

            <section className="rounded-2xl border border-zinc-200 bg-white p-5 sm:p-6">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-zinc-950">Included accounts and sources</h2>
                  <p className="mt-1 text-sm text-zinc-500">
                    Snapshot for {context.workspace_name}; generated {new Date(context.generated_at).toLocaleString()}.
                  </p>
                </div>
                {context.connected_accounts.length ? (
                  <span className="inline-flex items-center gap-1.5 text-sm font-medium text-emerald-700">
                    <CheckCircle2 className="h-4 w-4" />
                    {context.connected_accounts.length} connected
                  </span>
                ) : null}
              </div>
              <div className="mt-5 grid gap-3 md:grid-cols-2">
                {context.connected_accounts.map((account) => (
                  <div key={account.id} className="rounded-xl border border-zinc-100 bg-zinc-50 p-4">
                    <p className="text-sm font-semibold capitalize text-zinc-900">{account.provider}</p>
                    <p className="mt-1 text-sm text-zinc-600">{account.account_name}</p>
                  </div>
                ))}
                {context.sources.map((source) => (
                  <a
                    key={source.id}
                    href={source.url}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-xl border border-zinc-200 p-4 transition hover:border-indigo-200 hover:bg-indigo-50/40"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="truncate text-sm font-semibold text-zinc-900">{source.name}</p>
                      <ExternalLink className="h-4 w-4 shrink-0 text-zinc-400" />
                    </div>
                    <p className="mt-1 text-xs text-zinc-500">
                      {source.provider} · {source.account_name}
                    </p>
                    <p className="mt-2 inline-flex items-center gap-1 text-xs text-zinc-500">
                      <Clock3 className="h-3.5 w-3.5" />
                      {source.sync_status.replaceAll("_", " ")}
                    </p>
                  </a>
                ))}
                {!context.connected_accounts.length && !context.sources.length ? (
                  <p className="text-sm text-zinc-500">
                    No app accounts are linked yet. Connect an app from{" "}
                    <Link href="/dashboard/apps" className="font-semibold text-indigo-700">Connected Apps</Link>.
                  </p>
                ) : null}
              </div>
            </section>

            <section className="space-y-4">
              <div>
                <h2 className="text-lg font-semibold text-zinc-950">Ordered context chunks</h2>
                <p className="mt-1 text-sm text-zinc-500">
                  Chunks respect the selected token budget. Token counts are estimates and may differ from Gemini’s tokenizer.
                </p>
              </div>
              {context.chunks.length ? context.chunks.map((chunk) => (
                <details key={chunk.index} className="group rounded-2xl border border-zinc-200 bg-white">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 p-5">
                    <span className="font-semibold text-zinc-900">Chunk {chunk.index}</span>
                    <span className="text-sm text-zinc-500">
                      {chunk.items.length} items · ~{chunk.estimated_tokens} tokens
                    </span>
                  </summary>
                  <ol className="space-y-3 border-t border-zinc-100 p-5">
                    {chunk.items.map((item, index) => (
                      <li key={`${item.item_type}-${item.external_id ?? item.card_id ?? index}-${index}`} className="rounded-xl bg-zinc-50 p-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-indigo-700">
                            {item.item_type}
                          </span>
                          {item.source_name ? <span className="text-xs text-zinc-500">{item.source_name}</span> : null}
                          {item.client_name ? <span className="text-xs text-zinc-500">· {item.client_name}</span> : null}
                        </div>
                        {item.title ? <h3 className="mt-2 text-sm font-semibold text-zinc-900">{item.title}</h3> : null}
                        {item.text ? <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-6 text-zinc-600">{item.text}</p> : null}
                        {item.summary ? (
                          <p className="mt-2 rounded-lg border border-indigo-100 bg-indigo-50/60 p-3 text-sm leading-6 text-indigo-950">
                            <span className="font-semibold">Cached summary: </span>{item.summary}
                          </p>
                        ) : null}
                      </li>
                    ))}
                  </ol>
                </details>
              )) : (
                <div className="rounded-2xl border border-dashed border-zinc-300 bg-white p-6 text-sm text-zinc-500">
                  No included, synchronized sources are available yet. Connect an app and include a source to build context.
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </DashboardTemplate>
  );
}
