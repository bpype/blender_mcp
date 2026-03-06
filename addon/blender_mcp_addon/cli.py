# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
CLI command handler for running the MCP server in background mode.

Started via ``blender --background file.blend --command blender_mcp``.
"""

__all__ = (
    "cli_execute",
)

import argparse

from . import execute_blocking
from . import mcp_to_blender_server as server

_DEFAULT_HOST = "localhost"
_DEFAULT_PORT = 9876


def cli_execute(argv: list[str]) -> int:
    """
    Block and serve MCP requests until interrupted.
    """
    parser = argparse.ArgumentParser(
        prog="blender_mcp",
        description=(
            "Start the Blender MCP server. "
            "Intended for background mode but also works with a GUI, "
            "although Blender will be unresponsive to user input until the server exits."
        ),
    )
    parser.add_argument("--host", default=_DEFAULT_HOST, help="Host to bind to.")
    parser.add_argument(
        "--port", type=int, default=_DEFAULT_PORT,
        help="Port to listen on.",
    )
    args = parser.parse_args(argv)

    try:
        server.start(args.host, args.port)
    except RuntimeError as ex:
        print("Error: {:s}".format(str(ex)))
        return 1

    print("MCP server started on {:s}:{:d}, press Ctrl+C to exit.".format(args.host, args.port))

    try:
        execute_blocking.run()
    finally:
        server.stop()
    return 0
