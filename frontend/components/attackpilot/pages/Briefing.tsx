"use client";

import React from "react";
import { useNavigate } from "../services/navigation";
import { Button } from "antd";
import { ArrowRight, Bot, Braces, CheckCircle2, Database, FileSearch, GitBranch, ShieldCheck, Sparkles, Wrench } from "lucide-react";
import "../briefing.css";

const valueCards = [
  { title: "实际问题", text: "攻击发生后，团队需要尽快确认关键交易、漏洞逻辑和证据是否可靠。", icon: ShieldCheck },
  { title: "任务输入", text: "选择真实攻击案例，或从 DApp 与交易哈希发起分析。", icon: Database },
  { title: "分析结果", text: "输出攻击路径、资金流、根因、证据链和修复建议。", icon: FileSearch },
  { title: "核心创新", text: "多智能体协作、动态轨迹探索与结构化证据审查。", icon: GitBranch },
];

const skillItems = [
  ["list_dapps", "列出可分析的链上攻击案例"],
  ["create_task", "启动攻击复盘任务"],
  ["get_task", "读取任务状态和最终报告"],
  ["get_macro_analysis", "读取交易与攻击路径摘要"],
  ["get_automated_review", "生成证据审查结果"],
  ["get_task_logs", "读取智能体分析日志"],
];

const demoSteps = [
  { title: "从真实事件开始", text: "资产已经损失，团队仍需查明根因和证据。" },
  { title: "进入复盘工作台", text: "选择示例案例，展示完整攻击复盘流程。" },
  { title: "说明智能体分工", text: "依次展示取证、调试、定位、验证和审查。" },
  { title: "以报告收束", text: "给出根因、关键证据、修复建议和可追溯日志。" },
];

const productItems = [
  { title: "产品定位", text: "提供可审查的链上风险分析流程，而非单纯生成一份报告。", icon: Bot },
  { title: "工程实现", text: "结合实时日志、任务持久化、多智能体分析和接口服务。", icon: Braces },
  { title: "知识复用", text: "通过漏洞知识库与相似案例检索辅助后续分析。", icon: Wrench },
  { title: "结果可信", text: "区分工具事实、交易证据和模型推理，降低错误判断风险。", icon: CheckCircle2 },
];

const Briefing: React.FC = () => {
  const navigate = useNavigate();
  return (
    <main className="ap-page ap-briefing-page">
      <div className="ap-page-content">
        <header className="ap-page-heading ap-briefing-heading">
          <div className="ap-briefing-intro">
            <span className="ap-eyebrow"><Sparkles size={14} aria-hidden="true" />链上攻击复盘 / 智能体协作 / 证据验证</span>
            <h1>AttackPilot：证据驱动的链上攻击复盘平台</h1>
            <p>AttackPilot 将链上取证、执行轨迹分析、漏洞定位和补丁验证组织成一套可复现的攻击复盘流程。</p>
          </div>
          <div className="ap-page-actions ap-briefing-actions">
            <Button onClick={() => navigate("/tasks")}>任务库</Button>
            <Button type="primary" onClick={() => navigate("/")}>返回平台<ArrowRight size={14} aria-hidden="true" /></Button>
          </div>
        </header>

        <section className="ap-briefing-overview" aria-label="项目介绍">
          {valueCards.map((card) => {
            const Icon = card.icon;
            return (
              <article className="ap-briefing-overview-item" key={card.title}>
                <Icon size={20} aria-hidden="true" />
                <h2>{card.title}</h2>
                <p>{card.text}</p>
              </article>
            );
          })}
        </section>

        <div className="ap-briefing-details">
          <section className="ap-briefing-workflow" aria-labelledby="ap-briefing-workflow-title">
            <h2 id="ap-briefing-workflow-title">演示顺序</h2>
            <ol className="ap-briefing-step-list">
              {demoSteps.map((step, index) => (
                <li key={step.title}>
                  <span className="ap-briefing-step-number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                  <div><h3>{step.title}</h3><p>{step.text}</p></div>
                </li>
              ))}
            </ol>
          </section>
          <section className="ap-briefing-api" aria-labelledby="ap-briefing-api-title">
            <h2 id="ap-briefing-api-title">平台接口能力</h2>
            <dl className="ap-briefing-api-list">
              {skillItems.map(([name, desc]) => (
                <div key={name}>
                  <dt><code>{name}</code></dt>
                  <dd>{desc}</dd>
                </div>
              ))}
            </dl>
          </section>
        </div>

        <section className="ap-briefing-principles" aria-label="产品定位">
          {productItems.map((item) => {
            const Icon = item.icon;
            return (
              <article key={item.title}>
                <span className="ap-briefing-principle-icon"><Icon size={20} aria-hidden="true" /></span>
                <div><h2>{item.title}</h2><p>{item.text}</p></div>
              </article>
            );
          })}
        </section>
      </div>
    </main>
  );
};

export default Briefing;
