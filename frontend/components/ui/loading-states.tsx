import { ReactNode } from "react";

export function LoadingDots({ label = "分析中" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm font-semibold text-blue-700">
      <span>{label}</span>
      <span className="flex items-center gap-1" aria-hidden="true">
        <span className="dot-pulse h-1.5 w-1.5 rounded-full bg-blue-600" />
        <span className="dot-pulse h-1.5 w-1.5 rounded-full bg-blue-600" />
        <span className="dot-pulse h-1.5 w-1.5 rounded-full bg-blue-600" />
      </span>
    </span>
  );
}

export function AgentProgress({
  icon,
  title,
  steps,
}: {
  icon?: ReactNode;
  title: string;
  steps: string[];
}) {
  return (
    <div className="agent-loader rounded-2xl border border-blue-100 bg-white px-7 py-6 shadow-sm shadow-blue-100/70">
      <div className="relative z-10 flex items-start gap-5">
        {icon && (
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-emerald-700 text-white">
            {icon}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <LoadingDots label={title} />
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            {steps.map((step) => (
              <div key={step} className="flex min-h-12 items-center gap-3 rounded-lg bg-blue-50/70 px-4 text-sm font-bold text-slate-700">
                <span className="h-2 w-2 rounded-full bg-emerald-600" />
                {step}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
