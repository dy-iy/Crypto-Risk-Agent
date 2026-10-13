# 演示数据

本目录包含已完成的 SushiSwap、ApeCoin 等缓存任务：

- `demo-data/attackpilot-postgres.dump`：任务、状态、报告和日志索引。
- `demo-data/attackpilot-redis-data.tar.gz`：完整日志正文。

恢复数据会覆盖当前 Docker 中的 PostgreSQL 和 Redis 数据，建议在首次部署时执行。

```powershell
.\import-demo-data.ps1 -ComposeDirectory ..\backend
```
