import { ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { Sparkles, ShieldCheck, BarChart3, Zap, CheckCircle2 } from "lucide-react";

import { ThemeToggle } from "@/components/atoms/ThemeToggle";

interface AuthTemplateProps {
  title: string;
  subtitle: string;
  children: ReactNode;
}

const keyFeatures = [
  {
    icon: BarChart3,
    title: "Executive Summaries",
    description: "Convert chaotic boards into clear sprint metrics and milestone reports.",
  },
  {
    icon: Zap,
    title: "Grounded AI Citations",
    description: "Every finding is strictly verified with direct links to cards and source lists.",
  },
  {
    icon: ShieldCheck,
    title: "Enterprise Security",
    description: "Encrypted credentials, isolated team workspaces, and strict role permissions.",
  },
];

export function AuthTemplate({ title, subtitle, children }: AuthTemplateProps) {
  return (
    <main className="relative min-h-screen w-full overflow-hidden bg-[#F8FAFC] text-[#06141B] transition-colors duration-200 dark:bg-[#06141B] dark:text-[#F1F5F9]">
      {/* Ambient background glows matching palette */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-40 left-1/2 -z-10 h-[600px] w-[1000px] -translate-x-1/2 rounded-full bg-gradient-to-tr from-[#253745]/15 via-[#4A5C6A]/10 to-transparent blur-3xl dark:from-[#11212D]/50 dark:via-[#253745]/30"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-40 right-[-10%] -z-10 h-[500px] w-[600px] rounded-full bg-gradient-to-br from-[#4A5C6A]/15 via-[#9BA8AB]/10 to-transparent blur-3xl dark:from-[#253745]/30"
      />

      {/* Top Header */}
      <header className="relative z-10 flex items-center justify-between px-6 py-5 sm:px-10 lg:px-16">
        <Link
          href="/"
          className="group inline-flex items-center gap-2.5 transition hover:opacity-90"
        >
          <Image
            src="/DeepClient-light.png"
            alt="DeepClient"
            width={380}
            height={98}
            priority
            className="h-9 w-auto dark:hidden"
          />
          <Image
            src="/DeepClient-dark.png"
            alt="DeepClient"
            width={380}
            height={98}
            priority
            className="hidden h-9 w-auto dark:block"
          />
        </Link>

        <div className="flex items-center gap-3">
          <ThemeToggle />
        </div>
      </header>

      {/* Main Content Showcase */}
      <div className="relative z-10 mx-auto grid min-h-[calc(100vh-80px)] max-w-7xl grid-cols-1 items-center px-4 pb-12 sm:px-8 lg:grid-cols-12 lg:gap-12 lg:px-12">
        {/* Left Side: Brand Highlights & Social Proof (Desktop) */}
        <div className="hidden lg:col-span-7 lg:flex lg:flex-col lg:justify-center lg:py-8 lg:pr-8">
          <div className="inline-flex w-fit items-center gap-2 rounded-full border border-[#4A5C6A] bg-[#253745] px-3.5 py-1 text-xs font-semibold text-white shadow-sm">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#9BA8AB] opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-[#F1F5F9]" />
            </span>
            Workspace Intelligence Platform
          </div>

          <h1 className="mt-5 text-4xl font-extrabold tracking-tight sm:text-5xl lg:leading-[1.15] text-[#06141B] dark:text-[#F1F5F9]">
            Turn chaotic task boards into{" "}
            <span className="bg-gradient-to-r from-[#253745] via-[#4A5C6A] to-[#11212D] bg-clip-text text-transparent dark:from-[#FFFFFF] dark:via-[#CCD0CF] dark:to-[#9BA8AB]">
              actionable intelligence.
            </span>
          </h1>

          <p className="mt-4 max-w-xl text-base leading-relaxed text-[#4A5C6A] sm:text-lg dark:text-[#9BA8AB]">
            Connect Trello, Slack, and Jira to generate grounded summaries, monitor team momentum, and track velocity in real-time.
          </p>

          <div className="mt-8 grid gap-4 max-w-lg">
            {keyFeatures.map((feat) => {
              const Icon = feat.icon;
              return (
                <div
                  key={feat.title}
                  className="flex items-start gap-3.5 rounded-2xl border border-[#E2E8F0] bg-white p-4 shadow-sm backdrop-blur-md transition-all hover:border-[#4A5C6A] dark:border-[#253745] dark:bg-[#11212D] dark:hover:border-[#4A5C6A]"
                >
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[#4A5C6A]/50 bg-[#253745] text-white">
                    <Icon className="h-5 w-5" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-[#06141B] dark:text-[#F1F5F9]">{feat.title}</h3>
                    <p className="text-xs text-[#4A5C6A] dark:text-[#9BA8AB] mt-0.5">{feat.description}</p>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-8 flex items-center gap-3 text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">
            <div className="flex -space-x-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-white bg-[#253745] text-[10px] font-bold text-white shadow dark:border-[#06141B]">
                AI
              </div>
              <div className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-white bg-[#4A5C6A] text-[10px] font-bold text-white shadow dark:border-[#06141B]">
                TR
              </div>
              <div className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-white bg-[#11212D] text-[10px] font-bold text-white shadow dark:border-[#06141B]">
                <CheckCircle2 className="h-4 w-4" />
              </div>
            </div>
            <span>Trusted by agile engineering teams and product leaders worldwide.</span>
          </div>
        </div>

        {/* Right Side: Auth Card Container */}
        <div className="flex w-full justify-center lg:col-span-5">
          <div className="relative w-full max-w-md">
            {/* Ambient card aura */}
            <div className="absolute -inset-1 -z-10 rounded-3xl bg-gradient-to-r from-[#253745]/15 via-[#4A5C6A]/15 to-[#11212D]/15 blur-xl dark:from-[#253745]/40 dark:to-[#11212D]/40" />

            <div className="overflow-hidden rounded-3xl border border-[#E2E8F0] bg-white p-7 shadow-xl backdrop-blur-xl transition-all sm:p-9 dark:border-[#253745] dark:bg-[#11212D] dark:shadow-[#06141B]/40">
              {/* Card top accent line */}
              <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-[#253745] via-[#4A5C6A] to-[#253745]" />

              <div className="mb-6 space-y-1.5 text-left">
                <div className="inline-flex items-center gap-1.5 text-xs font-semibold tracking-wider text-[#253745] uppercase dark:text-[#9BA8AB]">
                  <Sparkles className="h-3.5 w-3.5" />
                  DeepClient Intelligence
                </div>
                <h2 className="text-2xl font-bold tracking-tight text-[#06141B] dark:text-[#F1F5F9]">{title}</h2>
                <p className="text-sm text-[#4A5C6A] dark:text-[#9BA8AB]">{subtitle}</p>
              </div>

              {children}
            </div>

            <p className="mt-6 text-center text-xs text-[#4A5C6A] dark:text-[#9BA8AB]">
              By proceeding, you agree to Trella AI&apos;s{" "}
              <Link href="#" className="underline hover:text-[#06141B] dark:hover:text-[#F1F5F9]">
                Terms of Service
              </Link>{" "}
              and{" "}
              <Link href="#" className="underline hover:text-[#06141B] dark:hover:text-[#F1F5F9]">
                Privacy Policy
              </Link>
              .
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}
