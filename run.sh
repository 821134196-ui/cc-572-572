#!/usr/bin/env bash
# 一条本地命令启动：初始化数据库+种子数据，启动 FastAPI（同时托管 Vue 前端）
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

# 依赖缺失时自动安装（本机受 PEP 668 管理时加 --break-system-packages）
if ! "$PY" -c "import fastapi, uvicorn, sqlalchemy, multipart" 2>/dev/null; then
  echo ">> 安装 Python 依赖…"
  "$PY" -m pip install -q -r requirements.txt 2>/dev/null \
    || "$PY" -m pip install -q --break-system-packages -r requirements.txt
fi

# 重置并写入演示种子数据（生产环境请去掉这一行）
"$PY" -m backend.seed

PORT="${PORT:-8000}"
echo ">> 服务启动：http://127.0.0.1:${PORT}"
exec "$PY" -m uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}"
