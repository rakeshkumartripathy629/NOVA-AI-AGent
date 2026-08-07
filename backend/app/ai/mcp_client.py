"""MCP client for calling external MCP servers."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("ai.mcp")

MCP_SERVER_URL = "http://localhost:9002"


async def call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Call a tool on the external MCP server."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{MCP_SERVER_URL}/messages",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments,
                    },
                },
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            if "result" in data and "content" in data["result"]:
                content = data["result"]["content"]
                if isinstance(content, list) and content:
                    return content[0].get("text", str(content))
                return str(content)
            return str(data)
    except Exception as exc:
        logger.warning("MCP tool call failed: %s", exc)
        return f"Tool call failed: {exc}"


async def get_mcp_tools() -> List[Dict[str, Any]]:
    """Get list of available MCP tools."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{MCP_SERVER_URL}/messages",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {},
                },
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            if "result" in data and "tools" in data["result"]:
                return data["result"]["tools"]
            return []
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
