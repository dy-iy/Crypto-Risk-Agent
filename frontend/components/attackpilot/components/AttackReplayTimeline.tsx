import React, { useMemo, useState } from "react";
import { Button, Empty, Space, Tag, Typography } from "antd";
import { CircleDollarSign, GitBranch, PlayCircle, SearchCheck, ShieldCheck, Zap } from "lucide-react";
import { EvidenceItem, ProductViewMode, Task, TaskEvent } from "../types";
import {
  buildAttackPhaseEvidence,
  compactEvidenceText,
  extractTransactionHashes,
} from "../utils/evidence";
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

function findTextByKeywords(report: string, keywords: string[], fallback: string) {
  const paragraphs = report
    .split(/\n\s*\n/)
    .map((item) => item.trim())
    .filter(Boolean);
  const normalized = keywords.map((keyword) => keyword.toLowerCase());
  const match = paragraphs.find((paragraph) => {
    const haystack = paragraph.toLowerCase();
    return normalized.some((keyword) => haystack.includes(keyword));
  });
  return match ? compactEvidenceText(match, 360) : fallback;
}

function transactionEvidence(report: string): EvidenceItem[] {
  return extractTransactionHashes(report)
    .slice(0, 5)
    .map((hash, index) => ({
      id: `attack-tx-${index}`,
      title: `攻击交易 ${index + 1}`,
      source: "transaction",
      content: hash,
      full_content: hash,
      confidence: "high",
    }));
}

function buildAttackPhases(task: Task | null, events: TaskEvent[]): AttackPhase[] {
  const report = task?.final_report ?? "";
  const txEvidence = transactionEvidence(report);

  return [
    {
      key: "prepare",
      title: "攻击准备",
      subtitle: "准备攻击条件",
      description: findTextByKeywords(
        report,
        ["prepare", "create", "pool", "liquidity", "初始化", "创建", "流动性"],
        "识别攻击者是否先创建市场、准备流动性、部署辅助合约或设置攻击前置状态。",
      ),
      icon: <GitBranch size={17} />,
      evidence: [...txEvidence.slice(0, 2), ...buildAttackPhaseEvidence(events, ["create", "pool", "liquidity", "init"])],
    },
    {
      key: "trigger",
      title: "漏洞触发",
      subtitle: "触发关键函数",
      description: findTextByKeywords(
        report,
        ["trigger", "convert", "call", "execute", "触发", "调用", "执行"],
        "定位触发漏洞的核心交易、核心函数和关键调用链。",
      ),
      icon: <PlayCircle size={17} />,
      evidence: buildAttackPhaseEvidence(events, ["trigger", "convert", "execute", "call", "function", "trace"]),
    },
    {
      key: "manipulate",
      title: "状态操纵",
      subtitle: "改变价格或状态",
      description: findTextByKeywords(
        report,
        ["manipulate", "slippage", "storage", "event", "price", "操纵", "滑点", "状态", "价格"],
        "观察执行轨迹、状态变更和事件日志中是否出现价格、储备、余额或权限状态异常。",
      ),
      icon: <Zap size={17} />,
      evidence: buildAttackPhaseEvidence(events, ["storage", "event", "swap", "price", "balance", "state"]),
    },
    {
      key: "profit",
      title: "攻击获利",
      subtitle: "完成资产转移",
      description: findTextByKeywords(
        report,
        ["profit", "gain", "benefit", "transfer", "获利", "收益", "转移"],
        "归纳攻击者最终如何完成资产转移或套利收益。",
      ),
      icon: <CircleDollarSign size={17} />,
      evidence: buildAttackPhaseEvidence(events, ["profit", "transfer", "balance", "attacker", "benefit"]),
    },
    {
      key: "verify",
      title: "补丁验证",
      subtitle: "重放检查修复",
      description: findTextByKeywords(
        report,
        ["verify", "patch", "replay", "validation", "验证", "补丁", "抵挡"],
        "检查补丁建议是否经过重放验证，以及攻击路径是否被阻断。",
      ),
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
        <Tag>{modeLabel("zh", mode)}</Tag>
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
                  <Tag color={phase.evidence.length > 0 ? "cyan" : "default"}>{phase.evidence.length} 条证据</Tag>
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
