import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { App as AntdApp, Button, Card, Col, Layout, Modal, Row, Select, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  Activity,
  Archive,
  CheckCircle2,
  Eye,
  Home,
  ListChecks,
  Play,
  RefreshCcw,
  Square,
  Undo2,
  XCircle,
} from "lucide-react";
import DappContextButton from "../components/DappContextButton";
import { archiveTask, cancelTask, createTask, listDapps, listTasks, unarchiveTask } from "../services/api";
import { DappCatalogItem, Task, TaskCreateRequest, TaskStatus } from "../types";
import { formatDurationZh, taskStatusLabel } from "../utils/presentation";
import riskPilotLogo from "../assets/riskpilot_logo.png";

const { Header, Content } = Layout;

const dappModules = import.meta.glob("../data/*.json", { eager: true, import: "default" });
const DAPP_OPTIONS = Object.keys(dappModules)
  .map((path) => path.split("/").pop()?.replace(/\.json$/, "") ?? "")
  .filter(Boolean)
  .sort((a, b) => a.localeCompare(b));

function getStatusColor(status: TaskStatus) {
  if (status === TaskStatus.COMPLETED) return "success";
  if (status === TaskStatus.FAILED) return "error";
  if (status === TaskStatus.RUNNING) return "processing";
  return "default";
}

function formatDuration(duration?: number | null) {
  return formatDurationZh(duration);
}

function getErrorMessage(error: unknown, fallback: string) {
  if (typeof error === "object" && error !== null && "response" in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response;
    return response?.data?.detail ?? fallback;
  }
  return fallback;
}

function isRunnableTask(status: TaskStatus) {
  return status === TaskStatus.PENDING || status === TaskStatus.RUNNING;
}

