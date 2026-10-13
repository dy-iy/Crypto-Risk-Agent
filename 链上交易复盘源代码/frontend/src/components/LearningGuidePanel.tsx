import React, { useMemo } from "react";
import { Button, Empty, List, Space, Tag, Timeline, Typography } from "antd";
import { BookOpen, ExternalLink, GitBranch, Landmark, Route, ShieldAlert, Target, WalletCards, Zap } from "lucide-react";
import { LanguageMode, MacroAnalysisResponse, Task } from "../types";
import { getDappMetadata, shortHash } from "../utils/dappMetadata";
import MarkdownRenderer from "./MarkdownRenderer";
import RagKnowledgePanel from "./RagKnowledgePanel";

interface LearningGuidePanelProps {
  task: Task | null;
  macro: MacroAnalysisResponse | null;
  language?: LanguageMode;
}

function openExternal(url?: string) {
  if (!url) return;
  window.open(url, "_blank", "noopener,noreferrer");
}

function firstByType(macro: MacroAnalysisResponse | null, type: "attack" | "auxiliary") {
  return macro?.transactions.find((tx) => tx.type === type);
}

const LearningGuidePanel: React.FC<LearningGuidePanelProps> = ({ task, macro, language = "zh" }) => {
  const metadata = useMemo(() => getDappMetadata(task?.dapp_name), [task?.dapp_name]);
  const attackTx = firstByType(macro, "attack");
  const auxiliaryTx = firstByType(macro, "auxiliary");
  const debugTargets = macro?.transactions.filter((tx) => tx.is_debug_target) ?? [];

  const references = [
    { label: language === "zh" ? "漏洞披露" : "Disclosure", ...metadata?.disclosure },
    { label: language === "zh" ? "检测记录" : "Detection", ...metadata?.detection },
    { label: language === "zh" ? "原始报告" : "Report", link: metadata?.report_link },
  ].filter((item) => item.link);

  const title = metadata?.name ?? task?.dapp_name ?? "DApp";
  const isZh = language === "zh";
  const cause = metadata?.cause_zh ?? metadata?.cause;
  const platform = metadata?.platform_zh ?? metadata?.platform;
  const rootCause = metadata?.root_cause_zh ?? metadata?.root_cause;
  const ragQuery = [title, cause, rootCause, macro?.bug_summary]
    .filter(Boolean)
    .join(" ");
  const steps = [
    {
      title: "背景知识",
      icon: <BookOpen size={16} />,
      text:
        metadata?.report_zh ||
        metadata?.background_zh ||
        metadata?.report ||
        (isZh
          ? "先理解该 DApp 的业务角色、合约功能和历史漏洞背景。"
          : "Start from the DApp role, contract responsibility, and incident background."),
    },
    {
      title: isZh ? "攻击准备" : "Preparation",
      icon: <GitBranch size={16} />,
      text: auxiliaryTx
        ? `${isZh ? "宏观分析识别到辅助交易" : "Macro analysis identified auxiliary transaction"} ${shortHash(
            auxiliaryTx.hash,
          )}${auxiliaryTx.function_signature ? ` (${auxiliaryTx.function_signature})` : ""}.`
        : isZh
          ? "观察攻击前是否存在初始化、流动性准备、授权或辅助合约部署。"
          : "Check initialization, liquidity setup, approvals, or helper contracts before the exploit.",
    },
    {
      title: isZh ? "漏洞触发" : "Exploit Trigger",
      icon: <ShieldAlert size={16} />,
      text: attackTx
        ? `${isZh ? "核心攻击交易为" : "The main attack transaction is"} ${shortHash(attackTx.hash)}${
            attackTx.function_signature ? `, ${isZh ? "入口函数" : "entry"} ${attackTx.function_signature}` : ""
          }.`
        : isZh
          ? "定位最终触发异常状态变化或资产转移的核心交易。"
          : "Locate the core transaction that triggers abnormal state changes or asset transfer.",
    },
    {
      title: isZh ? "状态变化与证据" : "State Evidence",
      icon: <Zap size={16} />,
      text:
        macro?.bug_summary ||
        (isZh
          ? "结合 Trace、事件日志和余额变化确认模型判断是否有链上证据支撑。"
          : "Use trace, event logs, and balance changes to confirm whether the model claim is evidence-backed."),
    },
    {
      title: isZh ? "微观调试目标" : "Micro Debug Target",
      icon: <Target size={16} />,
      text:
        debugTargets.length > 0
          ? debugTargets
              .slice(0, 3)
              .map((tx) => `${shortHash(tx.hash)}${tx.function_signature ? ` (${tx.function_signature})` : ""}`)
              .join(", ")
          : isZh
            ? "宏观阶段会筛选需要进入 Trace Debugger 的交易，避免所有交易都进入长链推理。"
            : "The macro stage selects transactions for Trace Debugger instead of sending every transaction into long-chain reasoning.",
    },
  ];

  return (
    <section className="learning-guide-panel">
      <div className="panel-header">
        <Space size={8}>
          <BookOpen size={16} />
          <div>
            <Typography.Text strong>{isZh ? `${title} 学习导览` : `${title} Learning Guide`}</Typography.Text>
            <Typography.Text type="secondary" className="macro-subtitle">
              {isZh
                ? "把案例背景、攻击阶段和 AttackPilot 的宏观/微观分析串起来，适合演示和教学。"
            : "串联案例背景、攻击阶段和 AttackPilot 的宏观/微观分析，适合演示和教学。"}
            </Typography.Text>
          </div>
        </Space>
        <Space size={6}>
          {platform ? <Tag>{platform}</Tag> : null}
          {cause ? <Tag color="blue">{cause}</Tag> : null}
        </Space>
      </div>

      <div className="learning-guide-body">
        <div className="learning-context-grid">
          <section className="learning-card learning-hero">
            <Space size={8}>
              <Landmark size={16} />
              <Typography.Text strong>漏洞背景</Typography.Text>
            </Space>
            <div className="learning-meta-strip">
              <Tag>{metadata?.time ?? "暂无时间"}</Tag>
              <Tag>{rootCause ?? "根因待解析"}</Tag>
            </div>
            <MarkdownRenderer content={metadata?.report_zh || metadata?.background_zh || metadata?.report || macro?.bug_summary || ""} compact />
          </section>

          <section className="learning-card">
            <Space size={8}>
              <WalletCards size={16} />
              <Typography.Text strong>{isZh ? "关键交易入口" : "Key Transaction Entry"}</Typography.Text>
            </Space>
            {macro?.transactions?.length ? (
              <List
                size="small"
                dataSource={macro.transactions.slice(0, 6)}
                renderItem={(tx) => (
                  <List.Item>
                    <List.Item.Meta
                      title={
                        <Space size={6} wrap>
                          <Typography.Text copyable={{ text: tx.hash }} className="text-mono">
                            {shortHash(tx.hash)}
                          </Typography.Text>
                          <Tag color={tx.type === "attack" ? "error" : tx.type === "auxiliary" ? "processing" : "default"}>
                            {tx.type === "attack" ? "攻击交易" : tx.type === "auxiliary" ? "辅助交易" : "候选交易"}
                          </Tag>
                          {tx.is_debug_target ? <Tag color="purple">调试目标</Tag> : null}
                        </Space>
                      }
                      description={tx.function_signature || `${tx.from_role || "未知角色"} -> ${tx.to_role || "未知角色"}`}
                    />
                  </List.Item>
                )}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={isZh ? "暂无宏观交易结果" : "No macro transaction result"} />
            )}
          </section>
        </div>

        <section className="learning-card">
          <Space size={8}>
            <Route size={16} />
            <Typography.Text strong>{isZh ? "攻击阶段讲解" : "Attack Stage Explanation"}</Typography.Text>
          </Space>
          <Timeline
            className="learning-timeline"
            items={steps.map((step) => ({
              dot: <span className="learning-step-dot">{step.icon}</span>,
              children: (
                <div>
                  <Typography.Text strong>{step.title}</Typography.Text>
                  <MarkdownRenderer content={step.text} compact />
                </div>
              ),
            }))}
          />
        </section>

        <RagKnowledgePanel
          compact
          defaultQuery={ragQuery}
          title={isZh ? "相似案例召回" : "Similar Case Retrieval"}
          subtitle={isZh ? "从知识库中召回相似漏洞、历史案例和复现材料，辅助理解当前攻击。" : "Retrieve related vulnerabilities, cases, and reproductions from the knowledge base."}
        />

        <section className="learning-card">
          <Space size={8}>
            <ExternalLink size={16} />
            <Typography.Text strong>{isZh ? "延伸阅读" : "References"}</Typography.Text>
          </Space>
          {references.length ? (
            <div className="learning-reference-row">
              {references.map((item) => (
                <Button key={item.label} size="small" icon={<ExternalLink size={13} />} onClick={() => openExternal(item.link)}>
                  {item.label}
                </Button>
              ))}
            </div>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={isZh ? "暂无外部链接" : "No external links"} />
          )}
        </section>
      </div>
    </section>
  );
};

export default LearningGuidePanel;
