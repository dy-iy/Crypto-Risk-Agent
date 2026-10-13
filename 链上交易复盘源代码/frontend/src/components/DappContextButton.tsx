import React, { useEffect, useMemo, useState } from "react";
import { Button, Descriptions, Drawer, Empty, List, Space, Tag, Typography } from "antd";
import { ExternalLink, Info } from "lucide-react";
import { getDappMetadata, shortHash } from "../utils/dappMetadata";

function openExternal(url?: string) {
  if (!url) return;
  window.open(url, "_blank", "noopener,noreferrer");
}

interface Props {
  dappName?: string | null;
  size?: "small" | "middle" | "large";
  type?: "link" | "text" | "default" | "primary" | "dashed";
  disabled?: boolean;
  autoOpenKey?: string | number | null;
}

const DappContextButton: React.FC<Props> = ({ dappName, size = "small", type = "default", disabled, autoOpenKey }) => {
  const [open, setOpen] = useState(false);
  const metadata = useMemo(() => getDappMetadata(dappName), [dappName]);
  const title = metadata?.name ?? dappName ?? "DApp";
  const cause = metadata?.cause_zh ?? metadata?.cause;
  const platform = metadata?.platform_zh ?? metadata?.platform;
  const rootCause = metadata?.root_cause_zh ?? metadata?.root_cause;
  const background = metadata?.report_zh ?? metadata?.background_zh ?? metadata?.report;
  const references = [
    { label: "检测记录", ...metadata?.detection },
    { label: "公开披露", ...metadata?.disclosure },
    { label: "复盘报告", link: metadata?.report_link },
  ].filter((item) => item.link);

  useEffect(() => {
    if (!autoOpenKey || !dappName) return;
    setOpen(true);
  }, [autoOpenKey, dappName]);

  return (
    <>
      <Button
        size={size}
        type={type}
        icon={<Info size={14} />}
        disabled={disabled || !dappName}
        onClick={() => setOpen(true)}
      >
        背景知识
      </Button>

      <Drawer
        title={`${title} 背景知识`}
        open={open}
        onClose={() => setOpen(false)}
        size="large"
        extra={
          <Space>
            {platform ? <Tag>{platform}</Tag> : null}
            {cause ? <Tag color="blue">{cause}</Tag> : null}
          </Space>
        }
      >
        {metadata ? (
          <Space orientation="vertical" size={18} style={{ width: "100%" }}>
            <Descriptions bordered column={1} size="small">
              <Descriptions.Item label="事件时间">{metadata.time ?? "暂无"}</Descriptions.Item>
              <Descriptions.Item label="根因摘要">{rootCause ?? "暂无"}</Descriptions.Item>
              <Descriptions.Item label="相关协议">{platform ?? "暂无"}</Descriptions.Item>
            </Descriptions>

            <div>
              <Typography.Title level={5}>案例背景知识</Typography.Title>
              <Typography.Paragraph>{background ?? "暂无可用背景知识。"}</Typography.Paragraph>
            </div>

            <div>
              <Typography.Title level={5}>相关报道与复盘来源</Typography.Title>
              {references.length > 0 ? (
                <List
                  size="small"
                  dataSource={references}
                  renderItem={(item) => (
                    <List.Item
                      actions={[
                        <Button
                          key="open"
                          size="small"
                          type="link"
                          icon={<ExternalLink size={13} />}
                          onClick={() => openExternal(item.link)}
                        >
                          打开
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        title={item.label}
                        description={
                          <Space orientation="vertical" size={2}>
                            {item.time ? <Typography.Text type="secondary">{item.time}</Typography.Text> : null}
                            <Typography.Text copyable className="text-mono">
                              {item.link}
                            </Typography.Text>
                          </Space>
                        }
                      />
                    </List.Item>
                  )}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无相关链接" />
              )}
            </div>

            <div>
              <Typography.Title level={5}>关联攻击交易</Typography.Title>
              <List
                size="small"
                dataSource={metadata.transaction_hash ?? []}
                locale={{ emptyText: "暂无交易 Hash" }}
                renderItem={(hash) => (
                  <List.Item>
                    <Typography.Text copyable={{ text: hash }} className="text-mono">
                      {shortHash(hash)}
                    </Typography.Text>
                  </List.Item>
                )}
              />
            </div>
          </Space>
        ) : (
          <Empty description="暂无该 DApp 的背景知识" />
        )}
      </Drawer>
    </>
  );
};

export default DappContextButton;
