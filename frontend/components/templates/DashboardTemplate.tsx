import { ReactNode } from "react";

interface DashboardTemplateProps {
  sidebar: ReactNode;
  children: ReactNode;
}

export function DashboardTemplate({ sidebar, children }: DashboardTemplateProps) {
  return (
    <div className="flex min-h-screen flex-col bg-zinc-50 md:h-screen md:flex-row">
      {sidebar}
      <main className="min-w-0 flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">{children}</main>
    </div>
  );
}
