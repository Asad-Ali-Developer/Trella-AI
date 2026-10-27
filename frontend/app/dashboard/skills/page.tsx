"use client";

import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  Clock,
  Coins,
  ExternalLink,
  Layers,
  LoaderCircle,
  Play,
  RotateCw,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  UserCheck,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/atoms/Button";
import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { clearSession, setAuthenticatedUser } from "@/lib/authSlice";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { workspaceStore } from "@/lib/storage";
import type { Run, RunDetail, Skill, Workspace } from "@/lib/types";
import { authService } from "@/services/AuthService";
import { runService } from "@/services/RunService";
import { skillService } from "@/services/SkillService";
import { workspaceService } from "@/services/WorkspaceService";

export default function SkillsAndReportsPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [selectedSkillId, setSelectedSkillId] = useState<string>("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [activeRunDetail, setActiveRunDetail] = useState<RunDetail | null>(null);

  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [feedbackLoading, setFeedbackLoading] = useState<Record<string, boolean>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadInitialData = useCallback(async () => {
    try {
      const [currentUser, workspaceList] = await Promise.all([
        authService.me(),
        workspaceService.list(),
      ]);
      dispatch(setAuthenticatedUser(currentUser));
      setWorkspaces(workspaceList);

      const storedId = workspaceStore.getWorkspaceId();
      const workspace =
        workspaceList.find((item) => item.id === storedId) ?? workspaceList[0] ?? null;

      if (workspace) {
        workspaceStore.setWorkspaceId(workspace.id);
        setSelectedWorkspace(workspace);
        await loadWorkspaceSkillsAndRuns(workspace.id);
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
    void loadInitialData();
  }, [loadInitialData]);

  async function loadWorkspaceSkillsAndRuns(workspaceId: string) {
    setError("");
    try {
      const [skillsList, runsList] = await Promise.all([
        skillService.list(workspaceId),
        runService.list(workspaceId),
      ]);
      setSkills(skillsList);
      if (skillsList.length > 0 && !selectedSkillId) {
        setSelectedSkillId(skillsList[0].id);
      }
      setRuns(runsList);

      if (runsList.length > 0) {
        const latestRun = await runService.get(workspaceId, runsList[0].id);
        setActiveRunDetail(latestRun);
      } else {
        setActiveRunDetail(null);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to load skills and runs.";
      setError(message);
    }
  }

  async function handleSelectWorkspace(workspace: Workspace) {
    workspaceStore.setWorkspaceId(workspace.id);
    setSelectedWorkspace(workspace);
    setActiveRunDetail(null);
    await loadWorkspaceSkillsAndRuns(workspace.id);
  }

  async function handleRunSkill() {
    if (!selectedWorkspace || !selectedSkillId) return;
    setRunning(true);
    setError("");
    setNotice("");

    try {
      // Execute synchronous execution for immediate feedback
      const createdRun = await runService.create(
        selectedWorkspace.id,
        { skill_id: selectedSkillId, trigger: "manual" },
        false, // execute synchronous
      );

      if (createdRun.status === "failed") {
        setError(createdRun.error || "Skill execution encountered an error.");
      } else {
        setNotice("Analysis run completed successfully!");
      }
      // Reload runs list and set this run as active
      const updatedRuns = await runService.list(selectedWorkspace.id);
      setRuns(updatedRuns);
      const detail = await runService.get(selectedWorkspace.id, createdRun.id);
      setActiveRunDetail(detail);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Skill execution failed.";
      setError(message);
    } finally {
      setRunning(false);
    }
  }

  async function handleSelectPastRun(runId: string) {
    if (!selectedWorkspace) return;
    try {
      const detail = await runService.get(selectedWorkspace.id, runId);
      setActiveRunDetail(detail);
    } catch {
      setError("Failed to load run details.");
    }
  }

  async function handleFeedback(insightId: string, feedback: "thumbs_up" | "thumbs_down") {
    if (!selectedWorkspace || !activeRunDetail) return;
    setFeedbackLoading((prev) => ({ ...prev, [insightId]: true }));
    try {
      const updatedInsight = await runService.submitFeedback(
        selectedWorkspace.id,
        insightId,
        feedback,
      );

      // Update state locally
      setActiveRunDetail((prev) => {
        if (!prev) return null;
        return {
          ...prev,
          insights: prev.insights.map((ins) =>
            ins.id === insightId ? { ...ins, feedback: updatedInsight.feedback } : ins,
          ),
        };
      });
    } catch {
      setError("Could not submit feedback.");
    } finally {
      setFeedbackLoading((prev) => ({ ...prev, [insightId]: false }));
    }
  }

  function handleLogout() {
    authService.logout().finally(() => {
      dispatch(clearSession());
      workspaceStore.clear();
      router.replace("/login");
    });
  }

  const selectedSkill = skills.find((s) => s.id === selectedSkillId);

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
              <Sparkles className="h-3.5 w-3.5" />
              Phase 4: LLM Layer & Skill Engine
            </div>
            <h1 className="mt-2 text-2xl font-bold tracking-tight text-zinc-900 md:text-3xl">
              AI Skills & Insights
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              Run intelligence skills over your workspace context graph to extract needs, risks,
              and stakeholder patterns with verified citations.
            </p>
          </div>

          <Button
            onClick={handleRunSkill}
            disabled={running || !selectedSkillId || loading}
            className="inline-flex h-11 items-center gap-2 rounded-xl bg-indigo-600 px-6 font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50"
          >
            {running ? (
              <>
                <LoaderCircle className="h-4 w-4 animate-spin" />
                Running Analysis…
              </>
            ) : (
              <>
                <Play className="h-4 w-4 fill-white" />
                Run Analysis Now
              </>
            )}
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

        {/* Skill Selector Cards */}
        <div className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-500">
            Select a Skill to Execute
          </h2>
          <div className="grid gap-4 md:grid-cols-2">
            {skills.map((skill) => {
              const isSelected = skill.id === selectedSkillId;
              return (
                <div
                  key={skill.id}
                  onClick={() => setSelectedSkillId(skill.id)}
                  className={`cursor-pointer rounded-2xl border p-5 transition-all ${
                    isSelected
                      ? "border-indigo-600 bg-indigo-50/40 shadow-sm"
                      : "border-zinc-200 bg-white hover:border-zinc-300"
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex h-10 w-10 items-center justify-center rounded-xl ${
                          isSelected ? "bg-indigo-600 text-white" : "bg-zinc-100 text-zinc-600"
                        }`}
                      >
                        <Brain className="h-5 w-5" />
                      </div>
                      <div>
                        <h3 className="font-semibold text-zinc-900">{skill.name}</h3>
                        <p className="text-xs text-zinc-400">v{skill.version} • {skill.slug}</p>
                      </div>
                    </div>
                    {isSelected && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-indigo-100 px-2.5 py-0.5 text-xs font-medium text-indigo-800">
                        Active
                      </span>
                    )}
                  </div>
                  <p className="mt-3 text-sm text-zinc-600">{skill.description}</p>
                  <div className="mt-4 flex items-center gap-4 text-xs text-zinc-400">
                    <span>
                      Model: <strong>{String((skill.model_config_json as Record<string, unknown>)?.model || "gemini-3.5-flash")}</strong>
                    </span>
                    <span>•</span>
                    <span>Provider: <strong>Google Gemini</strong></span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Active Run Report & Details */}
        {activeRunDetail ? (
          <div className="space-y-6">
            {/* Run Metadata Banner */}
            <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-4 border-b border-zinc-100 pb-4">
                <div className="flex items-center gap-3">
                  <div
                    className={`flex h-8 w-8 items-center justify-center rounded-lg ${
                      activeRunDetail.status === "completed"
                        ? "bg-emerald-100 text-emerald-700"
                        : activeRunDetail.status === "failed"
                        ? "bg-rose-100 text-rose-700"
                        : "bg-amber-100 text-amber-700"
                    }`}
                  >
                    {activeRunDetail.status === "completed" ? (
                      <CheckCircle2 className="h-5 w-5" />
                    ) : activeRunDetail.status === "failed" ? (
                      <AlertTriangle className="h-5 w-5 text-rose-600" />
                    ) : (
                      <LoaderCircle className="h-5 w-5 animate-spin" />
                    )}
                  </div>
                  <div>
                    <h3 className="font-semibold text-zinc-900">
                      Report: {selectedSkill?.name || "Skill Execution"}
                    </h3>
                    <p className="text-xs text-zinc-400">
                      Status: <strong className="capitalize">{activeRunDetail.status}</strong> • Executed on{" "}
                      {new Date(activeRunDetail.created_at).toLocaleString()}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  {activeRunDetail.status === "completed" && (
                    activeRunDetail.citations_valid ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 border border-emerald-200">
                        <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
                        All Citations Grounded
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700 border border-amber-200">
                        <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
                        Contains Ungrounded Citations
                      </span>
                    )
                  )}
                  {activeRunDetail.status === "failed" && (
                    <Button
                      onClick={handleRunSkill}
                      disabled={running}
                      className="rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-700"
                    >
                      Retry Analysis
                    </Button>
                  )}
                </div>
              </div>

              {/* Error Notice if Failed */}
              {activeRunDetail.status === "failed" && (
                <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4">
                  <div className="flex items-start gap-2.5">
                    <AlertTriangle className="h-5 w-5 text-rose-600 flex-shrink-0 mt-0.5" />
                    <div>
                      <h4 className="text-sm font-semibold text-rose-900">Analysis Failed</h4>
                      <p className="mt-1 text-xs text-rose-700 leading-relaxed">
                        {activeRunDetail.error || "The analysis run encountered an error or upstream model timeout. Please click 'Retry Analysis' to run again."}
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Metrics Grid */}
              <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
                <div className="rounded-xl bg-zinc-50 p-3">
                  <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                    <Coins className="h-3.5 w-3.5" />
                    Estimated Cost
                  </div>
                  <p className="mt-1 text-base font-bold text-zinc-900">
                    ${activeRunDetail.cost_usd.toFixed(6)}
                  </p>
                </div>

                <div className="rounded-xl bg-zinc-50 p-3">
                  <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                    <Layers className="h-3.5 w-3.5" />
                    Prompt Tokens
                  </div>
                  <p className="mt-1 text-base font-bold text-zinc-900">
                    {activeRunDetail.tokens_in.toLocaleString()}
                  </p>
                </div>

                <div className="rounded-xl bg-zinc-50 p-3">
                  <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                    <Sparkles className="h-3.5 w-3.5" />
                    Completion Tokens
                  </div>
                  <p className="mt-1 text-base font-bold text-zinc-900">
                    {activeRunDetail.tokens_out.toLocaleString()}
                  </p>
                </div>

                <div className="rounded-xl bg-zinc-50 p-3">
                  <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                    <Clock className="h-3.5 w-3.5" />
                    Trigger
                  </div>
                  <p className="mt-1 text-base font-bold capitalize text-zinc-900">
                    {activeRunDetail.trigger}
                  </p>
                </div>
              </div>

              {/* Executive Summary */}
              {activeRunDetail.output_json?.executive_summary && (
                <div className="mt-5 rounded-xl border border-indigo-100 bg-indigo-50/50 p-4">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-indigo-900">
                    Executive Summary
                  </h4>
                  <p className="mt-1.5 text-sm leading-relaxed text-zinc-800">
                    {activeRunDetail.output_json.executive_summary}
                  </p>
                </div>
              )}
            </div>

            {/* Individual Insight Blocks */}
            <div className="space-y-4">
              <h3 className="text-base font-bold text-zinc-900">
                Extracted Insights ({activeRunDetail.insights.length})
              </h3>

              {activeRunDetail.insights.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-zinc-200 p-8 text-center text-sm text-zinc-500">
                  No individual insights were generated for this run.
                </div>
              ) : (
                <div className="grid gap-4">
                  {activeRunDetail.insights.map((insight) => {
                    const isVoting = feedbackLoading[insight.id] || false;
                    return (
                      <div
                        key={insight.id}
                        className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm transition-all hover:border-zinc-300"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="space-y-1">
                            <div className="flex items-center gap-2">
                              <span
                                className={`rounded-md px-2 py-0.5 text-xs font-semibold uppercase tracking-wider ${
                                  insight.category === "need"
                                    ? "bg-blue-50 text-blue-700 border border-blue-200"
                                    : insight.category === "risk"
                                    ? "bg-rose-50 text-rose-700 border border-rose-200"
                                    : insight.category === "stakeholder"
                                    ? "bg-purple-50 text-purple-700 border border-purple-200"
                                    : "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                }`}
                              >
                                {insight.category}
                              </span>

                              {insight.severity_or_priority && (
                                <span className="rounded-md bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-600">
                                  {insight.severity_or_priority} priority
                                </span>
                              )}
                            </div>

                            <h4 className="pt-1 text-base font-semibold text-zinc-900">
                              {insight.title}
                            </h4>
                          </div>

                          {/* Thumbs Up / Down Feedback */}
                          <div className="flex items-center gap-1 rounded-lg border border-zinc-200 p-1">
                            <button
                              onClick={() => handleFeedback(insight.id, "thumbs_up")}
                              disabled={isVoting}
                              title="Helpful insight"
                              className={`rounded p-1.5 transition-colors ${
                                insight.feedback === "thumbs_up"
                                  ? "bg-emerald-100 text-emerald-700"
                                  : "text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
                              }`}
                            >
                              <ThumbsUp className="h-4 w-4" />
                            </button>
                            <button
                              onClick={() => handleFeedback(insight.id, "thumbs_down")}
                              disabled={isVoting}
                              title="Inaccurate insight"
                              className={`rounded p-1.5 transition-colors ${
                                insight.feedback === "thumbs_down"
                                  ? "bg-red-100 text-red-700"
                                  : "text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
                              }`}
                            >
                              <ThumbsDown className="h-4 w-4" />
                            </button>
                          </div>
                        </div>

                        <p className="mt-2 text-sm text-zinc-600 leading-relaxed">
                          {insight.detail}
                        </p>

                        {/* Citations & Source Links */}
                        {insight.source_refs && insight.source_refs.length > 0 && (
                          <div className="mt-4 border-t border-zinc-100 pt-3">
                            <p className="text-xs font-medium text-zinc-400">Cited Sources:</p>
                            <div className="mt-1.5 flex flex-wrap gap-2">
                              {insight.source_refs.map((src, idx) => (
                                <div
                                  key={idx}
                                  className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs ${
                                    src.valid
                                      ? "border-zinc-200 bg-zinc-50 text-zinc-700"
                                      : "border-red-200 bg-red-50 text-red-700"
                                  }`}
                                >
                                  <span className="font-mono text-[11px] text-zinc-500">
                                    [{src.source_id}]
                                  </span>
                                  <span className="font-medium">
                                    {src.title || src.source_type}
                                  </span>
                                  {src.url && (
                                    <a
                                      href={src.url}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="text-indigo-600 hover:underline"
                                    >
                                      <ExternalLink className="h-3 w-3" />
                                    </a>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-zinc-200 bg-white p-12 text-center">
            <Sparkles className="mx-auto h-8 w-8 text-indigo-400" />
            <h3 className="mt-2 text-base font-semibold text-zinc-900">No Runs Performed Yet</h3>
            <p className="mt-1 text-sm text-zinc-500">
              Click the &quot;Run Analysis Now&quot; button above to generate structured insights
              with citations from your workspace context.
            </p>
          </div>
        )}

        {/* Run History Table */}
        {runs.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-500">
              Execution History
            </h3>
            <div className="overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm">
              <table className="w-full text-left text-sm text-zinc-600">
                <thead className="border-b border-zinc-100 bg-zinc-50 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                  <tr>
                    <th className="px-5 py-3">Date</th>
                    <th className="px-5 py-3">Status</th>
                    <th className="px-5 py-3">Tokens</th>
                    <th className="px-5 py-3">Cost (USD)</th>
                    <th className="px-5 py-3">Citations</th>
                    <th className="px-5 py-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100">
                  {runs.map((r) => (
                    <tr
                      key={r.id}
                      className={`hover:bg-zinc-50 transition-colors ${
                        activeRunDetail?.id === r.id ? "bg-indigo-50/30" : ""
                      }`}
                    >
                      <td className="px-5 py-3.5 font-medium text-zinc-900">
                        {new Date(r.created_at).toLocaleString()}
                      </td>
                      <td className="px-5 py-3.5">
                        <span
                          className={`rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${
                            r.status === "completed"
                              ? "bg-emerald-50 text-emerald-700"
                              : "bg-amber-50 text-amber-700"
                          }`}
                        >
                          {r.status}
                        </span>
                      </td>
                      <td className="px-5 py-3.5">
                        {(r.tokens_in + r.tokens_out).toLocaleString()}
                      </td>
                      <td className="px-5 py-3.5 font-mono text-xs">
                        ${r.cost_usd.toFixed(6)}
                      </td>
                      <td className="px-5 py-3.5">
                        {r.citations_valid ? (
                          <span className="text-xs text-emerald-600 font-medium">Grounded</span>
                        ) : (
                          <span className="text-xs text-amber-600 font-medium">Ungrounded</span>
                        )}
                      </td>
                      <td className="px-5 py-3.5 text-right">
                        <button
                          onClick={() => handleSelectPastRun(r.id)}
                          className="font-semibold text-indigo-600 hover:text-indigo-800"
                        >
                          View Report
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </DashboardTemplate>
  );
}
