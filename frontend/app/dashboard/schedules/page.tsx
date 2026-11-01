"use client";

import {
  AlertTriangle,
  ArrowRight,
  Calendar,
  Check,
  CheckCircle2,
  Clock,
  ExternalLink,
  Layers,
  Mail,
  MessageSquare,
  MoreVertical,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  Users,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/atoms/Button";
import { PageTransition } from "@/components/atoms/PageTransition";
import { ConfirmDeleteModal } from "@/components/molecules/ConfirmDeleteModal";
import { DeliveriesTable } from "@/components/organisms/DeliveriesTable";
import { ScheduleModal } from "@/components/organisms/ScheduleModal";
import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { clearSession, setAuthenticatedUser } from "@/lib/authSlice";
import { useAppDispatch, useAppSelector } from "@/lib/hooks";
import { workspaceStore } from "@/lib/storage";
import type {
  ClientSummary,
  Delivery,
  Schedule,
  ScheduleCreateRequest,
  Skill,
  Workspace,
} from "@/lib/types";
import { authService } from "@/services/AuthService";
import { clientService } from "@/services/ClientService";
import { scheduleService } from "@/services/ScheduleService";
import { skillService } from "@/services/SkillService";
import { workspaceService } from "@/services/WorkspaceService";

export default function SchedulesPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [activeTab, setActiveTab] = useState<"schedules" | "deliveries">("schedules");

  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [deliveriesTotal, setDeliveriesTotal] = useState<number>(0);
  const [deliveriesPage, setDeliveriesPage] = useState<number>(1);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [clients, setClients] = useState<ClientSummary[]>([]);

  const [loading, setLoading] = useState<boolean>(true);
  const [loadingDeliveries, setLoadingDeliveries] = useState<boolean>(false);
  const [runningScheduleId, setRunningScheduleId] = useState<string | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<string>("");

  // Modals state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<Schedule | null>(null);
  const [deletingSchedule, setDeletingSchedule] = useState<Schedule | null>(null);

  const loadData = useCallback(async (workspace: Workspace) => {
    workspaceStore.setWorkspaceId(workspace.id);
    setLoading(true);
    try {
      const [schedList, skillList, clientList] = await Promise.all([
        scheduleService.list(workspace.id),
        skillService.list(workspace.id),
        clientService.list(workspace.id),
      ]);
      setSchedules(schedList);
      setSkills(skillList);
      setClients(clientList);
    } catch {
      // Failed to load
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDeliveries = useCallback(async (workspaceId: string, page: number) => {
    setLoadingDeliveries(true);
    const skip = (page - 1) * 15;
    try {
      const res = await scheduleService.listDeliveries(workspaceId, skip, 15);
      setDeliveries(res.deliveries);
      setDeliveriesTotal(res.total);
    } catch {
      // Ignore
    } finally {
      setLoadingDeliveries(false);
    }
  }, []);

  useEffect(() => {
    async function init() {
      try {
        const u = await authService.me();
        dispatch(setAuthenticatedUser(u));
        const wsList = await workspaceService.list();
        setWorkspaces(wsList);

        if (wsList.length > 0) {
          const storedId = workspaceStore.getWorkspaceId();
          const target = wsList.find((w) => w.id === storedId) || wsList[0];
          setSelectedWorkspace(target);
          await loadData(target);
        } else {
          setLoading(false);
        }
      } catch {
        router.push("/login");
      }
    }
    init();
  }, [dispatch, router, loadData]);

  useEffect(() => {
    if (selectedWorkspace && activeTab === "deliveries") {
      loadDeliveries(selectedWorkspace.id, deliveriesPage);
    }
  }, [selectedWorkspace, activeTab, deliveriesPage, loadDeliveries]);

  function handleSelectWorkspace(workspace: Workspace) {
    setSelectedWorkspace(workspace);
    loadData(workspace);
  }

  async function handleLogout() {
    await authService.logout();
    dispatch(clearSession());
    router.push("/login");
  }

  async function handleSaveSchedule(payload: ScheduleCreateRequest) {
    if (!selectedWorkspace) return;
    if (editingSchedule) {
      await scheduleService.update(selectedWorkspace.id, editingSchedule.id, payload);
      setFeedbackMessage("Schedule updated successfully.");
    } else {
      await scheduleService.create(selectedWorkspace.id, payload);
      setFeedbackMessage("New report schedule created.");
    }
    await loadData(selectedWorkspace);
    setTimeout(() => setFeedbackMessage(""), 4000);
  }

  async function handleDeleteSchedule() {
    if (!selectedWorkspace || !deletingSchedule) return;
    try {
      await scheduleService.delete(selectedWorkspace.id, deletingSchedule.id);
      setDeletingSchedule(null);
      await loadData(selectedWorkspace);
      setFeedbackMessage("Schedule removed.");
      setTimeout(() => setFeedbackMessage(""), 4000);
    } catch {
      // Ignore
    }
  }

  async function handleToggleActive(schedule: Schedule) {
    if (!selectedWorkspace) return;
    const newActive = !schedule.active;
    await scheduleService.update(selectedWorkspace.id, schedule.id, { active: newActive });
    setSchedules((prev) =>
      prev.map((s) => (s.id === schedule.id ? { ...s, active: newActive } : s))
    );
  }

  async function handleRunNow(schedule: Schedule) {
    if (!selectedWorkspace) return;
    setRunningScheduleId(schedule.id);
    try {
      const res = await scheduleService.runNow(selectedWorkspace.id, schedule.id);
      if (res) {
        setFeedbackMessage(`Report executed successfully!`);
      } else {
        setFeedbackMessage("Report was skipped because no changes were detected (Delta check).");
      }
      await loadData(selectedWorkspace);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Run execution failed.";
      setFeedbackMessage(`Error: ${msg}`);
    } finally {
      setRunningScheduleId(null);
      setTimeout(() => setFeedbackMessage(""), 5000);
    }
  }

  function getSkillName(id: string) {
    return skills.find((s) => s.id === id)?.name || "Client Needs Analyzer";
  }

  function getClientName(id: string | null) {
    if (!id) return "All Workspace Clients";
    return clients.find((c) => c.id === id)?.name || "Specific Client";
  }

  return (
    <PageTransition>
      <DashboardTemplate
        sidebar={
          <Sidebar
            user={user}
            workspaces={workspaces}
            selectedId={selectedWorkspace?.id || null}
            onSelectWorkspace={handleSelectWorkspace}
            onLogout={handleLogout}
          />
        }
      >
        <div className="mx-auto max-w-7xl space-y-6">
          {/* Header */}
          <div className="flex flex-col justify-between gap-4 border-b border-[#E2E8F0] pb-6 dark:border-[#253745] sm:flex-row sm:items-center">
            <div>
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center gap-1 rounded-md bg-[#253745] px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider text-white dark:bg-[#162736] dark:text-[#88E5BE]">
                  <Send className="h-3 w-3" /> Delivery Engine
                </span>
              </div>
              <h1 className="mt-2 text-2xl font-bold tracking-tight text-[#06141B] dark:text-[#F1F5F9] sm:text-3xl">
                Schedules & Delivery
              </h1>
              <p className="mt-1 text-sm text-[#4A5C6A] dark:text-[#9BA8AB]">
                Automate scheduled AI syntheses and deliver Block Kit digests to Slack or formatted email updates.
              </p>
            </div>

            <Button
              onClick={() => {
                setEditingSchedule(null);
                setIsModalOpen(true);
              }}
              className="flex items-center gap-2 bg-[#253745] text-white hover:bg-[#162736] dark:bg-[#162736] dark:text-[#F1F5F9] dark:hover:bg-[#253745]"
            >
              <Plus className="h-4 w-4" />
              New Schedule
            </Button>
          </div>

          {/* Feedback banner */}
          {feedbackMessage && (
            <div className="flex items-center justify-between rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/40 dark:text-emerald-300 animate-in fade-in">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                <span>{feedbackMessage}</span>
              </div>
              <button
                onClick={() => setFeedbackMessage("")}
                className="text-emerald-600 hover:text-emerald-800 dark:text-emerald-400"
              >
                ✕
              </button>
            </div>
          )}

          {/* Tabs */}
          <div className="flex border-b border-[#E2E8F0] dark:border-[#253745]">
            <button
              onClick={() => setActiveTab("schedules")}
              className={`flex items-center gap-2 border-b-2 px-5 py-3 text-sm font-semibold transition-all ${
                activeTab === "schedules"
                  ? "border-[#253745] text-[#06141B] dark:border-[#88E5BE] dark:text-[#F1F5F9]"
                  : "border-transparent text-[#4A5C6A] hover:text-[#06141B] dark:text-[#9BA8AB] dark:hover:text-[#F1F5F9]"
              }`}
            >
              <Clock className="h-4 w-4" />
              Active Schedules ({schedules.length})
            </button>
            <button
              onClick={() => setActiveTab("deliveries")}
              className={`flex items-center gap-2 border-b-2 px-5 py-3 text-sm font-semibold transition-all ${
                activeTab === "deliveries"
                  ? "border-[#253745] text-[#06141B] dark:border-[#88E5BE] dark:text-[#F1F5F9]"
                  : "border-transparent text-[#4A5C6A] hover:text-[#06141B] dark:text-[#9BA8AB] dark:hover:text-[#F1F5F9]"
              }`}
            >
              <Send className="h-4 w-4" />
              Delivery History
            </button>
          </div>

          {/* Tab 1: Schedules Grid */}
          {activeTab === "schedules" && (
            <div>
              {loading ? (
                <div className="flex flex-col items-center justify-center p-16 text-[#4A5C6A] dark:text-[#9BA8AB]">
                  <RefreshCw className="mb-2 h-6 w-6 animate-spin" />
                  <p className="text-sm">Loading schedules...</p>
                </div>
              ) : schedules.length === 0 ? (
                <div className="rounded-2xl border border-[#E2E8F0] bg-white p-12 text-center shadow-sm dark:border-[#253745] dark:bg-[#11212D]">
                  <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#F1F5F9] dark:bg-[#162736]">
                    <Clock className="h-7 w-7 text-[#4A5C6A] dark:text-[#9BA8AB]" />
                  </div>
                  <h3 className="text-lg font-bold text-[#06141B] dark:text-[#F1F5F9]">
                    No Schedules Configured Yet
                  </h3>
                  <p className="mx-auto mt-1 max-w-md text-sm text-[#4A5C6A] dark:text-[#9BA8AB]">
                    Set up recurring schedules to automatically analyze client boards and deliver insights straight into your team’s Slack channels or email inboxes.
                  </p>
                  <Button
                    onClick={() => {
                      setEditingSchedule(null);
                      setIsModalOpen(true);
                    }}
                    className="mt-6 bg-[#253745] text-white hover:bg-[#162736] dark:bg-[#162736] dark:text-[#F1F5F9] dark:hover:bg-[#253745]"
                  >
                    <Plus className="mr-2 h-4 w-4" />
                    Create Your First Schedule
                  </Button>
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">
                  {schedules.map((schedule) => {
                    const isRunning = runningScheduleId === schedule.id;
                    const nextRunFormatted = schedule.next_run_at
                      ? new Date(schedule.next_run_at).toLocaleString("en-US", {
                          weekday: "short",
                          month: "short",
                          day: "numeric",
                          hour: "numeric",
                          minute: "2-digit",
                          timeZone: schedule.timezone || "UTC",
                        })
                      : "Paused";

                    return (
                      <div
                        key={schedule.id}
                        className={`group relative flex flex-col justify-between rounded-2xl border bg-white p-5 shadow-sm transition-all dark:bg-[#11212D] ${
                          schedule.active
                            ? "border-[#E2E8F0] hover:border-[#CCD0CF] dark:border-[#253745] dark:hover:border-[#4A5C6A]"
                            : "border-dashed border-slate-200 opacity-75 dark:border-slate-800"
                        }`}
                      >
                        {/* Top badges & Title */}
                        <div>
                          <div className="mb-3 flex items-center justify-between">
                            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#E2E8F0] bg-[#F8FAFC] px-2.5 py-0.5 text-[11px] font-semibold text-[#4A5C6A] dark:border-[#253745] dark:bg-[#162736] dark:text-[#9BA8AB]">
                              <Sparkles className="h-3 w-3 text-[#4F46E5] dark:text-[#88E5BE]" />
                              {getSkillName(schedule.skill_id)}
                            </span>

                            <div className="flex items-center gap-1.5">
                              {schedule.is_delta_only && (
                                <span
                                  title="Delta active: Skips running if no new activity is detected"
                                  className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400"
                                >
                                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
                                  Delta
                                </span>
                              )}
                              <button
                                onClick={() => handleToggleActive(schedule)}
                                className={`rounded-lg p-1 text-xs transition-colors ${
                                  schedule.active
                                    ? "text-emerald-600 hover:bg-emerald-50 dark:text-emerald-400 dark:hover:bg-emerald-950/30"
                                    : "text-slate-400 hover:bg-slate-100 dark:text-slate-500"
                                }`}
                                title={schedule.active ? "Pause Schedule" : "Resume Schedule"}
                              >
                                {schedule.active ? (
                                  <Pause className="h-4 w-4" />
                                ) : (
                                  <Play className="h-4 w-4" />
                                )}
                              </button>
                            </div>
                          </div>

                          <h3 className="text-base font-bold text-[#06141B] dark:text-[#F1F5F9]">
                            {schedule.name}
                          </h3>

                          {/* Client Scope */}
                          <div className="mt-2 flex items-center gap-1.5 text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">
                            <Users className="h-3.5 w-3.5" />
                            <span>{getClientName(schedule.client_id)}</span>
                          </div>

                          {/* Channel & Recipient */}
                          <div className="mt-2 flex items-center gap-1.5 text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">
                            {schedule.channel === "slack" ? (
                              <span className="inline-flex items-center gap-1 font-semibold text-violet-700 dark:text-violet-400">
                                <MessageSquare className="h-3.5 w-3.5" />
                                {schedule.slack_channel_name || "Slack Channel"}
                              </span>
                            ) : schedule.channel === "email" ? (
                              <span className="inline-flex items-center gap-1 font-semibold text-blue-700 dark:text-blue-400">
                                <Mail className="h-3.5 w-3.5" />
                                {schedule.recipients?.length || 1} Email Recipient(s)
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 font-semibold text-indigo-700 dark:text-indigo-400">
                                <Zap className="h-3.5 w-3.5" />
                                Slack & Email
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Timing footer & Actions */}
                        <div className="mt-5 border-t border-[#E2E8F0] pt-4 dark:border-[#253745]">
                          <div className="mb-3 flex items-center justify-between text-xs">
                            <span className="text-[#4A5C6A] dark:text-[#9BA8AB]">Next Run:</span>
                            <span className="font-semibold text-[#06141B] dark:text-[#F1F5F9]">
                              {nextRunFormatted}
                            </span>
                          </div>

                          <div className="flex items-center justify-between gap-2">
                            <Button
                              variant="secondary"
                              disabled={isRunning}
                              onClick={() => handleRunNow(schedule)}
                              className="h-8 flex-1 gap-1.5 text-xs font-semibold text-[#253745] hover:bg-[#F1F5F9] dark:text-[#F1F5F9] dark:hover:bg-[#162736]"
                            >
                              {isRunning ? (
                                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Play className="h-3.5 w-3.5" />
                              )}
                              Run Now
                            </Button>

                            <button
                              onClick={() => {
                                setEditingSchedule(schedule);
                                setIsModalOpen(true);
                              }}
                              className="rounded-lg border border-[#E2E8F0] p-1.5 text-[#4A5C6A] hover:bg-[#F1F5F9] hover:text-[#06141B] dark:border-[#253745] dark:text-[#9BA8AB] dark:hover:bg-[#162736] dark:hover:text-white"
                              title="Edit Schedule"
                            >
                              Edit
                            </button>

                            <button
                              onClick={() => setDeletingSchedule(schedule)}
                              className="rounded-lg border border-red-200 p-1.5 text-red-600 hover:bg-red-50 dark:border-red-900/40 dark:text-red-400 dark:hover:bg-red-950/30"
                              title="Delete Schedule"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* Tab 2: Delivery Audit History */}
          {activeTab === "deliveries" && (
            <DeliveriesTable
              deliveries={deliveries}
              total={deliveriesTotal}
              currentPage={deliveriesPage}
              pageSize={15}
              onPageChange={(page) => setDeliveriesPage(page)}
              loading={loadingDeliveries}
            />
          )}

          {/* Schedule Create / Edit Modal */}
          {selectedWorkspace && (
            <ScheduleModal
              isOpen={isModalOpen}
              onClose={() => {
                setIsModalOpen(false);
                setEditingSchedule(null);
              }}
              onSave={handleSaveSchedule}
              workspaceId={selectedWorkspace.id}
              skills={skills}
              clients={clients}
              defaultUserEmail={user?.email}
              initialSchedule={editingSchedule}
            />
          )}

          {/* Confirm Delete Modal */}
          <ConfirmDeleteModal
            isOpen={deletingSchedule !== null}
            title="Delete Report Schedule"
            description={`Are you sure you want to delete the schedule "${deletingSchedule?.name}"? Scheduled digests will no longer be generated or delivered.`}
            onClose={() => setDeletingSchedule(null)}
            onConfirm={handleDeleteSchedule}
          />
        </div>
      </DashboardTemplate>
    </PageTransition>
  );
}
