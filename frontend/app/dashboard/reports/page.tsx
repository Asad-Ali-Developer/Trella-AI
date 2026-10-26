"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Coins,
  ExternalLink,
  FileText,
  Filter,
  Layers,
  LoaderCircle,
  Play,
  RotateCcw,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/atoms/Button";
import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { workspaceStore } from "@/lib/storage";
import type { ClientSummary, Run, Skill, User, Workspace } from "@/lib/types";
import { authService } from "@/services/AuthService";
import { clientService } from "@/services/ClientService";
import { runService } from "@/services/RunService";
import { skillService } from "@/services/SkillService";
import { workspaceService } from "@/services/WorkspaceService";

export default function ReportsAndRunsPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);

  const [runs, setRuns] = useState<Run[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [clients, setClients] = useState<ClientSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Filters
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [clientFilter, setClientFilter] = useState<string>("all");

  // New Run Trigger Drawer
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [running, setRunning] = useState(false);

  const loadInitialData = useCallback(async () => {
    try {
      setLoading(true);
      setError("");
      const [currentUser, workspaceList] = await Promise.all([
        authService.me(),
        workspaceService.list(),
      ]);
      setUser(currentUser);
      setWorkspaces(workspaceList);

      if (workspaceList.length === 0) {
        setLoading(false);
        return;
      }

      const storedId = workspaceStore.getWorkspaceId();
      const current =
        workspaceList.find((w: Workspace) => w.id === storedId) ?? workspaceList[0];
      setSelectedWorkspace(current);
      workspaceStore.setWorkspaceId(current.id);

      await loadWorkspaceRunsAndMeta(current.id);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to load reports.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadInitialData();
  }, [loadInitialData]);

  async function loadWorkspaceRunsAndMeta(workspaceId: string) {
    try {
      const [runsList, skillsList, clientsList] = await Promise.all([
        runService.list(workspaceId),
        skillService.list(workspaceId),
        clientService.list(workspaceId),
      ]);
      setRuns(runsList);
      setSkills(skillsList);
      if (skillsList.length > 0 && !selectedSkillId) {
        setSelectedSkillId(skillsList[0].id);
      }
      setClients(clientsList);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to load run history.";
      setError(message);
    }
  }

  // Live polling for running/pending executions
  useEffect(() => {
    if (!selectedWorkspace) return;
    const hasPendingOrRunning = runs.some(
      (r) => r.status === "pending" || r.status === "running",
    );
    if (!hasPendingOrRunning) return;

    const interval = setInterval(async () => {
      try {
        const updated = await runService.list(selectedWorkspace.id);
        setRuns(updated);
      } catch {
        // silent poll error
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [runs, selectedWorkspace]);

  async function handleSelectWorkspace(workspace: Workspace) {
    workspaceStore.setWorkspaceId(workspace.id);
    setSelectedWorkspace(workspace);
    await loadWorkspaceRunsAndMeta(workspace.id);
  }

  async function handleStartRun(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedWorkspace || !selectedSkillId) return;
    setRunning(true);
    setError("");
    setNotice("");

    try {
      const created = await runService.create(
        selectedWorkspace.id,
        {
          skill_id: selectedSkillId,
          client_id: selectedClientId || null,
          trigger: "manual",
        },
        false, // Synchronous for immediate feedback
      );

      if (created.status === "failed") {
        setError(created.error || "Analysis encountered an error during execution.");
      } else {
        setNotice("Analysis run completed! View the structured report below.");
      }

      setIsModalOpen(false);
      // Refresh runs list
      const updated = await runService.list(selectedWorkspace.id);
      setRuns(updated);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Run execution failed.";
      setError(message);
    } finally {
      setRunning(false);
    }
  }

  async function handleLogout() {
    await authService.logout();
    router.replace("/login");
  }

  const filteredRuns = runs.filter((r) => {
    if (statusFilter !== "all" && r.status !== statusFilter) return false;
    if (clientFilter !== "all" && r.client_id !== clientFilter) return false;
    return true;
  });

  const totalTokens = runs.reduce((acc, r) => acc + r.tokens_in + r.tokens_out, 0);
  const totalCost = runs.reduce((acc, r) => acc + r.cost_usd, 0);
  const completedRunsCount = runs.filter((r) => r.status === "completed").length;

  return (
    <DashboardTemplate
      sidebar={
        <Sidebar
          user={user}
          workspaces={workspaces}
          selectedId={selectedWorkspace?.id ?? null}
          onSelectWorkspace={handleSelectWorkspace}
          onLogout={handleLogout}
        />
      }
    >
      <div className="mx-auto max-w-6xl space-y-8 p-6 md:p-8">
        {/* Header */}
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700">
              <FileText className="h-3.5 w-3.5" />
              Phase 5: Reports & Execution History
            </div>
            <h1 className="mt-2 text-2xl font-bold tracking-tight text-zinc-900 md:text-3xl">
              Reports & Run History
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              Inspect intelligence reports generated from your connected project boards. Every claim
              is grounded against verified Trello cards, GitHub commits, and Jira issues.
            </p>
          </div>

          <Button
            onClick={() => setIsModalOpen(true)}
            className="inline-flex h-11 items-center gap-2 rounded-xl bg-indigo-600 px-6 font-semibold text-white shadow-sm hover:bg-indigo-700"
          >
            <Play className="h-4 w-4 fill-white" />
            Run New Analysis
          </Button>
        </div>

        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </div>
        )}
        {notice && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
            {notice}
          </div>
        )}

        {/* Aggregated KPI Strip */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-zinc-500">
              <FileText className="h-4 w-4 text-zinc-400" />
              Total Runs
            </div>
            <p className="mt-2 text-2xl font-bold text-zinc-900">{runs.length}</p>
          </div>

          <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-zinc-500">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              Completed Reports
            </div>
            <p className="mt-2 text-2xl font-bold text-emerald-600">{completedRunsCount}</p>
          </div>

          <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-zinc-500">
              <Layers className="h-4 w-4 text-indigo-500" />
              Processed Tokens
            </div>
            <p className="mt-2 text-2xl font-bold text-zinc-900">{totalTokens.toLocaleString()}</p>
          </div>

          <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-zinc-500">
              <Coins className="h-4 w-4 text-zinc-400" />
              Estimated LLM Cost
            </div>
            <p className="mt-2 text-2xl font-bold text-zinc-900">${totalCost.toFixed(5)}</p>
          </div>
        </div>

        {/* Filters Strip */}
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-zinc-200 pb-4">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xs font-bold uppercase tracking-wider text-zinc-400">Filter:</span>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="h-9 rounded-xl border border-zinc-200 bg-white px-3 text-xs font-medium text-zinc-700 focus:border-indigo-500 focus:outline-none"
            >
              <option value="all">All Statuses</option>
              <option value="completed">Completed</option>
              <option value="running">Running</option>
              <option value="failed">Failed</option>
            </select>

            <select
              value={clientFilter}
              onChange={(e) => setClientFilter(e.target.value)}
              className="h-9 rounded-xl border border-zinc-200 bg-white px-3 text-xs font-medium text-zinc-700 focus:border-indigo-500 focus:outline-none"
            >
              <option value="all">All Clients</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          <span className="text-xs text-zinc-400">
            Showing {filteredRuns.length} of {runs.length} runs
          </span>
        </div>

        {/* Runs History Table */}
        {loading ? (
          <div className="flex h-64 items-center justify-center rounded-2xl border border-zinc-200 bg-white">
            <div className="flex items-center gap-2 text-zinc-500">
              <LoaderCircle className="h-5 w-5 animate-spin" />
              Loading run history…
            </div>
          </div>
        ) : filteredRuns.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-300 bg-white p-12 text-center">
            <FileText className="mx-auto h-12 w-12 text-zinc-300" />
            <h3 className="mt-4 text-base font-semibold text-zinc-900">No reports generated yet</h3>
            <p className="mt-1 text-sm text-zinc-500 max-w-sm mx-auto">
              Execute your first skill analysis to generate an executive report with verified citations.
            </p>
            <Button
              onClick={() => setIsModalOpen(true)}
              className="mt-5 inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-5 text-sm font-semibold text-white hover:bg-indigo-700"
            >
              <Play className="h-4 w-4 fill-white" />
              Run Analysis Now
            </Button>
          </div>
        ) : (
          <div className="divide-y divide-zinc-200 rounded-2xl border border-zinc-200 bg-white shadow-sm overflow-hidden">
            {filteredRuns.map((run) => {
              const client = clients.find((c) => c.id === run.client_id);
              const skill = skills.find((s) => s.id === run.skill_id);
              const isRunning = run.status === "running" || run.status === "pending";

              return (
                <div
                  key={run.id}
                  className="flex flex-col justify-between gap-4 p-5 hover:bg-zinc-50/70 transition-colors sm:flex-row sm:items-center"
                >
                  <div className="flex items-start gap-4">
                    <div
                      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl font-bold ${
                        run.status === "completed"
                          ? "bg-emerald-100 text-emerald-700"
                          : run.status === "failed"
                          ? "bg-rose-100 text-rose-700"
                          : "bg-amber-100 text-amber-700"
                      }`}
                    >
                      {run.status === "completed" ? (
                        <CheckCircle2 className="h-5 w-5" />
                      ) : run.status === "failed" ? (
                        <AlertTriangle className="h-5 w-5" />
                      ) : (
                        <LoaderCircle className="h-5 w-5 animate-spin" />
                      )}
                    </div>

                    <div>
                      <div className="flex items-center gap-2.5">
                        <h4 className="font-bold text-zinc-900">
                          {run.skill_name || skill?.name || "Client Needs Analyzer"}
                        </h4>
                        <span
                          className={`rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${
                            run.status === "completed"
                              ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                              : run.status === "failed"
                              ? "bg-rose-50 text-rose-700 border border-rose-200"
                              : "bg-amber-50 text-amber-700 border border-amber-200"
                          }`}
                        >
                          {run.status}
                        </span>
                        {run.status === "completed" && run.citations_valid && (
                          <span className="hidden sm:inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-700 border border-indigo-200">
                            <ShieldCheck className="h-3 w-3 text-indigo-600" />
                            Grounded
                          </span>
                        )}
                      </div>

                      <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-zinc-400">
                        <span>
                          Client: <strong>{run.client_name || client?.name || "All Clients"}</strong>
                        </span>
                        <span>•</span>
                        <span>Trigger: <strong className="capitalize">{run.trigger}</strong></span>
                        <span>•</span>
                        <span>{new Date(run.created_at).toLocaleString()}</span>
                      </div>
                    </div>
                  </div>

                  {/* Metrics & Action Link */}
                  <div className="flex items-center justify-between sm:justify-end gap-6 pt-2 sm:pt-0 border-t sm:border-t-0 border-zinc-100">
                    <div className="text-right text-xs">
                      <p className="font-semibold text-zinc-800">
                        {(run.tokens_in + run.tokens_out).toLocaleString()} tokens
                      </p>
                      <p className="text-zinc-400">${run.cost_usd.toFixed(6)}</p>
                    </div>

                    <Link
                      href={`/dashboard/reports/${run.id}`}
                      className="inline-flex items-center gap-1.5 rounded-xl bg-indigo-50 px-4 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-600 hover:text-white transition-colors"
                    >
                      View Report
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Run Analysis Modal */}
        {isModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
            <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl border border-zinc-100">
              <h3 className="text-lg font-bold text-zinc-900">Run Intelligence Skill</h3>
              <p className="mt-1 text-xs text-zinc-500">
                Execute an AI skill across your workspace context graph to generate an executive report
                and extract verified citations.
              </p>

              <form onSubmit={handleStartRun} className="mt-5 space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-zinc-700">Choose Skill</label>
                  <select
                    value={selectedSkillId}
                    onChange={(e) => setSelectedSkillId(e.target.value)}
                    className="mt-1 h-10 w-full rounded-xl border border-zinc-200 px-3 text-sm focus:border-indigo-500 focus:outline-none"
                  >
                    {skills.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name} (v{s.version})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-zinc-700">
                    Target Client (Optional)
                  </label>
                  <select
                    value={selectedClientId}
                    onChange={(e) => setSelectedClientId(e.target.value)}
                    className="mt-1 h-10 w-full rounded-xl border border-zinc-200 px-3 text-sm focus:border-indigo-500 focus:outline-none"
                  >
                    <option value="">All Clients (Whole Workspace)</option>
                    {clients.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex items-center justify-end gap-2 pt-3">
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setIsModalOpen(false)}
                    className="text-xs"
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    disabled={running}
                    className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {running ? (
                      <>
                        <LoaderCircle className="h-4 w-4 animate-spin" />
                        Running…
                      </>
                    ) : (
                      <>
                        <Play className="h-3.5 w-3.5 fill-white" />
                        Execute Now
                      </>
                    )}
                  </Button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </DashboardTemplate>
  );
}
