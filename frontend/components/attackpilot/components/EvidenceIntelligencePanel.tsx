import React, { useMemo, useState } from "react";
import { Button, Progress, Space, Tag, Typography } from "antd";
import { Activity, Database, SearchCheck, ShieldCheck, TriangleAlert, Wrench } from "lucide-react";
import { EvidenceItem, LanguageMode, ReportSectionKey } from "../types";
import { enrichEvidenceItems, evidenceScoreLabel, summarizeEvidenceHealth } from "../utils/evidenceScoring";
import EvidenceDrawer from "./EvidenceDrawer";

interface EvidenceSection {
  key: ReportSectionKey;
  title: string;
  content: string;
  evidence: EvidenceItem[];
}

interface EvidenceIntelligencePanelProps {
  sections: EvidenceSection[];
  language?: LanguageMode;
}

function scoreColor(label: string) {
  if (label === "strong") return "success";
  if (label === "supporting") return "processing";
  return "exception";
}

const EvidenceIntelligencePanel: React.FC<EvidenceIntelligencePanelProps> = ({ sections, language = "zh" }) => {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const isZh = language === "zh";
  const allEvidence = useMemo(() => sections.flatMap((section) => section.evidence), [sections]);
  const enrichedEvidence = useMemo(() => enrichEvidenceItems(allEvidence).slice(0, 12), [allEvidence]);
  const health = useMemo(() => summarizeEvidenceHealth(allEvidence), [allEvidence]);
  const sectionHealth = useMemo(
    () =>
      sections.map((section) => ({
        ...section,
        health: summarizeEvidenceHealth(section.evidence),
      })),
    [sections],
  );

  return (
    <section className="evidence-intelligence-card">
      <div className="evidence-intelligence-head">
        <Space size={8}>
          <ShieldCheck size={16} />
          <div>
            <Typography.Text strong>{isZh ? "证据智能筛选" : "Evidence Intelligence"}</Typography.Text>
            <Typography.Text type="secondary">
              {isZh
                ? "按来源、工具调用和哈希引用排列相关记录；分数不代表证据已验证或结论正确。"
                : "Ranks related records by source and references; scores do not establish verified evidence or correct conclusions."}
            </Typography.Text>
          </div>
        </Space>
        <Button size="small" icon={<SearchCheck size={14} />} onClick={() => setDrawerOpen(true)}>
          {isZh ? "查看相关记录" : "Top Evidence"}
        </Button>
      </div>

      <div className="evidence-health-grid">
        <div className="evidence-score-card">
          <Progress
            type="circle"
            percent={health.score}
            size={72}
            status={health.label === "weak" ? "exception" : "normal"}
          />
          <div>
            <Tag color={scoreColor(health.label)}>{evidenceScoreLabel(health.label, language)}</Tag>
            <Typography.Text type="secondary">
              {isZh ? "整体记录相关性" : "Overall record relevance"}
            </Typography.Text>
          </div>
        </div>
        <div className="evidence-metric-strip">
          <span>
            <ShieldCheck size={14} />
            {health.strong} {isZh ? "条高相关记录" : "strong"}
          </span>
          <span>
            <Activity size={14} />
            {health.supporting} {isZh ? "条相关记录" : "supporting"}
          </span>
          <span>
            <Database size={14} />
            {health.transactions} {isZh ? "条交易引用" : "tx"}
          </span>
          <span>
            <Wrench size={14} />
            {health.tools} {isZh ? "条工具记录" : "tool"}
          </span>
        </div>
      </div>

      <div className="evidence-section-bars">
        {sectionHealth.map((section) => (
          <div className="evidence-section-bar" key={section.key}>
            <div className="evidence-section-bar-head">
              <Typography.Text strong>{section.title}</Typography.Text>
              <Space size={4} wrap className="evidence-section-tags">
                <Tag color={scoreColor(section.health.label)}>{evidenceScoreLabel(section.health.label, language)}</Tag>
                <Tag>{section.health.total} {isZh ? "条相关记录" : "evidence"}</Tag>
              </Space>
            </div>
            <Progress
              percent={section.health.score}
              size="small"
              status={section.health.label === "weak" ? "exception" : "normal"}
              showInfo={false}
            />
          </div>
        ))}
      </div>

      {health.risks.length ? (
        <div className="evidence-risk-row">
          <TriangleAlert size={14} />
          <Space size={4} wrap>
            {health.risks.map((risk) => (
              <Tag key={risk} color="warning">
                {risk}
              </Tag>
            ))}
          </Space>
        </div>
      ) : null}

      <EvidenceDrawer
        title={isZh ? "相关记录排序" : "Top Ranked Evidence"}
        open={drawerOpen}
        evidence={enrichedEvidence}
        onClose={() => setDrawerOpen(false)}
      />
    </section>
  );
};

export default EvidenceIntelligencePanel;
