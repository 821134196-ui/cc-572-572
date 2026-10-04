#!/usr/bin/env bash
# 一条本地命令启动：./run.sh
# 完成：建虚拟环境装依赖 -> 构建前端 -> 初始化演示数据 -> 启动服务（API + 前端同一端口）
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"

# ---------- 1. Python 虚拟环境 ----------
if [ ! -d ".venv" ]; then
  echo ">> 创建 Python 虚拟环境 .venv"
  python3 -m venv .venv --without-pip 2>/dev/null || python3 -m venv .venv
  if [ ! -x ".venv/bin/pip" ]; then
    echo ">> 引导 pip 到虚拟环境"
    GETPIP="$(mktemp -d)/get-pip.py"
    curl -sSL https://bootstrap.pypa.io/get-pip.py -o "$GETPIP"
    .venv/bin/python "$GETPIP"
  fi
fi
echo ">> 安装/检查后端依赖"
.venv/bin/pip install -q -r backend/requirements.txt

# ---------- 2. 前端构建 ----------
if [ ! -d "frontend/node_modules" ]; then
  echo ">> 安装前端依赖（npm install）"
  (cd frontend && npm install --no-audit --no-fund)
fi
if [ ! -f "frontend/dist/index.html" ]; then
  echo ">> 构建 Vue 前端"
  (cd frontend && npm run build)
fi

# ---------- 3. 初始化演示数据 ----------
if [ ! -f "backend/lab.db" ]; then
  echo ">> 初始化数据库与演示数据"
  (cd backend && ../.venv/bin/python seed.py)
fi

# ---------- 4. 启动 ----------
PORT="${PORT:-8000}"
echo ""
echo "================================================================"
echo " 系统已启动： http://localhost:${PORT}"
echo " 演示账号（密码同用户名）："
echo "   teacher1/teacher1    王老师（任课老师）"
echo "   admin1/admin1        陈管理员"
echo "   reviewer1/reviewer1  赵主任（免赔审核员，非任课老师）"
echo " API 文档：    http://localhost:${PORT}/docs"
echo " 重置演示数据：rm backend/lab.db 后重新运行 ./run.sh"
echo "================================================================"
exec .venv/bin/uvicorn --app-dir backend --host 0.0.0.0 --port "$PORT" app.main:app
