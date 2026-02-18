# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
MCP server for Blender.
"""

__all__ = (
    "main",
)

import importlib
import os
import pkgutil

import yaml
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module


def main() -> int:
    # Load prompts.
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    with open(os.path.join(data_dir, "prompts.yml"), encoding="utf-8") as fh:
        prompts = yaml.safe_load(fh)

    mcp = FastMCP("blender-mcp", instructions=str(prompts["initial_instructions"]))

    # Auto-discover and register all tools (they are never un-registered).
    import blmcp.tools as tools_pkg

    for _importer, modname, _ispkg in pkgutil.iter_modules(tools_pkg.__path__):
        if modname.endswith("_toolcode"):
            continue
        mod = importlib.import_module("blmcp.tools.{:s}".format(modname))
        if hasattr(mod, "register"):
            mod.register(mcp)

    mcp.run()
    return 0
