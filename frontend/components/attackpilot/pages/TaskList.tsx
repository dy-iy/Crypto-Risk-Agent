"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "../services/navigation";
import { Alert, App as AntdApp, Button, Modal, Popconfirm, Select, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  Archive,
  Eye,
  Play,
  RefreshCcw,
  Square,
  Trash2,
  Undo2,
} from "lucide-react";
import DappContextButton from "../components/DappContextButton";
import { archiveTask, cancelTask, createTask, deleteTask, errorMessage, listDapps, listTasks, unarchiveTask } from "../services/api";
import { useAttackPilotIdentity } from "../context";
import { DappCatalogItem, Task, TaskCreateRequest, TaskStatus } from "../types";
import { formatDurationZh, taskStatusLabel } from "../utils/presentation";
import { getDappMetadata } from "../utils/dappMetadata";
import "../tasks.css";

function getStatusColor(status: TaskStatus) {
  if (status === TaskStatus.COMPLETED) return "success";
  if (status === TaskStatus.FAILED) return "error";
  if (status === TaskStatus.RUNNING) return "processing";
  return "default";
}

function formatDuration(duration?: number | null) {
  return formatDurationZh(duration);
}

function isRunnableTask(status: TaskStatus) {
  return status === TaskStatus.PENDING || status === TaskStatus.RUNNING;
}

