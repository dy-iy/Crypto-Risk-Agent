import React, { useMemo, useState } from "react";
import { Button, Empty, Space, Tag, Typography } from "antd";
import { CircleDollarSign, GitBranch, PlayCircle, SearchCheck, ShieldCheck, Zap } from "lucide-react";
import { EvidenceItem, ProductViewMode, Task, TaskEvent } from "../types";
import {
  buildAttackPhaseEvidence,
  extractTransactionHashes,
} from "../utils/evidence";
import { findNarrativeSummary, reportNarrativeParagraphs } from "../utils/reportNarrative";
import { getPatchVerificationPresentation } from "../utils/verification";
import EvidenceDrawer from "./EvidenceDrawer";
import { modeLabel } from "../utils/i18n";

interface AttackReplayTimelineProps {
  task: Task | null;
  events: TaskEvent[];
  mode?: ProductViewMode;
}

interface AttackPhase {
  key: string;
  title: string;
  subtitle: string;
  description: string;
  icon: React.ReactNode;
  evidence: EvidenceItem[];
}

function transactionEvidence(report: string): EvidenceItem[] {
  return extractTransactionHashes(reportNarrativeParagraphs(report).map(paragraph => paragraph.content).join("\n"))
    .slice(0, 5)
    .map((hash, index) => ({
      id: `attack-tx-${index}`,
      title: `报告交易引用 ${index + 1}`,
      source: "transaction",
      content: hash,
      full_content: hash,
      confidence: "high",
    }));
}

function buildAttackPhases(task: Task | null, events: TaskEvent[]): AttackPhase[] {
  const report = task?.final_report ?? "";
  const txEvidence = transactionEvidence(report);
  const verification = getPatchVerificationPresentation(task);

  return [
    {
      key: "prepare",
      title: "攻击准备",
      subtitle: "准备攻击条件",
      description: findNarrativeSummary(
        report,
        ["prepare", "create", "pool", "liquidity", "初始化", "创建", "流动性"],
        "报告尚未提供足够的攻击准备叙述。",
        360, ["攻击准备", "攻击前置", "preparation", "setup"],
      ),
      icon: <GitBranch size={17} />,
      evidence: [...txEvidence.slice(0, 2), ...buildAttackPhaseEvidence(events, ["create", "pool", "liquidity", "init"])],
    },
    {
      key: "trigger",
      title: "漏洞触发",
      subtitle: "触发关键函数",
      description: findNarrativeSummary(
        report,
        ["trigger", "convert", "call", "execute", "触发", "调用", "执行"],
        "报告尚未提供足够的漏洞触发叙述。",
        360, ["漏洞触发", "trigger", "攻击路径", "attack path", "exploit path"],
      ),
      icon: <PlayCircle size={17} />,
      evidence: buildAttackPhaseEvidence(events, ["trigger", "convert", "execute", "call", "function", "trace"]),
    },
    {
      key: "manipulate",
      title: "状态操纵",
      subtitle: "改变价格或状态",
      description: findNarrativeSummary(
        report,
        ["manipulate", "slippage", "storage", "event", "price", "操纵", "滑点", "状态", "价格"],
        "报告尚未提供足够的状态操纵叙述。",
        360, ["状态操纵", "价格操纵", "state manipulation", "price manipulation"],
      ),
      icon: <Zap size={17} />,
      evidence: buildAttackPhaseEvidence(events, ["storage", "event", "swap", "price", "balance", "state"]),
    },
    {
      key: "profit",
      title: "攻击获利",
      subtitle: "核对资产转移与收益",
      description: findNarrativeSummary(
        report,
        ["profit", "gain", "benefit", "transfer", "获利", "收益", "转移"],
        "报告尚未提供足够的攻击获利叙述，不能从验证表中的未知收益推断获利。",
        360, ["攻击获利", "资产转移", "profit", "fund flow"],
      ),
      icon: <CircleDollarSign size={17} />,
      evidence: buildAttackPhaseEvidence(events, ["profit", "transfer", "balance", "attacker", "benefit"]),
    },
    {
      key: "verify",
      title: "补丁验证",
      subtitle: "重放检查修复",
      description: `${verification.title}：${verification.description}`,
      icon: <ShieldCheck size={17} />,
      evidence: buildAttackPhaseEvidence(events, ["patch", "verify", "replay", "validation", "success", "failure"]),
    },
  ];
}

const AttackReplayTimeline: React.FC<AttackReplayTimelineProps> = ({ task, events, mode = "report" }) => {
  const [selectedPhase, setSelectedPhase] = useState<AttackPhase | null>(null);
  const phases = useMemo(() => buildAttackPhases(task, events), [events, task]);

  if (!task?.final_report && events.length === 0) {
    return (
      <section className="attack-replay-panel">
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="分析形成证据后，将在此展示攻击复盘时间线。" />
      </section>
    );
  }

  return (
    <section className="attack-replay-panel">
      <div className="panel-header">
        <Space size={8}>
          <GitBranch size={16} />
          <Typography.Text strong>攻击复盘时间线</Typography.Text>
        </Space>
        <Space size={6}><Tag>报告叙述复盘</Tag><Tag>{modeLabel("zh", mode)}</Tag></Space>
      </div>

      <div className="attack-phase-list">
        {phases.map((phase, index) => (
          <article className="attack-phase-card" key={phase.key}>
            <div className="attack-phase-index">{index + 1}</div>
            <div className="attack-phase-icon">{phase.icon}</div>
            <div className="attack-phase-content">
              <div className="attack-phase-head">
                <div>
                  <Typography.Text strong>{phase.title}</Typography.Text>
                  <Typography.Text type="secondary">{phase.subtitle}</Typography.Text>
                </div>
                <Space size={6}>
                  <Tag color={phase.evidence.length > 0 ? "cyan" : "default"}>{phase.evidence.length} 条相关记录</Tag>
                  <Button
                    size="small"
                    icon={<SearchCheck size={14} />}
                    onClick={() => setSelectedPhase(phase)}
                  >
                    查看证据
                  </Button>
                </Space>
              </div>
              <Typography.Paragraph className="attack-phase-description">
                {phase.description}
              </Typography.Paragraph>
            </div>
          </article>
        ))}
      </div>

      <EvidenceDrawer
        title={selectedPhase ? `${selectedPhase.title}证据` : "攻击阶段证据"}
        open={Boolean(selectedPhase)}
        evidence={selectedPhase?.evidence ?? []}
        onClose={() => setSelectedPhase(null)}
      />
    </section>
  );
};

export default AttackReplayTimeline;
