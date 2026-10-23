import json
import asyncio
import sys
import os
from contextlib import AsyncExitStack
from typing import Optional, Dict, Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPToolError(RuntimeError):
    """A failed transport/tool response cannot be used as execution evidence."""

    def __init__(self, tool_name: str, reason_code: str):
        self.tool_name = tool_name
        self.reason_code = reason_code
        # Do not include remote error bodies, arguments, or transport URLs.
        super().__init__(f"MCP tool failed ({reason_code})")


class MCPClient:
    def __init__(self, server_script_path: str):
        python_executable = sys.executable
        from app.attackpilot.settings import BACKEND_ROOT
        project_root = str(BACKEND_ROOT)
        env = os.environ.copy()

        current_pythonpath = env.get("PYTHONPATH", "")
        if current_pythonpath:
            env["PYTHONPATH"] = f"{project_root}{os.pathsep}{current_pythonpath}"
        else:
            env["PYTHONPATH"] = project_root

        self.server_params = StdioServerParameters(
            command=python_executable,
            args=["-m", "app.attackpilot.mcp_tools.mcp_server"],
            env=env
        )

        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self._read = None
        self._write = None

    async def connect(self):
        try:
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(self.server_params))
            self._read, self._write = stdio_transport
            self.session = await self.exit_stack.enter_async_context(ClientSession(self._read, self._write))
            await self.session.initialize()
            print("✅ MCP Client Connected.")
        except Exception as e:
            print(f"❌ MCP Connection Failed: {e}")
            print(f"   Command: {self.server_params.command}")
            print(f"   Args: {self.server_params.args}")
            raise e

    async def list_tools(self):
        if not self.session:
            raise RuntimeError("Client not connected")
        return await self.session.list_tools()

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str | Dict:
        if not self.session:
            raise MCPToolError(tool_name, "not_connected")

        try:
            result = await self.session.call_tool(tool_name, arguments)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise MCPToolError(tool_name, "transport_error") from None

        if getattr(result, "isError", False) is True:
            raise MCPToolError(tool_name, "remote_error")
        content = getattr(result, "content", None)
        if not isinstance(content, list) or not content:
            raise MCPToolError(tool_name, "empty_content")
        if any(getattr(item, "type", None) != "text" or not isinstance(getattr(item, "text", None), str)
               for item in content):
            raise MCPToolError(tool_name, "unsupported_content")
        text_response = "\n".join(item.text for item in content)
        if not text_response.strip():
            raise MCPToolError(tool_name, "empty_content")
        try:
            return json.loads(text_response)
        except json.JSONDecodeError:
            return text_response

    async def close(self):
        await self.exit_stack.aclose()
        print("🔌 MCP Client Closed.")
