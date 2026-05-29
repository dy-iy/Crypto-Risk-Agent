import { CSSProperties, ReactNode } from "react";

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
  activeStage,
  icon,
  title,
  steps,
}: {
  activeStage?: string;
  icon?: ReactNode;
  title: string;
  steps: string[];
}) {
  const displaySteps = steps.length ? steps : ["输入标准化", "风险信号扫描", "提取证据", "生成报告"];
  const stageOrder = ["input_standardization", "risk_signal_scan", "evidence_extraction", "report_generation"];
  const activeIndex = Math.max(0, stageOrder.indexOf(activeStage || stageOrder[0]));

  return (
    <div className="agent-loader agent-progress-card">
      <div className="relative z-10 flex items-start gap-5">
        {icon && (
          <span className="agent-progress-icon">
            {icon}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <LoadingDots label={title} />
          <div className="agent-step-stage" aria-label="Chat Agent 分析进度">
            {displaySteps.map((step, index) => {
              const stateClass = index === activeIndex ? "is-active" : index < activeIndex ? "is-complete" : "is-pending";
              return (
              <div
                key={`${step}-${stateClass}`}
                className={`agent-step-item ${stateClass}`}
                style={{ "--step-index": index } as CSSProperties}
              >
                <span className="agent-step-dot" />
                <span className="agent-step-text">{step}</span>
              </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
