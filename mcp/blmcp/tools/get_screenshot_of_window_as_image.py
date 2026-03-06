# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

__all__ = (
    "register",
)

import base64

from blmcp.tools_helpers import (
    toolcode_format_call,
    toolcode_load_from_filepath,
    toolcode_wrap_with_calling_convention,
)
from blmcp.tools_helpers.connection import send_code
from mcp.server.fastmcp import FastMCP, Image  # pylint: disable=import-error,no-name-in-module

_TOOL_CALL = toolcode_wrap_with_calling_convention(toolcode_load_from_filepath(__file__))


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def get_screenshot_of_window_as_image() -> Image:
        """
        Take a screenshot of the entire Blender window and return it as a PNG image.
        """
        response = send_code(toolcode_format_call(_TOOL_CALL, None))
        if response.get("status") != "ok":
            raise RuntimeError(str(response.get("message", "Unknown error")))
        result = response["result"]
        assert isinstance(result, dict)
        return Image(data=base64.b64decode(str(result["image_base64"])), format="png")
