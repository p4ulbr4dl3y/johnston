import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.infrastructure.mcp.manager import MCPManager
from core.infrastructure.mcp.process_client import MCPProcessClient
from core.infrastructure.mcp.sse_client import MCPSSEClient
from tools.read import ReadTool


@pytest.mark.asyncio
async def test_process_client_roots_and_ping():
    """Test MCPProcessClient handles incoming roots/list and ping requests."""
    client = MCPProcessClient("test_proc", ["echo", "test"], cwd="/tmp/test_dir")

    # Mock send_async
    sent_messages = []

    async def mock_send(data):
        sent_messages.append(data)

    client._send_async = mock_send

    # Handle roots/list
    await client._handle_server_request_async({"jsonrpc": "2.0", "id": 42, "method": "roots/list"})
    assert len(sent_messages) == 1
    resp = sent_messages[0]
    assert resp["id"] == 42
    assert "roots" in resp["result"]
    assert resp["result"]["roots"][0]["uri"].startswith("file://")

    # Handle ping
    await client._handle_server_request_async({"jsonrpc": "2.0", "id": 43, "method": "ping"})
    assert len(sent_messages) == 2
    assert sent_messages[1]["id"] == 43
    assert sent_messages[1]["result"] == {}

    # Handle unknown method
    await client._handle_server_request_async({"jsonrpc": "2.0", "id": 44, "method": "unknown/method"})
    assert len(sent_messages) == 3
    assert "error" in sent_messages[2]
    assert sent_messages[2]["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_process_client_resources_and_prompts_methods():
    """Test MCPProcessClient resources and prompts fetch and read methods."""
    client = MCPProcessClient("test_proc", ["echo", "test"])

    # Mock _send_request_async
    async def mock_send_request(method, params=None, timeout=None):
        if method == "resources/list":
            return {"result": {"resources": [{"uri": "test://doc", "name": "Test Doc"}]}}
        elif method == "resources/read":
            return {"result": {"contents": [{"uri": params.get("uri"), "text": "Hello MCP Resource"}]}}
        elif method == "prompts/list":
            return {"result": {"prompts": [{"name": "test_prompt", "description": "A test prompt"}]}}
        elif method == "prompts/get":
            return {"result": {"messages": [{"role": "user", "content": {"type": "text", "text": "Prompt text"}}]}}
        return None

    client._send_request_async = mock_send_request

    # Resources
    resources = await client.fetch_resources_async()
    assert len(resources) == 1
    assert resources[0]["name"] == "Test Doc"

    res_content = await client.read_resource_async("test://doc")
    assert res_content is not None
    assert res_content["contents"][0]["text"] == "Hello MCP Resource"

    # Prompts
    prompts = await client.fetch_prompts_async()
    assert len(prompts) == 1
    assert prompts[0]["name"] == "test_prompt"

    prompt_data = await client.get_prompt_async("test_prompt")
    assert prompt_data is not None
    assert prompt_data["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_sse_client_initialization_and_operations():
    """Test MCPSSEClient initialization, tools, resources, and prompts operations."""
    client = MCPSSEClient("remote_server", "https://example.com/sse", headers={"Authorization": "Bearer 123"}, cwd="/tmp/workspace")

    # Mock _http_client
    mock_http = AsyncMock()

    # Mock POST responses
    async def mock_post(url, json=None, headers=None):
        req = json or {}
        req_id = req.get("id")
        method = req.get("method")

        res_body = {}
        if method == "initialize":
            res_body = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "capabilities": {"resources": {}, "prompts": {}, "tools": {}},
                    "protocolVersion": "2024-11-05",
                },
            }
        elif method == "tools/list":
            res_body = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [{"name": "remote_tool"}]}}
        elif method == "tools/call":
            res_body = {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": "Tool Output"}]}}
        elif method == "resources/list":
            res_body = {"jsonrpc": "2.0", "id": req_id, "result": {"resources": [{"uri": "remote://file1"}]}}
        elif method == "resources/read":
            res_body = {"jsonrpc": "2.0", "id": req_id, "result": {"contents": [{"text": "Remote file content"}]}}
        elif method == "prompts/list":
            res_body = {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": [{"name": "remote_prompt"}]}}
        elif method == "prompts/get":
            res_body = {"jsonrpc": "2.0", "id": req_id, "result": {"messages": [{"role": "assistant", "content": "Hi"}]}}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json_dumps(res_body)
        mock_resp.json.return_value = res_body
        return mock_resp

    def json_dumps(d):
        return json.dumps(d)

    mock_http.post = mock_post
    client._http_client = mock_http

    # Initialize
    ok = await client._initialize_async()
    assert ok is True
    assert len(client.tools) == 1
    assert client.tools[0]["name"] == "remote_tool"
    assert len(client.resources) == 1
    assert len(client.prompts) == 1

    # Call tool
    tool_out = await client.call_tool_async("remote_tool", {})
    assert tool_out == "Tool Output"

    # Read resource
    res_out = await client.read_resource_async("remote://file1")
    assert res_out["contents"][0]["text"] == "Remote file content"

    # Get prompt
    prompt_out = await client.get_prompt_async("remote_prompt")
    assert prompt_out["messages"][0]["content"] == "Hi"

    # Test roots handler in SSE
    sent_roots = []
    async def mock_send_post_roots(payload):
        sent_roots.append(payload)
        return {"status": "ok"}
    client._send_post_async = mock_send_post_roots

    await client._handle_server_request_async({"jsonrpc": "2.0", "id": 99, "method": "roots/list"})
    assert len(sent_roots) == 1
    assert sent_roots[0]["id"] == 99
    assert sent_roots[0]["result"]["roots"][0]["uri"].startswith("file://")

    await client.stop_async()
    assert client._stopped is True


@pytest.mark.asyncio
async def test_mcp_manager_with_sse_config(tmp_path):
    """Test MCPManager loading SSE server configs and discovering resources and prompts."""
    config_dir = tmp_path / ".johnston"
    config_dir.mkdir(parents=True, exist_ok=True)
    mcp_file = config_dir / "mcp.json"

    config_data = {
        "mcpServers": {
            "remote_api": {
                "url": "https://mcp.remote.test/sse",
                "headers": {"X-Api-Key": "secret123"},
            },
            "local_srv": {
                "command": "python",
                "args": ["server.py"],
            },
        }
    }
    mcp_file.write_text(json.dumps(config_data), encoding="utf-8")

    mgr = MCPManager(project_dir=str(tmp_path))
    mgr.global_file = str(tmp_path / "global_mcp.json")
    mgr._global_config_ensured = True

    servers = mgr.load_servers()
    assert len(servers) == 2
    remote = next(s for s in servers if s["name"] == "remote_api")
    assert remote["type"] == "sse"
    assert remote["url"] == "https://mcp.remote.test/sse"
    assert remote["headers"] == {"X-Api-Key": "secret123"}

    # Mock client creation
    mock_sse_client = AsyncMock()
    mock_sse_client.start_async.return_value = True
    mock_sse_client.is_tools_stale = MagicMock(return_value=False)
    mock_sse_client.tools = [{"name": "remote_fn"}]
    mock_sse_client.resources = [{"uri": "mcp://remote_api/data", "name": "Remote Data"}]
    mock_sse_client.prompts = [{"name": "summarize", "description": "Summarize text"}]
    mock_sse_client.read_resource_async.return_value = {"contents": [{"text": "Sample Data Content"}]}
    mock_sse_client.get_prompt_async.return_value = {"messages": [{"role": "user", "content": "Do summary"}]}

    with patch.object(mgr, "_create_client", return_value=mock_sse_client):
        resources = await mgr.get_active_resources_async()
        assert len(resources) >= 1
        assert any(r["uri"] == "mcp://remote_api/data" for r in resources)

        # Read resource
        res_data = await mgr.read_resource_async("mcp://remote_api/data")
        assert res_data is not None
        assert res_data["contents"][0]["text"] == "Sample Data Content"

        # Prompts
        prompts = await mgr.get_active_prompts_async()
        assert len(prompts) >= 1
        assert any(p["name"] == "summarize" for p in prompts)

        prompt_data = await mgr.get_prompt_async("summarize")
        assert prompt_data is not None
        assert prompt_data["messages"][0]["content"] == "Do summary"


@pytest.mark.asyncio
async def test_read_tool_mcp_resource_integration():
    """Test ReadTool can read MCP resource URIs."""
    tool = ReadTool()

    mock_mgr = MagicMock()
    mock_mgr.read_resource_async = AsyncMock(
        return_value={"contents": [{"uri": "mcp://server/resource", "text": "MCP Resource Body"}]}
    )

    with patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mgr):
        result = await tool.execute({"path": "mcp://server/resource"})
        assert result.status == "done"
        assert "MCP Resource Body" in result.content
        assert result.display == "Resource mcp://server/resource"


@pytest.mark.asyncio
async def test_mcp_prompt_command_suggestions_and_dispatch():
    """Test MCP prompts appear in suggestions and execute via slash dispatch."""
    from widgets.app.command_provider import _build_command_suggestions
    from widgets.app.dispatch import handle_slash_command

    mock_client = MagicMock()
    mock_client.prompts = [{"name": "fast_review", "description": "Review code quickly"}]

    mock_mgr = MagicMock()
    mock_mgr.clients = {"demo": mock_client}
    mock_mgr.get_prompt_async = AsyncMock(
        return_value={"messages": [{"role": "user", "content": "Please review this code carefully"}]}
    )

    with patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mgr):
        suggestions = _build_command_suggestions()
        cmd_names = [s[0] for s in suggestions]
        assert "/fast_review" in cmd_names

        mock_app = MagicMock()
        handled = await handle_slash_command(mock_app, "/fast_review extra arg")
        assert handled is True
        mock_app.trigger_ai_response.assert_called_once()
        args = mock_app.trigger_ai_response.call_args[0]
        assert "Please review this code carefully" in args[0]

