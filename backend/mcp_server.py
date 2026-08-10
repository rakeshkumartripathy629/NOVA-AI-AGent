"""External MCP Server for Nova AI - SSE/HTTP transport."""
from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx
from bs4 import BeautifulSoup
from mcp import types
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from mcp.types import ListToolsRequest, ListToolsResult, CallToolRequest, CallToolResult, ServerCapabilities, TextContent
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import Receive, Scope, Send


class _ASGIEndpoint:
    """Starlette 1.x treats classes as ASGI apps (functions become Request endpoints)."""

    def __init__(self, handler):
        self._handler = handler

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._handler(scope, receive, send)

app = Server("nova-ai-mcp-server")
sse_transport = SseServerTransport("/messages")


async def _search_duckduckgo(query: str, max_results: int) -> List[Dict[str, str]]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 NovaAI/1.0"},
        )
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for result in soup.select(".result")[:max_results]:
        link = result.select_one("a.result__a")
        snippet = result.select_one(".result__snippet")
        if link:
            results.append(
                {
                    "title": link.get_text(" ", strip=True),
                    "url": link.get("href", ""),
                    "snippet": snippet.get_text(" ", strip=True) if snippet else "",
                }
            )
    return results


async def handle_list_tools(request: ListToolsRequest) -> ListToolsResult:
    return ListToolsResult(
        tools=[
            types.Tool(
                name="web_search",
                description="Search the web for current information. Use this for finding latest job postings, news, or any real-time data.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return",
                            "default": 10,
                        },
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="read_file",
                description="Read the contents of a file from the local filesystem.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The absolute path to the file",
                        },
                    },
                    "required": ["path"],
                },
            ),
            types.Tool(
                name="list_directory",
                description="List files and directories in a given path.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The absolute path to the directory",
                        },
                    },
                    "required": ["path"],
                },
            ),
            types.Tool(
                name="fetch_url",
                description="Fetch and extract text content from a URL.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to fetch",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Maximum characters to return",
                            "default": 5000,
                        },
                    },
                    "required": ["url"],
                },
            ),
        ]
    )


async def handle_call_tool(request: CallToolRequest) -> CallToolResult:
    name = request.params.name
    arguments = request.params.arguments or {}

    if name == "web_search":
        query = arguments.get("query", "")
        max_results = int(arguments.get("max_results", 10))
        if not query:
            return CallToolResult(content=[TextContent(type="text", text="No query provided")])

        try:
            results = await _search_duckduckgo(query, max_results)
            if not results:
                return CallToolResult(content=[TextContent(type="text", text="No search results found")])

            lines = []
            for i, r in enumerate(results, start=1):
                lines.append(f"[{i}] {r['title']}\n{r['snippet']}\nURL: {r['url']}")
            return CallToolResult(content=[TextContent(type="text", text="\n\n".join(lines))])
        except Exception as exc:
            return CallToolResult(content=[TextContent(type="text", text=f"Search failed: {exc}")])

    elif name == "read_file":
        path = arguments.get("path", "")
        if not path or not os.path.exists(path):
            return CallToolResult(content=[TextContent(type="text", text="File not found")])
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            return CallToolResult(content=[TextContent(type="text", text=content)])
        except Exception as exc:
            return CallToolResult(content=[TextContent(type="text", text=f"Read failed: {exc}")])

    elif name == "list_directory":
        path = arguments.get("path", "")
        if not path or not os.path.isdir(path):
            return CallToolResult(content=[TextContent(type="text", text="Directory not found")])
        try:
            entries = os.listdir(path)
            lines = [f"[DIR] {e}" if os.path.isdir(os.path.join(path, e)) else f"[FILE] {e}" for e in entries]
            return CallToolResult(content=[TextContent(type="text", text="\n".join(lines))])
        except Exception as exc:
            return CallToolResult(content=[TextContent(type="text", text=f"List failed: {exc}")])

    elif name == "fetch_url":
        url = arguments.get("url", "")
        max_chars = int(arguments.get("max_chars", 5000))
        if not url:
            return CallToolResult(content=[TextContent(type="text", text="No URL provided")])
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 NovaAI/1.0"})
                resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(separator="\n", strip=True)
            if len(text) > max_chars:
                text = text[:max_chars] + "..."
            return CallToolResult(content=[TextContent(type="text", text=text)])
        except Exception as exc:
            return CallToolResult(content=[TextContent(type="text", text=f"Fetch failed: {exc}")])

    return CallToolResult(content=[TextContent(type="text", text=f"Unknown tool: {name}")])


app.add_request_handler("tools/list", ListToolsRequest, handle_list_tools)
app.add_request_handler("tools/call", CallToolRequest, handle_call_tool)


async def handle_sse(scope, receive, send):
    async with sse_transport.connect_sse(scope, receive, send) as streams:
        await app.run(
            streams[0],
            streams[1],
            InitializationOptions(
                server_name="nova-ai-mcp",
                server_version="1.0.0",
                capabilities=ServerCapabilities(),
            ),
        )


async def handle_messages(scope, receive, send):
    await sse_transport.handle_post_message(scope, receive, send)


starlette_app = Starlette(
    routes=[
        Route("/sse", endpoint=_ASGIEndpoint(handle_sse), methods=["GET"]),
        Route("/messages", endpoint=_ASGIEndpoint(handle_messages), methods=["POST"]),
    ]
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(starlette_app, host="0.0.0.0", port=9002)
