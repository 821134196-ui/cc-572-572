#!/usr/bin/env bash
# 一键演示：重置演示数据 -> 后台启动服务 -> 跑四个场景 -> 关闭服务
set -e
cd "$(dirname "$0")"

echo ">> 重置演示数据库"
rm -f backend/lab.db
(cd backend && ../.venv/bin/python seed.py)

echo ">> 启动后端服务（后台）"
.venv/bin/uvicorn --app-dir backend --host 127.0.0.1 --port 8000 app.main:app >/tmp/lab_uvicorn.log 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null || true' EXIT

echo ">> 运行端到端演示"
.venv/bin/python backend/demo.py
