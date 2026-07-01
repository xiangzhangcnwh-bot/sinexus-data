#!/usr/bin/env python3
"""
Sinexus Data — 轻量企业文档知识库
上传 → MinerU 解析 → AI 分类 → 向量化 → 语义搜索 → MCP

Usage:  python3 sinx_data_server.py              # 启动服务
        python3 sinx_data_mcp.py                  # 启动 MCP 服务
        curl -F "file=@doc.pdf" localhost:8010/api/upload  # 上传文档
"""
import os, sys, json, hashlib, time, re
from pathlib import Path
from datetime import datetime
from typing import Optional

import requests
import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import chromadb
from chromadb.config import Settings
from chromadb.api.types import EmbeddingFunction, Embeddings

# ============ 环境变量配置 ============
DATA_DIR = Path(os.environ.get("SINEXUS_DATA_DIR", os.path.expanduser("~/.sinexus-data")))
MINERU_URL = os.environ.get("MINERU_URL", "http://localhost:8000")
VOLC_API_KEY = os.environ.get("VOLC_API_KEY", "")
VOLC_URL = "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions"
CHAT_MODEL = os.environ.get("CHAT_MODEL", "deepseek-v4-flash")
BGE_URL = os.environ.get("BGE_URL", "http://localhost:7997/v1/embeddings")
PORT = int(os.environ.get("PORT", 8010))

DOCS_DIR = DATA_DIR / "docs"
CHROMA_DIR = DATA_DIR / "chroma"
META_FILE = DATA_DIR / "metadata.json"

CATEGORIES = [
    "产品中心", "研发中心", "行政人事",
    "财务管理", "合同法务", "市场营销",
]

# ============ 初始化 ============
DATA_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)
if not META_FILE.exists():
    META_FILE.write_text("[]", encoding="utf-8")


class LocalBGEEmbedding(EmbeddingFunction):
    """调用本地 BGE 服务进行向量化"""
    def __call__(self, texts: list[str]) -> Embeddings:
        r = requests.post(BGE_URL, json={"input": texts, "model": "bge-small-zh-v1.5"}, timeout=60)
        r.raise_for_status()
        return [d["embedding"] for d in r.json()["data"]]


EMBED_FN = LocalBGEEmbedding()
chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False))

try:
    collection = chroma_client.get_collection("docs", embedding_function=EMBED_FN)
except:
    try: chroma_client.delete_collection("docs")
    except: pass
    collection = chroma_client.create_collection("docs", embedding_function=EMBED_FN, metadata={"hnsw:space": "cosine"})

# ============ FastAPI ============
app = FastAPI(title="Sinexus Data")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ============ 工具函数 ============
def load_meta() -> list:
    return json.loads(META_FILE.read_text("utf-8"))

def save_meta(data: list):
    META_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def doc_id(filename: str) -> str:
    return hashlib.md5(filename.encode()).hexdigest()[:16]


def classify(text: str) -> str:
    """AI 自动分类（无 API Key 时用关键词兜底）"""
    if not VOLC_API_KEY:
        return classify_fallback(text)
    prompt = f"""Choose the best category for this document, output ONLY the category name:
Category options: 产品中心 | 研发中心 | 行政人事 | 财务管理 | 合同法务 | 市场营销

Document: {text[:500]}
Category:"""
    try:
        r = requests.post(VOLC_URL,
            headers={"Authorization": f"Bearer {VOLC_API_KEY}", "Content-Type": "application/json"},
            json={"model": CHAT_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 10, "temperature": 0},
            timeout=15)
        result = r.json()["choices"][0]["message"]["content"].strip()
        for c in CATEGORIES:
            if c in result: return c
    except Exception as e:
        print(f"[classify] LLM failed: {e}, using fallback")
    return classify_fallback(text)

def classify_fallback(text: str) -> str:
    """关键词兜底分类"""
    kw = {
        "产品中心": ["产品", "手册", "功能", "规格", "说明书", "manual", "spec", "用户指南"],
        "研发中心": ["技术", "架构", "代码", "API", "开发", "技术文档", "设计", "dev", "engineer"],
        "行政人事": ["员工", "考勤", "招聘", "培训", "制度", "HR", "人事", "薪酬"],
        "财务管理": ["报销", "发票", "预算", "财务", "会计", "费用", "finance", "invoice"],
        "合同法务": ["合同", "协议", "法务", "合规", "NDA", "诉讼", "知识产权", "legal"],
        "市场营销": ["营销", "推广", "客户", "品牌", "广告", "案例", "market", "campaign"],
    }
    tl = text.lower()
    scores = {c: sum(1 for k in keys if k.lower() in tl) for c, keys in kw.items()}
    return max(scores, key=scores.get) or "产品中心"


