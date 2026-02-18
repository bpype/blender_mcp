# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for the MCP server configuration (prompts, data files, tool metadata).

Does not require Blender. Run with::

    python -m unittest tests.test_mcp_server -v
"""

__all__ = ()

import asyncio
import os
import sys
import unittest
from typing import Any

import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Root of the repository.
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _server_env() -> dict[str, str]:
    """
    Return an environment dict for the MCP server subprocess.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.join(_REPO_DIR, "mcp")
    return env


def _query_server() -> dict[str, Any]:
    """
    Launch the MCP server, initialize, fetch metadata, and return it all.
    """
    async def _run() -> dict[str, Any]:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "blmcp"],
            env=_server_env(),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init_result = await session.initialize()
                tools_result = await session.list_tools()
                return {
                    "server_info": init_result.serverInfo,
                    "instructions": init_result.instructions or "",
                    "tools": [
                        {
                            "name": t.name,
                            "description": t.description or "",
                            "inputSchema": t.inputSchema,
                        }
                        for t in tools_result.tools
                    ],
                }

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# Data file tests (no server needed).

class TestDataFiles(unittest.TestCase):
    """
    Verify bundled data files are present and well-formed.
    """

    _data_dir: str
    _prompts: dict[str, object]

    @classmethod
    def setUpClass(cls) -> None:
        cls._data_dir = os.path.join(_REPO_DIR, "mcp", "blmcp", "data")
        path = os.path.join(cls._data_dir, "prompts.yml")
        with open(path, encoding="utf-8") as fh:
            cls._prompts = yaml.safe_load(fh)

    def test_prompts_yml_valid_yaml(self) -> None:
        """
        ``prompts.yml`` must parse as a dict.
        """
        self.assertIsInstance(self._prompts, dict)

    def test_prompts_yml_has_initial_instructions(self) -> None:
        """
        ``prompts.yml`` must contain the ``initial_instructions`` key.
        """
        self.assertIn("initial_instructions", self._prompts)
        self.assertIsInstance(self._prompts["initial_instructions"], str)
        self.assertTrue(len(self._prompts["initial_instructions"]) > 0)

    def test_api_directory_exists(self) -> None:
        """
        The ``api/`` directory must exist and contain RST files.
        """
        api_dir = os.path.join(self._data_dir, "api")
        self.assertTrue(os.path.isdir(api_dir))
        rst_files = [f for f in os.listdir(api_dir) if f.endswith(".rst")]
        self.assertTrue(len(rst_files) > 0, "No RST files found in api/")

    def test_manual_directory_exists(self) -> None:
        """
        The ``manual/`` directory must exist and contain RST files.
        """
        manual_dir = os.path.join(self._data_dir, "manual")
        if not os.path.isdir(manual_dir):
            self.skipTest("manual/ directory not present (run make update_manual)")
        has_rst = False
        for _dirpath, _dirnames, filenames in os.walk(manual_dir):
            if any(f.endswith(".rst") for f in filenames):
                has_rst = True
                break
        self.assertTrue(has_rst, "No RST files found in manual/")


# ---------------------------------------------------------------------------
# Server metadata tests.

class TestMCPServer(unittest.TestCase):
    """
    Test the MCP server's metadata, instructions, and tool configuration.
    """

    _server_info: Any
    _instructions: str
    _tools: list[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        data = _query_server()
        cls._server_info = data["server_info"]
        cls._instructions = data["instructions"]
        cls._tools = data["tools"]

    # -----------------------------------------------------------------
    # Server identity.

    def test_server_name(self) -> None:
        """
        The server must identify itself as ``blender-mcp``.
        """
        self.assertEqual(self._server_info.name, "blender-mcp")

    # -----------------------------------------------------------------
    # Instructions.

    def test_instructions_not_empty(self) -> None:
        """
        The server must return non-empty instructions.
        """
        self.assertTrue(len(self._instructions) > 0)

    def test_instructions_contains_key_sections(self) -> None:
        """
        The instructions should contain the key section headings from ``prompts.yml``.
        """
        for section in (
            "Executing Code",
            "Scene & Data Structure",
            "Object Types & Creation",
            "Transformations & Coordinate Spaces",
        ):
            self.assertIn(
                section, self._instructions,
                "Missing section: {:s}".format(section),
            )

    def test_instructions_is_ascii(self) -> None:
        """
        The instructions should contain only ASCII characters.
        """
        try:
            self._instructions.encode("ascii")
        except UnicodeEncodeError as ex:
            self.fail("Non-ASCII character in instructions: {:s}".format(str(ex)))

    # -----------------------------------------------------------------
    # Tool metadata.

    def test_tool_count(self) -> None:
        """
        The server must expose at least one tool.
        """
        self.assertTrue(len(self._tools) > 0)

    def test_tool_names_unique(self) -> None:
        """
        All tool names must be unique.
        """
        names = [t["name"] for t in self._tools]
        self.assertEqual(len(names), len(set(names)))

    def test_all_tools_have_descriptions(self) -> None:
        """
        Every tool must have a non-empty description.
        """
        for tool in self._tools:
            self.assertTrue(
                len(tool["description"].strip()) > 0,
                "Tool {:s} has no description".format(tool["name"]),
            )

    def test_all_tools_have_input_schemas(self) -> None:
        """
        Every tool must define an ``inputSchema`` with a ``type`` field.
        """
        for tool in self._tools:
            schema = tool["inputSchema"]
            self.assertIsInstance(
                schema, dict,
                "Tool {:s} has no inputSchema".format(tool["name"]),
            )
            self.assertIn(
                "type", schema,
                "Tool {:s} inputSchema missing 'type'".format(tool["name"]),
            )

    def test_cli_tools_require_blend_file(self) -> None:
        """
        Every ``_for_cli`` tool must require a ``blend_file`` parameter.
        """
        checked = 0
        for tool in self._tools:
            if not tool["name"].endswith("_for_cli"):
                continue
            schema = tool["inputSchema"]
            required = schema.get("required", [])
            self.assertIn(
                "blend_file", required,
                "Tool {:s} does not require 'blend_file'".format(tool["name"]),
            )
            checked += 1
        self.assertGreater(checked, 0, "No _for_cli tools found")


if __name__ == "__main__":
    unittest.main()
