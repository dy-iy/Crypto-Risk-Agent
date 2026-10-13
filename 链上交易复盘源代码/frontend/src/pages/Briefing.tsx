import React from "react";
import { useNavigate } from "react-router-dom";
import { Button, Layout, Space, Tag, Typography } from "antd";
import { ArrowLeft, Bot, Braces, CheckCircle2, Database, FileSearch, GitBranch, ShieldCheck, Sparkles, Wrench } from "lucide-react";

const { Header, Content } = Layout;

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

const Briefing: React.FC = () => {
  const navigate = useNavigate();
  return (
    <Layout className="war-room-shell briefing-shell">
      <Header className="war-room-nav">
        <Space size={10}>
          <Button icon={<ArrowLeft size={16} />} onClick={() => navigate("/")} />
          <Typography.Text className="war-room-brand">AttackPilot 项目介绍</Typography.Text>
        </Space>
        <Space>
          <Button onClick={() => navigate("/tasks")}>任务库</Button>
          <Button type="primary" onClick={() => navigate("/")}>返回平台</Button>
        </Space>
      </Header>
      <Content className="briefing-content">
        <section className="briefing-hero">
          <Tag className="hero-chip" icon={<Sparkles size={13} />}>链上攻击复盘 / 智能体协作 / 证据验证</Tag>
          <Typography.Title>AttackPilot：证据驱动的链上攻击复盘平台</Typography.Title>
          <Typography.Paragraph>
            AttackPilot 将链上取证、执行轨迹分析、漏洞定位和补丁验证组织成一套可复现的攻击复盘流程。
          </Typography.Paragraph>
        </section>

        <section className="briefing-card-grid">
          {valueCards.map((card) => {
            const Icon = card.icon;
            return (
              <div className="briefing-card" key={card.title}>
                <Icon size={24} />
                <strong>{card.title}</strong>
                <span>{card.text}</span>
              </div>
            );
          })}
        </section>

        <section className="briefing-two-col">
          <div className="briefing-block">
            <Typography.Title level={3}>演示顺序</Typography.Title>
            <ol className="briefing-steps">
              <li><strong>从真实事件开始</strong><span>资产已经损失，团队仍需查明根因和证据。</span></li>
              <li><strong>进入复盘工作台</strong><span>选择示例案例，展示完整攻击复盘流程。</span></li>
              <li><strong>说明智能体分工</strong><span>依次展示取证、调试、定位、验证和审查。</span></li>
              <li><strong>以报告收束</strong><span>给出根因、关键证据、修复建议和可追溯日志。</span></li>
            </ol>
          </div>
          <div className="briefing-block skill-block">
            <Typography.Title level={3}>平台接口能力</Typography.Title>
            <div className="skill-list">
              {skillItems.map(([name, desc], index) => (
                <div className="skill-item" key={name}>
                  <span>{index + 1}</span>
                  <code>{name}</code>
                  <small>{desc}</small>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="briefing-pitch">
          <div><Bot size={28} /><strong>产品定位</strong><span>提供可审查的链上风险分析流程，而非单纯生成一份报告。</span></div>
          <div><Braces size={28} /><strong>工程实现</strong><span>结合实时日志、任务持久化、多智能体分析和接口服务。</span></div>
          <div><Wrench size={28} /><strong>知识复用</strong><span>通过漏洞知识库与相似案例检索辅助后续分析。</span></div>
          <div><CheckCircle2 size={28} /><strong>结果可信</strong><span>区分工具事实、交易证据和模型推理，降低错误判断风险。</span></div>
        </section>
      </Content>
    </Layout>
  );
};

export default Briefing;
