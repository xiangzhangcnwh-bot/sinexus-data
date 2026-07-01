# Sinexus Data

轻量企业文档知识库。上传文档 → 自动解析 → AI 分类 → 向量存档 → 语义搜索 → **MCP 协议供 Claude 调用**。

```
一个 Python 进程，无 Docker，无数据库集群，512MB 即可运行。
```

## 快速开始

```bash
git clone https://github.com/xiangzhangcnwh-bot/sinexus-data
cd sinexus-data

# 安装依赖
pip install -r requirements.txt

# 启动
python3 sinx_data_server.py
```

打开 http://localhost:8010 即可上传和搜索文档。

## 架构

```
上传 PDF/DOCX/图片                         Claude / Codex
       │                                       │
       ▼                                       ▼
┌──────────────┐   ┌──────────┐   ┌──────────────────────┐
│  MinerU      │   │ AI 分类  │   │  MCP Server           │
│  文档解析     │──▶│ DeepSeek │──▶│  tools/search/        │
│  pipeline    │   │ /关键词  │   │  get/list             │
└──────────────┘   └─────┬────┘   └──────────────────────┘
                         │
                    ┌────▼────┐
                    │ChromaDB │ ← 向量检索
                    │ + 文件  │ ← Markdown 原文
                    └─────────┘
```

**核心特点**：
- **1 个 Python 进程** 搞定全部
- **本地向量化**（BGE Small ZH，CPU 可跑）
- **AI 自动分类**（支持火山引擎 DeepSeek / 关键词兜底）
- **语义搜索**（不是关键词匹配，是理解意思）
- **MCP 协议**（Claude、Claude Code、任何 MCP 客户端原生支持）
- **无 Docker**、无 K8s、无外部数据库

## 配置

通过环境变量配置：

```bash
# 数据目录（默认 ~/.sinexus-data）
export SINEXUS_DATA_DIR=/opt/sinexus-data/data

# 端口（默认 8010）
export PORT=8010

# 火山引擎 API Key（用于 AI 分类，可选）
export VOLC_API_KEY="your-key"
export CHAT_MODEL="deepseek-v4-flash"

# MinerU 解析服务（可选）
export MINERU_URL="http://localhost:8000"

# BGE 嵌入服务（可选）
export BGE_URL="http://localhost:7997/v1/embeddings"
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | Web UI |
| POST | `/api/upload` | 上传文档（multipart） |
| POST | `/api/search` | 语义搜索 |
| GET | `/api/docs` | 文档列表 |
| GET | `/api/docs/:id` | 文档全文 |
| GET | `/health` | 健康检查 |

### 上传文档

```bash
curl -F "file=@合同.pdf" http://localhost:8010/api/upload
```

### 搜索

```bash
curl -X POST http://localhost:8010/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "公司报销制度"}'
```

## MCP（Model Context Protocol）

让 Claude / Claude Code 直接调用知识库：

In [Configuring OSS with Claude Code](https://docs.anthropic.com/en/docs/claude-code/settings):

```json
{
  "mcpServers": {
    "sinexus-data": {
      "command": "python3",
      "args": ["/path/to/sinx_data_mcp.py"]
    }
  }
}
```

Claude 就能用 `search_knowledge()`、`list_documents()`、`get_document()` 等工具。

## 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/xiangzhangcnwh-bot/sinexus-data/main/install.sh | bash
```

完整版（含 MinerU 解析 + BGE 嵌入）：

```bash
curl -fsSL https://raw.githubusercontent.com/xiangzhangcnwh-bot/sinexus-data/main/install.sh | bash -s -- --full
```

## 最小依赖

```
Python 3.10+、fastapi、uvicorn、chromadb、requests、httpx、mcp
```

无需 Docker、无需 GPU、无需 MongoDB/Redis/Postgres。

## License

MIT
