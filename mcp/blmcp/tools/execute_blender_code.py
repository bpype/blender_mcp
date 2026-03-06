# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

__all__ = (
    "register",
)

import json

from blmcp.tools_helpers.blender_cli import run_blender_cli, synced_blend_for_cli
from blmcp.tools_helpers.connection import send_code
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def execute_blender_code(code: str) -> str:
        """
        Execute Python code in the connected Blender instance.

        The code runs in Blender's Python environment with full access to ``bpy``.
        To return data, assign a JSON-serialisable dict to a variable named ``result``.
        """
        return json.dumps(send_code(code))

    @mcp.tool()
    def execute_blender_code_for_cli(blend_file: str, code: str) -> str:
        """
        Execute Python code in a background Blender process.

        Opens *blend_file* with ``blender --background`` and runs *code*.
        Assign a dict to ``result`` to return data.
        """
        with synced_blend_for_cli(blend_file) as synced_path:
            value = run_blender_cli(synced_path, code)
            assert isinstance(value, dict), "Expected dict from `run_blender_cli`, got {!r}".format(type(value))
            return json.dumps(value)
