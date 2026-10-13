# AttackPilot

AttackPilot 是面向链上安全事件的攻击复盘平台。用户可以输入单笔或多笔交易，选择攻击检测、故障定位、补丁生成和补丁验证模块，并在工作区查看 Agent 状态、分析日志、攻击路径和结构化报告。

## 运行环境

- Windows 10/11
- Docker Desktop
- Node.js 20+
- npm 9+

## 模型配置

将根目录的环境变量模板复制到后端：

```powershell
Copy-Item .\.env.example .\backend\.env
```

然后编辑 `backend\.env`，填写模型服务：

```env
LLM_NAME=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=你的模型服务密钥
```

项目已经提供链上 JSON-RPC、Etherscan 和 Tenderly 接口配置，无需评审人员另外注册。数据库、Redis 和服务地址也已写入 Docker Compose。

## 一键启动

在本目录打开 PowerShell：

```powershell
.\Start.ps1
```

脚本会启动后端、恢复缓存案例并启动前端。浏览器访问：

```text
http://localhost:5173
```

即使暂未填写模型密钥，也可以直接进入任务库查看已完成的 SushiSwap、ApeCoin 等缓存案例；启动新的智能分析任务时需要有效的模型密钥。

## 手动启动

```powershell
cd backend
docker compose up -d --build

cd ..\deployment
.\import-demo-data.ps1 -ComposeDirectory ..\backend

cd ..\frontend
npm ci
npm run dev
```

后端接口文档：`http://localhost:8000/docs`
