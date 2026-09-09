"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { Alert, App as AntdApp, Button, Checkbox, ConfigProvider, Empty, Input, Popconfirm, Select, Space, Spin, Table, Tag, Typography } from "antd";
import { Bot, Search, ShieldCheck } from "lucide-react";
import { AttackPilotIdentity, useAttackPilotIdentity } from "./context";
import { archiveTask, cancelTask, createTask, deleteTask, detectTransactions, errorMessage, getCapabilities, listDapps, listTasks, reviewTransaction, startTransactionDeepAnalysis, unarchiveTask } from "./services/api";
import type { Capabilities } from "./services/api";
import type { DappCatalogItem, Task, TxDetectResponse, TxReviewResponse } from "./types";
import { TaskStatus } from "./types";
import { taskStatusLabel } from "./utils/presentation";
import ForensicAssistantDrawer from "./components/ForensicAssistantDrawer";
import "./attackpilot.css";

const Dashboard = dynamic(() => import("./pages/Dashboard"), { loading: () => <Spin /> });
const Knowledge = dynamic(() => import("./pages/LearningCenter"), { loading: () => <Spin /> });
const modules = [
  ["attack_detection", "攻击检测"], ["fault_localization", "故障定位"], ["rag_retrieval", "知识检索"], ["patch_generation", "补丁生成"], ["patch_verification", "补丁验证"],
] as const;

function expandModules(values: string[]) {
  const selected = new Set(values); selected.add("attack_detection");
  if (selected.has("patch_verification")) selected.add("patch_generation");
  if (selected.has("patch_generation")) selected.add("fault_localization");
  if (selected.has("fault_localization")) selected.add("rag_retrieval");
  return modules.map(([key]) => key).filter(key => selected.has(key));
}

export default function AttackPilotWorkbench({ userId, onLogin }: { userId: string | null; onLogin: () => void }) {
  const pathname = usePathname();
  const section = pathname.includes("/tasks") ? "tasks" : pathname.includes("/knowledge") ? "knowledge" : "review";
  const detail = /^\/attackpilot\/tasks\/[^/]+/.test(pathname);
  return <AttackPilotIdentity.Provider value={{ userId, onLogin }}>
    <section className="attackpilot-root app-theme-light" data-appearance="light" data-ai-selection-ignore>
      <ConfigProvider theme={{ token: { colorPrimary: "#2563eb", fontFamily: "inherit", borderRadius: 8, colorBgBase: "#ffffff", colorTextBase: "#0f172a" } }} getPopupContainer={trigger => trigger?.closest(".attackpilot-root") as HTMLElement || document.querySelector<HTMLElement>(".attackpilot-root") || document.body}>
        <AntdApp>
          <nav className="ap-module-nav" aria-label="AttackPilot 功能导航">
            <span className="ap-brand"><ShieldCheck size={21} /> AttackPilot</span>
            {[ ["review", "/attackpilot", "交易审查"], ["tasks", "/attackpilot/tasks", "任务库"], ["knowledge", "/attackpilot/knowledge", "漏洞知识库"] ].map(([key, href, label]) => <Link key={key} href={href} aria-current={section === key ? "page" : undefined}>{label}</Link>)}
          </nav>
          {detail ? <Dashboard key={`${pathname}:${userId}`} /> : section === "tasks" ? <TaskLibrary key={userId || "guest"} /> : section === "knowledge" ? <Knowledge key={userId || "guest"} /> : <TransactionReview key={userId || "guest"} />}
        </AntdApp>
      </ConfigProvider>
    </section>
  </AttackPilotIdentity.Provider>;
}

