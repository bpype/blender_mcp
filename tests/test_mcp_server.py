# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Tests for the MCP server configuration (prompts, data files, tool metadata).

Does not require Blender. Run with::

    python -m unittest tests.test_mcp_server -v
"""

__all__ = ()

import ast
import asyncio
import functools
import importlib
import os
import re
import sys
import types
import unittest
from unittest import mock
from typing import Any

import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Root of the repository.
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MCP_DIR = os.path.join(_REPO_DIR, "mcp")


def _import_blmcp_module() -> Any:
    """
    Import and return the local ``blmcp`` package.
    """
    if _MCP_DIR not in sys.path:
        sys.path.insert(0, _MCP_DIR)
    return importlib.import_module("blmcp")


def _load_prompts() -> dict[str, object]:
    """
    Return the parsed ``prompts.yml`` file.
    """
    path = os.path.join(_REPO_DIR, "mcp", "blmcp", "data", "prompts.yml")
    with open(path, encoding="utf-8") as fh:
        prompts = yaml.safe_load(fh)
    assert isinstance(prompts, dict)
    return prompts


@functools.lru_cache(maxsize=1)
def _source_tool_definitions() -> dict[str, dict[str, object]]:
    """
    Return source-defined MCP tool signatures keyed by tool name.
    """
    tools_dir = os.path.join(_REPO_DIR, "mcp", "blmcp", "tools")
    tool_defs: dict[str, dict[str, object]] = {}
    for filename in sorted(os.listdir(tools_dir)):
        if (
            not filename.endswith(".py") or
            filename == "__init__.py" or
            filename.endswith("_toolcode.py") or
            filename.startswith("_template_")
        ):
            continue
        path = os.path.join(tools_dir, filename)
        with open(path, encoding="utf-8") as fh:
            module = ast.parse(fh.read(), filename=path)
        for node in ast.walk(module):
            if not isinstance(node, ast.FunctionDef):
                continue
            is_tool = any(
                isinstance(deco, ast.Call) and
                isinstance(deco.func, ast.Attribute) and
                deco.func.attr == "tool"
                for deco in node.decorator_list
            )
            if not is_tool:
                continue
            arg_names = [arg.arg for arg in node.args.args]
            required_count = len(arg_names) - len(node.args.defaults)
            required_names = arg_names[:required_count]
            tool_defs[node.name] = {
                "args": arg_names,
                "required": required_names,
                "module": filename,
            }
    return tool_defs


def _prompt_data_paths(instructions: str) -> list[str]:
    """
    Return ``data/...`` paths referenced in backticks in *instructions*.
    """
    return re.findall(r"`(data/[^`]+)`", instructions)


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

    # Async is required because the MCP client SDK is async-only.
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
        cls._prompts = _load_prompts()

    def test_prompts_yml_valid_yaml(self) -> None:
        """
        Checks that ``prompts.yml`` loads as a dictionary.
        """
        self.assertIsInstance(self._prompts, dict)

    def test_prompts_yml_has_initial_instructions(self) -> None:
        """
        Checks that ``prompts.yml`` includes non-empty startup instructions.
        """
        self.assertIn("initial_instructions", self._prompts)
        self.assertIsInstance(self._prompts["initial_instructions"], str)
        self.assertTrue(len(self._prompts["initial_instructions"]) > 0)

    def test_api_directory_exists(self) -> None:
        """
        Checks that the bundled API docs folder exists and contains RST files.
        """
        api_dir = os.path.join(self._data_dir, "api")
        self.assertTrue(os.path.isdir(api_dir))
        rst_files = [f for f in os.listdir(api_dir) if f.endswith(".rst")]
        self.assertTrue(len(rst_files) > 0, "No RST files found in api/")

    def test_manual_directory_exists(self) -> None:
        """
        Checks that the bundled manual folder exists and contains RST files.
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

    def test_api_index_exists(self) -> None:
        """
        Checks that the bundled API docs include an ``index.rst`` entry point.
        """
        self.assertTrue(
            os.path.isfile(os.path.join(self._data_dir, "api", "index.rst"))
        )

    def test_manual_index_exists(self) -> None:
        """
        Checks that the bundled manual docs include an ``index.rst`` entry point.
        """
        manual_index = os.path.join(self._data_dir, "manual", "index.rst")
        if not os.path.isdir(os.path.dirname(manual_index)):
            self.skipTest("manual/ directory not present (run make update_manual)")
        self.assertTrue(os.path.isfile(manual_index))

    def test_prompt_referenced_data_paths_exist(self) -> None:
        """
        Checks that every ``data/...`` path mentioned in the prompt actually exists.
        """
        instructions = str(self._prompts["initial_instructions"])
        prompt_paths = _prompt_data_paths(instructions)
        self.assertIn("data/api/", prompt_paths)
        self.assertIn("data/manual/", prompt_paths)
        for prompt_path in prompt_paths:
            if not prompt_path.startswith("data/"):
                continue
            fs_path = os.path.join(self._data_dir, prompt_path.removeprefix("data/"))
            if prompt_path == "data/manual/" and not os.path.exists(fs_path):
                self.skipTest("manual/ directory not present (run make update_manual)")
            self.assertTrue(
                os.path.exists(fs_path),
                "Prompt references missing path: {:s}".format(prompt_path),
            )


