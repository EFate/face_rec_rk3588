#!/bin/bash
# start.sh

# 当任何命令失败时，立即退出脚本
set -e

# 关键步骤：切换到容器内的项目根目录 /app
# 这能确保后续所有命令的相对路径都是正确的
cd /app || exit

echo "[INFO] Current working directory: $(pwd)"
echo "[INFO] Starting Streamlit UI in background..."

# 以后台模式启动 Streamlit UI，并允许从外部访问
# 使用环境变量来动态设置地址和端口，并提供默认值
streamlit run ui/ui.py --server.address=${WEBUI__HOST:-0.0.0.0} --server.port=${WEBUI__PORT:-12021} &

echo "[INFO] Starting FastAPI application in foreground..."

# 在前台启动 FastAPI 应用 (作为容器的主进程)
python3 run.py --env production start