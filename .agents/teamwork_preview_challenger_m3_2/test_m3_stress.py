import asyncio
import json
import os
import subprocess
import sys
import time

# Ensure project root is in sys.path
PROJECT_ROOT = "/Users/yegor/johnston"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.provider_manager import ProviderManager
from core.session_manager import SessionManager
from tools.ask_user import AskUserTool
from tools.bash import BashTool
from core.mcp_manager import MCPProcessClient


def test_provider_model_config_isolation():
    print("=== TEST 1: Provider Model Config Isolation ===")
    pm = ProviderManager()
    
    # Get initial git status of providers/
    git_before = subprocess.run(
        ["git", "status", "--porcelain", "providers/"],
        cwd=PROJECT_ROOT, capture_output=True, text=True
    ).stdout.strip()
    
    # Call set_provider_model
    pm.set_provider_model("opencode", "custom-model-test-123")
    
    # Check git status of providers/ again
    git_after = subprocess.run(
        ["git", "status", "--porcelain", "providers/"],
        cwd=PROJECT_ROOT, capture_output=True, text=True
    ).stdout.strip()
    
    print(f"Git status before: '{git_before}'")
    print(f"Git status after: '{git_after}'")
    
    assert git_after == "", f"Git status in providers/ is dirty after set_provider_model: {git_after}"
    print("PASS: Provider model config isolated, providers/ git working tree clean.")


def test_session_file_retention():
    print("\n=== TEST 2: Session File Retention (agent_history only) ===")
    sm = SessionManager(project_path=PROJECT_ROOT)
    
    test_session_id = "test_agent_history_only_session"
    filepath = os.path.join(sm.sessions_dir, f"{test_session_id}.json")
    
    session_data = {
        "id": test_session_id,
        "title": "Agent History Only Session",
        "created_at": time.time(),
        "updated_at": time.time(),
        "agent_history": [
            {"role": "user", "content": "Hello agent"},
            {"role": "assistant", "content": "Hello user"}
        ]
        # Note: ui_messages is intentionally missing
    }
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(session_data, f)
        
    try:
        sessions = sm.list_sessions()
        session_ids = [s["id"] for s in sessions]
        
        file_still_exists = os.path.exists(filepath)
        print(f"Session file exists after list_sessions(): {file_still_exists}")
        print(f"Session in list_sessions() output: {test_session_id in session_ids}")
        
        assert file_still_exists, "Session file containing only agent_history was unexpectedly deleted!"
        assert test_session_id in session_ids, "Session containing only agent_history was not returned in list_sessions()!"
        print("PASS: Session file retained and listed successfully.")
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)


async def test_ask_user_single_dict():
    print("\n=== TEST 3: AskUserTool Single Dict Input ===")
    ask_user_tool = AskUserTool()
    
    # Pass single dict under "questions"
    single_dict_args = {
        "questions": {
            "question_text": "Single dict test",
            "options": ["Option 1", "Option 2"]
        }
    }
    
    # Execute with app=None (headless)
    res = await ask_user_tool.execute(single_dict_args, app=None)
    print(f"AskUserTool execution result: {res}")
    
    assert isinstance(res, str), "Result is not a string!"
    assert "Error" in res or res == "Error: App instance not available or no valid questions provided.", (
        f"Unexpected output format: {res}"
    )
    print("PASS: AskUserTool handled single dict without crashing or raising exceptions.")


async def test_bash_headless_timeout():
    print("\n=== TEST 4: BashTool Timeout in Headless Mode ===")
    bash_tool = BashTool()
    
    start_time = time.time()
    # Command sleeping 12s via python process exceeds 10s wait_for timeout
    # (avoiding sleep regex optimization)
    res = await bash_tool.execute({"command": 'python3 -c "import time; time.sleep(12)"'}, app=None)
    elapsed = time.time() - start_time
    
    print(f"Elapsed time: {elapsed:.2f}s")
    print(f"BashTool result: {res}")
    
    assert elapsed >= 9.5 and elapsed <= 14.0, f"Execution time outside expected ~10s window: {elapsed}s"
    assert "Background Task ID:" in res, f"Expected background task notification, got: {res}"
    print("PASS: BashTool timed out and transitioned to background task gracefully without hanging.")


def test_mcp_stream_buffering():
    print("\n=== TEST 5: Non-blocking MCP Stream Buffering ===")
    dummy_server_code = """
import sys, json, time

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    req_id = req.get("id")
    method = req.get("method")
    
    if method == "initialize":
        res = {"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05"}}
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "tools/list":
        res = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [{"name": "test_tool"}]}}
        sys.stdout.write(json.dumps(res) + "\\n")
        sys.stdout.flush()
    elif method == "tools/call":
        # Send chunked response across two writes
        part1 = f'{{"jsonrpc": "2.0", "id": {req_id}, "res'
        part2 = 'ult": {"content": [{"type": "text", "text": "chunked_success"}]}}\\n'
        sys.stdout.write(part1)
        sys.stdout.flush()
        time.sleep(0.1)
        sys.stdout.write(part2)
        sys.stdout.flush()
"""
    client = MCPProcessClient("test_chunked", [sys.executable, "-c", dummy_server_code])
    started = client.start()
    assert started, "Failed to start dummy MCP process"
    
    try:
        res = client.call_tool("test_tool", {}, timeout=2.0)
        print(f"Call Tool Result: {res}")
        assert "chunked_success" in res, f"Expected chunked_success in output, got: {res}"
        print("PASS: MCP stream buffering correctly reassembled split JSON RPC frames.")
    finally:
        client.stop()


def main():
    test_provider_model_config_isolation()
    test_session_file_retention()
    asyncio.run(test_ask_user_single_dict())
    asyncio.run(test_bash_headless_timeout())
    test_mcp_stream_buffering()
    print("\nALL STRESS TESTS COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
