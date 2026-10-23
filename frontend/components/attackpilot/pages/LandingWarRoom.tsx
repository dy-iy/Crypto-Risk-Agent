"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { localStore, sessionStore } from "@/lib/browser-storage";
import { useNavigate } from "../services/navigation";
import { Alert, App as AntdApp, Button, Checkbox, Input, Layout, Modal, Select, Space, Tag, Typography } from "antd";
import {
  ArrowRight,
  ArrowUpRight,
  Bot,
  BookOpen,
  GitBranch,
  Library,
  Play,
  Search,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import DappContextButton from "../components/DappContextButton";
import ForensicAssistantDrawer from "../components/ForensicAssistantDrawer";
import { createTask, detectTransactions, errorMessage, getCapabilities, listDapps, listTasks, listVulnerabilityKnowledge, reviewTransaction, startTransactionDeepAnalysis } from "../services/api";
import type { Capabilities } from "../services/api";
import { DappCatalogItem, Task, TaskStatus, TxDetectItem, TxDetectResponse, TxReviewResponse } from "../types";
import { useAttackPilotIdentity } from "../context";
import { DAPP_CONTEXT_MAP, getDappMetadata } from "../utils/dappMetadata";
import { buildDeepAnalysisRequest, normalizeAnalysisModules as modulesForRequest } from "../utils/requestPayloads";
const { Content } = Layout;

const demoCases = ["ApeCoin (APE)", "SushiSwap", "Balancer"];

function toFrontendCase(name: string): DappCatalogItem {
  const meta = DAPP_CONTEXT_MAP[name];
  const txHashes = meta?.transaction_hash ?? [];
  return {
    name: meta?.name ?? name,
    cause: meta?.cause_zh ?? meta?.cause ?? null,
    platform: meta?.platform ?? null,
    time: meta?.time ?? null,
    root_cause: meta?.root_cause_zh ?? meta?.root_cause ?? null,
    report: meta?.report_zh ?? meta?.report ?? null,
    detection: meta?.detection ?? null,
    disclosure: meta?.disclosure ?? null,
    report_link: meta?.report_link ?? null,
    transaction_hash: txHashes,
    transaction_count: txHashes.length,
    raw_file: `${name}.json`,
    has_processed_analysis: false,
    demo_ready: false,
  };
}

const fallbackCatalog: DappCatalogItem[] = demoCases.map(toFrontendCase);

const fallbackVulnerabilityCount = 8;

function normalizeCaseName(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

function getPublicCaseTasks(tasks: Task[]) {
  const cases = new Map<string, Task>();
  const completed = tasks
    .filter(task => task.is_demo === true && task.status === TaskStatus.COMPLETED && !task.archived)
    .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
      || left.task_id.localeCompare(right.task_id));
  for (const task of completed) {
    const name = normalizeCaseName(task.dapp_name);
    if (!cases.has(name)) cases.set(name, task);
  }
  return cases;
}

function getCaseLabel(item: DappCatalogItem, task?: Task) {
  if (task?.status === TaskStatus.COMPLETED) return "已完成分析 / 缓存报告";
  if (task?.status === TaskStatus.RUNNING) return "正在分析";
  const txText = item.transaction_count > 0 ? `${item.transaction_count} 笔交易` : "案例";
  const cause = item.cause || item.root_cause || item.platform || "链上风险";
  return `${txText} / ${cause}`;
}


const sampleChains: Record<string, string> = { Ethereum: "ethereum", BNBChain: "bnbchain", BSC: "bnbchain" };
const LAST_TX_REVIEW_HASH_KEY = "cryptorisk.attackpilot-input";
const LOGIN_DRAFT_KEY = "cryptorisk.attackpilot-login-draft";
const TX_HASH_RE = /^0x[a-fA-F0-9]{64}$/;

function subscribeToSavedInput(onChange: () => void) {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

function readLoginDraft() {
  const value = sessionStore.getItem(LOGIN_DRAFT_KEY);
  if (!value) return "";
  try {
    const saved: unknown = JSON.parse(value);
    if (saved && typeof saved === "object" && "origin" in saved && saved.origin === "guest" && "expiresAt" in saved && typeof saved.expiresAt === "number" && saved.expiresAt > Date.now()) return value;
  } catch { /* 忽略损坏的临时登录草稿。 */ }
  return "";
}

function parseSavedInput(value: string): { rows: string[]; chain: string; modules: string[] } {
  try {
    const saved: unknown = JSON.parse(value);
    if (saved && typeof saved === "object" && "rows" in saved && "chain" in saved && Array.isArray(saved.rows) && saved.rows.every(row => typeof row === "string")) {
      const modules = "modules" in saved && Array.isArray(saved.modules) ? saved.modules.filter((module): module is string => typeof module === "string" && analysisModules.some(item => item.id === module)) : analysisModules.map(module => module.id);
      return { rows: saved.rows.length ? saved.rows : [""], chain: saved.chain === "bnbchain" ? "bnbchain" : "ethereum", modules: modulesForRequest(modules) };
    }
  } catch { /* 首次访问或旧草稿无效时从空白输入开始。 */ }
  return { rows: [""], chain: "ethereum", modules: analysisModules.map(module => module.id) };
}

const analysisModules = [
  { id: "attack_detection", label: "攻击检测", desc: "筛出可疑交易" },
  { id: "fault_localization", label: "故障定位", desc: "定位根因函数" },
  { id: "rag_retrieval", label: "知识检索", desc: "参考历史攻击案例" },
  { id: "patch_generation", label: "补丁生成", desc: "生成修复建议" },
  { id: "patch_verification", label: "补丁验证", desc: "重放验证修复" },
];

function parseTxHashes(value: string) {
  return value.split(/[\s,，;；]+/).filter(Boolean).map((item) => item.toLowerCase());
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
  const { userId, onLogin } = useAttackPilotIdentity();
  const [catalog, setCatalog] = useState<DappCatalogItem[]>(fallbackCatalog);
  const [tasks, setTasks] = useState<Task[]>([]);
  const demoNavigationRef = useRef(0);
  const submissionRef = useRef<AbortController | null>(null);
  const [vulnerabilityCount, setVulnerabilityCount] = useState(fallbackVulnerabilityCount);
  const inputStorageKey = `${LAST_TX_REVIEW_HASH_KEY}:${userId || "guest"}`;
  const readSavedInput = useCallback(() => (userId ? readLoginDraft() : "") || localStore.getItem(inputStorageKey) || "", [inputStorageKey, userId]);
  const savedInput = useSyncExternalStore(subscribeToSavedInput, readSavedInput, () => "");
  const savedDraft = useMemo(() => parseSavedInput(savedInput), [savedInput]);
  const [draftRows, setDraftRows] = useState<string[] | null>(null);
  const txRows = draftRows ?? savedDraft.rows;
  const [draftChain, setChain] = useState<string | null>(null);
  const chain = draftChain ?? savedDraft.chain;
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [draftModules, setSelectedModules] = useState<string[] | null>(null);
  const selectedModules = draftModules ?? savedDraft.modules;
  const [txDetection, setTxDetection] = useState<TxDetectResponse | null>(null);
  const [txDetectLoading, setTxDetectLoading] = useState(false);
  const [txReview, setTxReview] = useState<TxReviewResponse | null>(null);
  const [deepAnalysisLoading, setDeepAnalysisLoading] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [caseModalOpen, setCaseModalOpen] = useState(false);
  const [sampleModalOpen, setSampleModalOpen] = useState(false);
  const [selectedSample, setSelectedSample] = useState<string>();
  const sampleCases = useMemo(() => {
    const items = new Map(Object.keys(DAPP_CONTEXT_MAP).map(name => [name, toFrontendCase(name)]));
    catalog.forEach(item => items.set(item.name, item));
    return [...items.values()].filter(item => sampleChains[item.platform ?? ""] && item.transaction_hash.length > 0);
  }, [catalog]);
  const sampleDetail = sampleCases.find(item => item.name === selectedSample);
  const [selectedDapps, setSelectedDapps] = useState<string[]>([]);
  const [caseCreateLoading, setCaseCreateLoading] = useState(false);
  const [dappCatalogLoading, setDappCatalogLoading] = useState(true);
  const [dappCatalogError, setDappCatalogError] = useState("");

  useEffect(() => {
    if (!userId) return;
    const pending = readLoginDraft();
    if (pending) localStore.setItem(inputStorageKey, pending);
    sessionStore.removeItem(LOGIN_DRAFT_KEY);
  }, [inputStorageKey, userId]);

  const requestLogin = useCallback(() => {
    if (!userId && txRows.some(row => row.trim())) {
      sessionStore.setItem(LOGIN_DRAFT_KEY, JSON.stringify({ rows: txRows, chain, modules: selectedModules, origin: "guest", expiresAt: Date.now() + 15 * 60 * 1000 }));
    } else if (!userId) {
      sessionStore.removeItem(LOGIN_DRAFT_KEY);
    }
    onLogin();
  }, [chain, onLogin, selectedModules, txRows, userId]);

  useEffect(() => {
    let cancelled = false;
    listDapps()
      .then((response) => {
        if (cancelled) return;
        setCatalog(response.items.map(item => {
          const metadata = getDappMetadata(item.name);
          return { ...item, cause: metadata?.cause_zh ?? item.cause, root_cause: metadata?.root_cause_zh ?? item.root_cause };
        }));
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

    listTasks()
      .then((items) => {
        if (!cancelled) setTasks(items);
      })
      .catch(() => { if (!cancelled) setTasks([]); });

    getCapabilities().then((value) => { if (!cancelled) setCapabilities(value); }).catch(() => {});

    listVulnerabilityKnowledge()
      .then((response) => {
        if (cancelled) return;
        setVulnerabilityCount(response.items.length);
      })
      .catch(() => { /* 案例服务不可用时保留内置知识分类数量。 */ });

    return () => {
      cancelled = true;
      demoNavigationRef.current += 1;
      submissionRef.current?.abort();
      submissionRef.current = null;
    };
  }, []);

  const txHashes = useMemo(() => {
    const parsed = txRows.flatMap((value) => parseTxHashes(value));
    return Array.from(new Set(parsed));
  }, [txRows]);

  const invalidHashes = txHashes.some((hash) => !TX_HASH_RE.test(hash));
  const validInput = txHashes.length > 0 && txHashes.length <= 50 && !invalidHashes;
  const inputError = txHashes.length > 50 ? "每次最多分析 50 笔交易。" : invalidHashes ? "交易哈希格式不正确：0x 后应有 64 位十六进制字符。" : "";
  const busy = txDetectLoading || deepAnalysisLoading || caseCreateLoading;
  const analysisReady = capabilities?.model.configured && capabilities.chains[chain]?.rpc && capabilities.chains[chain]?.explorer && capabilities.compiler && capabilities.node && capabilities.node_modules && capabilities.tenderly && !capabilities.missing_dependencies.length;

  const clearReview = useCallback(() => { setTxDetection(null); setTxReview(null); }, []);
  const openAssistant = useCallback(() => { if (userId) setAssistantOpen(true); else requestLogin(); }, [userId, requestLogin]);

  const changeModules = useCallback((next: string[]) => {
    const removed = selectedModules.filter(module => !next.includes(module));
    const dependentModules: Record<string, string[]> = {
      rag_retrieval: ["fault_localization", "patch_generation", "patch_verification"],
      fault_localization: ["patch_generation", "patch_verification"],
      patch_generation: ["patch_verification"],
    };
    const blocked = new Set(removed.flatMap(module => dependentModules[module] ?? []));
    setSelectedModules(modulesForRequest(next.filter(module => !blocked.has(module))));
    clearReview();
  }, [clearReview, selectedModules]);

  const publicTaskByDapp = useMemo(() => getPublicCaseTasks(tasks), [tasks]);

  const sushiCase = useMemo(
    () => catalog.find((item) => normalizeCaseName(item.name) === normalizeCaseName("SushiSwap")) ?? toFrontendCase("SushiSwap"),
    [catalog],
  );

  const apeCase = useMemo(
    () => catalog.find((item) => normalizeCaseName(item.name) === normalizeCaseName("ApeCoin (APE)")) ?? toFrontendCase("ApeCoin (APE)"),
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

  const updateTxRow = useCallback((index: number, value: string) => {
    clearReview();
    setDraftRows((rows) => (rows ?? txRows).map((row, rowIndex) => (rowIndex === index ? value : row)));
  }, [clearReview, txRows]);

  const addTxRow = useCallback(() => {
    setDraftRows((rows) => [...(rows ?? txRows), ""]);
  }, [txRows]);

  const removeTxRow = useCallback((index: number) => {
    clearReview();
    setDraftRows((rows) => {
      const current = rows ?? txRows;
      return current.length <= 1 ? [""] : current.filter((_, rowIndex) => rowIndex !== index);
    });
  }, [clearReview, txRows]);

  const fillSampleHash = useCallback(() => {
    if (!sampleDetail || busy) return;
    clearReview();
    setChain(sampleChains[sampleDetail.platform ?? ""]);
    setDraftRows(Array.from(new Set(sampleDetail.transaction_hash)));
    setSampleModalOpen(false);
  }, [busy, clearReview, sampleDetail]);

  const openCachedDemo = useCallback(
    async (dappName: string) => {
      const requestId = ++demoNavigationRef.current;
      const targetName = normalizeCaseName(dappName);
      let task = publicTaskByDapp.get(targetName);
      if (!task) {
        try {
          const items = await listTasks();
          if (requestId !== demoNavigationRef.current) return;
          setTasks(items);
          task = getPublicCaseTasks(items).get(targetName);
        } catch {
          if (requestId === demoNavigationRef.current) message.error("历史报告加载失败，请重试。");
          return;
        }
      }
      if (task) {
        navigate(`/tasks/${task.task_id}`);
        return;
      }

      message.info("此案例暂无可用历史报告。");
    },
    [message, navigate, publicTaskByDapp],
  );

  const handleCreateCaseTasks = useCallback(async () => {
    if (!userId) { requestLogin(); return; }
    if (submissionRef.current) return;
    if (selectedDapps.length === 0) {
      message.warning("请先选择一个或多个已发生案例。");
      return;
    }

    const controller = new AbortController();
    submissionRef.current = controller;
    setCaseCreateLoading(true);
    const created: Task[] = [];
    try {
      for (const dappName of selectedDapps) {
        created.push(await createTask({ dapp_name: dappName, modules: modulesForRequest(selectedModules) }, controller.signal));
        if (controller.signal.aborted) return;
      }
      message.success(`已启动 ${created.length} 个案例复盘任务。`);
      setCaseModalOpen(false);
      setSelectedDapps([]);
      navigate(created.length === 1 ? `/tasks/${created[0].task_id}` : "/tasks");
    } catch (error) {
      if (controller.signal.aborted) return;
      setSelectedDapps(selectedDapps.filter(name => !created.some(task => task.dapp_name === name)));
      setTasks((current) => [...created, ...current]);
      message.error(`${created.length ? `已创建 ${created.length} 个任务，剩余案例创建失败：` : ""}${errorMessage(error)}`);
    } finally {
      if (submissionRef.current === controller) submissionRef.current = null;
      if (!controller.signal.aborted) setCaseCreateLoading(false);
    }
  }, [message, navigate, requestLogin, selectedDapps, selectedModules, userId]);

  const handleTxDetect = useCallback(async () => {
    if (!userId) { requestLogin(); return; }
    if (submissionRef.current) return;
    if (!validInput) {
      message.warning(inputError || "请先粘贴一笔或多笔 0x 开头的交易哈希。");
      return;
    }
    if (!selectedModules.length) {
      message.warning("请至少选择一个分析模块。");
      return;
    }

    const controller = new AbortController();
    submissionRef.current = controller;
    setTxDetectLoading(true);
    try {
      localStore.setItem(inputStorageKey, JSON.stringify({ rows: txHashes, chain, modules: selectedModules }));
      clearReview();
      const payload = buildDeepAnalysisRequest(txHashes, chain, selectedModules);
      const result = txHashes.length === 1 ? await reviewTransaction(payload, controller.signal) : await detectTransactions(payload, controller.signal);
      if (controller.signal.aborted) return;
      if ("attack_candidates" in result) setTxDetection(result);
      else setTxReview(result);
      if (result.risk_level === "high") {
        message.success("检测到高风险交易候选，可以进入故障定位。");
      } else if (result.risk_level === "medium") {
        message.info("检测到可疑交易，建议结合上下文继续分析。");
      } else if (result.risk_level === "low") {
        message.info("暂未发现明显攻击信号，仍可手动启动分析。");
      } else {
        message.warning("当前证据不足，尚不能确认交易风险；可查看取证结果或继续深度分析。");
      }
    } catch (error) {
      if (!controller.signal.aborted) message.error(errorMessage(error));
    } finally {
      if (submissionRef.current === controller) submissionRef.current = null;
      if (!controller.signal.aborted) setTxDetectLoading(false);
    }
  }, [chain, clearReview, inputError, inputStorageKey, message, requestLogin, selectedModules, txHashes, userId, validInput]);

  const handleStartDeepAnalysis = useCallback(async () => {
    if (!userId) { requestLogin(); return; }
    if (submissionRef.current) return;
    if (!validInput) { message.warning(inputError || "先粘贴一笔交易哈希。"); return; }
    if (!selectedModules.length) {
      message.warning("请至少选择一个分析模块。");
      return;
    }

    const controller = new AbortController();
    submissionRef.current = controller;
    setDeepAnalysisLoading(true);
    try {
      localStore.setItem(inputStorageKey, JSON.stringify({ rows: txHashes, chain, modules: selectedModules }));
      const task = await startTransactionDeepAnalysis(buildDeepAnalysisRequest(txHashes, chain, selectedModules), controller.signal);
      if (controller.signal.aborted) return;
      message.success("深度分析任务已启动。");
      navigate(`/tasks/${task.task_id}`);
    } catch (error) {
      if (!controller.signal.aborted) message.error(errorMessage(error));
    } finally {
      if (submissionRef.current === controller) submissionRef.current = null;
      if (!controller.signal.aborted) setDeepAnalysisLoading(false);
    }
  }, [chain, inputError, inputStorageKey, message, navigate, requestLogin, selectedModules, txHashes, userId, validInput]);

  const scrollToSection = useCallback((sectionId: string) => {
    document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  useEffect(() => {
    const target = window.location.hash.replace("#", "");
    if (!target) return;
    const timer = window.setTimeout(() => scrollToSection(target), 80);
    return () => window.clearTimeout(timer);
  }, [scrollToSection]);

  return (
    <Layout className="ap-review-page">
      <Content className="ap-review-content">
        <section className="ap-review-hero" aria-labelledby="ap-review-title">
          <div>
            <span className="ap-review-eyebrow"><ShieldCheck size={15} />链上安全复盘</span>
            <Typography.Title id="ap-review-title">链上攻击复盘平台</Typography.Title>
            <Typography.Paragraph>
              从交易出发，还原攻击链路、定位根因并生成验证报告。
            </Typography.Paragraph>
          </div>
          <Button className="ap-review-demo" icon={<ArrowUpRight size={16} />} onClick={() => openCachedDemo("SushiSwap")}>
            查看示例案例
          </Button>
        </section>

        {capabilities && !analysisReady ? <Alert className="ap-review-service-alert" type="warning" showIcon title="当前网络的深度复盘服务尚未就绪，可以先浏览历史案例与漏洞知识库。" /> : null}

        <section className="ap-review-grid" id="analysis-workbench" aria-label="开始一次攻击复盘">
          <div className="ap-review-main">
            <div className="ap-review-form hero-action-panel" id="tx-review" aria-label="交易哈希审查">
              <div className="ap-review-form-heading">
                <Typography.Title level={2}>开始一次攻击复盘</Typography.Title>
                <p>一行一笔交易。你可以只填一笔，也可以点“+ 交易”补充同一事件中的多笔交易。</p>
              </div>
              <div className="ap-review-network">
                <label htmlFor="attackpilot-chain">所属网络</label>
                <Select id="attackpilot-chain" value={chain} disabled={busy} onChange={value => { setChain(value); clearReview(); }} options={[
                  { value: "ethereum", label: "以太坊 Ethereum" },
                  { value: "bnbchain", label: "币安智能链 BNB Chain" },
                ]} />
              </div>
              <div className="ap-review-field-heading">
                <label htmlFor="ap-tx-hash-0">输入交易哈希</label>
                <Button type="link" disabled={busy} onClick={() => setSampleModalOpen(true)}>填入示例交易</Button>
              </div>
              <div className="tx-row-list">
                {txRows.map((value, index) => (
                  <div className="tx-row-item" key={`tx-row-${index}`}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <Input
                      id={`ap-tx-hash-${index}`}
                      className="tx-review-input"
                      value={value}
                      disabled={busy}
                      aria-label={`第 ${index + 1} 笔交易哈希`}
                      aria-invalid={!!inputError}
                      aria-describedby={inputError ? "ap-tx-input-error" : undefined}
                      onChange={(event) => updateTxRow(index, event.target.value)}
                      placeholder="0x..."
                      allowClear
                    />
                    <Button type="text" icon={<Trash2 size={16} />} aria-label="删除交易" title="删除交易" disabled={busy} onClick={() => removeTxRow(index)} />
                  </div>
                ))}
                <Button className="tx-add-row-btn" type="text" disabled={busy || txRows.length >= 50} onClick={addTxRow}>
                  + 交易
                </Button>
              </div>
              {inputError ? <Typography.Paragraph id="ap-tx-input-error" className="ap-review-input-error" role="alert" type="danger">{inputError}</Typography.Paragraph> : null}

              <div className="workflow-module-box">
                <span id="ap-module-label">选择分析模块</span>
                <Checkbox.Group aria-labelledby="ap-module-label" disabled={busy} value={selectedModules} onChange={(value) => changeModules(value.map(String))}>
                  {analysisModules.map((module) => (
                    <Checkbox value={module.id} key={module.id} disabled={module.id === "attack_detection"}>
                      <span className="ap-review-module-copy"><strong>{module.label}</strong><small>{module.desc}</small></span>
                    </Checkbox>
                  ))}
                </Checkbox.Group>
              </div>

              <div className="hero-action-buttons">
                <Button className="tx-detect-primary-btn" type="primary" icon={<Search size={16} />} disabled={!validInput || busy} loading={txDetectLoading} onClick={handleTxDetect}>
                  快速攻击检测
                </Button>
                <Button disabled={!validInput || busy} loading={deepAnalysisLoading} onClick={handleStartDeepAnalysis}>
                  直接开始分析<ArrowRight size={15} />
                </Button>
              </div>
            </div>
            {!userId ? <div className="ap-review-access">
              <ShieldCheck size={16} aria-hidden="true" />
              <span>公共案例与漏洞知识库可直接浏览，登录后可创建自己的复盘任务并使用取证助手。</span>
              <Button type="link" onClick={requestLogin}>登录</Button>
            </div> : null}
            {(txDetection || txReview) ? (
            <section className="tx-review-section" id="ap-review-results" aria-label="交易检测结果" aria-live="polite">
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
                      {detectionItems(txDetection).map((item) => (
                        <article className={`tx-detect-card tx-detect-${item.risk_level}`} key={item.tx_hash}>
                          <div>
                            <Tag color={getRiskTagColor(item.risk_level)}>{({ attack: "攻击候选", attack_candidate: "攻击候选", auxiliary: "辅助交易", auxiliary_candidate: "辅助交易", unrelated: "无关交易", unknown: "待取证" } as Record<string, string>)[item.classification] || getRiskText(item.risk_level)}</Tag>
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
                      <Button icon={<Bot size={15} />} onClick={openAssistant}>
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
                ) : !txDetection ? (
                  <div className="tx-review-empty">
                    输入交易哈希后，这里会显示案例命中、审查信号和下一步操作。
                  </div>
                ) : null}
              </div>
            </section>
            ) : null}

          </div>

          <aside className="ap-review-aside">
            <section className="ap-review-cases" id="quick-cases" aria-labelledby="ap-review-cases-title">
              <div className="ap-review-aside-heading">
                <span className="ap-review-aside-icon"><BookOpen size={18} /></span>
                <h2 id="ap-review-cases-title">想先看结果？</h2>
              </div>
              <div className="ap-review-case-list">
                <button className="ap-review-case" onClick={() => openCachedDemo("SushiSwap")} type="button">
                  <span className="ap-review-case-name"><strong>SushiSwap</strong><ArrowUpRight size={16} /></span>
                  <small>{getCaseLabel(sushiCase, publicTaskByDapp.get(normalizeCaseName("SushiSwap")))}</small>
                </button>
                <button className="ap-review-case" onClick={() => openCachedDemo("ApeCoin (APE)")} type="button">
                  <span className="ap-review-case-name"><strong>ApeCoin (APE)</strong><ArrowUpRight size={16} /></span>
                  <small>{getCaseLabel(apeCase, publicTaskByDapp.get(normalizeCaseName("ApeCoin (APE)")))}</small>
                </button>
              </div>
              <Button className="ap-review-case-entry" block onClick={() => userId ? setCaseModalOpen(true) : requestLogin()}>
                选择已发生案例复盘<ArrowRight size={15} />
              </Button>
            </section>
            <section className="ap-review-output" aria-labelledby="ap-review-output-title">
              <h2 id="ap-review-output-title">本次将生成</h2>
              <ul>
                <li><GitBranch size={17} />攻击路径图</li>
                {selectedModules.includes("fault_localization") ? <li><Search size={17} />根因证据</li> : null}
                {selectedModules.includes("rag_retrieval") ? <li><Library size={17} />相似案例参考</li> : null}
                {selectedModules.includes("patch_verification") ? <li><ShieldCheck size={17} />修复验证报告</li> : null}
              </ul>
            </section>
          </aside>
        </section>

        <section className="ap-review-metrics" aria-label="平台概览">
          <div><strong>{dappCatalogLoading ? "—" : catalog.length}<small>个</small></strong><span>{dappCatalogError ? "本地案例背景资料" : "案例库收录事件"}</span></div>
          <div><strong>{tasks.filter(task => task.is_demo).length}<small>份</small></strong><span>可直接浏览的公共历史案例</span></div>
          <div><strong>{vulnerabilityCount}<small>类</small></strong><span>常见漏洞知识与修复思路</span></div>
          <div><strong>5<small>个模块</small></strong><span>攻击检测、定位、检索、补丁与验证</span></div>
        </section>

        <ForensicAssistantDrawer
          open={assistantOpen}
          onOpen={openAssistant}
          onClose={() => setAssistantOpen(false)}
          scope="tx_review"
          txHash={txReview?.tx_hash || (validInput ? txHashes[0] : undefined)}
          chain={chain}
          title="交易取证助手"
        />

      </Content>
      <Modal
        title="选择示例交易"
        open={sampleModalOpen}
        onOk={fillSampleHash}
        onCancel={() => setSampleModalOpen(false)}
        okText="填入全部交易"
        cancelText="取消"
        okButtonProps={{ disabled: !sampleDetail || busy }}
        centered
      >
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Typography.Text type="secondary">选择一个案例，一次填入全部交易哈希并切换所属网络。填入会替换当前交易，不会自动开始分析。</Typography.Text>
          <Select
            aria-label="选择示例案例"
            placeholder="搜索案例名称，例如 SushiSwap / ApeCoin"
            style={{ width: "100%" }}
            value={selectedSample}
            onChange={setSelectedSample}
            showSearch
            optionFilterProp="label"
            loading={dappCatalogLoading}
            options={sampleCases.map(item => ({ value: item.name, label: `${item.name} · ${item.platform} · ${item.transaction_hash.length} 笔交易` }))}
          />
          {dappCatalogError ? <Typography.Text type="warning">{dappCatalogError}</Typography.Text> : null}
          {sampleDetail ? (
            <div className="case-catalog-preview">
              <Space size={6} wrap>
                <Tag>{sampleDetail.platform}</Tag>
                {sampleDetail.cause ? <Tag>{sampleDetail.cause}</Tag> : null}
                <Tag>{sampleDetail.transaction_hash.length} 笔交易</Tag>
              </Space>
              <div style={{ maxHeight: 240, overflowY: "auto", marginTop: 12 }}>
                {sampleDetail.transaction_hash.map((hash, index) => (
                  <div key={`${hash}-${index}`} style={{ overflowWrap: "anywhere", marginBottom: 8 }}>
                    <Typography.Text code>{index + 1}. {hash}</Typography.Text>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </Space>
      </Modal>
      <Modal
        title="已发生案例复盘"
        open={caseModalOpen}
        onOk={handleCreateCaseTasks}
        onCancel={() => {
          if (caseCreateLoading) return;
          setCaseModalOpen(false);
          setSelectedDapps([]);
        }}
        okText="开始复盘"
        cancelText="取消"
        confirmLoading={caseCreateLoading}
        closable={!caseCreateLoading}
        maskClosable={!caseCreateLoading}
        cancelButtonProps={{ disabled: caseCreateLoading }}
        okButtonProps={{ disabled: !selectedDapps.length || !!dappCatalogError }}
        centered
      >
        <Space orientation="vertical" size={8} style={{ width: "100%" }}>
          <Typography.Text type="secondary">选择一个或多个已整理攻击案例，系统会为每个案例创建复盘任务。</Typography.Text>
          <Select
            mode="multiple"
            size="large"
            placeholder="选择案例，例如 SushiSwap / ApeCoin"
            style={{ width: "100%" }}
            value={selectedDapps}
            disabled={caseCreateLoading}
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
