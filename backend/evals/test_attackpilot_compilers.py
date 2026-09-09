"""Local compiler integration checks, using only synthetic Solidity source."""
import json
import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.attackpilot import settings
from app.attackpilot.utils.solc import Solc, SolcJS
from app.attackpilot.utils.typed_ast import get_typed_ast_items

class CompilerTest(unittest.IsolatedAsyncioTestCase):
    async def test_namespaced_mcp_subprocess_handshake_and_local_tool(self):
        from app.attackpilot.mcp_tools.mcp_client import MCPClient
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"ATTACKPILOT_WORK_DIR": temp}):
            client = MCPClient(settings.MCP_SERVER_PATH)
            async with asyncio.timeout(30):
                try:
                    await client.connect()
                    catalog = await client.list_tools()
                    self.assertIn("update_understanding", {tool.name for tool in catalog.tools})
                    response = await client.call_tool("update_understanding", {"insight": "offline synthetic evidence"})
                    self.assertIn("Added", response)
                finally:
                    await client.close()

    async def test_native_js_and_ast_in_isolated_work_directory(self):
        binaries = list(settings.COMPILER_ROOT.glob("solc-linux-amd64-v0.8.9+*"))
        if not binaries or not (settings.PACKAGE_ROOT / "node_modules/solcv0.8.9").exists():
            self.skipTest("Run AttackPilot prepare --compilers and install its Node dependencies first")
        source = {"language": "Solidity", "sources": {"Example.sol": {"content": "pragma solidity ^0.8.9; contract Example { function value() external pure returns(uint) { return 42; } }"}}, "settings": {"outputSelection": {"*": {"*": ["*"], "": ["ast"]}}}}
        with tempfile.TemporaryDirectory(prefix="attackpilot compiler ") as temp:
            native_input = Path(temp) / "input with spaces.json"
            native_input.write_text(json.dumps(source))
            compiled = await Solc(str(binaries[0])).compile_json(str(native_input), "Example")
            self.assertTrue(compiled.bytecode, compiled.errors)
            script = Path(temp) / "compiler with spaces.js"
            script.write_text(settings.SOLCJS_CODE % ("v0.8.9", json.dumps(source)))
            js = await SolcJS(settings.NODE_PATH).compile_json(str(script), "Example")
            self.assertEqual(js.bytecode, compiled.bytecode)
            with patch("app.attackpilot.utils.tmpfile.TMP_FILE_DIR", temp):
                nodes, edges = await get_typed_ast_items(next(iter(compiled.ast.values())))
            self.assertGreater(len(nodes), 3)
            self.assertTrue(edges)

if __name__ == "__main__": unittest.main()
