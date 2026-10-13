import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { App as AntdApp, Button, Checkbox, Input, Layout, Modal, Select, Space, Tag, Typography } from "antd";
import {
  AlertTriangle,
  Bot,
  BookOpen,
  CheckCircle2,
  Coins,
  Database,
  ExternalLink,
  GitBranch,
  KeyRound,
  Library,
  Plus,
  Play,
  Repeat2,
  Scale,
  Search,
  ShieldCheck,
  Signature,
  TrendingUp,
  WalletCards,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import DappContextButton from "../components/DappContextButton";
import ForensicAssistantDrawer from "../components/ForensicAssistantDrawer";
import { createTask, detectTransactions, listDapps, listTasks, listVulnerabilityKnowledge, startTransactionDeepAnalysis } from "../services/api";
import { DappCatalogItem, Task, TaskStatus, TxDetectItem, TxDetectResponse, TxReviewResponse, VulnerabilityTypeKnowledge } from "../types";
import { getDemoTaskIdForDapp } from "../utils/demoSnapshots";
import { DAPP_CONTEXT_MAP } from "../utils/dappMetadata";
import riskPilotLogo from "../assets/riskpilot_logo.png";

const { Header, Content } = Layout;

const demoCases = ["ApeCoin (APE)", "SushiSwap", "Balancer"];

function toFrontendCase(name: string): DappCatalogItem {
  const meta = DAPP_CONTEXT_MAP[name];
  const txHashes = meta?.transaction_hash ?? [];
  return {
    name: meta?.name ?? name,
    cause: meta?.cause ?? null,
    platform: meta?.platform ?? null,
    time: meta?.time ?? null,
    root_cause: meta?.root_cause ?? null,
    report: meta?.report ?? null,
    detection: meta?.detection ?? null,
    disclosure: meta?.disclosure ?? null,
    report_link: meta?.report_link ?? null,
    transaction_hash: txHashes,
    transaction_count: txHashes.length || (name === "ApeCoin (APE)" ? 1 : 3),
    raw_file: `${name}.json`,
    has_processed_analysis: true,
    demo_ready: true,
  };
}

const fallbackCatalog: DappCatalogItem[] = demoCases.map(toFrontendCase);

const attackPath = [
  { zh: "攻击者", en: "Attacker", desc: "借入临时资金", icon: WalletCards, tone: "blue" },
  { zh: "入口交易", en: "Entry Tx", desc: "触发异常分支", icon: Database, tone: "cyan" },
  { zh: "脆弱逻辑", en: "Weak Logic", desc: "协议假设被打破", icon: AlertTriangle, tone: "red" },
  { zh: "状态偏移", en: "State Drift", desc: "价格或余额失真", icon: GitBranch, tone: "amber" },
  { zh: "获利出口", en: "Profit", desc: "兑换、赎回、转移", icon: Coins, tone: "green" },
];
type VulnerabilityLesson = {
  titleZh: string;
  titleEn: string;
  icon: LucideIcon;
  beginnerHook: string;
  mentalModel: string;
  attackSteps: string[];
  traceChecklist: string[];
  repairHints?: string[];
  practice: string;
};

const vulnerabilityIconMap: Record<string, LucideIcon> = {
  oracle_manipulation: TrendingUp,
  reentrancy: Repeat2,
  accounting_drift: Scale,
  access_control: KeyRound,
  flash_loan_amplifier: Zap,
  signature_replay: Signature,
  precision_rounding: Scale,
  business_logic: AlertTriangle,
};

function nonEmptyList(primary?: string[], fallback?: string[]) {
  if (primary && primary.length > 0) return primary;
  if (fallback && fallback.length > 0) return fallback;
  return [];
}

function toVulnerabilityLesson(item: VulnerabilityTypeKnowledge): VulnerabilityLesson {
  const practice = item.practice_sources && item.practice_sources.length > 0
    ? item.practice_sources
        .map((source) => `${source.name}${source.hint ? `：${source.hint}` : ""}`)
        .join(" / ")
    : item.tracepilot_usage || "结合真实攻击复盘，在 AttackPilot 中对照交易、调用和证据链。";

  return {
    titleZh: item.name_zh,
    titleEn: item.name_en,
    icon: vulnerabilityIconMap[item.id] ?? Library,
    beginnerHook: item.one_liner || item.tracepilot_usage || item.name_zh,
    mentalModel: item.mental_model || item.one_liner || item.tracepilot_usage || "先理解协议相信了什么，再看攻击者如何打破这个假设。",
    attackSteps: nonEmptyList(item.attack_steps, item.why_it_happens),
    traceChecklist: nonEmptyList(item.trace_signals, item.repair_hints),
    repairHints: item.repair_hints ?? [],
    practice,
  };
}
const fallbackVulnerabilityLessons: VulnerabilityLesson[] = [
  {
    titleZh: "预言机操纵",
    titleEn: "Oracle Manipulation",
    icon: TrendingUp,
    beginnerHook: "如果协议用一个容易被临时推高或压低的价格做决策，攻击者就能在同一笔交易里先改价格，再薅协议。",
    mentalModel: "把 AMM 池想成一个临时秤。秤上的代币比例会影响价格，如果池子很浅，攻击者用大额 swap 就能短暂把秤拨歪。脆弱协议如果刚好相信这个秤，就会算错抵押、兑换或赎回价值。",
    attackSteps: ["借入闪电贷，获得足够大的临时资金。", "对低流动性池子做大额 swap，短暂扭曲价格。", "调用受害协议中依赖该价格的函数，例如 borrow、redeem、mint。", "反向交易恢复价格，归还闪电贷，留下套利收益。"],
    traceChecklist: ["获利动作前是否有异常大额 swap。", "同一交易内 reserve、price、exchange rate 是否剧烈变化。", "受害合约是否直接读取 AMM spot price。", "利润是否来自被错误估值的借款、铸造或赎回。"],
    practice: "先看 DeFiHackLabs 中 price/oracle 类攻击复现，再用 AttackPilot 对照交易调用和资金流。",
  },
  {
    titleZh: "重入攻击",
    titleEn: "Reentrancy",
    icon: Repeat2,
    beginnerHook: "合约还没把账记完，就把控制权交给别人；别人趁机又回来，重复领钱。",
    mentalModel: "把协议想成柜台。正常流程应该是先登记余额减少，再把钱转出去。重入漏洞的问题是柜台先把钱递出去，攻击者拿到钱的一瞬间又冲回柜台，说自己余额还在。",
    attackSteps: ["攻击合约调用 withdraw、claim 或 callback 类函数。", "受害合约先进行外部转账或回调。", "攻击合约在回调里再次调用受害函数。", "受害合约仍读取旧余额，导致重复提现。"],
    traceChecklist: ["调用树中是否出现同一函数或同一合约的嵌套调用。", "外部 call 是否发生在余额扣减之前。", "同一地址是否多次收到资产转出。", "是否缺少 reentrancy guard 或状态锁。"],
    practice: "先做 Ethernaut Reentrance 关卡，再看 DeFiHackLabs 真实重入案例。",
  },
  {
    titleZh: "会计偏移",
    titleEn: "Accounting Drift",
    icon: Scale,
    beginnerHook: "协议账本里记录的份额或汇率，和真实资产余额对不上，攻击者把这个差价变成收益。",
    mentalModel: "很多金库会用 share 表示你拥有多少份资产。问题出在 asset 和 share 的换算，如果有人能改变真实余额却不改变份额，或者利用舍入边界，就会让兑换比例失真。",
    attackSteps: ["把池子或金库推到极端状态，例如低份额、低余额或高汇率。", "通过 donation、mint、redeem 或 borrow 制造账面偏差。", "在错误汇率下兑换、赎回或借款。", "把内部账本偏差兑现成真实资产。"],
    traceChecklist: ["asset balance、share supply、exchange rate 是否突然跳变。", "关键函数前后是否出现 donation 或非标准转账。", "计算中是否存在向下或向上舍入导致的边界收益。", "协议是否缺少最小流动性或汇率变化限制。"],
    practice: "重点整理 vault、lending、share price 类案例，把攻击前后的不变量写出来。",
  },
  {
    titleZh: "权限控制缺陷",
    titleEn: "Access Control",
    icon: KeyRound,
    beginnerHook: "不该有钥匙的人打开了管理员门。",
    mentalModel: "升级、铸币、暂停、设置预言机、修改策略都属于高危权限。如果函数没有检查调用者身份，或者初始化/签名逻辑有洞，攻击者不需要复杂数学，直接改规则。",
    attackSteps: ["找到缺少 onlyOwner、role 或 signature 检查的敏感函数。", "直接调用特权分支，或初始化未初始化合约。", "修改价格源、策略地址、铸币权限或资金出口。", "转移资产或让协议进入攻击者控制的状态。"],
    traceChecklist: ["调用者是否真的拥有 owner/role 权限。", "函数是否会修改全局参数或资金控制权。", "签名是否校验 nonce、deadline、chain id。", "代理合约或初始化函数是否被二次初始化。"],
    practice: "先做 Ethernaut 中 owner、delegatecall、preservation 类关卡，再回看真实权限事故。",
  },
  {
    titleZh: "闪电贷放大",
    titleEn: "Flash Loan Amplifier",
    icon: Zap,
    beginnerHook: "闪电贷本身不是漏洞，它像放大镜，把很小的协议假设错误放大成一次可盈利攻击。",
    mentalModel: "攻击者不用自带巨额本金，只要在同一笔交易里借钱、利用漏洞、还钱即可。真正危险的不是借钱，而是协议允许临时资金改变价格、份额、投票权或清算条件。",
    attackSteps: ["从借贷协议借入大量临时资产。", "用临时资产改变目标协议的关键状态。", "在状态被扭曲时执行获利动作。", "还清闪电贷，把剩余资产作为利润带走。"],
    traceChecklist: ["交易开头是否有 flashLoan、borrow、swap 类资金入口。", "借入资产是否被用于影响价格、流动性或抵押状态。", "获利和归还是否发生在同一笔交易。", "如果去掉闪电贷，漏洞是否仍然存在但规模变小。"],
    practice: "把 DeFiHackLabs 中带 flashloan 的案例按“借入 -> 放大 -> 获利 -> 归还”四步重画一遍。",
  },
  {
    titleZh: "签名重放",
    titleEn: "Signature Replay",
    icon: Signature,
    beginnerHook: "一张旧授权如果没有过期、没有 nonce、没有链 ID 约束，攻击者可能拿它重复办事。",
    mentalModel: "签名像一张支票。安全支票要写收款人、金额、日期、编号和适用银行。如果少了编号或适用范围，别人可能复印这张支票，到别处或再次使用。",
    attackSteps: ["收集用户或管理员曾经签过的授权消息。", "检查签名是否缺少 nonce、deadline、domain separator 或 chainId。", "在同一合约、另一条链或另一份代理合约中复用签名。", "触发 permit、claim、withdraw 或 admin action。"],
    traceChecklist: ["签名参数里是否有 nonce/deadline/chainId。", "nonce 是否真的被消费并递增。", "domain separator 是否绑定合约地址和链。", "同一签名哈希是否多次出现。"],
    practice: "先补 EIP-712、permit、nonce 概念，再看签名授权类攻击复现。",
  },
  {
    titleZh: "精度与舍入错误",
    titleEn: "Precision / Rounding",
    icon: Scale,
    beginnerHook: "链上没有小数，所有小数都靠整数缩放模拟；舍入方向错了，就可能把零头变成利润。",
    mentalModel: "协议在计算份额、利息、手续费时经常做乘除法。每次除法都要舍入，向上舍入给谁、向下舍入给谁，会决定长期或边界情况下谁占便宜。",
    attackSteps: ["找到金额很小、份额很少或汇率极端的边界状态。", "重复执行 mint/redeem/swap，让舍入误差累积。", "利用精度损失让协议少扣、多发或错误判断阈值。", "把累计误差兑换成真实资产。"],
    traceChecklist: ["关键计算是否有除法、缩放因子或 decimal 转换。", "攻击交易是否重复执行同类小额操作。", "份额、余额或债务是否出现不成比例变化。", "代码是否明确使用向上或向下舍入。"],
    practice: "把 vault share、AMM swap、fee accounting 的公式手算一遍，再对照 trace 中的实际数值。",
  },
  {
    titleZh: "业务逻辑漏洞",
    titleEn: "Business Logic",
    icon: AlertTriangle,
    beginnerHook: "代码没有报错，但协议规则本身被绕过了。",
    mentalModel: "很多 DeFi 攻击不是传统 bug，而是流程设计有洞：先后顺序不对、状态检查漏了、假设用户会诚实操作、或者多个模块组合后产生了意外路径。",
    attackSteps: ["找到协议文档或正常业务流程中的关键约束。", "构造一个不按正常顺序走的交易路径。", "让某个检查在旧状态、错误状态或缺失状态下通过。", "利用通过后的状态执行获利动作。"],
    traceChecklist: ["攻击路径是否绕过了正常 deposit/withdraw/settle 顺序。", "是否存在先使用后验证、先转账后结算的流程。", "多个合约组合时是否丢失了某个前置条件。", "最终利润是否来自规则漏洞而不是单行代码错误。"],
    practice: "读案例时先画正常流程，再画攻击流程，两条路径差异就是漏洞入口。",
  },
];

function normalizeCaseName(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

function getCaseLabel(item: DappCatalogItem, task?: Task) {
  if (task?.status === TaskStatus.COMPLETED) return "已完成分析 / 缓存报告";
  if (task?.status === TaskStatus.RUNNING) return "正在分析";
  const txText = item.transaction_count > 0 ? `${item.transaction_count} 笔交易` : "案例";
  const cause = item.cause || item.root_cause || item.platform || "链上风险";
  return `${txText} / ${cause}`;
}


const defaultPatchHints = [
  "先写清楚漏洞成立的不变量，例如价格不能只看单点、余额扣减必须早于外部调用。",
  "把检查放在最小修复点上，避免直接禁用正常入口或破坏 ABI / storage layout。",
  "用原始 PoC、变体 PoC 和历史正常交易一起回归，确认不是只让脚本 revert。",
];
const learningLinks = [
  { label: "Ethernaut", href: "https://ethernaut.openzeppelin.com/", desc: "Solidity / EVM 闯关练习" },
  { label: "DeFiHackLabs", href: "https://github.com/SunWeb3Sec/DeFiHackLabs", desc: "真实 DeFi 攻击复现" },
];

const sampleAttackHash = "0xeb8c3bebed11e2e4fcd30cbfc2fb3c55c4ca166003c7f7d319e78eaab9747098";
const LAST_TX_REVIEW_HASH_KEY = "attackpilot:last-tx-review-hash";
const TX_HASH_RE = /0x[a-fA-F0-9]{64}/g;

const capabilityCards = [
  { id: "attack_detection", label: "筛交易", desc: "从交易列表找可疑入口" },
  { id: "fault_localization", label: "查根因", desc: "定位漏洞函数和规则问题" },
  { id: "rag_retrieval", label: "看相似案例", desc: "参考历史攻击和修复模式" },
  { id: "patch_verification", label: "验补丁", desc: "重放攻击检查修复效果" },
];

const analysisModules = [
  { id: "attack_detection", label: "攻击检测", desc: "筛出可疑交易" },
  { id: "fault_localization", label: "故障定位", desc: "定位根因函数" },
  { id: "patch_generation", label: "补丁生成", desc: "生成修复建议" },
  { id: "patch_verification", label: "补丁验证", desc: "重放验证修复" },
];

function modulesForRequest(modules: string[]) {
  const expanded = new Set(modules);
  if (expanded.has("fault_localization")) expanded.add("rag_retrieval");
  if (expanded.has("patch_verification")) expanded.add("patch_generation");
  return Array.from(expanded);
}

function parseTxHashes(value: string) {
  const matches = value.match(TX_HASH_RE) ?? [];
  return Array.from(new Set(matches.map((item) => item.toLowerCase())));
}

function detectionItems(response: TxDetectResponse | null): TxDetectItem[] {
  if (!response) return [];
  return [
    ...response.attack_candidates,
    ...response.auxiliary_candidates,
    ...response.unrelated_candidates,
  ];
}

function getRiskTagColor(level: string) {
  if (level === "high") return "red";
  if (level === "medium") return "orange";
  if (level === "low") return "green";
  return "gold";
}

function getRiskText(level: string) {
  if (level === "high") return "高风险线索";
  if (level === "medium") return "可疑线索";
  if (level === "low") return "低风险/信息";
  return "待取证";
}

const LandingWarRoom: React.FC = () => {
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const [catalog, setCatalog] = useState<DappCatalogItem[]>(fallbackCatalog);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [vulnerabilityLessons, setVulnerabilityLessons] = useState<VulnerabilityLesson[]>(fallbackVulnerabilityLessons);
  const [activeVuln, setActiveVuln] = useState(fallbackVulnerabilityLessons[0].titleEn);
  const [knowledgeSource, setKnowledgeSource] = useState<"api" | "fallback">("fallback");
  const [txHash, setTxHash] = useState(() => {
    try {
      return window.localStorage.getItem(LAST_TX_REVIEW_HASH_KEY) || sampleAttackHash;
    } catch {
      return sampleAttackHash;
    }
  });
  const [txRows, setTxRows] = useState<string[]>(() => {
    try {
      return [window.localStorage.getItem(LAST_TX_REVIEW_HASH_KEY) || sampleAttackHash];
    } catch {
      return [sampleAttackHash];
    }
  });
  const [selectedModules, setSelectedModules] = useState<string[]>(["attack_detection", "fault_localization", "patch_generation", "patch_verification"]);
  const [txDetection, setTxDetection] = useState<TxDetectResponse | null>(null);
  const [txDetectLoading, setTxDetectLoading] = useState(false);
  const [txReview] = useState<TxReviewResponse | null>(null);
  const [deepAnalysisLoading, setDeepAnalysisLoading] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [caseModalOpen, setCaseModalOpen] = useState(false);
  const [selectedDapps, setSelectedDapps] = useState<string[]>([]);
  const [caseCreateLoading, setCaseCreateLoading] = useState(false);
  const [dappCatalogLoading, setDappCatalogLoading] = useState(false);
  const [dappCatalogError, setDappCatalogError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setDappCatalogLoading(true);
    listDapps()
      .then((response) => {
        if (cancelled) return;
        setCatalog(response.items);
        setDappCatalogError("");
      })
      .catch(() => {
        if (cancelled) return;
        setCatalog(fallbackCatalog);
        setDappCatalogError("后端案例库暂不可用，正在使用前端内置案例。");
      })
      .finally(() => {
        if (!cancelled) setDappCatalogLoading(false);
      });

    listTasks(true)
      .then((items) => {
        if (!cancelled) setTasks(items);
      })
      .catch(() => setTasks([]));

    listVulnerabilityKnowledge()
      .then((response) => {
        if (cancelled) return;
        const lessons = response.items.map(toVulnerabilityLesson).filter((item) => item.attackSteps.length > 0);
        if (lessons.length === 0) return;
        setVulnerabilityLessons(lessons);
        setKnowledgeSource("api");
        setActiveVuln((current) => lessons.some((item) => item.titleEn === current) ? current : lessons[0].titleEn);
      })
      .catch(() => setKnowledgeSource("fallback"));

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(LAST_TX_REVIEW_HASH_KEY, txHash);
    } catch {
      // Ignore localStorage failures in private mode or quota pressure.
    }
  }, [txHash]);

  const txHashes = useMemo(() => {
    const parsed = txRows.flatMap((value) => parseTxHashes(value));
    return Array.from(new Set(parsed));
  }, [txRows]);

  const recommendedTxHashes = useMemo(() => {
    if (txDetection?.recommended_tx_hashes?.length) return txDetection.recommended_tx_hashes;
    return txHashes;
  }, [txDetection, txHashes]);

  const taskByDapp = useMemo(() => {
    const map = new Map<string, Task>();
    for (const name of demoCases) {
      const targetName = normalizeCaseName(name);
      const sameName = tasks.filter((task) => normalizeCaseName(task.dapp_name) === targetName);
      const preferred =
        sameName.find((task) => task.status === TaskStatus.COMPLETED && !task.archived) ??
        sameName.find((task) => task.status === TaskStatus.COMPLETED) ??
        sameName.find((task) => !task.archived) ??
        sameName[0];
      if (preferred) map.set(name, preferred);
    }
    return map;
  }, [tasks]);

  const sushiCase = useMemo(
    () => catalog.find((item) => normalizeCaseName(item.name) === normalizeCaseName("SushiSwap")),
    [catalog],
  );

  const apeCase = useMemo(
    () => catalog.find((item) => normalizeCaseName(item.name) === normalizeCaseName("ApeCoin (APE)")),
    [catalog],
  );

  const dappOptions = useMemo(() => {
    const source = catalog.length > 0 ? catalog : fallbackCatalog;
    return source.map((item) => ({
      label: `${item.name}${item.demo_ready ? " · 可直接演示" : ""}${item.platform ? ` · ${item.platform}` : ""}`,
      value: item.name,
    }));
  }, [catalog]);

  const selectedDappDetail = useMemo(() => {
    if (selectedDapps.length !== 1) return null;
    return catalog.find((item) => item.name === selectedDapps[0]) ?? fallbackCatalog.find((item) => item.name === selectedDapps[0]) ?? null;
  }, [catalog, selectedDapps]);

  const selectedVuln = useMemo(
    () => vulnerabilityLessons.find((item) => item.titleEn === activeVuln) ?? vulnerabilityLessons[0],
    [activeVuln, vulnerabilityLessons],
  );

  const updateTxRow = useCallback((index: number, value: string) => {
    setTxRows((rows) => rows.map((row, rowIndex) => (rowIndex === index ? value : row)));
  }, []);

  const addTxRow = useCallback(() => {
    setTxRows((rows) => [...rows, ""]);
  }, []);

  const removeTxRow = useCallback((index: number) => {
    setTxRows((rows) => (rows.length <= 1 ? [""] : rows.filter((_, rowIndex) => rowIndex !== index)));
  }, []);

  const fillSampleHash = useCallback(() => {
    setTxRows([sampleAttackHash]);
    setTxHash(sampleAttackHash);
  }, []);

  const openCachedDemo = useCallback(
    async (dappName: string) => {
      const targetName = normalizeCaseName(dappName);
      const task =
        taskByDapp.get(dappName) ??
        tasks.find((item) => normalizeCaseName(item.dapp_name) === targetName && item.status === TaskStatus.COMPLETED && !item.archived) ??
        tasks.find((item) => normalizeCaseName(item.dapp_name) === targetName && item.status === TaskStatus.COMPLETED) ??
        tasks.find((item) => normalizeCaseName(item.dapp_name) === targetName && !item.archived) ??
        tasks.find((item) => normalizeCaseName(item.dapp_name) === targetName);
      if (task) {
        navigate(`/tasks/${task.task_id}`);
        return;
      }

      try {
        const created = await createTask({ dapp_name: dappName });
        message.success("已为示例案例创建复盘任务。");
        navigate(`/tasks/${created.task_id}`);
      } catch (error) {
        const demoTaskId = getDemoTaskIdForDapp(dappName);
        if (demoTaskId) {
          message.info("后端暂不可用，已打开前端内置缓存案例。");
          navigate(`/tasks/${demoTaskId}`);
          return;
        }
        const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
        message.error(detail || "暂时无法打开示例案例，请检查后端服务和案例数据。");
      }
    },
    [message, navigate, taskByDapp, tasks],
  );

  const handleCreateCaseTasks = useCallback(async () => {
    if (selectedDapps.length === 0) {
      message.warning("请先选择一个或多个已发生案例。");
      return;
    }

    setCaseCreateLoading(true);
    try {
      const created: Task[] = [];
      for (const dappName of selectedDapps) {
        created.push(await createTask({ dapp_name: dappName }));
      }
      message.success(`已启动 ${created.length} 个案例复盘任务。`);
      setCaseModalOpen(false);
      setSelectedDapps([]);
      navigate(created.length === 1 ? `/tasks/${created[0].task_id}` : "/tasks");
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || "启动案例复盘失败，请检查后端服务。");
    } finally {
      setCaseCreateLoading(false);
    }
  }, [message, navigate, selectedDapps]);

  const handleTxDetect = useCallback(async () => {
    if (!txHashes.length) {
      message.warning("请先粘贴一笔或多笔 0x 开头的交易哈希。");
      return;
    }
    if (!selectedModules.length) {
      message.warning("请至少选择一个分析模块。");
      return;
    }

    setTxDetectLoading(true);
    try {
      setTxHash(txHashes[0]);
      const result = await detectTransactions({
        tx_hashes: txHashes,
        chain: "ethereum",
        modules: modulesForRequest(selectedModules),
      });
      setTxDetection(result);
      if (result.risk_level === "high") {
        message.success("检测到高风险交易候选，可以进入故障定位。");
      } else if (result.risk_level === "medium") {
        message.info("检测到可疑交易，建议结合上下文继续分析。");
      } else {
        message.info("暂未发现明显攻击信号，仍可手动启动分析。");
      }
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || "快速攻击检测失败，请检查后端服务。");
    } finally {
      setTxDetectLoading(false);
    }
  }, [message, selectedModules, txHashes]);

  const handleStartDeepAnalysis = useCallback(async () => {
    const hashes = recommendedTxHashes.length ? recommendedTxHashes : txHashes;
    const value = hashes[0] || txHash.trim();
    if (!value) {
      message.warning("先粘贴一笔交易哈希。");
      return;
    }
    if (!selectedModules.length) {
      message.warning("请至少选择一个分析模块。");
      return;
    }

    setDeepAnalysisLoading(true);
    try {
      setTxHash(value);
      const task = await startTransactionDeepAnalysis({
        tx_hash: value,
        tx_hashes: hashes,
        modules: modulesForRequest(selectedModules),
        chain: "ethereum",
      });
      message.success("深度分析任务已启动。");
      navigate(`/tasks/${task.task_id}`);
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      message.error(detail || "启动深度分析失败，请检查后端服务。");
    } finally {
      setDeepAnalysisLoading(false);
    }
  }, [message, navigate, recommendedTxHashes, selectedModules, txHash, txHashes]);

  const scrollToSection = useCallback((sectionId: string) => {
    document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  useEffect(() => {
    const target = window.location.hash.replace("#", "");
    if (!target) return;
    const timer = window.setTimeout(() => scrollToSection(target), 80);
    return () => window.clearTimeout(timer);
  }, [scrollToSection]);

  const showSupplementalSections = false;

  return (
    <Layout className="landing-v2">
      <Header className="landing-v2-nav">
        <button className="landing-brand" type="button" onClick={() => navigate("/") }>
          <span className="landing-brand-mark"><img src={riskPilotLogo} alt="RiskPilot logo" /></span>
          <span><strong>AttackPilot</strong><small>攻击复盘工作台</small></span>
        </button>
        <Space size={10} className="landing-nav-actions">
          <Button type="text" onClick={() => scrollToSection("tx-review")}>开始分析</Button>
          <Button type="text" onClick={() => navigate("/tasks")}>任务库</Button>
          <Button type="text" onClick={() => navigate("/learning")}>漏洞学习</Button>
          <Button type="primary" icon={<Play size={15} />} onClick={() => openCachedDemo("SushiSwap")}>查看示例案例</Button>
        </Space>
      </Header>

      <Content className="landing-v2-content">
        <section className="landing-stage product-overview-page">
          <div className="stage-network" aria-hidden="true" />
          <div className="stage-copy">
            <Tag className="stage-chip">链上安全复盘</Tag>
            <Typography.Title className="stage-title">链上攻击复盘平台</Typography.Title>
            <Typography.Title level={2} className="stage-subtitle">从交易出发，还原攻击链路、定位根因并生成验证报告。</Typography.Title>
            <Typography.Paragraph className="stage-desc">
              输入单笔或多笔交易，AttackPilot 会调用多智能体协作完成攻击检测、故障定位、相似案例参考和补丁验证。
            </Typography.Paragraph>
            <div className="stage-cta-row">
              <Button type="primary" size="large" icon={<Play size={16} />} onClick={() => scrollToSection("analysis-workbench")}>
                开始一次复盘
              </Button>
              <Button size="large" onClick={() => openCachedDemo("SushiSwap")}>
                查看示例案例
              </Button>
            </div>
          </div>

          <div className="stage-brand-visual" aria-label="AttackPilot">
            <div className="brand-orbit">
              <img src={riskPilotLogo} alt="" aria-hidden="true" />
            </div>
          </div>

          <div className="stage-overview-panel">
            <div className="stage-metric-list">
              <span><strong>$3,700,000,000+</strong>近两年公开链上攻击损失规模</span>
              <span><strong>2,166 起</strong>近两年公开链上攻击事件数量</span>
              <span><strong>$1,500,000,000</strong>Bybit 单次安全事件损失规模</span>
              <span><strong>16.7h → 1.36h</strong>人工复盘与 AttackPilot 平均分析耗时对比</span>
            </div>
            <div className="stage-module-grid">
              {capabilityCards.map((module, index) => (
                <div className="stage-module-card" key={module.id}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{module.label}</strong>
                  <small>{module.desc}</small>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="analysis-workbench-page" id="analysis-workbench">
          <div className="analysis-page-heading">
            <span>开始分析 / 工作台</span>
            <Typography.Title level={2}>开始一次攻击复盘</Typography.Title>
            <Typography.Paragraph>
              粘贴交易哈希，选择需要的功能模块，系统会生成攻击路径、根因证据、相似案例和修复验证报告。
            </Typography.Paragraph>
          </div>

          <div className="analysis-page-grid">
          <div className="hero-action-panel" id="tx-review" aria-label="交易哈希审查">
            <div className="hero-action-title">
              <span>交易输入</span>
              <strong>输入交易哈希</strong>
              <p>一行一笔交易。你可以只填一笔，也可以点“+ 交易”补充同一事件中的多笔交易。</p>
            </div>
            <div className="tx-row-list">
              {txRows.map((value, index) => (
                <div className="tx-row-item" key={`tx-row-${index}`}>
                  <span>{index + 1}</span>
                  <Input
                    className="tx-review-input"
                    value={value}
                    onChange={(event) => updateTxRow(index, event.target.value)}
                    placeholder="0x..."
                    allowClear
                  />
                  <Button aria-label="删除交易" onClick={() => removeTxRow(index)}>删除</Button>
                </div>
              ))}
              <Button className="tx-add-row-btn" icon={<Plus size={15} />} onClick={addTxRow}>
                + 交易
              </Button>
            </div>

            <div className="workflow-module-box">
              <span>选择分析模块</span>
              <Checkbox.Group value={selectedModules} onChange={(value) => setSelectedModules(value.map(String))}>
                {analysisModules.map((module) => (
                  <Checkbox value={module.id} key={module.id}>
                    <strong>{module.label}</strong>
                    <small>{module.desc}</small>
                  </Checkbox>
                ))}
              </Checkbox.Group>
            </div>

            <div className="hero-action-buttons">
              <Button className="tx-detect-primary-btn" type="primary" icon={<Search size={15} />} loading={txDetectLoading} onClick={handleTxDetect}>
                快速攻击检测
              </Button>
              <Button loading={deepAnalysisLoading} onClick={handleStartDeepAnalysis}>
                直接开始分析
              </Button>
              <Button type="link" onClick={fillSampleHash}>填入示例交易</Button>
            </div>

            <div className="quick-case-strip" id="quick-cases">
              <span>想先看结果？</span>
              <div className="quick-case-wide-grid">
                <button className="quick-case-wide" onClick={() => openCachedDemo("SushiSwap")} type="button">
                  <strong>SushiSwap</strong>
                  <small>{sushiCase ? getCaseLabel(sushiCase, taskByDapp.get("SushiSwap")) : "多交易准备 + 路由逻辑缺陷。"}</small>
                </button>
                <button className="quick-case-wide" onClick={() => openCachedDemo("ApeCoin (APE)")} type="button">
                  <strong>ApeCoin (APE)</strong>
                  <small>{apeCase ? getCaseLabel(apeCase, taskByDapp.get("ApeCoin (APE)")) : "缓存复盘案例，可直接查看分析结果。"}</small>
                </button>
              </div>
              <Button className="case-replay-entry-btn" type="primary" ghost onClick={() => setCaseModalOpen(true)}>
                选择已发生案例复盘
              </Button>
            </div>

          </div>
          <aside className="analysis-side-panel">
            <div className="analysis-output-card">
              <span>本次将生成</span>
              <ul>
                <li><GitBranch size={16} />攻击路径图</li>
                <li><Search size={16} />根因证据</li>
                <li><Library size={16} />相似案例参考</li>
                <li><ShieldCheck size={16} />修复验证报告</li>
              </ul>
            </div>
            <div className="analysis-progress-card">
              <span>任务进度预览</span>
              <ol>
                <li className="active">等待输入</li>
                <li>链上数据拉取</li>
                <li>智能体协作分析</li>
                <li>报告生成</li>
              </ol>
            </div>
          </aside>
          </div>
        </section>

        {(txDetection || txReview) ? (
        <section className="tx-review-section" aria-label="交易检测结果">
          <div className="section-kicker tx-review-kicker">
            <div>
              <strong>检测反馈</strong>
              <span>先看命中情况与风险信号，再决定是否进入深度复盘。</span>
            </div>
            <Tag className="tx-review-mode">案例命中 / 链上取证</Tag>
          </div>

          <div className="tx-review-panel">
            {txDetection ? (
              <div className="tx-detect-result">
                <div className="tx-detect-summary">
                  <Tag color={getRiskTagColor(txDetection.risk_level)}>{getRiskText(txDetection.risk_level)}</Tag>
                  <strong>{txDetection.summary}</strong>
                  <span>
                    输入 {txDetection.input_count} 笔，完成检测 {txDetection.analyzed_count} 笔，
                    推荐进入分析 {txDetection.recommended_tx_hashes.length} 笔
                  </span>
                  <div className="tx-detect-summary-actions">
                    <Button type="primary" icon={<Play size={15} />} loading={deepAnalysisLoading} onClick={handleStartDeepAnalysis}>
                      开始复盘
                    </Button>
                    <Button onClick={() => scrollToSection("tx-review")}>继续补充交易</Button>
                  </div>
                </div>
                <div className="tx-detect-grid">
                  {detectionItems(txDetection).slice(0, 8).map((item) => (
                    <article className={`tx-detect-card tx-detect-${item.risk_level}`} key={item.tx_hash}>
                      <div>
                        <Tag color={getRiskTagColor(item.risk_level)}>{item.classification}</Tag>
                        <Typography.Text copyable={{ text: item.tx_hash }} className="text-mono">
                          {item.tx_hash.slice(0, 10)}...{item.tx_hash.slice(-8)}
                        </Typography.Text>
                      </div>
                      <strong>{item.summary}</strong>
                      <p>{item.signals.slice(0, 3).join(" / ") || "暂无明显信号"}</p>
                    </article>
                  ))}
                </div>
              </div>
            ) : null}
            {txReview ? (
              <div className="tx-review-result">
                <div className="tx-review-result-main">
                  <Tag color={getRiskTagColor(txReview.risk_level)}>
                    {txReview.tx_type === "known_attack_case" ? "已知攻击案例" : getRiskText(txReview.risk_level)}
                  </Tag>
                  <strong>{txReview.summary}</strong>
                  <small>{txReview.tx_hash}</small>
                </div>

                <div className="tx-review-queue">
                  <div className="tx-step-card tx-step-primary">
                    <span>P1</span>
                    <strong>{txReview.tx_type === "known_attack_case" ? "打开已知案例" : "启动链上取证"}</strong>
                    <p>
                      {txReview.tx_type === "known_attack_case"
                        ? `已命中 ${txReview.matched_cases[0]?.name || "本地攻击案例"}，可以直接查看复盘报告。`
                        : "本地案例库未命中，需要拉取交易详情、trace、事件日志和资金变化。"}
                    </p>
                    {txReview.matched_cases.length > 0 ? (
                      <div className="tx-review-actions">
                        <Button className="tx-review-action-primary" type="primary" size="middle" onClick={() => openCachedDemo(txReview.matched_cases[0].name)}>打开复盘工作区</Button>
                        <Button className="tx-review-action-secondary" size="middle" loading={deepAnalysisLoading} onClick={handleStartDeepAnalysis}>重新深度分析</Button>
                      </div>
                    ) : (
                      <Button className="tx-review-action-primary" size="middle" type="primary" loading={deepAnalysisLoading} onClick={handleStartDeepAnalysis}>启动深度分析</Button>
                    )}
                  </div>
                  <div className="tx-step-card">
                    <span>P2</span>
                    <strong>查看审查信号</strong>
                    <p>
                      {txReview.signal_details?.length
                        ? txReview.signal_details.slice(0, 3).map((signal) => signal.name).join(" / ")
                        : txReview.signals.slice(0, 3).join(" / ")}
                    </p>
                  </div>
                  <div className="tx-step-card">
                    <span>P3</span>
                    <strong>核对证据来源</strong>
                    <p>{txReview.evidence.map((item) => `${item.title}：${item.source}`).join(" / ")}</p>
                  </div>
                </div>

                <div className="tx-assistant-entry">
                  <div>
                    <strong>需要解释这笔交易吗？</strong>
                    <span>让智能取证助手基于审查信号、案例库和漏洞知识库回答。</span>
                  </div>
                  <Button icon={<Bot size={15} />} onClick={() => setAssistantOpen(true)}>
                    问问取证助手
                  </Button>
                </div>

                {txReview.signal_details?.length > 0 ? (
                  <div className="tx-signal-list">
                    {txReview.signal_details.map((signal) => (
                      <div className={`tx-signal-item tx-signal-${signal.level}`} key={signal.id}>
                        <Tag color={getRiskTagColor(signal.level)}>{getRiskText(signal.level)}</Tag>
                        <strong>{signal.name}</strong>
                        <p>{signal.summary}</p>
                        <small>{signal.evidence}</small>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="tx-review-empty">
                输入交易哈希后，这里会显示案例命中、审查信号和下一步操作。
              </div>
            )}
          </div>
        </section>
        ) : null}

        <ForensicAssistantDrawer
          open={assistantOpen}
          onOpen={() => setAssistantOpen(true)}
          onClose={() => setAssistantOpen(false)}
          scope="tx_review"
          txHash={txReview?.tx_hash || txHash.trim()}
          title="交易取证助手"
        />

        {showSupplementalSections ? (
        <section className="attack-flow-section" aria-label="攻击路径图">
          <div className="section-kicker">
            <strong>它如何复盘攻击</strong>
            <span>从交易入口到获利出口，逐步还原攻击链路。</span>
          </div>
          <div className="attack-path-visual" aria-label="攻击路径图">
            <div className="path-rail" />
            {attackPath.map((node, index) => {
              const Icon = node.icon;
              return (
                <div className={`path-node path-node-${node.tone}`} key={node.en} style={{ gridColumn: index + 1 }}>
                  <span className="path-node-step">0{index + 1}</span>
                  <span className="path-node-icon"><Icon size={19} /></span>
                  <strong>{node.zh}</strong>
                  <small>{node.en}</small>
                  <em>{node.desc}</em>
                </div>
              );
            })}
            <div className="path-note path-note-left"><CheckCircle2 size={15} /> 聚焦关键调用分支</div>
            <div className="path-note path-note-right"><ShieldCheck size={15} /> 区分链上事实与模型推理</div>
          </div>
        </section>
        ) : null}

        {showSupplementalSections ? (
        <section className="tutorial-section" id="vuln-tutorial">
          <div className="section-kicker tutorial-kicker">
            <div>
              <strong>漏洞新手教程</strong>
              <span>不是背术语，而是按“背景直觉 → 攻击步骤 → 链上证据 → 练习路径”学习。</span>
            </div>
            <div className="learning-links">
              <span className="knowledge-source">{knowledgeSource === "api" ? "知识库同步" : "本地内容"}</span>
              {learningLinks.map((link) => (
                <a key={link.href} href={link.href} target="_blank" rel="noreferrer">
                  <span><strong>{link.label}</strong><small>{link.desc}</small></span>
                  <ExternalLink size={14} />
                </a>
              ))}
            </div>
          </div>
          <div className="tutorial-board">
            <div className="tutorial-list">
              {vulnerabilityLessons.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    className={`tutorial-tab ${item.titleEn === selectedVuln.titleEn ? "tutorial-tab-active" : ""}`}
                    key={item.titleEn}
                    onClick={() => setActiveVuln(item.titleEn)}
                    type="button"
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
                <Library size={21} />
                <div>
                  <strong>{selectedVuln.titleZh}</strong>
                  <small>{selectedVuln.titleEn}</small>
                </div>
              </div>
              <p className="tutorial-hook">{selectedVuln.beginnerHook}</p>
              <div className="tutorial-block">
                <span>1. 背景直觉</span>
                <p>{selectedVuln.mentalModel}</p>
              </div>
              <div className="tutorial-columns">
                <div className="tutorial-block">
                  <span>2. 攻击者怎么做</span>
                  <ol>{selectedVuln.attackSteps.map((step) => <li key={step}>{step}</li>)}</ol>
                </div>
                <div className="tutorial-block">
                  <span>3. AttackPilot 怎么查</span>
                  <ol>{selectedVuln.traceChecklist.map((step) => <li key={step}>{step}</li>)}</ol>
                </div>
              </div>
              <div className="tutorial-bottom-grid">
                <div className="tutorial-note">
                  <span>PoC 是什么</span>
                  <p>PoC（Proof of Concept）就是“最小攻击复现”：用一段脚本或一笔交易证明漏洞真的能被触发。看 PoC 不是为了照抄攻击，而是为了确认漏洞成立需要哪些前提。</p>
                </div>
                <div className="tutorial-block tutorial-patch">
                  <span>4. 一般怎么打补丁</span>
                  <ol>{(selectedVuln.repairHints?.length ? selectedVuln.repairHints : defaultPatchHints).map((step) => <li key={step}>{step}</li>)}</ol>
                </div>
              </div>
              <div className="tutorial-practice">
                <BookOpen size={17} />
                <span>{selectedVuln.practice}</span>
              </div>
            </article>
          </div>
        </section>
        ) : null}

      </Content>
      <Modal
        title="已发生案例复盘"
        open={caseModalOpen}
        onOk={handleCreateCaseTasks}
        onCancel={() => {
          setCaseModalOpen(false);
          setSelectedDapps([]);
        }}
        okText="开始复盘"
        cancelText="取消"
        confirmLoading={caseCreateLoading}
        centered
      >
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Typography.Text type="secondary">选择一个或多个已整理攻击案例，系统会为每个案例创建复盘任务。</Typography.Text>
          <Select
            mode="multiple"
            size="large"
            placeholder="选择案例，例如 SushiSwap / ApeCoin"
            style={{ width: "100%" }}
            value={selectedDapps}
            onChange={setSelectedDapps}
            options={dappOptions}
            showSearch
            optionFilterProp="label"
            loading={dappCatalogLoading}
          />
          {dappCatalogError ? <Typography.Text type="warning">{dappCatalogError}</Typography.Text> : null}
          {selectedDappDetail ? (
            <div className="case-catalog-preview">
              <Space size={6} wrap>
                {selectedDappDetail.demo_ready ? <Tag color="green">可直接演示</Tag> : <Tag>原始案例</Tag>}
                {selectedDappDetail.has_processed_analysis ? <Tag color="blue">已有宏观分析</Tag> : null}
                {selectedDappDetail.platform ? <Tag>{selectedDappDetail.platform}</Tag> : null}
                {selectedDappDetail.cause ? <Tag>{selectedDappDetail.cause}</Tag> : null}
              </Space>
              <Typography.Text type="secondary">
                {selectedDappDetail.transaction_count} 笔交易
                {selectedDappDetail.root_cause ? ` · 根因：${selectedDappDetail.root_cause}` : ""}
              </Typography.Text>
            </div>
          ) : null}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <Typography.Text type="secondary">
              可以先查看案例背景知识，再启动复盘任务。
            </Typography.Text>
            <DappContextButton
              dappName={selectedDapps.length === 1 ? selectedDapps[0] : undefined}
              disabled={selectedDapps.length !== 1}
            />
          </div>
        </Space>
      </Modal>
    </Layout>
  );
};

export default LandingWarRoom;