function TransactionReview() {
  const router = useRouter();
  const { userId, onLogin } = useAttackPilotIdentity();
  const [chain, setChain] = useState("ethereum");
  const [text, setText] = useState("");
  const [selectedModules, setSelectedModules] = useState<string[]>(modules.map(([key]) => key));
  const [catalog, setCatalog] = useState<DappCatalogItem[]>([]);
  const [selectedCase, setSelectedCase] = useState<string>();
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [result, setResult] = useState<TxReviewResponse | TxDetectResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [assistantOpen, setAssistantOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.all([listDapps(), getCapabilities()]).then(([data, status]) => { if (alive) { setCatalog(data.items); setCapabilities(status); } }).catch(error => { if (alive) setError(errorMessage(error)); });
    return () => { alive = false; };
  }, []);

  const inputHashes = [...new Set(text.split(/[\s,，;；]+/).filter(Boolean))];
  const invalid = inputHashes.filter(hash => !/^0x[\da-fA-F]{64}$/.test(hash));
  const valid = inputHashes.length > 0 && inputHashes.length <= 50 && invalid.length === 0;
  const configReady = capabilities?.model.configured && capabilities.compiler && capabilities.node && capabilities.node_modules && capabilities.tenderly && !capabilities.missing_dependencies.length;

  async function submit(action: "review" | "deep" | "case") {
    if (!userId) { onLogin(); return; }
    setBusy(action); setError("");
    try {
      const payload = { tx_hash: inputHashes[0] || "", tx_hashes: inputHashes, chain, modules: selectedModules };
      if (action === "deep" || action === "case") {
        const task = action === "case" ? await createTask({ dapp_name: selectedCase!, modules: selectedModules }) : await startTransactionDeepAnalysis(payload);
        router.push(`/attackpilot/tasks/${encodeURIComponent(task.task_id)}`);
      } else {
        setResult(inputHashes.length === 1 ? await reviewTransaction(payload) : await detectTransactions(payload));
      }
    } catch (error) { setError(errorMessage(error)); }
    finally { setBusy(""); }
  }

  return <div className="ap-page">
    <div className="ap-intro">
      <div><p className="ap-eyebrow">链上安全事件 · 多智能体取证</p><h2>从交易线索，到可核查的攻击复盘</h2><p>审查可疑交易，追踪关键调用与资金变化，查看漏洞定位和补丁验证依据。</p></div>
      <Button icon={<Bot size={16} />} onClick={() => userId ? setAssistantOpen(true) : onLogin()}>取证助手</Button>
    </div>
    {error && <Alert type="error" showIcon title={error} closable onClose={() => setError("")} />}
    {!userId && <Alert type="info" showIcon title="公共案例与知识库可直接浏览。登录后可创建自己的分析任务。" action={<Button onClick={onLogin}>登录</Button>} />}
    {capabilities && !configReady && <Alert type="warning" showIcon title="实时分析服务尚未就绪，您可以先浏览历史案例和漏洞知识库。" />}
    <div className="ap-review-grid">
      <div className="ap-card">
        <div className="ap-card-heading"><h3>交易输入</h3><Tag>{inputHashes.length} / 50 笔</Tag></div>
        <label htmlFor="ap-chain">所属网络</label>
        <Select id="ap-chain" value={chain} onChange={value => { setChain(value); setResult(null); }} options={[{ value: "ethereum", label: "Ethereum" }, { value: "bnbchain", label: "BNB Chain" }]} style={{ width: "100%" }} />
        <label htmlFor="ap-hashes">交易 Hash</label>
        <Input.TextArea id="ap-hashes" rows={7} value={text} onChange={event => { setText(event.target.value); setResult(null); }} placeholder="粘贴 0x 开头的交易 Hash，多笔交易用换行或逗号分隔" spellCheck={false} />
        {text && !valid && <p role="alert" className="ap-validation">{inputHashes.length > 50 ? "每次最多审查 50 笔交易。" : "请检查 Hash 格式：0x 后应有 64 位十六进制字符。"}</p>}
        <label>分析模块</label>
        <Checkbox.Group value={selectedModules} onChange={values => setSelectedModules(expandModules(values))} options={modules.map(([value, label]) => ({ value, label, disabled: value === "attack_detection" }))} />
        <Space wrap style={{ marginTop: 24 }}>
          <Button icon={<Search size={15} />} loading={busy === "review"} disabled={!valid || !!busy} onClick={() => void submit("review")}>先做交易审查</Button>
          <Button type="primary" loading={busy === "deep"} disabled={!valid || !!busy} onClick={() => void submit("deep")}>启动深度复盘</Button>
        </Space>
      </div>
      <div className="ap-card">
        <h3>从已知案例开始</h3><p>选择历史事件，了解其交易线索，或建立一份新的私有分析。</p>
        <Select aria-label="选择历史案例" showSearch optionFilterProp="label" placeholder="搜索案例名称" style={{ width: "100%" }} value={selectedCase} options={catalog.filter(item => ["Ethereum", "BNBChain", "BSC"].includes(item.platform || "")).map(item => ({ value: item.name, label: `${item.name} · ${item.transaction_count} 笔交易` }))} onChange={value => {
          setSelectedCase(value); const item = catalog.find(item => item.name === value);
          if (item) { setText(item.transaction_hash.join("\n")); setChain(item.platform === "Ethereum" ? "ethereum" : "bnbchain"); setResult(null); }
        }} />
        {selectedCase && <p className="ap-case-context">{catalog.find(item => item.name === selectedCase)?.root_cause || catalog.find(item => item.name === selectedCase)?.cause}</p>}
        <Space wrap style={{ marginTop: 20 }}><Button disabled={!selectedCase || !!busy} loading={busy === "case"} onClick={() => void submit("case")}>重新分析此案例</Button><Link href="/attackpilot/tasks">浏览公共历史报告 →</Link></Space>
        <div className="ap-method"><h4>复盘过程</h4><ol><li>提取交易调用和资金变化</li><li>关联多笔交易，定位关键漏洞函数</li><li>结合历史知识生成修复建议</li><li>按选择执行补丁编译与回放验证</li></ol><p>报告保留证据来源；验证被跳过或失败时会明确标注。</p></div>
      </div>
    </div>
    {result && <div className="ap-card" aria-live="polite"><Space><h3>交易审查结果</h3><Tag color={result.risk_level === "high" ? "error" : "processing"}>{result.risk_level}</Tag></Space><p>{result.summary}</p>
      {"signals" in result ? <ul>{result.signals.map((signal, index) => <li key={index}>{signal}</li>)}</ul> : <div className="ap-candidate-grid">{[["攻击候选", result.attack_candidates], ["辅助交易", result.auxiliary_candidates], ["其他交易", result.unrelated_candidates]].map(([label, items]) => <div key={String(label)}><h4>{String(label)}</h4>{typeof items !== "string" && items.map(item => <p key={item.tx_hash}><code>{item.tx_hash.slice(0, 12)}…</code> {item.summary}</p>)}</div>)}</div>}
      {"live_observation_status" in result && <Tag>链上取证：{result.live_observation_status}</Tag>}
    </div>}
    <ForensicAssistantDrawer key={userId || "guest"} open={assistantOpen} onClose={() => setAssistantOpen(false)} scope={result ? "tx_review" : "general"} txHash={result && inputHashes.length === 1 ? inputHashes[0] : undefined} chain={chain} />
  </div>;
}