# ---------------------------------------------------------------------------
# Server metadata tests.


class TestMCPServer(unittest.TestCase):
    """
    Test the MCP server's metadata, instructions, and tool configuration.
    """

    _server_info: Any
    _instructions: str
    _prompts: dict[str, object]
    _tools: list[dict[str, Any]]
    _tools_by_name: dict[str, dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        data = _query_server()
        cls._prompts = _load_prompts()
        cls._server_info = data["server_info"]
        cls._instructions = data["instructions"]
        cls._tools = data["tools"]
        cls._tools_by_name = {tool["name"]: tool for tool in cls._tools}

    # -----------------------------------------------------------------
    # Server identity.

    def test_server_name(self) -> None:
        """
        Checks that the server reports the expected public name.
        """
        self.assertEqual(self._server_info.name, "blender-mcp")

    # -----------------------------------------------------------------
    # Instructions.

    def test_instructions_not_empty(self) -> None:
        """
        Checks that the server returns some startup instructions.
        """
        self.assertTrue(len(self._instructions) > 0)

    def test_instructions_match_prompts_yml_exactly(self) -> None:
        """
        Checks that the server returns exactly the instructions from ``prompts.yml``.
        """
        self.assertEqual(
            self._instructions,
            str(self._prompts["initial_instructions"]),
        )

    def test_instructions_contains_key_sections(self) -> None:
        """
        Checks that the instructions still include the main guidance sections.
        """
        for section in (
            "Executing Code",
            "Scene & Data Structure",
            "Object Types & Creation",
            "Transformations & Coordinate Spaces",
        ):
            self.assertIn(
                section,
                self._instructions,
                "Missing section: {:s}".format(section),
            )

    def test_instructions_is_ascii(self) -> None:
        """
        Checks that the instructions stay ASCII-only.
        """
        try:
            self._instructions.encode("ascii")
        except UnicodeEncodeError as ex:
            self.fail("Non-ASCII character in instructions: {:s}".format(str(ex)))

    # -----------------------------------------------------------------
    # Tool metadata.

    def test_tool_count(self) -> None:
        """
        Checks that the server exposes at least one tool.
        """
        self.assertTrue(len(self._tools) > 0)

    def test_tool_names_unique(self) -> None:
        """
        Checks that every exposed tool has a unique name.
        """
        names = [t["name"] for t in self._tools]
        self.assertEqual(len(names), len(set(names)))

    def test_all_tools_have_descriptions(self) -> None:
        """
        Checks that every exposed tool has a non-empty description.
        """
        for tool in self._tools:
            self.assertTrue(
                len(tool["description"].strip()) > 0,
                "Tool {:s} has no description".format(tool["name"]),
            )

    def test_all_tools_have_input_schemas(self) -> None:
        """
        Checks that every exposed tool includes an input schema with a type.
        """
        for tool in self._tools:
            schema = tool["inputSchema"]
            self.assertIsInstance(
                schema,
                dict,
                "Tool {:s} has no inputSchema".format(tool["name"]),
            )
            self.assertIn(
                "type",
                schema,
                "Tool {:s} inputSchema missing 'type'".format(tool["name"]),
            )

    def test_server_tools_match_public_source_tool_functions(self) -> None:
        """
        Checks that the live server exposes exactly the public ``@mcp.tool()`` wrappers.
        """
        self.assertEqual(
            set(self._tools_by_name),
            set(_source_tool_definitions()),
        )

    def test_all_tool_schemas_are_object_schemas(self) -> None:
        """
        Checks that every tool schema looks like a normal object schema.
        """
        for tool in self._tools:
            schema = tool["inputSchema"]
            self.assertEqual(
                schema.get("type"),
                "object",
                "Tool {:s} inputSchema type is not 'object'".format(tool["name"]),
            )
            properties = schema.get("properties", {})
            self.assertIsInstance(
                properties,
                dict,
                "Tool {:s} inputSchema properties are not a dict".format(tool["name"]),
            )
            required = schema.get("required", [])
            self.assertIsInstance(
                required,
                list,
                "Tool {:s} inputSchema required is not a list".format(tool["name"]),
            )
            for key in required:
                self.assertIn(
                    key,
                    properties,
                    "Tool {:s} requires unknown property {:s}".format(
                        tool["name"], key
                    ),
                )

    def test_tool_schemas_match_source_signatures(self) -> None:
        """
        Checks that each schema matches the Python function signature that defines it.
        """
        tool_defs = _source_tool_definitions()
        for name, tool_def in tool_defs.items():
            schema = self._tools_by_name[name]["inputSchema"]
            self.assertEqual(
                set(schema.get("properties", {})),
                set(tool_def["args"]),
                "Tool {:s} properties do not match function arguments in {:s}".format(
                    name, tool_def["module"]
                ),
            )
            self.assertEqual(
                set(schema.get("required", [])),
                set(tool_def["required"]),
                "Tool {:s} required properties do not match function signature in {:s}".format(
                    name, tool_def["module"]
                ),
            )

    def test_cli_tools_require_blend_file(self) -> None:
        """
        Checks that every ``_for_cli`` tool requires a ``blend_file`` argument.
        """
        checked = 0
        for tool in self._tools:
            if not tool["name"].endswith("_for_cli"):
                continue
            schema = tool["inputSchema"]
            required = schema.get("required", [])
            self.assertIn(
                "blend_file",
                required,
                "Tool {:s} does not require 'blend_file'".format(tool["name"]),
            )
            checked += 1
        self.assertGreater(checked, 0, "No _for_cli tools found")

    def test_non_cli_tools_do_not_require_blend_file(self) -> None:
        """
        Checks that non-CLI tools do not require a ``blend_file`` argument.
        """
        checked = 0
        for tool in self._tools:
            if tool["name"].endswith("_for_cli"):
                continue
            self.assertNotIn(
                "blend_file",
                tool["inputSchema"].get("required", []),
                "Tool {:s} unexpectedly requires 'blend_file'".format(tool["name"]),
            )
            checked += 1
        self.assertGreater(checked, 0, "No non-CLI tools found")

    def test_cli_tools_have_non_cli_twins(self) -> None:
        """
        Checks that every ``_for_cli`` tool has a matching non-CLI version.
        """
        checked = 0
        for name in self._tools_by_name:
            if not name.endswith("_for_cli"):
                continue
            self.assertIn(
                name[:-8],
                self._tools_by_name,
                "Tool {:s} has no non-CLI twin".format(name),
            )
            checked += 1
        self.assertGreater(checked, 0, "No _for_cli tools found")


class TestMainConfiguration(unittest.TestCase):
    """
    Test server startup configuration without launching Blender.
    """

    _prompts: dict[str, object]

    @classmethod
    def setUpClass(cls) -> None:
        cls._prompts = _load_prompts()

    def test_main_uses_stdio_transport_by_default(self) -> None:
        """
        Checks that ``main()`` starts the server in ``stdio`` mode by default.
        """
        blmcp = _import_blmcp_module()
        mcp_instance = mock.Mock()
        with (
            mock.patch.object(sys, "argv", ["blmcp"]),
            mock.patch.object(
                blmcp, "FastMCP", return_value=mcp_instance
            ) as fastmcp_cls,
            mock.patch.object(blmcp.pkgutil, "iter_modules", return_value=[]),
        ):
            result = blmcp.main()
        self.assertEqual(result, 0)
        fastmcp_cls.assert_called_once_with(
            "blender-mcp",
            instructions=str(self._prompts["initial_instructions"]),
        )
        mcp_instance.run.assert_called_once_with(transport="stdio")

    def test_main_discovers_and_registers_only_public_tool_modules(self) -> None:
        """
        Checks that startup imports only public tool modules and registers them.
        """
        blmcp = _import_blmcp_module()
        mcp_instance = mock.Mock()
        gamma_mod = mock.Mock()
        no_register_mod = object()

        with (
            mock.patch.object(sys, "argv", ["blmcp"]),
            mock.patch.object(blmcp, "FastMCP", return_value=mcp_instance),
            mock.patch.object(
                blmcp.pkgutil,
                "iter_modules",
                return_value=[
                    (None, "alpha", False),
                    (None, "beta_toolcode", False),
                    (None, "_template_hidden", False),
                    (None, "gamma", False),
                ],
            ),
            mock.patch.object(
                blmcp.importlib,
                "import_module",
                side_effect=[no_register_mod, gamma_mod],
            ) as import_module,
        ):
            result = blmcp.main()

        self.assertEqual(result, 0)
        self.assertEqual(
            import_module.call_args_list,
            [
                mock.call("blmcp.tools.alpha"),
                mock.call("blmcp.tools.gamma"),
            ],
        )
        gamma_mod.register.assert_called_once_with(mcp_instance)
        mcp_instance.run.assert_called_once_with(transport="stdio")

    def test_main_skips_modules_without_register(self) -> None:
        """
        Checks that startup ignores tool modules that do not define ``register()``.
        """
        blmcp = _import_blmcp_module()
        mcp_instance = mock.Mock()
        no_register_mod = object()

        with (
            mock.patch.object(sys, "argv", ["blmcp"]),
            mock.patch.object(blmcp, "FastMCP", return_value=mcp_instance),
            mock.patch.object(
                blmcp.pkgutil,
                "iter_modules",
                return_value=[(None, "alpha", False)],
            ),
            mock.patch.object(
                blmcp.importlib,
                "import_module",
                return_value=no_register_mod,
            ) as import_module,
        ):
            result = blmcp.main()

        self.assertEqual(result, 0)
        import_module.assert_called_once_with("blmcp.tools.alpha")
        mcp_instance.run.assert_called_once_with(transport="stdio")

    def test_main_configures_http_transport_settings_and_cors(self) -> None:
        """
        Checks that HTTP mode sets the expected server settings and CORS wrapper.
        """
        # NOTE: this is fairly closely tied with HTTP which only tests the few things
        # we have supported for LLAMA.C++.

        blmcp = _import_blmcp_module()

        class FakeTransportSecuritySettings:
            def __init__(self, **kwargs: object):
                self.kwargs = kwargs

        class FakeCORSMiddleware:
            pass

        class FakeApp:
            def __init__(self) -> None:
                self.middleware_calls: list[tuple[object, dict[str, object]]] = []

            def add_middleware(self, middleware: object, **kwargs: object) -> None:
                self.middleware_calls.append((middleware, kwargs))

        fake_app = FakeApp()
        mcp_instance = mock.Mock()
        mcp_instance.settings = types.SimpleNamespace()
        mcp_instance.streamable_http_app = mock.Mock(return_value=fake_app)

        fastmcp_server_mod = types.ModuleType("mcp.server.fastmcp.server")
        fastmcp_server_mod.TransportSecuritySettings = FakeTransportSecuritySettings
        starlette_apps_mod = types.ModuleType("starlette.applications")
        starlette_apps_mod.Starlette = object
        starlette_cors_mod = types.ModuleType("starlette.middleware.cors")
        starlette_cors_mod.CORSMiddleware = FakeCORSMiddleware

        with (
            mock.patch.object(
                sys,
                "argv",
                ["blmcp", "--transport", "http", "--host", "0.0.0.0", "--port", "8123"],
            ),
            mock.patch.object(blmcp, "FastMCP", return_value=mcp_instance),
            mock.patch.object(blmcp.pkgutil, "iter_modules", return_value=[]),
            mock.patch.dict(
                sys.modules,
                {
                    "mcp.server.fastmcp.server": fastmcp_server_mod,
                    "starlette.applications": starlette_apps_mod,
                    "starlette.middleware.cors": starlette_cors_mod,
                },
            ),
        ):
            result = blmcp.main()

        self.assertEqual(result, 0)
        self.assertEqual(mcp_instance.settings.host, "0.0.0.0")
        self.assertEqual(mcp_instance.settings.port, 8123)
        self.assertEqual(mcp_instance.settings.streamable_http_path, "/")
        self.assertTrue(mcp_instance.settings.stateless_http)
        self.assertIsInstance(
            mcp_instance.settings.transport_security,
            FakeTransportSecuritySettings,
        )
        self.assertEqual(
            mcp_instance.settings.transport_security.kwargs,
            {"enable_dns_rebinding_protection": False},
        )
        mcp_instance.run.assert_called_once_with(transport="streamable-http")

        app = mcp_instance.streamable_http_app()
        self.assertIs(app, fake_app)
        self.assertEqual(
            fake_app.middleware_calls,
            [
                (
                    FakeCORSMiddleware,
                    {
                        "allow_origins": ["*"],
                        "allow_methods": ["*"],
                        "allow_headers": ["*"],
                    },
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
