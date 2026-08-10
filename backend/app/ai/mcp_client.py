"""MCP client for calling external MCP servers (SSE transport)."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from mcp import ClientSession
from mcp.client.sse import sse_client

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("ai.mcp")


def _sse_url() -> str:
    return settings.MCP_SERVER_URL.rstrip("/") + "/sse"


async def call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Call a tool on the external MCP server."""
    try:
        async with sse_client(
            _sse_url(), timeout=settings.MCP_SERVER_TIMEOUT
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments or {})
                if getattr(result, "isError", False):
                    return f"Tool call failed: {result.content}"
                parts = []
                for block in getattr(result, "content", []) or []:
                    text = getattr(block, "text", None)
                    if text is not None:
                        parts.append(text)
                return "\n".join(parts) if parts else str(result.content)
    except Exception as exc:
        logger.warning("MCP tool call failed: %s", exc)
        return f"Tool call failed: {exc}"


async def get_mcp_tools() -> List[Dict[str, Any]]:
    """Get list of available MCP tools."""
    try:
        async with sse_client(_sse_url(), timeout=10) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                        "inputSchema": tool.inputSchema
                        or {"type": "object", "properties": {}},
                    }
                    for tool in result.tools
                ]
    except Exception as exc:
        logger.warning("Failed to list MCP tools: %s", exc)
        return []


def mcp_tools_to_openai_functions(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert MCP tools to OpenAI function calling format."""
    functions = []
    for tool in tools:
        functions.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema", {}),
            },
        })
    return functions


async def execute_mcp_tool_calls(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Execute MCP tool calls and return results."""
    results = []
    for call in tool_calls:
        function_name = call.get("function", {}).get("name")
        arguments = call.get("function", {}).get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}

        result = await call_mcp_tool(function_name, arguments)
        results.append({
            "tool_call_id": call.get("id"),
            "role": "tool",
            "content": result,
        })
    return results
