"use client";

import {
  AlertTriangle,
  Calendar,
  Check,
  Clock,
  Globe,
  Mail,
  MessageSquare,
  Sparkles,
  Users,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/atoms/Button";
import type { ClientSummary, Schedule, ScheduleCreateRequest, Skill, SlackChannel } from "@/lib/types";
import { slackService } from "@/services/SlackService";

interface ScheduleModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (payload: ScheduleCreateRequest) => Promise<void>;
  workspaceId: string;
  skills: Skill[];
  clients: ClientSummary[];
  defaultUserEmail?: string;
  initialSchedule?: Schedule | null;
}

const PRESET_CRONS = [
  { label: "Weekly (Monday at 9:00 AM)", cron: "0 9 * * 1" },
  { label: "Daily (Every day at 9:00 AM)", cron: "0 9 * * *" },
  { label: "Bi-weekly (1st & 15th at 9:00 AM)", cron: "0 9 1,15 * *" },
  { label: "Custom Cron Expression", cron: "custom" },
];

const TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Asia/Dubai",
  "Asia/Karachi",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

export function ScheduleModal({
  isOpen,
  onClose,
  onSave,
  workspaceId,
  skills,
  clients,
  defaultUserEmail = "",
  initialSchedule = null,
}: ScheduleModalProps) {
  const [name, setName] = useState(initialSchedule?.name || "Weekly Client Insights Digest");
  const [skillId, setSkillId] = useState(initialSchedule?.skill_id || (skills[0]?.id || ""));
  const [clientId, setClientId] = useState<string | null>(initialSchedule?.client_id || null);
  const [preset, setPreset] = useState("0 9 * * 1");
  const [customCron, setCustomCron] = useState(initialSchedule?.cron || "0 9 * * 1");
  const [timezone, setTimezone] = useState(initialSchedule?.timezone || "UTC");
  const [channel, setChannel] = useState<"slack" | "email" | "both">(initialSchedule?.channel || "email");
  const [recipientsInput, setRecipientsInput] = useState(
    initialSchedule?.recipients?.join(", ") || defaultUserEmail
  );
  const [slackChannels, setSlackChannels] = useState<SlackChannel[]>([]);
  const [selectedSlackChannel, setSelectedSlackChannel] = useState<string>(
    initialSchedule?.slack_channel_id || ""
  );
  const [slackConnected, setSlackConnected] = useState<boolean>(false);
  const [loadingSlack, setLoadingSlack] = useState<boolean>(false);
  const [isDeltaOnly, setIsDeltaOnly] = useState<boolean>(
    initialSchedule ? initialSchedule.is_delta_only : true
  );
  const [active, setActive] = useState<boolean>(initialSchedule ? initialSchedule.active : true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Auto-detect browser timezone
  useEffect(() => {
    if (!initialSchedule) {
      try {
        const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (detected) setTimezone(detected);
      } catch {
        setTimezone("UTC");
      }
    }
  }, [initialSchedule]);

  // Load Slack status and channels if slack is selected
  useEffect(() => {
    if (channel === "slack" || channel === "both") {
      setLoadingSlack(true);
      slackService
        .getStatus(workspaceId)
        .then((res) => {
          setSlackConnected(res.connected);
          if (res.connected) {
            return slackService.getChannels(workspaceId).then((chs) => {
              setSlackChannels(chs);
              if (chs.length > 0 && !selectedSlackChannel) {
                setSelectedSlackChannel(chs[0].id);
              }
            });
          }
        })
        .catch(() => setSlackConnected(false))
        .finally(() => setLoadingSlack(false));
    }
  }, [channel, workspaceId, selectedSlackChannel]);

  if (!isOpen) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (!name.trim()) {
      setError("Please provide a name for this schedule.");
      return;
    }

    if (!skillId) {
      setError("Please select an AI skill to execute.");
      return;
    }

    const effectiveCron = preset === "custom" ? customCron.trim() : preset;
    if (!effectiveCron) {
      setError("Please provide a valid cron expression.");
      return;
    }

    // Process email recipients
    const emails = recipientsInput
      .split(/[,;\s]+/)
      .map((e) => e.trim())
      .filter((e) => e.length > 0 && e.includes("@"));

    if ((channel === "email" || channel === "both") && emails.length === 0) {
      setError("Please provide at least one valid recipient email address.");
      return;
    }

    // Process Slack channel
    if ((channel === "slack" || channel === "both") && !selectedSlackChannel) {
      setError("Please select a target Slack channel for digest delivery.");
      return;
    }

    const channelObj = slackChannels.find((c) => c.id === selectedSlackChannel);
    const slackChannelName = channelObj ? `#${channelObj.name}` : null;

    setSubmitting(true);
    try {
      await onSave({
        name: name.trim(),
        skill_id: skillId,
        client_id: clientId,
        cron: effectiveCron,
        timezone,
        channel,
        recipients: emails,
        slack_channel_id: selectedSlackChannel || null,
        slack_channel_name: slackChannelName,
        is_delta_only: isDeltaOnly,
        active,
      });
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save schedule.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-in fade-in">
      <div className="relative max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-[#E2E8F0] bg-white p-6 shadow-2xl transition-colors dark:border-[#253745] dark:bg-[#11212D] sm:p-8">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between border-b border-[#E2E8F0] pb-4 dark:border-[#253745]">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#253745] text-white dark:bg-[#162736]">
              <Clock className="h-5 w-5 text-[#88E5BE]" />
            </div>
            <div>
              <h2 className="text-xl font-bold tracking-tight text-[#06141B] dark:text-[#F1F5F9]">
                {initialSchedule ? "Edit Report Schedule" : "Schedule Automated Report"}
              </h2>
              <p className="text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">
                Deliver recurring AI client insights to your team via Slack or Email.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-[#4A5C6A] transition-colors hover:bg-[#F1F5F9] hover:text-[#06141B] dark:text-[#9BA8AB] dark:hover:bg-[#162736] dark:hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {error && (
          <div className="mb-5 flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 p-3.5 text-sm text-red-700 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-300">
            <AlertTriangle className="h-5 w-5 shrink-0 text-red-500" />
            <p>{error}</p>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Schedule Name */}
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[#4A5C6A] dark:text-[#9BA8AB]">
              Schedule Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Weekly Client Needs & Risk Digest"
              className="w-full rounded-xl border border-[#CCD0CF] bg-white px-3.5 py-2.5 text-sm font-medium text-[#06141B] outline-none transition focus:border-[#253745] focus:ring-1 focus:ring-[#253745] dark:border-[#253745] dark:bg-[#06141B] dark:text-[#F1F5F9]"
              required
            />
          </div>

          {/* Skill & Client Selectors */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[#4A5C6A] dark:text-[#9BA8AB]">
                AI Skill
              </label>
              <select
                value={skillId}
                onChange={(e) => setSkillId(e.target.value)}
                className="w-full rounded-xl border border-[#CCD0CF] bg-white px-3.5 py-2.5 text-sm font-medium text-[#06141B] outline-none transition focus:border-[#253745] focus:ring-1 focus:ring-[#253745] dark:border-[#253745] dark:bg-[#06141B] dark:text-[#F1F5F9]"
              >
                {skills.map((skill) => (
                  <option key={skill.id} value={skill.id}>
                    {skill.name} (v{skill.version})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[#4A5C6A] dark:text-[#9BA8AB]">
                Client Scope
              </label>
              <select
                value={clientId || ""}
                onChange={(e) => setClientId(e.target.value ? e.target.value : null)}
                className="w-full rounded-xl border border-[#CCD0CF] bg-white px-3.5 py-2.5 text-sm font-medium text-[#06141B] outline-none transition focus:border-[#253745] focus:ring-1 focus:ring-[#253745] dark:border-[#253745] dark:bg-[#06141B] dark:text-[#F1F5F9]"
              >
                <option value="">All Workspace Clients</option>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Recurrence & Timezone */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[#4A5C6A] dark:text-[#9BA8AB]">
                Frequency / Recurrence
              </label>
              <select
                value={preset}
                onChange={(e) => {
                  setPreset(e.target.value);
                  if (e.target.value !== "custom") {
                    setCustomCron(e.target.value);
                  }
                }}
                className="w-full rounded-xl border border-[#CCD0CF] bg-white px-3.5 py-2.5 text-sm font-medium text-[#06141B] outline-none transition focus:border-[#253745] focus:ring-1 focus:ring-[#253745] dark:border-[#253745] dark:bg-[#06141B] dark:text-[#F1F5F9]"
              >
                {PRESET_CRONS.map((p) => (
                  <option key={p.cron} value={p.cron}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[#4A5C6A] dark:text-[#9BA8AB]">
                Timezone
              </label>
              <select
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                className="w-full rounded-xl border border-[#CCD0CF] bg-white px-3.5 py-2.5 text-sm font-medium text-[#06141B] outline-none transition focus:border-[#253745] focus:ring-1 focus:ring-[#253745] dark:border-[#253745] dark:bg-[#06141B] dark:text-[#F1F5F9]"
              >
                {TIMEZONES.includes(timezone) ? null : <option value={timezone}>{timezone}</option>}
                {TIMEZONES.map((tz) => (
                  <option key={tz} value={tz}>
                    {tz}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {preset === "custom" && (
            <div>
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[#4A5C6A] dark:text-[#9BA8AB]">
                Custom Cron Expression (Minute Hour Day-of-Month Month Day-of-Week)
              </label>
              <input
                type="text"
                value={customCron}
                onChange={(e) => setCustomCron(e.target.value)}
                placeholder="e.g. 0 9 * * 1 (Every Monday at 9:00 AM)"
                className="font-mono w-full rounded-xl border border-[#CCD0CF] bg-white px-3.5 py-2.5 text-sm text-[#06141B] outline-none transition focus:border-[#253745] focus:ring-1 focus:ring-[#253745] dark:border-[#253745] dark:bg-[#06141B] dark:text-[#F1F5F9]"
                required
              />
            </div>
          )}

          {/* Delivery Channels */}
          <div>
            <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[#4A5C6A] dark:text-[#9BA8AB]">
              Delivery Channel
            </label>
            <div className="grid grid-cols-3 gap-3">
              {[
                { id: "email", label: "Email Digest", icon: Mail },
                { id: "slack", label: "Slack Channel", icon: MessageSquare },
                { id: "both", label: "Email & Slack", icon: Zap },
              ].map((opt) => {
                const Icon = opt.icon;
                const isSelected = channel === opt.id;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setChannel(opt.id as "email" | "slack" | "both")}
                    className={`flex flex-col items-center justify-center gap-1.5 rounded-xl border p-3 text-xs font-semibold transition-all ${
                      isSelected
                        ? "border-[#253745] bg-[#253745] text-white shadow-sm dark:border-[#4A5C6A] dark:bg-[#162736]"
                        : "border-[#CCD0CF] bg-white text-[#4A5C6A] hover:bg-[#F1F5F9] dark:border-[#253745] dark:bg-[#06141B] dark:text-[#9BA8AB]"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                    <span>{opt.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Email recipients configuration */}
          {(channel === "email" || channel === "both") && (
            <div>
              <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[#4A5C6A] dark:text-[#9BA8AB]">
                Recipient Emails (comma-separated)
              </label>
              <input
                type="text"
                value={recipientsInput}
                onChange={(e) => setRecipientsInput(e.target.value)}
                placeholder="founder@example.com, account-manager@example.com"
                className="w-full rounded-xl border border-[#CCD0CF] bg-white px-3.5 py-2.5 text-sm font-medium text-[#06141B] outline-none transition focus:border-[#253745] focus:ring-1 focus:ring-[#253745] dark:border-[#253745] dark:bg-[#06141B] dark:text-[#F1F5F9]"
              />
              <p className="mt-1 text-[11px] text-[#4A5C6A] dark:text-[#9BA8AB]">
                Each recipient will receive an HTML summary with a direct link to the report.
              </p>
            </div>
          )}

          {/* Slack Channel configuration */}
          {(channel === "slack" || channel === "both") && (
            <div className="space-y-3 rounded-xl border border-violet-100 bg-violet-50/50 p-4 dark:border-violet-900/30 dark:bg-violet-950/20">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-violet-900 dark:text-violet-300">
                  Target Slack Channel
                </span>
                {!slackConnected && !loadingSlack && (
                  <a
                    href="/dashboard/apps"
                    target="_blank"
                    className="text-xs font-semibold text-violet-600 underline hover:text-violet-800 dark:text-violet-400"
                  >
                    Connect Slack App ↗
                  </a>
                )}
              </div>

              {loadingSlack ? (
                <p className="text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">Checking Slack connection...</p>
              ) : !slackConnected ? (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900/30 dark:bg-amber-950/30 dark:text-amber-300">
                  Slack is not connected to this workspace. Please connect Slack from the{" "}
                  <a href="/dashboard/apps" className="font-semibold underline">
                    Connected Apps
                  </a>{" "}
                  page first.
                </div>
              ) : (
                <select
                  value={selectedSlackChannel}
                  onChange={(e) => setSelectedSlackChannel(e.target.value)}
                  className="w-full rounded-xl border border-violet-200 bg-white px-3.5 py-2.5 text-sm font-medium text-[#06141B] outline-none dark:border-violet-900/50 dark:bg-[#06141B] dark:text-[#F1F5F9]"
                >
                  <option value="">Select a channel...</option>
                  {slackChannels.map((ch) => (
                    <option key={ch.id} value={ch.id}>
                      #{ch.name} {ch.is_private ? "(Private)" : "(Public)"}
                    </option>
                  ))}
                </select>
              )}

              {/* Mandatory privacy warning from PLAN.md */}
              <div className="flex items-start gap-2 rounded-lg border border-amber-200/80 bg-amber-50/80 p-3 text-xs text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-300">
                <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
                <p>
                  <strong>Privacy Warning:</strong> Anyone in this Slack channel will be able to see
                  client insights, extracted needs, and project pattern data shared in these automated digests.
                </p>
              </div>
            </div>
          )}

          {/* Delta-only toggle */}
          <div className="flex items-center justify-between rounded-xl border border-[#E2E8F0] p-4 transition-colors dark:border-[#253745] dark:bg-[#06141B]/40">
            <div className="pr-4">
              <span className="block text-sm font-semibold text-[#06141B] dark:text-[#F1F5F9]">
                Delta Reports Only
              </span>
              <span className="block text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">
                Only run and deliver if new/changed cards or comments were detected since the last run. Saves AI tokens and avoids duplicate notifications.
              </span>
            </div>
            <label className="relative inline-flex cursor-pointer items-center">
              <input
                type="checkbox"
                checked={isDeltaOnly}
                onChange={(e) => setIsDeltaOnly(e.target.checked)}
                className="peer sr-only"
              />
              <div className="peer h-6 w-11 rounded-full bg-slate-200 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:border after:border-gray-300 after:bg-white after:transition-all after:content-[''] peer-checked:bg-[#253745] peer-checked:after:translate-x-full peer-checked:after:border-white dark:bg-slate-700 dark:peer-checked:bg-[#4A5C6A]"></div>
            </label>
          </div>

          {/* Active status */}
          <div className="flex items-center justify-between rounded-xl border border-[#E2E8F0] p-4 transition-colors dark:border-[#253745] dark:bg-[#06141B]/40">
            <div>
              <span className="block text-sm font-semibold text-[#06141B] dark:text-[#F1F5F9]">
                Schedule Active
              </span>
              <span className="block text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">
                Enable or pause this schedule without deleting it.
              </span>
            </div>
            <label className="relative inline-flex cursor-pointer items-center">
              <input
                type="checkbox"
                checked={active}
                onChange={(e) => setActive(e.target.checked)}
                className="peer sr-only"
              />
              <div className="peer h-6 w-11 rounded-full bg-slate-200 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:border after:border-gray-300 after:bg-white after:transition-all after:content-[''] peer-checked:bg-emerald-600 peer-checked:after:translate-x-full peer-checked:after:border-white dark:bg-slate-700 dark:peer-checked:bg-emerald-500"></div>
            </label>
          </div>

          {/* Action buttons */}
          <div className="flex items-center justify-end gap-3 border-t border-[#E2E8F0] pt-5 dark:border-[#253745]">
            <Button type="button" variant="secondary" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={submitting}
              className="bg-[#253745] text-white hover:bg-[#162736] dark:bg-[#162736] dark:text-[#F1F5F9] dark:hover:bg-[#253745]"
            >
              {submitting ? "Saving..." : initialSchedule ? "Save Changes" : "Create Schedule"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
