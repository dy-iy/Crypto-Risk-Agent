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
    <div className="agent-loader rounded-2xl border border-blue-100 bg-white px-5 py-4 shadow-sm">
      <div className="relative z-10 flex items-start gap-3">
        {icon && (
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-600 text-white">
            {icon}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <LoadingDots label={title} />
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {steps.map((step) => (
              <div key={step} className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-600">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-600" />
                {step}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
