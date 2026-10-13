FROM python:3.10-slim-bookworm

# 设置工作目录
WORKDIR /app

# 默认使用 Debian 官方源，避免单个国内镜像 502 时阻塞构建。
# 如需切换国内源，可在 docker compose/.env 中设置：
# APT_MIRROR=mirrors.aliyun.com
# APT_SECURITY_MIRROR=mirrors.aliyun.com
ARG APT_MIRROR=deb.debian.org
ARG APT_SECURITY_MIRROR=deb.debian.org

RUN set -ex; \
    if [ "$APT_MIRROR" != "deb.debian.org" ] || [ "$APT_SECURITY_MIRROR" != "deb.debian.org" ]; then \
      echo "Using Debian mirror: $APT_MIRROR, security mirror: $APT_SECURITY_MIRROR"; \
    fi; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s|http://deb.debian.org/debian-security|http://${APT_SECURITY_MIRROR}/debian-security|g" /etc/apt/sources.list.d/debian.sources; \
        sed -i "s|http://deb.debian.org/debian|http://${APT_MIRROR}/debian|g" /etc/apt/sources.list.d/debian.sources; \
    else \
        sed -i "s|http://deb.debian.org/debian|http://${APT_MIRROR}/debian|g" /etc/apt/sources.list; \
        sed -i "s|http://security.debian.org/debian-security|http://${APT_SECURITY_MIRROR}/debian-security|g" /etc/apt/sources.list; \
    fi

# 更新包管理器并安装系统依赖，增加重试机制
RUN apt-get update -o Acquire::Retries=5 && \
    apt-get install -y --no-install-recommends \
    -o Acquire::Retries=5 \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 安装 uvicorn 和 celery
RUN pip install --no-cache-dir "uvicorn[standard]" celery

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 8000

# 设置启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
