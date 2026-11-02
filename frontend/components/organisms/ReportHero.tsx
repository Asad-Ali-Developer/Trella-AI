import type { RunDetail } from "@/lib/types";

interface ReportHeroProps {
  run: RunDetail;
  clientName?: string | null;
}

export function ReportHero({ run, clientName }: ReportHeroProps) {
  // Guard against failed/running status or missing headline
  if (
    run.status === "failed" ||
    run.status === "running" ||
    !run.output_json?.headline
  ) {
    return null;
  }

  const { headline, health, stats } = run.output_json;

  // 1) Headline Subject & Sentence
  const resolvedName = (clientName ?? run.client_name ?? "").trim();
  const isAllClients =
    !resolvedName || resolvedName.toLowerCase() === "all clients";
  const subject = isAllClients ? "All clients are" : `${resolvedName} is`;

  const statusWord = (headline.status_word ?? "unclear").trim();
  const isUnclear = statusWord.toLowerCase() === "unclear";

  let tone = headline.status_word_tone;
  if (isUnclear) {
    tone = "neutral";
  }

  let markerClass = "border border-amber-200 bg-amber-50 text-amber-700";
  if (tone === "positive") {
    markerClass = "border border-emerald-200 bg-emerald-50 text-emerald-700";
  } else if (tone === "negative") {
    markerClass = "border border-rose-200 bg-rose-50 text-rose-700";
  }

  const rawRest = headline.rest?.trim() ?? "";
  const rest = rawRest
    ? rawRest.startsWith(",") || rawRest.startsWith(".")
      ? rawRest
      : ` ${rawRest}`
    : ".";

  // 2) Summary
  const summary = headline.summary?.trim();

  // 3) Key Figures Strip
  // Health
  const rawHealthStatus = health?.status?.toLowerCase();
  let healthLabel = "n/a";
  let healthDot: string | null = null;

  if (rawHealthStatus === "green") {
    healthLabel = "Healthy";
    healthDot = "bg-emerald-500";
  } else if (rawHealthStatus === "amber") {
    healthLabel = "Watch";
    healthDot = "bg-amber-500";
  } else if (rawHealthStatus === "red") {
    healthLabel = "At risk";
    healthDot = "bg-rose-500";
  } else if (rawHealthStatus === "insufficient_data") {
    healthLabel = "Not enough data";
    healthDot = "bg-zinc-400 dark:bg-zinc-500";
  }

  // Confidence
  const rawConfidence = health?.confidence?.toLowerCase();
  let confidenceLabel = "n/a";
  if (rawConfidence === "insufficient_data") {
    confidenceLabel = "Not enough data";
  } else if (rawConfidence === "high") {
    confidenceLabel = "High";
  } else if (rawConfidence === "medium") {
    confidenceLabel = "Medium";
  } else if (rawConfidence === "low") {
    confidenceLabel = "Low";
  } else if (rawConfidence) {
    confidenceLabel =
      rawConfidence.charAt(0).toUpperCase() + rawConfidence.slice(1);
  }

  // Scope changes
  const scopeChangesVal = stats?.scope_changes;
  const scopeChangesLabel =
    scopeChangesVal !== null && scopeChangesVal !== undefined
      ? String(scopeChangesVal)
      : "n/a";

  // Deadlines moved
  const deadlinesMovedVal = stats?.deadlines_moved;
  const deadlinesMovedLabel =
    deadlinesMovedVal !== null && deadlinesMovedVal !== undefined
      ? String(deadlinesMovedVal)
      : "n/a";

  // Our reply gap
  const replyGapVal = stats?.our_reply_gap_days;
  const replyGapLabel =
    replyGapVal !== null && replyGapVal !== undefined
      ? `${replyGapVal}d`
      : "n/a";

  // Client comments
  const clientCommentsVal = stats?.client_comments;
  const clientCommentsLabel =
    clientCommentsVal !== null && clientCommentsVal !== undefined
      ? String(clientCommentsVal)
      : "n/a";

  const figures = [
    {
      label: "Health",
      value: healthLabel,
      isNA: healthLabel === "n/a",
      dot: healthDot,
    },
    {
      label: "Confidence",
      value: confidenceLabel,
      isNA: confidenceLabel === "n/a",
    },
    {
      label: "Scope changes",
      value: scopeChangesLabel,
      isNA: scopeChangesLabel === "n/a",
    },
    {
      label: "Deadlines moved",
      value: deadlinesMovedLabel,
      isNA: deadlinesMovedLabel === "n/a",
    },
    {
      label: "Our reply gap",
      value: replyGapLabel,
      isNA: replyGapLabel === "n/a",
    },
    {
      label: "Client comments",
      value: clientCommentsLabel,
      isNA: clientCommentsLabel === "n/a",
    },
  ];

  return (
    <section aria-label="Report Hero" className="space-y-6 pb-8 border-b border-zinc-200 dark:border-[#253745]">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-zinc-900 sm:text-3xl md:text-4xl dark:text-[#F1F5F9] leading-tight">
          {subject}{" "}
          <span className={`inline-block px-2.5 py-0.5 rounded-lg font-bold ${markerClass}`}>
            {statusWord}
          </span>
          {rest}
        </h1>
        {summary && (
          <p className="mt-3 max-w-[65ch] text-base leading-relaxed text-zinc-600 dark:text-zinc-400">
            {summary}
          </p>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 sm:gap-6 lg:grid-cols-6 pt-2">
        {figures.map((fig) => {
          const isLongValue = fig.value === "Not enough data";
          return (
            <div key={fig.label} className="flex flex-col gap-1 min-w-0">
              <dt className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 truncate">
                {fig.label}
              </dt>
              <dd
                className={`flex items-center gap-1.5 font-bold tracking-tight ${
                  fig.isNA
                    ? "text-zinc-400 dark:text-zinc-500 font-medium text-lg sm:text-xl"
                    : isLongValue
                    ? "text-zinc-900 dark:text-[#F1F5F9] text-base sm:text-lg"
                    : "text-zinc-900 dark:text-[#F1F5F9] text-xl sm:text-2xl"
                }`}
              >
                {fig.dot && (
                  <span
                    className={`h-2.5 w-2.5 flex-shrink-0 rounded-full ${fig.dot}`}
                    aria-hidden="true"
                  />
                )}
                <span className="truncate">{fig.value}</span>
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