function TaskLibrary() {
  const { userId, onLogin } = useAttackPilotIdentity();
  const [items, setItems] = useState<Task[]>([]);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let alive = true;
    const refresh = () => listTasks(includeArchived).then(tasks => { if (alive) { setItems(tasks); setError(""); setLoading(false); } }).catch(error => { if (alive) { setError(errorMessage(error)); setLoading(false); } });
    void refresh(); const timer = setInterval(refresh, 5000);
    return () => { alive = false; clearInterval(timer); };
  }, [includeArchived, revision]);
  const visible = items.filter(task => filter === "all" || (filter === "mine" ? !task.is_demo : task.is_demo));
  async function action(task: Task, kind: "cancel" | "archive" | "delete") {
    try { await (kind === "cancel" ? cancelTask(task.task_id) : kind === "delete" ? deleteTask(task.task_id) : task.archived ? unarchiveTask(task.task_id) : archiveTask(task.task_id)); setRevision(value => value + 1); }
    catch (error) { setError(errorMessage(error)); }
  }
  return <div className="ap-page"><div className="ap-intro"><div><h2>分析任务库</h2><p>公共历史示例保留原始状态；您创建的分析仅本人可见。</p></div><Link href="/attackpilot"><Button type="primary">新建分析</Button></Link></div>
    {error && <Alert type="error" showIcon title={error} />}
    <Space wrap><Select aria-label="任务范围" value={filter} onChange={setFilter} options={[{ value: "all", label: "全部可见任务" }, { value: "demo", label: "公共历史示例" }, { value: "mine", label: "我的任务", disabled: !userId }]} /><Checkbox checked={includeArchived} onChange={event => setIncludeArchived(event.target.checked)}>包含已归档</Checkbox>{!userId && <Button onClick={onLogin}>登录查看我的任务</Button>}</Space>
    <Table rowKey="task_id" loading={loading} dataSource={visible} scroll={{ x: 760 }} pagination={{ pageSize: 10 }} locale={{ emptyText: <Empty description="暂无任务，可从交易审查创建分析" /> }} columns={[
      { title: "案例 / 任务", dataIndex: "dapp_name", render: (name: string, task: Task) => <><Link href={`/attackpilot/tasks/${encodeURIComponent(task.task_id)}`}>{name}</Link><div><Tag color={task.is_demo ? "blue" : "green"}>{task.is_demo ? "公共历史示例" : "我的分析"}</Tag>{task.archived && <Tag>已归档</Tag>}</div></> },
      { title: "状态", dataIndex: "status", render: (status: TaskStatus) => <Tag color={status === TaskStatus.COMPLETED ? "success" : status === TaskStatus.FAILED ? "error" : "default"}>{taskStatusLabel(status)}</Tag> },
      { title: "创建时间", dataIndex: "created_at", render: (date: string) => new Date(date).toLocaleString("zh-CN") },
      { title: "操作", render: (_: unknown, task: Task) => task.is_demo ? <Typography.Text type="secondary">只读示例</Typography.Text> : <Space>{[TaskStatus.PENDING, TaskStatus.RUNNING].includes(task.status) ? <Popconfirm title="取消这项分析？" onConfirm={() => action(task, "cancel")}><Button size="small">取消</Button></Popconfirm> : <><Button size="small" onClick={() => void action(task, "archive")}>{task.archived ? "恢复" : "归档"}</Button><Popconfirm title="删除此任务及其日志？" onConfirm={() => action(task, "delete")}><Button danger size="small">删除</Button></Popconfirm></>}</Space> },
    ]} />
  </div>;
}
