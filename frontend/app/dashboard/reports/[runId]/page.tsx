"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock,
  Coins,
  Copy,
  Download,
  ExternalLink,
  FileText,
  Layers,
  LoaderCircle,
  RotateCcw,
  Share2,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  TrendingUp,
  Users,
} from "lucide-react";

import { Button } from "@/components/atoms/Button";
import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { workspaceStore } from "@/lib/storage";
import type { Insight, RunDetail, User, Workspace } from "@/lib/types";
import { authService } from "@/services/AuthService";
import { runService } from "@/services/RunService";
import { workspaceService } from "@/services/WorkspaceService";

export default function ReportDetailPage() {
  const router = useRouter();
  const params = useParams<{ runId: string }>();
  const runId = params?.runId;

  const [user, setUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);

  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  // Thumbs Feedback
  const [feedbackLoading, setFeedbackLoading] = useState<Record<string, boolean>>({});

  const loadData = useCallback(async () => {
    if (!runId) return;
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

      const runDetail = await runService.get(current.id, runId);
      setRun(runDetail);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to load report.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  async function handleSelectWorkspace(workspace: Workspace) {
    workspaceStore.setWorkspaceId(workspace.id);
    setSelectedWorkspace(workspace);
    router.push("/dashboard/reports");
  }

  async function handleFeedback(insightId: string, type: "thumbs_up" | "thumbs_down") {
    if (!selectedWorkspace || !run) return;
    setFeedbackLoading((prev) => ({ ...prev, [insightId]: true }));
    try {
      const updated = await runService.submitFeedback(
        selectedWorkspace.id,
        insightId,
        type,
      );

      setRun((prev) => {
        if (!prev) return null;
        return {
          ...prev,
          insights: prev.insights.map((item) =>
            item.id === insightId ? { ...item, feedback: updated.feedback } : item,
          ),
        };
      });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to submit feedback.";
      setError(message);
    } finally {
      setFeedbackLoading((prev) => ({ ...prev, [insightId]: false }));
    }
  }

  function handleCopyMarkdown() {
    if (!run) return;
    let md = `# Executive Report: ${run.skill_name || "Skill Execution"}\n\n`;
    md += `**Client:** ${run.client_name || "All Clients"}\n`;
    md += `**Date:** ${new Date(run.created_at).toLocaleString()}\n`;
    md += `**Citations Valid:** ${run.citations_valid ? "Yes" : "No"}\n\n`;

    if (run.output_json?.executive_summary) {
      md += `## Executive Summary\n${run.output_json.executive_summary}\n\n`;
    }

    if (run.insights.length > 0) {
      md += `## Extracted Insights\n`;
      for (const ins of run.insights) {
        md += `### [${ins.category.toUpperCase()}] ${ins.title}\n`;
        md += `${ins.detail}\n`;
        if (ins.source_refs?.length > 0) {
          md += `*Sources:*\n`;
          for (const s of ins.source_refs) {
            md += `- [${s.source_type}] ${s.title || s.source_id} (${s.url || "internal"})\n`;
          }
        }
        md += `\n`;
      }
    }

    navigator.clipboard.writeText(md);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  }

  function handleExportJSON() {
    if (!run) return;
    const blob = new Blob([JSON.stringify(run, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `report-${run.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function handleLogout() {
    await authService.logout();
    router.replace("/login");
  }

  if (loading) {
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
        <div className="flex h-96 items-center justify-center">
          <div className="flex items-center gap-3 text-zinc-500">
            <LoaderCircle className="h-6 w-6 animate-spin text-indigo-600" />
            Loading report…
          </div>
        </div>
      </DashboardTemplate>
    );
  }

  if (!run) {
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
        <div className="p-8 text-center">
          <p className="text-zinc-500">Report not found.</p>
          <Link
            href="/dashboard/reports"
            className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-indigo-600 hover:underline"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Reports & Runs
          </Link>
        </div>
      </DashboardTemplate>
    );
  }

  const needs = run.insights.filter((i) => i.category === "need");
  const patterns = run.insights.filter((i) => i.category === "pattern");
  const stakeholders = run.insights.filter((i) => i.category === "stakeholder");
  const risks = run.insights.filter((i) => i.category === "risk");

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
      <div className="mx-auto max-w-5xl space-y-8 p-6 md:p-8">
        {/* Navigation Breadcrumb */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs font-medium text-zinc-400">
            <Link href="/dashboard" className="hover:text-zinc-700">
              Dashboard
            </Link>
            <ChevronRight className="h-3 w-3" />
            <Link href="/dashboard/reports" className="hover:text-zinc-700">
              Reports
            </Link>
            <ChevronRight className="h-3 w-3" />
            <span className="text-zinc-800">Report {run.id.slice(0, 8)}</span>
          </div>

          <div className="flex items-center gap-2">
            <Button
              onClick={handleCopyMarkdown}
              variant="ghost"
              className="h-9 gap-1.5 rounded-xl border border-zinc-200 bg-white px-3 text-xs font-medium text-zinc-700 hover:bg-zinc-50"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? "Copied Markdown" : "Copy Markdown"}
            </Button>
            <Button
              onClick={handleExportJSON}
              variant="ghost"
              className="h-9 gap-1.5 rounded-xl border border-zinc-200 bg-white px-3 text-xs font-medium text-zinc-700 hover:bg-zinc-50"
            >
              <Download className="h-3.5 w-3.5" />
              Export JSON
            </Button>
          </div>
        </div>

        {/* Hero Header */}
        <div className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-zinc-100 pb-5">
            <div className="flex items-center gap-4">
              <div
                className={`flex h-12 w-12 items-center justify-center rounded-2xl ${
                  run.status === "completed"
                    ? "bg-emerald-100 text-emerald-700"
                    : run.status === "failed"
                    ? "bg-rose-100 text-rose-700"
                    : "bg-amber-100 text-amber-700"
                }`}
              >
                {run.status === "completed" ? (
                  <CheckCircle2 className="h-6 w-6" />
                ) : run.status === "failed" ? (
                  <AlertTriangle className="h-6 w-6" />
                ) : (
                  <LoaderCircle className="h-6 w-6 animate-spin" />
                )}
              </div>
              <div>
                <h1 className="text-xl font-bold text-zinc-900 md:text-2xl">
                  {run.skill_name || "Client Needs Analyzer"}
                </h1>
                <p className="mt-1 text-xs text-zinc-400">
                  Target: <strong>{run.client_name || "All Clients"}</strong> • Executed on{" "}
                  {new Date(run.created_at).toLocaleString()}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              {run.citations_valid ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 border border-emerald-200">
                  <ShieldCheck className="h-4 w-4 text-emerald-600" />
                  All Citations Grounded
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700 border border-amber-200">
                  <AlertTriangle className="h-4 w-4 text-amber-600" />
                  Contains Ungrounded Citations
                </span>
              )}
            </div>
          </div>

          {/* Failure Alert if Failed */}
          {run.status === "failed" && (
            <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4">
              <div className="flex items-start gap-2.5">
                <AlertTriangle className="h-5 w-5 text-rose-600 flex-shrink-0 mt-0.5" />
                <div>
                  <h4 className="text-sm font-semibold text-rose-900">Execution Error</h4>
                  <p className="mt-1 text-xs text-rose-700 leading-relaxed">
                    {run.error || "The analysis run timed out or was interrupted. Please retry from the Reports dashboard."}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Metrics Strip */}
          <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="rounded-xl bg-zinc-50 p-3.5">
              <span className="flex items-center gap-1.5 text-xs text-zinc-500">
                <Coins className="h-3.5 w-3.5" />
                Cost (USD)
              </span>
              <p className="mt-1 text-base font-bold text-zinc-900">${run.cost_usd.toFixed(6)}</p>
            </div>

            <div className="rounded-xl bg-zinc-50 p-3.5">
              <span className="flex items-center gap-1.5 text-xs text-zinc-500">
                <Layers className="h-3.5 w-3.5" />
                Prompt Tokens
              </span>
              <p className="mt-1 text-base font-bold text-zinc-900">
                {run.tokens_in.toLocaleString()}
              </p>
            </div>

            <div className="rounded-xl bg-zinc-50 p-3.5">
              <span className="flex items-center gap-1.5 text-xs text-zinc-500">
                <Sparkles className="h-3.5 w-3.5" />
                Completion Tokens
              </span>
              <p className="mt-1 text-base font-bold text-zinc-900">
                {run.tokens_out.toLocaleString()}
              </p>
            </div>

            <div className="rounded-xl bg-zinc-50 p-3.5">
              <span className="flex items-center gap-1.5 text-xs text-zinc-500">
                <Clock className="h-3.5 w-3.5" />
                Trigger Mode
              </span>
              <p className="mt-1 text-base font-bold capitalize text-zinc-900">{run.trigger}</p>
            </div>
          </div>

          {/* Executive Summary */}
          {run.output_json?.executive_summary && (
            <div className="mt-6 rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50/70 to-indigo-50/20 p-5">
              <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-indigo-900">
                <Sparkles className="h-4 w-4 text-indigo-600" />
                Executive Summary
              </div>
              <p className="mt-2 text-sm leading-relaxed text-zinc-800 font-normal">
                {run.output_json.executive_summary}
              </p>
            </div>
          )}
        </div>

        {/* Section: Needs */}
        {needs.length > 0 && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-blue-600" />
              <h3 className="text-base font-bold text-zinc-900">Extracted Needs ({needs.length})</h3>
            </div>
            <div className="grid gap-4">
              {needs.map((ins) => (
                <ReportInsightCard
                  key={ins.id}
                  insight={ins}
                  onFeedback={handleFeedback}
                  isLoadingFeedback={feedbackLoading[ins.id] || false}
                />
              ))}
            </div>
          </div>
        )}

        {/* Section: Patterns */}
        {patterns.length > 0 && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-purple-600" />
              <h3 className="text-base font-bold text-zinc-900">Recurring Patterns ({patterns.length})</h3>
            </div>
            <div className="grid gap-4">
              {patterns.map((ins) => (
                <ReportInsightCard
                  key={ins.id}
                  insight={ins}
                  onFeedback={handleFeedback}
                  isLoadingFeedback={feedbackLoading[ins.id] || false}
                />
              ))}
            </div>
          </div>
        )}

        {/* Section: Stakeholders */}
        {stakeholders.length > 0 && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-indigo-600" />
              <h3 className="text-base font-bold text-zinc-900">
                Identified Stakeholders ({stakeholders.length})
              </h3>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {stakeholders.map((ins) => (
                <ReportInsightCard
                  key={ins.id}
                  insight={ins}
                  onFeedback={handleFeedback}
                  isLoadingFeedback={feedbackLoading[ins.id] || false}
                />
              ))}
            </div>
          </div>
        )}

        {/* Section: Risks */}
        {risks.length > 0 && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-rose-600" />
              <h3 className="text-base font-bold text-zinc-900">
                Delivery & Scope Risks ({risks.length})
              </h3>
            </div>
            <div className="grid gap-4">
              {risks.map((ins) => (
                <ReportInsightCard
                  key={ins.id}
                  insight={ins}
                  onFeedback={handleFeedback}
                  isLoadingFeedback={feedbackLoading[ins.id] || false}
                />
              ))}
            </div>
          </div>
        )}

        {run.insights.length === 0 && (
          <div className="rounded-2xl border border-dashed border-zinc-200 bg-white p-12 text-center text-zinc-500">
            No individual insights were extracted in this run.
          </div>
        )}
      </div>
    </DashboardTemplate>
  );
}

function ReportInsightCard({
  insight,
  onFeedback,
  isLoadingFeedback,
}: {
  insight: Insight;
  onFeedback: (id: string, type: "thumbs_up" | "thumbs_down") => void;
  isLoadingFeedback: boolean;
}) {
  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm transition-all hover:border-zinc-300">
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
              <span className="rounded-md bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-600 capitalize">
                {insight.severity_or_priority} priority
              </span>
            )}
          </div>

          <h4 className="pt-1 text-base font-semibold text-zinc-900">{insight.title}</h4>
        </div>

        {/* Quality Feedback */}
        <div className="flex items-center gap-1 rounded-lg border border-zinc-200 p-1">
          <button
            onClick={() => onFeedback(insight.id, "thumbs_up")}
            disabled={isLoadingFeedback}
            className={`rounded-md p-1.5 transition-colors ${
              insight.feedback === "thumbs_up"
                ? "bg-emerald-100 text-emerald-700"
                : "text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
            }`}
            title="Mark insight accurate"
          >
            <ThumbsUp className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => onFeedback(insight.id, "thumbs_down")}
            disabled={isLoadingFeedback}
            className={`rounded-md p-1.5 transition-colors ${
              insight.feedback === "thumbs_down"
                ? "bg-rose-100 text-rose-700"
                : "text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
            }`}
            title="Mark insight inaccurate"
          >
            <ThumbsDown className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <p className="mt-2 text-sm leading-relaxed text-zinc-600">{insight.detail}</p>

      {/* Clickable Citations Grounding */}
      {insight.source_refs && insight.source_refs.length > 0 && (
        <div className="mt-4 border-t border-zinc-100 pt-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-400 uppercase tracking-wider">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
            Clickable Grounded Sources:
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {insight.source_refs.map((ref, idx) => (
              <a
                key={idx}
                href={ref.url || "#"}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-xs font-medium text-zinc-700 hover:border-indigo-300 hover:bg-indigo-50/50 hover:text-indigo-700 transition-colors"
              >
                <span className="capitalize text-zinc-400">[{ref.source_type}]:</span>
                <span className="font-semibold">{ref.title || ref.source_id}</span>
                <ExternalLink className="h-3 w-3 text-zinc-400" />
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
