"""Tests for the MCP server and MCP client integration."""
from __future__ import annotations

import threading
import time
import types
from unittest.mock import AsyncMock, patch

import pytest

import mcp_server
from app.ai import mcp_client
from app.ai.mcp_client import (
    call_mcp_tool,
    execute_mcp_tool_calls,
    get_mcp_tools,
    mcp_tools_to_openai_functions,
)


def _call_request(name: str, arguments: dict):
    return types.SimpleNamespace(params=types.SimpleNamespace(name=name, arguments=arguments))


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


class FakeAsyncClient:
    def __init__(self, text: str):
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def get(self, *args, **kwargs):
        return FakeResponse(self._text)


def test_mcp_tools_to_openai_functions():
    tools = [
        {
            "name": "web_search",
            "description": "Search the web",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
        }
    ]
    functions = mcp_tools_to_openai_functions(tools)
    assert functions == [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }
    ]


@pytest.mark.asyncio
async def test_execute_mcp_tool_calls():
    calls = [
        {
            "id": "call_1",
            "function": {"name": "read_file", "arguments": '{"path": "/tmp/a.txt"}'},
        }
    ]
    mock = AsyncMock(return_value="file contents")
    with patch("app.ai.mcp_client.call_mcp_tool", mock):
        results = await execute_mcp_tool_calls(calls)
    assert results == [
        {"tool_call_id": "call_1", "role": "tool", "content": "file contents"}
    ]
    mock.assert_awaited_once_with("read_file", {"path": "/tmp/a.txt"})


@pytest.mark.asyncio
async def test_handle_list_tools():
    result = await mcp_server.handle_list_tools(None)
    names = {tool.name for tool in result.tools}
    assert {"web_search", "read_file", "list_directory", "fetch_url"} == names


@pytest.mark.asyncio
async def test_handle_call_read_file(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("hello mcp", encoding="utf-8")
    result = await mcp_server.handle_call_tool(
        _call_request("read_file", {"path": str(f)})
    )
    assert "hello mcp" in result.content[0].text


@pytest.mark.asyncio
async def test_handle_call_read_missing_file():
    result = await mcp_server.handle_call_tool(
        _call_request("read_file", {"path": "C:\\does_not_exist_mcp.txt"})
    )
    assert "not found" in result.content[0].text.lower()


@pytest.mark.asyncio
async def test_handle_call_list_directory(tmp_path):
    (tmp_path / "alpha.txt").write_text("x", encoding="utf-8")
    (tmp_path / "beta.txt").write_text("y", encoding="utf-8")
    result = await mcp_server.handle_call_tool(
        _call_request("list_directory", {"path": str(tmp_path)})
    )
    text = result.content[0].text
    assert "[FILE] alpha.txt" in text
    assert "[FILE] beta.txt" in text


@pytest.mark.asyncio
async def test_handle_call_fetch_url():
    with patch(
        "mcp_server.httpx.AsyncClient",
        return_value=FakeAsyncClient("<html><body><h1>Title</h1><p>Body text</p></body></html>"),
    ):
        result = await mcp_server.handle_call_tool(
            _call_request("fetch_url", {"url": "https://example.com", "max_chars": 5000})
        )
    assert "Body text" in result.content[0].text


@pytest.mark.asyncio
async def test_handle_call_web_search():
    html = (
        '<div class="result"><a class="result__a" href="https://example.com">'
        "Hello World</a><div class=\"result__snippet\">A snippet.</div></div>"
    )
    with patch("mcp_server.httpx.AsyncClient", return_value=FakeAsyncClient(html)):
        result = await mcp_server.handle_call_tool(
            _call_request("web_search", {"query": "nova ai", "max_results": 5})
        )
    text = result.content[0].text
    assert "Hello World" in text
    assert "https://example.com" in text


@pytest.mark.asyncio
async def test_handle_call_unknown_tool():
    result = await mcp_server.handle_call_tool(_call_request("nope", {}))
    assert "Unknown tool" in result.content[0].text


MCP_TEST_PORT = 19002


@pytest.fixture(scope="module")
def mcp_server_process():
    import uvicorn

    config = uvicorn.Config(
        mcp_server.starlette_app,
        host="127.0.0.1",
        port=MCP_TEST_PORT,
        log_level="error",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "MCP test server failed to start"
    try:
        yield f"http://127.0.0.1:{MCP_TEST_PORT}/sse"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.mark.asyncio
async def test_loopback_list_and_call(mcp_server_process, monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_client.settings, "MCP_SERVER_URL", mcp_server_process)
    tools = await get_mcp_tools()
    assert len(tools) == 4
    assert {t["name"] for t in tools} == {"web_search", "read_file", "list_directory", "fetch_url"}
    assert tools[0]["inputSchema"]["type"] == "object"

    (tmp_path / "note.txt").write_text("loopback works", encoding="utf-8")
    text = await call_mcp_tool("list_directory", {"path": str(tmp_path)})
    assert "[FILE] note.txt" in text
