"use client";

import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";
import { LoadingDots } from "@/components/ui/loading-states";

type ActiveView =
  | "attackpilot"
  | "home"
  | "chat"
  | "news"
  | "coin"
  | "daily"

  | "sim"
  | "reports"
  | "favoriteNews"
  | "favoriteReports"
  | "settings"
  | "my";

const RiskDashboard = dynamic(() => import("@/components/risk-dashboard"), {
  loading: () => <DashboardSkeleton />,
  ssr: false,
});

export default function RiskDashboardLoader({ initialView = "home" }: { initialView?: ActiveView }) {
  return <RiskDashboard initialView={initialView} />;
}

function DashboardSkeleton() {
  const pathname = usePathname();
  if (pathname === "/attackpilot" || pathname.startsWith("/attackpilot/")) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50">
        <LoadingDots label="加载链上攻击复盘" />
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-50">
      <header className="border-b border-blue-100 bg-white px-4 py-4 sm:px-6">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
          <div>
            <div className="h-4 w-32 rounded bg-blue-100" />
            <div className="mt-3 h-7 w-56 rounded bg-slate-200" />
          </div>
          <div className="hidden h-10 w-36 rounded-lg bg-blue-100 sm:block" />
        </div>
      </header>
      <section className="mx-auto grid max-w-7xl gap-4 px-4 py-5 sm:px-6 lg:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="hidden rounded-lg border border-blue-100 bg-white p-4 lg:block">
          <div className="space-y-3">
            {Array.from({ length: 8 }, (_, index) => (
              <div key={index} className="h-9 rounded-md bg-slate-100" />
            ))}
          </div>
        </aside>
        <div className="space-y-4">
          <div className="rounded-lg border border-blue-100 bg-white p-5">
            <LoadingDots label="加载风险工作台" />
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              <div className="h-24 rounded-lg bg-blue-50" />
              <div className="h-24 rounded-lg bg-slate-100" />
              <div className="h-24 rounded-lg bg-emerald-50" />
            </div>
          </div>
          <div className="rounded-lg border border-blue-100 bg-white p-5">
            <div className="h-5 w-44 rounded bg-slate-200" />
            <div className="mt-4 space-y-3">
              {Array.from({ length: 5 }, (_, index) => (
                <div key={index} className="h-14 rounded-lg bg-slate-100" />
              ))}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
