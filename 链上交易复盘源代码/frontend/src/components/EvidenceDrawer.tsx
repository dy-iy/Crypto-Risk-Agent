import React, { useMemo, useState } from "react";
import { Descriptions, Drawer, Empty, List, Progress, Segmented, Space, Tag, Typography } from "antd";
import { Database, FileText, TerminalSquare, Wrench } from "lucide-react";
import { EvidenceItem } from "../types";
import { normalizeEvidenceMarkdown } from "../utils/evidence";
import { enrichEvidenceItems, isToolBackedEvidence } from "../utils/evidenceScoring";
import MarkdownRenderer from "./MarkdownRenderer";
import { agentDisplayName, messageTypeLabel } from "../utils/presentation";

interface EvidenceDrawerProps {
  title: string;
  open: boolean;
  evidence: EvidenceItem[];
  onClose: () => void;
}

function getSourceIcon(source: EvidenceItem["source"]) {
  if (source === "tool") return <Wrench size={14} />;
  if (source === "transaction") return <Database size={14} />;
  if (source === "report") return <FileText size={14} />;
  return <TerminalSquare size={14} />;
}

type EvidenceFilter = "all" | "tool_backed" | "no_tool" | "report_only" | "weak";

function getSupportColor(confidence: EvidenceItem["confidence"]) {
  if (confidence === "high") return "success";
  if (confidence === "medium") return "warning";
  return "default";
}

function getScoreColor(label?: EvidenceItem["score_label"]) {
  if (label === "strong") return "success";
  if (label === "supporting") return "processing";
  return "default";
}

function renderableContent(item: EvidenceItem) {
  return normalizeEvidenceMarkdown(item.full_content || item.content);
}

function tierLabel(tier?: EvidenceItem["evidence_tier"]) {
  if (tier === "verified") return "已验证";
  if (tier === "tool_backed") return "工具证据";
  if (tier === "agent_derived") return "智能体推理";
  return "报告提取";
}

function supportLabel(confidence: EvidenceItem["confidence"]) {
  if (confidence === "high") return "强支撑";
  if (confidence === "medium") return "一般支撑";
  return "弱支撑";
}

const EvidenceDrawer: React.FC<EvidenceDrawerProps> = ({ title, open, evidence, onClose }) => {
  const [filter, setFilter] = useState<EvidenceFilter>("all");
  const rankedEvidence = useMemo(() => enrichEvidenceItems(evidence), [evidence]);
  const visibleEvidence = useMemo(() => {
    if (filter === "tool_backed") return rankedEvidence.filter(isToolBackedEvidence);
    if (filter === "no_tool") return rankedEvidence.filter((item) => !isToolBackedEvidence(item));
    if (filter === "report_only") return rankedEvidence.filter((item) => item.evidence_tier === "report_derived");
    if (filter === "weak") return rankedEvidence.filter((item) => item.score_label === "weak");
    return rankedEvidence;
  }, [filter, rankedEvidence]);

  return (
    <Drawer title={title} open={open} onClose={onClose} size="large" className="evidence-drawer">
      {rankedEvidence.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关联证据" />
      ) : (
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Segmented
            size="small"
            value={filter}
            onChange={(value) => setFilter(value as EvidenceFilter)}
            options={[
              { label: "全部", value: "all" },
              { label: "工具证据", value: "tool_backed" },
              { label: "无工具支撑", value: "no_tool" },
              { label: "仅报告", value: "report_only" },
              { label: "弱证据", value: "weak" },
            ]}
          />
          {visibleEvidence.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有符合筛选条件的证据" />
          ) : (
            <List
              className="evidence-list"
              dataSource={visibleEvidence}
              renderItem={(item) => (
                <List.Item className="evidence-item">
                  <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                    <div className="evidence-item-head">
                      <Space size={8} wrap>
                        <span className="evidence-source-icon">{getSourceIcon(item.source)}</span>
                        <Typography.Text strong>{item.title}</Typography.Text>
                        <Tag>{tierLabel(item.evidence_tier)}</Tag>
                        <Tag color={getSupportColor(item.confidence)}>{supportLabel(item.confidence)}</Tag>
                        <Tag color={getScoreColor(item.score_label)}>
                          {item.score_label === "strong" ? "强证据" : item.score_label === "supporting" ? "辅助证据" : "弱证据"}
                        </Tag>
                      </Space>
                    </div>

                    <div className="evidence-score-row">
                      <Progress
                        percent={item.score ?? 0}
                        size="small"
                        status={item.score_label === "weak" ? "exception" : "normal"}
                        showInfo
                      />
                      <div className="evidence-reasons">
                        {(item.score_reasons ?? []).map((reason) => (
                          <Tag key={reason}>{reason}</Tag>
                        ))}
                      </div>
                    </div>

                    <Descriptions bordered size="small" column={1}>
                      {item.agent ? <Descriptions.Item label="智能体">{agentDisplayName(item.agent)}</Descriptions.Item> : null}
                      {item.message_type ? <Descriptions.Item label="类型">{messageTypeLabel(item.message_type)}</Descriptions.Item> : null}
                      {item.timestamp ? <Descriptions.Item label="时间">{item.timestamp}</Descriptions.Item> : null}
                      {item.log_id ? (
                        <Descriptions.Item label="Log ID">
                          <Typography.Text copyable className="text-mono">
                            {item.log_id}
                          </Typography.Text>
                        </Descriptions.Item>
                      ) : null}
                    </Descriptions>

                    <div className="evidence-content">
                      <MarkdownRenderer content={renderableContent(item)} compact />
                    </div>
                  </Space>
                </List.Item>
              )}
            />
          )}
        </Space>
      )}
    </Drawer>
  );
};

export default EvidenceDrawer;
