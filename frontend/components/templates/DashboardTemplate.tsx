import { ReactNode } from "react";

interface DashboardTemplateProps {
  sidebar: ReactNode;
  children: ReactNode;
}

export function DashboardTemplate({ sidebar, children }: DashboardTemplateProps) {
  return (
    <div className="flex min-h-screen flex-col bg-[#F8FAFC] text-[#06141B] transition-colors duration-200 dark:bg-[#06141B] dark:text-[#F1F5F9] md:h-screen md:flex-row">
      {sidebar}
      <main className="min-w-0 flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">{children}</main>
    </div>
  );
}
