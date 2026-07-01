#!/usr/bin/env bash
set -euo pipefail

# ╔═══════════════════════════════════════════════╗
# ║  Sinexus Data - 一键安装脚本                   ║
# ║  轻量企业文档知识库                             ║
# ╚═══════════════════════════════════════════════╝

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[i]${NC} $1"; }

# ---- 配置 ----
SINEXUS_DIR="${SINEXUS_DIR:-/opt/sinexus-data}"
SINEXUS_PORT="${SINEXUS_PORT:-8010}"
SINEXUS_USER="${SINEXUS_USER:-ubuntu}"

# ---- 检查环境 ----
info "检查系统..."
ARCH=$(uname -m)
OS=$(uname -s)

if [ "$OS" != "Linux" ]; then
    warn "当前系统: $OS，推荐 Linux 以获得最佳 MinerU 支持"
fi

# ---- 安装系统依赖 ----
log "安装系统依赖..."
if command -v apt-get &>/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-pip python3-venv curl 2>/dev/null
elif command -v yum &>/dev/null; then
    sudo yum install -y python3 python3-pip python3-venv curl 2>/dev/null
fi

# ---- 创建目录 ----
info "创建目录: $SINEXUS_DIR"
sudo mkdir -p "$SINEXUS_DIR"
sudo mkdir -p "$SINEXUS_DIR/data/docs"
sudo mkdir -p "$SINEXUS_DIR/data/chroma"
echo "[]" | sudo tee "$SINEXUS_DIR/data/metadata.json" > /dev/null

# ---- 复制文件 ----
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/sinx_data_server.py" ]; then
    sudo cp "$SCRIPT_DIR/sinx_data_server.py" "$SINEXUS_DIR/"
    sudo cp "$SCRIPT_DIR/sinx_data_mcp.py" "$SINEXUS_DIR/"
    sudo cp "$SCRIPT_DIR/requirements.txt" "$SINEXUS_DIR/" 2>/dev/null || true
    log "文件已复制"
else
    warn "未找到源文件，将直接从 GitHub 下载..."
    # 如果从 GitHub 运行，后续补充
fi

# ---- 安装 Python 依赖 ----
log "安装 Python 依赖..."
sudo pip3 install -q -U fastapi uvicorn chromadb requests httpx mcp 2>/dev/null || {
    sudo pip3 install -U fastapi uvicorn chromadb requests httpx mcp
}

# ---- 配置环境变量 ----
cat > /tmp/sinexus-data.env << ENVEOF
# Sinexus Data 配置
export SINEXUS_DIR="$SINEXUS_DIR"
export SINEXUS_DATA_DIR="$SINEXUS_DIR/data"
export PORT="$SINEXUS_PORT"
export MINERU_URL="http://localhost:8000"
export BGE_URL="http://localhost:7997/v1/embeddings"
# 火山引擎 API（需要你自己填，否则分类用关键词兜底）
export VOLC_API_KEY="your_volc_api_key_here"
export CHAT_MODEL="deepseek-v4-flash"
ENVEOF
chmod +x /tmp/sinexus-data.env

# ---- 创建 systemd 服务 ----
log "创建 systemd 服务..."
cat > /tmp/sinexus-data.service << SERVEOF
[Unit]
Description=Sinexus Data - Document Knowledge Base
Documentation=https://github.com/YOUR_USER/sinexus-data
After=network.target

[Service]
Type=simple
User=$SINEXUS_USER
EnvironmentFile=-/etc/sinexus-data/env
Environment="SINEXUS_DATA_DIR=$SINEXUS_DIR/data"
Environment="PORT=$SINEXUS_PORT"
Environment="SINEXUS_DIR=$SINEXUS_DIR"
ExecStart=/usr/bin/python3 $SINEXUS_DIR/sinx_data_server.py
WorkingDirectory=$SINEXUS_DIR
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVEOF

sudo mkdir -p /etc/sinexus-data
sudo cp /tmp/sinexus-data.env /etc/sinexus-data/env 2>/dev/null || true
sudo cp /tmp/sinexus-data.service /etc/systemd/system/sinexus-data.service
sudo systemctl daemon-reload
sudo systemctl enable sinexus-data.service

# ---- 启动 ----
log "启动 Sinexus Data..."
sudo systemctl restart sinexus-data.service
sleep 3

# ---- 验证 ----
if curl -sS -o /dev/null -w "%{http_code}" "http://localhost:$SINEXUS_PORT/" 2>/dev/null | grep -q 200; then
    log "Sinexus Data 已启动!"
    info "   Web UI: http://localhost:$SINEXUS_PORT"
    info "   API:    http://localhost:$SINEXUS_PORT/api"
    info "   MCP:    python3 $SINEXUS_DIR/sinx_data_mcp.py"
else
    warn "服务可能未正常启动，检查日志: sudo journalctl -u sinexus-data -n 30"
fi

# ---- 可选：安装 MinerU + BGE ----
if [ "${1:-}" = "--full" ]; then
    echo ""
    info "安装完整版（MinerU 文档解析 + BGE 本地嵌入）..."

    # BGE 嵌入服务
    pip3 install -q fastapi uvicorn fastembed 2>/dev/null || pip3 install fastapi uvicorn fastembed
    cp "$SCRIPT_DIR/bge_server.py" "$SINEXUS_DIR/" 2>/dev/null || true

    # MinerU
    pip3 install -q -U "mineru[all]" 2>/dev/null || pip3 install -U "mineru[all]"

    log "完整版组件已安装，请参照文档启动 MinerU 和 BGE 服务"
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Sinexus Data 安装完成!            ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════╝${NC}"
echo ""
echo "  配置文件: /etc/sinexus-data/env"
echo "  数据目录: $SINEXUS_DIR/data"
echo ""
echo "  上传文档: curl -F \"file=@doc.pdf\" http://localhost:$SINEXUS_PORT/api/upload"
echo "  搜索:     curl http://localhost:$SINEXUS_PORT/api/docs"
echo ""
echo "  查看日志: sudo journalctl -u sinexus-data -f"
