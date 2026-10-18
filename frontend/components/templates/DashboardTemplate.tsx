import { ReactNode } from "react";

interface DashboardTemplateProps {
  sidebar: ReactNode;
  children: ReactNode;
}

export function DashboardTemplate({ sidebar, children }: DashboardTemplateProps) {
  return (
    <div className="flex h-screen bg-zinc-50">
      {sidebar}
      <main className="min-w-0 flex-1 overflow-y-auto p-8">{children}</main>
    </div>
  );
}
