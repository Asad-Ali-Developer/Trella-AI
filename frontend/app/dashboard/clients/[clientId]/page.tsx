"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Calendar,
  CheckCircle2,
  ChevronRight,
  Clock,
  ExternalLink,
  FileText,
  GitCommit,
  Layers,
  LoaderCircle,
  MessageSquare,
  Play,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  TrendingUp,
  UserCheck,
  Users,
} from "lucide-react";

import { Button } from "@/components/atoms/Button";
import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { workspaceStore } from "@/lib/storage";
import type { ClientProfile, Insight, Run, User, Workspace } from "@/lib/types";
import { authService } from "@/services/AuthService";
import { clientService } from "@/services/ClientService";
import { runService } from "@/services/RunService";
import { skillService } from "@/services/SkillService";
import { workspaceService } from "@/services/WorkspaceService";

export default function ClientProfilePage() {
  const router = useRouter();
  const params = useParams<{ clientId: string }>();
  const clientId = params?.clientId;

  const [user, setUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);

  const [profile, setProfile] = useState<ClientProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Tab State
  const [activeTab, setActiveTab] = useState<
    "needs" | "patterns" | "stakeholders" | "risks" | "timeline"
  >("needs");

  // Run Skill Modal / Trigger
  const [runningSkill, setRunningSkill] = useState(false);
  const [skillsList, setSkillsList] = useState<{ id: string; name: string }[]>([]);

  // Thumbs Feedback State
  const [feedbackLoading, setFeedbackLoading] = useState<Record<string, boolean>>({});

  const loadData = useCallback(async () => {
    if (!clientId) return;
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

      const [clientData, skills] = await Promise.all([
        clientService.get(current.id, clientId),
        skillService.list(current.id),
      ]);
      setProfile(clientData);
      setSkillsList(skills.map((s) => ({ id: s.id, name: s.name })));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to load client profile.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  async function handleSelectWorkspace(workspace: Workspace) {
    workspaceStore.setWorkspaceId(workspace.id);
    setSelectedWorkspace(workspace);
    router.push("/dashboard/clients");
  }

  async function handleTriggerRun() {
    if (!selectedWorkspace || !profile || skillsList.length === 0) return;
    setRunningSkill(true);
    setError("");
    setNotice("");

    try {
      const defaultSkillId = skillsList[0].id;
      const createdRun = await runService.create(
        selectedWorkspace.id,
        {
          skill_id: defaultSkillId,
          client_id: clientId,
          trigger: "manual",
        },
        false, // Synchronous for immediate feedback
      );

      if (createdRun.status === "failed") {
        setError(createdRun.error || "Analysis run encountered an error.");
      } else {
        setNotice(`Successfully completed fresh analysis for ${profile.client.name}!`);
      }

      // Refresh profile data
      const updated = await clientService.get(selectedWorkspace.id, clientId);
      setProfile(updated);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to run analysis.";
      setError(message);
    } finally {
      setRunningSkill(false);
    }
  }

  async function handleFeedback(insightId: string, type: "thumbs_up" | "thumbs_down") {
    if (!selectedWorkspace) return;
    setFeedbackLoading((prev) => ({ ...prev, [insightId]: true }));
    try {
      const updated = await runService.submitFeedback(
        selectedWorkspace.id,
        insightId,
        type,
      );

      // Update in local state
      setProfile((prev) => {
        if (!prev) return null;
        const updateList = (list: Insight[]) =>
          list.map((item) => (item.id === insightId ? { ...item, feedback: updated.feedback } : item));

        return {
          ...prev,
          needs: updateList(prev.needs),
          patterns: updateList(prev.patterns),
          stakeholders: updateList(prev.stakeholders),
          risks: updateList(prev.risks),
        };
      });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to submit feedback.";
      setError(message);
    } finally {
      setFeedbackLoading((prev) => ({ ...prev, [insightId]: false }));
    }
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
            Loading client profile…
          </div>
        </div>
      </DashboardTemplate>
    );
  }

  if (!profile) {
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
          <p className="text-zinc-500">Client profile not found.</p>
          <Link
            href="/dashboard/clients"
            className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-indigo-600 hover:underline"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Client Directory
          </Link>
        </div>
      </DashboardTemplate>
    );
  }

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
        {/* Navigation Breadcrumb */}
        <div className="flex items-center gap-2 text-xs font-medium text-zinc-400">
          <Link href="/dashboard" className="hover:text-zinc-700">
            Dashboard
          </Link>
          <ChevronRight className="h-3 w-3" />
          <Link href="/dashboard/clients" className="hover:text-zinc-700">
            Clients
          </Link>
          <ChevronRight className="h-3 w-3" />
          <span className="text-zinc-800">{profile.client.name}</span>
        </div>

        {/* Hero Header */}
        <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between border-b border-zinc-200 pb-6">
          <div className="flex items-center gap-4">
            <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-600 to-indigo-800 text-2xl font-bold text-white shadow-md">
              {profile.client.name.trim().charAt(0).toUpperCase()}
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h1 className="text-2xl font-bold tracking-tight text-zinc-900 md:text-3xl">
                  {profile.client.name}
                </h1>
                <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-semibold text-indigo-700 border border-indigo-200">
                  Client Dossier
                </span>
              </div>
              <p className="mt-1 text-xs text-zinc-400">
                Created on {new Date(profile.client.created_at).toLocaleDateString()} •{" "}
                {profile.client.last_run_at
                  ? `Last analyzed on ${new Date(profile.client.last_run_at).toLocaleString()}`
                  : "No prior analyses"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Button
              onClick={handleTriggerRun}
              disabled={runningSkill}
              className="inline-flex h-11 items-center gap-2 rounded-xl bg-indigo-600 px-6 font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50"
            >
              {runningSkill ? (
                <>
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  Running AI Analysis…
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 fill-white" />
                  Analyze Client Now
                </>
              )}
            </Button>
          </div>
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

        {/* Metrics Overview Strip */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
          <div className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
              <Layers className="h-3.5 w-3.5 text-zinc-400" />
              Mapped Cards
            </div>
            <p className="mt-1.5 text-xl font-bold text-zinc-900">{profile.total_cards}</p>
          </div>

          <div className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
              <Sparkles className="h-3.5 w-3.5 text-indigo-500" />
              Verified Needs
            </div>
            <p className="mt-1.5 text-xl font-bold text-indigo-600">{profile.needs.length}</p>
          </div>

          <div className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
              <TrendingUp className="h-3.5 w-3.5 text-purple-500" />
              Patterns
            </div>
            <p className="mt-1.5 text-xl font-bold text-purple-600">{profile.patterns.length}</p>
          </div>

          <div className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
              <Users className="h-3.5 w-3.5 text-blue-500" />
              Stakeholders
            </div>
            <p className="mt-1.5 text-xl font-bold text-blue-600">{profile.stakeholders.length}</p>
          </div>

          <div className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
              <ShieldAlert className="h-3.5 w-3.5 text-rose-500" />
              Open Risks
            </div>
            <p className="mt-1.5 text-xl font-bold text-rose-600">{profile.risks.length}</p>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="border-b border-zinc-200">
          <nav className="flex space-x-6">
            <button
              onClick={() => setActiveTab("needs")}
              className={`border-b-2 pb-3 text-sm font-semibold transition-colors ${
                activeTab === "needs"
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-zinc-500 hover:border-zinc-300 hover:text-zinc-700"
              }`}
            >
              Needs & Requirements ({profile.needs.length})
            </button>
            <button
              onClick={() => setActiveTab("patterns")}
              className={`border-b-2 pb-3 text-sm font-semibold transition-colors ${
                activeTab === "patterns"
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-zinc-500 hover:border-zinc-300 hover:text-zinc-700"
              }`}
            >
              Recurring Patterns ({profile.patterns.length})
            </button>
            <button
              onClick={() => setActiveTab("stakeholders")}
              className={`border-b-2 pb-3 text-sm font-semibold transition-colors ${
                activeTab === "stakeholders"
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-zinc-500 hover:border-zinc-300 hover:text-zinc-700"
              }`}
            >
              Stakeholders ({profile.stakeholders.length})
            </button>
            <button
              onClick={() => setActiveTab("risks")}
              className={`border-b-2 pb-3 text-sm font-semibold transition-colors ${
                activeTab === "risks"
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-zinc-500 hover:border-zinc-300 hover:text-zinc-700"
              }`}
            >
              Operational Risks ({profile.risks.length})
            </button>
            <button
              onClick={() => setActiveTab("timeline")}
              className={`border-b-2 pb-3 text-sm font-semibold transition-colors ${
                activeTab === "timeline"
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-zinc-500 hover:border-zinc-300 hover:text-zinc-700"
              }`}
            >
              Activity Timeline ({profile.timeline.length})
            </button>
          </nav>
        </div>

        {/* Tab Content 1: Needs */}
        {activeTab === "needs" && (
          <div className="space-y-4">
            {profile.needs.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-zinc-200 bg-white p-12 text-center">
                <Sparkles className="mx-auto h-8 w-8 text-zinc-300" />
                <h4 className="mt-3 text-sm font-semibold text-zinc-700">No Needs Extracted Yet</h4>
                <p className="mt-1 text-xs text-zinc-400">
                  Click &apos;Analyze Client Now&apos; above to run the Client Needs Analyzer skill on this client.
                </p>
              </div>
            ) : (
              <div className="grid gap-4">
                {profile.needs.map((item) => (
                  <InsightCard
                    key={item.id}
                    insight={item}
                    onFeedback={handleFeedback}
                    isLoadingFeedback={feedbackLoading[item.id] || false}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab Content 2: Patterns */}
        {activeTab === "patterns" && (
          <div className="space-y-4">
            {profile.patterns.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-zinc-200 bg-white p-12 text-center">
                <TrendingUp className="mx-auto h-8 w-8 text-zinc-300" />
                <h4 className="mt-3 text-sm font-semibold text-zinc-700">No Recurring Patterns Found</h4>
                <p className="mt-1 text-xs text-zinc-400">
                  Patterns will be extracted as multiple cards and sprints are analyzed for this client.
                </p>
              </div>
            ) : (
              <div className="grid gap-4">
                {profile.patterns.map((item) => (
                  <InsightCard
                    key={item.id}
                    insight={item}
                    onFeedback={handleFeedback}
                    isLoadingFeedback={feedbackLoading[item.id] || false}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab Content 3: Stakeholders */}
        {activeTab === "stakeholders" && (
          <div className="space-y-4">
            {profile.stakeholders.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-zinc-200 bg-white p-12 text-center">
                <Users className="mx-auto h-8 w-8 text-zinc-300" />
                <h4 className="mt-3 text-sm font-semibold text-zinc-700">No Stakeholders Detected</h4>
                <p className="mt-1 text-xs text-zinc-400">
                  The skill scans card assignments, comment authors, and git commits to identify key stakeholders.
                </p>
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
                {profile.stakeholders.map((item) => (
                  <InsightCard
                    key={item.id}
                    insight={item}
                    onFeedback={handleFeedback}
                    isLoadingFeedback={feedbackLoading[item.id] || false}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab Content 4: Risks */}
        {activeTab === "risks" && (
          <div className="space-y-4">
            {profile.risks.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-zinc-200 bg-white p-12 text-center">
                <CheckCircle2 className="mx-auto h-8 w-8 text-emerald-400" />
                <h4 className="mt-3 text-sm font-semibold text-zinc-700">Zero Open Delivery Risks</h4>
                <p className="mt-1 text-xs text-zinc-400">
                  No critical bottlenecks, delays, or scope creep flags detected for this client.
                </p>
              </div>
            ) : (
              <div className="grid gap-4">
                {profile.risks.map((item) => (
                  <InsightCard
                    key={item.id}
                    insight={item}
                    onFeedback={handleFeedback}
                    isLoadingFeedback={feedbackLoading[item.id] || false}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab Content 5: Activity Timeline */}
        {activeTab === "timeline" && (
          <div className="space-y-4">
            {profile.timeline.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-zinc-200 bg-white p-12 text-center">
                <Clock className="mx-auto h-8 w-8 text-zinc-300" />
                <h4 className="mt-3 text-sm font-semibold text-zinc-700">No Timeline Activity Recorded</h4>
                <p className="mt-1 text-xs text-zinc-400">
                  As you sync cards, commits, and execute skill runs, they will populate here in real-time.
                </p>
              </div>
            ) : (
              <div className="relative border-l border-zinc-200 ml-4 space-y-6 pb-4">
                {profile.timeline.map((event) => {
                  return (
                    <div key={event.id} className="relative pl-6">
                      {/* Timeline Dot Icon */}
                      <div
                        className={`absolute -left-3.5 top-0.5 flex h-7 w-7 items-center justify-center rounded-full border bg-white ${
                          event.event_type === "skill_run"
                            ? "border-indigo-400 text-indigo-600"
                            : event.event_type === "risk_identified"
                            ? "border-rose-400 text-rose-600"
                            : event.event_type === "commit"
                            ? "border-blue-400 text-blue-600"
                            : "border-zinc-300 text-zinc-500"
                        }`}
                      >
                        {event.event_type === "skill_run" && <Sparkles className="h-3.5 w-3.5" />}
                        {event.event_type === "risk_identified" && <AlertTriangle className="h-3.5 w-3.5" />}
                        {event.event_type === "commit" && <GitCommit className="h-3.5 w-3.5" />}
                        {event.event_type === "card_activity" && <Layers className="h-3.5 w-3.5" />}
                      </div>

                      {/* Timeline Item Content */}
                      <div className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-bold uppercase tracking-wider text-zinc-400">
                              {event.source}
                            </span>
                            <span className="text-zinc-300">•</span>
                            <h4 className="text-sm font-semibold text-zinc-900">{event.title}</h4>
                          </div>

                          <div className="flex items-center gap-2 text-xs text-zinc-400">
                            <Calendar className="h-3 w-3" />
                            {new Date(event.timestamp).toLocaleString()}
                          </div>
                        </div>

                        {event.detail && (
                          <p className="mt-1.5 text-xs text-zinc-600 leading-relaxed">
                            {event.detail}
                          </p>
                        )}

                        {event.source_url && (
                          <div className="mt-2.5">
                            <a
                              href={event.source_url}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:underline"
                            >
                              View in {event.source}
                              <ExternalLink className="h-3 w-3" />
                            </a>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Recent Analysis Runs */}
        {profile.recent_runs.length > 0 && (
          <div className="space-y-4 border-t border-zinc-200 pt-8">
            <h3 className="text-base font-bold text-zinc-900">Recent Analysis Runs</h3>
            <div className="divide-y divide-zinc-100 rounded-2xl border border-zinc-200 bg-white shadow-sm overflow-hidden">
              {profile.recent_runs.map((r) => (
                <div
                  key={r.id}
                  className="flex flex-wrap items-center justify-between gap-4 p-4 hover:bg-zinc-50 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div
                      className={`flex h-8 w-8 items-center justify-center rounded-lg text-xs font-bold ${
                        r.status === "completed"
                          ? "bg-emerald-100 text-emerald-700"
                          : r.status === "failed"
                          ? "bg-rose-100 text-rose-700"
                          : "bg-amber-100 text-amber-700"
                      }`}
                    >
                      {r.status === "completed" ? "✓" : "!"}
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-zinc-900">
                        {r.skill_name || "Client Needs Analyzer"}
                      </p>
                      <p className="text-xs text-zinc-400">
                        Executed on {new Date(r.created_at).toLocaleString()}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-6 text-xs text-zinc-500">
                    <div>
                      Tokens: <strong>{(r.tokens_in + r.tokens_out).toLocaleString()}</strong>
                    </div>
                    <div>
                      Cost: <strong>${r.cost_usd.toFixed(6)}</strong>
                    </div>
                    <Link
                      href={`/dashboard/reports/${r.id}`}
                      className="inline-flex items-center gap-1 font-semibold text-indigo-600 hover:underline"
                    >
                      View Report
                      <ExternalLink className="h-3 w-3" />
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </DashboardTemplate>
  );
}

function InsightCard({
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
              <span className="rounded-md bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-600">
                {insight.severity_or_priority} priority
              </span>
            )}
          </div>

          <h4 className="pt-1 text-base font-semibold text-zinc-900">{insight.title}</h4>
        </div>

        {/* Thumbs Up / Down Quality Evaluation */}
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
            Verified Citations:
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
                <span className="capitalize text-zinc-500">[{ref.source_type}]:</span>
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
