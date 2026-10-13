import React from "react";
import { Empty, Space, Tag, Typography } from "antd";
import {
  BadgeDollarSign,
  Bot,
  Bug,
  CircleHelp,
  DatabaseZap,
  Landmark,
  Route,
  ShieldAlert,
  Target,
  UserRound,
  WalletCards,
} from "lucide-react";
import { LanguageMode, MacroAnalysisResponse, MacroTransactionSummary, TransactionRoleEvidence } from "../types";
import { t } from "../utils/i18n";
import MarkdownRenderer from "./MarkdownRenderer";

interface MacroAnalysisPanelProps {
  macro: MacroAnalysisResponse | null;
  language?: LanguageMode;
}

function shortHash(value?: string | null) {
  if (!value) return "暂无";
  return value.length > 18 ? `${value.slice(0, 10)}...${value.slice(-6)}` : value;
}

function formatUsd(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "暂无";
  const sign = value > 0 ? "+" : "";
  return `${sign}$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function getRoleIcon(role?: string | null) {
  const normalized = (role || "").toLowerCase();
  if (normalized.includes("attacker")) return <Bug size={14} />;
  if (normalized.includes("profit") || normalized.includes("benefit")) return <BadgeDollarSign size={14} />;
  if (normalized.includes("pool") || normalized.includes("liquidity")) return <DatabaseZap size={14} />;
  if (normalized.includes("router") || normalized.includes("dex")) return <Route size={14} />;
  if (normalized.includes("token")) return <WalletCards size={14} />;
  if (normalized.includes("contract")) return <Landmark size={14} />;
  return <UserRound size={14} />;
}

function getTxIcon(tx: MacroTransactionSummary) {
  if (tx.is_debug_target) return <Target size={16} />;
  if (tx.type === "attack") return <ShieldAlert size={16} />;
  if (tx.type === "auxiliary") return <Route size={16} />;
  return <CircleHelp size={16} />;
}

function getTxColor(tx: MacroTransactionSummary) {
  if (tx.is_debug_target) return "purple";
  if (tx.type === "attack") return "error";
  if (tx.type === "auxiliary") return "processing";
  return "default";
}

function getTxTypeLabel(language: LanguageMode, tx: MacroTransactionSummary) {
  if (tx.type === "attack") return t(language, "attack");
  if (tx.type === "auxiliary") return t(language, "auxiliary");
  return t(language, "candidate");
}

function flattenRoles(macro: MacroAnalysisResponse): TransactionRoleEvidence[] {
  const fromRoleMap = Object.entries(macro.transaction_roles || {}).map(([address, role]) => ({
    address,
    role: role.role,
    description: role.description,
  }));

  const fromTransactions = macro.transactions.flatMap((tx) => tx.involved_roles || []);
  const merged = new Map<string, TransactionRoleEvidence>();
  [...fromRoleMap, ...fromTransactions].forEach((item) => {
    if (!item.address) return;
    const current = merged.get(item.address);
    merged.set(item.address, {
      address: item.address,
      role: item.role || current?.role,
      description: item.description || current?.description,
    });
  });
  return Array.from(merged.values());
}

const MacroAnalysisPanel: React.FC<MacroAnalysisPanelProps> = ({ macro, language = "en" }) => {
  if (!macro) {
    return (
      <section className="macro-panel">
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t(language, "noMacro")} />
      </section>
    );
  }

  const roles = flattenRoles(macro);
  const attackCount = macro.transactions.filter((tx) => tx.type === "attack").length || macro.attack_transactions.length;
  const auxiliaryCount =
    macro.transactions.filter((tx) => tx.type === "auxiliary").length || macro.auxiliary_transactions.length;
  const debugTargetCount =
    macro.transactions.filter((tx) => tx.is_debug_target).length || macro.transactions_need_analyze.length;

  return (
    <section className="macro-panel">
      <div className="panel-header">
        <Space size={8}>
          <Bot size={16} />
          <div>
            <Typography.Text strong>{t(language, "macroTitle")}</Typography.Text>
            <Typography.Text type="secondary" className="macro-subtitle">
              {t(language, "macroSubtitle")}
            </Typography.Text>
          </div>
        </Space>
        <Tag color="cyan">{macro.processed_file}</Tag>
      </div>

      <div className="macro-body">
        <div className="macro-metrics">
          <div className="macro-metric-card macro-danger">
            <ShieldAlert size={18} />
            <span>{attackCount}</span>
            <small>{t(language, "attackTx")}</small>
          </div>
          <div className="macro-metric-card macro-info">
            <Route size={18} />
            <span>{auxiliaryCount}</span>
            <small>{t(language, "auxiliaryTx")}</small>
          </div>
          <div className="macro-metric-card macro-purple">
            <Target size={18} />
            <span>{debugTargetCount}</span>
            <small>{t(language, "debugTargets")}</small>
          </div>
          <div className="macro-metric-card">
            <UserRound size={18} />
            <span>{roles.length}</span>
            <small>{t(language, "addressRoles")}</small>
          </div>
        </div>

        <div className="macro-grid">
          <section className="macro-card">
            <div className="macro-section-title">
              <Typography.Text strong>{t(language, "transactionClasses")}</Typography.Text>
              <Tag>{macro.transactions.length} tx</Tag>
            </div>
            <div className="macro-tx-list">
              {macro.transactions.map((tx) => (
                <article className="macro-tx-row" key={tx.hash}>
                  <span className={`tx-type-icon tx-${tx.type}${tx.is_debug_target ? " tx-debug-target" : ""}`}>
                    {getTxIcon(tx)}
                  </span>
                  <div>
                    <Space size={6} wrap>
                      <Typography.Text copyable={{ text: tx.hash }} className="text-mono">
                        {shortHash(tx.hash)}
                      </Typography.Text>
                      <Tag color={getTxColor(tx)}>{getTxTypeLabel(language, tx)}</Tag>
                      {tx.is_debug_target ? <Tag color="purple">{t(language, "debugTarget")}</Tag> : null}
                    </Space>
                    <div className="macro-tx-meta">
                      <span>
                        {t(language, "functionSig")}: {tx.function_signature || "暂无"}
                      </span>
                      <span>
                        {t(language, "balanceDelta")}: {formatUsd(tx.balance_summary?.total_usd_delta)}
                      </span>
                      <span>
                        {t(language, "from")}: {tx.from_role || shortHash(tx.from)}
                      </span>
                      <span>
                        {t(language, "to")}: {tx.to_role || shortHash(tx.to)}
                      </span>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="macro-card">
            <div className="macro-section-title">
              <Typography.Text strong>{t(language, "roleMap")}</Typography.Text>
              <Tag>{roles.length}</Tag>
            </div>
            <div className="macro-role-grid">
              {roles.map((item) => (
                <article className="macro-role-card" key={item.address}>
                  <span className="macro-role-icon">{getRoleIcon(item.role)}</span>
                  <div>
                    <Space size={6} wrap>
                      <Tag className="tx-role-tag">{item.role || "未知角色"}</Tag>
                      <Typography.Text copyable={{ text: item.address }} className="text-mono">
                        {shortHash(item.address)}
                      </Typography.Text>
                    </Space>
                    <Typography.Paragraph ellipsis={{ rows: 2 }}>{item.description || "暂无说明"}</Typography.Paragraph>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>

        <section className="macro-card macro-summary-card">
          <div className="macro-section-title">
            <Typography.Text strong>{t(language, "faultSummary")}</Typography.Text>
          </div>
          <MarkdownRenderer content={macro.bug_summary || "暂无"} compact />
        </section>
      </div>
    </section>
  );
};

export default MacroAnalysisPanel;