def parse_with_mineru(file_path: str) -> Optional[str]:
    """调 MinerU API 解析 PDF/图片等文档"""
    with open(file_path, "rb") as f:
        r = requests.post(f"{MINERU_URL}/file_parse",
            files={"files": (Path(file_path).name, f)},
            data={"backend": "pipeline", "parse_method": "auto"},
            timeout=600)
    r.raise_for_status()
    task = r.json()
    task_id = task["task_id"]
    while True:
        s = requests.get(f"{MINERU_URL}/tasks/{task_id}", timeout=30).json()
        if s["status"] == "completed": break
        if s["status"] == "failed": raise RuntimeError(s.get("error", "parse failed"))
        time.sleep(5)
    result = requests.get(f"{MINERU_URL}/tasks/{task_id}/result", timeout=60).json()
    files_result = result.get("results", {})
    if not files_result: raise RuntimeError("no result")
    first = list(files_result.keys())[0]
    return files_result[first].get("md_content", "")


# ============ API ============

PAGE = """<!DOCTYPE html><html lang="zh-CN">
<head><meta charset="utf-8"><title>Sinexus Data</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#f5f7fa;color:#333}
.hd{background:linear-gradient(135deg,#1a237e,#283593);color:#fff;padding:20px 0;margin-bottom:20px}
.hd h1{font-size:22px}.hd p{opacity:.85;font-size:13px;margin-top:4px}
.ct{max-width:1000px;margin:0 auto;padding:0 20px}
.cd{background:#fff;border-radius:10px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:16px}
.cd h2{font-size:16px;color:#1a237e;margin-bottom:12px}
.up{border:2px dashed #c5cae9;border-radius:8px;padding:30px;text-align:center;cursor:pointer}
.up:hover{border-color:#3f51b5;background:#e8eaf6;cursor:pointer}
.tag{display:inline-block;background:#e8eaf6;color:#3949ab;padding:2px 8px;border-radius:10px;font-size:11px}
.err{color:#d32f2f;background:#ffebee;padding:8px;border-radius:4px;margin:8px 0}
.ok{color:#2e7d32;background:#e8f5e9;padding:8px;border-radius:4px;margin:8px 0}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #eee}
th{color:#666;font-weight:500}
.sbx{display:flex;gap:8px;margin-bottom:12px}
.sbx input{flex:1;padding:6px 10px;border:1px solid #ddd;border-radius:4px;font-size:14px}
.btn{background:#3f51b5;color:#fff;border:none;padding:8px 20px;border-radius:6px;cursor:pointer;font-size:14px}
</style></head><body>
<div class="hd"><div class="ct"><h1>📚 Sinexus Data</h1><p>拖拽文档上传 → 自动解析 → AI 分类 → 可检索</p></div></div>
<div class="ct" id="a">
<div class="cd"><h2>📤 上传文档</h2>
<div class="up" id="dz" onclick="document.getElementById('fi').click()">
<div>📁 拖拽文件到此处，或点击选择</div><div style="color:#999;font-size:12px">PDF / DOCX / PPTX / XLSX / TXT / MD / 图片</div>
<input type="file" id="fi" accept=".pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.txt,.md" style="display:none">
</div><div id="us"></div></div>
<div class="cd"><h2>🔍 搜索文档</h2>
<div class="sbx"><input type="text" id="sq" placeholder="输入问题或关键词..." onkeydown="if(event.key==='Enter')S()">
<button class="btn" onclick="S()">搜索</button></div><div id="sr"></div></div>
<div class="cd"><h2>📋 文档列表</h2><div id="dl"></div></div></div>
<script>
async function U(f){const s=document.getElementById('us');s.innerHTML='<div class="ok">⏳ 上传中...</div>';
const fd=new FormData();fd.append('file',f);
const d=await(await fetch('/api/upload',{method:'POST',body:fd})).json();
s.innerHTML=d.error?'<div class="err">❌ '+d.error+'</div>':'<div class="ok">✅ '+d.message+'</div>';L();}
document.getElementById('fi').onchange=e=>{if(e.target.files[0])U(e.target.files[0])};
document.getElementById('dz').ondragover=e=>e.preventDefault();
document.getElementById('dz').ondrop=e=>{e.preventDefault();if(e.dataTransfer.files[0])U(e.dataTransfer.files[0])};
async function S(){const q=document.getElementById('sq').value;
const d=await(await fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:q})})).json();
const el=document.getElementById('sr');
if(!d.results||!d.results.length){el.innerHTML='<div style="color:#999">无结果</div>';return;}
el.innerHTML='<table><tr><th>文档</th><th>分类</th><th>匹配</th></tr>'+d.results.map(r=>'<tr><td>'+r.name+'</td><td><span class="tag">'+r.category+'</span></td><td style="font-size:12px;color:#666">'+r.snippet.slice(0,100)+'</td></tr>').join('')+'</table>';}
async function L(){const d=await(await fetch('/api/docs')).json();const el=document.getElementById('dl');
if(!d.docs||!d.docs.length){el.innerHTML='<div style="color:#999">暂无文档</div>';return;}
el.innerHTML='<table><tr><th>文件名</th><th>分类</th><th>时间</th><th>大小</th></tr>'+d.docs.map(d=>'<tr><td>'+d.name+'</td><td><span class="tag">'+d.category+'</span></td><td>'+d.time+'</td><td>'+d.size+'</td></tr>').join('')+'</table>';}
L();</script></body></html>"""

