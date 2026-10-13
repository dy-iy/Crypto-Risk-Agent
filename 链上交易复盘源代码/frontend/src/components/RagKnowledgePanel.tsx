import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Empty, Input, Space, Tag, Typography } from "antd";
import { BookOpen, ChevronDown, ChevronUp, Database, Search, Sparkles } from "lucide-react";
import { searchRagKnowledge } from "../services/api";
import { RagSearchItem } from "../types";

interface RagKnowledgePanelProps {
  defaultQuery?: string;
  title?: string;
  subtitle?: string;
  compact?: boolean;
}

const quickPrompts = [
  { label: "价格操纵", query: "oracle manipulation flash loan price" },
  { label: "重入提款", query: "reentrancy withdraw callback" },
  { label: "权限缺陷", query: "access control owner initialize" },
];

function sourceLabel(source: string) {
  if (source === "vulnerability_type") return "漏洞类型";
  if (source === "curated_case") return "精选案例";
  if (source === "generated_case") return "案例索引";
  if (source === "platform_report") return "平台复盘报告";
  return source || "知识片段";
}

function sourceHint(source: string) {
  if (source === "platform_report") return "来自 AttackPilot 已完成复盘";
  if (source === "vulnerability_type") return "用于理解漏洞模式";
  if (source === "curated_case") return "可参考真实攻击复现";
  if (source === "generated_case") return "来自本地案例索引";
  return "知识库参考";
}

function previewText(value: string, maxLength = 220) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength)}...`;
}

function metadataText(item: RagSearchItem) {
  const dapp = item.metadata?.dapp_name;
  const rootCause = item.metadata?.root_cause;
  const taskId = item.metadata?.task_id;
  const pieces = [dapp, rootCause, taskId ? `task ${String(taskId).slice(0, 8)}` : ""].filter(
    (value) => typeof value === "string" && value.trim(),
  );
  return pieces.join(" / ");
}

const RagKnowledgePanel: React.FC<RagKnowledgePanelProps> = ({
  defaultQuery = "",
  title = "相似案例参考",
  subtitle = "系统会自动召回相似漏洞、历史案例和平台复盘报告，帮助理解当前攻击和修复思路。",
  compact = false,
}) => {
  const [query, setQuery] = useState(defaultQuery);
  const [items, setItems] = useState<RagSearchItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState(false);
  const [manualOpen, setManualOpen] = useState(!compact);

  useEffect(() => {
    const nextQuery = defaultQuery.trim();
    setQuery(defaultQuery);
    if (!nextQuery) return;

    let cancelled = false;
    setLoading(true);
    setError("");
    setSearched(true);
    searchRagKnowledge({ query: nextQuery, top_k: compact ? 3 : 5 })
      .then((response) => {
        if (cancelled) return;
        setItems(response.items || []);
        setTotal(response.total || 0);
      })
      .catch((err) => {
        if (cancelled) return;
        const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
        setError(detail || "相似案例检索暂时不可用，请检查后端知识索引。");
        setItems([]);
        setTotal(0);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [compact, defaultQuery]);

  const topItems = useMemo(() => items.slice(0, compact ? 3 : 5), [compact, items]);

  const runSearch = useCallback(
    async (value = query) => {
      const nextQuery = value.trim();
      if (!nextQuery || loading) return;
      setQuery(nextQuery);
      setLoading(true);
      setError("");
      setSearched(true);
      try {
        const response = await searchRagKnowledge({ query: nextQuery, top_k: compact ? 3 : 5 });
        setItems(response.items || []);
        setTotal(response.total || 0);
      } catch (err) {
        const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
        setError(detail || "相似案例检索暂时不可用，请检查后端知识索引。");
        setItems([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [compact, loading, query],
  );

  return (
    <section className={`rag-knowledge-panel${compact ? " rag-knowledge-panel-compact" : ""}`}>
      <div className="rag-panel-header">
        <Space size={8}>
          <span className="rag-panel-icon">
            <Sparkles size={17} />
          </span>
          <div>
            <Typography.Text strong>{title}</Typography.Text>
            <Typography.Paragraph>{subtitle}</Typography.Paragraph>
          </div>
        </Space>
        <Tag icon={<Database size={13} />}>向量检索</Tag>
      </div>

      <div className="rag-result-list">
        {loading ? (
          <div className="rag-result-meta">
            <BookOpen size={14} />
            <span>正在匹配相似案例...</span>
          </div>
        ) : null}

        {topItems.length ? (
          <>
            <div className="rag-result-meta">
              <BookOpen size={14} />
              <span>
                已召回 {topItems.length} 条参考，候选知识片段 {total} 条
              </span>
            </div>
            {topItems.map((item) => {
              const meta = metadataText(item);
              return (
                <article className="rag-result-card" key={item.id}>
                  <div className="rag-result-title">
                    <Tag>{sourceLabel(item.source)}</Tag>
                    <strong>{item.title}</strong>
                    <span>{Math.round(item.score * 100)}%</span>
                  </div>
                  <small className="rag-source-hint">
                    {sourceHint(item.source)}
                    {meta ? ` / ${meta}` : ""}
                  </small>
                  <p>{previewText(item.content)}</p>
                  {item.tags?.length ? (
                    <div className="rag-tag-row">
                      {item.tags.slice(0, 4).map((tag) => (
                        <Tag key={tag}>{tag}</Tag>
                      ))}
                    </div>
                  ) : null}
                </article>
              );
            })}
          </>
        ) : searched && !loading && !error ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂未召回相似案例" />
        ) : null}
      </div>

      {error ? <Alert type="error" showIcon message={error} /> : null}

      <Button
        type="text"
        className="rag-manual-toggle"
        icon={manualOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        onClick={() => setManualOpen((open) => !open)}
      >
        手动调整关键词
      </Button>

      {manualOpen ? (
        <>
          <div className="rag-search-row">
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onPressEnter={() => runSearch()}
              placeholder="输入漏洞类型、函数名、攻击现象或交易描述"
              allowClear
            />
            <Button type="primary" icon={<Search size={15} />} loading={loading} onClick={() => runSearch()}>
              检索
            </Button>
          </div>

          <div className="rag-prompt-row">
            {quickPrompts.map((prompt) => (
              <button key={prompt.query} type="button" onClick={() => runSearch(prompt.query)}>
                {prompt.label}
              </button>
            ))}
          </div>
        </>
      ) : null}
    </section>
  );
};

export default RagKnowledgePanel;
