import React, { useEffect, useMemo, useState } from "react";
import { Button, Layout, Space, Tag, Typography } from "antd";
import {
  AlertTriangle,
  BookOpen,
  ExternalLink,
  KeyRound,
  Library,
  Repeat2,
  Scale,
  Signature,
  TrendingUp,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";
import RagKnowledgePanel from "../components/RagKnowledgePanel";
import { listVulnerabilityKnowledge } from "../services/api";
import { VulnerabilityTypeKnowledge } from "../types";
import riskPilotLogo from "../assets/riskpilot_logo.png";

const { Header, Content } = Layout;

type VulnerabilityLesson = {
  id: string;
  titleZh: string;
  titleEn: string;
  icon: LucideIcon;
  beginnerHook: string;
  mentalModel: string;
  attackSteps: string[];
  traceChecklist: string[];
  repairHints: string[];
  practice: string;
};

const iconMap: Record<string, LucideIcon> = {
  oracle_manipulation: TrendingUp,
  reentrancy: Repeat2,
  accounting_drift: Scale,
  access_control: KeyRound,
  flash_loan_amplifier: Zap,
  signature_replay: Signature,
  precision_rounding: Scale,
  business_logic: AlertTriangle,
};

const fallbackLessons: VulnerabilityLesson[] = [
  {
    id: "oracle_manipulation",
    titleZh: "预言机操纵",
    titleEn: "Oracle Manipulation",
    icon: TrendingUp,
    beginnerHook: "协议相信了可以在同一笔交易内被临时推高或压低的价格。",
    mentalModel: "把 AMM 池想成一杆临时秤。池子越浅，攻击者越容易用大额交易把价格扭歪。如果协议刚好用这杆秤计算借款、赎回或兑换价值，就可能做出错误决策。",
    attackSteps: [
      "借入闪电贷或准备大额临时资金。",
      "对低流动性交易池进行大额 swap，短暂扭曲价格。",
      "调用依赖该价格的脆弱函数，例如 borrow、redeem、mint。",
      "反向交易恢复价格，归还临时资金并保留收益。",
    ],
    traceChecklist: [
      "获利动作前是否出现异常大额 swap。",
      "同一交易内 reserve、price 或 exchange rate 是否剧烈变化。",
      "受害合约是否读取 AMM spot price 或单点价格源。",
      "攻击收益是否来自错误估值下的借款、铸造、赎回或兑换。",
    ],
    repairHints: [
      "使用 TWAP 或多源预言机。",
      "增加流动性阈值和价格变化边界检查。",
      "避免在关键逻辑中直接信任同交易内可操纵价格。",
      "对价格敏感操作增加延迟或二次确认。",
    ],
    practice: "DeFiHackLabs：搜索 oracle、price、twap、spot 等关键词，挑选价格操纵案例。",
  },
  {
    id: "reentrancy",
    titleZh: "重入攻击",
    titleEn: "Reentrancy",
    icon: Repeat2,
    beginnerHook: "合约还没把账记完，就把控制权交给外部地址，攻击者趁机再次进入同一逻辑。",
    mentalModel: "正常流程应该先扣余额，再转钱。重入漏洞的问题是合约先把钱转出去，攻击者在回调中再次调用提款函数，此时合约仍读到旧余额。",
    attackSteps: [
      "攻击合约调用 withdraw、claim 或 callback 类函数。",
      "受害合约先进行外部转账或回调。",
      "攻击合约在回调里再次调用受害函数。",
      "受害合约重复读取旧状态，导致重复提现或重复领取。",
    ],
    traceChecklist: [
      "调用树中是否出现同一函数或同一合约的嵌套调用。",
      "外部 call 是否发生在余额扣减之前。",
      "同一地址是否多次收到资产转出。",
      "是否缺少 reentrancy guard 或状态锁。",
    ],
    repairHints: [
      "遵循 checks-effects-interactions。",
      "先更新内部状态，再执行外部调用。",
      "对敏感入口增加 ReentrancyGuard。",
      "将提款设计成 pull payment 模式。",
    ],
    practice: "Ethernaut：先做 Reentrance 关卡，再对照 DeFiHackLabs 中的真实重入案例。",
  },
  {
    id: "accounting_drift",
    titleZh: "会计偏移",
    titleEn: "Accounting Drift",
    icon: Scale,
    beginnerHook: "协议内部记录的份额、债务或汇率与真实资产余额发生偏离。",
    mentalModel: "很多金库用 share 表示用户拥有多少份资产。若有人能改变真实余额但不改变份额，或利用舍入边界，就会让兑换比例失真。",
    attackSteps: [
      "把池子或金库推到低份额、低余额或高汇率的边界状态。",
      "通过 donation、mint、redeem 或 borrow 制造账面偏差。",
      "在错误汇率下兑换、赎回或借款。",
      "把内部账本偏差兑现成真实资产。",
    ],
    traceChecklist: [
      "asset balance、share supply、exchange rate 是否突然跳变。",
      "关键函数前后是否出现 donation 或非标准转账。",
      "计算中是否存在舍入方向导致的边界收益。",
      "协议是否缺少最小流动性或汇率变化限制。",
    ],
    repairHints: [
      "增加最小流动性和最小份额约束。",
      "把真实余额变化和份额变化放在同一不变量下检查。",
      "明确处理 donation、fee-on-transfer 等非标准资产行为。",
      "对汇率跳变设置保护阈值。",
    ],
    practice: "整理 vault、lending、share price 类案例，把攻击前后的不变量写出来。",
  },
  {
    id: "access_control",
    titleZh: "权限控制缺陷",
    titleEn: "Access Control",
    icon: KeyRound,
    beginnerHook: "敏感函数被不该拥有权限的人调用。",
    mentalModel: "升级、铸币、暂停、设置预言机、修改策略都属于高危权限。如果函数缺少身份检查，或初始化、签名、代理逻辑有问题，攻击者可以直接改规则。",
    attackSteps: [
      "找到缺少 onlyOwner、role 或 signature 检查的敏感函数。",
      "直接调用特权分支，或利用未初始化合约。",
      "修改价格源、策略地址、铸币权限或资金出口。",
      "转移资产或让协议进入攻击者控制的状态。",
    ],
    traceChecklist: [
      "调用者是否真的拥有 owner 或 role 权限。",
      "函数是否会修改全局参数或资金控制权。",
      "签名是否校验 nonce、deadline、chain id。",
      "代理合约或初始化函数是否被二次初始化。",
    ],
    repairHints: [
      "为敏感函数补齐权限检查。",
      "初始化函数只允许执行一次。",
      "升级和参数修改加入 timelock 或多签。",
      "签名消息绑定 nonce、deadline、chainId 和合约地址。",
    ],
    practice: "Ethernaut：owner、delegatecall、preservation 类关卡适合作为入门练习。",
  },
  {
    id: "flash_loan_amplifier",
    titleZh: "闪电贷放大",
    titleEn: "Flash Loan Amplifier",
    icon: Zap,
    beginnerHook: "闪电贷本身不是漏洞，但会把很小的协议假设错误放大成一次可盈利攻击。",
    mentalModel: "攻击者不用自带巨额本金，只要在同一笔交易里借钱、利用漏洞、还钱即可。真正危险的是协议允许临时资金改变价格、份额、投票权或清算条件。",
    attackSteps: [
      "从借贷协议借入大量临时资产。",
      "用临时资产改变目标协议的关键状态。",
      "在状态被扭曲时执行获利动作。",
      "还清闪电贷，把剩余资产作为利润带走。",
    ],
    traceChecklist: [
      "交易开头是否有 flashLoan、borrow、swap 类资金入口。",
      "借入资产是否被用于影响价格、流动性或抵押状态。",
      "获利和归还是否发生在同一笔交易。",
      "如果去掉闪电贷，漏洞是否仍然存在但规模变小。",
    ],
    repairHints: [
      "不要把同交易内临时状态当作长期可信状态。",
      "对价格、份额和投票权加入时间窗口。",
      "对大额状态跳变设置保护阈值。",
      "把核心安全判断绑定到更稳定的数据源。",
    ],
    practice: "把 DeFiHackLabs 中带 flashloan 的案例按“借入 -> 放大 -> 获利 -> 归还”四步重画一遍。",
  },
  {
    id: "signature_replay",
    titleZh: "签名重放",
    titleEn: "Signature Replay",
    icon: Signature,
    beginnerHook: "旧授权如果缺少 nonce、过期时间或域隔离，攻击者可能重复使用它。",
    mentalModel: "签名像一张支票。安全支票要写收款人、金额、日期、编号和适用范围。少了编号或范围，别人就可能复印这张支票再次使用。",
    attackSteps: [
      "收集用户或管理员曾经签过的授权消息。",
      "检查签名是否缺少 nonce、deadline、domain separator 或 chainId。",
      "在同一合约、另一条链或另一份代理合约中复用签名。",
      "触发 permit、claim、withdraw 或 admin action。",
    ],
    traceChecklist: [
      "签名参数里是否有 nonce、deadline、chainId。",
      "nonce 是否真的被消费并递增。",
      "domain separator 是否绑定合约地址和链。",
      "同一签名哈希是否多次出现。",
    ],
    repairHints: [
      "采用 EIP-712 域隔离。",
      "每个签名必须消费 nonce。",
      "签名加入 deadline 和 chainId。",
      "避免跨合约、跨链复用同一授权结构。",
    ],
    practice: "先补 EIP-712、permit、nonce 概念，再看签名授权类攻击复现。",
  },
  {
    id: "business_logic",
    titleZh: "业务逻辑漏洞",
    titleEn: "Business Logic",
    icon: AlertTriangle,
    beginnerHook: "代码没有报错，但协议规则本身被绕过了。",
    mentalModel: "很多 DeFi 攻击不是传统 bug，而是流程设计有洞：先后顺序不对、状态检查漏了、假设用户会诚实操作，或多个模块组合后产生意外路径。",
    attackSteps: [
      "找到协议正常业务流程中的关键约束。",
      "构造一个不按正常顺序走的交易路径。",
      "让某个检查在旧状态、错误状态或缺失状态下通过。",
      "利用通过后的状态执行获利动作。",
    ],
    traceChecklist: [
      "攻击路径是否绕过正常 deposit、withdraw、settle 顺序。",
      "是否存在先使用后验证、先转账后结算的流程。",
      "多个合约组合时是否丢失某个前置条件。",
      "最终利润是否来自规则漏洞，而不是单行代码错误。",
    ],
    repairHints: [
      "把业务不变量写成显式检查。",
      "检查所有跨合约组合入口。",
      "避免在流程中间暴露可被利用的中间状态。",
      "为关键状态转换补充回归用例。",
    ],
    practice: "读案例时先画正常流程，再画攻击流程，两条路径差异就是漏洞入口。",
  },
];

const learningLinks = [
  { label: "Ethernaut", href: "https://ethernaut.openzeppelin.com/", desc: "Solidity / EVM 闯关练习" },
  { label: "DeFiHackLabs", href: "https://github.com/SunWeb3Sec/DeFiHackLabs", desc: "真实 DeFi 攻击复现" },
];

function firstList(primary?: string[], fallback?: string[]) {
  if (primary && primary.length > 0) return primary;
  if (fallback && fallback.length > 0) return fallback;
  return [];
}

function toLesson(item: VulnerabilityTypeKnowledge): VulnerabilityLesson {
  const base = fallbackLessons.find((lesson) => lesson.id === item.id);
  const practice = item.practice_sources?.length
    ? item.practice_sources.map((source) => `${source.name}${source.hint ? `：${source.hint}` : ""}`).join(" / ")
    : base?.practice || item.tracepilot_usage || "结合真实案例和 AttackPilot 复盘结果理解攻击路径。";

  return {
    id: item.id,
    titleZh: item.name_zh || base?.titleZh || item.id,
    titleEn: item.name_en || base?.titleEn || item.id,
    icon: iconMap[item.id] ?? base?.icon ?? Library,
    beginnerHook: item.one_liner || base?.beginnerHook || item.tracepilot_usage || item.name_zh,
    mentalModel: item.mental_model || base?.mentalModel || item.one_liner || "先理解协议相信了什么，再看攻击者如何打破这个假设。",
    attackSteps: firstList(item.attack_steps, base?.attackSteps),
    traceChecklist: firstList(item.trace_signals, base?.traceChecklist),
    repairHints: firstList(item.repair_hints, base?.repairHints),
    practice,
  };
}

const LearningCenter: React.FC = () => {
  const navigate = useNavigate();
  const [lessons, setLessons] = useState<VulnerabilityLesson[]>(fallbackLessons);
  const [activeId, setActiveId] = useState(fallbackLessons[0].id);

  useEffect(() => {
    let cancelled = false;
    listVulnerabilityKnowledge()
      .then((response) => {
        if (cancelled || response.items.length === 0) return;
        const nextLessons = response.items.map(toLesson);
        setLessons(nextLessons);
        setActiveId((current) => (nextLessons.some((item) => item.id === current) ? current : nextLessons[0].id));
      })
      .catch(() => setLessons(fallbackLessons));
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedLesson = useMemo(
    () => lessons.find((lesson) => lesson.id === activeId) ?? lessons[0],
    [activeId, lessons],
  );
  const SelectedIcon = selectedLesson.icon;
  const ragQuery = `${selectedLesson.titleEn} ${selectedLesson.titleZh} ${selectedLesson.beginnerHook}`;

  return (
    <Layout className="learning-page">
      <Header className="landing-v2-nav">
        <button className="landing-brand" type="button" onClick={() => navigate("/")}>
          <span className="landing-brand-mark"><img src={riskPilotLogo} alt="AttackPilot logo" /></span>
          <span><strong>AttackPilot</strong><small>漏洞学习中心</small></span>
        </button>
        <Space size={10} className="landing-nav-actions">
          <Button type="text" onClick={() => navigate("/")}>返回首页</Button>
          <Button type="text" onClick={() => navigate("/tasks")}>任务库</Button>
        </Space>
      </Header>

      <Content className="learning-page-content">
        <section className="learning-page-hero">
          <Tag className="stage-chip">漏洞教程</Tag>
          <Typography.Title>按攻击路径理解漏洞</Typography.Title>
          <Typography.Paragraph>
            不是背术语，而是按“背景直觉 → 攻击步骤 → 链上证据 → 练习路径”学习。先理解攻击为什么成立，再回到真实交易里核对证据。
          </Typography.Paragraph>
          <div className="learning-links">
            {learningLinks.map((link) => (
              <a key={link.label} href={link.href} target="_blank" rel="noreferrer">
                <strong>{link.label}</strong>
                <small>{link.desc}</small>
                <ExternalLink size={15} />
              </a>
            ))}
          </div>
        </section>

        <section className="tutorial-section" id="vuln-tutorial">
          <div className="tutorial-board">
            <div className="tutorial-list">
              {lessons.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={`tutorial-tab ${item.id === selectedLesson.id ? "tutorial-tab-active" : ""}`}
                    onClick={() => setActiveId(item.id)}
                  >
                    <span className="tutorial-tab-icon"><Icon size={16} /></span>
                    <strong>{item.titleZh}</strong>
                    <small>{item.titleEn}</small>
                    <span>{item.beginnerHook}</span>
                  </button>
                );
              })}
            </div>

            <article className="tutorial-detail">
              <div className="tutorial-title">
                <span className="tutorial-tab-icon"><SelectedIcon size={18} /></span>
                <div>
                  <strong>{selectedLesson.titleZh}</strong>
                  <small>{selectedLesson.titleEn}</small>
                </div>
              </div>

              <p className="tutorial-hook">{selectedLesson.beginnerHook}</p>

              <div className="tutorial-block">
                <span>1. 背景直觉</span>
                <p>{selectedLesson.mentalModel}</p>
              </div>

              <div className="tutorial-columns">
                <div className="tutorial-block">
                  <span>2. 攻击者怎么做</span>
                  <ol>
                    {selectedLesson.attackSteps.map((step) => <li key={step}>{step}</li>)}
                  </ol>
                </div>
                <div className="tutorial-block">
                  <span>3. AttackPilot 怎么查</span>
                  <ol>
                    {selectedLesson.traceChecklist.map((step) => <li key={step}>{step}</li>)}
                  </ol>
                </div>
              </div>

              <div className="tutorial-bottom-grid">
                <div className="tutorial-note">
                  <span>PoC 是什么</span>
                  <p>PoC（Proof of Concept）就是“最小攻击复现”：用一段脚本或一笔交易证明漏洞真的能被触发。看 PoC 不是为了照抄攻击，而是为了确认漏洞成立需要哪些前提。</p>
                </div>
                <div className="tutorial-block tutorial-patch">
                  <span>4. 一般怎么打补丁</span>
                  <ol>
                    {selectedLesson.repairHints.map((hint) => <li key={hint}>{hint}</li>)}
                  </ol>
                </div>
              </div>

              <div className="tutorial-practice">
                <BookOpen size={16} />
                <span>{selectedLesson.practice}</span>
              </div>
            </article>
          </div>
        </section>

        <RagKnowledgePanel
          compact
          defaultQuery={ragQuery}
          title="相似案例参考"
          subtitle="从历史漏洞、真实案例和复现材料中检索相似攻击模式，辅助理解当前漏洞。"
        />
      </Content>
    </Layout>
  );
};

export default LearningCenter;