@app.get("/")
async def index():
    return HTMLResponse(PAGE)


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """上传文档 → 解析 → 分类 → 向量化 → 入库"""
    tmp = Path(f"/tmp/sinx_{int(time.time())}_{file.filename}")
    try:
        content = await file.read()
        tmp.write_bytes(content)
        filename, ext = file.filename, Path(file.filename).suffix.lower()

        # 1. 解析
        if ext in (".txt", ".md", ".csv", ".json", ".log"):
            md = tmp.read_text("utf-8", errors="ignore")
        else:
            md = parse_with_mineru(str(tmp))
        if not md or len(md.strip()) < 10:
            return JSONResponse({"error": "empty parse result"})

        # 2. 分类
        cat = classify(md)

        # 3. 存 Markdown
        cat_dir = DOCS_DIR / cat
        cat_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r'[^\w\-_\. ]', '', Path(filename).stem)[:50]
        md_path = cat_dir / f"{stem}_{doc_id(filename)}.md"
        md_path.write_text(md, encoding="utf-8")

        # 4. 元数据
        meta = load_meta()
        entry = {
            "id": doc_id(filename), "name": filename, "category": cat,
            "path": str(md_path.relative_to(DATA_DIR)),
            "size": f"{len(content)/1024:.1f}KB", "chars": len(md),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        meta.append(entry)
        save_meta(meta)

        # 5. 向量化
        chunks = [md[i:i+500] for i in range(0, len(md), 500)] or [md]
        collection.add(
            documents=chunks,
            metadatas=[{"doc_id": entry["id"], "name": filename, "category": cat} for _ in chunks],
            ids=[f"{entry['id']}_{i}" for i in range(len(chunks))],
        )

        return JSONResponse({"message": f"✅ {filename} → {cat} ({len(md)} chars, {len(chunks)} chunks)"})
    except Exception as e:
        return JSONResponse({"error": str(e)})
    finally:
        tmp.unlink(missing_ok=True)


@app.post("/api/search")
async def search(data: dict):
    """语义搜索"""
    query, limit = data.get("query", ""), min(data.get("limit", 10), 50)
    if not query: return JSONResponse({"results": []})
    try:
        results = collection.query(query_texts=[query], n_results=limit)
        items, seen = [], set()
        for i in range(len(results["ids"][0])):
            m = results["metadatas"][0][i]
            if m["doc_id"] in seen: continue
            seen.add(m["doc_id"])
            items.append({"id": m["doc_id"], "name": m["name"], "category": m["category"],
                "snippet": results["documents"][0][i][:200]})
        return JSONResponse({"results": items})
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.get("/api/docs")
async def list_docs():
    meta = load_meta()
    return JSONResponse({"docs": sorted(meta, key=lambda x: x["time"], reverse=True)})


@app.get("/api/docs/{doc_id}")
async def get_doc(doc_id: str):
    meta = load_meta()
    for m in meta:
        if m["id"] == doc_id:
            p = DATA_DIR / m["path"]
            if p.exists():
                return JSONResponse({"content": p.read_text("utf-8"), **m})
    raise HTTPException(404, "doc not found")


@app.get("/health")
async def health():
    return {"status": "ok", "docs": len(load_meta())}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
