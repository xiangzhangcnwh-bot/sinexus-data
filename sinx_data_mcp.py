#!/usr/bin/env python3
"""
Sinexus Data MCP Server — 让 Claude / Claude Code 直接调用知识库

启动: python3 sinx_data_mcp.py
"""
import asyncio
from mcp.server import Server, InitializationOptions
import mcp.server.stdio
import mcp.types as types
import httpx

API = "http://localhost:8010"
server = Server("sinexus-data")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(name="search_knowledge",
            description="Search the company document knowledge base. Returns relevant document snippets.",
            inputSchema={"type": "object", "properties": {
                "query": {"type": "string", "description": "Search query, e.g. 'company reimbursement policy'"},
                "limit": {"type": "integer", "description": "Max results", "default": 5},
            }, "required": ["query"]}),
        types.Tool(name="list_documents",
            description="List all documents in the knowledge base",
            inputSchema={"type": "object", "properties": {
                "category": {"type": "string", "description": "Filter by category"},
            }}),
        types.Tool(name="get_document",
            description="Get full content of a document by ID",
            inputSchema={"type": "object", "properties": {
                "doc_id": {"type": "string", "description": "Document ID from search results"},
            }, "required": ["doc_id"]}),
        types.Tool(name="list_categories",
            description="List all document categories",
            inputSchema={"type": "object", "properties": {}}),
    ]


async def api(method: str, path: str, **kw) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.request(method, f"{API}{path}", timeout=60, **kw)
        r.raise_for_status()
        return r.json()


@server.call_tool()
async def handle_call_tool(name: str, args: dict) -> list[types.TextContent]:
    try:
        if name == "search_knowledge":
            data = await api("POST", "/api/search", json={"query": args["query"], "limit": args.get("limit", 5)})
            results = data.get("results", [])
            if not results:
                return [types.TextContent(type="text", text="No relevant documents found.")]
            lines = [f"Found {len(results)} relevant documents:\n"]
            for r in results:
                lines.append(f"**{r['name']}** [{r['category']}]")
                lines.append(f"> {r['snippet'][:200]}...")
                lines.append(f"  ID: {r['id']}\n")
            return [types.TextContent(type="text", text="\n".join(lines))]

        elif name == "list_documents":
            data = await api("GET", "/api/docs")
            docs = data.get("docs", [])
            if args.get("category"):
                docs = [d for d in docs if d["category"] == args["category"]]
            if not docs:
                return [types.TextContent(type="text", text="No documents found.")]
            lines = [f"Total: {len(docs)} documents\n"]
            for d in docs:
                lines.append(f"- **{d['name']}** [{d['category']}] {d['time']} ({d['size']})")
            return [types.TextContent(type="text", text="\n".join(lines))]

        elif name == "get_document":
            data = await api("GET", f"/api/docs/{args['doc_id']}")
            content = data.get("content", "")
            return [types.TextContent(type="text", text=f"# {data.get('name', 'Document')}\n\n{content[:5000]}")]

        elif name == "list_categories":
            data = await api("GET", "/api/docs")
            cats = sorted(set(d["category"] for d in data.get("docs", [])))
            if not cats:
                return [types.TextContent(type="text", text="No categories.")]
            return [types.TextContent(type="text", text=f"Categories:\n" + "\n".join(f"- {c}" for c in cats))]

        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    async with mcp.server.stdio.stdio_server() as (rs, ws):
        await server.run(rs, ws, InitializationOptions(
            server_name="sinexus-data", server_version="1.0.0"))

if __name__ == "__main__":
    asyncio.run(main())
