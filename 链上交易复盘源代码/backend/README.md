# AttackPilot 后端

后端负责链上数据取证、多智能体分析、任务持久化、RAG 检索和报告生成。

## 配置模型

编辑 `.env`，填写可用的 OpenAI-compatible 模型服务：

```env
LLM_NAME=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=你的模型服务密钥
```

链上 JSON-RPC、Etherscan 和 Tenderly 接口已在 `settings.py` 中提供，评审运行时无需另外申请。PostgreSQL 和 Redis 由 Docker Compose 自动配置。

## 启动

```powershell
docker compose up -d --build
```

接口地址：`http://localhost:8000`  
接口文档：`http://localhost:8000/docs`

如需直接查看缓存案例，请按上级目录 `README.md` 的步骤导入演示数据。