const TaskList: React.FC = () => {
  const { message } = AntdApp.useApp();
  const { userId, onLogin } = useAttackPilotIdentity();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [selectedDapps, setSelectedDapps] = useState<string[]>([]);
  const [dappCatalog, setDappCatalog] = useState<DappCatalogItem[]>([]);
  const [dappCatalogLoading, setDappCatalogLoading] = useState(true);
  const [dappCatalogError, setDappCatalogError] = useState("");
  const [loading, setLoading] = useState(true);
  const requestVersion = useRef(0);
  const creationRef = useRef<AbortController | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [scopeFilter, setScopeFilter] = useState<"all" | "mine" | "demo">("all");
  const [statusFilter, setStatusFilter] = useState<"all" | TaskStatus>("all");
  const [archiveFilter, setArchiveFilter] = useState<"active" | "archived" | "all">("active");
  const navigate = useNavigate();

  useEffect(() => () => {
    creationRef.current?.abort();
    creationRef.current = null;
  }, []);

  const fetchTasks = useCallback(() => {
    const version = ++requestVersion.current;
    return listTasks(archiveFilter !== "active")
      .then(items => {
        if (version !== requestVersion.current) return;
        setTasks(items);
        setError("");
      })
      .catch(error => {
        if (version === requestVersion.current) setError(errorMessage(error));
      })
      .finally(() => {
        if (version === requestVersion.current) setLoading(false);
      });
  }, [archiveFilter]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await fetchTasks();
      if (!cancelled) timer = setTimeout(poll, 5000);
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); requestVersion.current += 1; };
  }, [fetchTasks]);

  useEffect(() => {
    let cancelled = false;
    listDapps()
      .then((catalog) => {
        if (cancelled) return;
        setDappCatalog(catalog.items.map(item => {
          const metadata = getDappMetadata(item.name);
          return { ...item, cause: metadata?.cause_zh ?? item.cause, root_cause: metadata?.root_cause_zh ?? item.root_cause };
        }));
        setDappCatalogError("");
      })
      .catch(() => {
        if (cancelled) return;
        setDappCatalog([]);
        setDappCatalogError("案例目录暂不可用，请稍后刷新。已有任务仍可从任务库查看。");
      })
      .finally(() => {
        if (!cancelled) setDappCatalogLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleCreate = async () => {
    if (!userId) { onLogin(); return; }
    if (creationRef.current) return;
    if (selectedDapps.length === 0) {
      message.error("请至少选择一个案例");
      return;
    }

    const controller = new AbortController();
    creationRef.current = controller;
    const created: Task[] = [];
    try {
      setCreating(true);
      for (const dappName of selectedDapps) {
        const req: TaskCreateRequest = { dapp_name: dappName };
        created.push(await createTask(req, controller.signal));
        if (controller.signal.aborted) return;
      }
      message.success(`已启动 ${created.length} 个复盘任务`);
      setIsModalVisible(false);
      setSelectedDapps([]);
      await fetchTasks();
      if (controller.signal.aborted) return;
      if (created.length === 1) {
        navigate(`/tasks/${created[0].task_id}`);
      }
    } catch (error: unknown) {
      if (controller.signal.aborted) return;
      setSelectedDapps(selectedDapps.filter(name => !created.some(task => task.dapp_name === name)));
      message.error(`${created.length ? `已创建 ${created.length} 个任务，剩余案例创建失败：` : ""}${errorMessage(error)}`);
      if (created.length) await fetchTasks();
    } finally {
      if (creationRef.current === controller) creationRef.current = null;
      if (!controller.signal.aborted) setCreating(false);
    }
  };

  const handleCancel = async (task: Task) => {
    if (!userId) { onLogin(); return; }
    if (task.is_demo) return;
    try {
      await cancelTask(task.task_id);
      message.success("已提交取消任务请求");
      await fetchTasks();
    } catch (error: unknown) {
      message.error(errorMessage(error));
    }
  };

  const handleArchive = async (task: Task) => {
    if (!userId) { onLogin(); return; }
    if (task.is_demo) return;
    try {
      await archiveTask(task.task_id);
      message.success("任务已归档");
      await fetchTasks();
    } catch (error: unknown) {
      message.error(errorMessage(error));
    }
  };

  const handleRestore = async (task: Task) => {
    if (!userId) { onLogin(); return; }
    if (task.is_demo) return;
    try {
      await unarchiveTask(task.task_id);
      message.success("任务已恢复");
      await fetchTasks();
    } catch (error: unknown) {
      message.error(errorMessage(error));
    }
  };

  const handleDelete = async (task: Task) => {
    if (!userId) { onLogin(); return; }
    if (task.is_demo || isRunnableTask(task.status)) return;
    try {
      await deleteTask(task.task_id);
      message.success("任务及日志已删除");
      await fetchTasks();
    } catch (error) { message.error(errorMessage(error)); }
  };

  const filteredTasks = useMemo(() => {
    return tasks.filter((task) => {
      if (scopeFilter === "mine" && task.is_demo) return false;
      if (scopeFilter === "demo" && !task.is_demo) return false;
      if (archiveFilter === "active" && task.archived) return false;
      if (archiveFilter === "archived" && !task.archived) return false;
      if (statusFilter !== "all" && task.status !== statusFilter) return false;
      return true;
    });
  }, [archiveFilter, scopeFilter, statusFilter, tasks]);

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
    return [];
  }, [dappCatalog]);

  const selectedDappDetail = useMemo(() => {
    if (selectedDapps.length !== 1) return null;
    return dappCatalog.find((item) => item.name === selectedDapps[0]) ?? null;
  }, [dappCatalog, selectedDapps]);

  const columns: ColumnsType<Task> = [
    {
      title: "案例 / 任务",
      dataIndex: "dapp_name",
      key: "dapp_name",
      width: 220,
      render: (name: string, task) => (
        <div className="ap-task-name">
          <button type="button" onClick={() => navigate(`/tasks/${task.task_id}`)}>{name}</button>
          <span>{task.is_demo ? "公共历史案例" : "我的分析"}</span>
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 170,
      render: (status: TaskStatus, record) => (
        <Space size={6}>
          <Tag color={getStatusColor(status)}>{taskStatusLabel(status)}</Tag>
          {record.archived ? <Tag>已归档</Tag> : null}
        </Space>
      ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 190,
      className: "ap-task-time",
      render: (value: string) => new Date(value).toLocaleString("zh-CN"),
    },
    {
      title: "耗时",
      dataIndex: "duration",
      key: "duration",
      width: 100,
      className: "ap-task-time",
      render: (value?: number | null) => formatDuration(value),
    },
    {
      title: "操作",
      key: "action",
      width: 370,
      render: (_, record) => (
        <Space wrap size={[8, 10]} className="ap-task-row-actions">
          <Button size="small" icon={<Eye size={14} />} onClick={() => navigate(`/tasks/${record.task_id}`)}>
            查看
          </Button>
          <DappContextButton dappName={record.dapp_name} />
          {record.is_demo || !userId ? <Typography.Text type="secondary">只读案例</Typography.Text> : isRunnableTask(record.status) ? (
            <Popconfirm title="取消此复盘任务？" okText="确认取消" cancelText="返回" onConfirm={() => handleCancel(record)}>
            <Button size="small" icon={<Square size={14} />} danger>
              取消
            </Button>
            </Popconfirm>
          ) : record.archived ? (
            <Button size="small" icon={<Undo2 size={14} />} onClick={() => handleRestore(record)}>
              恢复
            </Button>
          ) : (
            <Button size="small" icon={<Archive size={14} />} onClick={() => handleArchive(record)}>
              归档
            </Button>
          )}
          {!record.is_demo && userId && !isRunnableTask(record.status) ? <Popconfirm title="删除此任务及其日志？" description="删除后无法恢复。" okText="删除" cancelText="取消" onConfirm={() => handleDelete(record)}><Button size="small" danger icon={<Trash2 size={14} />}>删除</Button></Popconfirm> : null}
       </Space>
      ),
    },
  ];

  return (
    <div className="ap-page ap-task-page">
      <main className="ap-page-content">
        <header className="ap-page-heading">
          <div>
            <span className="ap-eyebrow">AttackPilot 任务工作台</span>
            <h1>任务库</h1>
          </div>
          <div className="ap-page-actions">
            <Button icon={<RefreshCcw size={15} />} loading={loading} onClick={() => { setLoading(true); void fetchTasks(); }}>
              刷新
            </Button>
            <Button type="primary" icon={<Play size={15} />} onClick={() => userId ? setIsModalVisible(true) : onLogin()}>
              已发生案例复盘
            </Button>
          </div>
        </header>

        {error || !userId ? <div className="ap-task-notices">
          {error ? <Alert type="error" showIcon title={error} /> : null}
          {!userId ? <Alert type="info" showIcon title="公共历史案例可直接浏览，登录后可创建和管理自己的复盘任务。" action={<Button onClick={onLogin}>登录</Button>} /> : null}
        </div> : null}

        <dl className="ap-task-stats">
          <div><dt>任务总数</dt><dd>{stats.total}</dd></div>
          <div><dt>运行中</dt><dd>{stats.running}</dd></div>
          <div><dt>已完成</dt><dd>{stats.completed}</dd></div>
          <div><dt>已失败</dt><dd>{stats.failed}</dd></div>
        </dl>

        <section className="ap-task-library" aria-labelledby="ap-task-library-title">
          <div className="ap-task-toolbar">
            <h2 id="ap-task-library-title">复盘任务</h2>
            <div className="ap-task-filters">
              <Select aria-label="任务范围" value={scopeFilter} onChange={setScopeFilter} options={[
                { label: "全部可见任务", value: "all" },
                { label: "公共历史案例", value: "demo" },
                { label: "我的任务", value: "mine", disabled: !userId },
              ]} />
              <Select
                aria-label="归档状态"
                value={archiveFilter}
                onChange={value => { setLoading(true); setArchiveFilter(value); }}
                options={[
                  { label: "当前任务", value: "active" },
                  { label: "已归档", value: "archived" },
                  { label: "全部记录", value: "all" },
                ]}
              />
              <Select
                aria-label="任务状态"
                value={statusFilter}
                onChange={setStatusFilter}
                options={[
                  { label: "全部状态", value: "all" },
                  { label: "等待中", value: TaskStatus.PENDING },
                  { label: "运行中", value: TaskStatus.RUNNING },
                  { label: "已完成", value: TaskStatus.COMPLETED },
                  { label: "已失败", value: TaskStatus.FAILED },
                  { label: "已取消", value: TaskStatus.CANCELLED },
                ]}
              />
            </div>
          </div>

          <Table
            className="ap-task-table"
            dataSource={filteredTasks}
            columns={columns}
            rowKey="task_id"
            loading={loading}
            scroll={{ x: 1050 }}
            pagination={{ pageSize: 10, size: "small" }}
          />
        </section>
      </main>

      <Modal
        title="已发生案例复盘"
        open={isModalVisible}
        onOk={handleCreate}
        onCancel={() => {
          if (creating) return;
          setIsModalVisible(false);
          setSelectedDapps([]);
        }}
        confirmLoading={creating}
        closable={!creating}
        maskClosable={!creating}
        cancelButtonProps={{ disabled: creating }}
        okText="开始复盘"
        cancelText="取消"
        okButtonProps={{ disabled: !selectedDapps.length || !dappCatalog.length }}
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
            disabled={creating}
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
    </div>
  );
};

export default TaskList;