const TaskList: React.FC = () => {
  const { message } = AntdApp.useApp();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [selectedDapps, setSelectedDapps] = useState<string[]>([]);
  const [dappCatalog, setDappCatalog] = useState<DappCatalogItem[]>([]);
  const [dappCatalogLoading, setDappCatalogLoading] = useState(false);
  const [dappCatalogError, setDappCatalogError] = useState("");
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<"all" | TaskStatus>("all");
  const [archiveFilter, setArchiveFilter] = useState<"active" | "archived" | "all">("active");
  const navigate = useNavigate();

  const fetchTasks = useCallback(async () => {
    try {
      setLoading(true);
      setTasks(await listTasks(archiveFilter !== "active"));
    } catch {
      message.error("任务列表加载失败");
    } finally {
      setLoading(false);
    }
  }, [archiveFilter, message]);

  useEffect(() => {
    fetchTasks();
    const interval = setInterval(fetchTasks, 5000);
    return () => clearInterval(interval);
  }, [fetchTasks]);

  useEffect(() => {
    let cancelled = false;
    setDappCatalogLoading(true);
    listDapps()
      .then((catalog) => {
        if (cancelled) return;
        setDappCatalog(catalog.items);
        setDappCatalogError("");
      })
      .catch(() => {
        if (cancelled) return;
        setDappCatalog([]);
        setDappCatalogError("后端案例目录暂不可用，当前使用前端内置案例信息。");
      })
      .finally(() => {
        if (!cancelled) setDappCatalogLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleCreate = async () => {
    if (selectedDapps.length === 0) {
      message.error("请至少选择一个案例");
      return;
    }

    try {
      setLoading(true);
      const created: Task[] = [];
      for (const dappName of selectedDapps) {
        const req: TaskCreateRequest = { dapp_name: dappName };
        created.push(await createTask(req));
      }
      message.success(`已启动 ${created.length} 个复盘任务`);
      setIsModalVisible(false);
      setSelectedDapps([]);
      await fetchTasks();
      if (created.length === 1) {
        navigate(`/tasks/${created[0].task_id}`);
      }
    } catch (error: unknown) {
      message.error(getErrorMessage(error, "复盘任务创建失败"));
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async (task: Task) => {
    try {
      await cancelTask(task.task_id);
      message.success("已提交取消任务请求");
      await fetchTasks();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, "任务取消失败"));
    }
  };

  const handleArchive = async (task: Task) => {
    try {
      await archiveTask(task.task_id);
      message.success("任务已归档");
      await fetchTasks();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, "任务归档失败"));
    }
  };

  const handleRestore = async (task: Task) => {
    try {
      await unarchiveTask(task.task_id);
      message.success("任务已恢复");
      await fetchTasks();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, "任务恢复失败"));
    }
  };

  const filteredTasks = useMemo(() => {
    return tasks.filter((task) => {
      if (archiveFilter === "active" && task.archived) return false;
      if (archiveFilter === "archived" && !task.archived) return false;
      if (statusFilter !== "all" && task.status !== statusFilter) return false;
      return true;
    });
  }, [archiveFilter, statusFilter, tasks]);

  const stats = {
    total: filteredTasks.length,
    running: filteredTasks.filter((task) => task.status === TaskStatus.RUNNING).length,
    completed: filteredTasks.filter((task) => task.status === TaskStatus.COMPLETED).length,
    failed: filteredTasks.filter((task) => task.status === TaskStatus.FAILED).length,
  };

  const dappOptions = useMemo(() => {
    if (dappCatalog.length > 0) {
      return dappCatalog.map((item) => ({
        label: `${item.name}${item.demo_ready ? " · 可直接演示" : ""}${item.platform ? ` · ${item.platform}` : ""}`,
        value: item.name,
      }));
    }
    return DAPP_OPTIONS.map((name) => ({ label: name, value: name }));
  }, [dappCatalog]);

  const selectedDappDetail = useMemo(() => {
    if (selectedDapps.length !== 1) return null;
    return dappCatalog.find((item) => item.name === selectedDapps[0]) ?? null;
  }, [dappCatalog, selectedDapps]);

  const columns: ColumnsType<Task> = [
    {
      title: "DApp",
      dataIndex: "dapp_name",
      key: "dapp_name",
      render: (name: string) => <Typography.Text strong>{name}</Typography.Text>,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      render: (status: TaskStatus, record) => (
        <Space size={6}>
          <Tag color={getStatusColor(status)}>{taskStatusLabel(status)}</Tag>
          {record.archived ? <Tag>已归档</Tag> : null}
        </Space>
      ),
      filters: Object.values(TaskStatus).map((value) => ({ text: taskStatusLabel(value), value })),
      onFilter: (value, record) => record.status === value,
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: "耗时",
      dataIndex: "duration",
      key: "duration",
      render: (value?: number | null) => formatDuration(value),
    },
    {
      title: "操作",
      key: "action",
      width: 420,
      render: (_, record) => (
        <Space>
          <Button size="small" icon={<Eye size={14} />} onClick={() => navigate(`/tasks/${record.task_id}`)}>
            查看
          </Button>
          <DappContextButton dappName={record.dapp_name} />
          {isRunnableTask(record.status) ? (
            <Button size="small" icon={<Square size={14} />} danger onClick={() => handleCancel(record)}>
              取消
            </Button>
          ) : record.archived ? (
            <Button size="small" icon={<Undo2 size={14} />} onClick={() => handleRestore(record)}>
              恢复
            </Button>
          ) : (
            <Button size="small" icon={<Archive size={14} />} onClick={() => handleArchive(record)}>
              归档
            </Button>
          )}
       </Space>
      ),
    },
  ];

  return (
    <Layout className="app-shell">
      <Header className="topbar">
        <div className="topbar-brand workbench-brand">
          <span className="workbench-brand-mark"><img src={riskPilotLogo} alt="AttackPilot 标志" /></span>
          <div>
            <Typography.Text className="brand-kicker">AttackPilot 任务工作台</Typography.Text>
            <Typography.Title level={3} className="topbar-title">
              任务库
            </Typography.Title>
            <Typography.Text type="secondary" className="topbar-subtitle">
              管理实时任务、历史报告和可复现攻击案例。
            </Typography.Text>
          </div>
        </div>
        <Space>
          <Button icon={<Home size={15} />} onClick={() => navigate("/")}>
            首页
          </Button>
          <Button icon={<RefreshCcw size={15} />} onClick={fetchTasks}>
            刷新
          </Button>
          <Button type="primary" icon={<Play size={15} />} onClick={() => setIsModalVisible(true)}>
            已发生案例复盘
          </Button>
        </Space>
      </Header>

      <Content className="task-list-page">
        <Row gutter={[16, 16]} className="stat-row">
          <Col xs={12} lg={6}>
            <Card className="metric-card metric-card-total">
              <div className="metric-card-inner">
                <span className="metric-icon">
                  <ListChecks size={22} />
                </span>
                <div>
                  <span className="metric-label">任务总数</span>
                  <span className="metric-value large">{stats.total}</span>
                </div>
              </div>
            </Card>
          </Col>
          <Col xs={12} lg={6}>
            <Card className="metric-card metric-card-running">
              <div className="metric-card-inner">
                <span className="metric-icon">
                  <Activity size={22} />
                </span>
                <div>
                  <span className="metric-label">运行中</span>
                  <span className="metric-value large text-blue">{stats.running}</span>
                </div>
              </div>
            </Card>
          </Col>
          <Col xs={12} lg={6}>
            <Card className="metric-card metric-card-completed">
              <div className="metric-card-inner">
                <span className="metric-icon">
                  <CheckCircle2 size={22} />
                </span>
                <div>
                  <span className="metric-label">已完成</span>
                  <span className="metric-value large text-green">{stats.completed}</span>
                </div>
              </div>
            </Card>
          </Col>
          <Col xs={12} lg={6}>
            <Card className="metric-card metric-card-failed">
              <div className="metric-card-inner">
                <span className="metric-icon">
                  <XCircle size={22} />
                </span>
                <div>
                  <span className="metric-label">已失败</span>
                  <span className="metric-value large text-red">{stats.failed}</span>
                </div>
              </div>
            </Card>
          </Col>
        </Row>

        <Card className="table-card">
          <div className="table-toolbar">
            <div>
              <Typography.Title level={5}>复盘任务</Typography.Title>
              <Typography.Text type="secondary">创建、恢复并查看攻击复盘任务。</Typography.Text>
            </div>
            <Select
              value={archiveFilter}
              onChange={setArchiveFilter}
              options={[
                { label: "当前任务", value: "active" },
                { label: "已归档", value: "archived" },
                { label: "全部记录", value: "all" },
              ]}
            />
            <Select
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { label: "全部状态", value: "all" },
                { label: "等待中", value: TaskStatus.PENDING },
                { label: "运行中", value: TaskStatus.RUNNING },
                { label: "已完成", value: TaskStatus.COMPLETED },
                { label: "已失败", value: TaskStatus.FAILED },
              ]}
            />
          </div>

          <Table
            dataSource={filteredTasks}
            columns={columns}
            rowKey="task_id"
            loading={loading}
            pagination={{ pageSize: 10, size: "small" }}
          />
        </Card>
      </Content>

      <Modal
        title="已发生案例复盘"
        open={isModalVisible}
        onOk={handleCreate}
        onCancel={() => {
          setIsModalVisible(false);
          setSelectedDapps([]);
        }}
        confirmLoading={loading}
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

export default TaskList;

